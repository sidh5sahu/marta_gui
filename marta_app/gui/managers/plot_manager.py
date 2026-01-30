"""
Plot management for MARTA GUI.

Handles creation and management of real-time plots and saving plots to files.
"""

import os
import re
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from tkinter import messagebox


class PlotManager:
    """Manages all plotting functionality for MARTA GUI."""
    
    def __init__(self, poller_getter, ambient_poller_getter, param_getters, log_callback):
        """
        Initialize PlotManager.
        
        Args:
            poller_getter: Function that returns the current DataPoller instance
            ambient_poller_getter: Function that returns the current AmbientPoller instance
            param_getters: Dict with keys 'var_max', 'var_min' - functions to get parameter values
            log_callback: Function to call for logging messages
        """
        self.get_poller = poller_getter
        self.get_ambient_poller = ambient_poller_getter
        self.param_getters = param_getters
        self.log = log_callback
        self.animations = []
    
    def open_all_temps_plot(self):
        """Open real-time plot of all MARTA temperatures (TT01-TT06)."""
        poller = self.get_poller()
        if not poller:
            messagebox.showinfo("Not Connected", "Connect to MARTA first.")
            return
        
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title("All Temperatures vs Time")
        labels = [f"TT0{i+1}" for i in range(6)]
        
        def animate(_):
            with poller.lock:
                t = list(poller.timestamps)
                ys = [list(poller.temp[i]) for i in range(6)]
            ax.clear()
            if t:
                for lab, y in zip(labels, ys):
                    ax.plot(t, y, label=lab)
                ax.set_ylabel("Temperature (°C)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("All Temps plot opened.")
    
    def open_ambient_temp_plot(self):
        """Open real-time plot of ambient temperatures (S1, S2)."""
        ambient_poller = self.get_ambient_poller()
        if not ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title("Ambient Temperatures (S1-S4)")
        
        def animate(_):
            with ambient_poller.lock:
                t = list(ambient_poller.timestamps)
                t1 = list(ambient_poller.s1["temp"])
                t2 = list(ambient_poller.s2["temp"])
            ax.clear()
            if t:
                if any(v is not None for v in t1):
                    ax.plot(t, t1, label="S1 (AM2315C)")
                if any(v is not None for v in t2):
                    ax.plot(t, t2, label="S2 (MAX6675)")
                ax.set_ylabel("Temperature (°C)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Ambient Temp plot opened.")
    
    def open_humidity_plot(self):
        """Open real-time plot of humidity (S1)."""
        ambient_poller = self.get_ambient_poller()
        if not ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title("Ambient Humidity (S1, S3, S4)")
        
        def animate(_):
            with ambient_poller.lock:
                t = list(ambient_poller.timestamps)
                h1 = list(ambient_poller.s1["hum"])
            ax.clear()
            if t:
                if any(v is not None for v in h1):
                    ax.plot(t, h1, label="S1 (AM2315C)")
                ax.set_ylabel("Humidity (%)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Humidity plot opened.")
    
    def open_dew_point_plot(self):
        """Open real-time plot of dew point (S1)."""
        ambient_poller = self.get_ambient_poller()
        if not ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title("Ambient Dew Point (S1, S3, S4)")
        
        def animate(_):
            with ambient_poller.lock:
                t = list(ambient_poller.timestamps)
                d1 = list(ambient_poller.s1["dew"])
            ax.clear()
            if t:
                if any(v is not None for v in d1):
                    ax.plot(t, d1, label="S1 (AM2315C)")
                ax.set_ylabel("Dew Point (°C)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Dew Point plot opened.")
    
    def open_cycle_plot(self):
        """Open real-time plot of TT06 vs setpoints."""
        poller = self.get_poller()
        if not poller:
            messagebox.showinfo("Not Connected", "Connect to MARTA first.")
            return
        
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title("Cycle Plot TT06 vs Setpoints")
        
        def animate(_):
            with poller.lock:
                t = list(poller.timestamps)
                tt06 = list(poller.temp[5])
                active_sp = list(poller.active_sp_history)
                current_tgt = list(poller.current_target_history)
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
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Cycle plot opened.")
    
    def open_unified_plot(self):
        """Open unified plot showing MARTA temps, ambient temps, humidity, and setpoints."""
        fig, ax1 = plt.subplots(figsize=(10, 8))
        fig.canvas.manager.set_window_title("Unified System Monitor")
        
        # Create second Y-axis for Humidity
        ax2 = ax1.twinx()
        
        poller = self.get_poller()
        ambient_poller = self.get_ambient_poller()
        
        def animate(_):
            # Data Containers
            t_marta, tt06, tt05, active_sp, current_tgt = [], [], [], [], []
            t_amb, s1_t, s1_h, s1_d, s2_t = [], [], [], [], []
            
            # Fetch MARTA Data
            if poller:
                with poller.lock:
                    t_marta = list(poller.timestamps)
                    tt06 = list(poller.temp[5])
                    tt05 = list(poller.temp[4])
                    active_sp = list(poller.active_sp_history)
                    current_tgt = list(poller.current_target_history)
            
            # Fetch Ambient Data
            if ambient_poller:
                with ambient_poller.lock:
                    t_amb = list(ambient_poller.timestamps)
                    s1_t = list(ambient_poller.s1["temp"])
                    s1_h = list(ambient_poller.s1["hum"])
                    s1_d = list(ambient_poller.s1["dew"])
                    s2_t = list(ambient_poller.s2["temp"])
            
            # --- Plot 1: Temperatures (Left Y-Axis) ---
            ax1.clear()
            ax2.clear()  # Clear ax2 as well to prevent overplotting
            
            # Re-setup axes labels after clear
            ax1.set_ylabel("Temperature (°C)", color="blue")
            ax1.set_xlabel("Time")
            ax1.tick_params(axis='y', labelcolor="blue")
            
            ax2.set_ylabel("Humidity (RH%)", color="purple")
            ax2.tick_params(axis='y', labelcolor="purple")
            
            # Plot Temperatures on ax1
            if t_marta:
                if any(v is not None for v in tt06):
                    ax1.plot(t_marta, tt06, label="TT06 (Contact)", color="blue", linewidth=2)
                if any(v is not None for v in tt05):
                    ax1.plot(t_marta, tt05, label="TT05 (Air)", color="cyan", linewidth=1)
                if any(v is not None for v in active_sp):
                    ax1.plot(t_marta, active_sp, label="Setpoint", color="green", linestyle=":")
                if any(v is not None for v in current_tgt):
                    ax1.plot(t_marta, current_tgt, label="Target", color="red", linestyle="--")
            
            if t_amb:
                if any(v is not None for v in s1_t):
                    ax1.plot(t_amb, s1_t, label="Amb S1 Temp", color="orange", alpha=0.7)
                if any(v is not None for v in s2_t):
                    ax1.plot(t_amb, s2_t, label="Amb S2 Temp", color="brown", alpha=0.7)
                if any(v is not None for v in s1_d):
                    ax1.plot(t_amb, s1_d, label="Dew Point (S1)", color="navy", linewidth=2, linestyle="-.")
            
            # Limits
            try:
                mx = float(self.param_getters['var_max']())
                mn = float(self.param_getters['var_min']())
                ax1.axhline(y=mx, color='r', linestyle='-', alpha=0.3)
                ax1.axhline(y=mn, color='b', linestyle='-', alpha=0.3)
            except:
                pass
            
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
        """Open real-time plot of contact point temperature (S2)."""
        ambient_poller = self.get_ambient_poller()
        if not ambient_poller:
            messagebox.showinfo("Not Connected", "Connect to ESP32 first.")
            return
        
        fig, ax = plt.subplots()
        fig.canvas.manager.set_window_title("Contact Point (S2) Temp")
        
        def animate(_):
            with ambient_poller.lock:
                t = list(ambient_poller.timestamps)
                t2 = list(ambient_poller.s2["temp"])
            ax.clear()
            if t:
                if any(v is not None for v in t2):
                    ax.plot(t, t2, label="S2 (Contact Point)", color="orange")
                ax.set_ylabel("Temperature (°C)")
                ax.set_xlabel("Time")
                ax.legend()
                ax.grid(True)
                fig.autofmt_xdate()
            else:
                ax.text(0.5, 0.5, "NO DATA", ha="center", va="center", fontsize=16, transform=ax.transAxes)
        
        ani = animation.FuncAnimation(fig, animate, interval=10000)
        self.animations.append(ani)
        plt.show(block=False)
        self.log("Contact Point (S2) plot opened.")
    
    def save_all_plots(self, run_dir):
        """
        Save all plots to JPEG files in the run directory.
        
        Args:
            run_dir: Directory to save plots to
        
        Returns:
            Number of plots saved
        """
        if not run_dir:
            self.log("Cannot save plots: No run directory set.")
            return 0
        
        plots_saved = 0
        
        # Save open animated plots if any
        if self.animations:
            self.log(f"Saving {len(self.animations)} open plot windows...")
            for ani in self.animations:
                try:
                    fig = ani.fig if hasattr(ani, 'fig') else ani._fig
                    title = fig.canvas.manager.get_window_title()
                    safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", title)
                    save_path = os.path.join(run_dir, f"{safe_title}.jpg")
                    fig.savefig(save_path, dpi=150, bbox_inches='tight')
                    plots_saved += 1
                except Exception as e:
                    self.log(f"Error saving plot: {e}")
        
        # Generate static plots from poller data (even if no windows open)
        try:
            poller = self.get_poller()
            ambient_poller = self.get_ambient_poller()
            
            # Plot 1: MARTA Temperatures (if data available)
            if poller and hasattr(poller, 'timestamps') and len(poller.timestamps) > 0:
                with poller.lock:
                    t = list(poller.timestamps)
                    temps = [list(poller.temp[i]) for i in range(min(6, len(poller.temp)))]
                
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
                    save_path = os.path.join(run_dir, "marta_temperatures.jpg")
                    fig.savefig(save_path, dpi=150, bbox_inches='tight')
                    plt.close(fig)
                    plots_saved += 1
                    self.log(f"Saved: marta_temperatures.jpg")
            
            # Plot 2: Ambient Data (if ESP32 connected)
            if ambient_poller and hasattr(ambient_poller, 'timestamps') and len(ambient_poller.timestamps) > 0:
                with ambient_poller.lock:
                    t = list(ambient_poller.timestamps)
                    s1_t = list(ambient_poller.s1["temp"])
                    s1_h = list(ambient_poller.s1["hum"])
                    s1_d = list(ambient_poller.s1["dew"])
                    s2_t = list(ambient_poller.s2["temp"])
                
                if t:
                    # Ambient Temperature Plot
                    fig, ax = plt.subplots(figsize=(12, 6))
                    if s1_t:
                        ax.plot(t, s1_t, label="S1 Temp", color='blue')
                    if s2_t:
                        ax.plot(t, s2_t, label="S2 Temp", color='orange')
                    ax.set_ylabel("Temperature (°C)")
                    ax.set_xlabel("Time")
                    ax.set_title("Ambient Temperatures")
                    ax.legend()
                    ax.grid(True)
                    fig.autofmt_xdate()
                    save_path = os.path.join(run_dir, "ambient_temperature.jpg")
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
                        save_path = os.path.join(run_dir, "ambient_humidity.jpg")
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
                        save_path = os.path.join(run_dir, "dew_point.jpg")
                        fig.savefig(save_path, dpi=150, bbox_inches='tight')
                        plt.close(fig)
                        plots_saved += 1
                        self.log(f"Saved: dew_point.jpg")
        
        except Exception as e:
            self.log(f"Error generating plots: {e}")
        
        if plots_saved > 0:
            self.log(f"Total {plots_saved} plots saved to {run_dir}")
        else:
            self.log("No data available to generate plots.")
        
        return plots_saved
