from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from app import tasks
from app.db import Base, Job, User


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + str(tmp_path / "jobs.sqlite"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def transaction():
        with factory.begin() as db:
            yield db

    with transaction() as db:
        db.add(
            User(
                id=1,
                username="test",
                display_name="test",
                password_hash="unused",
                role="admin",
            )
        )
    with transaction() as db:
        db.add(
            Job(
                id="job",
                owner_id=1,
                kind="image",
                filename="image.jpg",
                status="running",
            )
        )
    monkeypatch.setattr(tasks, "session", transaction)
    yield factory, transaction
    engine.dispose()


def test_committed_cancellation_wins_over_stale_worker_completion(database):
    factory, transaction = database
    with factory() as worker:
        stale = worker.get(Job, "job")
        worker.commit()
        with transaction() as cancel:
            cancel.execute(
                update(Job).where(Job.id == "job").values(cancel_requested=True)
            )
        assert stale.cancel_requested is False
        assert (
            tasks.complete_job("job", {"result_path": "should-not-be-exposed.jpg"})
            is False
        )
        tasks.finish_job("job", "cancelled")
    with transaction() as db:
        job = db.get(Job, "job")
        assert job.status == "cancelled"
        assert job.cancel_requested is True
        assert job.result_path is None
        assert job.progress < 100


def test_completion_cannot_be_replaced_by_late_failure_or_cancellation(database):
    _, transaction = database
    assert tasks.complete_job(
        "job", {"result_path": "finished.jpg", "counts": {"fire": 2}}
    )
    tasks.finish_job("job", "failed", "late worker error")
    tasks.finish_job("job", "cancelled")
    with transaction() as db:
        job = db.get(Job, "job")
        assert (job.status, job.progress, job.result_path, job.error) == (
            "completed",
            100,
            "finished.jpg",
            None,
        )
        assert job.counts == {"fire": 2}


def test_failure_does_not_replace_committed_cancellation(database):
    _, transaction = database
    with transaction() as db:
        db.execute(update(Job).where(Job.id == "job").values(cancel_requested=True))
    tasks.finish_job("job", "failed", "encoder stopped")
    with transaction() as db:
        job = db.get(Job, "job")
        assert job.status == "cancelled"
        assert job.error is None
