"""
Report generation manager for MARTA GUI.

Handles creation and management of run reports in Markdown format.
"""

from datetime import datetime


class ReportManager:
    """Manages generation of run reports."""
    
    def __init__(self, log_callback):
        """
        Initialize ReportManager.
        
        Args:
            log_callback: Function to call for logging messages
        """
        self.log = log_callback
        self.report_file_path = None
        self.current_run_dir = None
        self.current_run_name_full = None
    
    def set_run_info(self, run_dir, run_name_full, report_path):
        """
        Set information for the current run.
        
        Args:
            run_dir: Directory path for the current run
            run_name_full: Full name of the current run
            report_path: Path to the report file
        """
        self.current_run_dir = run_dir
        self.current_run_name_full = run_name_full
        self.report_file_path = report_path
    
    def generate_start_report(self, params):
        """
        Generate start report with run parameters.
        
        Args:
            params: Dict with keys: max_temp, min_temp, cycles, dwell_s, pump_rpm
        """
        self.log("Generating start report...")
        
        report_content = f"# MARTA Run Report: {self.current_run_name_full}\\n\\n"
        report_content += "## Starting Parameters\\n"
        report_content += f"- **Start Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n"
        report_content += f"- **Max Temp (°C):** {params.get('max_temp', '--')}\\n"
        report_content += f"- **Min Temp (°C):** {params.get('min_temp', '--')}\\n"
        report_content += f"- **# Cycles:** {params.get('cycles', '--')}\\n"
        report_content += f"- **Dwell (s):** {params.get('dwell_s', '--')}\\n"
        report_content += f"- **Pump RPM:** {params.get('pump_rpm', '--')}\\n\\n"
        
        self._write_to_report(report_content, mode="w")
    
    def generate_stop_report(self, stop_reason, final_tt06):
        """
        Generate stop report.
        
        Args:
            stop_reason: Reason for stopping (string)
            final_tt06: Final TT06 temperature reading
        """
        self.log("Generating stop report...")
        
        report_content = "\\n## Run Stopped\\n"
        report_content += f"- **Stop Reason:** {stop_reason}\\n"
        report_content += f"- **Stop Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\\n"
        report_content += f"- **Final TT06:** {final_tt06}\\n"
        
        self._write_to_report(report_content, mode="a")
    
    def _write_to_report(self, text, mode="a"):
        """
        Write text to report file.
        
        Args:
            text: Text to write
            mode: File open mode ('w' for write, 'a' for append)
        """
        if not self.report_file_path:
            self.log("Error: Report file path is not set.")
            return
        
        try:
            with open(self.report_file_path, mode, encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            self.log(f"Error writing to report: {e}")
