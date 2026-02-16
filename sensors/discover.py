"""Discovery mechanism for Homely sensors."""
from typing import Any
from . import SENSORS


def _get_value_by_path(obj: dict, path: str) -> Any:
    """Get value from nested dict using dot-notation path.
    
    Example: "alarm.states.alarm.value" -> obj["alarm"]["states"]["alarm"]["value"]
    """
    keys = path.split(".")
    value = obj
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def discover_device_sensors(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Discover all available sensors for a device.
    
    Returns a list of sensor configurations that match the device's features.
    Each discovered sensor includes device information and the current value.
    """
    discovered = []
    device_name = device.get("name", "Unknown")
    
    for sensor_config in SENSORS:
        path = sensor_config["path"]
        value = _get_value_by_path(device, path)
        
        # Only add sensor if device has this feature
        if value is not None:
            # Build sensor name (use get_name function if available)
            if "get_name" in sensor_config:
                sensor_name = sensor_config["get_name"](device)
            else:
                sensor_name = sensor_config["name"]
            
            # Build device class (use get_device_class function if available)
            device_class = sensor_config.get("device_class")
            if "get_device_class" in sensor_config:
                device_class = sensor_config["get_device_class"](device)
            
            discovered.append({
                **sensor_config,
                "device_id": device.get("id"),
                "device_name": device.get("name"),
                "model_name": device.get("modelName"),
                "serial_number": device.get("serialNumber"),
                "resolved_name": sensor_name,
                "resolved_device_class": device_class,
                "value": value,
            })
    
    return discovered

