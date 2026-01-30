#!/usr/bin/env python3
"""
Integration script to complete the refactoring of app.py.

This script replaces all remaining methods with manager delegations.
Run this to avoid manual errors in the large-scale refactoring.
"""

import re

# Read the current app.py
with open("marta_app/gui/app.py", "r") as f:
    content = f.read()

# List of method replacements
replacements = [
    # connect_esp32
    (
        r"    # ---------- Connect ESP32 ----------\n    def connect_esp32\(self\):.*?(?=\n    # ----------)",
        """    # ---------- Connect ESP32 ----------
    def connect_esp32(self):
        if self.connection_mgr.connect_esp32():
            self.connection_mgr.update_ambient_display(
                self.var_s1, self.var_s2, self.var_dewavg, self.root
            )

    # ----------"""
    ),
    
    # test_network_connection
    (
        r"    # ---------- Network Diagnostics ----------\n    def test_network_connection\(self\):.*?    def _run_network_test\(self, marta_ip, esp_ip\):.*?(?=\n    def )",
        """    # ---------- Network Diagnostics ----------
    def test_network_connection(self):
        self.connection_mgr.test_network()

    def """
    ),
    
    # update_pump
    (
        r"    def update_pump\(self\):.*?        self\.log\(f\"Pump RPM write \{val\} -> \{'OK' if ok else 'FAIL'\}\"\)",
        """    def update_pump(self):
        self.controller.update_pump(self.var_pump.get(), self.client_lock)""" 
    ),
    
    # start_chiller
    (
        r"    def start_chiller\(self\):.*?            self\.log\(\"Chiller start failed\.\"\)",
        """    def start_chiller(self):
        self.controller.start_chiller(
            self.client_lock,
            self._update_button_states
        )"""
    ),
    
    # stop_chiller
    (
        r"    def stop_chiller\(self\):.*?            self\.log\(\"Chiller stop failed\.\"\)",
        """    def stop_chiller(self):
        self.controller.stop_chiller(
            self.client_lock,
            self._update_button_states,
            self._reset_stopwatch,
            self._set_param_state
        )"""
    ),
    
    # start_co2
    (
        r"    def start_co2\(self\):.*?            self\.log\(\"CO₂ start failed\.\"\)",
        """    def start_co2(self):
        params = {
            'max_temp': self.var_max.get(),
            'min_temp': self.var_min.get(),
            'cycles': self.var_cycle.get(),
            'dwell_s': self.var_dwell.get()
        }
        self.controller.start_co2(
            self.client_lock,
            params,
            self._update_button_states,
            self._set_param_state,
            self._update_stopwatch
        )"""
    ),
    
    # stop_co2
    (
        r"    def stop_co2\(self\):.*?            self\.log\(\"CO₂ stop failed\.\"\)",
        """    def stop_co2(self):
        self.controller.stop_co2(
            self.client_lock,
            self._update_button_states,
            self._reset_stopwatch,
            self._set_param_state
        )"""
    ),
    
    # stop_all
    (
        r"    def stop_all\(self\):.*?        self\.log\(\"System stopped & disconnected\.\"\)",
        """    def stop_all(self):
        self.controller.stop_all(
            self.client_lock,
            self._update_button_states,
            self._reset_stopwatch,
            self._set_param_state,
            self._cancel_health_check
        )"""
    ),
    
    # Plot methods
    (
        r"    def open_all_temps_plot\(self\):.*?        self\.log\(\"All Temps plot opened\.\"\)",
        """    def open_all_temps_plot(self):
        self.plot_mgr.open_all_temps_plot()"""
    ),
    (
        r"    def open_ambient_temp_plot\(self\):.*?        self\.log\(\"Ambient Temp plot opened\.\"\)",
        """    def open_ambient_temp_plot(self):
        self.plot_mgr.open_ambient_temp_plot()"""
    ),
    (
        r"    def open_humidity_plot\(self\):.*?        self\.log\(\"Humidity plot opened\.\"\)",
        """    def open_humidity_plot(self):
        self.plot_mgr.open_humidity_plot()"""
    ),
    (
        r"    def open_dew_point_plot\(self\):.*?        self\.log\(\"Dew Point plot opened\.\"\)",
        """    def open_dew_point_plot(self):
        self.plot_mgr.open_dew_point_plot()"""
    ),
    (
        r"    def open_cycle_plot\(self\):.*?        self\.log\(\"Cycle plot opened\.\"\)",
        """    def open_cycle_plot(self):
        self.plot_mgr.open_cycle_plot()"""
    ),
    (
        r"    def open_unified_plot\(self\):.*?        self\.log\(\"Unified plot opened\.\"\)",
        """    def open_unified_plot(self):
        self.plot_mgr.open_unified_plot()"""
    ),
    (
        r"    def open_contact_point\(self\):.*?        self\.log\(\"Contact Point \(S2\) plot opened\.\"\)",
        """    def open_contact_point(self):
        self.plot_mgr.open_contact_point()"""
    ),
]

# Apply replacements
for pattern, replacement in replacements:
    content = re.sub(pattern, replacement, content, flags=re.DOTALL)

# Write back
with open("marta_app/gui/app.py", "w") as f:
    f.write(content)

print("Integration complete! Replaced methods with manager delegations.")
print("Next: Manually remove obsolete methods and update _process_gui_updates()")
