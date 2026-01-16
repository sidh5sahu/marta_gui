import os
import csv
from datetime import datetime
import threading
try:
    from ..config import load_config
    from .influx_logger import InfluxLogger
except ImportError:
    # Fallback for when running directly or diff structure
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config import load_config
    from backend.influx_logger import InfluxLogger

HEADER = [
    "Timestamp", "Event_Type", "Status", 
    "TT06", "Target_Temp", "Active_Setpoint", "Dew_Max",
    "Amb_S1_T", "Amb_S1_H", "Amb_S1_D", 
    "Amb_S2_T", "Amb_S2_H", "Amb_S2_D",
    "TT01", "TT02", "TT03", "TT04", "TT05"
]

class UnifiedEventLogger:
    def __init__(self, base_dir, run_name):
        self.base_dir = base_dir
        self.run_name = run_name
        
        # Create run directory
        ts_str = datetime.now().strftime("%d%m%Y_%H%M")
        self.run_dir = os.path.join(base_dir, f"{run_name}_{ts_str}")
        os.makedirs(self.run_dir, exist_ok=True)
        print(f"Created new run directory: {self.run_dir}")
        
        self.path = os.path.join(self.run_dir, "events.csv")
        self.lock = threading.Lock()
        
        if not os.path.exists(self.path):
            with open(self.path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=HEADER)
                writer.writeheader()

        # Initialize InfluxDB Logger
        self.influx_logger = None
        config = load_config()
        influx_conf = config.get("influxdb", {})
        if influx_conf.get("enabled", False):
            self.influx_logger = InfluxLogger(
                url=influx_conf.get("url"),
                token=influx_conf.get("token"),
                org=influx_conf.get("org"),
                bucket=influx_conf.get("bucket")
            )

    def log(self, data_dict):
        with self.lock:
            try:
                # Fill missing keys with empty string
                row = {k: data_dict.get(k, "") for k in HEADER}
                with open(self.path, "a", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=HEADER)
                    writer.writerow(row)
                
                # Log to InfluxDB if enabled
                if self.influx_logger:
                    self.influx_logger.log(data_dict)
                    
            except Exception as e:
                print(f"Logging failed: {e}")
