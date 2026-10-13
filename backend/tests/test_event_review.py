from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.db import Base, Job, SafetyEvent, User
from app.schemas import EventPatch


@pytest.fixture
def event_database(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "events.db").as_posix())
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def transaction():
        with factory.begin() as db:
            yield db

    with transaction() as db:
        db.add(User(id=1, username="operator", display_name="Operator", password_hash="unused", role="operator"))
        db.add(Job(id="job", owner_id=1, kind="video", filename="clip.mp4", status="completed"))
        db.add(
            SafetyEvent(
                id="event",
                job_id="job",
                rule_type="fire",
                severity="high",
                title="疑似火情",
                status="pending",
                timestamp_seconds=3,
            )
        )
    monkeypatch.setattr(main, "session", transaction)
    monkeypatch.setattr(main, "lock_control", lambda db, key: None)
    yield factory
    engine.dispose()


def test_confirmed_risk_can_be_marked_handled_without_processing_step(event_database):
    user = SimpleNamespace(username="operator")
    confirmed = main.update_event(
        "event", EventPatch(status="confirmed", note="视频复核确认有烟火"), user=user
    )
    assert confirmed["status"] == "confirmed"
    handled = main.update_event(
        "event", EventPatch(status="closed", note="现场已排查并处理"), user=user
    )
    assert handled["status"] == "closed"
    assert [item["status"] for item in handled["history"]] == ["confirmed", "closed"]


def test_review_decision_requires_reason():
    with pytest.raises(ValidationError):
        EventPatch(status="false_positive", note="   ")


def test_legacy_processing_state_cannot_be_selected_for_new_review():
    with pytest.raises(ValidationError):
        EventPatch(status="processing", note="不再新增处理中状态")
