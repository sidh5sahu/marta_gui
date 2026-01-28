"""
Configuration Window for Marta GUI
Allows editing MARTA, ESP32, InfluxDB, and Path settings.
"""

import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
from ..config import load_config, save_config


class ConfigWindow(tk.Toplevel):
    def __init__(self, parent, on_save_callback=None):
        super().__init__(parent)
        self.title("Configuration")
        self.geometry("500x600")
        self.resizable(False, False)
        
        self.on_save_callback = on_save_callback
        self.config = load_config()
        
        # Make modal
        self.transient(parent)
        self.grab_set()
        
        self._create_widgets()
        self._load_values()
        
        # Center on parent
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() // 2) - (self.winfo_width() // 2)
        y = parent.winfo_y() + (parent.winfo_height() // 2) - (self.winfo_height() // 2)
        self.geometry(f"+{x}+{y}")

    def _create_widgets(self):
        # Main container with padding
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        row = 0
        
        # --- MARTA Section ---
        ttk.Label(main_frame, text="MARTA", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(main_frame, text="IP Address:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_marta_ip = ttk.Entry(main_frame, width=30)
        self.e_marta_ip.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- ESP32 Section ---
        ttk.Label(main_frame, text="ESP32", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(main_frame, text="IP Address:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_esp_ip = ttk.Entry(main_frame, width=30)
        self.e_esp_ip.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- InfluxDB Section ---
        ttk.Label(main_frame, text="InfluxDB", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(main_frame, text="URL:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_influx_url = ttk.Entry(main_frame, width=30)
        self.e_influx_url.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Token:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_influx_token = ttk.Entry(main_frame, width=30, show="*")
        self.e_influx_token.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Organization:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_influx_org = ttk.Entry(main_frame, width=30)
        self.e_influx_org.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Bucket:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_influx_bucket = ttk.Entry(main_frame, width=30)
        self.e_influx_bucket.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Enabled:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.var_influx_enabled = tk.BooleanVar()
        self.chk_influx_enabled = ttk.Checkbutton(main_frame, variable=self.var_influx_enabled)
        self.chk_influx_enabled.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- Paths Section ---
        ttk.Label(main_frame, text="Paths", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(main_frame, text="Run Sequence File:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        path_frame1 = ttk.Frame(main_frame)
        path_frame1.grid(row=row, column=1, sticky="w", pady=2)
        self.e_seq_file = ttk.Entry(path_frame1, width=25)
        self.e_seq_file.pack(side=tk.LEFT)
        ttk.Button(path_frame1, text="Browse", width=6, command=self._browse_seq_file).pack(side=tk.LEFT, padx=2)
        row += 1
        
        ttk.Label(main_frame, text="Base Log Dir:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        path_frame2 = ttk.Frame(main_frame)
        path_frame2.grid(row=row, column=1, sticky="w", pady=2)
        self.e_log_dir = ttk.Entry(path_frame2, width=25)
        self.e_log_dir.pack(side=tk.LEFT)
        ttk.Button(path_frame2, text="Browse", width=6, command=self._browse_log_dir).pack(side=tk.LEFT, padx=2)
        row += 1
        
        ttk.Separator(main_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- Cycle Defaults Section ---
        ttk.Label(main_frame, text="Cycle Defaults", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(main_frame, text="Max Temp (°C):").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_max_temp = ttk.Entry(main_frame, width=10)
        self.e_max_temp.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Min Temp (°C):").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_min_temp = ttk.Entry(main_frame, width=10)
        self.e_min_temp.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Cycles:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_cycles = ttk.Entry(main_frame, width=10)
        self.e_cycles.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(main_frame, text="Dwell (s):").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.e_dwell = ttk.Entry(main_frame, width=10)
        self.e_dwell.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        # --- Buttons ---
        btn_frame = ttk.Frame(main_frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=20)
        
        ttk.Button(btn_frame, text="Save", command=self._save, width=10).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy, width=10).pack(side=tk.LEFT, padx=10)

    def _load_values(self):
        """Load values from config into fields."""
        # MARTA
        self.e_marta_ip.insert(0, self.config.get("marta_ip", ""))
        
        # ESP32
        self.e_esp_ip.insert(0, self.config.get("esp32_ip", ""))
        
        # InfluxDB
        influx = self.config.get("influxdb", {})
        self.e_influx_url.insert(0, influx.get("url", "http://localhost:8086"))
        self.e_influx_token.insert(0, influx.get("token", ""))
        self.e_influx_org.insert(0, influx.get("org", ""))
        self.e_influx_bucket.insert(0, influx.get("bucket", ""))
        self.var_influx_enabled.set(influx.get("enabled", False))
        
        # Paths
        paths = self.config.get("paths", {})
        self.e_seq_file.insert(0, paths.get("run_sequence_file", ""))
        self.e_log_dir.insert(0, paths.get("base_log_dir", ""))
        
        # Cycle Defaults
        cycle_defaults = self.config.get("cycle_defaults", {})
        self.e_max_temp.insert(0, str(cycle_defaults.get("max_temp", 15)))
        self.e_min_temp.insert(0, str(cycle_defaults.get("min_temp", 10)))
        self.e_cycles.insert(0, str(cycle_defaults.get("cycles", 2)))
        self.e_dwell.insert(0, str(cycle_defaults.get("dwell_s", 60)))

    def _save(self):
        """Save values to config file."""
        # Update config dict
        self.config["marta_ip"] = self.e_marta_ip.get().strip()
        self.config["esp32_ip"] = self.e_esp_ip.get().strip()
        
        if "influxdb" not in self.config:
            self.config["influxdb"] = {}
        self.config["influxdb"]["url"] = self.e_influx_url.get().strip()
        self.config["influxdb"]["token"] = self.e_influx_token.get().strip()
        self.config["influxdb"]["org"] = self.e_influx_org.get().strip()
        self.config["influxdb"]["bucket"] = self.e_influx_bucket.get().strip()
        self.config["influxdb"]["enabled"] = self.var_influx_enabled.get()
        
        if "paths" not in self.config:
            self.config["paths"] = {}
        self.config["paths"]["run_sequence_file"] = self.e_seq_file.get().strip()
        self.config["paths"]["base_log_dir"] = self.e_log_dir.get().strip()
        
        if "cycle_defaults" not in self.config:
            self.config["cycle_defaults"] = {}
        try:
            self.config["cycle_defaults"]["max_temp"] = int(self.e_max_temp.get())
            self.config["cycle_defaults"]["min_temp"] = int(self.e_min_temp.get())
            self.config["cycle_defaults"]["cycles"] = int(self.e_cycles.get())
            self.config["cycle_defaults"]["dwell_s"] = int(self.e_dwell.get())
        except ValueError:
            tk.messagebox.showerror("Error", "Cycle defaults must be integers.")
            return
        
        # Save to file
        save_config(self.config)
        print("Configuration saved.")
        
        # Callback
        if self.on_save_callback:
            self.on_save_callback(self.config)
        
        self.destroy()

    def _browse_seq_file(self):
        path = filedialog.askopenfilename(
            title="Select Run Sequence File",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
        )
        if path:
            self.e_seq_file.delete(0, tk.END)
            self.e_seq_file.insert(0, path)

    def _browse_log_dir(self):
        path = filedialog.askdirectory(title="Select Base Log Directory")
        if path:
            self.e_log_dir.delete(0, tk.END)
            self.e_log_dir.insert(0, path)
