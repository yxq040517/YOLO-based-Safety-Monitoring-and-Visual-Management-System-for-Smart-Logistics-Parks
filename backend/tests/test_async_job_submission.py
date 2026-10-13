import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app import main
from app.db import Job


def submit(database):
    return main.create_job(database.upload(), confidence=0.35, classes="[]", user=SimpleNamespace(id=1))


def test_database_wait_does_not_block_other_coroutines(isolated_job_database, monkeypatch):
    database = isolated_job_database
    started, released = threading.Event(), threading.Event()
    responsive = []

    @contextmanager
    def slow_transaction():
        started.set()
        responsive.append(released.wait(timeout=0.5))
        with database.transaction() as db:
            yield db

    monkeypatch.setattr(main, "session", slow_transaction)

    async def scenario():
        async def other_request():
            while not started.is_set():
                await asyncio.sleep(0.001)
            released.set()

        other = asyncio.create_task(other_request())
        result = await submit(database)
        await other
        return result

    result = asyncio.run(scenario())
    assert result["status"] == "queued"
    assert responsive == [True], "database waiting must not freeze other requests"
    assert all(thread != threading.get_ident() for thread in database.threads)


def test_queue_rejection_removes_unpersisted_upload(isolated_job_database, monkeypatch):
    database = isolated_job_database
    monkeypatch.setattr(main, "MAX_PENDING", 1)
    with database.factory.begin() as db:
        db.add(Job(id="existing", owner_id=1, kind="image", filename="existing.jpg", status="queued"))
    with pytest.raises(HTTPException) as caught:
        asyncio.run(submit(database))
    assert caught.value.status_code == 429
    assert list((database.root / "uploads").iterdir()) == []
    with database.factory() as db:
        assert [job.id for job in db.scalars(select(Job))] == ["existing"]


def test_executor_failure_keeps_a_failed_job_and_its_upload(isolated_job_database, monkeypatch):
    database = isolated_job_database

    def unavailable(_job_id):
        raise RuntimeError("executor unavailable")

    monkeypatch.setattr(main.runtime, "submit", unavailable)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(submit(database))
    assert caught.value.status_code == 503
    with database.factory() as db:
        job = db.scalar(select(Job))
        assert job.status == "failed"
        assert "无法提交检测任务" in job.error
        assert job.source_path
    assert len(list((database.root / "uploads").iterdir())) == 1
    assert all(thread != threading.get_ident() for thread in database.threads)
