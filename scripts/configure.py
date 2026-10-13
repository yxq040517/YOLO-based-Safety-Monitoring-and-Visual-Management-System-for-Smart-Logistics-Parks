"""Generate private Docker Compose secrets once. Never replaces existing .env."""

import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
try:
    with target.open("x", encoding="utf-8") as stream:
        stream.write(
            f"POSTGRES_PASSWORD={secrets.token_hex(24)}\nJWT_SECRET={secrets.token_hex(48)}\nWEB_PORT=8080\nCORS_ORIGINS=http://localhost:8080\n"
        )
    if os.name != "nt":
        target.chmod(0o600)
    print("Created .env with random private secrets. Run: docker compose up --build -d")
except FileExistsError:
    raise SystemExit(
        "Existing .env preserved; edit it manually if configuration changes are needed."
    )
