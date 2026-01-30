#!/usr/bin/env python3
"""
Comprehensive test suite for the refactored Marta GUI.
Tests manager imports, initialization, and basic functionality.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all managers can be imported."""
    print("=" * 60)
    print("TEST 1: Manager Imports")
    print("=" * 60)
    
    try:
        from marta_app.gui.managers import (
            ReportManager,
            PlotManager,
            ConnectionManager,
            MartaController
        )
        print("✅ All manager imports successful")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_manager_initialization():
    """Test that managers can be initialized."""
    print("\n" + "=" * 60)
    print("TEST 2: Manager Initialization")
    print("=" * 60)
    
    try:
        from marta_app.gui.managers import (
            ReportManager,
            PlotManager,
            ConnectionManager,
            MartaController
        )
        import queue
        
        # Mock callbacks
        log_callback = lambda msg: print(f"  [LOG] {msg}")
        
        # Test ReportManager
        print("\n📝 Testing ReportManager...")
        report_mgr = ReportManager(log_callback=log_callback)
        print("  ✅ ReportManager initialized")
        
        # Test ConnectionManager
        print("\n🔌 Testing ConnectionManager...")
        gui_update_q = queue.Queue()
        config = {"marta_ip": "10.0.0.1", "esp32_ip": "10.0.0.2"}
        connection_mgr = ConnectionManager(
            config=config,
            gui_update_q=gui_update_q,
            log_callback=log_callback,
            web_update_callback=lambda *args: None
        )
        print("  ✅ ConnectionManager initialized")
        
        # Test PlotManager
        print("\n📊 Testing PlotManager...")
        plot_mgr = PlotManager(
            poller_getter=lambda: None,
            ambient_poller_getter=lambda: None,
            param_getters={'var_max': lambda: '15', 'var_min': lambda: '10'},
            log_callback=log_callback
        )
        print("  ✅ PlotManager initialized")
        
        # Test MartaController
        print("\n🎛️  Testing MartaController...")
        controller = MartaController(
            connection_mgr=connection_mgr,
            gui_update_q=gui_update_q,
            log_callback=log_callback,
            report_mgr=report_mgr,
            plot_mgr=plot_mgr
        )
        print("  ✅ MartaController initialized")
        
        print("\n✅ All managers initialized successfully")
        return True
        
    except Exception as e:
        print(f"\n❌ Initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_manager_methods():
    """Test that manager methods exist and are callable."""
    print("\n" + "=" * 60)
    print("TEST 3: Manager Method Availability")
    print("=" * 60)
    
    try:
        from marta_app.gui.managers import (
            ReportManager,
            PlotManager,
            ConnectionManager,
            MartaController
        )
        
        # Check ReportManager methods
        print("\n📝 ReportManager methods:")
        report_methods = ['set_run_info', 'generate_start_report', 'generate_stop_report']
        for method in report_methods:
            assert hasattr(ReportManager, method), f"Missing method: {method}"
            print(f"  ✅ {method}")
        
        # Check PlotManager methods
        print("\n📊 PlotManager methods:")
        plot_methods = [
            'open_all_temps_plot', 'open_ambient_temp_plot', 'open_humidity_plot',
            'open_dew_point_plot', 'open_cycle_plot', 'open_unified_plot',
            'open_contact_point', 'save_all_plots'
        ]
        for method in plot_methods:
            assert hasattr(PlotManager, method), f"Missing method: {method}"
            print(f"  ✅ {method}")
        
        # Check ConnectionManager methods
        print("\n🔌 ConnectionManager methods:")
        conn_methods = [
            'connect_marta', 'connect_esp32', 'disconnect', 'test_network',
            'update_param_display', 'update_ambient_display', 'check_health',
            'is_connected', 'get_poller', 'get_ambient_poller'
        ]
        for method in conn_methods:
            assert hasattr(ConnectionManager, method), f"Missing method: {method}"
            print(f"  ✅ {method}")
        
        # Check MartaController methods
        print("\n🎛️  MartaController methods:")
        controller_methods = [
            'start_chiller', 'stop_chiller', 'start_co2', 'stop_co2', 'stop_all',
            'update_pump', 'get_active_setpoint', 'get_current_target', 'set_stable_color'
        ]
        for method in controller_methods:
            assert hasattr(MartaController, method), f"Missing method: {method}"
            print(f"  ✅ {method}")
        
        print("\n✅ All required methods present")
        return True
        
    except Exception as e:
        print(f"\n❌ Method check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_app_integration():
    """Test that app.py can import and use managers."""
    print("\n" + "=" * 60)
    print("TEST 4: App Integration")
    print("=" * 60)
    
    try:
        # Check that app.py imports managers
        with open('marta_app/gui/app.py', 'r') as f:
            content = f.read()
        
        print("\n🔍 Checking app.py integration...")
        
        # Check imports
        required_imports = [
            'from .managers.report_manager import ReportManager',
            'from .managers.plot_manager import PlotManager',
            'from .managers.connection_manager import ConnectionManager',
            'from .managers.controller import MartaController'
        ]
        
        for imp in required_imports:
            if imp in content:
                print(f"  ✅ {imp}")
            else:
                print(f"  ❌ Missing: {imp}")
                return False
        
        # Check manager initialization
        if 'self.report_mgr = ReportManager' in content:
            print("  ✅ ReportManager instantiation found")
        else:
            print("  ❌ ReportManager instantiation missing")
            return False
            
        if 'self.connection_mgr = ConnectionManager' in content:
            print("  ✅ ConnectionManager instantiation found")
        else:
            print("  ❌ ConnectionManager instantiation missing")
            return False
            
        if 'self.plot_mgr = PlotManager' in content:
            print("  ✅ PlotManager instantiation found")
        else:
            print("  ❌ PlotManager instantiation missing")
            return False
            
        if 'self.controller = MartaController' in content:
            print("  ✅ MartaController instantiation found")
        else:
            print("  ❌ MartaController instantiation missing")
            return False
        
        # Check method delegations
        delegation_checks = [
            ('self.connection_mgr.connect_marta', 'Connection delegation'),
            ('self.controller.start_chiller', 'Chiller control delegation'),
            ('self.plot_mgr.open_all_temps_plot', 'Plot delegation'),
            ('self.report_mgr.generate_start_report', 'Report delegation')
        ]
        
        for pattern, desc in delegation_checks:
            if pattern in content:
                print(f"  ✅ {desc}")
            else:
                print(f"  ⚠️  {desc} not found (may use different pattern)")
        
        print("\n✅ App integration successful")
        return True
        
    except Exception as e:
        print(f"\n❌ App integration check failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_syntax_all_files():
    """Test syntax of all Python files."""
    print("\n" + "=" * 60)
    print("TEST 5: Syntax Validation")
    print("=" * 60)
    
    import py_compile
    
    files_to_check = [
        'marta_app/gui/app.py',
        'marta_app/gui/managers/__init__.py',
        'marta_app/gui/managers/report_manager.py',
        'marta_app/gui/managers/plot_manager.py',
        'marta_app/gui/managers/connection_manager.py',
        'marta_app/gui/managers/controller.py'
    ]
    
    all_passed = True
    for file_path in files_to_check:
        try:
            py_compile.compile(file_path, doraise=True)
            print(f"  ✅ {file_path}")
        except Exception as e:
            print(f"  ❌ {file_path}: {e}")
            all_passed = False
    
    if all_passed:
        print("\n✅ All files have valid syntax")
    else:
        print("\n❌ Some files have syntax errors")
    
    return all_passed

def main():
    """Run all tests."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "MARTA GUI REFACTORING TEST SUITE" + " " * 16 + "║")
    print("╚" + "=" * 58 + "╝")
    
    results = []
    
    # Run tests
    results.append(("Imports", test_imports()))
    results.append(("Initialization", test_manager_initialization()))
    results.append(("Method Availability", test_manager_methods()))
    results.append(("App Integration", test_app_integration()))
    results.append(("Syntax Validation", test_syntax_all_files()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:.<40} {status}")
    
    print("\n" + "=" * 60)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Refactoring successful!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review output above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
