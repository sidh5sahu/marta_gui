"""
Connection management for MARTA GUI.

Handles MARTA Modbus and ESP32 HTTP connections, health monitoring,
and parameter display updates.
"""

import socket
import time
import threading
import requests
from tkinter import messagebox

from ...backend.modbus import get_modbus_client
from ...backend.logger import UnifiedEventLogger
from ...backend.poller import DataPoller, AmbientPoller


class ConnectionManager:
    """Manages connections to MARTA and ESP32 devices."""
    
    def __init__(self, config, gui_update_q, log_callback, web_update_callback):
        """
        Initialize ConnectionManager.
        
        Args:
            config: Configuration dictionary
            gui_update_q: Queue for GUI updates
            log_callback: Function to call for logging messages  
            web_update_callback: Function to update web server pollers
        """
        self.config = config
        self.gui_update_q = gui_update_q
        self.log = log_callback
        self.web_update_callback = web_update_callback
        
        # Connection state
        self.client = None
        self.client_lock = threading.Lock()
        self.connected = False
        self.esp_connected = False
        
        # Pollers
        self.poller = None
        self.ambient_poller = None
        
        # Logger
        self.unified_logger = None
        self.log_file_path = None
        
        # Ambient data (for external access)
        self.ambient = {}
        
        # Health check
        self.health_check_job = None
        self.last_health_check_time = 0
    
    def connect_marta(self, run_dir, run_name_short, get_active_sp_func, get_current_target_func, enable_buttons_callback):
        """
        Connect to MARTA via Modbus.
        
        Args:
            run_dir: Directory for the current run
            run_name_short: Short name for the current run
            get_active_sp_func: Function to get active setpoint
            get_current_target_func: Function to get current target
            enable_buttons_callback: Function to enable control buttons
            
        Returns:
            True if connection successful, False otherwise
        """
        ip = self.config.get("marta_ip", "")
        if not ip:
            messagebox.showwarning("MARTA IP", "Please set MARTA IP in the Settings tab.")
            return False
        
        self.log(f"Connecting to {ip}...")
        c = get_modbus_client(ip)
        if not c.connect():
            self.gui_update_q.put({"type": "conn_status", "text": "MARTA: Failed", "fg": "red"})
            self.log("Connection failed.")
            return False
        
        self.client = c
        self.connected = True
        self.gui_update_q.put({"type": "conn_status", "text": "MARTA: Connected", "fg": "green"})
        self.log("Connected to MARTA.")
        
        # Enable control buttons
        enable_buttons_callback()
        
        # Create logger
        self.unified_logger = UnifiedEventLogger(
            base_dir=self.config.get("paths", {}).get("base_log_dir", ""),
            run_name=run_name_short,
            run_dir=run_dir
        )
        self.log_file_path = self.unified_logger.path
        
        # Create and start poller
        self.poller = DataPoller(
            self.client,
            self.client_lock,
            self.unified_logger,
            get_active_sp_func,
            get_current_target_func,
            interval=10.0
        )
        self.poller.start()
        
        # Update web server
        self.web_update_callback(self.poller, self.ambient_poller)
        
        return True
    
    def connect_esp32(self):
        """
        Connect to ESP32 via HTTP.
        
        Returns:
            True if connection successful, False otherwise
        """
        ip = self.config.get("esp32_ip", "")
        if not ip:
            messagebox.showwarning("ESP32 IP", "Please set ESP32 IP in the Settings tab.")
            return False
        
        # Stop existing ambient poller if any
        if self.ambient_poller:
            self.ambient_poller.stop()
            self.ambient_poller = None
        
        url = f"http://{ip}/data"
        self.log(f"Testing ESP32 connection at {url}...")
        
        try:
            r = requests.get(url, timeout=5)
            r.raise_for_status()
            _ = r.json()
            
            self.gui_update_q.put({"type": "esp_status", "text": f"ESP32: Connected ({ip})", "fg": "green"})
            self.log("ESP32 connection test successful.")
            self.esp_connected = True
            
            # Create and start ambient poller
            self.ambient_poller = AmbientPoller(lambda: self.config.get("esp32_ip", ""), interval=10.0)
            self.ambient_poller.start()
            
            # Update web server
            self.web_update_callback(self.poller, self.ambient_poller)
            
            return True
            
        except Exception as e:
            self.log(f"ESP32 connection FAILED: {e}")
            self.gui_update_q.put({
                "type": "error",
                "title": "ESP32 Connection Failed",
                "message": f"Could not connect to {ip}.\\n\\nError: {e}"
            })
            self.gui_update_q.put({"type": "esp_status", "text": "ESP32: FAILED", "fg": "red"})
            self.esp_connected = False
            return False
    
    def disconnect(self):
        """Disconnect from MARTA and ESP32."""
        # Stop pollers
        if self.poller:
            self.poller.stop()
            self.poller = None
        
        if self.ambient_poller:
            self.ambient_poller.stop()
            self.ambient_poller = None
        
        # Close Modbus client
        if self.client:
            try:
                self.client.close()
            except:
                pass
            self.client = None
        
        self.connected = False
        self.esp_connected = False
        
        # Update GUI
        self.gui_update_q.put({"type": "conn_status", "text": "MARTA: Disconnected", "fg": "gray"})
        self.gui_update_q.put({"type": "esp_status", "text": "ESP32: Disconnected", "fg": "gray"})
        
        self.log("Disconnected from all devices.")
    
    def test_network(self):
        """Run network diagnostics in background thread."""
        marta_ip = self.config.get("marta_ip", "")
        esp_ip = self.config.get("esp32_ip", "")
        
        self.log(f"Starting network test for MARTA ({marta_ip}) and ESP32 ({esp_ip})...")
        threading.Thread(target=self._run_network_test, args=(marta_ip, esp_ip), daemon=True).start()
    
    def _run_network_test(self, marta_ip, esp_ip):
        """
        Run network test for both devices.
        
        Args:
            marta_ip: MARTA IP address
            esp_ip: ESP32 IP address
        """
        results = []
        
        # Test MARTA (TCP 502)
        try:
            s = socket.create_connection((marta_ip, 502), timeout=3)
            s.close()
            results.append(f"MARTA ({marta_ip}): OK")
        except socket.timeout:
            results.append(f"MARTA ({marta_ip}): Timeout (Device offline or firewall?)")
        except ConnectionRefusedError:
            results.append(f"MARTA ({marta_ip}): Connection Refused (Service not running?)")
        except OSError as e:
            results.append(f"MARTA ({marta_ip}): Unreachable ({e})")
        
        # Test ESP32 (HTTP GET)
        try:
            r = requests.get(f"http://{esp_ip}/data", timeout=3)
            if r.status_code == 200:
                results.append(f"ESP32 ({esp_ip}): OK")
            else:
                results.append(f"ESP32 ({esp_ip}): HTTP {r.status_code}")
        except requests.exceptions.Timeout:
            results.append(f"ESP32 ({esp_ip}): Timeout")
        except requests.exceptions.ConnectionError as e:
            results.append(f"ESP32 ({esp_ip}): Connection Error ({e})")
        except Exception as e:
            results.append(f"ESP32 ({esp_ip}): Error ({e})")
        
        final_msg = "\\n".join(results)
        self.log(f"Network Test Results:\\n{final_msg}")
        self.gui_update_q.put({"type": "error", "title": "Network Test Results", "message": final_msg})
    
    def update_param_display(self, param_vars, alarm_vars, alarm_actions, var_tt06_display, var_status_int, var_control_word, var_active_actions, root):
        """
        Update parameter and alarm displays from poller data.
        
        Args:
            param_vars: Dict of {address: StringVar} for parameters
            alarm_vars: Dict of {(address, bit): Label} for alarms
            alarm_actions: Dict of {(address, bit): action_string}
            var_tt06_display: StringVar for TT06 display
            var_status_int: StringVar for status display
            var_control_word: StringVar for control word display
            var_active_actions: StringVar for active actions display
            root: Tkinter root for scheduling next update
        """
        if self.poller:
            with self.poller.lock:
                data = getattr(self.poller, "full_data", None)
                if data:
                    # Update Floats
                    floats = data.get("floats", {})
                    for addr, var in param_vars.items():
                        val = floats.get(addr)
                        var.set(f"{val:.2f}" if val is not None else "--")
                        
                        # Sync TT06 to main display
                        if addr == 136:
                            var_tt06_display.set(f"{val:.2f}" if val is not None else "--")
                    
                    # Update Alarms & Actions
                    alarms = data.get("alarms", {})
                    active_actions_list = []
                    
                    for (addr, bit), lbl in alarm_vars.items():
                        reg_val = alarms.get(addr, 0)
                        is_set = (reg_val >> bit) & 1
                        lbl.config(bg="red" if is_set else "lightgray", fg="white" if is_set else "black")
                        
                        if is_set:
                            action = alarm_actions.get((addr, bit))
                            if action:
                                active_actions_list.append(f"• {lbl.cget('text')}: {action}")
                    
                    if active_actions_list:
                        var_active_actions.set("\\n".join(active_actions_list))
                    else:
                        var_active_actions.set("No active alarms.")
                    
                    # Update Status
                    var_status_int.set(str(data.get("status", "--")))
                    
                    # Control Word
                    var_control_word.set(str(data.get("control", "--")))
        
        root.after(2000, lambda: self.update_param_display(
            param_vars, alarm_vars, alarm_actions, var_tt06_display,
            var_status_int, var_control_word, var_active_actions, root
        ))
    
    def update_ambient_display(self, var_s1, var_s2, var_dewavg, root):
        """
        Update ambient sensor displays from ambient poller data.
        
        Args:
            var_s1: StringVar for S1 display
            var_s2: StringVar for S2 display
            var_dewavg: StringVar for dew average display
            root: Tkinter root for scheduling next update
        """
        if self.ambient_poller:
            latest = self.ambient_poller.get_latest()
            s1 = latest.get("s1", (None, None, None))
            s2 = latest.get("s2", (None, None, None))
            dew_max = latest.get("dew_max", None)
            
            def fmt(vals):
                t, h, d = vals
                t_str = f"{t:.1f}" if t is not None else "--"
                h_str = f"{h:.0f}%" if h is not None else "--"
                d_str = f"{d:.1f}" if d is not None else "--"
                return f"T:{t_str} H:{h_str} D:{d_str}"
            
            var_s1.set(fmt(s1))
            var_s2.set(f"T:{s2[0]:.1f}" if s2[0] is not None else "T:--")
            var_dewavg.set("--" if dew_max is None else f"{dew_max:.2f}")
            
            self.ambient = latest  # Store for external access
        
        root.after(2000, lambda: self.update_ambient_display(var_s1, var_s2, var_dewavg, root))
    
    def check_health(self, lab_conn, root):
        """
        Check connection health and update status.
        
        Args:
            lab_conn: Label widget for connection status
            root: Tkinter root for scheduling next check
        """
        if self.connected and self.poller and self.poller.is_alive():
            elapsed = time.time() - self.poller.last_successful_read_time
            tolerance = self.poller.interval * 2.5
            
            if elapsed > tolerance:
                if lab_conn.cget("text") != "MARTA: POLLING FAILED":
                    self.log("POLLER HEARTBEAT FAILED. Updating status label.")
                    self.gui_update_q.put({"type": "conn_status", "text": "MARTA: POLLING FAILED", "fg": "red"})
            else:
                if lab_conn.cget("text") != "MARTA: Connected":
                    self.log("Poller heartbeat recovered.")
                    self.gui_update_q.put({"type": "conn_status", "text": "MARTA: Connected", "fg": "green"})
        
        elif not self.connected:
            if lab_conn.cget("text") != "MARTA: Disconnected":
                self.gui_update_q.put({"type": "conn_status", "text": "MARTA: Disconnected", "fg": "red"})
        
        self.health_check_job = root.after(5000, lambda: self.check_health(lab_conn, root))
    
    def is_connected(self):
        """Check if MARTA is connected."""
        return self.connected
    
    def is_esp32_connected(self):
        """Check if ESP32 is connected."""
        return self.esp_connected
    
    def get_poller(self):
        """Get the current DataPoller instance."""
        return self.poller
    
    def get_ambient_poller(self):
        """Get the current AmbientPoller instance."""
        return self.ambient_poller
    
    def get_latest_tt06(self):
        """Get the latest TT06 reading from poller."""
        if self.poller:
            with self.poller.lock:
                if hasattr(self.poller, 'temp') and len(self.poller.temp) > 5:
                    temps = list(self.poller.temp[5])
                    if temps:
                        return temps[-1]
        return None
