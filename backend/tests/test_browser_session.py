import asyncio
import json
import threading
from types import SimpleNamespace

from sqlalchemy import select

from app import main
from app import runtime as runtime_module
from app.db import DEFAULT_SETTINGS, Job


class DisconnectedBrowser:
    def __init__(self):
        self.headers = {}

    async def accept(self):
        pass

    async def receive_text(self):
        return json.dumps({"token": "test-token", "confidence": 0.35, "classes": []})

    async def receive(self):
        return {"type": "websocket.disconnect"}

    async def send_json(self, payload):
        raise AssertionError(f"Unexpected browser error: {payload}")

    async def close(self, **_kwargs):
        pass


def test_browser_job_transactions_leave_the_event_loop_and_release_session(isolated_job_database, monkeypatch):
    database = isolated_job_database
    monkeypatch.setattr(main, "authenticate", lambda _token: SimpleNamespace(id=1, role="operator"))
    monkeypatch.setattr(main, "settings", lambda: dict(DEFAULT_SETTINGS))
    monkeypatch.setattr(main, "get_detector", lambda: SimpleNamespace(reset_tracker=lambda _id: None))
    monkeypatch.setattr(runtime_module, "session", database.transaction)
    sessions_before = set(main.runtime.browser_sessions)
    asyncio.run(main.browser_live(DisconnectedBrowser()))
    with database.factory() as db:
        job = db.scalar(select(Job))
        assert job.kind == "camera"
        assert job.status == "completed"
    assert main.runtime.browser_sessions == sessions_before
    assert all(thread != threading.get_ident() for thread in database.threads)
