import os
import subprocess
import json
import logging

class LadderManager:
    """Manages the configuration and sequential testing of 12 ladder modules."""
    
    def __init__(self, report_mgr):
        self.report_mgr = report_mgr
        # Initialize default names for 12 modules
        self.modules = [f"Module_{i+1}" for i in range(12)]
        self.test_type = "quick" # Options: 'quick', 'full'
        self.logger = logging.getLogger("LadderManager")

    def set_module_names(self, names):
        """Configure the list of module names."""
        if len(names) == 12:
            self.modules = names
        else:
            self.logger.warning("Expected exactly 12 module names.")

    def set_test_type(self, test_type):
        """Set the test type ('quick' or 'full')."""
        if test_type in ['quick', 'full']:
            self.test_type = test_type

    def run_ladder_tests(self, ph2acf_bin_path="./ph2acf/build/ladder_test", progress_callback=None):
        """Run the IV and Quick/Full tests sequentially for all modules."""
        if not self.report_mgr.current_run_dir:
            msg = "Error: Run directory not established. Please Connect MARTA and start run first."
            self.logger.error(msg)
            if progress_callback:
                progress_callback(msg)
            return False

        # Create a run-wise folder for the ladder test results
        ladder_dir = os.path.join(self.report_mgr.current_run_dir, "ladder_results")
        os.makedirs(ladder_dir, exist_ok=True)

        self.logger.info(f"Starting ladder tests. Results will be saved to: {ladder_dir}")
        results = {}

        for idx, mod_name in enumerate(self.modules):
            if not mod_name or not mod_name.strip():
                continue
                
            msg = f"Testing Module {idx+1}/{len(self.modules)}: {mod_name}..."
            self.logger.info(msg)
            if progress_callback:
                progress_callback(msg)
            
            # Execute the Ph2_ACF ladder_test workflow
            try:
                cmd = [ph2acf_bin_path, "-m", mod_name, "-t", self.test_type]
                output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
                success = True
            except subprocess.CalledProcessError as e:
                output = e.output
                success = False
            except FileNotFoundError:
                output = "Error: Ph2_ACF ladder_test executable not found."
                success = False

            # Save per-module results
            mod_res_path = os.path.join(ladder_dir, f"{mod_name}_results.txt")
            with open(mod_res_path, "w") as f:
                f.write(output)
                
            results[mod_name] = success
            res_msg = f"Finished {mod_name}. Success: {success}"
            self.logger.info(res_msg)
            if progress_callback:
                progress_callback(res_msg)

        # Save an overall summary
        summary_path = os.path.join(ladder_dir, "ladder_summary.json")
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=4)
            
        final_msg = "Ladder testing complete."
        self.logger.info(final_msg)
        if progress_callback:
            progress_callback(final_msg)
        return results
