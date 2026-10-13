from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import main
from app.db import Base, Job, SafetyEvent, User


@pytest.fixture
def query_client(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "queries.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    with factory.begin() as db:
        db.add(User(id=1, username="viewer", display_name="Viewer", password_hash="unused", role="viewer"))
        for number in range(3):
            job_id = f"job-{number}"
            db.add(
                Job(
                    id=job_id,
                    owner_id=1,
                    kind="image",
                    filename=f"image-{number}.jpg",
                    status="completed",
                    created_at=now + timedelta(seconds=number),
                    counts={"fire": number + 1, "smoke": 1},
                )
            )
            for index in range(101):
                db.add(
                    SafetyEvent(
                        id=f"event-{number}-{index}",
                        job_id=job_id,
                        rule_type="fire",
                        severity="high",
                        title="Fire",
                        created_at=now + timedelta(seconds=index),
                        timestamp_seconds=float(index),
                    )
                )
    monkeypatch.setattr(main, "Session", factory)
    app = FastAPI()
    app.include_router(main.api)
    app.dependency_overrides[main.current_user] = lambda: object()
    with TestClient(app) as client:
        yield client, engine
    engine.dispose()


@pytest.mark.parametrize("path", ["/api/jobs?page_size=3", "/api/dashboard"])
def test_job_collections_load_events_in_one_query(query_client, path):
    client, engine = query_client
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT") and "events" in statement.lower():
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get(path)
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200
    jobs = response.json()["items" if path.startswith("/api/jobs") else "recent_jobs"]
    assert len(jobs) == 3
    for job in jobs:
        assert len(job["events"]) == 100
        assert job["events_truncated"] is True
        assert job["events"][0]["timestamp_seconds"] == 100
    event_detail_queries = [
        sql for sql in statements if "job_id" in sql.lower() and "where " in sql.lower()
    ]
    assert len(event_detail_queries) == 1


def test_dashboard_aggregates_class_counts_in_database(query_client):
    client, engine = query_client
    statements = []

    def record(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", record)
    try:
        response = client.get("/api/dashboard")
    finally:
        event.remove(engine, "before_cursor_execute", record)

    assert response.status_code == 200
    data = response.json()
    assert data["total_detections"] == 9
    assert data["class_counts"] == [
        {"name": "fire", "count": 6},
        {"name": "smoke", "count": 3},
    ]
    assert any("json_each" in sql for sql in statements)
    assert not any("select jobs.counts" in sql for sql in statements)


def seed_review_states(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("UPDATE events SET status = 'closed'")
        for index, status in enumerate(("pending", "confirmed", "processing", "false_positive", "closed")):
            connection.exec_driver_sql(
                "UPDATE events SET status = ? WHERE id = ?", (status, f"event-0-{index}")
            )


def test_open_events_filter_matches_the_dashboard_count(query_client):
    client, engine = query_client
    seed_review_states(engine)
    summary = client.get("/api/dashboard").json()
    response = client.get("/api/events?open_only=true&page_size=2")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == summary["open_events"] == 3
    assert len(data["items"]) == 2
    assert {event["status"] for event in data["items"]} <= {"pending", "confirmed", "processing"}
    assert client.get("/api/events").json()["total"] == 303


@pytest.mark.parametrize("filters,total", [("status=confirmed", 1), ("status=closed", 0), ("severity=low", 0)])
def test_open_events_filter_combines_with_existing_filters(query_client, filters, total):
    client, engine = query_client
    seed_review_states(engine)
    response = client.get(f"/api/events?open_only=true&{filters}")
    assert response.status_code == 200
    assert response.json()["total"] == total
