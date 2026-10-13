import os
import threading
import time
from collections import Counter
from pathlib import Path
from celery import Celery
from sqlalchemy import case, update
from .config import STORAGE
from .db import Job, Session, session, settings, utcnow
from .rules import RuleState

celery_app = Celery(
    "logistics", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0")
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_ignore_result=True,
    broker_transport_options={"visibility_timeout": 86400},
)
_detector = None
_detector_lock = threading.Lock()


def get_detector():
    global _detector
    with _detector_lock:
        if _detector is None:
            from .inference import Detector

            _detector = Detector(
                Path(
                    os.environ.get("MODEL_WEIGHTS", str(STORAGE / "models" / "best.pt"))
                )
            )
        return _detector


def model_status():
    return get_detector().status()


def request_cancelled(job_id):
    with Session() as db:
        row = db.get(Job, job_id)
        return row is None or row.cancel_requested or row.status == "cancelled"


def finish_job(job_id, status, error=None):
    with session() as db:
        db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(("queued", "running")))
            .values(
                status=case(
                    (Job.cancel_requested.is_(True), "cancelled"), else_=status
                ),
                error=case((Job.cancel_requested.is_(True), None), else_=error),
                completed_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )


def complete_job(job_id, result):
    values = {
        name: result[name]
        for name in (
            "result_path",
            "preview_path",
            "width",
            "height",
            "counts",
            "duration_ms",
            "frames",
        )
        if name in result
    }
    values.update(
        detections=result.get("detections", [])[:2000],
        status="completed",
        progress=100,
        completed_at=utcnow(),
    )
    with session() as db:
        completed = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "running",
                Job.cancel_requested.is_(False),
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        return completed.rowcount == 1


def run_job(job_id):
    from .inference import process_file, InferenceCancelled

    # Atomic claim also makes broker redelivery safe: never run two copies.
    with session() as db:
        claimed = db.execute(
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == "queued",
                Job.cancel_requested.is_(False),
            )
            .values(status="running")
        )
        if claimed.rowcount != 1:
            return
        job = db.get(Job, job_id)
    config = settings()
    rule_state = RuleState(
        job.id, None, config, single_image=job.kind == "image", classes=job.classes
    )
    counts = Counter()
    frames = 0
    last_write = 0.0
    last_result = None

    def progress(value):
        nonlocal last_write
        now = time.monotonic()
        if now - last_write < 0.5 and value < 100:
            return
        last_write = now
        with session() as db:
            row = db.get(Job, job.id)
            row.progress = min(99.9, max(0, float(value)))
            row.counts = dict(counts)
            row.frames = frames
            if last_result:
                row.width, row.height = last_result["width"], last_result["height"]
                row.detections = last_result["detections"][:2000]

    def on_frame(result, frame, seconds):
        nonlocal frames, last_result
        if request_cancelled(job.id):
            raise InferenceCancelled("任务已取消")
        frames += 1
        last_result = result
        counts.update(d["class_name"] for d in result["detections"])
        rule_state.evaluate(result, frame, seconds)

    result = None
    try:
        result = process_file(
            get_detector(),
            Path(job.source_path),
            job.kind,
            STORAGE / "results" / job.id,
            job.confidence,
            job.classes or None,
            progress,
            lambda: request_cancelled(job.id),
            on_frame,
        )
        if not complete_job(job.id, result):
            raise InferenceCancelled("任务已取消")
    except InferenceCancelled:
        if result is not None:
            for name in ("result_path", "preview_path", "json_path", "frames_path"):
                if result.get(name):
                    Path(result[name]).unlink(missing_ok=True)
        finish_job(job.id, "cancelled")
    except Exception as exc:
        finish_job(job.id, "failed", f"检测失败：{str(exc)[:1000]}")


@celery_app.task(name="logistics.process_job", acks_late=True, bind=True)
def process_job(self, job_id):
    if self.request.delivery_info.get("redelivered"):
        with session() as db:
            job = db.get(Job, job_id)
            interrupted = job is not None and job.status == "running"
        if interrupted:
            finish_job(
                job_id,
                "failed",
                "Celery 执行进程中断，已终止未完成任务；请检查工作进程后重新提交",
            )
            return
    run_job(job_id)
