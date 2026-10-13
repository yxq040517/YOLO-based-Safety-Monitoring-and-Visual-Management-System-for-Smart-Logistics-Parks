import asyncio
import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from urllib.parse import quote
from fastapi import (
    FastAPI,
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from sqlalchemy import Integer, cast, select, func, or_, true, update
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool
from . import config
from .config import STORAGE, MAX_UPLOAD, MAX_PENDING, MAX_CAMERAS, VERSION, safe_path
from .db import (
    Session,
    session,
    initialize,
    lock_control,
    User,
    Job,
    Camera,
    SafetyEvent,
    settings,
    utcnow,
    iso,
)
from .schemas import (
    Setup,
    Login,
    UserCreate,
    UserPatch,
    CameraCreate,
    CameraPatch,
    EventPatch,
    Settings,
    LiveHello,
)
from .security import (
    current_user,
    operator,
    admin,
    authenticate,
    public_user,
    hasher,
    verify,
    token,
    limit_login,
    initialize_secret,
    media_ticket,
    authenticate_media_ticket,
    MEDIA_TICKET_SECONDS,
)
from .serializers import job_data, jobs_data, event_data, camera_data
from .tasks import model_status, get_detector, request_cancelled
from .runtime import runtime, LiveRecorder, read_live_preview
from .media import validate_upload, decode_jpeg, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS


@asynccontextmanager
async def lifespan(app):
    initialize()
    initialize_secret()
    runtime.start()
    try:
        yield
    finally:
        await run_in_threadpool(runtime.close)


app = FastAPI(title="物流智安 API", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        v.strip()
        for v in os.environ.get(
            "CORS_ORIGINS", "http://localhost:15173,http://127.0.0.1:15173"
        ).split(",")
        if v.strip()
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],
)


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = MAX_UPLOAD + 1024 * 1024 if scope["path"] == "/api/jobs" else 128 * 1024
        headers = dict(scope["headers"])
        if scope["path"] == "/api/jobs" and scope["method"] == "POST":
            authorization = headers.get(b"authorization", b"").decode("latin-1")
            scheme, _, credential = authorization.partition(" ")
            try:
                if scheme.lower() != "bearer" or not credential:
                    raise HTTPException(401, "请先登录")
                user = await run_in_threadpool(authenticate, credential)
                if user.role not in {"admin", "operator"}:
                    raise HTTPException(403, "仅管理员和操作员可上传检测文件")
            except HTTPException as exc:
                return await JSONResponse(
                    {"detail": exc.detail}, status_code=exc.status_code
                )(scope, receive, send)
        try:
            content_length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            return await JSONResponse({"detail": "无效的请求长度"}, status_code=400)(
                scope, receive, send
            )
        if content_length > limit:
            return await JSONResponse(
                {"detail": "请求体超过允许大小"}, status_code=413
            )(scope, receive, send)
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(413, "请求体超过允许大小")
            return message

        await self.app(scope, bounded_receive, send)


app.add_middleware(BodyLimitMiddleware)
api = APIRouter(prefix="/api")


@api.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@api.get("/auth/status")
def auth_status():
    with Session() as db:
        return {"initialized": bool(db.scalar(select(func.count()).select_from(User)))}


@api.post("/auth/setup", status_code=201)
def setup(body: Setup, request: Request):
    limit_login(request)
    hashed = hasher.hash(body.password)
    with session() as db:
        control = lock_control(db, 1)
        if control.value.get("initialized") or db.scalar(
            select(func.count()).select_from(User)
        ):
            raise HTTPException(409, "系统已初始化，请使用已有管理员账号登录")
        user = User(
            username=body.username,
            display_name=body.display_name,
            password_hash=hashed,
            role="admin",
        )
        db.add(user)
        db.flush()
        control.value = {"initialized": True}
        result = {"access_token": token(user), "user": public_user(user)}
    return result


