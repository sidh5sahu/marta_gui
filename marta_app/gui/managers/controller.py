"""
Controller for MARTA chiller and CO2 system.

Handles all control logic including chiller start/stop, CO2 control,
thermal cycling with dew point protection, and parameter updates.
"""

import time
import threading
import socket
import json
import tkinter as tk
from datetime import datetime
from tkinter import messagebox

from ...backend.modbus import write_float, write_control_word, REGISTER_PUMP_SPEED, REGISTER_TEMP_SETPOINT


class MartaController:
    """Manages chiller and CO2 control with thermal cycling logic."""
    
    def __init__(self, connection_mgr, gui_update_q, log_callback, report_mgr, plot_mgr, ladder_mgr=None):
        """
        Initialize MartaController.
        
        Args:
            connection_mgr: ConnectionManager instance
            gui_update_q: Queue for GUI updates
            log_callback: Function to call for logging messages
            report_mgr: ReportManager instance
            plot_mgr: PlotManager instance
            ladder_mgr: LadderManager instance
        """
        self.connection_mgr = connection_mgr
        self.gui_update_q = gui_update_q
        self.log = log_callback
        self.report_mgr = report_mgr
        self.plot_mgr = plot_mgr
        self.ladder_mgr = ladder_mgr
        
        # Control state
        self.chiller_on = False
        self.co2_on = False
        self.abort_cycle = False
        
        # Cycle parameters
        self.target_temp = None
        self.active_setpoint = None
        self.current_target = None
        
        # Stopwatch
        self.stopwatch_start_time = None
    
    def start_chiller(self, client_lock, enable_buttons_callback):
        """
        Start the chiller.
        
        Args:
            client_lock: Lock for Modbus client access
            enable_buttons_callback: Function to enable/disable buttons
            
        Returns:
            True if successful, False otherwise
        """
        if not self.connection_mgr.is_connected():
            self.log("Cannot start chiller: Not connected.")
            return False
        
        ok = False
        try:
            with client_lock:
                ok = write_control_word(self.connection_mgr.client, True, self.co2_on)
        except Exception as e:
            self.log(f"Start Chiller FAILED: {e}")
            ok = False
        
        if ok:
            self.chiller_on = True
            enable_buttons_callback('chiller_started')
            self.log("Chiller started.")
            self._enable_co2_after_delay()
            return True
        else:
            self.log("Chiller start failed.")
            return False
    
    def stop_chiller(self, client_lock, enable_buttons_callback, reset_stopwatch_callback, set_param_state_callback):
        """
        Stop the chiller.
        
        Args:
            client_lock: Lock for Modbus client access
            enable_buttons_callback: Function to enable/disable buttons
            reset_stopwatch_callback: Function to reset stopwatch display
            set_param_state_callback: Function to enable/disable parameter entries
            
        Returns:
            True if successful, False otherwise
        """
        if not self.connection_mgr.is_connected():
            self.log("Cannot stop chiller: Not connected.")
            return False
        
        ok = False
        try:
            with client_lock:
                ok = write_control_word(self.connection_mgr.client, False, False)
        except Exception as e:
            self.log(f"Stop Chiller FAILED: {e}")
            ok = False
        
        if ok:
            self.chiller_on = False
            self.co2_on = False
            self.abort_cycle = True
            enable_buttons_callback('chiller_stopped')
            self.stopwatch_start_time = None
            reset_stopwatch_callback()
            set_param_state_callback(tk.NORMAL)
            self.set_stable_color(False)
            self.log("Chiller stopped.")
            
            # Generate stop report and save plots
            tt06 = self.connection_mgr.get_latest_tt06()
            self.report_mgr.generate_stop_report("Chiller Stopped", tt06)
            self.plot_mgr.save_all_plots(self.report_mgr.current_run_dir)
            return True
        else:
            self.log("Chiller stop failed.")
            return False
    
    def start_co2(self, client_lock, params, enable_buttons_callback, set_param_state_callback, update_stopwatch_callback):
        """
        Start CO2 and begin thermal cycling.
        
        Args:
            client_lock: Lock for Modbus client access
            params: Dict with keys: max_temp, min_temp, cycles, dwell_s
            enable_buttons_callback: Function to enable/disable buttons
            set_param_state_callback: Function to enable/disable parameter entries
            update_stopwatch_callback: Function to start stopwatch updates
            
        Returns:
            True if successful, False otherwise
        """
        if not self.chiller_on:
            messagebox.showwarning("Start Chiller", "Please start Chiller first.")
            self.log("CO2 start failed: Chiller is off.")
            return False
        
        if not self.connection_mgr.is_connected():
            self.log("CO2 start failed: Not connected.")
            return False
        
        if not self.report_mgr.report_file_path:
            self.log("CO2 start failed: Run Directory not set up. (Did you Connect?)")
            messagebox.showerror("Run Error", "Run directory is not set. Please reconnect.")
            return False
        
        ok = False
        try:
            with client_lock:
                ok = write_control_word(self.connection_mgr.client, True, True)
        except Exception as e:
            self.log(f"Start CO2 FAILED: {e}")
            ok = False
        
        if ok:
            # Generate start report
            self.report_mgr.generate_start_report(params)
            
            self.co2_on = True
            self.abort_cycle = False
            enable_buttons_callback('co2_started')
            set_param_state_callback(tk.DISABLED)
            self.set_stable_color(False)
            
            self.stopwatch_start_time = time.time()
            update_stopwatch_callback()
            
            self.log("CO₂ started. Dewpoint-cycle active.")
            threading.Thread(target=self._dewpoint_cycle_worker, args=(client_lock, params), daemon=True).start()
            return True
        else:
            self.log("CO₂ start failed.")
            return False
    
    def stop_co2(self, client_lock, enable_buttons_callback, reset_stopwatch_callback, set_param_state_callback):
        """
        Stop CO2.
        
        Args:
            client_lock: Lock for Modbus client access
            enable_buttons_callback: Function to enable/disable buttons
            reset_stopwatch_callback: Function to reset stopwatch display
            set_param_state_callback: Function to enable/disable parameter entries
            
        Returns:
            True if successful, False otherwise
        """
        if not self.connection_mgr.is_connected():
            self.log("CO2 stop failed: Not connected.")
            return False
        
        ok = False
        try:
            with client_lock:
                ok = write_control_word(self.connection_mgr.client, True, False)
        except Exception as e:
            self.log(f"Stop CO2 FAILED: {e}")
            ok = False
        
        if ok:
            self.co2_on = False
            self.abort_cycle = True
            enable_buttons_callback('co2_stopped')
            
            self.stopwatch_start_time = None
            reset_stopwatch_callback()
            
            set_param_state_callback(tk.NORMAL)
            self.set_stable_color(False)
            self.log("CO₂ stopped.")
            
            # Generate stop report and save plots
            tt06 = self.connection_mgr.get_latest_tt06()
            self.report_mgr.generate_stop_report("CO2 Stopped", tt06)
            self.plot_mgr.save_all_plots(self.report_mgr.current_run_dir)
            return True
        else:
            self.log("CO₂ stop failed.")
            return False
    
    def stop_all(self, client_lock, enable_buttons_callback, reset_stopwatch_callback, set_param_state_callback, cancel_health_check_callback):
        """
        Emergency stop - stop everything and disconnect.
        
        Args:
            client_lock: Lock for Modbus client access
            enable_buttons_callback: Function to enable/disable buttons
            reset_stopwatch_callback: Function to reset stopwatch display
            set_param_state_callback: Function to enable/disable parameter entries
            cancel_health_check_callback: Function to cancel health check timer
        """
        # Generate reports if running
        if self.chiller_on or self.co2_on:
            tt06 = self.connection_mgr.get_latest_tt06()
            self.report_mgr.generate_stop_report("System Stop All", tt06)
            self.plot_mgr.save_all_plots(self.report_mgr.current_run_dir)
        
        # Stop control
        if self.connection_mgr.is_connected():
            try:
                with client_lock:
                    write_control_word(self.connection_mgr.client, False, False)
            except Exception as e:
                self.log(f"Stop All FAILED: {e}")
        
        self.abort_cycle = True
        self.co2_on = False
        self.chiller_on = False
        
        # Disconnect via connection manager
        self.connection_mgr.disconnect()
        
        set_param_state_callback(tk.NORMAL)
        enable_buttons_callback('all_stopped')
        
        self.stopwatch_start_time = None
        reset_stopwatch_callback()
        
        cancel_health_check_callback()
        
        self.set_stable_color(False)
        self.log("System stopped & disconnected.")
    
    def update_pump(self, pump_rpm, client_lock):
        """
        Update pump speed.
        
        Args:
            pump_rpm: Pump RPM value
            client_lock: Lock for Modbus client access
        """
        if not self.connection_mgr.is_connected():
            return
        
        try:
            val = float(pump_rpm)
        except ValueError:
            self.log("Invalid Pump RPM.")
            return
        
        ok = False
        try:
            with client_lock:
                ok = write_float(self.connection_mgr.client, REGISTER_PUMP_SPEED, val)
        except Exception as e:
            self.log(f"Pump RPM write FAILED: {e}")
            ok = False
        
        self.log(f"Pump RPM write {val} -> {'OK' if ok else 'FAIL'}")
    
    def send_power_supply_command(self, action, voltage=None, slot=1, channel=0):
        """Send a command to the power supply server."""
        try:
            cmd = {"command": action, "slot": slot, "channel": channel}
            if voltage is not None:
                cmd["voltage"] = voltage
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2.0)
                s.connect(("127.0.0.1", 5555))
                s.sendall((json.dumps(cmd) + "\n").encode('utf-8'))
            self.log(f"PSU Cmd: {action} {voltage if voltage else ''}")
        except Exception as e:
            self.log(f"PSU Cmd Failed: {e}")

    def set_stable_color(self, is_stable):
        """
        Update stability indicator color.
        
        Args:
            is_stable: True if system is stable, False otherwise
        """
        self.gui_update_q.put({"type": "stable_color", "color": "green" if is_stable else "red"})
    
    def get_active_setpoint(self):
        """Get the current active setpoint."""
        return self.active_setpoint if self.active_setpoint is not None else ""
    
    def get_current_target(self):
        """Get the current target temperature."""
        return self.current_target if self.current_target is not None else ""
    
    def _enable_co2_after_delay(self):
        """Enable CO2 button after 60 second countdown."""
        def countdown():
            for i in range(60, 0, -1):
                if not self.chiller_on:
                    self.gui_update_q.put({"type": "co2_btn", "text": "Start CO₂", "state": tk.DISABLED})
                    return
                self.gui_update_q.put({"type": "co2_btn", "text": f"Start CO₂ ({i}s)", "state": tk.DISABLED})
                time.sleep(1)
            if self.chiller_on:
                self.gui_update_q.put({"type": "co2_btn", "text": "Start CO₂", "state": tk.NORMAL})
        
        threading.Thread(target=countdown, daemon=True).start()
    
    def _dewpoint_cycle_worker(self, client_lock, params):
        """
        Worker thread for thermal cycling with dew point protection.
        
        Args:
            client_lock: Lock for Modbus client access
            params: Dict with keys: max_temp, min_temp, cycles, dwell_s
        """
        try:
            max_t = float(params['max_temp'])
            min_t = float(params['min_temp'])
            cycles = int(params['cycles'])
            dwell = int(params['dwell_s'])
        except Exception as e:
            self.log(f"Invalid parameters: {e}")
            self.gui_update_q.put({
                "type": "error",
                "title": "Parameter Error",
                "message": f"Invalid cycle parameters. Check values.\\nError: {e}"
            })
            return
        
        if not (max_t > min_t):
            err_msg = f"Max Temp ({max_t}) must be greater than Min Temp ({min_t})."
            self.log(f"Error: {err_msg}")
            self.gui_update_q.put({
                "type": "error",
                "title": "Parameter Error",
                "message": f"{err_msg}\\nCycle aborted."
            })
            return
        
        self.target_temp = max_t
        cycle_count = 0
        deadband = 0.7
        
        self.log(f"Starting direct-cycle logic Max={max_t} Min={min_t}")
        
        # --- INITIAL DWELL AT MAX TEMP ---
        self.log(f"Starting initial hold at {max_t:.2f}°C")
        self.current_target = max_t
        self.active_setpoint = max_t
        self.gui_update_q.put({"type": "setpoint_display", "value": f"{self.active_setpoint:.2f}"})
        
        try:
            with client_lock:
                write_float(self.connection_mgr.client, REGISTER_TEMP_SETPOINT, max_t)
        except Exception as e:
            self.log(f"Initial SP WRITE FAILED: {e}")
            self.gui_update_q.put({"type": "stop_co2"})
            return
        
        last_log_time = 0
        while not self.abort_cycle and self.co2_on:
            tt06 = self._get_latest_tt06()
            status_msg = ""
            if tt06 is None:
                status_msg = f"Waiting for initial TT06 data... (Target: {max_t:.2f}°C)"
            elif abs(tt06 - max_t) <= deadband:
                self.set_stable_color(True)
                self.log(f"✅ Initial TT06 reached {tt06:.2f}°C. Dwelling for {dwell}s.")
                self.send_power_supply_command("turn_on")
                self.send_power_supply_command("set_voltage", voltage=3.3)
                if self.connection_mgr.unified_logger:
                    log_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Event_Type": "DWELL_INIT",
                        "TT06": tt06,
                        "Target_Temp": max_t,
                        "Active_Setpoint": max_t,
                        "Status": f"DWELL_{dwell}s"
                    }
                    self.connection_mgr.unified_logger.log(log_data)
                break
            else:
                self.set_stable_color(False)
                status_msg = f"Waiting for initial TT06={tt06:.2f}°C -> {max_t:.2f}°C"
            
            now = time.time()
            if now - last_log_time >= 5.0:
                self.log(status_msg)
                last_log_time = now
            
            if self.abort_cycle or not self.co2_on:
                self.log("Cycle aborted during initial wait.")
                return
            time.sleep(1)
        
        if self.ladder_mgr:
            self.log("Triggering dynamic dwell: Running Ladder Tests...")
            def _cb(msg):
                self.log(f"[Ladder Test] {msg}")
            
            # This blocks until all modules are tested
            self.ladder_mgr.run_ladder_tests(progress_callback=_cb)
            self.log("Ladder Tests complete. Moving to next phase.")
        else:
            self.log(f"No ladder_mgr configured, dwelling for {dwell}s.")
            end_dwell = time.time() + dwell
            while time.time() < end_dwell and not self.abort_cycle and self.co2_on:
                time.sleep(1)
        
        if self.abort_cycle or not self.co2_on:
            self.log("Cycle aborted during initial dwell.")
            return
        
        # --- MAIN CYCLE LOOP ---
        while not self.abort_cycle and self.co2_on and cycle_count < cycles:
            
            going_down = (self.target_temp == max_t)
            target_temp = min_t if going_down else max_t
            self.target_temp = target_temp
            self.current_target = target_temp
            
            phase = "high_to_low" if going_down else "low_to_high"
            self.log(f"--- Starting Trip ({phase}) to {target_temp:.2f}°C ---")
            
            target_reached = False
            while not self.abort_cycle and self.co2_on:
                
                dew_max = None
                dew_limit = None
                ambient_data = {}
                if self.connection_mgr.ambient_poller:
                    latest_ambient = self.connection_mgr.ambient_poller.get_latest()
                    dew_max = latest_ambient.get("dew_max")
                    if dew_max is not None:
                        dew_limit = dew_max + 10.0
                    
                    s1 = latest_ambient.get("s1", (None, None, None))
                    s2 = latest_ambient.get("s2", (None, None, None))
                    
                    ambient_data = {
                        "Dew_Max": dew_max,
                        "Amb_S1_T": s1[0], "Amb_S1_H": s1[1], "Amb_S1_D": s1[2],
                        "Amb_S2_T": s2[0], "Amb_S2_H": s2[1], "Amb_S2_D": s2[2],
                    }
                
                temporary_target_temp = target_temp
                log_status = "WAITING"
                
                if going_down:
                    if dew_max is None:
                        temporary_target_temp = 20.0
                        log_status = "ESP32_FAIL_SAFE_20C"
                    elif dew_limit is not None and dew_limit > target_temp:
                        temporary_target_temp = dew_limit
                        log_status = "DEW_BLOCK"
                
                ok = False
                try:
                    with client_lock:
                        ok = write_float(self.connection_mgr.client, REGISTER_TEMP_SETPOINT, temporary_target_temp)
                except Exception as e:
                    self.log(f"SP WRITE FAILED: {e}")
                    ok = False
                
                if not ok:
                    self.log("❌ Failed to write SP, retrying in 10s...")
                    for _ in range(10):
                        if self.abort_cycle or not self.co2_on:
                            break
                        time.sleep(1)
                    continue
                
                self.active_setpoint = temporary_target_temp
                self.gui_update_q.put({"type": "setpoint_display", "value": f"{self.active_setpoint:.2f}"})
                log_msg = f"WAITING: TT06 must reach {temporary_target_temp:.2f}°C (Logical target: {target_temp:.2f}°C)"
                if log_status != "WAITING":
                    log_msg += f" [{log_status}]"
                self.log(log_msg)
                
                if self.connection_mgr.unified_logger:
                    log_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Event_Type": "LOGIC",
                        "Status": log_status,
                        "TT06": self._get_latest_tt06(),
                        "Target_Temp": target_temp,
                        "Active_Setpoint": temporary_target_temp,
                    }
                    log_data.update(ambient_data)
                    self.connection_mgr.unified_logger.log(log_data)
                
                self.set_stable_color(False)
                
                start_wait = time.time()
                last_log_time = start_wait
                
                while time.time() - start_wait < 10.0:
                    if self.abort_cycle or not self.co2_on:
                        break
                    
                    tt06 = self._get_latest_tt06()
                    
                    if tt06 is not None and abs(tt06 - temporary_target_temp) <= deadband:
                        self.set_stable_color(True)
                        
                        if log_status == "DEW_BLOCK" or log_status == "ESP32_FAIL_SAFE_20C":
                            now = time.time()
                            if now - last_log_time >= 5.0:
                                self.log(f"HOLDING at {tt06:.2f}°C due to {log_status}")
                                last_log_time = now
                        else:
                            self.log(f"✅ TT06 reached {tt06:.2f}°C (matches {temporary_target_temp:.2f}°C)")
                            
                            if going_down:
                                self.send_power_supply_command("turn_off")
                            else:
                                self.send_power_supply_command("turn_on")
                                self.send_power_supply_command("set_voltage", voltage=3.3)
                                
                            if self.connection_mgr.unified_logger:
                                log_data = {
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Event_Type": "LOGIC",
                                    "Status": "REACHED",
                                    "TT06": tt06,
                                    "Target_Temp": target_temp,
                                    "Active_Setpoint": temporary_target_temp,
                                }
                                log_data.update(ambient_data)
                                self.connection_mgr.unified_logger.log(log_data)
                            
                            target_reached = True
                            break
                    else:
                        self.set_stable_color(False)
                    
                    time.sleep(1)
                
                if target_reached:
                    break
                
                if self.abort_cycle or not self.co2_on:
                    break
            
            if self.abort_cycle or not self.co2_on:
                break
            
            self.log(f"Cycle reach target side, dwelling {dwell}s")
            if self.connection_mgr.unified_logger:
                ambient_data = {}
                if self.connection_mgr.ambient_poller:
                    latest_ambient = self.connection_mgr.ambient_poller.get_latest()
                    dew_max = latest_ambient.get("dew_max")
                    s1 = latest_ambient.get("s1", (None, None, None))
                    s2 = latest_ambient.get("s2", (None, None, None))
                    
                    ambient_data = {
                        "Dew_Max": dew_max,
                        "Amb_S1_T": s1[0], "Amb_S1_H": s1[1], "Amb_S1_D": s1[2],
                        "Amb_S2_T": s2[0], "Amb_S2_H": s2[1], "Amb_S2_D": s2[2],
                    }
                
                log_data = {
                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "Event_Type": "DWELL",
                    "Status": f"DWELL_{dwell}s",
                    "TT06": self._get_latest_tt06(),
                    "Target_Temp": self.target_temp,
                    "Active_Setpoint": self.active_setpoint,
                }
                log_data.update(ambient_data)
                self.connection_mgr.unified_logger.log(log_data)
            
            if self.ladder_mgr:
                self.log("Triggering dynamic dwell: Running Ladder Tests...")
                def _cb(msg):
                    self.log(f"[Ladder Test] {msg}")
                
                # This blocks until all modules are tested
                self.ladder_mgr.run_ladder_tests(progress_callback=_cb)
                self.log("Ladder Tests complete. Moving to next phase.")
            else:
                self.log(f"No ladder_mgr configured, dwelling for {dwell}s.")
                end_dwell = time.time() + dwell
                while time.time() < end_dwell and not self.abort_cycle and self.co2_on:
                    time.sleep(1)
            
            if self.abort_cycle or not self.co2_on:
                break
            
            if not going_down:
                cycle_count += 1
                self.log(f"--- Cycle {cycle_count}/{cycles} complete ---")
        
        self.log("✅ CYCLE SEQUENCE FINISHED OR ABORTED")
        
        if not self.abort_cycle and self.co2_on:
            self.log("Cycle finished. Stopping CO2.")
            self.gui_update_q.put({"type": "stop_co2"})
    
    def _get_latest_tt06(self):
        """Get the latest TT06 reading from poller."""
        poller = self.connection_mgr.get_poller()
        if not poller:
            return None
        
        with poller.lock:
            arr = poller.temp[5]
            if not arr:
                return None
            
            for v in reversed(arr):
                if v is not None:
                    return v
        
        return None
