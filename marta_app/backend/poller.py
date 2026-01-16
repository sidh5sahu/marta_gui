import threading
import time
import requests
import math
from datetime import datetime
from .modbus import _u16pair_to_float, REGISTER_TT

class DataPoller(threading.Thread):
    def __init__(self, client, client_lock, logger, get_active_sp=None, get_current_target=None, interval=10.0):
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
            "status": 0,
            "control": 0
        }
        
        self.interval = interval
        self.last_successful_read_time = time.time()

    def run(self):
        while self.runflag:
            ts = datetime.now()
            read_ok = False 
            
            try:
                with self.client_lock:
                    # Split reads to avoid gaps
                    # 1. Floats Part 1: 100 - 186 (Count 88: 100..187)
                    rr1 = self.client.read_holding_registers(100, count=88, slave=1)
                    
                    # 2. Floats Part 2: 190 - 210 (Count 22: 190..211)
                    rr2 = self.client.read_holding_registers(190, count=22, slave=1)
                    
                    # 3. Alarms: 300 - 303 (Count 4)
                    rr3 = self.client.read_holding_registers(300, count=4, slave=1)
                    
                    # 4. Control: 305 (Count 1)
                    rr4 = self.client.read_holding_registers(305, count=1, slave=1)
                    
                    # 5. Setpoints: 310 - 314 (Count 6: 310..315)
                    rr5 = self.client.read_holding_registers(310, count=6, slave=1)
                    
                    # 6. Status: 320 (Count 1)
                    rr6 = self.client.read_holding_registers(320, count=1, slave=1)
                    
                if not (rr1.isError() or rr2.isError() or rr3.isError() or rr4.isError() or rr5.isError() or rr6.isError()):
                    read_ok = True
                    
                    floats = {}
                    
                    # Parse RR1 (100-186)
                    regs1 = rr1.registers
                    for i in range(0, 88, 2):
                        addr = 100 + i
                        floats[addr] = _u16pair_to_float((regs1[i], regs1[i+1]))
                        
                    # Parse RR2 (190-210)
                    regs2 = rr2.registers
                    for i in range(0, 22, 2):
                        addr = 190 + i
                        floats[addr] = _u16pair_to_float((regs2[i], regs2[i+1]))
                        
                    # Parse RR3 (Alarms)
                    regs3 = rr3.registers
                    alarms = {
                        300: regs3[0],
                        301: regs3[1],
                        302: regs3[2],
                        303: regs3[3]
                    }
                    
                    # Parse RR4 (Control)
                    control_bits = rr4.registers[0]
                    
                    # Parse RR5 (Setpoints)
                    regs5 = rr5.registers
                    floats[310] = _u16pair_to_float((regs5[0], regs5[1]))
                    floats[312] = _u16pair_to_float((regs5[2], regs5[3]))
                    floats[314] = _u16pair_to_float((regs5[4], regs5[5]))
                    
                    # Parse RR6 (Status)
                    status_val = rr6.registers[0]
                    
                    with self.lock:
                        self.timestamps.append(ts)
                        self.full_data["floats"] = floats
                        self.full_data["alarms"] = alarms
                        self.full_data["status"] = status_val
                        self.full_data["control"] = control_bits
                        
                        # Maintain compatibility for plotting/logic
                        tt_addrs = [126, 128, 130, 132, 134, 136]
                        for i, addr in enumerate(tt_addrs):
                            self.temp[i].append(floats.get(addr))
                            
                        self.active_sp_history.append(floats.get(310)) # Temp Setpoint
                        
                        tgt_val = None
                        if self.get_current_target:
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
            
            active_sp_val = self.get_active_sp() if self.get_active_sp else None
            current_target_val = self.get_current_target() if self.get_current_target else None


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

    def stop(self):
        self.runflag = False

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
