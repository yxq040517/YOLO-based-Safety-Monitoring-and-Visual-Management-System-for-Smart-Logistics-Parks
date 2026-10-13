"""Start native API and web UI. Usage: python scripts/dev.py [--install]"""

from __future__ import annotations

import argparse
import os
import json
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Start Logistics Safety API (18080) and web UI (15173). Ctrl+C stops both."
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Create venv and install pinned application dependencies first",
    )
    args = parser.parse_args()
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        parser.error("Node.js 22+ and npm are required")
    if args.install:
        if not PYTHON.exists():
            subprocess.run(
                [sys.executable, "-m", "venv", str(ROOT / ".venv")], check=True
            )
        subprocess.run(
            [
                str(PYTHON),
                "-m",
                "pip",
                "install",
                "-r",
                str(ROOT / "backend/requirements.txt"),
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run([npm, "ci"], cwd=ROOT / "frontend", check=True)
    if not PYTHON.exists() or not (ROOT / "frontend/node_modules").is_dir():
        parser.error("Dependencies missing. Run python scripts/dev.py --install")
    for port in (18080, 15173):
        with socket.socket() as probe:
            probe.settimeout(0.5)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                parser.error(
                    f"Port {port} is already in use. Stop the existing instance before starting another."
                )
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
    training_status = ROOT / "storage" / "training" / "status.json"
    try:
        training = json.loads(training_status.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        training = {}
    if training.get("status") == "running" and "INFERENCE_DEVICE" not in env:
        env["INFERENCE_DEVICE"] = "cpu"
        print(
            "GPU training is active; detection will use CPU until the service is restarted after training.",
            flush=True,
        )
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    children: list[subprocess.Popen] = []
    try:
        api = subprocess.Popen(
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                os.environ.get("API_HOST", "127.0.0.1"),
                "--port",
                "18080",
                "--workers",
                "1",
                "--ws-max-size",
                "2097152",
                "--ws-max-queue",
                "1",
            ],
            cwd=ROOT / "backend",
            env=env,
            creationflags=flags,
        )
        children.append(api)
        for _ in range(120):
            if api.poll() is not None:
                raise RuntimeError("API exited before readiness; see error above")
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:18080/api/health", timeout=1
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.5)
        else:
            raise RuntimeError("API did not become ready within 60 seconds")
        children.append(
            subprocess.Popen(
                [
                    npm,
                    "run",
                    "dev",
                    "--",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "15173",
                    "--strictPort",
                ],
                cwd=ROOT / "frontend",
                env=env,
                creationflags=flags,
            )
        )
        print(
            "\nWeb: http://localhost:15173\nAPI: http://127.0.0.1:18080/docs\nFirst visit: create your administrator account.\n",
            flush=True,
        )
        while all(child.poll() is None for child in children):
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in reversed(children):
            if child.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(child.pid), "/T", "/F"],
                        capture_output=True,
                    )
                else:
                    child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()


if __name__ == "__main__":
    raise SystemExit(main())
