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
        "api.py": "API client",
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

def check_websocket_imports():
    """Check if websocket.py has correct imports."""
    print("\n✓ Checking websocket.py imports...")
    websocket_path = Path(__file__).parent / "websocket.py"
    
    if not websocket_path.exists():
        print("  ✗ websocket.py not found")
        return False
    
    with open(websocket_path) as f:
        content = f.read()
    
    required_imports = [
        "import asyncio",
        "import logging",
        "from typing import Any, Callable",
        "class HomelyWebSocket",
    ]
    
    all_found = True
    for import_stmt in required_imports:
        found = import_stmt in content
        status = "✓" if found else "✗"
        print(f"  {status} {import_stmt}")
        if not found:
            all_found = False
    
    return all_found

def check_init_imports():
    """Check if __init__.py has WebSocket imports."""
    print("\n✓ Checking __init__.py imports...")
    init_path = Path(__file__).parent / "__init__.py"
    
    if not init_path.exists():
        print("  ✗ __init__.py not found")
        return False
    
    with open(init_path) as f:
        content = f.read()
    
    required_imports = [
        "import asyncio",
        "from .websocket import HomelyWebSocket",
        "init_websocket",
        "reconnect_with_token",
    ]
    
    all_found = True
    for import_stmt in required_imports:
        found = import_stmt in content
        status = "✓" if found else "✗"
        print(f"  {status} {import_stmt}")
        if not found:
            all_found = False
    
    return all_found

def main():
    """Run all checks."""
    print("=" * 50)
    print("Homely WebSocket Integration - Setup Verification")
    print("=" * 50)
    
    checks = [
        ("Manifest Configuration", check_manifest),
        ("Required Files", check_files),
        ("WebSocket Imports", check_websocket_imports),
        ("Init Integration Imports", check_init_imports),
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
