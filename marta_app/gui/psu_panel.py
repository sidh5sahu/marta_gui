import tkinter as tk
from tkinter import ttk
import socket
import json
import threading
import time
from collections import deque
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

class PSUPanel(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        
        self.history_len = 60
        self.times = deque(maxlen=self.history_len)
        self.vmon_data = {
            '1': {str(c): deque(maxlen=self.history_len) for c in range(8)},
            '3': {str(c): deque(maxlen=self.history_len) for c in range(8)},
            '5': {str(c): deque(maxlen=self.history_len) for c in range(12)}
        }
        self.start_time = time.time()
        
        self._setup_ui()
        
        self.running = True
        self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.poll_thread.start()

    def _setup_ui(self):
        left_pane = ttk.Frame(self)
        left_pane.pack(side="left", fill="y", padx=5, pady=5)
        
        ttk.Label(left_pane, text="CAEN Power Supply Channels", font=("Arial", 12, "bold")).pack(pady=5)
        
        columns = ("Slot", "Channel", "V0Set", "VMon", "IMon", "Status")
        self.tree = ttk.Treeview(left_pane, columns=columns, show="headings", height=28)
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=70, anchor="center")
        self.tree.pack(fill="y", expand=True)
        
        self.tree.tag_configure('stable', background='lightgreen')
        self.tree.tag_configure('ramping', background='yellow')
        self.tree.tag_configure('alarm', background='salmon')
        self.tree.tag_configure('off', background='lightgray')
        
        self.rows = {}
        for slot, max_ch in [('1', 8), ('3', 8), ('5', 12)]:
            for ch in range(max_ch):
                item = self.tree.insert("", "end", values=(slot, ch, "-", "-", "-", "-"))
                self.rows[f"{slot}_{ch}"] = item
                
        right_pane = ttk.Frame(self)
        right_pane.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        self.fig, self.ax = plt.subplots(figsize=(6, 5))
        self.canvas = FigureCanvasTkAgg(self.fig, master=right_pane)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
    def _poll_loop(self):
        while self.running:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(("127.0.0.1", 5555))
                    cmd = {"command": "get_status"}
                    s.sendall((json.dumps(cmd) + "\n").encode('utf-8'))
                    
                    data = b""
                    while b"\n" not in data:
                        chunk = s.recv(4096)
                        if not chunk: break
                        data += chunk
                        
                    if data:
                        response = json.loads(data.decode('utf-8').strip())
                        if response.get("status") == "ok":
                            telemetry = response.get("telemetry", {})
                            self.after(0, self._update_data, telemetry)
            except Exception:
                pass
            time.sleep(1.0)
            
    def _update_data(self, telemetry):
        current_time = time.time() - self.start_time
        self.times.append(current_time)
        
        for slot, channels in telemetry.items():
            for ch, data in channels.items():
                vset = data.get("V0Set", 0)
                vmon = data.get("VMon", 0)
                imon = data.get("IMon", 0)
                status = data.get("Status", "Off")
                
                row_id = self.rows.get(f"{slot}_{ch}")
                if row_id:
                    self.tree.item(row_id, values=(slot, ch, f"{vset:.2f}", f"{vmon:.2f}", f"{imon:.2f}", status))
                    
                    tag = 'stable'
                    sl = status.lower()
                    if sl == "ramping":
                        tag = 'ramping'
                    elif sl == "alarm":
                        tag = 'alarm'
                    elif sl == "off":
                        tag = 'off'
                    self.tree.item(row_id, tags=(tag,))
                    
                if slot in self.vmon_data and ch in self.vmon_data[slot]:
                    self.vmon_data[slot][ch].append(vmon)
                    
        self.ax.clear()
        self.ax.set_title("Live Voltage (VMon)")
        self.ax.set_xlabel("Time (s)")
        self.ax.set_ylabel("Voltage (V)")
        
        if len(self.times) > 0:
            for slot, channels in self.vmon_data.items():
                for ch, v_hist in channels.items():
                    if len(v_hist) == len(self.times):
                        if ch == '0':
                            self.ax.plot(self.times, v_hist, label=f"Slot {slot} Ch {ch}")
                        else:
                            self.ax.plot(self.times, v_hist, alpha=0.2)
                            
            self.ax.legend(loc="upper left")
        self.canvas.draw()
        
    def destroy(self):
        self.running = False
        super().destroy()
