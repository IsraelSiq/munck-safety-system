# -*- coding: utf-8 -*-
import argparse
import json
from pathlib import Path
import subprocess
import sys

def run_4cameras(video_files, config_path, operation_active=True):
    """Executa sistema com 4 cameras lendo arquivos MP4"""
    
    # Carregar config
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Mapear videos para cameras
    camera_ids = ["cam_frente_esq", "cam_frente_dir", "cam_tras_esq", "cam_tras_dir"]
    
    if len(video_files) != 4:
        print("ERRO: Precisa de 4 videos!")
        sys.exit(1)
    
    # Atualizar config com os videos
    for i, video_file in enumerate(video_files):
        config["cameras"][i]["source"] = str(Path(video_file).resolve())
        config["cameras"][i]["camera_id"] = camera_ids[i]
    
    # Salvar config temporaria
    temp_config = "config/temp_4cameras.json"
    with open(temp_config, 'w') as f:
        json.dump(config, f, indent=2)
    
    print("\n" + "="*60)
    print("MUNCK SAFETY SYSTEM - SIMULACAO COM 4 CAMERAS")
    print("="*60 + "\n")
    
    print("Mapeamento de cameras:")
    for i, (cam_id, video) in enumerate(zip(camera_ids, video_files)):
        print(f"  {i+1}. {cam_id} -> {video}")
    
    print("\nIniciando sistema...\n")
    
    # Executar sistema
    cmd = [
        sys.executable,
        "-m", "munck_safety.app",
        "--source", "0",  # dummy
        "--config", temp_config,
        "--operation-active"
    ]
    
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        print("\n\nSistema interrompido pelo usuario.")
    finally:
        # Limpeza
        Path(temp_config).unlink(missing_ok=True)
        print("\n✅ Simulacao finalizada!")
        print("✅ Eventos salvos em artifacts/events.jsonl")
        print("✅ Snapshots salvos em artifacts/")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simular 4 cameras com videos MP4")
    parser.add_argument("--videos", nargs=4, required=True, help="4 arquivos MP4")
    parser.add_argument("--config", default="config/example.json", help="Config JSON")
    
    args = parser.parse_args()
    run_4cameras(args.videos, args.config)
