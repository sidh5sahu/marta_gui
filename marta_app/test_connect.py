import sys
import time
import socket

# Defaults from app.py
MARTA_IP = "10.4.133.77"
ESP32_IP = "10.4.135.152"

print(f"Testing connection to MARTA ({MARTA_IP})...")
try:
    from pymodbus.client import ModbusTcpClient
    client = ModbusTcpClient(host=MARTA_IP, port=502)
    if client.connect():
        print("MARTA: Connected successfully (pymodbus)")
        client.close()
    else:
        print("MARTA: Connection failed (pymodbus returned False)")
except Exception as e:
    print(f"MARTA: Connection error: {e}")

print("-" * 20)

print(f"Testing connection to ESP32 ({ESP32_IP})...")
try:
    import requests
    url = f"http://{ESP32_IP}/data"
    print(f"GET {url}")
    r = requests.get(url, timeout=5)
    print(f"ESP32: Status Code {r.status_code}")
    try:
        print(f"ESP32: JSON: {r.json()}")
    except Exception as e:
        print(f"ESP32: Invalid JSON: {e}")
except Exception as e:
    print(f"ESP32: Connection error: {e}")
