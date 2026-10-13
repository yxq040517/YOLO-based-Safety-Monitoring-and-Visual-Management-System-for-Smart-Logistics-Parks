import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STORAGE = Path(os.environ.get("STORAGE_DIR", str(ROOT / "storage"))).resolve()
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "sqlite:///" + (STORAGE / "app.db").as_posix()
)
TASK_MODE = os.environ.get("TASK_MODE", "local")
if TASK_MODE not in {"local", "celery"}:
    raise RuntimeError("TASK_MODE 必须为 local 或 celery")
MAX_UPLOAD = int(os.environ.get("MAX_UPLOAD_MB", "512")) * 1024 * 1024
MAX_CAMERAS = int(os.environ.get("MAX_CAMERAS", "8"))
MAX_LIVE = int(os.environ.get("MAX_LIVE_SESSIONS", "4"))
MAX_PENDING = int(os.environ.get("MAX_PENDING_JOBS", "20"))
MAX_PIXELS = 24_000_000
JWT_HOURS = 12
VERSION = "1.0.0"


def prepare_storage():
    for name in ("uploads", "results", "snapshots", "models", "training", "runtime"):
        (STORAGE / name).mkdir(parents=True, exist_ok=True)


def safe_path(relative: str) -> Path:
    path = (STORAGE / relative).resolve()
    if not path.is_relative_to(STORAGE) or path == STORAGE:
        raise ValueError("非法媒体路径")
    return path


def media_url(path: str | Path | None):
    if not path:
        return None
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(STORAGE):
        raise ValueError("媒体输出必须位于 storage 目录")
    from urllib.parse import quote

    return "/api/media/" + quote(resolved.relative_to(STORAGE).as_posix(), safe="/")
