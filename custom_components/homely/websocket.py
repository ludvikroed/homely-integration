"""Compatibility export for the reusable Homely SDK websocket client."""

from importlib import import_module

HomelyWebSocket = getattr(import_module("homely.websocket"), "HomelyWebSocket")

__all__ = ["HomelyWebSocket"]
