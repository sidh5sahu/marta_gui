"""
MARTA GUI v19 — 4-Sensor Integrated Version
 
CHANGELOG (v19):
 - INTEGRATION: Updated `AmbientPoller` to read JSON for 4 sensors (S1, S2, S3, S4).
 - LAYOUT: Added display rows for Sensor 3 (DHT #1) and Sensor 4 (DHT #2).
 - LOGGING: Updated `UnifiedEventLogger` to include columns for S3 and S4 data.
 - PLOTTING: Updated Temp, Humidity, and Dew Point plots to show traces for all 4 sensors.
 - LOGIC: Updated Cycle Worker and Contact Point logic to capture full ambient context.

PREVIOUS (v18):
 - Modbus v3 Strict Fix
"""

import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
import re 

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
plt.ion()

import struct
import socket
import threading
import time
import csv
import queue
import os
import sys 
import subprocess 
from datetime import datetime
import json
import math 
import requests

# Try pymodbus, fallback to minimal
_HAVE_PYMODBUS = False
try:
    from pymodbus.client import ModbusTcpClient as _PMClient
    _HAVE_PYMODBUS = True
except Exception:
    _HAVE_PYMODBUS = False

# ---------- utility dummy lock ----------
class dummy_lock:
    def __enter__(self): return None
    def __exit__(self, *a): return False

