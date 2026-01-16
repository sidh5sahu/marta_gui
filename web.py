import threading
import time
import json
import struct
import socket
import requests
from datetime import datetime
from flask import Flask, jsonify, render_template_string

# --- CONFIGURATION ---
MARTA_IP = "10.4.133.77"  # Default from v19.py
ESP32_IP = "10.4.135.152" # Default from v19.py
POLL_INTERVAL = 2.0       # Update speed in seconds

# --- FLASK APP ---
app = Flask(__name__)

# --- GLOBAL DATA STORE ---
# This dictionary holds the latest data to be served to the dashboard
system_data = {
    "timestamp": None,
    "marta": {
        "connected": False,
        "temps": {},      # TT01-TT06
        "pressure": {},   # PT01-04
        "setpoints": {},  # Active SP, Flow SP
        "status": 0,
        "alarms": []
    },
    "esp32": {
        "connected": False,
        "s1": {"temp": None, "hum": None, "dew": None},
        "s2": {"temp": None},
        "dew_max": None
    }
}

# --- MODBUS UTILITIES (Adapted from your v19.py) ---
try:
    from pymodbus.client import ModbusTcpClient as _PMClient
    HAS_PYMODBUS = True
except ImportError:
    HAS_PYMODBUS = False

class MinimalModbusTCP:
    # ... [Same Minimal Modbus Class from v19.py for fallback] ...
    def __init__(self, host, port=502, unit_id=1, timeout=3.0):
        self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
        self.sock = None
        self._tx_id = 0
    def connect(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            return True
        except OSError: return False
    def close(self):
        if self.sock: self.sock.close()
    def _request(self, pdu):
        if not self.sock: raise RuntimeError("Not connected")
        self._tx_id = (self._tx_id + 1) & 0xFFFF
        mbap = struct.pack(">HHHB", self._tx_id, 0, len(pdu) + 1, self.unit_id)
        self.sock.sendall(mbap + pdu)
        hdr = self.sock.recv(7)
        _, _, length = struct.unpack(">HHH", hdr[:6])
        return self.sock.recv(length - 1)
    def read_holding_registers(self, address, count=1):
        try:
            pdu = struct.pack(">BHH", 3, address, count)
            body = self._request(pdu)
            data = body[2:]
            return list(struct.unpack(">" + "H" * count, data))
        except: return None

def get_client(ip):
    if HAS_PYMODBUS:
        c = _PMClient(host=ip, port=502)
        if c.connect(): return c
    c = MinimalModbusTCP(ip)
    c.connect()
    return c

def u16_to_float(h1, h2):
    return struct.unpack("<f", struct.pack("<HH", h1, h2))[0]

# --- BACKGROUND WORKER: DATA POLLER ---
def data_poller_loop():
    print(f"--- Starting Poller: MARTA ({MARTA_IP}) & ESP32 ({ESP32_IP}) ---")
    
    # Persistent Client
    mb_client = get_client(MARTA_IP)
    
    while True:
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # 1. POLL MARTA (Modbus)
        marta_payload = {"connected": False, "temps": {}, "pressure": {}, "alarms": []}
        try:
            # Read Block 100-140 (Sensors) 
            # TT01-06 are at 126, 128, 130, 132, 134, 136 (from v19 logic)
            # Table 3.1 in manual confirms: TT01_CO2=126, TT06_CO2=136 
            
            # Note: PyModbus read_holding_registers returns an object, Minimal returns list.
            # Simplified logic for this example assuming list or object.registers
            rr = mb_client.read_holding_registers(100, count=40) 
            regs = rr.registers if hasattr(rr, 'registers') else rr
            
            if regs:
                marta_payload["connected"] = True
                
                # Helper to grab float from offset
                def get_f(offset):
                    idx = offset - 100
                    return u16_to_float(regs[idx], regs[idx+1])

                # Temperatures 
                marta_payload["temps"]["TT01"] = round(get_f(126), 2)
                marta_payload["temps"]["TT02"] = round(get_f(128), 2)
                marta_payload["temps"]["TT03"] = round(get_f(130), 2)
                marta_payload["temps"]["TT04"] = round(get_f(132), 2)
                marta_payload["temps"]["TT05"] = round(get_f(134), 2)
                marta_payload["temps"]["TT06"] = round(get_f(136), 2) # Return Temp

                # Pressures 
                marta_payload["pressure"]["PT01"] = round(get_f(106), 2)
                
            # Read Status/Setpoints Block (300+)
            # Setpoint is 310 [cite: 1098], Status is 320 
            rr2 = mb_client.read_holding_registers(300, count=25)
            regs2 = rr2.registers if hasattr(rr2, 'registers') else rr2
            
            if regs2 and marta_payload["connected"]:
                # 310 is offset 10
                idx_sp = 310 - 300
                marta_payload["setpoints"]["temp"] = round(u16_to_float(regs2[idx_sp], regs2[idx_sp+1]), 2)
                
                # Status word at 320 (offset 20)
                marta_payload["status"] = regs2[20]

        except Exception as e:
            print(f"MARTA Poll Error: {e}")
            try: mb_client.close(); mb_client = get_client(MARTA_IP) # Reconnect
            except: pass

        # 2. POLL ESP32 (HTTP)
        esp_payload = {"connected": False, "s1": {}, "s2": {}}
        try:
            url = f"http://{ESP32_IP}/data"
            r = requests.get(url, timeout=1)
            if r.status_code == 200:
                j = r.json()
                esp_payload["connected"] = True
                esp_payload["s1"] = j.get("sensor1", {})
                esp_payload["s2"] = j.get("sensor2", {})
                
                # Calculate Dew Max
                d1 = j.get("sensor1", {}).get("dew")
                if d1: esp_payload["dew_max"] = d1
        except Exception as e:
            # print(f"ESP32 Poll Error: {e}") # Silence to avoid spam
            pass

        # Update Global Store
        system_data["timestamp"] = timestamp
        system_data["marta"] = marta_payload
        system_data["esp32"] = esp_payload
        
        time.sleep(POLL_INTERVAL)

# --- WEB SERVER ROUTES ---

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data():
    return jsonify(system_data)

# --- HTML FRONTEND (Embedded for single-file usage) ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MARTA 2.0 Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #121212; color: #e0e0e0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        .card { background-color: #1e1e1e; border: 1px solid #333; margin-bottom: 20px; }
        .card-header { font-weight: bold; border-bottom: 1px solid #333; }
        .val-large { font-size: 2.5rem; font-weight: bold; }
        .unit { font-size: 1rem; color: #888; }
        .status-dot { height: 15px; width: 15px; background-color: #bbb; border-radius: 50%; display: inline-block; }
        .status-on { background-color: #00ff00; box-shadow: 0 0 10px #00ff00; }
        .status-off { background-color: #ff0000; }
        .chart-container { position: relative; height: 350px; width: 100%; }
    </style>
</head>
<body>

<nav class="navbar navbar-dark bg-dark border-bottom border-secondary mb-4">
  <div class="container-fluid">
    <span class="navbar-brand mb-0 h1">MARTA 2.0 & ESP32 Sensor Hub</span>
    <span class="navbar-text" id="clock">--:--:--</span>
  </div>
</nav>

<div class="container-fluid">
    <div class="row text-center">
        <div class="col-md-3">
            <div class="card">
                <div class="card-header">TT06 (Return Temp)</div>
                <div class="card-body">
                    <div id="val-tt06" class="val-large text-primary">--</div>
                    <span class="unit">°C</span>
                </div>
            </div>
        </div>
        
        <div class="col-md-3">
            <div class="card">
                <div class="card-header">Target Setpoint</div>
                <div class="card-body">
                    <div id="val-sp" class="val-large text-warning">--</div>
                    <span class="unit">°C</span>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card">
                <div class="card-header">Ambient Dew Point (Max)</div>
                <div class="card-body">
                    <div id="val-dew" class="val-large text-info">--</div>
                    <span class="unit">°C</span>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card">
                <div class="card-header">System Status</div>
                <div class="card-body text-start">
                    <p>MARTA: <span id="status-marta" class="status-dot"></span></p>
                    <p>ESP32: <span id="status-esp" class="status-dot"></span></p>
                    <p>Mode: <span id="marta-mode">Initializing...</span></p>
                </div>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-md-8">
            <div class="card">
                <div class="card-header">MARTA Internal Cycle (TT01-TT06)</div>
                <div class="card-body">
                    <div class="chart-container">
                        <canvas id="martaChart"></canvas>
                    </div>
                </div>
            </div>
        </div>
        <div class="col-md-4">
            <div class="card">
                <div class="card-header">Ambient Conditions</div>
                <div class="card-body">
                    <div class="chart-container">
                        <canvas id="ambientChart"></canvas>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>

<script>
    // --- CHART SETUP ---
    const ctxMarta = document.getElementById('martaChart').getContext('2d');
    const martaChart = new Chart(ctxMarta, {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'TT06 (Ret)', borderColor: '#0d6efd', data: [], tension: 0.3 },
            { label: 'Setpoint', borderColor: '#ffc107', data: [], borderDash: [5, 5] },
            { label: 'TT04 (Heater)', borderColor: '#dc3545', data: [], hidden: true }
        ]},
        options: { 
            responsive: true, 
            maintainAspectRatio: false,
            scales: { x: { display: false }, y: { grid: { color: '#333' } } },
            plugins: { legend: { labels: { color: '#fff' } } }
        }
    });

    const ctxAmb = document.getElementById('ambientChart').getContext('2d');
    const ambientChart = new Chart(ctxAmb, {
        type: 'line',
        data: { labels: [], datasets: [
            { label: 'S1 Temp', borderColor: '#0dcaf0', data: [] },
            { label: 'S1 Dew', borderColor: '#adb5bd', data: [], borderDash: [2, 2] },
            { label: 'S2 Temp', borderColor: '#20c997', data: [] }
        ]},
        options: { 
            responsive: true, 
            maintainAspectRatio: false,
            scales: { x: { display: false }, y: { grid: { color: '#333' } } },
            plugins: { legend: { labels: { color: '#fff' } } }
        }
    });

    const MAX_DATA_POINTS = 50;

    function updateDashboard() {
        fetch('/api/data')
            .then(response => response.json())
            .then(data => {
                document.getElementById('clock').innerText = data.timestamp;

                // Update Values
                const m = data.marta;
                const e = data.esp32;

                document.getElementById('val-tt06').innerText = m.connected ? m.temps.TT06 : "--";
                document.getElementById('val-sp').innerText = m.connected ? m.setpoints.temp : "--";
                document.getElementById('val-dew').innerText = e.connected ? (e.dew_max || "--") : "--";

                // Update Status Dots
                const mDot = document.getElementById('status-marta');
                mDot.className = m.connected ? 'status-dot status-on' : 'status-dot status-off';
                
                const eDot = document.getElementById('status-esp');
                eDot.className = e.connected ? 'status-dot status-on' : 'status-dot status-off';

                // Status Word Interpretation 
                let modeText = "Unknown";
                if(m.status == 1) modeText = "Supply ON";
                else if(m.status == 2) modeText = "Working (Pump ON)";
                else if(m.status == 3) modeText = "ALARM";
                document.getElementById('marta-mode').innerText = m.connected ? modeText : "Disconnected";

                // UPDATE CHARTS
                if (data.timestamp) {
                    // MARTA Chart
                    if (martaChart.data.labels.length > MAX_DATA_POINTS) {
                        martaChart.data.labels.shift();
                        martaChart.data.datasets.forEach(ds => ds.data.shift());
                    }
                    martaChart.data.labels.push(data.timestamp);
                    martaChart.data.datasets[0].data.push(m.temps.TT06);
                    martaChart.data.datasets[1].data.push(m.setpoints.temp);
                    martaChart.data.datasets[2].data.push(m.temps.TT04);
                    martaChart.update('none'); // 'none' for smooth animation

                    // Ambient Chart
                    if (ambientChart.data.labels.length > MAX_DATA_POINTS) {
                        ambientChart.data.labels.shift();
                        ambientChart.data.datasets.forEach(ds => ds.data.shift());
                    }
                    ambientChart.data.labels.push(data.timestamp);
                    ambientChart.data.datasets[0].data.push(e.s1.temp);
                    ambientChart.data.datasets[1].data.push(e.s1.dew);
                    ambientChart.data.datasets[2].data.push(e.s2.temp);
                    ambientChart.update('none');
                }
            });
    }

    // Poll API every 2 seconds
    setInterval(updateDashboard, 2000);
</script>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# --- MAIN ---
if __name__ == "__main__":
    # Start the Data Poller Thread
    t = threading.Thread(target=data_poller_loop, daemon=True)
    t.start()
    
    # Start Web Server
    print("Starting Web Server on http://0.0.0.0:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)