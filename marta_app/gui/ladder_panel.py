import tkinter as tk
from tkinter import ttk
import threading

class LadderPanel(ttk.Frame):
    def __init__(self, parent, ladder_manager, log_callback):
        super().__init__(parent)
        self.ladder_manager = ladder_manager
        self.log = log_callback
        
        self.module_vars = []
        
        # Configuration Frame
        config_frame = ttk.LabelFrame(self, text="Ladder Configuration")
        config_frame.pack(fill="x", padx=10, pady=10)
        
        # 12 Entry fields
        for i in range(12):
            row = i // 4
            col = (i % 4) * 2
            ttk.Label(config_frame, text=f"Module {i+1}:").grid(row=row, column=col, padx=5, pady=5, sticky="e")
            var = tk.StringVar(value=f"Module_{i+1}")
            self.module_vars.append(var)
            ttk.Entry(config_frame, textvariable=var, width=15).grid(row=row, column=col+1, padx=5, pady=5)
        
        # Test Type
        options_frame = ttk.Frame(config_frame)
        options_frame.grid(row=3, column=0, columnspan=8, pady=10)
        
        ttk.Label(options_frame, text="Test Type:").pack(side="left", padx=5)
        self.test_type_var = tk.StringVar(value="quick")
        ttk.Radiobutton(options_frame, text="Quick", variable=self.test_type_var, value="quick").pack(side="left", padx=5)
        ttk.Radiobutton(options_frame, text="Full", variable=self.test_type_var, value="full").pack(side="left", padx=5)
        
        # Start Button
        self.start_btn = ttk.Button(options_frame, text="Start Ladder Test", command=self.start_test)
        self.start_btn.pack(side="left", padx=20)
        
        # Status Frame
        status_frame = ttk.LabelFrame(self, text="Test Progress")
        status_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        self.progress_lbl = ttk.Label(status_frame, text="Ready", font=("Arial", 12, "bold"))
        self.progress_lbl.pack(pady=10)
        
        self.log_text = tk.Text(status_frame, height=15, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=5, pady=5)
        
    def log_msg(self, msg):
        self.log_text.config(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self.log(msg)
        
    def update_progress(self, msg):
        self.progress_lbl.config(text=msg)
        self.log_msg(msg)
        
    def start_test(self):
        # Disable button
        self.start_btn.config(state="disabled")
        
        # Update names
        names = [var.get() for var in self.module_vars]
        self.ladder_manager.set_module_names(names)
        self.ladder_manager.set_test_type(self.test_type_var.get())
        
        self.log_msg(f"Starting {self.test_type_var.get()} test for 12 modules...")
        
        # Run in thread
        threading.Thread(target=self._test_thread, daemon=True).start()
        
    def _test_thread(self):
        def _cb(msg):
            # Safely schedule GUI update
            self.after(0, lambda: self.update_progress(msg))
            
        # Run
        self.ladder_manager.run_ladder_tests(progress_callback=_cb)
        
        # Re-enable button
        self.after(0, lambda: self.start_btn.config(state="normal"))
