# MARTA GUI System

MARTA GUI is a control and monitoring application for a **CO₂-based thermal cycling system**.  
It provides a **desktop GUI** for operation, a **web dashboard** for remote monitoring, and implements **dew-point–based safety logic** to prevent condensation during temperature cycling.

---

## Features

- Desktop GUI (Tkinter) for full system control
- Web dashboard (Flask) for live and historical monitoring
- Modbus TCP communication with MARTA PLC
- HTTP-based communication with ESP32 ambient sensors
- Automated temperature cycling with dwell logic
- Dew point protection and ESP32 failsafe handling
- Real-time plotting and saved run plots
- CSV logging and Markdown run reports
- Alarm and connection health monitoring

---

## System Architecture

PLC (Modbus TCP) ──┐
├──> Data Pollers ──> GUI / Logger / Web
ESP32 (HTTP JSON) ─┘

User Commands ──> GUI ──> PLC (Control & Setpoints)


---

## Directory Structure

marta_gui/
├── main.py # Application entry point
├── config.json # User configuration
├── marta_app/
│ ├── config.py
│ ├── gui/
│ │ ├── app.py
│ │ └── config_window.py
│ ├── backend/
│ │ ├── modbus.py
│ │ ├── poller.py
│ │ ├── logger.py
│ │ └── influx_logger.py
│ └── web/
│ └── server.py
└── marta_logs/ # Auto-generated run logs


---

## Requirements

- Python 3.8+
- MARTA PLC accessible over Modbus TCP
- ESP32 running HTTP JSON sensor endpoint

### Python Dependencies

```bash
pip install pymodbus flask matplotlib requests numpy
pip install influxdb-client
Edit config.json before running:

{
  "marta_ip": "10.4.133.77",
  "esp32_ip": "10.4.135.152",
  "paths": {
    "base_log_dir": "./marta_logs"
  },
  "cycle_defaults": {
    "max_temp": 15,
    "min_temp": 10,
    "cycles": 2,
    "dwell_s": 60
  },
  "safety_limits": {
    "pump_rpm_default": 6000
  }
}
python main.py
Desktop GUI starts automatically

Web dashboard runs at: http://localhost:5000
Each connection creates a new run directory:
run_<ID>_<DATE>_<TIME>/
├── events.csv          # Time-series data
├── run_<ID>.md         # Auto-generated report
├── *.jpg               # Saved plots
Logged data includes:

Temperatures (TT01–TT06)

Target and active setpoints

Dew point and ambient conditions

Cycle and dwell events

Safety Features

Dew-point–based temperature blocking

ESP32 communication failsafe (20 °C setpoint)

Mandatory 60 s chiller warm-up

Emergency stop

Continuous alarm monitoring

Polling health watchdog

Note: Software safety features do not replace hardware interlocks.
Web Dashboard
Available endpoints:
| Route         | Description      |
| ------------- | ---------------- |
| `/`           | Live dashboard   |
| `/data`       | JSON API         |
| `/logs`       | List of run logs |
| `/logs/<run>` | View run details |

Intended Use

This software is intended for laboratory and integration testing of CO₂ thermal cycling systems by trained personnel.

License Internal / Research use (Modify as required)

Author Sidhartha Sahu Institute of Physics (IoP)

