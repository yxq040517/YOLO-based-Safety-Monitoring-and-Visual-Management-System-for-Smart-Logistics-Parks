from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Role = Literal["admin", "operator", "viewer"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(StrictModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=256)


class Setup(Login):
    password: str = Field(min_length=10, max_length=256)
    display_name: str = Field(min_length=1, max_length=80)


class UserCreate(Setup):
    role: Role


class UserPatch(StrictModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Role | None = None
    password: str | None = Field(default=None, min_length=10, max_length=256)


class Settings(StrictModel):
    confidence: float = Field(default=0.35, ge=0.05, le=1, allow_inf_nan=False)
    event_cooldown_seconds: int = Field(default=30, ge=1, le=86400)
    consecutive_frames: int = Field(default=3, ge=1, le=120)
    enable_fire: bool = True
    enable_smoke: bool = True
    enable_ppe: bool = False
    enable_intrusion: bool = False
    enable_proximity: bool = False
    proximity_ratio: float = Field(default=0.15, gt=0, le=1, allow_inf_nan=False)
    zone_polygon: list[tuple[float, float]] = Field(default_factory=list, max_length=32)

    @field_validator("zone_polygon")
    @classmethod
    def polygon(cls, points):
        if points and len(points) < 3:
            raise ValueError("区域多边形至少需要三个顶点")
        if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in points):
            raise ValueError("多边形坐标必须是 0 到 1 的归一化坐标")
        if points:
            area = sum(
                points[i][0] * points[(i + 1) % len(points)][1]
                - points[(i + 1) % len(points)][0] * points[i][1]
                for i in range(len(points))
            )
            if abs(area) < 1e-5 or len(set(points)) != len(points):
                raise ValueError("多边形不得退化或包含重复顶点")

            def cross(a, b, c):
                return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

            for i in range(len(points)):
                a, b, c = points[i - 1], points[i], points[(i + 1) % len(points)]
                if (
                    cross(a, b, c) == 0
                    and (a[0] - b[0]) * (c[0] - b[0]) + (a[1] - b[1]) * (c[1] - b[1])
                    > 0
                ):
                    raise ValueError("区域多边形不得包含重叠边")
                for j in range(i + 1, len(points)):
                    if j == i + 1 or (i == 0 and j == len(points) - 1):
                        continue
                    a, b = points[i], points[(i + 1) % len(points)]
                    c, d = points[j], points[(j + 1) % len(points)]
                    bounds_overlap = max(min(a[0], b[0]), min(c[0], d[0])) <= min(
                        max(a[0], b[0]), max(c[0], d[0])
                    ) and max(min(a[1], b[1]), min(c[1], d[1])) <= min(
                        max(a[1], b[1]), max(c[1], d[1])
                    )
                    if (
                        bounds_overlap
                        and cross(a, b, c) * cross(a, b, d) <= 0
                        and cross(c, d, a) * cross(c, d, b) <= 0
                    ):
                        raise ValueError("区域多边形不得自相交")
        return points

    @model_validator(mode="after")
    def intrusion_zone(self):
        if self.enable_intrusion and not self.zone_polygon:
            raise ValueError("启用区域入侵检测前请设置多边形")
        return self


def validate_source(value):
    if any(ord(c) < 32 for c in value):
        raise ValueError("摄像头地址包含非法字符")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"rtsp", "rtsps"}
            or not parsed.hostname
            or parsed.fragment
        ):
            raise ValueError()
        parsed.port
    except ValueError:
        raise ValueError("摄像头地址必须是有效的 rtsp:// 或 rtsps:// 地址")
    return value


class CameraCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=8, max_length=2048)
    zone: str = Field(default="", max_length=100)
    _source = field_validator("source")(validate_source)


class CameraPatch(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    source: str | None = Field(default=None, min_length=8, max_length=2048)
    zone: str | None = Field(default=None, max_length=100)

    @field_validator("source")
    @classmethod
    def source_valid(cls, value):
        return validate_source(value) if value is not None else value


class EventPatch(StrictModel):
    status: Literal["confirmed", "false_positive", "closed"]
    note: str = Field(min_length=1, max_length=2000)


class LiveHello(StrictModel):
    token: str = Field(min_length=1, max_length=4096)
    confidence: float = Field(default=0.35, ge=0.05, le=1, allow_inf_nan=False)
    classes: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("classes", mode="before")
    @classmethod
    def class_ids(cls, value):
        if (
            not isinstance(value, list)
            or any(type(v) is not int or v < 0 or v >= 20 for v in value)
            or len(set(value)) != len(value)
        ):
            raise ValueError("类别编号必须为 0 至 19 且不能重复")
        return value
