import json
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")

# Default configuration with clear paths
DEFAULT_CONFIG = {
    "marta_ip": "",
    "esp32_ip": "",
    "cycle_defaults": {
        "max_temp": 15,
        "min_temp": -35,
        "cycles": 2,
        "dwell_s": 60
    },
    "safety_limits": {
        "pump_rpm_default": 6000
    },
    "paths": {
        # Default log directory: marta_logs folder next to the application
        "base_log_dir": os.path.join(os.path.dirname(BASE_DIR), "marta_logs")
    },
    "influxdb": {
        "url": "http://localhost:8086",
        "token": "",
        "org": "",
        "bucket": "",
        "enabled": False
    },
    "last_run_number": 0
}

def load_config():
    """Load config from file, applying defaults for missing keys."""
    config = DEFAULT_CONFIG.copy()
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                # Deep merge saved config into defaults
                for key, value in saved.items():
                    if isinstance(value, dict) and key in config:
                        config[key] = {**config.get(key, {}), **value}
                    else:
                        config[key] = value
        except Exception as e:
            print(f"Error loading config: {e}")
    
    # Ensure log directory exists
    log_dir = config.get("paths", {}).get("base_log_dir", "")
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
            print(f"Created log directory: {log_dir}")
        except Exception as e:
            print(f"Could not create log directory: {e}")
    
    return config

def save_config(config):
    """Save config to file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")
