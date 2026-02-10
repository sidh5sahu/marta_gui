Inside the GUI directory the filkes are in tree level as:

.
├── app.py
├── app.py.backup
├── app.py.progress
├── config_window.py
├── __init__.py
├── managers
│   ├── connection_manager.py
│   ├── controller.py
│   ├── __init__.py
│   ├── plot_manager.py
│   ├── __pycache__
│   │   ├── connection_manager.cpython-310.pyc
│   │   ├── controller.cpython-310.pyc
│   │   ├── __init__.cpython-310.pyc
│   │   ├── plot_manager.cpython-310.pyc
│   │   └── report_manager.cpython-310.pyc
│   └── report_manager.py
└── __pycache__
    ├── app.cpython-310.pyc
    ├── app.cpython-39.pyc
    ├── config_window.cpython-310.pyc
    ├── config_window.cpython-39.pyc
    ├── __init__.cpython-310.pyc
    └── __init__.cpython-39.pyc



after removing the unessesary files 

.
├── app.py
├── config_window.py
└── managers/
    ├── connection_manager.py
    ├── controller.py
    ├── __init__.py
    ├── plot_manager.py
    └── report_manager.py


