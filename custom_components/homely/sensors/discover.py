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


def _resolve_path_and_value(device: dict[str, Any], sensor_config: dict[str, Any]) -> tuple[str | None, Any]:
    """Resolve first matching path for a sensor configuration."""
    configured_paths = sensor_config.get("paths")
    if isinstance(configured_paths, list) and configured_paths:
        for candidate_path in configured_paths:
            if not isinstance(candidate_path, str):
                continue
            value = _get_value_by_path(device, candidate_path)
            if value is not None:
                return candidate_path, value
        return None, None

    path = sensor_config.get("path")
    if not isinstance(path, str):
        return None, None
    return path, _get_value_by_path(device, path)


def _transform_value(sensor_config: dict[str, Any], value: Any) -> Any:
    """Apply optional value transform from the sensor config."""
    transform = sensor_config.get("transform_value")
    if callable(transform):
        try:
            return transform(value)
        except (TypeError, ValueError):
            return value
    return value


def discover_device_sensors(device: dict[str, Any]) -> list[dict[str, Any]]:
    """Discover all available sensors for a device.
    
    Returns a list of sensor configurations that match the device's features.
    Each discovered sensor includes device information and the current value.
    """
    discovered = []
    for sensor_config in SENSORS:
        matched_path, value = _resolve_path_and_value(device, sensor_config)
        
        # Only add sensor if device has this feature
        if matched_path is not None and value is not None:
            transformed_value = _transform_value(sensor_config, value)
            # Build sensor name (use get_name function if available)
            if "get_name" in sensor_config:
                sensor_name = sensor_config["get_name"](device)
            else:
                sensor_name = sensor_config["name"]

            if "get_translation_key" in sensor_config:
                translation_key = sensor_config["get_translation_key"](device)
            else:
                translation_key = sensor_config.get("translation_key")
            
            # Build device class (use get_device_class function if available)
            device_class = sensor_config.get("device_class")
            if "get_device_class" in sensor_config:
                device_class = sensor_config["get_device_class"](device)
            
            discovered.append({
                **sensor_config,
                "path": matched_path,
                "device_id": device.get("id"),
                "device_name": device.get("name"),
                "model_name": device.get("modelName"),
                "serial_number": device.get("serialNumber"),
                "resolved_name": sensor_name,
                "resolved_translation_key": translation_key,
                "resolved_device_class": device_class,
                "value": transformed_value,
            })
    
    return discovered
