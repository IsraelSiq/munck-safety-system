from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
from ultralytics import YOLO

from .events import write_event
from .rules import should_alert
from .zones import contains_point, normalized_to_pixels


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Munck Safety POC v0.1")
    parser.add_argument("--source", required=True, help="Indice da webcam, arquivo ou URL RTSP")
    parser.add_argument("--config", default="config/example.json")
    parser.add_argument("--operation-active", action="store_true")
    return parser.parse_args()


def source_value(value: str):
    return int(value) if value.isdigit() else value


def run(args: argparse.Namespace) -> int:
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    model = YOLO(config["model"])
    capture = cv2.VideoCapture(source_value(args.source))
    if not capture.isOpened():
        raise RuntimeError(f"Nao foi possivel abrir a fonte de video: {args.source}")

    was_in_zone = False
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError("A fonte de video encerrou ou perdeu o stream")

            height, width = frame.shape[:2]
            polygon = normalized_to_pixels(config["zone"]["polygon"], width, height)
            person_in_zone = False
            best_confidence = 0.0
            results = model(frame, conf=float(config["confidence"]), verbose=False)
            for result in results:
                for box in result.boxes:
                    if int(box.cls[0]) != 0:
                        continue
                    x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                    feet = ((x1 + x2) // 2, y2)
                    in_zone = contains_point(feet, polygon)
                    person_in_zone = person_in_zone or in_zone
                    best_confidence = max(best_confidence, float(box.conf[0]))
                    color = (0, 0, 255) if in_zone else (0, 200, 0)
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

            cv2.polylines(frame, [polygon], True, (0, 0, 255), 2)
            if should_alert(person_in_zone=person_in_zone, operation_active=args.operation_active, was_in_zone=was_in_zone):
                event = {
                    "event": "PERSON_ENTERED_OPERATION_ZONE",
                    "camera": args.source,
                    "zone": config["zone"]["id"],
                    "confidence": round(best_confidence, 4),
                }
                write_event(Path(config["output_dir"]), event, frame)
                print(json.dumps(event, ensure_ascii=True))
            was_in_zone = person_in_zone

            cv2.imshow("Munck Safety POC", frame)
            if cv2.waitKey(1) & 0xFF == 27:
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()
    return 0


def main() -> int:
    try:
        return run(parse_args())
    except (OSError, RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
