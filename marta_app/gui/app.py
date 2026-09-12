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

# Import manager modules
from .managers.report_manager import ReportManager
from .managers.plot_manager import PlotManager
from .managers.connection_manager import ConnectionManager
from .managers.controller import MartaController
from .managers.ladder_manager import LadderManager
from .ladder_panel import LadderPanel
from .psu_panel import PSUPanel

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
        
        # Initialize Managers (early, before GUI setup)
        self.report_mgr = ReportManager(log_callback=self.log)
        self.connection_mgr = ConnectionManager(
            config=self.config,
            gui_update_q=self.gui_update_q,
            log_callback=self.log,
            web_update_callback=update_pollers
        )
        self.plot_mgr = PlotManager(
            poller_getter=lambda: self.connection_mgr.get_poller(),
            ambient_poller_getter=lambda: self.connection_mgr.get_ambient_poller(),
            param_getters={
                'var_max': lambda: self.var_max.get() if hasattr(self, 'var_max') else '15',
                'var_min': lambda: self.var_min.get() if hasattr(self, 'var_min') else '10'
            },
            log_callback=self.log
        )
        self.ladder_mgr = LadderManager(self.report_mgr)
        self.controller = MartaController(
            connection_mgr=self.connection_mgr,
            gui_update_q=self.gui_update_q,
            log_callback=self.log,
            report_mgr=self.report_mgr,
            plot_mgr=self.plot_mgr,
            ladder_mgr=self.ladder_mgr
        )
        
        # Keep client_lock for backward compatibility
        self.client_lock = self.connection_mgr.client_lock

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
        self.tab_ladder = LadderPanel(self.notebook, self.ladder_mgr, self.log)
        self.tab_psu = PSUPanel(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_main, text="Controller")
        self.notebook.add(self.tab_marta, text="Marta")
        self.notebook.add(self.tab_ladder, text="Ladder Test")
        self.notebook.add(self.tab_psu, text="Power Supply")
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

        #  Runtime state (most moved to managers, keep only GUI-specific state)
        # Note: self.client_lock already set above from connection_mgr
        
        # Run Management State (will be set by connect())
        self.log_file_path = None 
        self.current_run_name_full = None
        self.current_run_name_short = None 
        self.current_run_dir = None 
        self.report_file_path = None 
        
        # Health check job ID
        self.health_check_job = None
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
                elif msg_type == "setpoint_display":
                    self.var_setpoint_display.set(msg["value"])
                elif msg_type == "stop_co2":
                    self.root.after(0, self.stop_co2)
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

        success = self.connection_mgr.connect_marta(
            run_dir=self.current_run_dir,
            run_name_short=self.current_run_name_short,
            get_active_sp_func=self.controller.get_active_setpoint,
            get_current_target_func=self.controller.get_current_target,
            enable_buttons_callback=self._enable_control_buttons
        )
        
        if success:
            # Set up log and report paths
            self.log_file_path = self.connection_mgr.log_file_path
            self.report_file_path = os.path.join(self.current_run_dir, "report.md")
            
            # Set up report manager
            self.report_mgr.set_run_info(
                self.current_run_dir,
                self.current_run_name_full,
                self.report_file_path
            )
            
            # Start parameter updates
            self.connection_mgr.update_param_display(
                self.param_vars, self.alarm_vars, self.alarm_actions,
                self.var_tt06_display, self.var_status_int, self.var_control_word,
                self.var_active_actions, self.root
            )
            
            # Start health check
            self.connection_mgr.check_health(self.lab_conn, self.root)

    # ---------- Connect ESP32 ----------
    def connect_esp32(self):
        if self.connection_mgr.connect_esp32():
            self.connection_mgr.update_ambient_display(
                self.var_s1, self.var_s2, self.var_dewavg, self.root
            ) 

    # ---------- Network Diagnostics ----------
    def test_network_connection(self):
        self.connection_mgr.test_network() 

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
        self.controller.update_pump(self.var_pump.get(), self.client_lock)

    def get_active_setpoint(self):
        return self.controller.get_active_setpoint()
    
    def get_current_target(self):
        return self.controller.get_current_target()
    
    def set_stable_color(self, is_stable):
        """Update stability indicator."""
        self.controller.set_stable_color(is_stable)
    
    def _update_stopwatch(self):
        """Update stopwatch display."""
        if self.controller.stopwatch_start_time is None:
            return
        
        elapsed_sec = int(time.time() - self.controller.stopwatch_start_time)
        elapsed_min = elapsed_sec // 60
        elapsed_sec_mod = elapsed_sec % 60
        self.var_stopwatch_display.set(f"{elapsed_min:02d}:{elapsed_sec_mod:02d}")
        
        self.root.after(1000, self._update_stopwatch)

    def _set_param_state(self, state):
        """Enable or disable parameter entries."""
        for e, b in getattr(self, "param_entries", []):
            e.config(state=state)
            b.config(state=state)

    # ---------- Chiller / CO2 controls ----------
    def start_chiller(self):
        self.controller.start_chiller(
            self.client_lock,
            self._update_button_states
        )

    def stop_chiller(self):
        self.controller.stop_chiller(
            self.client_lock,
            self._update_button_states,
            self._reset_stopwatch,
            self._set_param_state
        )

    def start_co2(self):
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
        )

    def stop_co2(self):
        self.controller.stop_co2(
            self.client_lock,
            self._update_button_states,
            self._reset_stopwatch,
            self._set_param_state
        )

    def stop_all(self):
        self.controller.stop_all(
            self.client_lock,
            self._update_button_states,
            self._reset_stopwatch,
            self._set_param_state,
            self._cancel_health_check
        )

    # ---------- Dewpoint-cycle worker ----------

    # ---------- plotting functions ----------
    def open_all_temps_plot(self):
        self.plot_mgr.open_all_temps_plot()

    def open_ambient_temp_plot(self):
        self.plot_mgr.open_ambient_temp_plot()

    def open_humidity_plot(self):
        self.plot_mgr.open_humidity_plot()

    def open_dew_point_plot(self):
        self.plot_mgr.open_dew_point_plot()

    def open_cycle_plot(self):
        self.plot_mgr.open_cycle_plot()

    def open_unified_plot(self):
        self.plot_mgr.open_unified_plot()

    def open_contact_point(self):
        self.plot_mgr.open_contact_point()


    # --- Helper Methods for Manager Callbacks ---
    def _enable_control_buttons(self):
        """Enable control buttons after MARTA connection."""
        self.btn_start_chiller.config(state=tk.NORMAL)
        self.btn_stop_all.config(state=tk.NORMAL)
    
    def _update_button_states(self, event):
        """Update button states based on controller state."""
        if event == 'chiller_started':
            self.btn_start_chiller.config(state=tk.DISABLED)
            self.btn_stop_chiller.config(state=tk.NORMAL)
        elif event == 'chiller_stopped':
            self.btn_start_chiller.config(state=tk.NORMAL)
            self.btn_stop_chiller.config(state=tk.DISABLED)
            self.btn_start_co2.config(state=tk.DISABLED, text="Start CO₂")
            self.btn_stop_co2.config(state=tk.DISABLED)
        elif event == 'co2_started':
            self.btn_start_co2.config(state=tk.DISABLED)
            self.btn_stop_co2.config(state=tk.NORMAL)
        elif event == 'co2_stopped':
            self.btn_start_co2.config(state=tk.NORMAL)
            self.btn_stop_co2.config(state=tk.DISABLED)
        elif event == 'all_stopped':
            self.btn_start_chiller.config(state=tk.DISABLED)
            self.btn_stop_chiller.config(state=tk.DISABLED)
            self.btn_start_co2.config(state=tk.DISABLED, text="Start CO₂")
            self.btn_stop_co2.config(state=tk.DISABLED)
            self.btn_stop_all.config(state=tk.DISABLED)
    
    def _reset_stopwatch(self):
        """Reset stopwatch display."""
        self.var_stopwatch_display.set("00:00")
    
    def _cancel_health_check(self):
        """Cancel health check timer."""
        if self.connection_mgr.health_check_job:
            self.root.after_cancel(self.connection_mgr.health_check_job)
            self.connection_mgr.health_check_job = None

    def _on_close(self):
        self.stop_all()
        self.root.destroy()
