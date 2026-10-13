import os
import queue
import threading
import time
import uuid
from collections import Counter
from sqlalchemy import select
from .config import STORAGE, TASK_MODE, MAX_PENDING, MAX_LIVE, MAX_PIXELS
from .db import Job, Camera, Session, session, settings, utcnow
from .tasks import get_detector, run_job, finish_job, request_cancelled
from .rules import RuleState, annotated
from .media import write_jpeg


# One API process owns live recorders; a fixed lock avoids a growing per-job registry.
preview_lock = threading.Lock()
MAX_PREVIEW_BYTES = MAX_PIXELS * 4 + 65536


def read_live_preview(path):
    with preview_lock:
        with path.open("rb") as handle:
            size = os.fstat(handle.fileno()).st_size
            if size > MAX_PREVIEW_BYTES:
                raise ValueError("预览图像超过大小限制")
            return handle.read(size)


class Runtime:
    def __init__(self):
        self.queue = queue.Queue(maxsize=MAX_PENDING)
        self.stopping = threading.Event()
        self.lock = threading.RLock()
        self.cameras = {}
        self.frames = {}
        self.browser_sessions = set()
        self.worker = None
        self.process_lock = None

    def start(self):
        if self.worker and self.worker.is_alive():
            raise RuntimeError("前一执行器仍在关闭，请等待当前进程退出后重启")
        self.stopping.clear()
        self.queue = queue.Queue(maxsize=MAX_PENDING)
        self.process_lock = (STORAGE / "runtime" / "api.lock").open("a+b")
        self.process_lock.seek(0)
        if self.process_lock.read(1) == b"":
            self.process_lock.write(b"0")
            self.process_lock.flush()
        self.process_lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.process_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.process_lock.close()
            raise RuntimeError(
                "仅允许一个 API 进程管理实时会话；请使用 uvicorn --workers 1"
            ) from exc
        with session() as db:
            active = list(
                db.scalars(select(Job).where(Job.status.in_(["queued", "running"])))
            )
            for job in active:
                if job.kind == "camera" or (
                    TASK_MODE == "local" and job.status == "running"
                ):
                    job.status, job.completed_at = "failed", utcnow()
                    job.error = "服务重启导致任务中断，请重新提交或重新连接摄像头"
            for camera in db.scalars(select(Camera)):
                camera.status, camera.error = "offline", None
        if TASK_MODE == "local":
            self.worker = threading.Thread(
                target=self._worker, name="file-inference", daemon=True
            )
            self.worker.start()
            with Session() as db:
                queued = list(
                    db.scalars(
                        select(Job.id)
                        .where(Job.status == "queued")
                        .order_by(Job.created_at)
                    )
                )
            for job_id in queued:
                try:
                    self.queue.put_nowait(job_id)
                except queue.Full:
                    finish_job(job_id, "failed", "恢复任务数超过队列容量，请重新提交")

    def _worker(self):
        while not self.stopping.is_set():
            try:
                job_id = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                run_job(job_id)
            except Exception as exc:
                finish_job(job_id, "failed", f"执行器错误：{str(exc)[:800]}")
            finally:
                self.queue.task_done()

    def submit(self, job_id):
        if TASK_MODE == "celery":
            from .tasks import process_job

            process_job.apply_async(args=[job_id], task_id=job_id, retry=False)
        else:
            self.queue.put_nowait(job_id)

    def close(self):
        self.stopping.set()
        with self.lock:
            camera_handles = list(self.cameras.values())
            for stop, thread, job_id in camera_handles:
                stop.set()
        for stop, thread, job_id in camera_handles:
            thread.join(timeout=12)
        if self.worker:
            with session() as db:
                for job in db.scalars(
                    select(Job).where(Job.status == "running", Job.kind != "camera")
                ):
                    job.cancel_requested = True
            self.worker.join(timeout=15)
        if self.process_lock:
            self.process_lock.close()

    def reserve_browser(self, job_id):
        with self.lock:
            if len(self.browser_sessions) + len(self.cameras) >= MAX_LIVE:
                raise ValueError("实时会话数量达到上限，请先停止其他实时检测")
            self.browser_sessions.add(job_id)

    def release_browser(self, job_id):
        with self.lock:
            self.browser_sessions.discard(job_id)

    def start_camera(self, camera_id, owner_id):
        with self.lock:
            if camera_id in self.cameras:
                return
            if len(self.cameras) + len(self.browser_sessions) >= MAX_LIVE:
                raise ValueError("实时会话数量达到上限")
            cfg = settings()
            job_id = str(uuid.uuid4())
            with session() as db:
                camera = db.get(Camera, camera_id)
                camera.status, camera.error = "connecting", None
                source = camera.source
                db.add(
                    Job(
                        id=job_id,
                        owner_id=owner_id,
                        camera_id=camera.id,
                        kind="camera",
                        filename=camera.name,
                        status="running",
                        confidence=cfg["confidence"],
                    )
                )
            stop = threading.Event()
            thread = threading.Thread(
                target=self._camera,
                args=(camera_id, source, job_id, cfg, stop),
                daemon=True,
                name=f"rtsp-{camera_id}",
            )
            self.cameras[camera_id] = (stop, thread, job_id)
            thread.start()

    def stop_camera(self, camera_id):
        with self.lock:
            handle = self.cameras.get(camera_id)
            if handle:
                handle[0].set()
        if handle:
            handle[1].join(timeout=12)
            if handle[1].is_alive():
                raise ValueError("摄像头正在关闭网络连接，请稍后重试")

    def _camera(self, camera_id, source, job_id, cfg, stop):
        capture = None
        reader = None
        latest = queue.Queue(maxsize=1)
        recorder = LiveRecorder(job_id, camera_id, cfg, fixed_view=True)
        failed = False
        try:
            import cv2

            # Open/read deadlines prevent dead RTSP sources monopolizing threads forever.
            capture = cv2.VideoCapture(
                source,
                cv2.CAP_FFMPEG,
                [
                    cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                    8000,
                    cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                    5000,
                ],
            )
            if not capture.isOpened():
                raise RuntimeError("无法连接 RTSP，请检查地址、凭据、网络和摄像头编码")
            width, height = (
                capture.get(cv2.CAP_PROP_FRAME_WIDTH),
                capture.get(cv2.CAP_PROP_FRAME_HEIGHT),
            )
            if width * height > MAX_PIXELS:
                raise RuntimeError("摄像头分辨率超过 2400 万像素限制")
            capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

            def capture_latest():
                try:
                    while not stop.is_set() and not self.stopping.is_set():
                        ok, frame = capture.read()
                        if not ok:
                            frame = None
                        try:
                            latest.get_nowait()
                        except queue.Empty:
                            pass
                        latest.put_nowait(frame)
                        if frame is None:
                            break
                finally:
                    capture.release()

            reader = threading.Thread(
                target=capture_latest, name=f"rtsp-reader-{camera_id}", daemon=True
            )
            reader.start()
            with session() as db:
                db.get(Camera, camera_id).status = "online"
            started = time.monotonic()
            while not stop.is_set() and not self.stopping.is_set():
                if request_cancelled(job_id):
                    break
                try:
                    frame = latest.get(timeout=6)
                except queue.Empty:
                    if stop.is_set() or self.stopping.is_set():
                        break
                    raise RuntimeError("RTSP 读取超时，请检查摄像头网络")
                if stop.is_set() or self.stopping.is_set():
                    break
                if frame is None:
                    raise RuntimeError("RTSP 视频流已断开，请检查网络后重新启动")
                if frame.shape[0] * frame.shape[1] > MAX_PIXELS:
                    raise RuntimeError("摄像头分辨率超过限制")
                result = get_detector().detect(
                    frame, cfg["confidence"], tracker_id=job_id
                )
                seconds = time.monotonic() - started
                result["timestamp"] = seconds
                recorder.record(result, frame, seconds)
                ok, jpeg = cv2.imencode(
                    ".jpg",
                    annotated(frame, result["detections"]),
                    [cv2.IMWRITE_JPEG_QUALITY, 80],
                )
                if not ok:
                    raise RuntimeError("实时预览编码失败")
                with self.lock:
                    self.frames[camera_id] = jpeg.tobytes()
            recorder.close("cancelled" if request_cancelled(job_id) else "completed")
        except Exception as exc:
            failed = True
            # Never expose source URLs or FFmpeg credential-bearing error text.
            message = "摄像头检测失败：请检查 RTSP 连接、模型状态、存储权限后重试"
            from .inference import ModelUnavailableError

            if isinstance(exc, ModelUnavailableError):
                message = "训练模型不可用，请完成训练并检查 /api/model 状态"
            recorder.close("failed", message)
            with session() as db:
                camera = db.get(Camera, camera_id)
                if camera:
                    camera.status, camera.error = "error", message
        finally:
            stop.set()
            if reader is not None:
                reader.join(timeout=6)
            elif capture is not None:
                capture.release()
            try:
                get_detector().reset_tracker(job_id)
                if not failed:
                    with session() as db:
                        camera = db.get(Camera, camera_id)
                        if camera:
                            camera.status, camera.error = "offline", None
            finally:
                with self.lock:
                    self.cameras.pop(camera_id, None)
                    self.frames.pop(camera_id, None)


