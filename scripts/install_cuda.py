"""Install verified CUDA PyTorch wheels from a resumable mainland mirror, then prove GPU access."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
CACHE = ROOT / "cuda-cache"
FILES = {
    "torch-2.9.1+cu128-cp310-cp310-win_amd64.whl": (
        "https://mirror.nju.edu.cn/pytorch/whl/cu128/torch-2.9.1%2Bcu128-cp310-cp310-win_amd64.whl",
        "64399adaa8ea0896d02cf844cba3c5dd77e769520a1af73572599e0eaa2cf551",
    ),
    "torchvision-0.24.1+cu128-cp310-cp310-win_amd64.whl": (
        "https://mirror.nju.edu.cn/pytorch/whl/cu128/torchvision-0.24.1%2Bcu128-cp310-cp310-win_amd64.whl",
        "ccdf1aff65d5bd1af99c5430508c4c234b81384d78681607ce20f2dcf5407c56",
    ),
}


def digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def main() -> int:
    if os.name != "nt":
        raise SystemExit("This shortcut targets the Windows CUDA environment.")
    if not PYTHON.exists():
        raise SystemExit("Missing .venv. Run 启动系统.cmd --install first.")
    probe = (
        "import torch; assert torch.__version__ == '2.9.1+cu128' and torch.cuda.is_available(); "
        "print(torch.__version__, torch.cuda.get_device_name(0))"
    )
    if subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT).returncode == 0:
        return 0
    curl = shutil.which("curl.exe")
    if not curl:
        raise SystemExit("Windows curl.exe is required for the resumable download.")
    CACHE.mkdir(exist_ok=True)
    wheels = []
    for filename, (url, expected) in FILES.items():
        wheel = CACHE / filename
        if not wheel.exists() or digest(wheel) != expected:
            wheel.unlink(missing_ok=True)
            result = subprocess.run(
                [
                    curl,
                    "--fail",
                    "--location",
                    "--retry",
                    "20",
                    "--retry-delay",
                    "2",
                    "--retry-all-errors",
                    "--output",
                    str(wheel),
                    url,
                ],
                cwd=ROOT,
            )
            if result.returncode:
                return result.returncode
        if digest(wheel) != expected:
            raise SystemExit(f"Checksum mismatch: {filename}")
        wheels.append(str(wheel))
    result = subprocess.run(
        [
            str(PYTHON),
            "-m",
            "pip",
            "install",
            *wheels,
            "--no-deps",
            "--force-reinstall",
        ],
        cwd=ROOT,
    )
    if result.returncode:
        return result.returncode
    return subprocess.run([str(PYTHON), "-c", probe], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
