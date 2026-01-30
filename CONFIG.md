# Configuration Guide

## Single Configuration File

The Marta GUI uses **ONE unified configuration file**:

```
marta_app/config.json
```

This file contains all settings for the application.

## Configuration Sections

### 1. **MARTA Connection**
```json
"marta_ip": "10.4.133.77"
```
IP address of the MARTA chiller (Modbus TCP, port 502)

### 2. **ESP32 Connection**
```json
"esp32_ip": "10.4.136.191"
```
IP address of the ESP32 ambient sensor module (HTTP)

### 3. **Thermal Cycling Defaults**
```json
"cycle_defaults": {
    "max_temp": 15,
    "min_temp": -35,
    "cycles": 1,
    "dwell_s": 60
}
```
- `max_temp`: Maximum temperature (°C)
- `min_temp`: Minimum temperature (°C)
- `cycles`: Number of thermal cycles
- `dwell_s`: Dwell time at each temperature (seconds)

**Note**: These are defaults - you can change them in the GUI before starting a cycle.

### 4. **Safety Limits**
```json
"safety_limits": {
    "pump_rpm_default": 2000
}
```
Default pump RPM setting (safety protection)

### 5. **File Paths**
```json
"paths": {
    "base_log_dir": "/home/cleanroom2/Downloads/marta_gui (1)/marta_logs"
}
```
Directory where:
- Run logs are saved
- Reports are generated
- Plots are saved as JPEG
- Web dashboard reads data from

### 6. **InfluxDB (Optional)**
```json
"influxdb": {
    "url": "http://localhost:8086",
    "token": "your-token-here",
    "org": "niser",
    "bucket": "ladder",
    "enabled": true
}
```
Time-series database for advanced data logging.

**Note**: The application works without InfluxDB. Set `"enabled": false` to disable.

### 7. **Run Sequence**
```json
"last_run_number": 16
```
Auto-incremented run number. **Do not edit manually** - managed by the application.

## How to Edit Configuration

### Method 1: Using GUI (Recommended)
1. Launch the application
2. Go to **Settings** tab
3. Edit values
4. Click **Save**
5. Restart if needed

### Method 2: Manual Editing
1. **Stop the application**
2. Open `marta_app/config.json` in a text editor
3. Edit the values
4. Save the file
5. **Restart the application**

## Important Notes

⚠️ **Before Editing**:
- Always stop the application first
- Make a backup: `cp marta_app/config.json marta_app/config.json.backup`
- Validate JSON syntax before saving

✅ **After Editing**:
- Restart the application to apply changes
- Check the log for any errors

## Configuration Removed

The following redundant config file has been **removed**:
- ~~`./config.json`~~ (root directory - was not used)

Now there is only **ONE** config file: `marta_app/config.json` ✅

## Troubleshooting

### Config file not found
If `marta_app/config.json` is missing, the application will create it with default values.

### Invalid JSON
If the file has syntax errors:
1. Restore from backup
2. Or delete it - app will recreate with defaults
3. Use a JSON validator: https://jsonlint.com/

### Settings not saving
Check file permissions:
```bash
chmod 644 marta_app/config.json
```

## Default Configuration

If you need to reset to defaults, create this file:

```json
{
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
        "base_log_dir": "./marta_logs"
    },
    "influxdb": {
        "url": "http://localhost:8086",
        "token": "",
        "org": "",
        "bucket": "",
        "enabled": false
    },
    "last_run_number": 0
}
```

Then configure IPs and paths through the Settings tab.
