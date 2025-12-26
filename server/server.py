# server/server.py - Updated for IMU analysis
import asyncio
import threading
import json
import csv
import os
import time
import traceback
import numpy as np
from datetime import datetime
from typing import Set, Any

from flask import Flask, request, jsonify, render_template
import websockets

# ---- Flask app ----
app = Flask(__name__, template_folder="../web/templates", static_folder="../web/static")

# -------------------- Shared State --------------------
recording = False
recording_lock = threading.Lock()
current_session = {}
csv_file = None
csv_writer = None

# Connected clients
ui_clients: Set[Any] = set()
analysis_data = {
    'last_processed': None,
    'buffers': {
        'timestamps': [],
        'ax': [], 'ay': [], 'az': [],
        'gx': [], 'gy': [], 'gz': []
    }
}

RECORDINGS_DIR = "../recordings"
os.makedirs(RECORDINGS_DIR, exist_ok=True)

# -------------------- Data Processing --------------------
def process_imu_data(data):
    """Process incoming IMU data for analysis"""
    global analysis_data
    
    with threading.Lock():
        # Store in buffer (keep last 500 samples)
        analysis_data['buffers']['timestamps'].append(data.get('timestamp_ms', 0))
        analysis_data['buffers']['ax'].append(data.get('ax_g', 0))
        analysis_data['buffers']['ay'].append(data.get('ay_g', 0))
        analysis_data['buffers']['az'].append(data.get('az_g', 0))
        analysis_data['buffers']['gx'].append(data.get('gx_dps', 0))
        analysis_data['buffers']['gy'].append(data.get('gy_dps', 0))
        analysis_data['buffers']['gz'].append(data.get('gz_dps', 0))
        
        # Limit buffer size
        max_buffer = 500
        for key in analysis_data['buffers']:
            if len(analysis_data['buffers'][key]) > max_buffer:
                analysis_data['buffers'][key] = analysis_data['buffers'][key][-max_buffer:]
        
        # Store last processed data
        analysis_data['last_processed'] = data
    
    return data

# -------------------- Flask Routes --------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/start", methods=["POST"])
def start_recording():
    global recording, current_session, csv_file, csv_writer
    
    payload = request.get_json() or request.form.to_dict()
    
    reading_type = payload.get("reading_type", "unknown")
    date = payload.get("date", datetime.now().strftime("%Y-%m-%d"))
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = "".join(c if c.isalnum() or c in "-_" else "_" for c in reading_type)
    
    fname = f"{date}_{safe_type}_{ts}.csv"
    path = os.path.join(RECORDINGS_DIR, fname)
    
    with recording_lock:
        csv_file = open(path, "w", newline="")
        csv_writer = csv.writer(csv_file)
        
        # Updated CSV header
        csv_writer.writerow([
            "date", "timestamp", "timestamp_ms",
            "ax_g", "ay_g", "az_g",
            "gx_dps", "gy_dps", "gz_dps",
            "magnitude", "mean_magnitude", "rms_magnitude"
        ])
        csv_file.flush()
        
        current_session = {
            "reading_type": reading_type,
            "date": date,
            "filename": path,
            "start_time": datetime.now().isoformat()
        }
        recording = True
    
    print(f"[INFO] Recording STARTED -> {path}")
    return jsonify({"status": "recording_started", "file": path})

@app.route("/stop", methods=["POST"])
def stop_recording():
    global recording, csv_file, csv_writer, current_session
    
    with recording_lock:
        recording = False
        if csv_file:
            csv_file.close()
        
        meta = current_session
        current_session = {}
        csv_file = None
        csv_writer = None
    
    print("[INFO] Recording STOPPED")
    return jsonify({
        "status": "recording_stopped",
        "file": meta.get("filename") if meta else None
    })

@app.route("/status", methods=["GET"])
def status():
    with recording_lock:
        return jsonify({
            "record": recording,
            "session": current_session,
            "last_data": analysis_data.get('last_processed')
        })

@app.route("/analysis", methods=["GET"])
def get_analysis():
    """Get current analysis data"""
    return jsonify({
        "last": analysis_data.get('last_processed'),
        "buffers": {
            k: v[-100:] if isinstance(v, list) else v  # Send last 100 samples
            for k, v in analysis_data.get('buffers', {}).items()
        }
    })

# -------------------- WebSocket Server --------------------
async def handle_ws(websocket, path=None):
    """WebSocket handler for all connections"""
    global ui_clients
    
    # Get path (compatibility)
    if path is None:
        try:
            path = getattr(websocket, "path", None) or getattr(getattr(websocket, "request", None), "path", None)
        except:
            path = "/"
    
    print(f"[WS] Client connected: {path}")
    
    try:
        # UI Dashboard clients
        if path == "/ui":
            ui_clients.add(websocket)
            try:
                async for _ in websocket:
                    # UI doesn't send messages
                    pass
            except websockets.ConnectionClosed:
                pass
            finally:
                ui_clients.discard(websocket)
                print("[WS] UI client disconnected")
            return
            
        # Serial data stream (from serial_reader.py)
        if path == "/serial":
            try:
                async for msg in websocket:
                    try:
                        data = json.loads(msg)
                        
                        # Process for analysis
                        processed_data = process_imu_data(data)
                        
                        # Broadcast to UI clients
                        packet = json.dumps({
                            "type": "imu_data",
                            "data": processed_data,
                            "analysis": {
                                "buffers": {
                                    k: v[-50:]  # Send last 50 for immediate plotting
                                    for k, v in analysis_data['buffers'].items()
                                }
                            }
                        })
                        
                        dead = []
                        for client in set(ui_clients):
                            try:
                                await client.send(packet)
                            except:
                                dead.append(client)
                        for d in dead:
                            ui_clients.discard(d)
                        
                        # Write to CSV if recording
                        with recording_lock:
                            if recording and csv_writer and processed_data:
                                try:
                                    csv_writer.writerow([
                                        processed_data.get('date', ''),
                                        processed_data.get('time', ''),
                                        processed_data.get('timestamp_ms', 0),
                                        processed_data.get('ax_g', 0),
                                        processed_data.get('ay_g', 0),
                                        processed_data.get('az_g', 0),
                                        processed_data.get('gx_dps', 0),
                                        processed_data.get('gy_dps', 0),
                                        processed_data.get('gz_dps', 0),
                                        processed_data.get('magnitude', 0),
                                        processed_data.get('mean_magnitude', 0),
                                        processed_data.get('rms_magnitude', 0)
                                    ])
                                    csv_file.flush()
                                except Exception as e:
                                    print(f"[WS] CSV write error: {e}")
                                    
                    except json.JSONDecodeError:
                        print(f"[WS] Invalid JSON: {msg[:100]}")
                        
            except websockets.ConnectionClosed:
                print("[WS] Serial client disconnected")
            return
            
    except Exception:
        print("[WS] Handler error:")
        traceback.print_exc()

def start_ws_server(host="0.0.0.0", port=8765):
    async def main():
        async with websockets.serve(handle_ws, host, port):
            print(f"[WS] Listening on ws://{host}:{port}")
            await asyncio.Future()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())

# -------------------- Start Servers --------------------
if __name__ == "__main__":
    # Start WebSocket server in background
    threading.Thread(target=start_ws_server, daemon=True).start()
    print("[INFO] Flask running on http://0.0.0.0:5000")
    print("[INFO] Connect serial_reader.py to ws://localhost:8765/serial")
    app.run(host="0.0.0.0", port=5000, debug=False)