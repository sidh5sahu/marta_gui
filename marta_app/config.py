import json
import os
import re
import ipaddress
from typing import List, Dict, Any


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


def is_valid_ip(ip_str: str) -> bool:
    """Validate IP address format."""
    if not ip_str:
        return True  # Empty is allowed (will be set later)
    try:
        ipaddress.ip_address(ip_str)
        return True
    except ValueError:
        return False


def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate configuration values.
    
    Args:
        config: Configuration dictionary
    
    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    
    # Validate IP addresses
    marta_ip = config.get('marta_ip', '')
    if marta_ip and not is_valid_ip(marta_ip):
        errors.append(f"Invalid MARTA IP address: '{marta_ip}'")
    
    esp32_ip = config.get('esp32_ip', '')
    if esp32_ip and not is_valid_ip(esp32_ip):
        errors.append(f"Invalid ESP32 IP address: '{esp32_ip}'")
    
    # Validate temperature ranges
    cycle_defaults = config.get('cycle_defaults', {})
    max_temp = cycle_defaults.get('max_temp')
    min_temp = cycle_defaults.get('min_temp')
    
    if max_temp is not None and min_temp is not None:
        if max_temp <= min_temp:
            errors.append(
                f"Max temperature ({max_temp}°C) must be greater than "
                f"min temperature ({min_temp}°C)"
            )
    
    # Validate cycles
    cycles = cycle_defaults.get('cycles', 1)
    if not isinstance(cycles, int) or cycles < 1:
        errors.append(f"Cycles must be a positive integer (got: {cycles})")
    
    # Validate dwell time
    dwell_s = cycle_defaults.get('dwell_s', 60)
    if not isinstance(dwell_s, (int, float)) or dwell_s < 0:
        errors.append(f"Dwell time must be non-negative (got: {dwell_s})")
    
    # Validate pump RPM
    pump_rpm = config.get('safety_limits', {}).get('pump_rpm_default', 6000)
    if not isinstance(pump_rpm, (int, float)) or pump_rpm < 0:
        errors.append(f"Pump RPM must be non-negative (got: {pump_rpm})")
    
    # Validate paths
    log_dir = config.get('paths', {}).get('base_log_dir', '')
    if log_dir:
        parent_dir = os.path.dirname(log_dir)
        if parent_dir and not os.path.exists(parent_dir):
            errors.append(
                f"Parent directory for log_dir does not exist: '{parent_dir}'"
            )
    
    # Validate InfluxDB settings (if enabled)
    influxdb = config.get('influxdb', {})
    if influxdb.get('enabled', False):
        if not influxdb.get('url'):
            errors.append("InfluxDB URL is required when InfluxDB is enabled")
        if not influxdb.get('token'):
            errors.append("InfluxDB token is required when InfluxDB is enabled")
        if not influxdb.get('org'):
            errors.append("InfluxDB org is required when InfluxDB is enabled")
        if not influxdb.get('bucket'):
            errors.append("InfluxDB bucket is required when InfluxDB is enabled")
    
    return errors


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
    
    # Validate configuration
    validation_errors = validate_config(config)
    if validation_errors:
        print("\n" + "="*60)
        print("⚠️  CONFIGURATION VALIDATION ERRORS:")
        print("="*60)
        for error in validation_errors:
            print(f"  • {error}")
        print("="*60)
        print("Please fix these errors in marta_app/config.json")
        print("The application may not work correctly!")
        print("="*60 + "\n")
    
    return config

def save_config(config):
    """Save config to file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving config: {e}")
