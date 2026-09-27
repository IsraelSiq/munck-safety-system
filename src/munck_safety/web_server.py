"""
MUNCK Safety System - Web Server
Integra detecção de intrusão com dashboard em tempo real
"""

import cv2
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template_string, Response, request, jsonify
from flask_socketio import SocketIO, emit
from io import BytesIO
import base64

from munck_safety import MunckCore
from munck_safety.event_store import EventStore

# Instanciar Flask
app = Flask(__name__, static_folder='dashboard', static_url_path='/static')
app.config['SECRET_KEY'] = 'munck-safety-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# Estado global
class SystemState:
    def __init__(self):
        self.running = False
        self.cameras = {}
        self.munck = None
        self.event_store = None
        self.last_frame = {}
        self.detection_lock = threading.Lock()
        self.stats = {
            'cameras_online': 0,
            'total_intrusions': 0,
            'total_people': 0,
            'uptime': 0,
            'start_time': datetime.now()
        }

state = SystemState()

def init_system(config_path='config/example.json'):
    """Inicializar sistema MUNCK"""
    try:
        config = json.load(open(config_path))
        state.munck = MunckCore(config)
        state.event_store = EventStore()
        state.running = True
        print("✅ Sistema MUNCK inicializado")
        return True
    except Exception as e:
        print(f"❌ Erro ao inicializar: {e}")
        return False

def camera_stream(camera_id):
    """Generator que faz streaming de câmera em MJPEG"""
    while state.running:
        if camera_id in state.last_frame:
            frame = state.last_frame[camera_id]
            if frame is not None:
                # Encode frame como JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ret:
                    yield (b'--frame\\r\\n'
                           b'Content-Type: image/jpeg\\r\\n'
                           b'Content-Length: ' + str(len(buffer)).encode() + b'\\r\\n\\r\\n' +
                           buffer.tobytes() + b'\\r\\n')
        time.sleep(0.033)  # ~30fps

def event_monitor():
    """Monitorar eventos e emitir via WebSocket"""
    last_sent = set()
    while state.running:
        try:
            events = state.event_store.recent_events(limit=50)
            for event in reversed(events):
                event_key = (event['timestamp'], event['event_type'])
                if event_key not in last_sent:
                    last_sent.add(event_key)
                    socketio.emit('new_event', {
                        'timestamp': event['timestamp'],
                        'event_type': event['event_type'],
                        'camera_id': event.get('camera_id', 'unknown'),
                        'zone': event.get('zone', 'N/A'),
                        'track_id': event.get('track_id'),
                        'confidence': event.get('confidence', 0)
                    })
                    
                    # Atualizar stats
                    if event['event_type'] == 'INTRUSION_START':
                        state.stats['total_intrusions'] += 1
                    
        except Exception as e:
            print(f"Erro no monitor de eventos: {e}")
        time.sleep(0.5)

# ROTAS
@app.route('/')
def index():
    """Servir dashboard estático"""
    return app.send_static_file('index.html')

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """API: Estatísticas do sistema"""
    uptime = (datetime.now() - state.stats['start_time']).total_seconds()
    return jsonify({
        'cameras_online': state.stats['cameras_online'],
        'total_intrusions': state.stats['total_intrusions'],
        'total_people': state.stats['total_people'],
        'uptime': int(uptime),
        'system_status': 'online' if state.running else 'offline'
    })

@app.route('/api/events', methods=['GET'])
def get_events():
    """API: Últimos eventos"""
    try:
        limit = request.args.get('limit', 50, type=int)
        events = state.event_store.recent_events(limit=limit)
        return jsonify(events)
    except:
        return jsonify([])

@app.route('/camera/<camera_id>/stream')
def camera_stream_route(camera_id):
    """Stream MJPEG de câmera"""
    return Response(
        camera_stream(camera_id),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/camera/<camera_id>/snapshot')
def camera_snapshot(camera_id):
    """Snapshot atual da câmera"""
    if camera_id in state.last_frame:
        frame = state.last_frame[camera_id]
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame)
            return Response(buffer.tobytes(), mimetype='image/jpeg')
    return '', 404

# WebSocket
@socketio.on('connect')
def handle_connect():
    print(f"✅ Cliente conectado: {request.sid}")
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

def run_detection(video_sources, config_path='config/example.json'):
    """Rodar detecção em thread separada"""
    if not init_system(config_path):
        return
    
    # Abrir câmeras/vídeos
    caps = []
    for source in video_sources:
        try:
            cap = cv2.VideoCapture(source)
            caps.append((source, cap))
            print(f"✅ Câmera aberta: {source}")
        except Exception as e:
            print(f"❌ Erro ao abrir {source}: {e}")
    
    state.stats['cameras_online'] = len(caps)
    
    while state.running:
        for camera_id, (source, cap) in enumerate(caps):
            ret, frame = cap.read()
            if ret:
                # Processar frame com MUNCK
                try:
                    detections = state.munck.process_frame(frame, camera_id=f"cam_{camera_id}")
                    
                    # Armazenar frame para streaming
                    state.last_frame[f"cam_{camera_id}"] = frame
                    
                    # Processar detecções
                    if detections:
                        for det in detections:
                            state.stats['total_people'] = max(
                                state.stats['total_people'],
                                det.get('track_id', 0)
                            )
                except Exception as e:
                    print(f"Erro processando frame: {e}")
            else:
                state.stats['cameras_online'] -= 1
        
        time.sleep(0.01)
    
    # Cleanup
    for _, cap in caps:
        cap.release()

if __name__ == '__main__':
    import sys
    
    # Detectar modo (webcam, vídeos, simulação)
    if len(sys.argv) > 1 and sys.argv[1] == '--simulate':
        # Simulação com vídeos
        video_sources = [
            'videos/test_cam_frente_esq.mp4',
            'videos/test_cam_frente_dir.mp4',
            'videos/test_cam_tras_esq.mp4',
            'videos/test_cam_tras_dir.mp4'
        ]
    else:
        # Webcam real
        video_sources = [0]
    
    # Rodar detecção em background
    detection_thread = threading.Thread(
        target=run_detection,
        args=(video_sources,),
        daemon=True
    )
    detection_thread.start()
    
    # Event monitor em background
    event_thread = threading.Thread(
        target=event_monitor,
        daemon=True
    )
    event_thread.start()
    
    # Servidor web
    print("🚀 MUNCK Safety Dashboard iniciando em http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
