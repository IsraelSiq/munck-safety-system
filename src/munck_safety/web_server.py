"""
MUNCK Safety System - Web Server
Streaming MJPEG + Event Log em tempo real
"""

import cv2
import threading
import time
from datetime import datetime
from flask import Flask, send_from_directory, Response, jsonify
from flask_socketio import SocketIO, emit
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'munck-safety-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

class SystemState:
    def __init__(self):
        self.running = False
        self.last_frame = {}
        self.stats = {
            'cameras_online': 0,
            'total_intrusions': 0,
            'total_people': 0,
            'uptime': 0,
            'start_time': datetime.now()
        }
        self.events = []

state = SystemState()

def camera_stream(camera_id):
    """Generator que faz streaming de câmera em MJPEG"""
    while state.running:
        if camera_id in state.last_frame:
            frame = state.last_frame[camera_id]
            if frame is not None:
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n'
                           b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n' +
                           buffer.tobytes() + b'\r\n')
        time.sleep(0.033)

def load_events():
    """Carregar eventos do arquivo artifacts/events.jsonl"""
    try:
        with open('artifacts/events.jsonl', 'r') as f:
            for line in f:
                try:
                    state.events.append(json.loads(line))
                except:
                    pass
    except:
        pass

def event_emitter():
    """Emitir eventos salvos via WebSocket"""
    event_idx = 0
    while state.running:
        if event_idx < len(state.events):
            event = state.events[event_idx]
            socketio.emit('new_event', {
                'timestamp': event.get('timestamp', ''),
                'event_type': event.get('event_type', ''),
                'camera_id': event.get('camera_id', 'unknown'),
                'zone': event.get('zone', 'N/A'),
                'track_id': event.get('track_id'),
                'confidence': event.get('confidence', 0)
            }, namespace='/')
            
            if event['event_type'] == 'INTRUSION_START':
                state.stats['total_intrusions'] += 1
            
            event_idx += 1
            time.sleep(0.5)
        else:
            time.sleep(1)

@app.route('/')
def index():
    """Servir dashboard"""
    return send_from_directory('dashboard', 'index.html')

@app.route('/api/stats')
def get_stats():
    """API: Estatísticas"""
    uptime = (datetime.now() - state.stats['start_time']).total_seconds()
    return jsonify({
        'cameras_online': state.stats['cameras_online'],
        'total_intrusions': state.stats['total_intrusions'],
        'total_people': state.stats['total_people'],
        'uptime': int(uptime),
        'system_status': 'online' if state.running else 'offline'
    })

@app.route('/camera/<camera_id>/stream')
def camera_stream_route(camera_id):
    """Stream MJPEG"""
    return Response(
        camera_stream(camera_id),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@socketio.on('connect')
def handle_connect():
    print(f"✅ Cliente conectado")
    emit('connection_response', {
        'data': 'Sistema MUNCK conectado',
        'status': 'online' if state.running else 'offline'
    })

@socketio.on('request_stats')
def handle_stats_request():
    uptime = (datetime.now() - state.stats['start_time']).total_seconds()
    emit('stats_update', {
        'cameras_online': state.stats['cameras_online'],
        'total_intrusions': state.stats['total_intrusions'],
        'total_people': state.stats['total_people'],
        'uptime': int(uptime)
    })

def video_player(video_sources):
    """Reproduzir vídeos e fazer streaming"""
    caps = []
    for idx, source in enumerate(video_sources):
        try:
            cap = cv2.VideoCapture(source)
            caps.append((f'cam_{idx}', cap))
            print(f"✅ Vídeo carregado: {source}")
        except Exception as e:
            print(f"❌ Erro: {e}")
    
    state.stats['cameras_online'] = len(caps)
    state.running = True
    
    frame_count = {cam_id: 0 for cam_id, _ in caps}
    
    while state.running:
        for cam_id, cap in caps:
            ret, frame = cap.read()
            if ret:
                state.last_frame[cam_id] = frame
                frame_count[cam_id] += 1
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        time.sleep(0.01)
    
    for _, cap in caps:
        cap.release()

if __name__ == '__main__':
    import sys
    
    # Detectar modo
    if len(sys.argv) > 1 and sys.argv[1] == '--simulate':
        video_sources = [
            'videos/test_cam_frente_esq.mp4',
            'videos/test_cam_frente_dir.mp4',
            'videos/test_cam_tras_esq.mp4',
            'videos/test_cam_tras_dir.mp4'
        ]
    else:
        video_sources = [0]
    
    # Carregar eventos
    load_events()
    print(f"📊 {len(state.events)} eventos carregados")
    
    # Thread de reprodução de vídeos
    video_thread = threading.Thread(
        target=video_player,
        args=(video_sources,),
        daemon=True
    )
    video_thread.start()
    
    # Thread de emissão de eventos
    event_thread = threading.Thread(
        target=event_emitter,
        daemon=True
    )
    event_thread.start()
    
    print("🚀 Dashboard em http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