@api.post("/auth/login")
def login(body: Login, request: Request):
    limit_login(request)
    with session() as db:
        user = db.scalar(select(User).where(User.username == body.username))
        valid = verify(body.password, user.password_hash if user else None)
        if not user or not valid:
            raise HTTPException(401, "用户名或密码错误")
        if hasher.check_needs_rehash(user.password_hash):
            user.password_hash = hasher.hash(body.password)
        return {"access_token": token(user), "user": public_user(user)}


@api.get("/auth/me")
def me(user=Depends(current_user)):
    return public_user(user)


@api.get("/model")
def model(user=Depends(current_user)):
    try:
        status = model_status()
    except Exception as exc:
        status = {
            "ready": False,
            "weights": None,
            "device": "unavailable",
            "classes": [],
            "message": f"模型加载失败：{str(exc)[:500]}",
        }
    training = STORAGE / "training" / "status.json"
    try:
        status["training"] = (
            json.loads(training.read_text(encoding="utf-8"))
            if training.is_file()
            else None
        )
    except (OSError, json.JSONDecodeError):
        status["training"] = {
            "status": "unreadable",
            "message": "训练状态正在更新或文件损坏，请稍后刷新",
        }
    return status


def require_model():
    try:
        status = model_status()
    except Exception as exc:
        raise HTTPException(503, f"模型服务不可用：{str(exc)[:500]}")
    if not status.get("ready"):
        raise HTTPException(
            503, status.get("message") or "训练模型尚未就绪，请先完成训练"
        )


def get_job(db, job_id):
    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "检测任务不存在")
    return job


def persist_uploaded_job(job_id, owner_id, kind, filename, confidence, class_ids, destination):
    with session() as db:
        lock_control(db, 1)
        pending = db.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status.in_(["queued", "running"]), Job.kind != "camera")
        )
        if pending >= MAX_PENDING:
            raise HTTPException(429, "检测队列已满，请等待已有任务完成")
        job = Job(
            id=job_id,
            owner_id=owner_id,
            kind=kind,
            filename=filename,
            status="queued",
            confidence=confidence,
            classes=class_ids,
            source_path=str(destination),
        )
        db.add(job)
        db.flush()
        return job_data(job)


def cleanup_unpersisted_upload(job_id, destination):
    with Session() as db:
        persisted = db.get(Job, job_id) is not None
    if not persisted:
        destination.unlink(missing_ok=True)


def create_browser_job(job_id, owner_id, confidence, classes):
    with session() as db:
        db.add(
            Job(
                id=job_id,
                owner_id=owner_id,
                kind="camera",
                filename="浏览器摄像头",
                status="running",
                confidence=confidence,
                classes=classes,
            )
        )


@api.post("/jobs", status_code=201)
async def create_job(
    file: UploadFile = File(...),
    confidence: float = Form(0.35, ge=0.05, le=1),
    classes: str | None = Form(None),
    user=Depends(operator),
):
    await run_in_threadpool(require_model)
    try:
        class_ids = json.loads(classes) if classes else []
        if (
            not isinstance(class_ids, list)
            or any(type(c) is not int or c < 0 or c >= 20 for c in class_ids)
            or len(set(class_ids)) != len(class_ids)
        ):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, "classes 必须是由 0 至 19 组成的不重复整数 JSON 数组")
    filename = (file.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1]
    if len(filename) > 255:
        raise HTTPException(422, "文件名过长")
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        raise HTTPException(415, "不支持此文件格式")
    job_id = str(uuid.uuid4())
    destination = STORAGE / "uploads" / (job_id + suffix)
    size = 0
    try:
        with destination.open("xb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(
                        413, f"文件不得超过 {MAX_UPLOAD // (1024 * 1024)}MB"
                    )
                await run_in_threadpool(output.write, chunk)
        if size == 0:
            raise HTTPException(422, "不能上传空文件")
        try:
            kind = await run_in_threadpool(
                validate_upload,
                destination,
                file.content_type or "application/octet-stream",
            )
        except ValueError as exc:
            raise HTTPException(415, str(exc))
        result = await run_in_threadpool(
            persist_uploaded_job,
            job_id,
            user.id,
            kind,
            filename,
            confidence,
            class_ids,
            destination,
        )
        try:
            await run_in_threadpool(runtime.submit, job_id)
        except Exception:
            from .tasks import finish_job

            await run_in_threadpool(
                finish_job,
                job_id,
                "failed",
                "无法提交检测任务，请检查本地执行器或 Redis/Celery 服务",
            )
            raise HTTPException(
                503, "检测执行器不可用，任务已记录为失败，请检查服务后重试"
            )
        return result
    except BaseException as exc:
        await run_in_threadpool(cleanup_unpersisted_upload, job_id, destination)
        if isinstance(exc, OSError):
            raise HTTPException(
                507, "文件保存失败，请检查服务器磁盘空间与 storage 目录权限"
            ) from exc
        raise
    finally:
        await file.close()


