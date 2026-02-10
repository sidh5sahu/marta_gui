
---

```markdown
# MARTA & ESP32 Connection Tester

A simple diagnostic script to verify network connectivity between your workstation and the **MARTA (Modbus)** and **ESP32 (HTTP)** hardware components.

## Prerequisites

Ensure you are using the correct Conda environment (e.g., `marta_env`) with the following dependencies installed:

* `pymodbus`
* `requests`

## How to Use

1. **Verify IP Addresses:**
   Open the script and ensure the IP addresses match your current hardware setup:
   - `MARTA_IP`: Default is `10.4.133.77`
   - `ESP32_IP`: Default is `10.4.135.152`

2. **Run the Script:**
   Execute the script from your terminal:
   ```bash
   python connection_test.py

```

3. **Interpret Results:**
* If you see `Connected successfully` and a `JSON` response, your hardware is ready.
* If you see `Connection error`, follow the troubleshooting steps below.



---

## Troubleshooting Guide

### 1. General Network Issues

* **Ping Test:** Try to ping the devices directly from your terminal:
```bash
ping 10.4.133.77
ping 10.4.135.152

```


If `ping` fails, the devices are either offline or on a different subnet.
* **Subnet Match:** Ensure your computer's IP address starts with `10.4.X.X`. If you are on a different network (like a home guest network or a phone hotspot), you won't be able to reach the 10.4 range.

### 2. MARTA (Modbus) Troubleshooting

* **Port 502:** Ensure no other software is currently using the Modbus port on the MARTA device. Modbus TCP usually only allows one active connection at a time.
* **Firewall:** Check if your system firewall is blocking outbound traffic on Port 502.

### 3. ESP32 (HTTP) Troubleshooting

* **Timeout:** If you get a "Connection timeout," the ESP32 might be struggling with a weak Wi-Fi signal or is stuck in a loop. Try power-cycling the ESP32.
* **Endpoint:** The script looks for `http://<IP>/data`. Ensure your ESP32 code actually has a route defined for `/data`. If you can open this address in a web browser and see text, the script should work.

### 4. Software Errors

* **ModuleNotFoundError:** This means your Conda environment isn't active. Run `conda activate marta_env` before running the script.

```

---

### A few "pro-tips" for you:
* **The "One-Connection" Trap:** If your main `app.py` is currently running, this test script might fail for the MARTA connection. Modbus can be a bit jealous and often won't let a second "client" talk to the hardware at the same time.
* **Check the ESP32 Serial Monitor:** If the ESP32 isn't responding, plug it into your PC and check the Serial Monitor. It might be failing to connect to the Wi-Fi or getting assigned a different IP address than `10.4.135.152`.

Would you like me to add a section on how to automatically detect the device IPs if they change frequently?

```
