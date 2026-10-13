import math
import uuid

from .config import STORAGE
from .db import SafetyEvent, iso, session, utcnow
from .media import write_jpeg


def annotated(frame, detections):
    import cv2

    image = frame.copy()
    for detection in detections:
        x1, y1, x2, y2 = map(int, detection["box"])
        cv2.rectangle(image, (x1, y1), (x2, y2), (43, 203, 115), 2)
        label = f"{detection['class_name']} {detection['confidence']:.2f}"
        cv2.putText(
            image,
            label,
            (x1, max(18, y1 - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (43, 203, 115),
            1,
            cv2.LINE_AA,
        )
    return image


def inside(point, polygon):
    x, y = point
    hit = False
    previous = polygon[-1]
    for current in polygon:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            hit = not hit
        previous = current
    return hit


class RuleState:
    """One instance per source; all timestamps use source seconds, never wall time."""

    def __init__(
        self,
        job_id,
        camera_id,
        config,
        single_image=False,
        fixed_view=True,
        classes=None,
    ):
        self.job_id, self.camera_id, self.config = job_id, camera_id, dict(config)
        # Missing equipment cannot be inferred when that equipment class was excluded.
        if classes and not {7, 10, 13}.issubset(classes):
            self.config["enable_ppe"] = False
        self.required = 1 if single_image else config["consecutive_frames"]
        self.fixed_view = fixed_view
        self.streaks = {}
        self.active = set()
        self.clear_streaks = {}
        self.last_emitted = {}

    def evaluate(self, result, frame, seconds):
        cfg = self.config
        detections = result["detections"]
        width, height = result["width"], result["height"]
        people = [d for d in detections if d["class_name"] == "person"]
        candidates = {}
        for rule in ("fire", "smoke"):
            if cfg["enable_" + rule] and any(
                d["class_name"] == rule for d in detections
            ):
                candidates[rule] = (
                    "high",
                    "疑似火情" if rule == "fire" else "疑似烟雾",
                )
        for person in people:
            x1, y1, x2, y2 = person["box"]
            pw, ph = x2 - x1, y2 - y1
            if cfg["enable_ppe"]:
                helmet = vest = False
                for gear in detections:
                    gx1, gy1, gx2, gy2 = gear["box"]
                    cx, cy = (gx1 + gx2) / 2, (gy1 + gy2) / 2
                    if (
                        gear["class_name"] == "helmet"
                        and x1 - 0.1 * pw <= cx <= x2 + 0.1 * pw
                        and y1 - 0.15 * ph <= cy <= y1 + 0.35 * ph
                    ):
                        helmet = True
                    if (
                        gear["class_name"] == "safety vest"
                        and x1 <= cx <= x2
                        and y1 + 0.15 * ph <= cy <= y1 + 0.8 * ph
                    ):
                        vest = True
                if not helmet or not vest:
                    missing = "、".join(
                        label
                        for label, found in (("安全帽", helmet), ("反光背心", vest))
                        if not found
                    )
                    candidates["ppe"] = (
                        "medium",
                        f"疑似未佩戴{missing}（遮挡可能导致误报，需人工复核）",
                    )
            if (
                cfg["enable_intrusion"]
                and self.fixed_view
                and cfg["zone_polygon"]
                and inside(((x1 + x2) / 2 / width, y2 / height), cfg["zone_polygon"])
            ):
                candidates["intrusion"] = ("high", "人员进入配置警戒区域")
            if cfg["enable_proximity"]:
                for vehicle in detections:
                    if vehicle["class_name"] not in {"forklift", "truck", "car", "van"}:
                        continue
                    vx1, vy1, vx2, vy2 = vehicle["box"]
                    # Image-space box separation, not a claim of metric distance.
                    dx = max(x1 - vx2, vx1 - x2, 0) / width
                    dy = max(y1 - vy2, vy1 - y2, 0) / height
                    if math.hypot(dx, dy) <= cfg["proximity_ratio"]:
                        candidates["proximity"] = (
                            "medium",
                            "人车交叉注意（仅根据画面相对位置判断，需人工复核）",
                        )
        self.streaks = {key: self.streaks.get(key, 0) + 1 for key in candidates}
        for key in tuple(self.active):
            if key in candidates:
                self.clear_streaks.pop(key, None)
                continue
            clear_count = self.clear_streaks.get(key, 0) + 1
            if clear_count >= self.required:
                self.active.remove(key)
                self.clear_streaks.pop(key, None)
            else:
                self.clear_streaks[key] = clear_count
        cooldown = cfg["event_cooldown_seconds"]
        self.last_emitted = {
            key: value
            for key, value in self.last_emitted.items()
            if seconds - value < cooldown
        }
        emitted = []
        for key, (severity, title) in candidates.items():
            if (
                self.streaks[key] < self.required
                or key in self.active
                or key in self.last_emitted
            ):
                continue
            event_id = str(uuid.uuid4())
            snapshot = STORAGE / "snapshots" / (event_id + ".jpg")
            write_jpeg(snapshot, annotated(frame, detections))
            now = utcnow()
            history = [
                {
                    "status": "pending",
                    "note": "系统规则触发；检测结果需人工复核",
                    "username": "系统",
                    "created_at": iso(now),
                }
            ]
            event = SafetyEvent(
                id=event_id,
                job_id=self.job_id,
                camera_id=self.camera_id,
                rule_type=key,
                severity=severity,
                title=title,
                status="pending",
                created_at=now,
                timestamp_seconds=max(0, seconds),
                snapshot_path=str(snapshot),
                note="",
                history=history,
            )
            try:
                with session() as db:
                    db.add(event)
            except BaseException:
                snapshot.unlink(missing_ok=True)
                raise
            self.last_emitted[key] = seconds
            self.active.add(key)
            emitted.append(event)
        return emitted
