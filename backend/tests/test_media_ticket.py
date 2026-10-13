import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config, main, security
from app.db import Base, Job, User


@pytest.fixture
def media_client(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    results = storage / "results"
    results.mkdir(parents=True)
    (results / "video.mp4").write_bytes(b"video-stream-content")
    (results / "other.mp4").write_bytes(b"another-video")
    (results / "unlinked.mp4").write_bytes(b"private")
    engine = create_engine("sqlite:///" + (tmp_path / "media.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as db:
        db.add(User(id=1, username="viewer", display_name="Viewer", password_hash="unused", role="viewer"))
        db.add_all(
            [
                Job(id="video", owner_id=1, kind="video", filename="video.mp4", status="completed", result_path=str(results / "video.mp4")),
                Job(id="other", owner_id=1, kind="video", filename="other.mp4", status="completed", result_path=str(results / "other.mp4")),
            ]
        )
    monkeypatch.setattr(config, "STORAGE", storage)
    monkeypatch.setattr(main, "Session", factory)
    monkeypatch.setattr(security, "Session", factory)
    monkeypatch.setattr(security, "_secret", "test-media-secret-12345678901234567890")
    with factory() as db:
        bearer = security.token(db.get(User, 1))
    app = FastAPI()
    app.include_router(main.api)
    with TestClient(app) as client:
        yield client, {"Authorization": f"Bearer {bearer}"}, factory
    engine.dispose()


def test_scoped_media_ticket_streams_video_ranges(media_client):
    client, headers, _ = media_client
    issued = client.get(
        "/api/media-access",
        params={"relative_path": "results/video.mp4"},
        headers=headers,
    )
    assert issued.status_code == 200
    playback_url = issued.json()["url"]
    assert playback_url == "/api/media-play/results/video.mp4"
    cookie = issued.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/api/media-play/results/video.mp4" in cookie
    assert "Max-Age=1800" in cookie
    response = client.get(playback_url, headers={"Range": "bytes=0-4"})
    assert response.status_code == 206
    assert response.content == b"video"
    assert response.headers["content-range"] == "bytes 0-4/20"


def test_media_ticket_is_path_scoped_and_revocable(media_client):
    client, headers, factory = media_client
    issued = client.get(
        "/api/media-access",
        params={"relative_path": "results/video.mp4"},
        headers=headers,
    )
    url = issued.json()["url"]
    assert client.get(url.replace("video.mp4", "other.mp4")).status_code == 401
    with factory.begin() as db:
        db.get(User, 1).token_version += 1
    assert client.get(url).status_code == 401


def test_media_ticket_requires_associated_file_and_login(media_client):
    client, headers, _ = media_client
    assert client.get(
        "/api/media-access", params={"relative_path": "results/video.mp4"}
    ).status_code == 401
    assert client.get(
        "/api/media-access",
        params={"relative_path": "results/unlinked.mp4"},
        headers=headers,
    ).status_code == 404


def test_media_ticket_cookie_is_secure_behind_https_proxy(media_client):
    client, headers, _ = media_client
    issued = client.get(
        "/api/media-access",
        params={"relative_path": "results/video.mp4"},
        headers={**headers, "X-Forwarded-Proto": "https"},
    )
    assert issued.status_code == 200
    assert "Secure" in issued.headers["set-cookie"]