class LiveRecorder:
    def __init__(self, job_id, camera_id, config, fixed_view=False, classes=None):
        self.job_id = job_id
        self.rule_state = RuleState(
            job_id, camera_id, config, fixed_view=fixed_view, classes=classes
        )
        self.counts = Counter()
        self.frames = 0
        self.duration_ms = 0
        self.last_result = None
        self.last_write = 0
        self.preview = None

    def record(self, result, frame, seconds):
        self.frames += 1
        self.duration_ms += result["duration_ms"]
        self.last_result = result
        self.counts.update(d["class_name"] for d in result["detections"])
        events = self.rule_state.evaluate(result, frame, seconds)
        if time.monotonic() - self.last_write >= 1:
            directory = STORAGE / "results" / self.job_id
            directory.mkdir(parents=True, exist_ok=True)
            self.preview = directory / "preview.jpg"
            temporary = directory / "preview.tmp.jpg"
            # Close snapshot readers before replacing the JPEG on native Windows.
            with preview_lock:
                write_jpeg(temporary, annotated(frame, result["detections"]))
                os.replace(temporary, self.preview)
            self.flush()
        return events

    def flush(self):
        self.last_write = time.monotonic()
        with session() as db:
            row = db.get(Job, self.job_id)
            if row:
                row.counts, row.frames, row.duration_ms = (
                    dict(self.counts),
                    self.frames,
                    self.duration_ms,
                )
                if self.last_result:
                    row.width, row.height = (
                        self.last_result["width"],
                        self.last_result["height"],
                    )
                    row.detections = self.last_result["detections"][:2000]
                if self.preview:
                    row.preview_path = str(self.preview)

    def close(self, status, error=None):
        self.flush()
        finish_job(self.job_id, status, error)


runtime = Runtime()
