"""Report local runtime capabilities without modifying dataset files."""

import importlib.metadata
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
report = {
    "python": sys.version,
    "executable": sys.executable,
    "root": str(ROOT),
    "ffmpeg": shutil.which("ffmpeg"),
    "disk_free_gb": round(shutil.disk_usage(ROOT).free / 2**30, 2),
}
for package in ("torch", "torchvision", "ultralytics", "opencv-python", "fastapi"):
    try:
        report[package] = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        report[package] = None
try:
    import torch

    report["cuda_available"] = torch.cuda.is_available()
    report["torch_cuda"] = torch.version.cuda
    report["gpu"] = [
        {
            "name": torch.cuda.get_device_name(i),
            "memory_gb": round(
                torch.cuda.get_device_properties(i).total_memory / 2**30, 2
            ),
        }
        for i in range(torch.cuda.device_count())
    ]
except Exception as exc:
    report["torch_error"] = str(exc)
report["dataset"] = {}
for split in ("train", "valid", "test"):
    base = ROOT / "物流数据集" / split
    images = {
        p.stem
        for p in (base / "images").iterdir()
        if p.is_file()
        and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    }
    labels = {p.stem for p in (base / "labels").glob("*.txt")}
    report["dataset"][split] = {
        "images": len(images),
        "labels": len(labels),
        "missing_labels": len(images - labels),
        "orphan_labels": len(labels - images),
    }
print(json.dumps(report, ensure_ascii=False, indent=2))
