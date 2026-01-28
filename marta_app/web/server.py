from flask import Flask, render_template, jsonify, request, send_from_directory
import threading
import os
import logging

# Disable Flask banner
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# Global references to pollers (set by start_server)
_data_poller = None
_ambient_poller = None
_app_instance = None # Reference to the main App instance if needed for controls
_config = None  # Reference to config for log directory

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

@app.route('/api/logs')
def get_logs():
    """List all log folders and their contents."""
    if not _config:
        return jsonify({"error": "Config not available"}), 500
    
    base_dir = _config.get("paths", {}).get("base_log_dir", "")
    if not base_dir or not os.path.exists(base_dir):
        return jsonify({"error": "Log directory not found", "path": base_dir}), 404
    
    runs = []
    try:
        for folder in sorted(os.listdir(base_dir), reverse=True):  # Most recent first
            folder_path = os.path.join(base_dir, folder)
            if os.path.isdir(folder_path) and folder.startswith("run_"):
                run_info = {
                    "name": folder,
                    "path": folder_path,
                    "files": []
                }
                # List files in folder
                for f in os.listdir(folder_path):
                    file_path = os.path.join(folder_path, f)
                    if os.path.isfile(file_path):
                        run_info["files"].append({
                            "name": f,
                            "size": os.path.getsize(file_path),
                            "is_image": f.lower().endswith(('.jpg', '.jpeg', '.png'))
                        })
                runs.append(run_info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    return jsonify({"runs": runs, "base_dir": base_dir})

@app.route('/api/logs/<run_name>/<filename>')
def get_log_file(run_name, filename):
    """Serve a file from a log folder."""
    if not _config:
        return jsonify({"error": "Config not available"}), 500
    
    base_dir = _config.get("paths", {}).get("base_log_dir", "")
    folder_path = os.path.join(base_dir, run_name)
    
    if not os.path.exists(folder_path):
        return jsonify({"error": "Run not found"}), 404
    
    return send_from_directory(folder_path, filename)

@app.route('/api/control', methods=['POST'])
def control():
    # Placeholder for control logic
    return jsonify({"status": "error", "message": "Control not implemented yet"}), 501

def run_flask(host, port):
    app.run(host=host, port=port, debug=False, use_reloader=False)

def start_web_server(data_poller, ambient_poller, config=None, host='0.0.0.0', port=5000):
    global _data_poller, _ambient_poller, _config
    _data_poller = data_poller
    _ambient_poller = ambient_poller
    _config = config
    
    t = threading.Thread(target=run_flask, args=(host, port), daemon=True)
    t.start()
    return t

def update_pollers(data_poller, ambient_poller, config=None):
    global _data_poller, _ambient_poller, _config
    _data_poller = data_poller
    _ambient_poller = ambient_poller
    if config:
        _config = config