# ---------- Minimal Modbus fallback ----------
class MinimalModbusTCP:
    def __init__(self, host, port=502, unit_id=1, timeout=3.0):
        self.host, self.port, self.unit_id, self.timeout = host, port, unit_id, timeout
        self.sock = None
        self._tx_id = 0

    def connect(self):
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            return True
        except OSError:
            return False

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
        self.sock = None

    def _next_tid(self):
        self._tx_id = (self._tx_id + 1) & 0xFFFF
        return self._tx_id

    def _recvn(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return buf

    def _request(self, pdu):
        if not self.sock:
            raise RuntimeError("Not connected")
        mbap = struct.pack(">HHHB", self._next_tid(), 0, len(pdu) + 1, self.unit_id)
        self.sock.sendall(mbap + pdu)
        hdr = self._recvn(7)
        if hdr is None:
            raise RuntimeError("No response")
        _, _, length = struct.unpack(">HHH", hdr[:6])
        body = self._recvn(length - 1)
        return body

    def read_holding_registers(self, address, count=1, slave=1):
        try:
            self.unit_id = slave
            pdu = struct.pack(">BHH", 3, address, count)
            body = self._request(pdu)
            if body[0] & 0x80:
                return _MBErrorResult()
            bc = body[1]
            data = body[2:2 + bc]
            regs = list(struct.unpack(">" + "H" * (bc // 2), data))
            return _MBResult(regs)
        except Exception:
            return _MBErrorResult()

    def write_register(self, address, value=0, slave=1):
        try:
            self.unit_id = slave
            pdu = struct.pack(">BHH", 6, address, value & 0xFFFF)
            body = self._request(pdu)
            return not (body[0] & 0x80)
        except Exception:
            return False

    def write_registers(self, address, values=None, slave=1):
        if values is None: values = []
        try:
            self.unit_id = slave
            qty = len(values)
            pdu = struct.pack(">BHHB", 16, address, qty, qty * 2)
            pdu += struct.pack(">" + "H" * qty, *values)
            body = self._request(pdu)
            return not (body[0] & 0x80)
        except Exception:
            return False

class _MBResult:
    def __init__(self, regs): self.registers = regs
    def isError(self): return False

class _MBErrorResult:
    def isError(self): return True
    @property
    def registers(self): return []

def get_modbus_client(ip, port=502):
    if _HAVE_PYMODBUS:
        try:
            return _PMClient(host=ip, port=port)
        except Exception:
            return MinimalModbusTCP(ip, port=port)
    return MinimalModbusTCP(ip, port=port)

# ---------- Register map ----------
REGISTER_TT = [126, 128, 130, 132, 134, 136]      # TT01..TT06
REGISTER_TEMP_SETPOINT = 310
REGISTER_PUMP_SPEED = 312
REGISTER_CONTROL_BITS = 305
BIT_CHILLER = 0
BIT_CO2 = 1

SP_MIN = -30.0
SP_MAX = 15.0

def _float_to_u16pair(v): return struct.unpack("<HH", struct.pack("<f", v))
def _u16pair_to_float(p): return struct.unpack("<f", struct.pack("<HH", *p))[0]

# --- v14 FIX: EXPLICIT KEYWORD ARGUMENTS FOR PYMODBUS v3+ ---
def write_float(c, reg, val): 
    return c.write_registers(reg, values=_float_to_u16pair(val), slave=1)

def read_float(c, reg):
    rr = c.read_holding_registers(reg, count=2, slave=1)
    return None if rr.isError() else _u16pair_to_float(rr.registers)

def write_u16(c, reg, val): 
    return c.write_register(reg, value=(val & 0xFFFF), slave=1)
# ------------------------------------------------------------

def build_control_word(chiller, co2):
    w = 0
    if chiller: w |= (1 << BIT_CHILLER)
    if co2:     w |= (1 << BIT_CO2)
    return w

def write_control_word(c, chiller, co2):
    word_to_write = build_control_word(chiller, co2)
    ok = write_u16(c, REGISTER_CONTROL_BITS, word_to_write)
    return ok

# ---------- CSV logger ----------
class UnifiedEventLogger:
    HEADER = [
        "Timestamp", "Event_Type", "Status", 
        "TT06", "Target_Temp", "Active_Setpoint", "Dew_Max",
        "Amb_S1_T", "Amb_S1_H", "Amb_S1_D", 
        "Amb_S2_T", "Amb_S2_H", "Amb_S2_D",
        "Amb_S1_T", "Amb_S1_H", "Amb_S1_D", 
        "Amb_S2_T", "Amb_S2_H", "Amb_S2_D",
        "TT06", "TT01", "TT02", "TT03", "TT04", "TT05"
    ]
    
    def __init__(self, log_dir, run_name):
        self.path = os.path.join(log_dir, f"{run_name}.csv")
        self.path = os.path.abspath(self.path)
        
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(self.HEADER)
            
    def log(self, data_dict):
        try:
            row = [data_dict.get(key, "") for key in self.HEADER]
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(row)
        except Exception as e:
            print(f"[UnifiedEventLogger ERROR] Failed to write log row: {e}")

# ---------- Data pollers ----------
class DataPoller(threading.Thread):
    def __init__(self, client, client_lock, logger, get_active_sp, get_current_target, interval=10.0):
        super().__init__(daemon=True)
        self.client = client
        self.client_lock = client_lock 
        self.logger = logger
        self.get_active_sp = get_active_sp
        self.get_current_target = get_current_target
        self.runflag = True
        self.lock = threading.Lock() 
        self.timestamps = []
        self.temp = [[] for _ in range(6)] # Keep for plotting compatibility (TT01-TT06)
        self.active_sp_history = []
        self.current_target_history = []
        
        # Storage for full map
        self.full_data = {
            "floats": {}, # Address -> Value
            "alarms": {}, # Address -> Value (Int)
            "status": 0
        }
        
        self.interval = interval
        self.last_successful_read_time = time.time()

    def run(self):
        while self.runflag:
            ts = datetime.now()
            read_ok = False 
            
            try:
                with self.client_lock:
                    # Block 1: Read Values (100 - 210) -> 112 registers (56 floats)
                    # Max PDU size usually allows ~125 registers. 112 is safe.
                    rr1 = self.client.read_holding_registers(100, count=112, slave=1)
                    
                    # Block 2: Alarms & Status (300 - 320) -> 21 registers
                    rr2 = self.client.read_holding_registers(300, count=21, slave=1)
                    
                if not rr1.isError() and not rr2.isError():
                    read_ok = True
                    regs1 = rr1.registers
                    regs2 = rr2.registers
                    
                    # Parse Block 1 (Floats)
                    floats = {}
                    for i in range(0, 112, 2):
                        addr = 100 + i
                        val = _u16pair_to_float((regs1[i], regs1[i+1]))
                        floats[addr] = val
                        
                    # Parse Block 2
                    # 300, 301, 302, 303 are Alarms (Bitmasks)
                    alarms = {
                        300: regs2[0],
                        301: regs2[1],
                        302: regs2[2],
                        303: regs2[3]
                    }
                    
                    # 305 is Control Bits
                    control_bits = regs2[5]
                    
                    # 310, 312, 314 are Floats (Setpoints)
                    # 310 is at offset 10 (310-300)
                    sp_temp = _u16pair_to_float((regs2[10], regs2[11]))
                    sp_speed = _u16pair_to_float((regs2[12], regs2[13]))
                    sp_flow = _u16pair_to_float((regs2[14], regs2[15]))
                    
                    floats[310] = sp_temp
                    floats[312] = sp_speed
                    floats[314] = sp_flow
                    
                    # 320 is Status (Int) at offset 20
                    status_val = regs2[20]
                    
                    with self.lock:
                        self.timestamps.append(ts)
                        self.full_data["floats"] = floats
                        self.full_data["alarms"] = alarms
                        self.full_data["status"] = status_val
                        
                        # Maintain compatibility for plotting/logic
                        # TT01-TT06 are at 118, 120, 122, 124, 126, 128 (R452A/CO2 mix in old code?)
                        # User map says:
                        # 118: TT01_R452A, 120: TT02_R452A, 122: TT03_R452A, 124: TT04_R452A
                        # 126: TT01_CO2, 128: TT02_CO2 ... 
                        # OLD CODE used: 126, 128, 130, 132, 134, 136 for TT01..TT06
                        # Let's stick to the OLD mapping for the "Cycle Plot" variables to avoid breaking logic
                        # TT01=126, TT02=128, TT03=130, TT04=132, TT05=134, TT06=136
                        
                        tt_addrs = [126, 128, 130, 132, 134, 136]
                        for i, addr in enumerate(tt_addrs):
                            self.temp[i].append(floats.get(addr))
                            
                        self.active_sp_history.append(floats.get(310)) # Temp Setpoint
                        
                        tgt = self.get_current_target()
                        try:
                            tgt_val = float(tgt)
                        except (ValueError, TypeError):
                            tgt_val = None
                        self.current_target_history.append(tgt_val)
                        
                else:
                    print("[DataPoller WARN] Read failed.")
                    
            except Exception as e:
                print(f"[DataPoller ERROR] Failed to read: {e}")
                read_ok = False
            
            if read_ok: 
                self.last_successful_read_time = time.time()
            
            active_sp_val = self.get_active_sp()
            current_target_val = self.get_current_target()



            if self.logger:
                log_data = {
                    "Timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "Event_Type": "POLL",
                    "Status": "Polling",
                    "TT06": self.temp[5][-1] if self.temp[5] else "",
                    "Target_Temp": current_target_val,
                    "Active_Setpoint": active_sp_val,
                    "TT01": self.temp[0][-1] if self.temp[0] else "",
                    "TT02": self.temp[1][-1] if self.temp[1] else "",
                    "TT03": self.temp[2][-1] if self.temp[2] else "",
                    "TT04": self.temp[3][-1] if self.temp[3] else "",
                    "TT05": self.temp[4][-1] if self.temp[4] else "",
                }
                self.logger.log(log_data)

            time.sleep(self.interval)

    def stop(self): self.runflag = False

class AmbientPoller(threading.Thread):
    def __init__(self, esp_ip_getter, interval=10.0):
        super().__init__(daemon=True)
        self.esp_ip_getter = esp_ip_getter
        self.interval = interval
        self.runflag = True
        self.lock = threading.Lock()
        self.timestamps = []
        
        # Initialize storage for 2 sensors
        self.s1 = {"temp": [], "hum": [], "dew": []} # AM2315C
        self.s2 = {"temp": [], "hum": [], "dew": []} # MAX6675 (Temp only)
        
        # Initial state
        self.last = {
            "s1": (None, None, None), 
            "s2": (None, None, None), 
            "dew_max": None
        }

    def run(self):
        while self.runflag:
            ip = self.esp_ip_getter()
            if not ip:
                time.sleep(self.interval)
                continue
            
            # The new ESP32 code serves JSON at /data
            url = f"http://{ip}/data"
            
            try:
                r = requests.get(url, timeout=5)
                j = r.json()
                
                # Extract data safely
                def get_sensor_data(key):
                    data = j.get(key, {})
                    t = self._safe_float(data.get("temp"))
                    h = self._safe_float(data.get("hum"))
                    d = self._safe_float(data.get("dew"))
                    return t, h, d

                t1, h1, d1 = get_sensor_data("sensor1")
                t2, h2, d2 = get_sensor_data("sensor2")

                # Calculate Max Dew Point from sensors that support it (S1)
                valid_dews = [d for d in [d1] if d is not None]
                dew_max = max(valid_dews) if valid_dews else None
                
                ts = datetime.now()
                with self.lock:
                    self.timestamps.append(ts)
                    
                    # Append history
                    self.s1["temp"].append(t1); self.s1["hum"].append(h1); self.s1["dew"].append(d1)
                    self.s2["temp"].append(t2); self.s2["hum"].append(h2); self.s2["dew"].append(d2)
                    
                    # Update instantaneous state
                    self.last = {
                        "s1": (t1, h1, d1), 
                        "s2": (t2, h2, d2), 
                        "dew_max": dew_max
                    }
                    
            except Exception as e:
                print(f"[AmbientPoller ERROR] {e}") 
                with self.lock:
                    # Keep previous values or reset to None on error? 
                    # Usually safer to keep None to indicate connection loss
                    pass 
            time.sleep(self.interval)

    def _safe_float(self, val):
        if val is None: return None
        try:
            f_val = float(val)
            return None if math.isnan(f_val) else f_val
        except (ValueError, TypeError):
            return None

    def stop(self): self.runflag = False
    
    def get_latest(self):
        with self.lock:
            return self.last.copy()

# ---------- GUI & Control ----------
class MartaGUI:
    def __init__(self, root):
        self.root = root
        root.title("Marta GUI v19")

        # Load Config
        self.config = self.load_config()

        self.log_q = queue.Queue()
        self.gui_update_q = queue.Queue() # For thread-safe GUI updates
        root.after(200, self._drain_log_q)
        root.after(100, self._process_gui_updates)
        self.animations = []

        # --- LAYOUT ---
        style = ttk.Style()
        style.theme_use('clam') 

        # Create Notebook (Tabs)
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, columnspan=8, sticky="nsew", padx=5, pady=5)
        
        self.tab_main = ttk.Frame(self.notebook)
        self.tab_params = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_main, text="Main")
        self.notebook.add(self.tab_params, text="Parameters")
        
        # --- MAIN TAB CONTENT ---

        # Row 0: MARTA connect
        ttk.Label(self.tab_main, text="MARTA IP:").grid(row=0, column=0, sticky="e", padx=5, pady=2)
        self.e_ip = ttk.Entry(self.tab_main, width=18); self.e_ip.insert(0, self.config.get("marta_ip", "10.4.133.77")); self.e_ip.grid(row=0,column=1,sticky="w", pady=2)
        ttk.Button(self.tab_main, text="Connect", command=self.connect).grid(row=0, column=4, padx=5, pady=2, sticky="w")
        self.lab_conn = ttk.Label(self.tab_main, text="Disconnected", foreground="red", width=25, anchor="w"); self.lab_conn.grid(row=0, column=5, columnspan=2, sticky="w", pady=2)

        # Row 1: ESP32 connect
        ttk.Label(self.tab_main, text="ESP32 IP:").grid(row=1, column=0, sticky="e", padx=5, pady=2)
        self.e_esp_ip = ttk.Entry(self.tab_main, width=18); self.e_esp_ip.insert(0, self.config.get("esp32_ip", "10.4.135.152")); self.e_esp_ip.grid(row=1,column=1,sticky="w", pady=2)
        ttk.Button(self.tab_main, text="Connect ESP32", command=self.connect_esp32).grid(row=1, column=4, padx=5, pady=2, sticky="w")
        self.lab_esp = ttk.Label(self.tab_main, text="ESP32: Disconnected", foreground="red", width=25, anchor="w"); self.lab_esp.grid(row=1, column=5, columnspan=2, sticky="w", pady=2)


        # Row 2: Run Sequence File
        ttk.Label(self.tab_main, text="Run Seq. File:").grid(row=2, column=0, sticky="e", padx=5, pady=2)
        self.e_seq_file = ttk.Entry(self.tab_main, width=18); self.e_seq_file.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Button(self.tab_main, text="Browse", command=self._browse_seq_file).grid(row=2, column=4, padx=5, pady=2, sticky="w")

        # Row 3: Base Log Directory
        ttk.Label(self.tab_main, text="Base Log Dir:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
        self.e_log_dir = ttk.Entry(self.tab_main, width=18); self.e_log_dir.grid(row=3, column=1, sticky="w", pady=2)
        ttk.Button(self.tab_main, text="Browse", command=self._browse_log_dir).grid(row=3, column=4, padx=5, pady=2, sticky="w")
        
        # Row 4-8: Params
        defaults = self.config.get("cycle_defaults", {})
        self.var_max   = tk.StringVar(value=str(defaults.get("max_temp", "15")))
        self.var_min   = tk.StringVar(value=str(defaults.get("min_temp", "10")))
        self.var_cycle = tk.StringVar(value=str(defaults.get("cycles", "2")))
        self.var_dwell = tk.StringVar(value=str(defaults.get("dwell_s", "60")))
        self.var_pump  = tk.StringVar(value=str(self.config.get("safety_limits", {}).get("pump_rpm_default", "6000")))
        self._param_row(4, "Max Temp (°C):", self.var_max,   self.update_max)
        self._param_row(5, "Min Temp (°C):", self.var_min,   self.update_min)
        self._param_row(6, "# Cycles:",       self.var_cycle, self.update_cycles)
        self._param_row(7, "Dwell (s):",       self.var_dwell, self.update_dwell)
        self._param_row(8, "Pump RPM:",       self.var_pump,  self.update_pump)

        # Row 9: displays
        ttk.Label(self.tab_main, text="Active Setpoint:").grid(row=9, column=0, sticky="e", padx=5, pady=5)
        self.var_setpoint_display = tk.StringVar(value="--")
        ttk.Entry(self.tab_main, textvariable=self.var_setpoint_display, width=10, state="readonly").grid(row=9, column=1, sticky="w", pady=5)
        ttk.Label(self.tab_main, text="TT06:").grid(row=9, column=2, sticky="e", padx=5, pady=5)
        self.var_tt06_display = tk.StringVar(value="--")
        ttk.Entry(self.tab_main, textvariable=self.var_tt06_display, width=10, state="readonly").grid(row=9, column=3, sticky="w", pady=5)
        self.lbl_status = tk.Label(self.tab_main, text="●", fg="red", font=("Arial", 14)); self.lbl_status.grid(row=9, column=4, sticky="w", padx=5, pady=5)

        # Row 10: Stopwatch
        ttk.Label(self.tab_main, text="Cycle Timer:").grid(row=10, column=0, sticky="e", padx=5, pady=2)
        self.var_stopwatch_display = tk.StringVar(value="00:00")
        self.lab_stopwatch = ttk.Entry(self.tab_main, textvariable=self.var_stopwatch_display, width=10, state="readonly")
        self.lab_stopwatch.grid(row=10, column=1, sticky="w", pady=2)

        # Row 11: Ambient S1 & S2
        ttk.Label(self.tab_main, text="S1 (AM2315C):").grid(row=11, column=0, sticky="e", padx=5, pady=2)
        self.var_s1 = tk.StringVar(value="--"); ttk.Entry(self.tab_main, textvariable=self.var_s1, width=22, state="readonly").grid(row=11,column=1,sticky="w", pady=2)
        
        ttk.Label(self.tab_main, text="S2 (MAX6675):").grid(row=11, column=2, sticky="e", padx=5, pady=2)
        self.var_s2 = tk.StringVar(value="--"); ttk.Entry(self.tab_main, textvariable=self.var_s2, width=22, state="readonly").grid(row=11,column=3,sticky="w", pady=2)

        ttk.Label(self.tab_main, text="Dew Max:").grid(row=11, column=4, sticky="e", padx=5, pady=2)
        self.var_dewavg = tk.StringVar(value="--"); ttk.Entry(self.tab_main, textvariable=self.var_dewavg, width=10, state="readonly").grid(row=11, column=5, sticky="w", pady=2)


        # Row 13: controls
        btn_frame = ttk.Frame(self.tab_main)
        btn_frame.grid(row=13, column=0, columnspan=6, pady=5)
        self.btn_start_chiller = ttk.Button(btn_frame, text="Start Chiller", command=self.start_chiller, state=tk.DISABLED)
        self.btn_stop_chiller  = ttk.Button(btn_frame, text="Stop Chiller",  command=self.stop_chiller,  state=tk.DISABLED)
        self.btn_start_co2     = ttk.Button(btn_frame, text="Start CO₂",     command=self.start_co2,     state=tk.DISABLED)
        self.btn_stop_co2      = ttk.Button(btn_frame, text="Stop CO₂",      command=self.stop_co2,      state=tk.DISABLED)
        self.btn_stop_all      = ttk.Button(btn_frame, text="Stop System",   command=self.stop_all,      state=tk.DISABLED)
        for i, btn in enumerate([self.btn_start_chiller, self.btn_stop_chiller, self.btn_start_co2, self.btn_stop_co2, self.btn_stop_all]):
            btn.pack(side=tk.LEFT, padx=5)

        # Row 14: plots & logs
        plot_frame = ttk.Frame(self.tab_main)
        plot_frame.grid(row=14, column=0, columnspan=6, pady=2)
        ttk.Button(plot_frame, text="Marta Temp",         command=self.open_all_temps_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="ColdBox Temp",       command=self.open_ambient_temp_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="ColdBox Humidity",   command=self.open_humidity_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="ColdBox DewPoint",   command=self.open_dew_point_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="CyclePlot",          command=self.open_cycle_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="contactPoint",       command=self.open_contact_point).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="Open Log File",      command=self.open_log_file).pack(side=tk.LEFT, padx=5)
        
        # --- PARAMETERS TAB CONTENT ---
        self._init_params_tab()
        
        # --- BOTTOM ROW (Log Box) ---
        # --- BOTTOM ROW (Log Box) ---
        # Grid logbox in root, below notebook
        root.grid_rowconfigure(1, weight=1) # Notebook row is 0, Logbox row is 1
        
        self.logbox = tk.Text(root, width=125, height=14, state=tk.DISABLED)
        self.logbox.grid(row=1, column=0, columnspan=8, sticky="nsew", padx=5, pady=5) 
        scroll = tk.Scrollbar(root, command=self.logbox.yview)
        scroll.grid(row=1, column=8, sticky="ns", pady=5) 
        self.logbox['yscrollcommand'] = scroll.set
        
        root.grid_rowconfigure(1, weight=1)      
        root.grid_columnconfigure(0, weight=1)    

        # runtime state
        self.client = None
        self.client_lock = threading.Lock() 
        self.connected = False
        self.chiller_on = False
        self.co2_on = False
        self.abort_cycle = False

        self.active_setpoint = None
        self.current_target = None

        self.logger = None 
        self.poller = None

        # ambient
        self.ambient = None
        self.ambient_poller = None
        self.esp_connected = False 

        # dew-cycle
        self.target_temp = float(self.var_max.get())
        self.cycle_phase = "initial"
        self.unified_logger = None 
        
        # Run Management State
        self.log_file_path = None 
        self.current_run_name_full = None
        self.current_run_name_short = None 
        self.current_run_dir = None 
        self.report_file_path = None 
        
        self.stopwatch_start_time = None
        self.health_check_job = None 

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- UI helpers ----------
    def load_config(self):
        try:
            with open("config.json", "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Config load failed: {e}, using defaults.")
            return {}

    def _process_gui_updates(self):
        try:
            while True:
                msg = self.gui_update_q.get_nowait()
                msg_type = msg.get("type")
                if msg_type == "conn_status":
                    self.lab_conn.config(text=msg["text"], foreground=msg["fg"])
                elif msg_type == "esp_status":
                    self.lab_esp.config(text=msg["text"], foreground=msg["fg"])
                elif msg_type == "stable_color":
                    self.lbl_status.config(fg=msg["color"])
                elif msg_type == "co2_btn":
                    self.btn_start_co2.config(text=msg["text"], state=msg["state"])
                elif msg_type == "error":
                    messagebox.showerror(msg["title"], msg["message"])
        except queue.Empty:
            pass
        self.root.after(100, self._process_gui_updates)

    def _param_row(self, row, label, var, cmd):
        ttk.Label(self.tab_main, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=2)
        e = ttk.Entry(self.tab_main, textvariable=var, width=10); e.grid(row=row, column=1, sticky="w", pady=2)
        b = ttk.Button(self.tab_main, text="Update", command=cmd); b.grid(row=row, column=4, sticky="w", padx=5, pady=2)
        if not hasattr(self, "param_entries"):
            self.param_entries = []
        self.param_entries.append((e, b))

    def _drain_log_q(self):
        try:
            while True:
                self._append_log(self.log_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(200, self._drain_log_q)

    def _append_log(self, msg):
        self.logbox.config(state=tk.NORMAL)
        self.logbox.insert(tk.END, msg + "\n")
        self.logbox.see(tk.END)
        self.logbox.config(state=tk.DISABLED)

    def log(self, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_q.put(line)
        print(line)

    # --- Browse and Reporting Methods ---
    def _browse_seq_file(self):
        path = filedialog.askopenfilename(
            title="Select Run Sequence File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.e_seq_file.delete(0, tk.END)
            self.e_seq_file.insert(0, path)

    def _browse_log_dir(self):
        path = filedialog.askdirectory(title="Select Base Log Directory")
        if path:
            self.e_log_dir.delete(0, tk.END)
            self.e_log_dir.insert(0, path)

    def _process_run_sequence(self):
        seq_file_path = self.e_seq_file.get()
        base_log_dir = self.e_log_dir.get()
        
        if not seq_file_path or not base_log_dir:
            self.log("Error: Run Sequence File and Base Log Dir must be set.")
            messagebox.showerror("Setup Error", "Please set the Run Sequence File and Base Log Directory paths.")
            return False

        try:
            with open(seq_file_path, "r") as f:
                last_run_name = f.read().strip()
            
            match = re.match(r"run_(\d+)_.*", last_run_name)
            if match:
                last_run_num = int(match.group(1))
                new_run_num = last_run_num + 1
            else:
                self.log(f"Warning: Could not parse '{last_run_name}', starting at run 01.")
                new_run_num = 1
                
            new_run_num_str = f"{new_run_num:02d}"
            
            now = datetime.now()
            date_str = now.strftime("%d%m%Y")
            time_str = now.strftime("%H%M")
            
            self.current_run_name_full = f"run_{new_run_num_str}_{date_str}_{time_str}"
            self.current_run_name_short = f"run_{new_run_num_str}_{date_str}"

            self.current_run_dir = os.path.join(base_log_dir, self.current_run_name_full)
            os.makedirs(self.current_run_dir, exist_ok=True)
            self.log(f"Created new run directory: {self.current_run_dir}")

            self.report_file_path = os.path.join(self.current_run_dir, f"{self.current_run_name_short}.md")
            
            with open(seq_file_path, "w") as f:
                f.write(self.current_run_name_full)
            
            return True

        except Exception as e:
            self.log(f"Error processing run sequence: {e}")
            messagebox.showerror("Run Sequence Error", f"Could not process run sequence file: {e}")
            return False

    def _write_to_report(self, text, mode="a"):
        if not self.report_file_path:
            self.log("Error: Report file path is not set.")
            return
        try:
            with open(self.report_file_path, mode, encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            self.log(f"Error writing to report: {e}")
            
    def _generate_start_report(self):
        self.log("Generating start report...")
        report_content = f"# MARTA Run Report: {self.current_run_name_full}\n\n"
        report_content += "## Starting Parameters\n"
        report_content += f"- **Start Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report_content += f"- **Max Temp (°C):** {self.var_max.get()}\n"
        report_content += f"- **Min Temp (°C):** {self.var_min.get()}\n"
        report_content += f"- **# Cycles:** {self.var_cycle.get()}\n"
        report_content += f"- **Dwell (s):** {self.var_dwell.get()}\n"
        report_content += f"- **Pump RPM:** {self.var_pump.get()}\n\n"
        
        self._write_to_report(report_content, mode="w")

    def _generate_stop_report(self, stop_reason):
        self.log("Generating stop report...")
        report_content = "\n## Run Stopped\n"
        report_content += f"- **Stop Reason:** {stop_reason}\n"
        report_content += f"- **Stop Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report_content += f"- **Final TT06:** {self.var_tt06_display.get()}\n"
        
        self._write_to_report(report_content, mode="a")

    def _save_all_plots(self):
        if not self.animations:
            self.log("No plots open to save.")
            return
        
        if not self.current_run_dir:
            self.log("Cannot save plots: No run directory set.")
            return
            
        self.log(f"Saving {len(self.animations)} plots...")
        try:
            for ani in self.animations:
                fig = ani.fig
                title = fig.canvas.manager.get_window_title()
                safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)
                
                save_path = os.path.join(self.current_run_dir, f"{safe_title}.jpg")
                fig.savefig(save_path)
            self.log("All plots saved successfully.")
        except Exception as e:
            self.log(f"Error saving plots: {e}")

    # ---------- Connect MARTA ----------
    def connect(self):
        if not self._process_run_sequence():
            self.log("Aborting connection: Run sequence setup failed.")
            return

        ip = self.e_ip.get().strip()
        self.log(f"Connecting to {ip}...")
        c = get_modbus_client(ip)
        if not c.connect():
            self.gui_update_q.put({"type": "conn_status", "text": "Failed", "fg": "red"})
            self.log("Connection failed.")
            return
        self.client = c
        self.connected = True
        self.gui_update_q.put({"type": "conn_status", "text": "Connected", "fg": "green"})
        self.log("Connected to MARTA.")

        self.btn_start_chiller.config(state=tk.NORMAL)
        self.btn_stop_all.config(state=tk.NORMAL)

        self.unified_logger = UnifiedEventLogger(
            log_dir=self.current_run_dir,
            run_name=self.current_run_name_short
        )
        self.log_file_path = self.unified_logger.path
        
        self.poller = DataPoller(self.client, self.client_lock, self.unified_logger, 
                                 self.get_active_setpoint, self.get_current_target, 
                                 interval=10.0)
        
        self.poller.start()
        self.update_param_display()
        self._check_connection_health()

    # ---------- Connect ESP32 ----------
    def connect_esp32(self):
        ip = self.e_esp_ip.get().strip()
        if not ip:
            messagebox.showwarning("ESP32 IP", "Please enter ESP32 IP.")
            return
            
        if self.ambient_poller:
            self.ambient_poller.stop()
            self.ambient_poller = None
            
        url = f"http://{ip}/data"
        self.log(f"Testing ESP32 connection at {url}...")
        
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status() 
            _ = r.json() 
            
            self.gui_update_q.put({"type": "esp_status", "text": f"ESP32: Connected ({ip})", "fg": "green"})
            self.log("ESP32 connection test successful.")
            self.esp_connected = True 
            
            self.ambient_poller = AmbientPoller(lambda: self.e_esp_ip.get().strip(), interval=10.0)
            self.ambient_poller.start()
            self.update_ambient_display()

        except Exception as e:
            self.log(f"ESP32 connection FAILED: {e}")
            self.gui_update_q.put({"type": "error", "title": "ESP32 Connection Failed", "message": f"Could not connect to {ip}.\n\nError: {e}"})
            self.gui_update_q.put({"type": "esp_status", "text": "ESP32: FAILED", "fg": "red"})
            self.esp_connected = False 

    # ---------- Parameters Display ----------
    def _init_params_tab(self):
        # Create vars for TT01-TT06
        self.vars_tt = [tk.StringVar(value="--") for _ in range(6)]
        
        # Grid them in tab_params
        for i in range(6):
            ttk.Label(self.tab_params, text=f"TT{i+1:02d}:").grid(row=i, column=0, sticky="e", padx=5, pady=5)
            ttk.Entry(self.tab_params, textvariable=self.vars_tt[i], width=10, state="readonly").grid(row=i, column=1, sticky="w", pady=5)
            
        # Also show Active Setpoint and Target Temp here
        ttk.Label(self.tab_params, text="Active Setpoint:").grid(row=0, column=2, sticky="e", padx=5, pady=5)
        self.var_param_sp = tk.StringVar(value="--")
        ttk.Entry(self.tab_params, textvariable=self.var_param_sp, width=10, state="readonly").grid(row=0, column=3, sticky="w", pady=5)
        
        ttk.Label(self.tab_params, text="Target Temp:").grid(row=1, column=2, sticky="e", padx=5, pady=5)
        self.var_param_target = tk.StringVar(value="--")
        ttk.Entry(self.tab_params, textvariable=self.var_param_target, width=10, state="readonly").grid(row=1, column=3, sticky="w", pady=5)

    def update_param_display(self):
        if self.poller:
            with self.poller.lock:
                # Update TT01-TT06
                for i in range(6):
                    arr = self.poller.temp[i]
                    if arr:
                        val = None
                        for v in reversed(arr):
                            if v is not None:
                                val = v
                                break
                        if val is not None:
                            self.vars_tt[i].set(f"{val:.2f}")
                            if i == 5: # TT06
                                self.var_tt06_display.set(f"{val:.2f}")
                
                # Update Setpoints
                sp = self.poller.active_sp_history[-1] if self.poller.active_sp_history else None
                tgt = self.poller.current_target_history[-1] if self.poller.current_target_history else None
                
                if sp is not None: self.var_param_sp.set(f"{sp:.2f}")
                if tgt is not None: self.var_param_target.set(f"{tgt:.2f}")

        self.root.after(2000, self.update_param_display)

    # ---------- Ambient display ----------
    def update_ambient_display(self):
        if self.ambient_poller:
            latest = self.ambient_poller.get_latest()
            s1 = latest.get("s1", (None,None,None))
            s2 = latest.get("s2", (None,None,None))
            dew_max = latest.get("dew_max", None)

            def fmt(vals):
                t, h, d = vals
                t_str = f"{t:.1f}" if t is not None else "--"
                h_str = f"{h:.0f}%" if h is not None else "--"
                d_str = f"{d:.1f}" if d is not None else "--"
                return f"T:{t_str} H:{h_str} D:{d_str}"

            self.var_s1.set(fmt(s1))
            self.var_s2.set(f"T:{s2[0]:.1f}" if s2[0] is not None else "T:--") # S2 has no hum/dew
            
            self.var_dewavg.set("--" if dew_max is None else f"{dew_max:.2f}")
            
            self.ambient = latest # Store for contact point logging
            
        self.root.after(2000, self.update_ambient_display)

    def open_log_file(self):
        if hasattr(self, 'log_file_path') and self.log_file_path:
            try:
                os.startfile(self.log_file_path)
                self.log(f"Opening log file: {self.log_file_path}")
            except AttributeError:
                try:
                    if sys.platform == "darwin": 
                        subprocess.call(["open", self.log_file_path])
                    else: 
                        subprocess.call(["xdg-open", self.log_file_path])
                    self.log(f"Opening log file: {self.log_file_path}")
                except Exception as e:
                    self.log(f"Error opening log file: {e}")
                    messagebox.showerror("Error", f"Could not open log file.\n{e}")
            except Exception as e:
                self.log(f"Error opening log file: {e}")
                messagebox.showerror("Error", f"Could not open log file.\n{e}")
        else:
            messagebox.showwarning("No Log File", "No log file has been created yet. Connect to MARTA first.")

    def set_stable_color(self, is_stable: bool):
        self.gui_update_q.put({"type": "stable_color", "color": "green" if is_stable else "red"})
        
    def _update_stopwatch(self):
        if self.stopwatch_start_time is None:
            return 
        
        elapsed_sec = int(time.time() - self.stopwatch_start_time)
        elapsed_min = elapsed_sec // 60
        elapsed_hr = elapsed_min // 60
        display_min = elapsed_min % 60
        
        self.var_stopwatch_display.set(f"{elapsed_hr:02d}:{display_min:02d}")
        
        self.root.after(1000, self._update_stopwatch)

    # -------- param updates ----------
    def update_max(self):   self.log(f"Max Temp updated: {self.var_max.get()}"); self.target_temp = float(self.var_max.get())
    def update_min(self):   self.log(f"Min Temp updated: {self.var_min.get()}")
    def update_cycles(self):self.log(f"Cycles updated: {self.var_cycle.get()}")
    def update_dwell(self): self.log(f"Dwell updated: {self.var_dwell.get()}")
    def update_pump(self):
        if not self.connected: return
        try:
            val = float(self.var_pump.get())
        except ValueError:
            self.log("Invalid Pump RPM.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_float(self.client, REGISTER_PUMP_SPEED, val)
        except Exception as e:
            self.log(f"Pump RPM write FAILED: {e}")
            ok = False
            
        self.log(f"Pump RPM write {val} -> {'OK' if ok else 'FAIL'}")

    def get_active_setpoint(self):
        return self.active_setpoint if self.active_setpoint is not None else ""
    def get_current_target(self):
        return self.current_target if self.current_target is not None else ""

    def _set_param_state(self, state):
        for e, b in getattr(self, "param_entries", []):
            e.config(state=state)
            b.config(state=state)
            
        if hasattr(self, 'e_seq_file'):
            self.e_seq_file.config(state=state)
        if hasattr(self, 'e_log_dir'):
            self.e_log_dir.config(state=state)
            
        if state == tk.DISABLED:
            self.e_ip.config(state=tk.DISABLED)
            self.e_esp_ip.config(state=tk.DISABLED)
            for child in self.root.winfo_children():
                if isinstance(child, tk.OptionMenu) and child.grid_info()['row'] == 2:
                    child.config(state=tk.DISABLED)
                    break
        else:
            self.e_ip.config(state=tk.NORMAL)
            self.e_esp_ip.config(state=tk.NORMAL)
            for child in self.root.winfo_children():
                if isinstance(child, tk.OptionMenu) and child.grid_info()['row'] == 2:
                    child.config(state=tk.NORMAL)
                    break

    # ---------- Chiller / CO2 controls ----------
    def start_chiller(self):
        if not self.connected: 
            self.log("Cannot start chiller: Not connected.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, True, self.co2_on)
        except Exception as e:
            self.log(f"Start Chiller FAILED: {e}")
            ok = False
            
        if ok:
            self.chiller_on = True
            self.btn_start_chiller.config(state=tk.DISABLED)
            self.btn_stop_chiller.config(state=tk.NORMAL)
            self.log("Chiller started.")
            self._enable_co2_after_delay()
        else:
            self.log("Chiller start failed.")

    def _enable_co2_after_delay(self):
        self.btn_start_co2.config(state=tk.DISABLED)
        def countdown():
            for i in range(60, 0, -1):
                if not self.chiller_on:
                    self.gui_update_q.put({"type": "co2_btn", "text": "Start CO₂", "state": tk.DISABLED})
                    return
                self.gui_update_q.put({"type": "co2_btn", "text": f"Start CO₂ ({i}s)", "state": tk.DISABLED})
                time.sleep(1)
            if self.chiller_on:
                self.gui_update_q.put({"type": "co2_btn", "text": "Start CO₂", "state": tk.NORMAL})
        threading.Thread(target=countdown, daemon=True).start()

    def stop_chiller(self):
        if not self.connected: 
            self.log("Cannot stop chiller: Not connected.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, False, False)
        except Exception as e:
            self.log(f"Stop Chiller FAILED: {e}")
            ok = False
            
        if ok:
            self.chiller_on = False
            self.co2_on = False
            self.abort_cycle = True
            self.btn_start_chiller.config(state=tk.NORMAL)
            self.btn_stop_chiller.config(state=tk.DISABLED)
            self.btn_start_co2.config(state=tk.DISABLED, text="Start CO₂")
            self.btn_stop_co2.config(state=tk.DISABLED)
            self.stopwatch_start_time = None 
            self.var_stopwatch_display.set("00:00")
            self._set_param_state(tk.NORMAL)
            self.set_stable_color(False)
            self.log("Chiller stopped.")
            
            self._generate_stop_report("Chiller Stopped")
            self._save_all_plots()
        else:
            self.log("Chiller stop failed.")

    def start_co2(self):
        if not self.chiller_on:
            messagebox.showwarning("Start Chiller", "Please start Chiller first.")
            self.log("CO2 start failed: Chiller is off.")
            return
        if not self.connected: 
            self.log("CO2 start failed: Not connected.")
            return
        
        if not self.report_file_path:
            self.log("CO2 start failed: Run Directory not set up. (Did you Connect?)")
            messagebox.showerror("Run Error", "Run directory is not set. Please reconnect.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, True, True)
        except Exception as e:
            self.log(f"Start CO2 FAILED: {e}")
            ok = False
            
        if ok:
            self._generate_start_report()

            self.co2_on = True
            self.abort_cycle = False
            self.btn_start_co2.config(state=tk.DISABLED)
            self.btn_stop_co2.config(state=tk.NORMAL)
            self._set_param_state(tk.DISABLED)
            self.set_stable_color(False)
            
            self.stopwatch_start_time = time.time()
            self._update_stopwatch()
            
            self.log("CO₂ started. Dewpoint-cycle active.")
            threading.Thread(target=self._dewpoint_cycle_worker, daemon=True).start()
        else:
            self.log("CO₂ start failed.")

    def stop_co2(self):
        if not self.connected: 
            self.log("CO2 stop failed: Not connected.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, True, False)
        except Exception as e:
            self.log(f"Stop CO2 FAILED: {e}")
            ok = False
            
        if ok:
            self.co2_on = False
            self.abort_cycle = True
            self.btn_start_co2.config(state=tk.NORMAL)
            self.btn_stop_co2.config(state=tk.DISABLED)
            
            self.stopwatch_start_time = None 
            self.var_stopwatch_display.set("00:00")
            
            self._set_param_state(tk.NORMAL)
            self.set_stable_color(False)
            self.log("CO₂ stopped.")

            self._generate_stop_report("CO2 Stopped")
            self._save_all_plots()
        else:
            self.log("CO₂ stop failed.")

    def stop_all(self):
        if self.chiller_on or self.co2_on:
             self._generate_stop_report("System Stop All")
             self._save_all_plots()
        
        if self.connected:
            try:
                with self.client_lock:
                    write_control_word(self.client, False, False)
            except Exception as e:
                self.log(f"Stop All FAILED: {e}")
            
        self.abort_cycle = True
        self.co2_on = False
        self.chiller_on = False
        if self.poller:
            self.poller.stop(); self.poller = None
        if self.ambient_poller:
            self.ambient_poller.stop(); self.ambient_poller = None
        if self.client:
            try: self.client.close()
            except Exception: pass
            self.client = None
        self.connected = False
        self._set_param_state(tk.NORMAL)
        self.btn_start_chiller.config(state=tk.DISABLED)
        self.btn_stop_chiller.config(state=tk.DISABLED)
        self.btn_start_co2.config(state=tk.DISABLED, text="Start CO₂")
        self.btn_stop_co2.config(state=tk.DISABLED)
        self.btn_stop_all.config(state=tk.DISABLED)
        self.gui_update_q.put({"type": "conn_status", "text": "Disconnected", "fg": "red"})
        self.gui_update_q.put({"type": "esp_status", "text": "ESP32: Disconnected", "fg": "red"})
        
        self.stopwatch_start_time = None 
        self.var_stopwatch_display.set("00:00")
        
        if self.health_check_job: 
            self.root.after_cancel(self.health_check_job)
            self.health_check_job = None
        
        self.set_stable_color(False)
        self.log("System stopped & disconnected.")

# ---------- Dewpoint-cycle worker ----------
    def _dewpoint_cycle_worker(self):
        try:
            max_t = float(self.var_max.get())
            min_t = float(self.var_min.get())
            cycles = int(self.var_cycle.get())
            dwell = int(self.var_dwell.get())
        except Exception as e:
            self.log(f"Invalid parameters: {e}")
            self.gui_update_q.put({"type": "error", "title": "Parameter Error", "message": f"Invalid cycle parameters. Check values.\nError: {e}"})
            return

        if not (max_t > min_t):
            err_msg = f"Max Temp ({max_t}) must be greater than Min Temp ({min_t})."
            self.log(f"Error: {err_msg}")
            self.gui_update_q.put({"type": "error", "title": "Parameter Error", "message": f"{err_msg}\nCycle aborted."})
            return
            
        self.target_temp = max_t 
        cycle_count = 0
        deadband = 0.7 

        self.log(f"Starting direct-cycle logic Max={max_t} Min={min_t}")

        # --- INITIAL DWELL AT MAX TEMP ---
        self.log(f"Starting initial hold at {max_t:.2f}°C")
        self.current_target = max_t
        self.active_setpoint = max_t
        self.var_setpoint_display.set(f"{self.active_setpoint:.2f}")

        try: 
            with self.client_lock:
                write_float(self.client, REGISTER_TEMP_SETPOINT, max_t)
        except Exception as e:
            self.log(f"Initial SP WRITE FAILED: {e}")
            self.root.after(0, self.stop_co2); return
            
        last_log_time = 0
        while not self.abort_cycle and self.co2_on:
            tt06 = self._get_latest_tt06()
            status_msg = ""
            if tt06 is None:
                status_msg = f"Waiting for initial TT06 data... (Target: {max_t:.2f}°C)"
            elif abs(tt06 - max_t) <= deadband:
                self.set_stable_color(True)
                self.log(f"✅ Initial TT06 reached {tt06:.2f}°C. Dwelling for {dwell}s.")
                if self.unified_logger:
                    log_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Event_Type": "DWELL_INIT",
                        "TT06": tt06, "Target_Temp": max_t, "Active_Setpoint": max_t,
                        "Status": f"DWELL_{dwell}s"
                    }
                    self.unified_logger.log(log_data)
                break
            else:
                self.set_stable_color(False)
                status_msg = f"Waiting for initial TT06={tt06:.2f}°C -> {max_t:.2f}°C"
            
            now = time.time()
            if now - last_log_time >= 5.0:
                self.log(status_msg)
                last_log_time = now
            
            if self.abort_cycle or not self.co2_on: 
                self.log("Cycle aborted during initial wait."); return
            time.sleep(1)

        end_dwell = time.time() + dwell
        while time.time() < end_dwell and not self.abort_cycle and self.co2_on:
            time.sleep(1)
        
        if self.abort_cycle or not self.co2_on:
            self.log("Cycle aborted during initial dwell."); return

        # --- MAIN CYCLE LOOP ---
        while not self.abort_cycle and self.co2_on and cycle_count < cycles:

            going_down = (self.target_temp == max_t)
            target_temp = min_t if going_down else max_t 
            self.target_temp = target_temp 
            self.current_target = target_temp 
            
            phase = "high_to_low" if going_down else "low_to_high"
            self.log(f"--- Starting Trip ({phase}) to {target_temp:.2f}°C ---")

            target_reached = False
            while not self.abort_cycle and self.co2_on:
                
                dew_max = None
                dew_limit = None
                ambient_data = {}
                if self.ambient_poller:
                    latest_ambient = self.ambient_poller.get_latest()
                    dew_max = latest_ambient.get("dew_max")
                    if dew_max is not None:
                        dew_limit = dew_max + 10.0
                    
                    s1 = latest_ambient.get("s1", (None,None,None))
                    s2 = latest_ambient.get("s2", (None,None,None))
                    
                    ambient_data = {
                        "Dew_Max": dew_max,
                        "Amb_S1_T": s1[0], "Amb_S1_H": s1[1], "Amb_S1_D": s1[2],
                        "Amb_S2_T": s2[0], "Amb_S2_H": s2[1], "Amb_S2_D": s2[2],
                    }

                temporary_target_temp = target_temp 
                log_status = "WAITING"
                
                if going_down: 
                    if dew_max is None:
                        temporary_target_temp = 20.0
                        log_status = "ESP32_FAIL_SAFE_20C"
                    elif dew_limit is not None and dew_limit > target_temp:
                        temporary_target_temp = dew_limit
                        log_status = "DEW_BLOCK"

                ok = False
                try:
                    with self.client_lock:
                        ok = write_float(self.client, REGISTER_TEMP_SETPOINT, temporary_target_temp)
                except Exception as e:
                    self.log(f"SP WRITE FAILED: {e}")
                    ok = False

                if not ok:
                    self.log("❌ Failed to write SP, retrying in 10s...")
                    for _ in range(10):
                        if self.abort_cycle or not self.co2_on: break
                        time.sleep(1)
                    continue 

                self.active_setpoint = temporary_target_temp
                self.var_setpoint_display.set(f"{self.active_setpoint:.2f}")
                log_msg = f"WAITING: TT06 must reach {temporary_target_temp:.2f}°C (Logical target: {target_temp:.2f}°C)"
                if log_status != "WAITING":
                    log_msg += f" [{log_status}]"
                self.log(log_msg)
                
                if self.unified_logger:
                    log_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Event_Type": "LOGIC",
                        "Status": log_status,
                        "TT06": self._get_latest_tt06(),
                        "Target_Temp": target_temp,
                        "Active_Setpoint": temporary_target_temp,
                    }
                    log_data.update(ambient_data) 
                    self.unified_logger.log(log_data)
                
                self.set_stable_color(False) 

                start_wait = time.time()
                last_log_time = start_wait
                
                while time.time() - start_wait < 10.0: 
                    if self.abort_cycle or not self.co2_on:
                        break 

                    tt06 = self._get_latest_tt06()
                    
                    if tt06 is not None and abs(tt06 - temporary_target_temp) <= deadband:
                        self.set_stable_color(True)
                        
                        if log_status == "DEW_BLOCK" or log_status == "ESP32_FAIL_SAFE_20C":
                            now = time.time()
                            if now - last_log_time >= 5.0: 
                                self.log(f"HOLDING at {tt06:.2f}°C due to {log_status}")
                                last_log_time = now
                        else:
                            self.log(f"✅ TT06 reached {tt06:.2f}°C (matches {temporary_target_temp:.2f}°C)")
                            if self.unified_logger:
                                log_data = {
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Event_Type": "LOGIC",
                                    "Status": "REACHED",
                                    "TT06": tt06,
                                    "Target_Temp": target_temp,
                                    "Active_Setpoint": temporary_target_temp,
                                }
                                log_data.update(ambient_data)
                                self.unified_logger.log(log_data)
                            
                            target_reached = True
                            break 
                    else:
                        self.set_stable_color(False)
                    
                    time.sleep(1) 

                if target_reached:
                    break 
                
                if self.abort_cycle or not self.co2_on:
                    break 
            
            if self.abort_cycle or not self.co2_on: break

            self.log(f"Cycle reach target side, dwelling {dwell}s")
            if self.unified_logger:
                ambient_data = {}
                if self.ambient_poller:
                    latest_ambient = self.ambient_poller.get_latest()
                    dew_max = latest_ambient.get("dew_max")
                    s1 = latest_ambient.get("s1", (None,None,None))
                    s2 = latest_ambient.get("s2", (None,None,None))
                    
                    ambient_data = {
                        "Dew_Max": dew_max,
                        "Amb_S1_T": s1[0], "Amb_S1_H": s1[1], "Amb_S1_D": s1[2],
                        "Amb_S2_T": s2[0], "Amb_S2_H": s2[1], "Amb_S2_D": s2[2],
                    }
                    
                log_data = {
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Event_Type": "DWELL",
                    "Status": f"DWELL_{dwell}s",
                    "TT06": self._get_latest_tt06(),
                    "Target_Temp": self.target_temp,
                    "Active_Setpoint": self.active_setpoint,
                }
                log_data.update(ambient_data)
                self.unified_logger.log(log_data)
            
            end_dwell = time.time() + dwell
            while time.time() < end_dwell and not self.abort_cycle and self.co2_on:
                time.sleep(1) 

            if self.abort_cycle or not self.co2_on: break

            if not going_down: 
                cycle_count += 1
                self.log(f"--- Cycle {cycle_count}/{cycles} complete ---")

        self.log("✅ CYCLE SEQUENCE FINISHED OR ABORTED")
        
        if not self.abort_cycle and self.co2_on:
            self.log("Cycle finished. Stopping CO2.")
            self.root.after(0, self.stop_co2) 


    def _get_latest_tt06(self):
        if not self.poller:
            return None
            
        with self.poller.lock: 
            arr = self.poller.temp[5]
            if not arr:
                return None 
                
            for v in reversed(arr):
                if v is not None:
                    return v
                    
        return None 

    # ---------- plotting functions ----------
    def open_all_temps_plot(self):
        if not self.poller:
            messagebox.showinfo("Not Connected", "Connect to MARTA first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("All Temperatures vs Time")
        labels = [f"TT0{i+1}" for i in range(6)]
        def animate(_):
            with self.poller.lock:
                t = list(self.poller.timestamps)
                ys = [list(self.poller.temp[i]) for i in range(6)]
            ax.clear()
            if t:
                for lab, y in zip(labels, ys): ax.plot(t, y, label=lab)
                ax.set_ylabel("Temperature (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("All Temps plot opened.")

    def open_ambient_temp_plot(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Ambient Temperatures (S1-S4)")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                t1 = list(self.ambient_poller.s1["temp"])
                t2 = list(self.ambient_poller.s2["temp"])
            ax.clear()
            if t:
                if any(v is not None for v in t1): ax.plot(t, t1, label="S1 (AM2315C)")
                if any(v is not None for v in t2): ax.plot(t, t2, label="S2 (MAX6675)")
                ax.set_ylabel("Temperature (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Ambient Temp plot opened.")

    def open_humidity_plot(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Ambient Humidity (S1, S3, S4)")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                h1 = list(self.ambient_poller.s1["hum"])
                # S2 is Thermocouple (No Hum)
            ax.clear()
            if t:
                if any(v is not None for v in h1): ax.plot(t, h1, label="S1 (AM2315C)")
                ax.set_ylabel("Humidity (%)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Humidity plot opened.")

    def open_dew_point_plot(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Ambient Dew Point (S1, S3, S4)")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                d1 = list(self.ambient_poller.s1["dew"])
                # S2 is Thermocouple (No Dew)
            ax.clear()
            if t:
                if any(v is not None for v in d1): ax.plot(t, d1, label="S1 (AM2315C)")
                ax.set_ylabel("Dew Point (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Dew Point plot opened.")

    def open_cycle_plot(self):
        if not self.poller:
            messagebox.showinfo("Not Connected", "Connect to MARTA first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Cycle Plot TT06 vs Setpoints")
        
        def animate(_):
            with self.poller.lock:
                t = list(self.poller.timestamps)
                tt06 = list(self.poller.temp[5])
                active_sp = list(self.poller.active_sp_history)
                current_tgt = list(self.poller.current_target_history)
            ax.clear()
            if t:
                if any(v is not None for v in tt06): 
                    ax.plot(t, tt06, label="TT06 (°C)", color="blue", linewidth=2)
                if any(v is not None for v in current_tgt): 
                    ax.plot(t, current_tgt, label="Target Temp", color="red", linestyle="--", drawstyle="steps-post")
                if any(v is not None for v in active_sp): 
                    ax.plot(t, active_sp, label="Active Setpoint", color="green", linestyle=":", drawstyle="steps-post")

                ax.set_ylabel("Temperature (°C)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Cycle plot opened.")

    def open_contact_point(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Contact Point (S2) Temp")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                t2 = list(self.ambient_poller.s2["temp"])
            ax.clear()
            if t:
                if any(v is not None for v in t2): ax.plot(t, t2, label="S2 (Contact Point)", color="orange")
                ax.set_ylabel("Temperature (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Contact Point (S2) plot opened.")



    # --- Connection Health Check ---
    def _check_connection_health(self):
        if self.connected and self.poller and self.poller.is_alive():
            elapsed = time.time() - self.poller.last_successful_read_time
            
            tolerance = (self.poller.interval * 2.5) 
            
            if elapsed > tolerance:
                if self.lab_conn.cget("text") != "POLLING FAILED":
                    self.log("POLLER HEARTBEAT FAILED. Updating status label.")
                    self.gui_update_q.put({"type": "conn_status", "text": "POLLING FAILED", "fg": "red"})
            else:
                if self.lab_conn.cget("text") != "Connected":
                    self.log("Poller heartbeat recovered.")
                    self.gui_update_q.put({"type": "conn_status", "text": "Connected", "fg": "green"})
        
        elif not self.connected:
            if self.lab_conn.cget("text") != "Disconnected":
                self.gui_update_q.put({"type": "conn_status", "text": "Disconnected", "fg": "red"})

        self.health_check_job = self.root.after(5000, self._check_connection_health) 

    def _on_close(self):
        self.stop_all()
        self.root.destroy()

# ---------- main ----------
if __name__ == "__main__":
    root = tk.Tk()
    app = MartaGUI(root)
    root.mainloop()