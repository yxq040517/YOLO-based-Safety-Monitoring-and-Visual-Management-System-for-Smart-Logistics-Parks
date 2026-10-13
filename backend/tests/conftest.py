import io
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.datastructures import Headers, UploadFile

from app import config, main, tasks
from app.db import Base, Control, User


@pytest.fixture
def isolated_job_database(tmp_path, monkeypatch):
    (tmp_path / "uploads").mkdir()
    engine = create_engine("sqlite:///" + (tmp_path / "jobs.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    threads = []

    @contextmanager
    def transaction():
        threads.append(threading.get_ident())
        with factory.begin() as db:
            yield db

    with factory.begin() as db:
        db.add(User(id=1, username="operator", display_name="Operator", password_hash="unused", role="operator"))
        db.add(Control(id=1, value={"initialized": True}))
    monkeypatch.setattr(main, "STORAGE", tmp_path)
    monkeypatch.setattr(config, "STORAGE", tmp_path)
    monkeypatch.setattr(main, "Session", factory)
    monkeypatch.setattr(main, "session", transaction)
    monkeypatch.setattr(tasks, "session", transaction)
    monkeypatch.setattr(main, "require_model", lambda: None)
    monkeypatch.setattr(main.runtime, "submit", lambda _job_id: None)

    def upload():
        buffer = io.BytesIO()
        Image.new("RGB", (32, 32), "white").save(buffer, "JPEG")
        return UploadFile(io.BytesIO(buffer.getvalue()), filename="sample.jpg", headers=Headers({"content-type": "image/jpeg"}))

    yield SimpleNamespace(root=tmp_path, factory=factory, transaction=transaction, threads=threads, upload=upload)
    engine.dispose()
