#!/usr/bin/env python3
"""
Ferramenta de calibração de zonas — Fase 1.

Abre um frame da câmera e permite desenhar a zona de atuação
clicando nos vértices com o mouse. Exporta para JSON.

Uso:
    python scripts/calibrate_zone.py --source 0 --camera-id cam_frente_esq
    python scripts/calibrate_zone.py --source videos/teste.mp4 --camera-id cam_a

Controles:
    Clique esquerdo  — adiciona vértice
    Backspace        — remove último vértice
    Enter            — finaliza e salva zona
    ESC              — cancela
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    print("opencv-python-headless não instalado. pip install opencv-python")
    sys.exit(1)


def main() -> None:
    p = argparse.ArgumentParser(description="Calibração de zonas")
    p.add_argument("--source", required=True, help="Índice da webcam, arquivo ou URL RTSP")
    p.add_argument("--camera-id", required=True, help="ID da câmera (ex: cam_frente_esq)")
    p.add_argument("--zone-id", default=None, help="ID da zona (padrão: zona_<camera-id>)")
    p.add_argument("--label", default="Zona de Atuação", help="Rótulo da zona")
    p.add_argument("--output", default="config/zones_calibrated.json", help="Arquivo de saída")
    args = p.parse_args()

    zone_id = args.zone_id or f"zona_{args.camera_id}"
    source: int | str = int(args.source) if args.source.isdigit() else args.source

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"Erro: não foi possível abrir a fonte: {source}")
        sys.exit(1)

    # Captura um frame para usar como fundo
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("Erro: não foi possível ler frame.")
        sys.exit(1)

    h, w = frame.shape[:2]
    points_px: list[tuple[int, int]] = []
    title = f"Calibração — {args.camera_id} | Clique: vértice | Enter: salvar | ESC: cancelar"

    def draw(img: np.ndarray) -> np.ndarray:
        out = img.copy()
        for pt in points_px:
            cv2.circle(out, pt, 5, (0, 255, 0), -1)
        if len(points_px) >= 2:
            pts = np.array(points_px, dtype=np.int32)
            cv2.polylines(out, [pts], isClosed=len(points_px) >= 3, color=(255, 0, 0), thickness=2)
        n = len(points_px)
        cv2.putText(out, f"Vértices: {n} | Enter=salvar | ESC=cancelar | BS=desfazer",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)
        return out

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            points_px.append((x, y))

    cv2.namedWindow(title, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(title, on_mouse)

    while True:
        cv2.imshow(title, draw(frame))
        key = cv2.waitKey(50) & 0xFF
        if key == 27:   # ESC
            print("Cancelado.")
            cv2.destroyAllWindows()
            sys.exit(0)
        elif key == 13:  # Enter
            if len(points_px) < 3:
                print("São necessários ao menos 3 pontos. Continue clicando.")
            else:
                break
        elif key == 8:   # Backspace
            if points_px:
                points_px.pop()

    cv2.destroyAllWindows()

    # Normaliza coordenadas
    normalized = [{"x": round(x / w, 4), "y": round(y / h, 4)} for x, y in points_px]

    zone_entry = {
        "zone_id": zone_id,
        "camera_id": args.camera_id,
        "label": args.label,
        "points": normalized,
    }

    out_path = Path(args.output)
    existing: list[dict] = []
    if out_path.exists():
        with out_path.open(encoding="utf-8") as f:
            existing = json.load(f)
        # Substitui zona com mesmo ID
        existing = [z for z in existing if z.get("zone_id") != zone_id]

    existing.append(zone_entry)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"\nZona '{zone_id}' salva em {out_path}:")
    print(json.dumps(zone_entry, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
