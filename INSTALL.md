# Marta GUI - Installation Guide

## Quick Install

Install all dependencies at once:

```bash
pip install -r requirements.txt
```

Or with pip3:

```bash
pip3 install -r requirements.txt
```

## Running the Application

```bash
python3 main.py
```

This will start:
- GUI application (tkinter)
- Web dashboard on http://localhost:5000

## Dependencies

The application requires:

1. **Flask** - Web server for dashboard
2. **pymodbus** - Modbus TCP communication with MARTA
3. **matplotlib** - Real-time plotting
4. **requests** - HTTP communication with ESP32
5. **influxdb-client** - Time-series data logging
6. **numpy** - Numerical operations (matplotlib dependency)

## System Requirements

- Python 3.8 or higher
- Linux (tested on Ubuntu/Debian)
- tkinter (usually pre-installed with Python)
- Network access to MARTA (Modbus TCP) and ESP32 (HTTP)

## Troubleshooting

### tkinter not found

On Ubuntu/Debian:
```bash
sudo apt-get install python3-tk
```

On Fedora/RHEL:
```bash
sudo dnf install python3-tkinter
```

### InfluxDB Connection Issues

The application will work without InfluxDB, but time-series logging will be disabled.
To use InfluxDB logging:
1. Install InfluxDB 2.x
2. Configure connection in Settings tab
3. Restart application

## Configuration

First-time setup:
1. Launch the application
2. Go to **Settings** tab
3. Configure:
   - MARTA IP address (Modbus TCP)
   - ESP32 IP address (HTTP)
   - Log directory
   - InfluxDB settings (optional)

## Testing

Run automated tests:
```bash
python3 test_refactoring.py
```

This validates:
- Manager imports
- Initialization
- Method availability
- App integration
- Syntax validation

## Documentation

- **walkthrough.md** - Refactoring documentation
- **test_report.md** - Testing results
- **integration_plan.md** - Integration strategy

## Support

For issues or questions, check the log output in the GUI or terminal.
