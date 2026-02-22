#!/usr/bin/env python3
"""
Quick verification script to test WebSocket integration setup.

This script verifies that all components are correctly installed
and configured for the Homely WebSocket integration.

Usage:
  python verify_setup.py

This is for verification only and cannot be run inside Home Assistant.
"""

import sys
import json
from pathlib import Path

def check_manifest():
    """Check if manifest.json is correctly configured."""
    print("✓ Checking manifest.json...")
    manifest_path = Path(__file__).parent / "manifest.json"
    
    if not manifest_path.exists():
        print("  ✗ manifest.json not found")
        return False
    
    with open(manifest_path) as f:
        manifest = json.load(f)
    
    required_fields = {
        "requirements": lambda m: "python-socketio" in str(m.get("requirements", [])),
        "version": lambda m: "1." in str(m.get("version", "")),
    }
    
    for field, check in required_fields.items():
        if not check(manifest):
            print(f"  ✗ {field} not correctly configured")
            return False
        print(f"  ✓ {field}: {manifest.get(field)}")
    
    return True

def check_files():
    """Check if all required files exist."""
    print("\n✓ Checking files...")
    base_path = Path(__file__).parent
    
    required_files = {
        "__init__.py": "Main integration setup",
        "websocket.py": "WebSocket client",
        "ws_updates.py": "WebSocket update helpers",
        "api.py": "API client",
        "entity_ids.py": "Entity ID helpers",
        "all_batteries_healthy.py": "Aggregate battery entity",
        "const.py": "Constants",
        "config_flow.py": "Config flow",
        "manifest.json": "Manifest",
    }
    
    all_exist = True
    for filename, description in required_files.items():
        file_path = base_path / filename
        exists = file_path.exists()
        status = "✓" if exists else "✗"
        print(f"  {status} {filename}: {description}")
        if not exists:
            all_exist = False
    
    return all_exist

def check_websocket_core():
    """Check if websocket.py has core reconnect functionality."""
    print("\n✓ Checking websocket.py core behavior...")
    websocket_path = Path(__file__).parent / "websocket.py"
    
    if not websocket_path.exists():
        print("  ✗ websocket.py not found")
        return False
    
    with open(websocket_path) as f:
        content = f.read()
    
    required_markers = [
        "class HomelyWebSocket",
        "async def connect(",
        "async def disconnect(",
        "async def _reconnect_loop(",
        "_reconnect_interval = 300",
        "reconnection=False",
        "def update_token(",
        "def request_reconnect(",
    ]
    
    all_found = True
    for marker in required_markers:
        found = marker in content
        status = "✓" if found else "✗"
        print(f"  {status} {marker}")
        if not found:
            all_found = False

    return all_found

def check_integration_wiring():
    """Check if __init__.py wires websocket + ws_updates correctly."""
    print("\n✓ Checking __init__.py integration wiring...")
    init_path = Path(__file__).parent / "__init__.py"
    
    if not init_path.exists():
        print("  ✗ __init__.py not found")
        return False
    
    with open(init_path) as f:
        content = f.read()
    
    required_markers = [
        "from .websocket import HomelyWebSocket",
        "from .ws_updates import apply_websocket_event_to_data",
        '"ws_status_listeners": []',
        "coordinator.async_set_updated_data",
        "ws.update_token(new_access_token)",
    ]
    
    all_found = True
    for marker in required_markers:
        found = marker in content
        status = "✓" if found else "✗"
        print(f"  {status} {marker}")
        if not found:
            all_found = False

    return all_found

def check_config_flow_validation():
    """Check stricter config flow validation and user-facing errors."""
    print("\n✓ Checking config_flow.py validation...")
    path = Path(__file__).parent / "config_flow.py"

    if not path.exists():
        print("  ✗ config_flow.py not found")
        return False

    content = path.read_text()
    required_markers = [
        "fetch_token_with_reason",
        "_fetch_locations_for_credentials",
        'errors[CONF_HOME_ID] = "invalid_home_id"',
        'errors[CONF_SCAN_INTERVAL] = "invalid_scan_interval"',
        "home_id >= len(location_response)",
    ]

    all_found = True
    for marker in required_markers:
        found = marker in content
        status = "✓" if found else "✗"
        print(f"  {status} {marker}")
        if not found:
            all_found = False

    return all_found

def check_ws_update_helpers():
    """Check if ws_updates.py contains expected update helpers."""
    print("\n✓ Checking ws_updates.py helpers...")
    path = Path(__file__).parent / "ws_updates.py"

    if not path.exists():
        print("  ✗ ws_updates.py not found")
        return False

    with open(path) as f:
        content = f.read()

    required_symbols = [
        "def apply_websocket_event_to_data",
        "def apply_device_state_changes",
        "def ensure_alarm_root",
    ]

    all_found = True
    for symbol in required_symbols:
        found = symbol in content
        status = "✓" if found else "✗"
        print(f"  {status} {symbol}")
        if not found:
            all_found = False

    return all_found

def check_unique_ids():
    """Check important unique ID setup for multi-home support."""
    print("\n✓ Checking unique ID helpers...")
    entity_ids_path = Path(__file__).parent / "entity_ids.py"
    battery_path = Path(__file__).parent / "all_batteries_healthy.py"

    if not entity_ids_path.exists() or not battery_path.exists():
        print("  ✗ entity_ids.py or all_batteries_healthy.py not found")
        return False

    entity_ids_content = entity_ids_path.read_text()
    battery_content = battery_path.read_text()

    checks = [
        ("battery_problem_unique_id helper", "def battery_problem_unique_id" in entity_ids_content),
        ("location-based battery unique id", "location_{location_id}_any_battery_problem" in entity_ids_content),
        ("battery entity uses helper", "battery_problem_unique_id(location_id)" in battery_content),
    ]

    all_ok = True
    for label, ok in checks:
        status = "✓" if ok else "✗"
        print(f"  {status} {label}")
        if not ok:
            all_ok = False

    return all_ok

def main():
    """Run all checks."""
    print("=" * 50)
    print("Homely WebSocket Integration - Setup Verification")
    print("=" * 50)
    
    checks = [
        ("Manifest Configuration", check_manifest),
        ("Required Files", check_files),
        ("WebSocket Core", check_websocket_core),
        ("Init Integration Wiring", check_integration_wiring),
        ("WebSocket Update Helpers", check_ws_update_helpers),
        ("Config Flow Validation", check_config_flow_validation),
        ("Unique ID Setup", check_unique_ids),
    ]
    
    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ Error in {name}: {e}")
            results.append((name, False))
    
    print("\n" + "=" * 50)
    print("Summary:")
    print("=" * 50)
    
    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n✓ All checks passed! WebSocket integration is ready.")
        print("\nNext steps:")
        print("1. Restart Home Assistant")
        print("2. Add the Homely integration")
        print("3. Check logs: logger.logs: custom_components.homely: debug")
        return 0
    else:
        print("\n✗ Some checks failed. Please review the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
