import sys
try:
    import requests
    print("requests: installed")
except ImportError:
    print("requests: missing")

try:
    import pymodbus
    print(f"pymodbus: installed (version {pymodbus.__version__})")
    try:
        from pymodbus.client import ModbusTcpClient
        print("pymodbus.client.ModbusTcpClient: found")
    except ImportError:
        print("pymodbus.client.ModbusTcpClient: missing")
        try:
            from pymodbus.client.sync import ModbusTcpClient
            print("pymodbus.client.sync.ModbusTcpClient: found")
        except ImportError:
            print("pymodbus.client.sync.ModbusTcpClient: missing")
except ImportError:
    print("pymodbus: missing")