@api.get("/jobs")
def jobs(
    kind: str | None = None,
    status: str | None = None,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user=Depends(current_user),
):
    query = select(Job)
    if kind:
        if kind not in {"image", "video", "camera"}:
            raise HTTPException(422, "无效的任务类型")
        query = query.where(Job.kind == kind)
    if status:
        if status not in {"queued", "running", "completed", "failed", "cancelled"}:
            raise HTTPException(422, "无效的任务状态")
        query = query.where(Job.status == status)
    if q:
        query = query.where(Job.filename.contains(q, autoescape=True))
    with Session() as db:
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        items = db.scalars(
            query.order_by(Job.created_at.desc(), Job.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return dict(
            items=jobs_data(items, db),
            total=total,
            page=page,
            page_size=page_size,
        )


@api.get("/jobs/{job_id}")
def job_detail(job_id: str, user=Depends(current_user)):
    with Session() as db:
        return job_data(get_job(db, job_id), db)


@api.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user=Depends(operator)):
    with session() as db:
        db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(["queued", "running"]))
            .values(cancel_requested=True)
            .execution_options(synchronize_session=False)
        )
        job = get_job(db, job_id)
        db.refresh(job)
        return job_data(job, db)


@api.get("/jobs/{job_id}/export")
def export_job(job_id: str, user=Depends(current_user)):
    with Session() as db:
        job = get_job(db, job_id)
        if job.status not in {"completed", "failed", "cancelled"}:
            raise HTTPException(409, "任务尚未结束，请完成或取消后导出")
        payload = job_data(job, db)
        payload["events"] = [
            event_data(e)
            for e in db.scalars(
                select(SafetyEvent)
                .where(SafetyEvent.job_id == job_id)
                .order_by(SafetyEvent.created_at)
            )
        ]
        payload["events_truncated"] = False
    frame_log = STORAGE / "results" / job_id / "frames.jsonl"

    def stream():
        yield (
            '{"job":'
            + json.dumps(payload, ensure_ascii=False, allow_nan=False)
            + ',"frame_records":['
        )
        if frame_log.is_file():
            with frame_log.open("r", encoding="utf-8") as handle:
                first = True
                for line in handle:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not first:
                        yield ","
                    first = False
                    yield json.dumps(record, ensure_ascii=False, allow_nan=False)
        yield "]}"

    return StreamingResponse(
        stream(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="job-{job_id}.json"'},
    )


def resolve_media(relative_path: str):
    try:
        path = safe_path(relative_path)
    except ValueError:
        raise HTTPException(404, "媒体不存在")
    if (
        not path.is_file()
        or path.suffix.lower() not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    ):
        raise HTTPException(404, "媒体不存在")
    with Session() as db:
        owned = db.execute(
            select(Job.id, Job.kind, Job.preview_path)
            .where(
                or_(
                    Job.source_path == str(path),
                    Job.result_path == str(path),
                    Job.preview_path == str(path),
                )
            )
            .limit(1)
        ).first()
        live_preview = (
            owned is not None
            and owned.kind == "camera"
            and owned.preview_path == str(path)
        )
        if not owned:
            owned = db.scalar(
                select(SafetyEvent.id)
                .where(SafetyEvent.snapshot_path == str(path))
                .limit(1)
            )
        if not owned:
            raise HTTPException(404, "媒体不存在或无权访问")
    return path, live_preview


def serve_media(relative_path: str):
    path, live_preview = resolve_media(relative_path)
    headers = {
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    }
    if live_preview:
        try:
            data = read_live_preview(path)
        except FileNotFoundError:
            raise HTTPException(404, "媒体不存在")
        except ValueError as exc:
            raise HTTPException(413, str(exc)) from exc
        return Response(data, media_type="image/jpeg", headers=headers)
    return FileResponse(path, headers=headers)


@api.get("/media-access")
def media_access(request: Request, relative_path: str = Query(..., max_length=1024), user=Depends(current_user)):
    path, _ = resolve_media(relative_path)
    if path.suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(422, "仅视频需要播放地址")
    canonical = path.relative_to(config.STORAGE).as_posix()
    signed = media_ticket(user, canonical)
    playback_url = "/api/media-play/" + quote(canonical, safe="/")
    response = JSONResponse(
        {"url": playback_url},
        headers={"Cache-Control": "no-store"},
    )
    response.set_cookie(
        "media_ticket",
        signed,
        max_age=MEDIA_TICKET_SECONDS,
        path=playback_url,
        httponly=True,
        secure=(request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"),
        samesite="strict",
    )
    return response


@api.get("/media-play/{relative_path:path}")
def media_play(relative_path: str, request: Request):
    ticket = request.cookies.get("media_ticket")
    if not ticket:
        raise HTTPException(401, "播放地址已过期，请重新打开视频")
    authenticate_media_ticket(ticket, relative_path)
    if Path(relative_path).suffix.lower() not in VIDEO_EXTENSIONS:
        raise HTTPException(404, "媒体不存在")
    return serve_media(relative_path)


@api.get("/media/{relative_path:path}")
def media(relative_path: str, user=Depends(current_user)):
    return serve_media(relative_path)


@api.get("/events")
def events(
    status: str | None = None,
    rule_type: str | None = None,
    severity: str | None = None,
    job_id: str | None = None,
    q: str = Query("", max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    open_only: bool = False,
    user=Depends(current_user),
):
    query = select(SafetyEvent)
    if open_only:
        query = query.where(SafetyEvent.status.in_(["pending", "confirmed", "processing"]))
    for column, value, allowed in (
        (
            SafetyEvent.status,
            status,
            {"pending", "confirmed", "false_positive", "processing", "closed"},
        ),
        (
            SafetyEvent.rule_type,
            rule_type,
            {"fire", "smoke", "ppe", "intrusion", "proximity"},
        ),
        (SafetyEvent.severity, severity, {"high", "medium", "low"}),
    ):
        if value:
            if value not in allowed:
                raise HTTPException(422, "无效的事件筛选条件")
            query = query.where(column == value)
    if job_id:
        query = query.where(SafetyEvent.job_id == job_id)
    if q:
        query = query.where(
            or_(
                SafetyEvent.title.contains(q, autoescape=True),
                SafetyEvent.note.contains(q, autoescape=True),
            )
        )
    with Session() as db:
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.scalars(
            query.order_by(SafetyEvent.created_at.desc(), SafetyEvent.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return dict(
            items=[event_data(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
        )


@api.get("/events/{event_id}")
def event_detail(event_id: str, user=Depends(current_user)):
    with Session() as db:
        event = db.get(SafetyEvent, event_id)
        if event is None:
            raise HTTPException(404, "事件不存在")
        return event_data(event)


@api.patch("/events/{event_id}")
def update_event(event_id: str, body: EventPatch, user=Depends(operator)):
    transitions = {
        "pending": {"confirmed", "false_positive"},
        "confirmed": {"closed", "false_positive"},
        "processing": {"closed", "false_positive"},
        "false_positive": {"confirmed"},
        "closed": {"confirmed"},
    }
    with session() as db:
        lock_control(db, 1)
        event = db.scalar(
            select(SafetyEvent).where(SafetyEvent.id == event_id).with_for_update()
        )
        if not event:
            raise HTTPException(404, "事件不存在")
        if body.status != event.status and body.status not in transitions[event.status]:
            raise HTTPException(
                409,
                "状态转换不合法：请先复核风险，再标记已处理；误报或已处理结果可重新确认",
            )
        event.status, event.note = body.status, body.note
        event.history = event.history + [
            dict(
                status=body.status,
                note=body.note,
                username=user.username,
                created_at=iso(utcnow()),
            )
        ]
        return event_data(event)


@api.get("/cameras")
def cameras(user=Depends(current_user)):
    with Session() as db:
        return [
            camera_data(camera, user.role)
            for camera in db.scalars(select(Camera).order_by(Camera.id))
        ]


@api.post("/cameras", status_code=201)
def create_camera(body: CameraCreate, user=Depends(admin)):
    with session() as db:
        lock_control(db, 1)
        if db.scalar(select(func.count()).select_from(Camera)) >= MAX_CAMERAS:
            raise HTTPException(409, f"最多配置 {MAX_CAMERAS} 个摄像头")
        camera = Camera(**body.model_dump())
        db.add(camera)
        db.flush()
        return camera_data(camera, user.role)


@api.patch("/cameras/{camera_id}")
def update_camera(camera_id: int, body: CameraPatch, user=Depends(admin)):
    with runtime.lock:
        if camera_id in runtime.cameras:
            raise HTTPException(409, "请先停止摄像头再修改配置")
        with session() as db:
            camera = db.get(Camera, camera_id)
            if not camera:
                raise HTTPException(404, "摄像头不存在")
            for key, value in body.model_dump(exclude_none=True).items():
                setattr(camera, key, value)
            return camera_data(camera, user.role)


@api.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: int, user=Depends(admin)):
    with runtime.lock:
        if camera_id in runtime.cameras:
            raise HTTPException(409, "请先停止摄像头再删除")
        with session() as db:
            camera = db.get(Camera, camera_id)
            if not camera:
                raise HTTPException(404, "摄像头不存在")
            db.delete(camera)
    return Response(status_code=204)


@api.post("/cameras/{camera_id}/start")
def start_camera(camera_id: int, user=Depends(operator)):
    require_model()
    with runtime.lock:
        with Session() as db:
            if db.get(Camera, camera_id) is None:
                raise HTTPException(404, "摄像头不存在")
        try:
            runtime.start_camera(camera_id, user.id)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        with Session() as db:
            return camera_data(db.get(Camera, camera_id), user.role)


@api.post("/cameras/{camera_id}/stop")
def stop_camera(camera_id: int, user=Depends(operator)):
    with Session() as db:
        if db.get(Camera, camera_id) is None:
            raise HTTPException(404, "摄像头不存在")
    try:
        runtime.stop_camera(camera_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    with session() as db:
        camera = db.get(Camera, camera_id)
        if camera is None:
            raise HTTPException(404, "摄像头已被删除")
        camera.status, camera.error = "offline", None
        return camera_data(camera, user.role)


@api.get("/cameras/{camera_id}/frame")
def camera_frame(camera_id: int, user=Depends(current_user)):
    with runtime.lock:
        frame = runtime.frames.get(camera_id)
    if frame is None:
        with Session() as db:
            if db.get(Camera, camera_id) is None:
                raise HTTPException(404, "摄像头不存在")
        raise HTTPException(409, "摄像头尚无可用画面，请先启动并等待连接")
    return Response(
        frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"}
    )


@api.get("/settings")
def read_settings(user=Depends(current_user)):
    return settings()


@api.put("/settings")
def update_settings(body: Settings, user=Depends(admin)):
    with session() as db:
        control = lock_control(db, 2)
        control.value = body.model_dump()
    return body.model_dump()


@api.get("/users")
def users(user=Depends(admin)):
    with Session() as db:
        return [public_user(row) for row in db.scalars(select(User).order_by(User.id))]


@api.post("/users", status_code=201)
def create_user(body: UserCreate, user=Depends(admin)):
    hashed = hasher.hash(body.password)
    try:
        with session() as db:
            lock_control(db, 1)
            row = User(
                username=body.username,
                display_name=body.display_name,
                role=body.role,
                password_hash=hashed,
            )
            db.add(row)
            db.flush()
            return public_user(row)
    except IntegrityError:
        raise HTTPException(409, "用户名已存在")


@api.patch("/users/{user_id}")
def update_user(user_id: int, body: UserPatch, user=Depends(admin)):
    hashed = hasher.hash(body.password) if body.password else None
    with session() as db:
        lock_control(db, 1)
        row = db.get(User, user_id)
        if row is None:
            raise HTTPException(404, "用户不存在")
        if row.role == "admin" and body.role and body.role != "admin":
            if (
                db.scalar(
                    select(func.count()).select_from(User).where(User.role == "admin")
                )
                <= 1
            ):
                raise HTTPException(409, "必须保留至少一名管理员")
        if body.display_name is not None:
            row.display_name = body.display_name
        if body.role is not None and body.role != row.role:
            row.role = body.role
            row.token_version += 1
        if hashed:
            row.password_hash = hashed
            row.token_version += 1
        return public_user(row)


@api.get("/dashboard")
def dashboard(user=Depends(current_user)):
    now = utcnow()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=6)
    with Session() as db:
        by_status = dict(
            db.execute(select(Job.status, func.count()).group_by(Job.status)).all()
        )
        json_entries = (
            func.json_each(Job.counts)
            if db.bind.dialect.name == "sqlite"
            else func.json_each_text(Job.counts)
        ).table_valued("key", "value")
        counts = sorted(
            db.execute(
                select(json_entries.c.key, func.sum(cast(json_entries.c.value, Integer)))
                .select_from(Job)
                .join(json_entries, true())
                .group_by(json_entries.c.key)
            ).all(),
            key=lambda item: (-item[1], item[0]),
        )
        job_days = {
            str(day): count
            for day, count in db.execute(
                select(func.date(Job.created_at), func.count())
                .where(Job.created_at >= start)
                .group_by(func.date(Job.created_at))
            )
        }
        event_days = {
            str(day): count
            for day, count in db.execute(
                select(func.date(SafetyEvent.created_at), func.count())
                .where(SafetyEvent.created_at >= start)
                .group_by(func.date(SafetyEvent.created_at))
            )
        }
        daily = []
        for offset in range(7):
            date = (start + timedelta(days=offset)).date().isoformat()
            daily.append(
                dict(
                    date=date,
                    jobs=job_days.get(date, 0),
                    events=event_days.get(date, 0),
                )
            )
        return dict(
            total_jobs=sum(by_status.values()),
            completed_jobs=by_status.get("completed", 0),
            active_jobs=by_status.get("queued", 0) + by_status.get("running", 0),
            total_detections=sum(count for _, count in counts),
            open_events=db.scalar(
                select(func.count())
                .select_from(SafetyEvent)
                .where(SafetyEvent.status.in_(["pending", "confirmed", "processing"]))
            ),
            cameras_online=db.scalar(
                select(func.count())
                .select_from(Camera)
                .where(Camera.status == "online")
            ),
            class_counts=[
                dict(name=name, count=count) for name, count in counts
            ],
            daily=daily,
            recent_events=[
                event_data(e)
                for e in db.scalars(
                    select(SafetyEvent).order_by(SafetyEvent.created_at.desc()).limit(8)
                )
            ],
            recent_jobs=jobs_data(
                db.scalars(select(Job).order_by(Job.created_at.desc()).limit(8)), db
            ),
        )


@api.websocket("/live/browser")
async def browser_live(websocket: WebSocket):
    origin = websocket.headers.get("origin")
    allowed = [
        v.strip()
        for v in os.environ.get(
            "CORS_ORIGINS", "http://localhost:15173,http://127.0.0.1:15173"
        ).split(",")
    ]
    # Same-origin reverse-proxy deployments are accepted without requiring a second URL setting.
    host = websocket.headers.get("host", "")
    if (
        origin
        and origin not in allowed
        and origin not in {"http://" + host, "https://" + host}
    ):
        await websocket.close(code=1008, reason="不允许的来源")
        return
    await websocket.accept()
    job_id = None
    recorder = None
    failure = None
    terminal_status = "completed"
    reserved = False
    try:
        hello_text = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if len(hello_text) > 8192:
            raise ValueError("认证消息过大")
        hello = LiveHello.model_validate_json(hello_text)
        user = await run_in_threadpool(authenticate, hello.token)
        if user.role not in {"admin", "operator"}:
            raise HTTPException(403, "仅管理员和操作员可以实时检测")
        await run_in_threadpool(require_model)
        job_id = str(uuid.uuid4())
        runtime.reserve_browser(job_id)
        reserved = True
        config = await run_in_threadpool(settings)
        await run_in_threadpool(
            create_browser_job, job_id, user.id, hello.confidence, hello.classes
        )
        recorder = LiveRecorder(job_id, None, config, classes=hello.classes)
        started = time.monotonic()

        async def process_frame(data):
            frame = await run_in_threadpool(decode_jpeg, data)
            result = await run_in_threadpool(
                get_detector().detect,
                frame,
                hello.confidence,
                hello.classes or None,
                job_id,
            )
            result["timestamp"] = time.monotonic() - started
            emitted = await run_in_threadpool(
                recorder.record, result, frame, result["timestamp"]
            )
            return dict(
                result, events=[event_data(event) for event in emitted], job_id=job_id
            )

        while True:
            # Receive/process/reply is deliberately serial: no inference work queue.
            message = await asyncio.wait_for(websocket.receive(), timeout=45)
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is None:
                raise ValueError("认证后仅接受二进制 JPEG 帧；发送下一帧前请等待结果")
            if await run_in_threadpool(request_cancelled, job_id):
                terminal_status = "cancelled"
                await websocket.close(code=1000, reason="任务已取消")
                break
            # Re-check JWT and role so revocation applies during long-lived sessions.
            active_user = await run_in_threadpool(authenticate, hello.token)
            if active_user.role not in {"admin", "operator"}:
                raise HTTPException(403, "实时检测权限已撤销")
            processing = asyncio.create_task(process_frame(message["bytes"]))
            premature = asyncio.create_task(websocket.receive())
            try:
                done, _ = await asyncio.wait(
                    {processing, premature}, return_when=asyncio.FIRST_COMPLETED
                )
                if premature in done:
                    next_message = premature.result()
                    await processing
                    if next_message["type"] == "websocket.disconnect":
                        break
                    raise ValueError("发送过快：必须收到上一帧检测结果后才能发送下一帧")
                result = await processing
            finally:
                premature.cancel()
                try:
                    await premature
                except asyncio.CancelledError:
                    pass
                if not processing.done():
                    await asyncio.shield(processing)
            await websocket.send_json(result)
    except WebSocketDisconnect:
        pass
    except asyncio.TimeoutError:
        failure, terminal_status = (
            "实时会话超时：认证需在 10 秒内完成，帧间隔不得超过 45 秒",
            "failed",
        )
    except Exception as exc:
        failure = exc.detail if isinstance(exc, HTTPException) else str(exc)[:800]
        terminal_status = "failed"
    finally:
        try:
            if recorder:
                await run_in_threadpool(recorder.close, terminal_status, failure)
        finally:
            try:
                if job_id:
                    await run_in_threadpool(get_detector().reset_tracker, job_id)
            finally:
                if reserved:
                    runtime.release_browser(job_id)
        if failure:
            try:
                await websocket.send_json({"error": failure, "job_id": job_id})
                await websocket.close(code=1008)
            except (RuntimeError, WebSocketDisconnect):
                pass


app.include_router(api)
