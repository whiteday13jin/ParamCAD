from __future__ import annotations

import os
from pathlib import Path


def load_local_env(env_path: Path | None = None) -> None:
    """Load a minimal .env file into process env without extra dependencies."""
    target = env_path or (Path(__file__).resolve().parents[2] / ".env")
    if not target.exists():
        return

    for raw_line in target.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]

        os.environ.setdefault(key, value)
