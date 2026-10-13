from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import rules
from app.db import DEFAULT_SETTINGS, Base, Job, SafetyEvent, User


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    storage = tmp_path / "中文园区"
    (storage / "snapshots").mkdir(parents=True)
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    @contextmanager
    def transaction():
        with factory.begin() as session:
            yield session

    with transaction() as db:
        db.add(
            User(
                id=1,
                username="test",
                display_name="测试",
                password_hash="not-used-for-authentication",
                role="admin",
            )
        )
    with transaction() as db:
        db.add(Job(id="job", owner_id=1, kind="video", filename="fixture.mp4"))
    monkeypatch.setattr(rules, "STORAGE", storage)
    monkeypatch.setattr(rules, "session", transaction)
    yield transaction, np.zeros((100, 100, 3), dtype=np.uint8)
    engine.dispose()


def detection(name, box, track_id=1):
    return {"class_name": name, "confidence": 0.9, "box": box, "track_id": track_id}


def frame(*detections):
    return {"width": 100, "height": 100, "detections": list(detections)}


def test_fire_requires_consecutive_frames_and_emits_once_per_episode(scenario):
    transaction, image = scenario
    state = rules.RuleState("job", None, DEFAULT_SETTINGS)
    fire = frame(detection("fire", [10, 10, 50, 50]))
    assert state.evaluate(fire, image, 0) == []
    assert state.evaluate(fire, image, 1) == []
    assert state.evaluate(frame(), image, 2) == []
    assert state.evaluate(fire, image, 3) == []
    assert state.evaluate(fire, image, 4) == []
    emitted = state.evaluate(fire, image, 5)
    assert len(emitted) == 1
    event_id = emitted[0].id
    with transaction() as db:
        saved = db.get(SafetyEvent, event_id)
        assert saved.rule_type == "fire" and saved.status == "pending"
        assert saved.timestamp_seconds == 5
        with Image.open(Path(saved.snapshot_path)) as snapshot:
            assert snapshot.size == (100, 100)
    assert state.evaluate(fire, image, 34.99) == []
    assert state.evaluate(fire, image, 35) == []
    with transaction() as db:
        assert len(list(db.scalars(select(SafetyEvent)))) == 1


def test_fire_rearms_only_after_consecutive_clear_frames(scenario):
    transaction, image = scenario
    cfg = {**DEFAULT_SETTINGS, "event_cooldown_seconds": 1}
    state = rules.RuleState("job", None, cfg)
    fire = frame(detection("fire", [10, 10, 50, 50]))
    for second in (0, 1):
        assert state.evaluate(fire, image, second) == []
    assert len(state.evaluate(fire, image, 2)) == 1
    assert state.evaluate(frame(), image, 3) == []
    assert state.evaluate(frame(), image, 4) == []
    assert state.evaluate(fire, image, 5) == []
    assert state.evaluate(fire, image, 6) == []
    assert state.evaluate(fire, image, 7) == []
    for second in (8, 9, 10):
        assert state.evaluate(frame(), image, second) == []
    assert state.evaluate(fire, image, 11) == []
    assert state.evaluate(fire, image, 12) == []
    assert len(state.evaluate(fire, image, 13)) == 1
    with transaction() as db:
        assert len(list(db.scalars(select(SafetyEvent)))) == 2


def test_multiple_people_with_same_risk_create_one_source_event(scenario):
    transaction, image = scenario
    cfg = {**DEFAULT_SETTINGS, "enable_ppe": True, "consecutive_frames": 1}
    state = rules.RuleState("job", None, cfg)
    people = frame(
        detection("person", [10, 10, 30, 90], 1),
        detection("person", [60, 10, 80, 90], 2),
    )
    assert len(state.evaluate(people, image, 0)) == 1
    assert state.evaluate(people, image, 31) == []
    with transaction() as db:
        assert len(list(db.scalars(select(SafetyEvent)))) == 1


def test_proximity_is_an_advisory_based_on_image_position(scenario):
    _, image = scenario
    cfg = {**DEFAULT_SETTINGS, "enable_proximity": True, "consecutive_frames": 1}
    state = rules.RuleState("job", None, cfg)
    near = frame(
        detection("person", [10, 10, 30, 80], 1),
        detection("forklift", [32, 20, 70, 90], 2),
    )
    events = state.evaluate(near, image, 0)
    assert len(events) == 1
    assert events[0].rule_type == "proximity"
    assert events[0].severity == "medium"
    assert "人车交叉注意" in events[0].title
    assert "画面相对位置" in events[0].title


def test_ppe_does_not_infer_missing_excluded_equipment(scenario):
    _, image = scenario
    cfg = {**DEFAULT_SETTINGS, "enable_ppe": True, "consecutive_frames": 1}
    person = detection("person", [20, 10, 60, 90])
    filtered = rules.RuleState("job", None, cfg, classes=[10])
    assert filtered.evaluate(frame(person), image, 0) == []
    complete = rules.RuleState("job", None, cfg, classes=[7, 10, 13])
    helmet = detection("helmet", [30, 5, 50, 20], 2)
    vest = detection("safety vest", [25, 35, 55, 65], 3)
    assert complete.evaluate(frame(person, helmet, vest), image, 0) == []
    events = complete.evaluate(frame(person, helmet), image, 1)
    assert len(events) == 1 and events[0].rule_type == "ppe"
    assert events[0].status == "pending"


def test_intrusion_uses_footpoint_and_fixed_view_only(scenario):
    _, image = scenario
    cfg = {
        **DEFAULT_SETTINGS,
        "enable_intrusion": True,
        "consecutive_frames": 1,
        "zone_polygon": [[0.1, 0.5], [0.9, 0.5], [0.9, 0.95], [0.1, 0.95]],
    }
    person = detection("person", [20, 10, 60, 90])
    mobile = rules.RuleState("job", None, cfg, fixed_view=False)
    assert mobile.evaluate(frame(person), image, 0) == []
    fixed = rules.RuleState("job", None, cfg, fixed_view=True)
    events = fixed.evaluate(frame(person), image, 0)
    assert len(events) == 1 and events[0].rule_type == "intrusion"
