from flask import Flask, render_template, jsonify, request
import threading
import time
import logging

# Disable Flask banner
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# Global references to pollers (set by start_server)
_data_poller = None
_ambient_poller = None
_app_instance = None # Reference to the main App instance if needed for controls

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/api/data')
def get_data():
    data = {}
    
    # Modbus Data
    if _data_poller:
        with _data_poller.lock:
            if hasattr(_data_poller, "full_data"):
                data["modbus"] = _data_poller.full_data
            else:
                data["modbus"] = None
    else:
        data["modbus"] = None

    # Ambient Data
    if _ambient_poller:
        data["ambient"] = _ambient_poller.get_latest()
    else:
        data["ambient"] = None
        
    return jsonify(data)

@app.route('/api/control', methods=['POST'])
def control():
    # Placeholder for control logic
    # We would need a safe way to trigger actions in the main app
    # For now, read-only dashboard is safer unless we implement a command queue
    return jsonify({"status": "error", "message": "Control not implemented yet"}), 501

def run_flask(host, port):
    app.run(host=host, port=port, debug=False, use_reloader=False)

def start_web_server(data_poller, ambient_poller, host='0.0.0.0', port=5000):
    global _data_poller, _ambient_poller
    _data_poller = data_poller
    _ambient_poller = ambient_poller
    
    t = threading.Thread(target=run_flask, args=(host, port), daemon=True)
    t.start()
    return t

def update_pollers(data_poller, ambient_poller):
    global _data_poller, _ambient_poller
    _data_poller = data_poller
    _ambient_poller = ambient_poller
