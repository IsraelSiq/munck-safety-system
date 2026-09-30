import json, os, threading, time, cv2
from datetime import datetime
from flask import Flask, send_file, Response, jsonify
from flask_socketio import SocketIO, emit

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DASHBOARD_DIR = os.path.join(BASE_DIR, 'dashboard')
ARTIFACTS_DIR = os.path.join(BASE_DIR, 'artifacts')
EVENTS_FILE = os.path.join(ARTIFACTS_DIR, 'events.jsonl')

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

def normalize_event(record):
    return {
        'timestamp': record.get('ts') or record.get('timestamp') or '',
        'event_type': record.get('kind') or record.get('event_type') or '',
        'severity': record.get('severity', ''),
        'camera_id': record.get('camera_id') or '',
        'zone': record.get('zone_id') or record.get('zone') or '',
        'track_id': record.get('track_id') if record.get('track_id') is not None else '',
        'message': record.get('message', ''),
        'confidence': record.get('confidence', 0),
    }

def load_events():
    if not os.path.exists(EVENTS_FILE):
        print(f"⚠️ {EVENTS_FILE} nao encontrado")
        return
    with open(EVENTS_FILE, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    state.events.append(normalize_event(json.loads(line)))
                except:
                    pass
    intrusions = [e for e in state.events if e['event_type'] == 'INTRUSION_START']
    print(f"📊 {len(state.events)} eventos | 🚨 {len(intrusions)} intrusoes")

def watch_events():
    """Monitora events.jsonl e emite novos eventos em tempo real"""
    last_size = 0
    while True:
        try:
            if os.path.exists(EVENTS_FILE):
                size = os.path.getsize(EVENTS_FILE)
                if size > last_size:
                    with open(EVENTS_FILE, encoding='utf-8') as f:
                        f.seek(last_size)
                        for line in f:
                            line = line.strip()
                            if line:
                                try:
                                    event = normalize_event(json.loads(line))
                                    state.events.append(event)
                                    socketio.emit('new_event', event)
                                    if event['event_type'] == 'INTRUSION_START':
                                        print(f"🚨 INTRUSAO: {event['camera_id']} | {event['zone']}")
                                except:
                                    pass
                    last_size = size
        except:
            pass
        time.sleep(0.5)

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
            except:
                pass
        time.sleep(0.1)

def video_player(video_sources):
    caps = []
    for idx, source in enumerate(video_sources):
        cap = cv2.VideoCapture(source)
        if cap.isOpened():
            caps.append((f'cam_{idx}', cap))
            print(f"✅ cam_{idx}: {source}")
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
    intrusions = len([e for e in state.events if e['event_type'] == 'INTRUSION_START'])
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
        e = dict(event)
        e['is_replay'] = True
        emit('new_event', e)

@socketio.on('request_stats')
def handle_stats_request():
    uptime = int((datetime.now() - state.start_time).total_seconds())
    intrusions = len([e for e in state.events if e['event_type'] == 'INTRUSION_START'])
    cameras = len([k for k, v in state.last_frame.items() if v is not None])
    emit('stats_update', {
        'cameras_online': cameras,
        'total_intrusions': intrusions,
        'total_people': 0,
        'uptime': uptime
    })

if __name__ == '__main__':
    import sys
    load_events()
    
    if '--simulate' in sys.argv:
        sources = [
            os.path.join(BASE_DIR, 'videos', 'test_cam_frente_esq.mp4'),
            os.path.join(BASE_DIR, 'videos', 'test_cam_frente_dir.mp4'),
            os.path.join(BASE_DIR, 'videos', 'test_cam_tras_esq.mp4'),
            os.path.join(BASE_DIR, 'videos', 'test_cam_tras_dir.mp4'),
        ]
    elif '--cameras' in sys.argv:
        idx = sys.argv.index('--cameras')
        sources = [int(x) for x in sys.argv[idx+1:]]
    else:
        sources = []

    # Watcher de eventos em tempo real
    threading.Thread(target=watch_events, daemon=True).start()
    
    if sources:
        threading.Thread(target=video_player, args=(sources,), daemon=True).start()
    
    print("🚀 http://localhost:5000")
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False)
