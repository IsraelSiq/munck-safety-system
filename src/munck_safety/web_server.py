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
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

class SystemState:
    def __init__(self):
        self.running = False
        self.last_frame = {}
        self.frame_lock = threading.Lock()
        self.events = []
        self.start_time = datetime.now()

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
        intrusions = [e for e in state.events if e.get('event_type') == 'INTRUSION_START']
        print(f"📊 {len(state.events)} eventos | 🚨 {len(intrusions)} intrusoes")
        for i in intrusions:
            print(f"   {i.get('camera_id')} | zone={i.get('zone')} | track={i.get('track_id')}")
    except Exception as e:
        print(f"⚠️ {e}")

def camera_stream(camera_id):
    while state.running:
        with state.frame_lock:
            frame = state.last_frame.get(camera_id)
        if frame is not None:
            try:
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                if ret:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' +
                           buffer.tobytes() + b'\r\n')
            except Exception:
                pass
        time.sleep(0.1)  # 10fps - mais leve

@app.route('/')
def index():
    return send_file(os.path.join(DASHBOARD_DIR, 'index.html'))

@app.route('/camera/<camera_id>/stream')
def camera_stream_route(camera_id):
    return Response(
        camera_stream(camera_id),
        mimetype='multipart/x-mixed-replace; boundary=frame',
        headers={'Cache-Control': 'no-cache', 'Connection': 'keep-alive'}
    )

@app.route('/api/stats')
def get_stats():
    uptime = int((datetime.now() - state.start_time).total_seconds())
    intrusions = len([e for e in state.events if e.get('event_type') == 'INTRUSION_START'])
    cameras = len([k for k, v in state.last_frame.items() if v is not None])
    return jsonify({
        'cameras_online': cameras,
        'total_intrusions': intrusions,
        'total_people': 0,
        'uptime': uptime
    })

@socketio.on('connect')
def handle_connect():
    print(f"✅ Cliente conectado — replay de {len(state.events)} eventos")
    emit('connection_response', {'status': 'online'})
    for event in state.events:
        emit('new_event', {
            'timestamp': event.get('timestamp', ''),
            'event_type': event.get('event_type', ''),
            'camera_id': event.get('camera_id', ''),
            'zone': event.get('zone', ''),
            'track_id': event.get('track_id', ''),
            'confidence': event.get('confidence', 0)
        })

@socketio.on('request_stats')
def handle_stats_request():
    uptime = int((datetime.now() - state.start_time).total_seconds())
    intrusions = len([e for e in state.events if e.get('event_type') == 'INTRUSION_START'])
    cameras = len([k for k, v in state.last_frame.items() if v is not None])
    emit('stats_update', {
        'cameras_online': cameras,
        'total_intrusions': intrusions,
        'total_people': 0,
        'uptime': uptime
    })

def video_player(video_sources):
    caps = []
    for idx, source in enumerate(video_sources):
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            caps.append((f'cam_{idx}', cap))
            print(f"✅ cam_{idx}: {os.path.basename(source)}")
        else:
            print(f"❌ Falhou: {source}")
    state.running = True
    while state.running:
        for cam_id, cap in caps:
            ret, frame = cap.read()
            if ret:
                with state.frame_lock:
                    state.last_frame[cam_id] = frame
            else:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        time.sleep(0.033)
    for _, cap in caps:
        cap.release()

if __name__ == '__main__':
    import sys
    if '--simulate' in sys.argv:
        sources = [
            os.path.join(VIDEOS_DIR, 'test_cam_frente_esq.mp4'),
            os.path.join(VIDEOS_DIR, 'test_cam_frente_dir.mp4'),
            os.path.join(VIDEOS_DIR, 'test_cam_tras_esq.mp4'),
            os.path.join(VIDEOS_DIR, 'test_cam_tras_dir.mp4'),
        ]
    else:
        sources = [0]
    load_events()
    threading.Thread(target=video_player, args=(sources,), daemon=True).start()
    print("🚀 http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
