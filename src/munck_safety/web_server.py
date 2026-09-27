import cv2
import threading
import time
from datetime import datetime
from flask import Flask, send_file, Response, jsonify
from flask_socketio import SocketIO, emit
import json
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_DIR = os.path.join(BASE_DIR, 'dashboard')
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
VIDEOS_DIR = os.path.join(BASE_DIR, 'videos')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'munck-safety-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

class SystemState:
    def __init__(self):
        self.running = False
        self.last_frame = {}
        self.events = []
        self.stats = {
            'cameras_online': 0,
            'total_intrusions': 0,
            'total_people': 0,
            'start_time': datetime.now()
        }

state = SystemState()

def load_events():
    path = os.path.join(ARTIFACTS_DIR, 'events.jsonl')
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        state.events.append(json.loads(line))
                    except:
                        pass
        print(f"📊 {len(state.events)} eventos carregados")
        intrusions = [e for e in state.events if e.get('event_type') == 'INTRUSION_START']
        print(f"🚨 {len(intrusions)} intrusoes nos dados")
        for i in intrusions:
            print(f"   -> {i}")
    except Exception as e:
        print(f"⚠️ Erro ao carregar eventos: {e}")

def camera_stream(camera_id):
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

@app.route('/')
def index():
    return send_file(os.path.join(DASHBOARD_DIR, 'index.html'))

@app.route('/api/stats')
def get_stats():
    uptime = (datetime.now() - state.stats['start_time']).total_seconds()
    return jsonify({
        'cameras_online': state.stats['cameras_online'],
        'total_intrusions': state.stats['total_intrusions'],
        'total_people': state.stats['total_people'],
        'uptime': int(uptime)
    })

@app.route('/camera/<camera_id>/stream')
def camera_stream_route(camera_id):
    return Response(camera_stream(camera_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@socketio.on('connect')
def handle_connect():
    print(f"✅ Cliente conectado — enviando {len(state.events)} eventos")
    emit('connection_response', {'status': 'online'})
    # Replay de todos os eventos para o cliente que conectou
    for event in state.events:
        evt = {
            'timestamp': event.get('timestamp', ''),
            'event_type': event.get('event_type', ''),
            'camera_id': event.get('camera_id', 'unknown'),
            'zone': event.get('zone', 'N/A'),
            'track_id': event.get('track_id'),
            'confidence': event.get('confidence', 0)
        }
        emit('new_event', evt)

@socketio.on('request_stats')
def handle_stats_request():
    uptime = (datetime.now() - state.stats['start_time']).total_seconds()
    intrusions = len([e for e in state.events if e.get('event_type') == 'INTRUSION_START'])
    emit('stats_update', {
        'cameras_online': state.stats['cameras_online'],
        'total_intrusions': intrusions,
        'total_people': state.stats['total_people'],
        'uptime': int(uptime)
    })

def video_player(video_sources):
    caps = []
    for idx, source in enumerate(video_sources):
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            caps.append((f'cam_{idx}', cap))
            print(f"✅ Camera {idx}: {source}")
        else:
            print(f"❌ Falhou: {source}")
    state.stats['cameras_online'] = len(caps)
    state.running = True
    while state.running:
        for cam_id, cap in caps:
            ret, frame = cap.read()
            if ret:
                state.last_frame[cam_id] = frame
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        time.sleep(0.01)
    for _, cap in caps:
        cap.release()

if __name__ == '__main__':
    import sys
    if '--simulate' in sys.argv:
        video_sources = [
            os.path.join(VIDEOS_DIR, 'test_cam_frente_esq.mp4'),
            os.path.join(VIDEOS_DIR, 'test_cam_frente_dir.mp4'),
            os.path.join(VIDEOS_DIR, 'test_cam_tras_esq.mp4'),
            os.path.join(VIDEOS_DIR, 'test_cam_tras_dir.mp4'),
        ]
    else:
        video_sources = [0]

    load_events()
    threading.Thread(target=video_player, args=(video_sources,), daemon=True).start()
    print("🚀 Dashboard em http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
