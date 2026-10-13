from collections import defaultdict
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select

from .config import media_url
from .db import SafetyEvent, iso


def event_data(event):
    return dict(
        id=event.id,
        job_id=event.job_id,
        camera_id=event.camera_id,
        rule_type=event.rule_type,
        severity=event.severity,
        title=event.title,
        status=event.status,
        created_at=iso(event.created_at),
        timestamp_seconds=event.timestamp_seconds,
        snapshot_url=media_url(event.snapshot_path),
        note=event.note,
        history=event.history,
    )


def job_data(job, db=None, include_events=True, events=None):
    if events is None:
        events = []
        if db is not None and include_events:
            events = [
                event_data(e)
                for e in db.scalars(
                    select(SafetyEvent)
                    .where(SafetyEvent.job_id == job.id)
                    .order_by(SafetyEvent.created_at.desc())
                    .limit(100)
                )
            ]
    return dict(
        id=job.id,
        kind=job.kind,
        filename=job.filename,
        status=job.status,
        progress=round(job.progress, 2),
        created_at=iso(job.created_at),
        completed_at=iso(job.completed_at),
        error=job.error,
        confidence=job.confidence,
        source_url=media_url(job.source_path),
        result_url=media_url(job.result_path),
        preview_url=media_url(job.preview_path),
        detections=job.detections,
        counts=job.counts,
        events=events,
        duration_ms=job.duration_ms,
        width=job.width,
        height=job.height,
        frames=job.frames,
        camera_id=job.camera_id,
        classes=job.classes,
        observations_are_unique_objects=False,
        events_truncated=len(events) == 100,
    )


def jobs_data(jobs, db):
    jobs = list(jobs)
    if not jobs:
        return []
    ranked = (
        select(
            SafetyEvent.id.label("event_id"),
            func.row_number()
            .over(
                partition_by=SafetyEvent.job_id,
                order_by=SafetyEvent.created_at.desc(),
            )
            .label("event_rank"),
        )
        .where(SafetyEvent.job_id.in_([job.id for job in jobs]))
        .subquery()
    )
    events_by_job = defaultdict(list)
    for event in db.scalars(
        select(SafetyEvent)
        .join(ranked, SafetyEvent.id == ranked.c.event_id)
        .where(ranked.c.event_rank <= 100)
        .order_by(SafetyEvent.job_id, SafetyEvent.created_at.desc())
    ):
        events_by_job[event.job_id].append(event_data(event))
    return [job_data(job, events=events_by_job[job.id]) for job in jobs]


def camera_data(camera, role):
    source = camera.source
    if role != "admin":
        parsed = urlsplit(source)
        host = parsed.hostname or ""
        if ":" in host:
            host = "[" + host + "]"
        if parsed.port:
            host += ":" + str(parsed.port)
        # Path/query may also contain credentials. Only administrators receive them.
        source = urlunsplit((parsed.scheme, host, "", "", ""))
    return dict(
        id=camera.id,
        name=camera.name,
        source=source,
        zone=camera.zone,
        status=camera.status,
        error=camera.error,
        created_at=iso(camera.created_at),
    )
