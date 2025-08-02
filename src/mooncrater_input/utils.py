#!/usr/bin/env python3

import sys
from typing import Dict

# Global log level for classes that don't have access to MooncraterInput
_global_log_level = "info"


def _should_log(level: str) -> bool:
    """Check if a message at the given level should be logged."""
    levels = {"debug": 0, "info": 1, "warning": 2, "error": 3}
    current_level = levels.get(_global_log_level, 1)
    message_level = levels.get(level, 1)
    return message_level >= current_level


def _log_global(level: str, message: str):
    """Global logging function for classes without MooncraterInput access."""
    if _should_log(level):
        if level == "error":
            print(f"[{level.upper()}] {message}", file=sys.stderr)
        else:
            print(f"[{level.upper()}] {message}")


def json_event_for_network(event: dict) -> dict:
    """Prepare a JSON event dictionary for network transmission by removing originalEvdevEvent."""
    result = event.copy()
    if "originalEvdevEvent" in result:
        del result["originalEvdevEvent"]
    return result


def set_global_log_level(level: str):
    """Set the global log level."""
    global _global_log_level
    _global_log_level = level


# Configuration for handleTypeEvents function
_unicode_config = {
    "mode": "warn",  # "warn", "windows_os", "custom"
    "warn_message": "typeUnicodeString event not configured, ignoring",
}


def configure_unicode_handling(mode: str, **kwargs):
    """Configure how handleTypeEvents processes typeUnicodeString events.

    Args:
        mode: Configuration mode - "warn" (default), "windows_os", or "custom"
        **kwargs: Additional configuration parameters for specific modes
    """
    global _unicode_config
    _unicode_config = {"mode": mode, **kwargs}


def handleTypeEvents(event):
    """Translate typing events to appropriate keyUp and keyDown events.

    This function handles two kinds of typing events:
    - "typeQwertyString": Returns keyDown/keyUp events for typing on US QWERTY keyboard
    - "typeUnicodeString": Configurable unicode handling (default: warn and do nothing)

    Also handles eventList events by recursive processing, and returns other events as-is.

    Args:
        event: A single event dictionary

    Returns:
        List of events (empty list if event is consumed/ignored)
    """
    # Handle eventList events by recursive processing
    if isinstance(event, dict) and event.get("type") == "eventList":
        result_events = []
        for sub_event in event.get("events", []):
            result_events.extend(handleTypeEvents(sub_event))
        return result_events

    # Handle typeQwertyString events
    if isinstance(event, dict) and event.get("type") == "typeQwertyString":
        string_to_type = event.get("string", "")
        input_tag = event.get("inputTag", "synthetic")

        result_events = []
        for char in string_to_type:
            # Create keyDown event
            key_down_event = {
                "category": "keyboard",
                "type": "keyDown",
                "keyChar": char,
                "inputTag": input_tag,
            }
            result_events.append(key_down_event)

            # Create keyUp event
            key_up_event = {
                "category": "keyboard",
                "type": "keyUp",
                "keyChar": char,
                "inputTag": input_tag,
            }
            result_events.append(key_up_event)

        return result_events

    # Handle typeUnicodeString events
    if isinstance(event, dict) and event.get("type") == "typeUnicodeString":
        mode = _unicode_config.get("mode", "warn")

        if mode == "warn":
            message = _unicode_config.get("warn_message", "typeUnicodeString event not configured, ignoring")
            _log_global("warning", message)
            return []  # Do nothing
        elif mode == "windows_os":
            # TODO: Implement Windows OS convention for unicode
            _log_global("warning", "Windows OS unicode mode not yet implemented")
            return []
        elif mode == "custom":
            # TODO: Implement custom encoding for XKB configuration
            _log_global("warning", "Custom unicode mode not yet implemented")
            return []
        else:
            _log_global("warning", f"Unknown unicode mode '{mode}', ignoring typeUnicodeString event")
            return []

    # For all other events, return them as-is in a list
    return [event]
