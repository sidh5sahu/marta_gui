import tkinter as tk
from tkinter import ttk
from tkinter import messagebox
from tkinter import filedialog
import re
import threading
import time
import os
import sys
import subprocess
from datetime import datetime
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import queue # Added: Required for queue.Queue()
import requests # Added: Required for ESP32 connection check
import socket # Added: Required for network testing

from ..config import load_config, save_config
from ..backend.modbus import get_modbus_client, write_float, write_control_word, REGISTER_PUMP_SPEED, REGISTER_TEMP_SETPOINT
from ..backend.logger import UnifiedEventLogger
from ..backend.poller import DataPoller, AmbientPoller
from ..web.server import update_pollers # Added: Import web server update function
from .config_window import ConfigWindow

class MartaGUI:
    def __init__(self, root):
        self.root = root
        root.title("Marta GUI v19 (Modular)")

        # Load Config
        self.config = load_config()

        self.log_q = queue.Queue() if 'queue' in globals() else __import__('queue').Queue()
        self.gui_update_q = queue.Queue() if 'queue' in globals() else __import__('queue').Queue()
        root.after(200, self._drain_log_q)
        root.after(100, self._process_gui_updates)
        self.animations = []

        # --- LAYOUT ---
        style = ttk.Style()
        style.theme_use('clam') 

        # --- MENU BAR ---
        self.menubar = tk.Menu(root)
        root.config(menu=self.menubar)
        
        # File Menu
        file_menu = tk.Menu(self.menubar, tearoff=0)
        self.menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Settings", command=self.open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)

        # Create Notebook (Tabs)
        self.notebook = ttk.Notebook(root)
        self.notebook.grid(row=0, column=0, columnspan=8, sticky="nsew", padx=5, pady=5)
        
        self.tab_main = ttk.Frame(self.notebook)
        self.tab_marta = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_main, text="Controller")
        self.notebook.add(self.tab_marta, text="Marta")
        self.notebook.add(self.tab_settings, text="Settings")
        
        # --- CONTROLLER TAB CONTENT ---
        # Store IP values for internal use (loaded from config, editable only in Settings)
        self.e_ip_value = self.config.get("marta_ip", "10.4.133.77")
        self.e_esp_ip_value = self.config.get("esp32_ip", "10.4.135.152")
        
        # Row 0: Connection Status and Buttons
        conn_frame = ttk.Frame(self.tab_main)
        conn_frame.grid(row=0, column=0, columnspan=8, pady=5, sticky="w")
        
        ttk.Button(conn_frame, text="Connect MARTA", command=self.connect).pack(side=tk.LEFT, padx=5)
        self.lab_conn = ttk.Label(conn_frame, text="MARTA: Disconnected", foreground="red", width=25, anchor="w")
        self.lab_conn.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(conn_frame, text="Connect ESP32", command=self.connect_esp32).pack(side=tk.LEFT, padx=5)
        self.lab_esp = ttk.Label(conn_frame, text="ESP32: Disconnected", foreground="red", width=25, anchor="w")
        self.lab_esp.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(conn_frame, text="Test Network", command=self.test_network_connection).pack(side=tk.LEFT, padx=5)
        
        # Row 1: Control Buttons
        btn_frame = ttk.Frame(self.tab_main)
        btn_frame.grid(row=1, column=0, columnspan=8, pady=10, sticky="w")
        self.btn_start_chiller = ttk.Button(btn_frame, text="Start Chiller", command=self.start_chiller, state=tk.DISABLED)
        self.btn_stop_chiller  = ttk.Button(btn_frame, text="Stop Chiller",  command=self.stop_chiller,  state=tk.DISABLED)
        self.btn_start_co2     = ttk.Button(btn_frame, text="Start CO₂",     command=self.start_co2,     state=tk.DISABLED)
        self.btn_stop_co2      = ttk.Button(btn_frame, text="Stop CO₂",      command=self.stop_co2,      state=tk.DISABLED)
        self.btn_stop_all      = ttk.Button(btn_frame, text="Stop System",   command=self.stop_all,      state=tk.DISABLED)
        for btn in [self.btn_start_chiller, self.btn_stop_chiller, self.btn_start_co2, self.btn_stop_co2, self.btn_stop_all]:
            btn.pack(side=tk.LEFT, padx=5)

        # Initialize runtime params from config (editable in Settings tab only)
        defaults = self.config.get("cycle_defaults", {})
        self.var_max   = tk.StringVar(value=str(defaults.get("max_temp", "15")))
        self.var_min   = tk.StringVar(value=str(defaults.get("min_temp", "10")))
        self.var_cycle = tk.StringVar(value=str(defaults.get("cycles", "2")))
        self.var_dwell = tk.StringVar(value=str(defaults.get("dwell_s", "60")))
        self.var_pump  = tk.StringVar(value=str(self.config.get("safety_limits", {}).get("pump_rpm_default", "6000")))

        # Row 2: displays
        ttk.Label(self.tab_main, text="Active Setpoint:").grid(row=2, column=0, sticky="e", padx=5, pady=5)
        self.var_setpoint_display = tk.StringVar(value="--")
        ttk.Entry(self.tab_main, textvariable=self.var_setpoint_display, width=10, state="readonly").grid(row=2, column=1, sticky="w", pady=5)
        ttk.Label(self.tab_main, text="TT06:").grid(row=2, column=2, sticky="e", padx=5, pady=5)
        self.var_tt06_display = tk.StringVar(value="--")
        ttk.Entry(self.tab_main, textvariable=self.var_tt06_display, width=10, state="readonly").grid(row=2, column=3, sticky="w", pady=5)
        self.lbl_status = tk.Label(self.tab_main, text="●", fg="red", font=("Arial", 14)); self.lbl_status.grid(row=2, column=4, sticky="w", padx=5, pady=5)

        # Row 3: Stopwatch and Current Run
        ttk.Label(self.tab_main, text="Cycle Timer:").grid(row=3, column=0, sticky="e", padx=5, pady=2)
        self.var_stopwatch_display = tk.StringVar(value="00:00")
        self.lab_stopwatch = ttk.Entry(self.tab_main, textvariable=self.var_stopwatch_display, width=10, state="readonly")
        self.lab_stopwatch.grid(row=3, column=1, sticky="w", pady=2)
        
        ttk.Label(self.tab_main, text="Current Run:").grid(row=3, column=2, sticky="e", padx=5, pady=2)
        self.var_current_run = tk.StringVar(value="Not connected")
        self.entry_current_run = ttk.Entry(self.tab_main, textvariable=self.var_current_run, width=30, state="readonly")
        self.entry_current_run.grid(row=3, column=3, columnspan=3, sticky="w", pady=2)

        # Row 4: Ambient S1 & S2
        ttk.Label(self.tab_main, text="S1 (AM2315C):").grid(row=4, column=0, sticky="e", padx=5, pady=2)
        self.var_s1 = tk.StringVar(value="--"); ttk.Entry(self.tab_main, textvariable=self.var_s1, width=22, state="readonly").grid(row=4,column=1,sticky="w", pady=2)
        
        ttk.Label(self.tab_main, text="S2 (MAX6675):").grid(row=4, column=2, sticky="e", padx=5, pady=2)
        self.var_s2 = tk.StringVar(value="--"); ttk.Entry(self.tab_main, textvariable=self.var_s2, width=22, state="readonly").grid(row=4,column=3,sticky="w", pady=2)

        ttk.Label(self.tab_main, text="Dew Max:").grid(row=4, column=4, sticky="e", padx=5, pady=2)
        self.var_dewavg = tk.StringVar(value="--"); ttk.Entry(self.tab_main, textvariable=self.var_dewavg, width=10, state="readonly").grid(row=4, column=5, sticky="w", pady=2)

        # Row 5: plots & logs
        plot_frame = ttk.Frame(self.tab_main)
        plot_frame.grid(row=5, column=0, columnspan=6, pady=2)
        ttk.Button(plot_frame, text="Marta Temp",         command=self.open_all_temps_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="ColdBox Temp",       command=self.open_ambient_temp_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="ColdBox Humidity",   command=self.open_humidity_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="ColdBox DewPoint",   command=self.open_dew_point_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="CyclePlot",          command=self.open_cycle_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="contactPoint",       command=self.open_contact_point).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="Unified Plot",       command=self.open_unified_plot).pack(side=tk.LEFT, padx=5)
        ttk.Button(plot_frame, text="Open Log File",      command=self.open_log_file).pack(side=tk.LEFT, padx=5)
        
        # --- MARTA TAB CONTENT ---
        self._init_marta_tab()
        
        # --- SETTINGS TAB CONTENT ---
        self._init_settings_tab()
        
        # --- BOTTOM ROW (Log Box) ---
        root.grid_rowconfigure(1, weight=1) 
        
        self.logbox = tk.Text(root, width=125, height=14, state=tk.DISABLED)
        self.logbox.grid(row=1, column=0, columnspan=8, sticky="nsew", padx=5, pady=5) 
        scroll = tk.Scrollbar(root, command=self.logbox.yview)
        scroll.grid(row=1, column=8, sticky="ns", pady=5) 
        self.logbox['yscrollcommand'] = scroll.set
        
        root.grid_rowconfigure(1, weight=1)      
        root.grid_columnconfigure(0, weight=1)    

        # runtime state
        self.client = None
        self.client_lock = threading.Lock() 
        self.connected = False
        self.chiller_on = False
        self.co2_on = False
        self.abort_cycle = False

        self.active_setpoint = None
        self.current_target = None

        self.logger = None 
        self.poller = None

        # ambient
        self.ambient = None
        self.ambient_poller = None
        self.esp_connected = False 

        # dew-cycle
        self.target_temp = float(self.var_max.get())
        self.cycle_phase = "initial"
        self.unified_logger = None 
        
        # Run Management State
        self.log_file_path = None 
        self.current_run_name_full = None
        self.current_run_name_short = None 
        self.current_run_dir = None 
        self.report_file_path = None 
        
        self.stopwatch_start_time = None
        self.health_check_job = None 

        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_marta_tab(self):
        # Bottom Frame: Scrollable Parameters
        bottom_frame = ttk.Frame(self.tab_marta)
        bottom_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Scrollable Frame
        canvas = tk.Canvas(bottom_frame)
        scrollbar = ttk.Scrollbar(bottom_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        # --- DEFINITIONS ---
        # Table 3.1 Read Values (Floats)
        self.param_defs = [
            (100, "PT01_R452A"), (102, "PT03_R452A"), (104, "PT04_R452A"),
            (106, "PT01_CO2"), (108, "PT02_CO2"), (110, "PT03_CO2"), (112, "PT04_CO2"), (114, "PT05_CO2"), (116, "PT06_CO2"),
            (118, "TT01_R452A"), (120, "TT02_R452A"), (122, "TT03_R452A"), (124, "TT04_R452A"),
            (126, "TT01_CO2"), (128, "TT02_CO2"), (130, "TT03_CO2"), (132, "TT04_CO2"), (134, "TT05_CO2"), (136, "TT06_CO2"), (138, "TT07_CO2"),
            (140, "FT01_CO2"), (142, "SH01_R452A"), (144, "SH03_R452A"), (146, "ST01_R452A"), (148, "ST03_R452A"),
            (150, "ST01_CO2"), (152, "ST02_CO2"), (154, "ST03_CO2"), (156, "ST04_CO2"), (158, "ST05_CO2"), (160, "ST06_CO2"),
            (162, "SC01_CO2"), (164, "SC02_CO2"), (166, "SC03_CO2"), (168, "SC04_CO2"), (170, "SC05_CO2"), (172, "SC06_CO2"),
            (174, "DP01_CO2"), (176, "DP02_CO2"), (178, "DP03_CO2"), (180, "DP04_CO2"),
            (182, "DT02_CO2"), (184, "DT03_CO2"), (186, "DP_EV3C_CO2"), (190, "SC01_CO2_Start"),
            (192, "EV1 pos"), (194, "EV2 pos"), (196, "EV3 pos"), (198, "EV3C pos"),
            (200, "LP speed"), (202, "EH power"),
            (204, "Temp SP"), (206, "Speed SP"), (208, "Flow SP"), (210, "TC04_TSP SP")
        ]
        
        # Table 3.2 Chiller Alarms (Address 300, 301)
        self.alarm_defs_chiller = [
            (300, 0, "ChTT_IOErr_FS", ""), (300, 1, "ChPT_IOErr_FS", ""), (300, 2, "PS_HP_FS", ""), (300, 3, "PS_LP_FS", ""),
            (300, 4, "CP_HP_FS", ""), (300, 5, "CP_HP_W", ""), (300, 6, "CP_LP_FS", ""), (300, 7, "CP_LP_W", ""),
            (300, 8, "SH03_R452A_FS", ""), (300, 9, "SH03_R452A_W", ""), (300, 10, "TT03_R452A_HT_W", ""), (300, 11, "TT03_R452A_LT_FS", ""),
            (300, 12, "TT03_R452A_LT_W", ""), (300, 13, "ST01_R452A_TS", ""), (300, 14, "ST01_R452A_W", ""), (300, 15, "TT04_R452A_HT_FS", ""),
            (301, 0, "TT04_R452A_HT_W", ""), (301, 1, "EV1_CEr_FS", ""), (301, 2, "EV2_CEr_FS", ""), (301, 3, "EV3_CEr_FS", ""),
            (301, 4, "CP_CB_FS", ""), (301, 5, "V_CB_FS", ""), (301, 6, "UPS_MODE_FS", ""), (301, 7, "EB_FS", ""), (301, 8, "CP_Cnt_FS", "")
        ]
        
        # Table 3.3 CO2 Alarms (Address 302, 303)
        self.alarm_defs_co2 = [
            (302, 0, "TT_IOErr_FS", ""), 
            (302, 1, "PT_IOErr_FS", ""), 
            (302, 2, "Pressure drop over FL1 too high", "Too low mass flow rate. Increase mass flow rate, reduce the CO2 flow resistance (e.g. with MV5/MV6 valves)"), 
            (302, 3, "Pressure drop over FL1 high", "Replace the FL1 filter"),
            (302, 4, "Pressure drop over FL2 too high", "Throttle the CO2 flow with valves MV5 and/or MV6"), 
            (302, 5, "Pressure drop over FL2 high", "Replace the FL2 filter"), 
            (302, 6, "Pump LP1 delta pressure too low", "Too high flow resistance in the CO2 loop, reduce pump speed, open MV5 /MV6 valves"), 
            (302, 7, "Pump LP1 delta pressure low", "Too high flow resistance in the CO2 loop, reduce pump speed, open MV5/ MV6 valves"),
            (302, 8, "Pump LP1 delta pressure too high", "Increase heat load"), 
            (302, 9, "Pump LP1 delta pressure high", "too small amount of CO2 in the system - chiller failure - change Set-point to 20°C"), 
            (302, 10, "DT03_CO2_HT_FS", ""), 
            (302, 11, "Pump LP1 delta temperature high", "Increase the pump speed"),
            (302, 12, "Pump outlet pressure too high", "Too high flow resistance in the CO2 loop, reduce pump speed, open MV5 /MV6 valves"), 
            (302, 13, "Pump suction subcooling too low", "too small amount of CO2 in the system"), 
            (302, 14, "Pump suction subcooling low", "too small amount of CO2 in the system"), 
            (302, 15, "Too low CO2 temperature", "- too small amount of CO2 in the system\n- chiller failure\n- change Set-point to 20°C"),
            (303, 0, "Accumulator pressure too high", "Contact Service"), 
            (303, 1, "Accumulator pressure high", "Contact Service"), 
            (303, 2, "Accumulator heater temperature too high", "Contact Service"), 
            (303, 3, "Accumulator heater temperature very high", "Contact Service"),
            (303, 4, "Accumulator heater temperature high", "Contact Service"), 
            (303, 5, "EV3C_CEr_FS", ""), 
            (303, 6, "Heater circuit breaker", "Contact Service"), 
            (303, 7, "CO2 pump circuit breaker", "Contact Service"),
            (303, 8, "Compressor circuit breaker", "Contact Service"),
            (303, 9, "Fans circuit breaker", "Contact Service"),
            (303, 10, "Low pressure - Pressure switch", "Leak of the R452A, Contact Service"),
            (303, 11, "High pressure - Pressure switch", "No condenser cooling: fan failure, dirty condenser, or high ambient temp"),
            (303, 12, "Pressure in compressor too high", "Contact Service"),
            (303, 13, "Power supply error", "Contact Service"),
            (303, 14, "Emergency stop", ""),
            (303, 15, "Interlock IN trigger", "")
        ]

        self.param_vars = {} # addr -> StringVar
        self.alarm_vars = {} # (addr, bit) -> Label widget (to change color)
        self.alarm_actions = {} # (addr, bit) -> action string

        # --- BUILD UI ---
        r = 0
        
        # Section 1: Read Values
        ttk.Label(self.scrollable_frame, text="--- READ VALUES ---", font=("Arial", 10, "bold")).grid(row=r, column=0, columnspan=4, pady=5, sticky="w"); r+=1
        
        col = 0
        start_r = r
        for addr, name in self.param_defs:
            ttk.Label(self.scrollable_frame, text=f"{name}:").grid(row=r, column=col*2, sticky="e", padx=2)
            v = tk.StringVar(value="--")
            ttk.Entry(self.scrollable_frame, textvariable=v, width=8, state="readonly").grid(row=r, column=col*2+1, sticky="w", padx=2)
            self.param_vars[addr] = v
            
            r += 1
            if r > start_r + 15: # Wrap columns
                r = start_r
                col += 1
        
        r = start_r + 16 # Move below table
        
        # Section 2: Alarms
        ttk.Label(self.scrollable_frame, text="--- ALARMS ---", font=("Arial", 10, "bold")).grid(row=r, column=0, columnspan=8, pady=10, sticky="w"); r+=1
        
        # Helper for alarms - now with 6 columns and consistent sizing
        def add_alarm_grid(defs, start_row):
            cr = start_row
            cc = 0
            max_cols = 6  # 6 columns for better fit
            for addr, bit, name, action in defs:
                # Truncate long names for display
                display_name = name if len(name) <= 25 else name[:22] + "..."
                lbl = tk.Label(self.scrollable_frame, text=display_name, bg="lightgray", 
                              width=25, anchor="w", padx=4, pady=2, relief="groove",
                              font=("Arial", 8))
                lbl.grid(row=cr, column=cc, padx=1, pady=1, sticky="ew")
                self.alarm_vars[(addr, bit)] = lbl
                self.alarm_actions[(addr, bit)] = action
                
                # Create tooltip for long names
                if len(name) > 25:
                    lbl.bind("<Enter>", lambda e, n=name: e.widget.config(bg="lightyellow"))
                    lbl.bind("<Leave>", lambda e: e.widget.config(bg="lightgray" if not getattr(e.widget, 'is_active', False) else "red"))
                
                cc += 1
                if cc >= max_cols:
                    cc = 0
                    cr += 1
            return cr + 1

        r = add_alarm_grid(self.alarm_defs_chiller + self.alarm_defs_co2, r)
        
        # Section 2.5: Active Actions
        ttk.Label(self.scrollable_frame, text="--- SUGGESTED ACTIONS ---", font=("Arial", 10, "bold")).grid(row=r, column=0, columnspan=4, pady=10, sticky="w"); r+=1
        self.var_active_actions = tk.StringVar(value="No active alarms.")
        lbl_actions = tk.Label(self.scrollable_frame, textvariable=self.var_active_actions, justify="left", anchor="w", fg="blue")
        lbl_actions.grid(row=r, column=0, columnspan=4, sticky="w", padx=5)
        r+=1

        # Section 3: Status & Control
        ttk.Label(self.scrollable_frame, text="--- STATUS & CONTROL ---", font=("Arial", 10, "bold")).grid(row=r, column=0, columnspan=4, pady=10, sticky="w"); r+=1
        
        ttk.Label(self.scrollable_frame, text="MARTA State (320):").grid(row=r, column=0, sticky="e")
        self.var_status_int = tk.StringVar(value="--")
        ttk.Entry(self.scrollable_frame, textvariable=self.var_status_int, width=10, state="readonly").grid(row=r, column=1, sticky="w")
        
        ttk.Label(self.scrollable_frame, text="Control Word (305):").grid(row=r, column=2, sticky="e")
        self.var_control_word = tk.StringVar(value="--")
        ttk.Entry(self.scrollable_frame, textvariable=self.var_control_word, width=10, state="readonly").grid(row=r, column=3, sticky="w")

    def _init_settings_tab(self):
        """Initialize the Settings tab content."""
        from tkinter import filedialog as fd
        
        # Scrollable frame for settings
        canvas = tk.Canvas(self.tab_settings)
        scrollbar = ttk.Scrollbar(self.tab_settings, orient="vertical", command=canvas.yview)
        settings_frame = ttk.Frame(canvas, padding="10")
        
        settings_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=settings_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        row = 0
        
        # --- MARTA Section ---
        ttk.Label(settings_frame, text="MARTA", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(settings_frame, text="IP Address:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_marta_ip = ttk.Entry(settings_frame, width=30)
        self.cfg_marta_ip.insert(0, self.config.get("marta_ip", ""))
        self.cfg_marta_ip.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Separator(settings_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- ESP32 Section ---
        ttk.Label(settings_frame, text="ESP32", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        ttk.Label(settings_frame, text="IP Address:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_esp_ip = ttk.Entry(settings_frame, width=30)
        self.cfg_esp_ip.insert(0, self.config.get("esp32_ip", ""))
        self.cfg_esp_ip.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Separator(settings_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- InfluxDB Section ---
        ttk.Label(settings_frame, text="InfluxDB", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        influx = self.config.get("influxdb", {})
        
        ttk.Label(settings_frame, text="URL:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_influx_url = ttk.Entry(settings_frame, width=30)
        self.cfg_influx_url.insert(0, influx.get("url", "http://localhost:8086"))
        self.cfg_influx_url.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Token:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_influx_token = ttk.Entry(settings_frame, width=30, show="*")
        self.cfg_influx_token.insert(0, influx.get("token", ""))
        self.cfg_influx_token.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Organization:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_influx_org = ttk.Entry(settings_frame, width=30)
        self.cfg_influx_org.insert(0, influx.get("org", ""))
        self.cfg_influx_org.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Bucket:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_influx_bucket = ttk.Entry(settings_frame, width=30)
        self.cfg_influx_bucket.insert(0, influx.get("bucket", ""))
        self.cfg_influx_bucket.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Enabled:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_influx_enabled = tk.BooleanVar(value=influx.get("enabled", False))
        ttk.Checkbutton(settings_frame, variable=self.cfg_influx_enabled).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Separator(settings_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- Paths Section ---
        ttk.Label(settings_frame, text="Paths", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        paths = self.config.get("paths", {})
        
        ttk.Label(settings_frame, text="Base Log Dir:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        path_frame2 = ttk.Frame(settings_frame)
        path_frame2.grid(row=row, column=1, sticky="w", pady=2)
        self.cfg_log_dir = ttk.Entry(path_frame2, width=25)
        self.cfg_log_dir.insert(0, paths.get("base_log_dir", ""))
        self.cfg_log_dir.pack(side=tk.LEFT)
        ttk.Button(path_frame2, text="Browse", width=6,
                   command=lambda: self._browse_for_entry(self.cfg_log_dir, "dir")).pack(side=tk.LEFT, padx=2)
        row += 1
        
        ttk.Separator(settings_frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10)
        row += 1
        
        # --- Cycle Defaults Section ---
        ttk.Label(settings_frame, text="Cycle Defaults", font=("Arial", 11, "bold")).grid(
            row=row, column=0, sticky="w", pady=(10, 5))
        row += 1
        
        cycle_defaults = self.config.get("cycle_defaults", {})
        
        ttk.Label(settings_frame, text="Max Temp (°C):").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_max_temp = ttk.Entry(settings_frame, width=10)
        self.cfg_max_temp.insert(0, str(cycle_defaults.get("max_temp", 15)))
        self.cfg_max_temp.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Min Temp (°C):").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_min_temp = ttk.Entry(settings_frame, width=10)
        self.cfg_min_temp.insert(0, str(cycle_defaults.get("min_temp", 10)))
        self.cfg_min_temp.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Cycles:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_cycles = ttk.Entry(settings_frame, width=10)
        self.cfg_cycles.insert(0, str(cycle_defaults.get("cycles", 2)))
        self.cfg_cycles.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Dwell (s):").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_dwell = ttk.Entry(settings_frame, width=10)
        self.cfg_dwell.insert(0, str(cycle_defaults.get("dwell_s", 60)))
        self.cfg_dwell.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        ttk.Label(settings_frame, text="Pump RPM:").grid(row=row, column=0, sticky="e", padx=5, pady=2)
        self.cfg_pump_rpm = ttk.Entry(settings_frame, width=10)
        self.cfg_pump_rpm.insert(0, str(self.config.get("safety_limits", {}).get("pump_rpm_default", 6000)))
        self.cfg_pump_rpm.grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        
        # --- Save Button ---
        btn_frame = ttk.Frame(settings_frame)
        btn_frame.grid(row=row, column=0, columnspan=3, pady=20)
        
        ttk.Button(btn_frame, text="Save Settings", command=self._save_settings_from_tab, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="Reload", command=self._reload_settings_tab, width=10).pack(side=tk.LEFT, padx=10)

    def _browse_for_entry(self, entry_widget, browse_type):
        """Browse for file or directory and update entry."""
        from tkinter import filedialog
        if browse_type == "file":
            path = filedialog.askopenfilename(
                title="Select File",
                filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
            )
        else:
            path = filedialog.askdirectory(title="Select Directory")
        
        if path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, path)

    def _save_settings_from_tab(self):
        """Save settings from the Settings tab."""
        # Update config dict
        self.config["marta_ip"] = self.cfg_marta_ip.get().strip()
        self.config["esp32_ip"] = self.cfg_esp_ip.get().strip()
        
        if "influxdb" not in self.config:
            self.config["influxdb"] = {}
        self.config["influxdb"]["url"] = self.cfg_influx_url.get().strip()
        self.config["influxdb"]["token"] = self.cfg_influx_token.get().strip()
        self.config["influxdb"]["org"] = self.cfg_influx_org.get().strip()
        self.config["influxdb"]["bucket"] = self.cfg_influx_bucket.get().strip()
        self.config["influxdb"]["enabled"] = self.cfg_influx_enabled.get()
        
        if "paths" not in self.config:
            self.config["paths"] = {}
        self.config["paths"]["base_log_dir"] = self.cfg_log_dir.get().strip()
        
        if "cycle_defaults" not in self.config:
            self.config["cycle_defaults"] = {}
        try:
            self.config["cycle_defaults"]["max_temp"] = int(self.cfg_max_temp.get())
            self.config["cycle_defaults"]["min_temp"] = int(self.cfg_min_temp.get())
            self.config["cycle_defaults"]["cycles"] = int(self.cfg_cycles.get())
            self.config["cycle_defaults"]["dwell_s"] = int(self.cfg_dwell.get())
        except ValueError:
            messagebox.showerror("Error", "Cycle defaults must be integers.")
            return
        
        # Pump RPM
        if "safety_limits" not in self.config:
            self.config["safety_limits"] = {}
        try:
            self.config["safety_limits"]["pump_rpm_default"] = int(self.cfg_pump_rpm.get())
        except ValueError:
            messagebox.showerror("Error", "Pump RPM must be an integer.")
            return
        
        # Save to file
        save_config(self.config)
        self.log("Configuration saved.")
        
        # Update runtime params in Controller tab
        defaults = self.config.get("cycle_defaults", {})
        self.var_max.set(str(defaults.get("max_temp", 15)))
        self.var_min.set(str(defaults.get("min_temp", 10)))
        self.var_cycle.set(str(defaults.get("cycles", 2)))
        self.var_dwell.set(str(defaults.get("dwell_s", 60)))
        self.var_pump.set(str(self.config.get("safety_limits", {}).get("pump_rpm_default", 6000)))
        
        messagebox.showinfo("Settings", "Configuration saved successfully!")

    def _reload_settings_tab(self):
        """Reload settings from config file into the Settings tab."""
        from ..config import load_config
        self.config = load_config()
        
        # MARTA
        self.cfg_marta_ip.delete(0, tk.END)
        self.cfg_marta_ip.insert(0, self.config.get("marta_ip", ""))
        
        # ESP32
        self.cfg_esp_ip.delete(0, tk.END)
        self.cfg_esp_ip.insert(0, self.config.get("esp32_ip", ""))
        
        # InfluxDB
        influx = self.config.get("influxdb", {})
        self.cfg_influx_url.delete(0, tk.END)
        self.cfg_influx_url.insert(0, influx.get("url", ""))
        self.cfg_influx_token.delete(0, tk.END)
        self.cfg_influx_token.insert(0, influx.get("token", ""))
        self.cfg_influx_org.delete(0, tk.END)
        self.cfg_influx_org.insert(0, influx.get("org", ""))
        self.cfg_influx_bucket.delete(0, tk.END)
        self.cfg_influx_bucket.insert(0, influx.get("bucket", ""))
        self.cfg_influx_enabled.set(influx.get("enabled", False))
        
        # Paths
        paths = self.config.get("paths", {})
        self.cfg_log_dir.delete(0, tk.END)
        self.cfg_log_dir.insert(0, paths.get("base_log_dir", ""))
        
        # Cycle Defaults
        cycle_defaults = self.config.get("cycle_defaults", {})
        self.cfg_max_temp.delete(0, tk.END)
        self.cfg_max_temp.insert(0, str(cycle_defaults.get("max_temp", 15)))
        self.cfg_min_temp.delete(0, tk.END)
        self.cfg_min_temp.insert(0, str(cycle_defaults.get("min_temp", 10)))
        self.cfg_cycles.delete(0, tk.END)
        self.cfg_cycles.insert(0, str(cycle_defaults.get("cycles", 2)))
        self.cfg_dwell.delete(0, tk.END)
        self.cfg_dwell.insert(0, str(cycle_defaults.get("dwell_s", 60)))
        
        # Pump RPM
        self.cfg_pump_rpm.delete(0, tk.END)
        self.cfg_pump_rpm.insert(0, str(self.config.get("safety_limits", {}).get("pump_rpm_default", 6000)))
        
        self.log("Settings reloaded from config file.")

    def _process_gui_updates(self):
        try:
            while True:
                msg = self.gui_update_q.get_nowait()
                msg_type = msg.get("type")
                if msg_type == "conn_status":
                    self.lab_conn.config(text=msg["text"], foreground=msg["fg"])
                elif msg_type == "esp_status":
                    self.lab_esp.config(text=msg["text"], foreground=msg["fg"])
                elif msg_type == "stable_color":
                    self.lbl_status.config(fg=msg["color"])
                elif msg_type == "co2_btn":
                    self.btn_start_co2.config(text=msg["text"], state=msg["state"])
                elif msg_type == "error":
                    messagebox.showerror(msg["title"], msg["message"])
        except queue.Empty:
            pass
        self.root.after(100, self._process_gui_updates)

    def _param_row(self, row, label, var, cmd):
        ttk.Label(self.tab_main, text=label).grid(row=row, column=0, sticky="e", padx=5, pady=2)
        e = ttk.Entry(self.tab_main, textvariable=var, width=10); e.grid(row=row, column=1, sticky="w", pady=2)
        b = ttk.Button(self.tab_main, text="Update", command=cmd); b.grid(row=row, column=4, sticky="w", padx=5, pady=2)
        if not hasattr(self, "param_entries"):
            self.param_entries = []
        self.param_entries.append((e, b))

    def _drain_log_q(self):
        try:
            while True:
                self._append_log(self.log_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(200, self._drain_log_q)

    def _append_log(self, msg):
        self.logbox.config(state=tk.NORMAL)
        self.logbox.insert(tk.END, msg + "\n")
        self.logbox.see(tk.END)
        self.logbox.config(state=tk.DISABLED)

    def log(self, msg):
        line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        self.log_q.put(line)
        print(line)

    # --- Run Sequence Processing ---
    def _process_run_sequence(self):
        base_log_dir = self.config.get("paths", {}).get("base_log_dir", "")
        
        if not base_log_dir:
            self.log("Error: Base Log Dir must be set in Settings.")
            messagebox.showerror("Setup Error", "Please set the Base Log Directory in the Settings tab.")
            return False

        try:
            # Get last run number from config (no external file needed)
            last_run_num = self.config.get("last_run_number", 0)
            new_run_num = last_run_num + 1
            new_run_num_str = f"{new_run_num:02d}"
            
            now = datetime.now()
            date_str = now.strftime("%d%m%Y")
            time_str = now.strftime("%H%M")
            
            self.current_run_name_full = f"run_{new_run_num_str}_{date_str}_{time_str}"
            self.current_run_name_short = f"run_{new_run_num_str}_{date_str}"

            self.current_run_dir = os.path.join(base_log_dir, self.current_run_name_full)
            os.makedirs(self.current_run_dir, exist_ok=True)
            self.log(f"Created new run directory: {self.current_run_dir}")
            
            # Update UI to show current run
            self.var_current_run.set(self.current_run_name_full)

            self.report_file_path = os.path.join(self.current_run_dir, f"{self.current_run_name_short}.md")
            
            # Save new run number to config
            self.config["last_run_number"] = new_run_num
            save_config(self.config)
            
            return True

        except Exception as e:
            self.log(f"Error processing run sequence: {e}")
            messagebox.showerror("Run Sequence Error", f"Could not create run directory: {e}")
            return False

    def _write_to_report(self, text, mode="a"):
        if not self.report_file_path:
            self.log("Error: Report file path is not set.")
            return
        try:
            with open(self.report_file_path, mode, encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            self.log(f"Error writing to report: {e}")
            
    def _generate_start_report(self):
        self.log("Generating start report...")
        report_content = f"# MARTA Run Report: {self.current_run_name_full}\n\n"
        report_content += "## Starting Parameters\n"
        report_content += f"- **Start Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report_content += f"- **Max Temp (°C):** {self.var_max.get()}\n"
        report_content += f"- **Min Temp (°C):** {self.var_min.get()}\n"
        report_content += f"- **# Cycles:** {self.var_cycle.get()}\n"
        report_content += f"- **Dwell (s):** {self.var_dwell.get()}\n"
        report_content += f"- **Pump RPM:** {self.var_pump.get()}\n\n"
        
        self._write_to_report(report_content, mode="w")

    def _generate_stop_report(self, stop_reason):
        self.log("Generating stop report...")
        report_content = "\n## Run Stopped\n"
        report_content += f"- **Stop Reason:** {stop_reason}\n"
        report_content += f"- **Stop Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        report_content += f"- **Final TT06:** {self.var_tt06_display.get()}\n"
        
        self._write_to_report(report_content, mode="a")

    def _save_all_plots(self):
        """Save all plots to JPEG in the current run directory."""
        if not self.current_run_dir:
            self.log("Cannot save plots: No run directory set.")
            return
        
        plots_saved = 0
        
        # Save open animated plots if any
        if self.animations:
            self.log(f"Saving {len(self.animations)} open plot windows...")
            for ani in self.animations:
                try:
                    fig = ani.fig if hasattr(ani, 'fig') else ani._fig
                    title = fig.canvas.manager.get_window_title()
                    safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)
                    save_path = os.path.join(self.current_run_dir, f"{safe_title}.jpg")
                    fig.savefig(save_path, dpi=150, bbox_inches='tight')
                    plots_saved += 1
                except Exception as e:
                    self.log(f"Error saving plot: {e}")
        
        # Generate static plots from poller data (even if no windows open)
        try:
            # Generate static plots using the existing backend

            
            # Plot 1: MARTA Temperatures (if data available)
            if self.poller and hasattr(self.poller, 'timestamps') and len(self.poller.timestamps) > 0:
                with self.poller.lock:
                    t = list(self.poller.timestamps)
                    temps = [list(self.poller.temp[i]) for i in range(min(6, len(self.poller.temp)))]
                
                if t and any(temps):
                    fig, ax = plt.subplots(figsize=(12, 6))
                    labels = [f"TT0{i+1}" for i in range(len(temps))]
                    for lab, y in zip(labels, temps):
                        if y:
                            ax.plot(t, y, label=lab)
                    ax.set_ylabel("Temperature (°C)")
                    ax.set_xlabel("Time")
                    ax.set_title("MARTA Temperatures")
                    ax.legend()
                    ax.grid(True)
                    fig.autofmt_xdate()
                    save_path = os.path.join(self.current_run_dir, "marta_temperatures.jpg")
                    fig.savefig(save_path, dpi=150, bbox_inches='tight')
                    plt.close(fig)
                    plots_saved += 1
                    self.log(f"Saved: marta_temperatures.jpg")
            
            # Plot 2: Ambient Data (if ESP32 connected)
            if self.ambient_poller and hasattr(self.ambient_poller, 'timestamps') and len(self.ambient_poller.timestamps) > 0:
                with self.ambient_poller.lock:
                    t = list(self.ambient_poller.timestamps)
                    s1_t = list(self.ambient_poller.s1["temp"])
                    s1_h = list(self.ambient_poller.s1["hum"])
                    s1_d = list(self.ambient_poller.s1["dew"])
                    s2_t = list(self.ambient_poller.s2["temp"])
                
                if t:
                    # Ambient Temperature Plot
                    fig, ax = plt.subplots(figsize=(12, 6))
                    if s1_t: ax.plot(t, s1_t, label="S1 Temp", color='blue')
                    if s2_t: ax.plot(t, s2_t, label="S2 Temp", color='orange')
                    ax.set_ylabel("Temperature (°C)")
                    ax.set_xlabel("Time")
                    ax.set_title("Ambient Temperatures")
                    ax.legend()
                    ax.grid(True)
                    fig.autofmt_xdate()
                    save_path = os.path.join(self.current_run_dir, "ambient_temperature.jpg")
                    fig.savefig(save_path, dpi=150, bbox_inches='tight')
                    plt.close(fig)
                    plots_saved += 1
                    self.log(f"Saved: ambient_temperature.jpg")
                    
                    # Humidity Plot
                    if s1_h:
                        fig, ax = plt.subplots(figsize=(12, 6))
                        ax.plot(t, s1_h, label="Humidity", color='green')
                        ax.set_ylabel("Humidity (%)")
                        ax.set_xlabel("Time")
                        ax.set_title("Ambient Humidity")
                        ax.legend()
                        ax.grid(True)
                        fig.autofmt_xdate()
                        save_path = os.path.join(self.current_run_dir, "ambient_humidity.jpg")
                        fig.savefig(save_path, dpi=150, bbox_inches='tight')
                        plt.close(fig)
                        plots_saved += 1
                        self.log(f"Saved: ambient_humidity.jpg")
                    
                    # Dew Point Plot
                    if s1_d:
                        fig, ax = plt.subplots(figsize=(12, 6))
                        ax.plot(t, s1_d, label="Dew Point", color='purple')
                        ax.set_ylabel("Dew Point (°C)")
                        ax.set_xlabel("Time")
                        ax.set_title("Dew Point")
                        ax.legend()
                        ax.grid(True)
                        fig.autofmt_xdate()
                        save_path = os.path.join(self.current_run_dir, "dew_point.jpg")
                        fig.savefig(save_path, dpi=150, bbox_inches='tight')
                        plt.close(fig)
                        plots_saved += 1
                        self.log(f"Saved: dew_point.jpg")
            
            # Done saving plots
            
        except Exception as e:
            self.log(f"Error generating plots: {e}")
        
        if plots_saved > 0:
            self.log(f"Total {plots_saved} plots saved to {self.current_run_dir}")
        else:
            self.log("No data available to generate plots.")

    # ---------- Connect MARTA ----------
    def connect(self):
        if not self._process_run_sequence():
            self.log("Aborting connection: Run sequence setup failed.")
            return

        ip = self.config.get("marta_ip", "")
        if not ip:
            messagebox.showwarning("MARTA IP", "Please set MARTA IP in the Settings tab.")
            return
        self.log(f"Connecting to {ip}...")
        c = get_modbus_client(ip)
        if not c.connect():
            self.gui_update_q.put({"type": "conn_status", "text": "Failed", "fg": "red"})
            self.log("Connection failed.")
            return
        self.client = c
        self.connected = True
        self.gui_update_q.put({"type": "conn_status", "text": "Connected", "fg": "green"})
        self.log("Connected to MARTA.")

        self.btn_start_chiller.config(state=tk.NORMAL)
        self.btn_stop_all.config(state=tk.NORMAL)

        self.unified_logger = UnifiedEventLogger(
            base_dir=self.config.get("paths", {}).get("base_log_dir", ""),
            run_name=self.current_run_name_short,
            run_dir=self.current_run_dir  # Pass existing directory to avoid duplication
        )
        # Let's assume for now I pass `self.current_run_dir` as `base_dir` and it might create a subdir inside it. That's messy.
        # I'll fix `logger.py` in a separate step. For now I'll use `self.current_run_dir`.
        
        self.log_file_path = self.unified_logger.path
        
        self.poller = DataPoller(self.client, self.client_lock, self.unified_logger, 
                                 self.get_active_setpoint, self.get_current_target, 
                                 interval=10.0)
        
        self.poller.start()
        update_pollers(self.poller, self.ambient_poller)
        self.update_param_display()
        self._check_connection_health()

    # ---------- Connect ESP32 ----------
    def connect_esp32(self):
        ip = self.config.get("esp32_ip", "")
        if not ip:
            messagebox.showwarning("ESP32 IP", "Please set ESP32 IP in the Settings tab.")
            return
            
        if self.ambient_poller:
            self.ambient_poller.stop()
            self.ambient_poller = None
            
        url = f"http://{ip}/data"
        self.log(f"Testing ESP32 connection at {url}...")
        
        try:
            # requests is not imported? I need to import requests in app.py
            import requests
            r = requests.get(url, timeout=5)
            r.raise_for_status() 
            _ = r.json() 
            
            self.gui_update_q.put({"type": "esp_status", "text": f"ESP32: Connected ({ip})", "fg": "green"})
            self.log("ESP32 connection test successful.")
            self.esp_connected = True 
            
            self.ambient_poller = AmbientPoller(lambda: self.config.get("esp32_ip", ""), interval=10.0)
            self.ambient_poller.start()
            update_pollers(self.poller, self.ambient_poller)
            self.update_ambient_display()

        except Exception as e:
            self.log(f"ESP32 connection FAILED: {e}")
            self.gui_update_q.put({"type": "error", "title": "ESP32 Connection Failed", "message": f"Could not connect to {ip}.\n\nError: {e}"})
            self.gui_update_q.put({"type": "esp_status", "text": "ESP32: FAILED", "fg": "red"})
            self.esp_connected = False 

    # ---------- Network Diagnostics ----------
    def test_network_connection(self):
        marta_ip = self.config.get("marta_ip", "")
        esp_ip = self.config.get("esp32_ip", "")
        
        self.log(f"Starting network test for MARTA ({marta_ip}) and ESP32 ({esp_ip})...")
        threading.Thread(target=self._run_network_test, args=(marta_ip, esp_ip), daemon=True).start()

    def _run_network_test(self, marta_ip, esp_ip):
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
            
        final_msg = "\n".join(results)
        self.log(f"Network Test Results:\n{final_msg}")
        self.gui_update_q.put({"type": "error", "title": "Network Test Results", "message": final_msg}) 

    def update_param_display(self):
        if self.poller:
            with self.poller.lock:
                data = getattr(self.poller, "full_data", None)
                if data:
                    # Update Floats
                    floats = data.get("floats", {})
                    for addr, var in self.param_vars.items():
                        val = floats.get(addr)
                        var.set(f"{val:.2f}" if val is not None else "--")
                        
                        # Sync TT06 to main display
                        if addr == 136: 
                            self.var_tt06_display.set(f"{val:.2f}" if val is not None else "--")
                            
                    # Update Alarms & Actions
                    alarms = data.get("alarms", {})
                    active_actions_list = []
                    
                    for (addr, bit), lbl in self.alarm_vars.items():
                        reg_val = alarms.get(addr, 0)
                        is_set = (reg_val >> bit) & 1
                        lbl.config(bg="red" if is_set else "lightgray", fg="white" if is_set else "black")
                        
                        if is_set:
                            action = self.alarm_actions.get((addr, bit))
                            if action:
                                active_actions_list.append(f"• {lbl.cget('text')}: {action}")
                    
                    if active_actions_list:
                        self.var_active_actions.set("\n".join(active_actions_list))
                    else:
                        self.var_active_actions.set("No active alarms.")
                        
                    # Update Status
                    self.var_status_int.set(str(data.get("status", "--")))
                    
                    # Control Word
                    self.var_control_word.set(str(data.get("control", "--")))

        self.root.after(2000, self.update_param_display)

    def update_ambient_display(self):
        if self.ambient_poller:
            latest = self.ambient_poller.get_latest()
            s1 = latest.get("s1", (None,None,None))
            s2 = latest.get("s2", (None,None,None))
            dew_max = latest.get("dew_max", None)

            def fmt(vals):
                t, h, d = vals
                t_str = f"{t:.1f}" if t is not None else "--"
                h_str = f"{h:.0f}%" if h is not None else "--"
                d_str = f"{d:.1f}" if d is not None else "--"
                return f"T:{t_str} H:{h_str} D:{d_str}"

            self.var_s1.set(fmt(s1))
            self.var_s2.set(f"T:{s2[0]:.1f}" if s2[0] is not None else "T:--") # S2 has no hum/dew
            
            self.var_dewavg.set("--" if dew_max is None else f"{dew_max:.2f}")
            
            self.ambient = latest # Store for contact point logging
            
        self.root.after(2000, self.update_ambient_display)

    def open_log_file(self):
        if hasattr(self, 'log_file_path') and self.log_file_path:
            try:
                os.startfile(self.log_file_path)
                self.log(f"Opening log file: {self.log_file_path}")
            except AttributeError:
                try:
                    if sys.platform == "darwin": 
                        subprocess.call(["open", self.log_file_path])
                    else: 
                        subprocess.call(["xdg-open", self.log_file_path])
                    self.log(f"Opening log file: {self.log_file_path}")
                except Exception as e:
                    self.log(f"Error opening log file: {e}")
                    messagebox.showerror("Error", f"Could not open log file.\n{e}")
            except Exception as e:
                self.log(f"Error opening log file: {e}")
                messagebox.showerror("Error", f"Could not open log file.\n{e}")
        else:
            messagebox.showwarning("No Log File", "No log file has been created yet. Connect to MARTA first.")

    def open_settings(self):
        """Open the configuration window."""
        ConfigWindow(self.root, on_save_callback=self._on_config_saved)
    
    def _on_config_saved(self, new_config):
        """Callback when config is saved from ConfigWindow."""
        self.config = new_config
        self.log("Configuration saved. UI fields updated.")
        
        # Update cycle defaults in Controller tab
        defaults = new_config.get("cycle_defaults", {})
        self.var_max.set(str(defaults.get("max_temp", 15)))
        self.var_min.set(str(defaults.get("min_temp", 10)))
        self.var_cycle.set(str(defaults.get("cycles", 2)))
        self.var_dwell.set(str(defaults.get("dwell_s", 60)))

    def set_stable_color(self, is_stable: bool):
        self.gui_update_q.put({"type": "stable_color", "color": "green" if is_stable else "red"})
        
    def _update_stopwatch(self):
        if self.stopwatch_start_time is None:
            return 
        
        elapsed_sec = int(time.time() - self.stopwatch_start_time)
        elapsed_min = elapsed_sec // 60
        elapsed_hr = elapsed_min // 60
        display_min = elapsed_min % 60
        
        self.var_stopwatch_display.set(f"{elapsed_hr:02d}:{display_min:02d}")
        
        self.root.after(1000, self._update_stopwatch)

    # -------- param updates ----------
    def update_max(self):   self.log(f"Max Temp updated: {self.var_max.get()}"); self.target_temp = float(self.var_max.get())
    def update_min(self):   self.log(f"Min Temp updated: {self.var_min.get()}")
    def update_cycles(self):self.log(f"Cycles updated: {self.var_cycle.get()}")
    def update_dwell(self): self.log(f"Dwell updated: {self.var_dwell.get()}")
    def update_pump(self):
        if not self.connected: return
        try:
            val = float(self.var_pump.get())
        except ValueError:
            self.log("Invalid Pump RPM.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_float(self.client, REGISTER_PUMP_SPEED, val)
        except Exception as e:
            self.log(f"Pump RPM write FAILED: {e}")
            ok = False
            
        self.log(f"Pump RPM write {val} -> {'OK' if ok else 'FAIL'}")

    def get_active_setpoint(self):
        return self.active_setpoint if self.active_setpoint is not None else ""
    def get_current_target(self):
        return self.current_target if self.current_target is not None else ""

    def _set_param_state(self, state):
        """Enable or disable parameter entries."""
        for e, b in getattr(self, "param_entries", []):
            e.config(state=state)
            b.config(state=state)

    # ---------- Chiller / CO2 controls ----------
    def start_chiller(self):
        if not self.connected: 
            self.log("Cannot start chiller: Not connected.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, True, self.co2_on)
        except Exception as e:
            self.log(f"Start Chiller FAILED: {e}")
            ok = False
            
        if ok:
            self.chiller_on = True
            self.btn_start_chiller.config(state=tk.DISABLED)
            self.btn_stop_chiller.config(state=tk.NORMAL)
            self.log("Chiller started.")
            self._enable_co2_after_delay()
        else:
            self.log("Chiller start failed.")

    def _enable_co2_after_delay(self):
        self.btn_start_co2.config(state=tk.DISABLED)
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

    def stop_chiller(self):
        if not self.connected: 
            self.log("Cannot stop chiller: Not connected.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, False, False)
        except Exception as e:
            self.log(f"Stop Chiller FAILED: {e}")
            ok = False
            
        if ok:
            self.chiller_on = False
            self.co2_on = False
            self.abort_cycle = True
            self.btn_start_chiller.config(state=tk.NORMAL)
            self.btn_stop_chiller.config(state=tk.DISABLED)
            self.btn_start_co2.config(state=tk.DISABLED, text="Start CO₂")
            self.btn_stop_co2.config(state=tk.DISABLED)
            self.stopwatch_start_time = None 
            self.var_stopwatch_display.set("00:00")
            self._set_param_state(tk.NORMAL)
            self.set_stable_color(False)
            self.log("Chiller stopped.")
            
            self._generate_stop_report("Chiller Stopped")
            self._save_all_plots()
        else:
            self.log("Chiller stop failed.")

    def start_co2(self):
        if not self.chiller_on:
            messagebox.showwarning("Start Chiller", "Please start Chiller first.")
            self.log("CO2 start failed: Chiller is off.")
            return
        if not self.connected: 
            self.log("CO2 start failed: Not connected.")
            return
        
        if not self.report_file_path:
            self.log("CO2 start failed: Run Directory not set up. (Did you Connect?)")
            messagebox.showerror("Run Error", "Run directory is not set. Please reconnect.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, True, True)
        except Exception as e:
            self.log(f"Start CO2 FAILED: {e}")
            ok = False
            
        if ok:
            self._generate_start_report()

            self.co2_on = True
            self.abort_cycle = False
            self.btn_start_co2.config(state=tk.DISABLED)
            self.btn_stop_co2.config(state=tk.NORMAL)
            self._set_param_state(tk.DISABLED)
            self.set_stable_color(False)
            
            self.stopwatch_start_time = time.time()
            self._update_stopwatch()
            
            self.log("CO₂ started. Dewpoint-cycle active.")
            threading.Thread(target=self._dewpoint_cycle_worker, daemon=True).start()
        else:
            self.log("CO₂ start failed.")

    def stop_co2(self):
        if not self.connected: 
            self.log("CO2 stop failed: Not connected.")
            return
        
        ok = False
        try:
            with self.client_lock:
                ok = write_control_word(self.client, True, False)
        except Exception as e:
            self.log(f"Stop CO2 FAILED: {e}")
            ok = False
            
        if ok:
            self.co2_on = False
            self.abort_cycle = True
            self.btn_start_co2.config(state=tk.NORMAL)
            self.btn_stop_co2.config(state=tk.DISABLED)
            
            self.stopwatch_start_time = None 
            self.var_stopwatch_display.set("00:00")
            
            self._set_param_state(tk.NORMAL)
            self.set_stable_color(False)
            self.log("CO₂ stopped.")

            self._generate_stop_report("CO2 Stopped")
            self._save_all_plots()
        else:
            self.log("CO₂ stop failed.")

    def stop_all(self):
        if self.chiller_on or self.co2_on:
             self._generate_stop_report("System Stop All")
             self._save_all_plots()
        
        if self.connected:
            try:
                with self.client_lock:
                    write_control_word(self.client, False, False)
            except Exception as e:
                self.log(f"Stop All FAILED: {e}")
            
        self.abort_cycle = True
        self.co2_on = False
        self.chiller_on = False
        if self.poller:
            self.poller.stop(); self.poller = None
        if self.ambient_poller:
            self.ambient_poller.stop(); self.ambient_poller = None
        if self.client:
            try: self.client.close()
            except Exception: pass
            self.client = None
        self.connected = False
        update_pollers(None, None)
        self._set_param_state(tk.NORMAL)
        self.btn_start_chiller.config(state=tk.DISABLED)
        self.btn_stop_chiller.config(state=tk.DISABLED)
        self.btn_start_co2.config(state=tk.DISABLED, text="Start CO₂")
        self.btn_stop_co2.config(state=tk.DISABLED)
        self.btn_stop_all.config(state=tk.DISABLED)
        self.gui_update_q.put({"type": "conn_status", "text": "Disconnected", "fg": "red"})
        self.gui_update_q.put({"type": "esp_status", "text": "ESP32: Disconnected", "fg": "red"})
        
        self.stopwatch_start_time = None 
        self.var_stopwatch_display.set("00:00")
        
        if self.health_check_job: 
            self.root.after_cancel(self.health_check_job)
            self.health_check_job = None
        
        self.set_stable_color(False)
        self.log("System stopped & disconnected.")

    # ---------- Dewpoint-cycle worker ----------
    def _dewpoint_cycle_worker(self):
        try:
            max_t = float(self.var_max.get())
            min_t = float(self.var_min.get())
            cycles = int(self.var_cycle.get())
            dwell = int(self.var_dwell.get())
        except Exception as e:
            self.log(f"Invalid parameters: {e}")
            self.gui_update_q.put({"type": "error", "title": "Parameter Error", "message": f"Invalid cycle parameters. Check values.\nError: {e}"})
            return

        if not (max_t > min_t):
            err_msg = f"Max Temp ({max_t}) must be greater than Min Temp ({min_t})."
            self.log(f"Error: {err_msg}")
            self.gui_update_q.put({"type": "error", "title": "Parameter Error", "message": f"{err_msg}\nCycle aborted."})
            return
            
        self.target_temp = max_t 
        cycle_count = 0
        deadband = 0.7 

        self.log(f"Starting direct-cycle logic Max={max_t} Min={min_t}")

        # --- INITIAL DWELL AT MAX TEMP ---
        self.log(f"Starting initial hold at {max_t:.2f}°C")
        self.current_target = max_t
        self.active_setpoint = max_t
        self.var_setpoint_display.set(f"{self.active_setpoint:.2f}")

        try: 
            with self.client_lock:
                write_float(self.client, REGISTER_TEMP_SETPOINT, max_t)
        except Exception as e:
            self.log(f"Initial SP WRITE FAILED: {e}")
            self.root.after(0, self.stop_co2); return
            
        last_log_time = 0
        while not self.abort_cycle and self.co2_on:
            tt06 = self._get_latest_tt06()
            status_msg = ""
            if tt06 is None:
                status_msg = f"Waiting for initial TT06 data... (Target: {max_t:.2f}°C)"
            elif abs(tt06 - max_t) <= deadband:
                self.set_stable_color(True)
                self.log(f"✅ Initial TT06 reached {tt06:.2f}°C. Dwelling for {dwell}s.")
                if self.unified_logger:
                    log_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Event_Type": "DWELL_INIT",
                        "TT06": tt06, "Target_Temp": max_t, "Active_Setpoint": max_t,
                        "Status": f"DWELL_{dwell}s"
                    }
                    self.unified_logger.log(log_data)
                break
            else:
                self.set_stable_color(False)
                status_msg = f"Waiting for initial TT06={tt06:.2f}°C -> {max_t:.2f}°C"
            
            now = time.time()
            if now - last_log_time >= 5.0:
                self.log(status_msg)
                last_log_time = now
            
            if self.abort_cycle or not self.co2_on: 
                self.log("Cycle aborted during initial wait."); return
            time.sleep(1)

        end_dwell = time.time() + dwell
        while time.time() < end_dwell and not self.abort_cycle and self.co2_on:
            time.sleep(1)
        
        if self.abort_cycle or not self.co2_on:
            self.log("Cycle aborted during initial dwell."); return

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
                if self.ambient_poller:
                    latest_ambient = self.ambient_poller.get_latest()
                    dew_max = latest_ambient.get("dew_max")
                    if dew_max is not None:
                        dew_limit = dew_max + 10.0
                    
                    s1 = latest_ambient.get("s1", (None,None,None))
                    s2 = latest_ambient.get("s2", (None,None,None))
                    
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
                    with self.client_lock:
                        ok = write_float(self.client, REGISTER_TEMP_SETPOINT, temporary_target_temp)
                except Exception as e:
                    self.log(f"SP WRITE FAILED: {e}")
                    ok = False

                if not ok:
                    self.log("❌ Failed to write SP, retrying in 10s...")
                    for _ in range(10):
                        if self.abort_cycle or not self.co2_on: break
                        time.sleep(1)
                    continue 

                self.active_setpoint = temporary_target_temp
                self.var_setpoint_display.set(f"{self.active_setpoint:.2f}")
                log_msg = f"WAITING: TT06 must reach {temporary_target_temp:.2f}°C (Logical target: {target_temp:.2f}°C)"
                if log_status != "WAITING":
                    log_msg += f" [{log_status}]"
                self.log(log_msg)
                
                if self.unified_logger:
                    log_data = {
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Event_Type": "LOGIC",
                        "Status": log_status,
                        "TT06": self._get_latest_tt06(),
                        "Target_Temp": target_temp,
                        "Active_Setpoint": temporary_target_temp,
                    }
                    log_data.update(ambient_data) 
                    self.unified_logger.log(log_data)
                
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
                            if self.unified_logger:
                                log_data = {
                                    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "Event_Type": "LOGIC",
                                    "Status": "REACHED",
                                    "TT06": tt06,
                                    "Target_Temp": target_temp,
                                    "Active_Setpoint": temporary_target_temp,
                                }
                                log_data.update(ambient_data)
                                self.unified_logger.log(log_data)
                            
                            target_reached = True
                            break 
                    else:
                        self.set_stable_color(False)
                    
                    time.sleep(1) 

                if target_reached:
                    break 
                
                if self.abort_cycle or not self.co2_on:
                    break 
            
            if self.abort_cycle or not self.co2_on: break

            self.log(f"Cycle reach target side, dwelling {dwell}s")
            if self.unified_logger:
                ambient_data = {}
                if self.ambient_poller:
                    latest_ambient = self.ambient_poller.get_latest()
                    dew_max = latest_ambient.get("dew_max")
                    s1 = latest_ambient.get("s1", (None,None,None))
                    s2 = latest_ambient.get("s2", (None,None,None))
                    
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
                self.unified_logger.log(log_data)
            
            end_dwell = time.time() + dwell
            while time.time() < end_dwell and not self.abort_cycle and self.co2_on:
                time.sleep(1) 

            if self.abort_cycle or not self.co2_on: break

            if not going_down: 
                cycle_count += 1
                self.log(f"--- Cycle {cycle_count}/{cycles} complete ---")

        self.log("✅ CYCLE SEQUENCE FINISHED OR ABORTED")
        
        if not self.abort_cycle and self.co2_on:
            self.log("Cycle finished. Stopping CO2.")
            self.root.after(0, self.stop_co2) 


    def _get_latest_tt06(self):
        if not self.poller:
            return None
            
        with self.poller.lock: 
            arr = self.poller.temp[5]
            if not arr:
                return None 
                
            for v in reversed(arr):
                if v is not None:
                    return v
                    
        return None 

    # ---------- plotting functions ----------
    def open_all_temps_plot(self):
        if not self.poller:
            messagebox.showinfo("Not Connected", "Connect to MARTA first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("All Temperatures vs Time")
        labels = [f"TT0{i+1}" for i in range(6)]
        def animate(_):
            with self.poller.lock:
                t = list(self.poller.timestamps)
                ys = [list(self.poller.temp[i]) for i in range(6)]
            ax.clear()
            if t:
                for lab, y in zip(labels, ys): ax.plot(t, y, label=lab)
                ax.set_ylabel("Temperature (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("All Temps plot opened.")

    def open_ambient_temp_plot(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Ambient Temperatures (S1-S4)")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                t1 = list(self.ambient_poller.s1["temp"])
                t2 = list(self.ambient_poller.s2["temp"])
            ax.clear()
            if t:
                if any(v is not None for v in t1): ax.plot(t, t1, label="S1 (AM2315C)")
                if any(v is not None for v in t2): ax.plot(t, t2, label="S2 (MAX6675)")
                ax.set_ylabel("Temperature (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Ambient Temp plot opened.")

    def open_humidity_plot(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Ambient Humidity (S1, S3, S4)")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                h1 = list(self.ambient_poller.s1["hum"])
                # S2 is Thermocouple (No Hum)
            ax.clear()
            if t:
                if any(v is not None for v in h1): ax.plot(t, h1, label="S1 (AM2315C)")
                ax.set_ylabel("Humidity (%)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Humidity plot opened.")

    def open_dew_point_plot(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Ambient Dew Point (S1, S3, S4)")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                d1 = list(self.ambient_poller.s1["dew"])
                # S2 is Thermocouple (No Dew)
            ax.clear()
            if t:
                if any(v is not None for v in d1): ax.plot(t, d1, label="S1 (AM2315C)")
                ax.set_ylabel("Dew Point (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Dew Point plot opened.")

    def open_cycle_plot(self):
        if not self.poller:
            messagebox.showinfo("Not Connected", "Connect to MARTA first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Cycle Plot TT06 vs Setpoints")
        
        def animate(_):
            with self.poller.lock:
                t = list(self.poller.timestamps)
                tt06 = list(self.poller.temp[5])
                active_sp = list(self.poller.active_sp_history)
                current_tgt = list(self.poller.current_target_history)
            ax.clear()
            if t:
                if any(v is not None for v in tt06): 
                    ax.plot(t, tt06, label="TT06 (°C)", color="blue", linewidth=2)
                if any(v is not None for v in current_tgt): 
                    ax.plot(t, current_tgt, label="Target Temp", color="red", linestyle="--", drawstyle="steps-post")
                if any(v is not None for v in active_sp): 
                    ax.plot(t, active_sp, label="Active Setpoint", color="green", linestyle=":", drawstyle="steps-post")

                ax.set_ylabel("Temperature (°C)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Cycle plot opened.")

    def open_unified_plot(self):
        fig, ax1 = plt.subplots(figsize=(10, 8))
        fig.canvas.manager.set_window_title("Unified System Monitor")
        
        # Create second Y-axis for Humidity
        ax2 = ax1.twinx()

        def animate(_):
            # Data Containers
            t_marta, tt06, tt05, active_sp, current_tgt = [], [], [], [], []
            t_amb, s1_t, s1_h, s1_d, s2_t = [], [], [], [], []
            
            # Fetch MARTA Data
            if self.poller:
                with self.poller.lock:
                    t_marta = list(self.poller.timestamps)
                    tt06 = list(self.poller.temp[5])
                    tt05 = list(self.poller.temp[4])
                    active_sp = list(self.poller.active_sp_history)
                    current_tgt = list(self.poller.current_target_history)
            
            # Fetch Ambient Data
            if self.ambient_poller:
                with self.ambient_poller.lock:
                    t_amb = list(self.ambient_poller.timestamps)
                    s1_t = list(self.ambient_poller.s1["temp"])
                    s1_h = list(self.ambient_poller.s1["hum"])
                    s1_d = list(self.ambient_poller.s1["dew"])
                    s2_t = list(self.ambient_poller.s2["temp"])

            # --- Plot 1: Temperatures (Left Y-Axis) ---
            ax1.clear()
            ax2.clear() # Clear ax2 as well to prevent overplotting

            # Re-setup axes labels after clear
            ax1.set_ylabel("Temperature (°C)", color="blue")
            ax1.set_xlabel("Time")
            ax1.tick_params(axis='y', labelcolor="blue")
            
            ax2.set_ylabel("Humidity (RH%)", color="purple")
            ax2.tick_params(axis='y', labelcolor="purple")
            
            # Plot Temperatures on ax1
            if t_marta:
                if any(v is not None for v in tt06): ax1.plot(t_marta, tt06, label="TT06 (Contact)", color="blue", linewidth=2)
                if any(v is not None for v in tt05): ax1.plot(t_marta, tt05, label="TT05 (Air)", color="cyan", linewidth=1)
                if any(v is not None for v in active_sp): ax1.plot(t_marta, active_sp, label="Setpoint", color="green", linestyle=":")
                if any(v is not None for v in current_tgt): ax1.plot(t_marta, current_tgt, label="Target", color="red", linestyle="--")
            
            if t_amb:
                if any(v is not None for v in s1_t): ax1.plot(t_amb, s1_t, label="Amb S1 Temp", color="orange", alpha=0.7)
                if any(v is not None for v in s2_t): ax1.plot(t_amb, s2_t, label="Amb S2 Temp", color="brown", alpha=0.7)
                if any(v is not None for v in s1_d): ax1.plot(t_amb, s1_d, label="Dew Point (S1)", color="navy", linewidth=2, linestyle="-.")

            # Limits
            try:
                mx = float(self.var_max.get())
                mn = float(self.var_min.get())
                ax1.axhline(y=mx, color='r', linestyle='-', alpha=0.3)
                ax1.axhline(y=mn, color='b', linestyle='-', alpha=0.3)
            except: pass

            # --- Plot 2: Humidity (Right Y-Axis) ---
            if t_amb and any(v is not None for v in s1_h):
                ax2.plot(t_amb, s1_h, label="S1 Humidity", color="purple", linestyle="-")
            
            # Combine Legends
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize='small', ncol=2)
            
            ax1.grid(True)
            fig.autofmt_xdate()

        ani = animation.FuncAnimation(fig, animate, interval=5000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Unified plot opened.")

    def open_contact_point(self):
        if not self.ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        fig, ax = plt.subplots(); fig.canvas.manager.set_window_title("Contact Point (S2) Temp")
        def animate(_):
            with self.ambient_poller.lock:
                t = list(self.ambient_poller.timestamps)
                t2 = list(self.ambient_poller.s2["temp"])
            ax.clear()
            if t:
                if any(v is not None for v in t2): ax.plot(t, t2, label="S2 (Contact Point)", color="orange")
                ax.set_ylabel("Temperature (°C)"); ax.set_xlabel("Time"); ax.legend(); ax.grid(True); fig.autofmt_xdate()
            else:
                ax.text(0.5,0.5,"NO DATA",ha="center",va="center",fontsize=16,transform=ax.transAxes)
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani); plt.show(block=False); self.log("Contact Point (S2) plot opened.")

    # --- Connection Health Check ---
    def _check_connection_health(self):
        if self.connected and self.poller and self.poller.is_alive():
            elapsed = time.time() - self.poller.last_successful_read_time
            
            tolerance = (self.poller.interval * 2.5) 
            
            if elapsed > tolerance:
                if self.lab_conn.cget("text") != "POLLING FAILED":
                    self.log("POLLER HEARTBEAT FAILED. Updating status label.")
                    self.gui_update_q.put({"type": "conn_status", "text": "POLLING FAILED", "fg": "red"})
            else:
                if self.lab_conn.cget("text") != "Connected":
                    self.log("Poller heartbeat recovered.")
                    self.gui_update_q.put({"type": "conn_status", "text": "Connected", "fg": "green"})
        
        elif not self.connected:
            if self.lab_conn.cget("text") != "Disconnected":
                self.gui_update_q.put({"type": "conn_status", "text": "Disconnected", "fg": "red"})

        self.health_check_job = self.root.after(5000, self._check_connection_health) 

    def _on_close(self):
        self.stop_all()
        self.root.destroy()
