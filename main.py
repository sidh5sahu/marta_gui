import tkinter as tk
import threading
import sys
import os

# Ensure the current directory is in the python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from marta_app.gui.app import MartaGUI
from marta_app.web.server import start_web_server

def main():
    # Start Web Server (initially with no pollers)
    print("Starting Web Server on port 5000...")
    start_web_server(None, None, port=5000)
    
    # Start GUI
    print("Starting GUI...")
    root = tk.Tk()
    app = MartaGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
