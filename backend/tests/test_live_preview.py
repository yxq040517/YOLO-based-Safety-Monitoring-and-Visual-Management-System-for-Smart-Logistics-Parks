import io
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, main, runtime
from app.db import Base, DEFAULT_SETTINGS, Job, User


@pytest.fixture
def preview_scenario(tmp_path, monkeypatch):
    storage = tmp_path / "中文园区"
    storage.mkdir()
    engine = create_engine("sqlite:///" + (storage / "test.db").as_posix())
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
                username="preview",
                display_name="测试",
                password_hash="unused",
                role="admin",
            )
        )
    with transaction() as db:
        db.add(
            Job(
                id="live",
                owner_id=1,
                kind="camera",
                filename="浏览器摄像头",
                status="running",
            )
        )
    monkeypatch.setattr(config, "STORAGE", storage)
    monkeypatch.setattr(runtime, "STORAGE", storage)
    monkeypatch.setattr(runtime, "session", transaction)
    monkeypatch.setattr(main, "Session", factory)
    recorder = runtime.LiveRecorder("live", None, DEFAULT_SETTINGS)
    result = {"width": 32, "height": 32, "duration_ms": 1, "detections": []}
    recorder.record(result, np.zeros((32, 32, 3), dtype=np.uint8), 0)
    application = FastAPI()
    application.include_router(main.api)
    client = TestClient(application)
    yield recorder, result, client, transaction, storage
    client.close()
    engine.dispose()


def test_polling_snapshot_closes_file_before_concurrent_windows_replace(
    preview_scenario, monkeypatch
):
    recorder, result, client, _, _ = preview_scenario
    client.app.dependency_overrides[main.current_user] = lambda: object()
    opened = threading.Event()
    descriptors = []
    release_read = threading.Event()
    writer_waiting = threading.Event()
    original_open = Path.open
    original_replace = runtime.os.replace
    lock = threading.Lock()

    @contextmanager
    def held_snapshot(handle):
        with handle:
            opened.set()
            assert release_read.wait(5), "Snapshot reader was not released"
            yield handle

    def open_snapshot(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        if path == recorder.preview and args and args[0] == "rb":
            descriptors.append(handle)
            return held_snapshot(handle)
        return handle

    def windows_replace(source, destination):
        if destination == recorder.preview and any(
            not handle.closed for handle in descriptors
        ):
            raise PermissionError("Windows cannot replace an open preview")
        return original_replace(source, destination)

    class SnapshotLock:
        def __enter__(self):
            if opened.is_set():
                writer_waiting.set()
            lock.acquire()

        def __exit__(self, *exc):
            lock.release()

    monkeypatch.setattr(runtime, "preview_lock", SnapshotLock())
    monkeypatch.setattr(Path, "open", open_snapshot)
    monkeypatch.setattr(runtime.os, "replace", windows_replace)
    recorder.last_write = 0
    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(client.get, "/api/media/results/live/preview.jpg")
        try:
            assert opened.wait(5), "Media route must take a closed-descriptor snapshot"
            writer = pool.submit(
                recorder.record, result, np.full((32, 32, 3), 255, dtype=np.uint8), 1
            )
            assert writer_waiting.wait(5), (
                "Concurrent recorder did not reach snapshot lock"
            )
        finally:
            release_read.set()
        response = reader.result(timeout=5)
        writer.result(timeout=5)
    assert response.status_code == 200
    assert all(handle.closed for handle in descriptors)
    assert response.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.getpixel((0, 0)) == (0, 0, 0)
    latest = client.get("/api/media/results/live/preview.jpg")
    with Image.open(io.BytesIO(latest.content)) as image:
        assert image.getpixel((0, 0)) == (255, 255, 255)


def test_preview_requires_auth_and_media_association(preview_scenario):
    _, _, client, _, storage = preview_scenario
    assert client.get("/api/media/results/live/preview.jpg").status_code in {401, 403}
    client.app.dependency_overrides[main.current_user] = lambda: object()
    unassociated = storage / "results" / "private.jpg"
    unassociated.write_bytes(b"not-associated")
    assert client.get("/api/media/results/private.jpg").status_code == 404


def test_preview_size_limit_does_not_buffer_videos(preview_scenario, monkeypatch):
    _, _, client, transaction, storage = preview_scenario
    client.app.dependency_overrides[main.current_user] = lambda: object()
    monkeypatch.setattr(runtime, "MAX_PREVIEW_BYTES", 32)
    with pytest.raises(HTTPException) as error:
        main.media("results/live/preview.jpg", user=object())
    assert error.value.status_code == 413
    video = storage / "results" / "video.mp4"
    video.write_bytes(b"video-is-streamed" * 128)
    with transaction() as db:
        db.add(
            Job(
                id="video",
                owner_id=1,
                kind="video",
                filename="video.mp4",
                result_path=str(video),
            )
        )
    response = client.get(
        "/api/media/results/video.mp4", headers={"Range": "bytes=0-4"}
    )
    assert response.status_code == 206
    assert response.content == b"video"
    assert response.headers["content-range"] == f"bytes 0-4/{video.stat().st_size}"
