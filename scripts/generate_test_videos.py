# -*- coding: utf-8 -*-
import argparse
import cv2
import numpy as np
from pathlib import Path

def generate_test_video(output_path, camera_id, duration_s=30, fps=15):
    """Gera video de teste com pessoa simulada"""
    
    width, height = 640, 480
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))
    
    total_frames = duration_s * fps
    
    for frame_num in range(total_frames):
        frame = np.ones((height, width, 3), dtype=np.uint8) * 200
        
        zone_points = np.array([
            [int(width*0.1), int(height*0.3)],
            [int(width*0.9), int(height*0.3)],
            [int(width*0.9), int(height*0.95)],
            [int(width*0.1), int(height*0.95)]
        ], np.int32)
        cv2.polylines(frame, [zone_points], True, (0, 255, 0), 2)
        cv2.putText(frame, "ZONA RISCO", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        
        progress = frame_num / total_frames
        
        if camera_id == "cam_frente_esq":
            if progress < 0.5:
                person_x = int(width * (0.2 + progress))
                person_y = int(height * 0.6)
            else:
                person_x = int(width * (0.2 + (1-progress)))
                person_y = int(height * 0.6)
        elif camera_id == "cam_frente_dir":
            person_x = int(width * 0.5)
            person_y = int(height * (0.3 + progress * 0.5))
        elif camera_id == "cam_tras_esq":
            person_x = int(width * 0.2)
            person_y = int(height * 0.1)
        else:
            person_x = -100
            person_y = -100
        
        if person_x > 0 and person_y > 0:
            cv2.rectangle(frame, (person_x-20, person_y-40), (person_x+20, person_y+40), (0, 255, 0), -1)
        
        cv2.putText(frame, f"Frame {frame_num}", (10, height-20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(frame, camera_id, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        
        writer.write(frame)
    
    writer.release()
    print("OK: " + str(output_path))

if __name__ == "__main__":
    from pathlib import Path
    
    output_dir = Path("videos")
    output_dir.mkdir(exist_ok=True)
    
    cameras = [
        ("cam_frente_esq", "Person entering zone"),
        ("cam_frente_dir", "Person crossing zone"),
        ("cam_tras_esq", "Person outside zone"),
        ("cam_tras_dir", "Empty zone")
    ]
    
    print("Gerando 4 videos de teste...")
    
    for camera_id, description in cameras:
        output_path = output_dir / f"test_{camera_id}.mp4"
        print(f"  {camera_id}: {description}")
        generate_test_video(output_path, camera_id, 30)
    
    print("Pronto!")
