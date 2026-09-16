from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2


def write_event(output_dir: Path, payload: dict[str, Any], frame) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc)
    stem = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    snapshot_path = output_dir / f"{stem}.jpg"
    event_path = output_dir / f"{stem}.json"
    if not cv2.imwrite(str(snapshot_path), frame):
        raise OSError(f"Nao foi possivel salvar snapshot em {snapshot_path}")
    payload = {**payload, "timestamp": timestamp.isoformat(), "snapshot": str(snapshot_path)}
    event_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    return event_path
