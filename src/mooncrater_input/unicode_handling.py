#!/usr/bin/env python3
"""
Unicode handling utilities for Windows Alt+code input.

This module provides functionality to convert Unicode characters to Windows
Alt+hex input sequences for compatibility with Windows systems.
"""

from typing import List, Dict, Any, Union


class WindowsUnicodeCapture:
    """
    Stateful filter that detects QMK's UNICODE_MODE_WINDOWS key sequences and
    converts them to typeUnicodeString events.

    Maintains a separate state machine per inputTag so interleaved events from
    different input sources don't interfere with each other.

    The Windows Alt+KP+ hex sequence that QMK emits per character:
      KEY_LEFTALT down
      KEY_KPPLUS down + up
      hex digit keys (KEY_KP0-KEY_KP9 for 0-9, KEY_A-KEY_F for a-f) down + up each
      KEY_LEFTALT up

    On completion, emits a single typeUnicodeString event with the decoded character.
    All intermediate key events are suppressed. If the sequence is interrupted by an
    unexpected key, the buffered events are flushed as passthrough and the filter resets.
    """

    _IDLE = 'idle'
    _SAW_ALT = 'saw_alt'
    _SAW_KPPLUS = 'saw_kpplus'
    _CAPTURING = 'capturing'

    _KP_DIGIT_MAP = {
        'KEY_KP0': '0', 'KEY_KP1': '1', 'KEY_KP2': '2', 'KEY_KP3': '3',
        'KEY_KP4': '4', 'KEY_KP5': '5', 'KEY_KP6': '6', 'KEY_KP7': '7',
        'KEY_KP8': '8', 'KEY_KP9': '9',
        'KEY_A': 'a', 'KEY_B': 'b', 'KEY_C': 'c',
        'KEY_D': 'd', 'KEY_E': 'e', 'KEY_F': 'f',
    }

    def __init__(self):
        self._states: Dict[str, Dict] = {}

    def _get_state(self, tag: str) -> Dict:
        if tag not in self._states:
            self._states[tag] = {'state': self._IDLE, 'buffer': [], 'hex_digits': []}
        return self._states[tag]

    def _reset(self, st: Dict):
        st['state'] = self._IDLE
        st['buffer'] = []
        st['hex_digits'] = []

    def process_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        output = []
        for event in events:
            output.extend(self._process_one(event))
        return output

    def _process_one(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        if event.get('category') != 'keyboard':
            return [event]

        tag = event.get('inputTag', '')
        st = self._get_state(tag)
        event_type = event.get('type')
        keyname = event.get('keyName', '')
        state = st['state']

        if state == self._IDLE:
            if event_type == 'keyDown' and keyname == 'KEY_LEFTALT':
                st['state'] = self._SAW_ALT
                st['buffer'] = [event]
                return []
            return [event]

        elif state == self._SAW_ALT:
            if event_type == 'keyDown' and keyname == 'KEY_KPPLUS':
                st['state'] = self._SAW_KPPLUS
                st['buffer'].append(event)
                return []
            else:
                flushed = st['buffer']
                self._reset(st)
                return flushed + self._process_one(event)

        elif state == self._SAW_KPPLUS:
            if event_type == 'keyUp' and keyname == 'KEY_KPPLUS':
                st['state'] = self._CAPTURING
                st['hex_digits'] = []
                # buffer is no longer needed; suppress the KP+ keyUp
                st['buffer'] = []
                return []
            else:
                flushed = st['buffer']
                self._reset(st)
                return flushed + self._process_one(event)

        elif state == self._CAPTURING:
            if keyname in self._KP_DIGIT_MAP and event_type in ('keyDown', 'keyUp'):
                if event_type == 'keyDown':
                    st['hex_digits'].append(self._KP_DIGIT_MAP[keyname])
                # suppress both down and up for digit keys
                return []
            elif event_type == 'keyUp' and keyname == 'KEY_LEFTALT':
                hex_str = ''.join(st['hex_digits'])
                self._reset(st)
                if hex_str:
                    try:
                        char = chr(int(hex_str, 16))
                        return [{'category': 'keyboard', 'type': 'typeUnicodeString',
                                 'string': char, 'inputTag': tag}]
                    except (ValueError, OverflowError):
                        pass
                return []
            else:
                # Unexpected event mid-sequence; buffer is already cleared in CAPTURING
                self._reset(st)
                return self._process_one(event)

        return [event]


def unicode_char_to_windows_alt_code(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert Unicode character events to Windows Alt+hex sequences.

    Takes an event in the standard JSON format and returns a list of events.
    For typeUnicodeString events with a single non-printable ASCII character,
    returns Alt+hex sequence. Otherwise returns the event unchanged.

    Args:
        event: Input event dictionary

    Returns:
        List of output events
    """
    # Only handle typeUnicodeString events
    if event.get("type") != "typeUnicodeString":
        return [event]

    # Get the string from the event
    string_content = event.get("string", "")
    if not string_content:
        return [event]

    input_tag = event.get("inputTag", "layout")

    # Handle multi-character strings by processing each character
    events = []
    for char in string_content:
        # Create a single-character event and process it recursively
        char_event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": char,
            "inputTag": input_tag
        }
        char_events = _process_single_character(char_event)
        events.extend(char_events)

    return events


def _process_single_character(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Process a single character typeUnicodeString event."""
    string_content = event.get("string", "")
    if len(string_content) != 1:
        return [event]  # Should not happen, but handle gracefully

    char = string_content[0]
    input_tag = event.get("inputTag", "layout")

    # Check if it's a printable ASCII character (32-126 range)
    if 32 <= ord(char) <= 126:
        return _ascii_char_to_key_events(char, input_tag)

    # Non-printable character - use Alt+hex sequence
    code_point = ord(char)
    hex_string = f"{code_point:04x}"  # 4-digit lowercase

    events = []

    # 1. Left Alt down
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_LEFTALT",
        "inputTag": input_tag
    })

    # 2. Keypad Plus down and up
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_KP_PLUS",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_KP_PLUS",
        "inputTag": input_tag
    })

    # 3. Each hex digit as keypad numbers (0-9) and regular letters (A-F)
    for digit in hex_string:
        key_name = _hex_digit_to_key(digit)
        events.append({
            "category": "keyboard",
            "type": "keyDown",
            "keyName": key_name,
            "inputTag": input_tag
        })
        events.append({
            "category": "keyboard",
            "type": "keyUp",
            "keyName": key_name,
            "inputTag": input_tag
        })

    # 4. Left Alt up
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_LEFTALT",
        "inputTag": input_tag
    })

    return events


def _hex_digit_to_key(digit: str) -> str:
    """Convert a hex digit to the corresponding keypad key name."""
    digit_map = {
        '0': 'KEY_KP_0',
        '1': 'KEY_KP_1',
        '2': 'KEY_KP_2',
        '3': 'KEY_KP_3',
        '4': 'KEY_KP_4',
        '5': 'KEY_KP_5',
        '6': 'KEY_KP_6',
        '7': 'KEY_KP_7',
        '8': 'KEY_KP_8',
        '9': 'KEY_KP_9',
        'A': 'KEY_A',  # Letter A (regular keys for A-F)
        'B': 'KEY_B',  # Letter B
        'C': 'KEY_C',  # Letter C
        'D': 'KEY_D',  # Letter D
        'E': 'KEY_E',  # Letter E
        'F': 'KEY_F',  # Letter F
        'a': 'KEY_A',  # Support lowercase too
        'b': 'KEY_B',
        'c': 'KEY_C',
        'd': 'KEY_D',
        'e': 'KEY_E',
        'f': 'KEY_F',
    }
    return digit_map.get(digit, 'KEY_KP_0')  # Default to keypad 0 if unknown


def _ascii_char_to_key_events(char: str, input_tag: str) -> List[Dict[str, Any]]:
    """Convert an ASCII character to key down/up events with proper shift handling."""
    key_name, needs_shift = _char_to_key_name(char)

    if key_name is None:
        # Character not representable, return original as-is
        return [{
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": char,
            "inputTag": input_tag
        }]

    events = []

    # If shift is needed, add shift down
    if needs_shift:
        events.append({
            "category": "keyboard",
            "type": "keyDown",
            "keyName": "KEY_LEFTSHIFT",
            "inputTag": input_tag
        })

    # Add key down
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": key_name,
        "inputTag": input_tag
    })

    # Add key up
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": key_name,
        "inputTag": input_tag
    })

    # If shift was used, add shift up
    if needs_shift:
        events.append({
            "category": "keyboard",
            "type": "keyUp",
            "keyName": "KEY_LEFTSHIFT",
            "inputTag": input_tag
        })

    return events


def _char_to_key_name(char: str) -> tuple[str, bool]:
    """
    Convert a character to the corresponding US QWERTY keyName and shift requirement.

    Based on the implementation from keyboard_layout_1.py.

    Args:
        char: Character to convert

    Returns:
        Tuple of (keyName, needs_shift) or (None, False) if not representable
    """
    # US QWERTY character to key mapping
    char_map = {
        # Letters
        'a': ('KEY_A', False), 'A': ('KEY_A', True),
        'b': ('KEY_B', False), 'B': ('KEY_B', True),
        'c': ('KEY_C', False), 'C': ('KEY_C', True),
        'd': ('KEY_D', False), 'D': ('KEY_D', True),
        'e': ('KEY_E', False), 'E': ('KEY_E', True),
        'f': ('KEY_F', False), 'F': ('KEY_F', True),
        'g': ('KEY_G', False), 'G': ('KEY_G', True),
        'h': ('KEY_H', False), 'H': ('KEY_H', True),
        'i': ('KEY_I', False), 'I': ('KEY_I', True),
        'j': ('KEY_J', False), 'J': ('KEY_J', True),
        'k': ('KEY_K', False), 'K': ('KEY_K', True),
        'l': ('KEY_L', False), 'L': ('KEY_L', True),
        'm': ('KEY_M', False), 'M': ('KEY_M', True),
        'n': ('KEY_N', False), 'N': ('KEY_N', True),
        'o': ('KEY_O', False), 'O': ('KEY_O', True),
        'p': ('KEY_P', False), 'P': ('KEY_P', True),
        'q': ('KEY_Q', False), 'Q': ('KEY_Q', True),
        'r': ('KEY_R', False), 'R': ('KEY_R', True),
        's': ('KEY_S', False), 'S': ('KEY_S', True),
        't': ('KEY_T', False), 'T': ('KEY_T', True),
        'u': ('KEY_U', False), 'U': ('KEY_U', True),
        'v': ('KEY_V', False), 'V': ('KEY_V', True),
        'w': ('KEY_W', False), 'W': ('KEY_W', True),
        'x': ('KEY_X', False), 'X': ('KEY_X', True),
        'y': ('KEY_Y', False), 'Y': ('KEY_Y', True),
        'z': ('KEY_Z', False), 'Z': ('KEY_Z', True),

        # Numbers
        '0': ('KEY_0', False), ')': ('KEY_0', True),
        '1': ('KEY_1', False), '!': ('KEY_1', True),
        '2': ('KEY_2', False), '@': ('KEY_2', True),
        '3': ('KEY_3', False), '#': ('KEY_3', True),
        '4': ('KEY_4', False), '$': ('KEY_4', True),
        '5': ('KEY_5', False), '%': ('KEY_5', True),
        '6': ('KEY_6', False), '^': ('KEY_6', True),
        '7': ('KEY_7', False), '&': ('KEY_7', True),
        '8': ('KEY_8', False), '*': ('KEY_8', True),
        '9': ('KEY_9', False), '(': ('KEY_9', True),

        # Punctuation
        ' ': ('KEY_SPACE', False),
        '\t': ('KEY_TAB', False),
        '\n': ('KEY_ENTER', False),
        '`': ('KEY_GRAVE', False), '~': ('KEY_GRAVE', True),
        '-': ('KEY_MINUS', False), '_': ('KEY_MINUS', True),
        '=': ('KEY_EQUAL', False), '+': ('KEY_EQUAL', True),
        '[': ('KEY_LEFTBRACE', False), '{': ('KEY_LEFTBRACE', True),
        ']': ('KEY_RIGHTBRACE', False), '}': ('KEY_RIGHTBRACE', True),
        '\\': ('KEY_BACKSLASH', False), '|': ('KEY_BACKSLASH', True),
        ';': ('KEY_SEMICOLON', False), ':': ('KEY_SEMICOLON', True),
        "'": ('KEY_APOSTROPHE', False), '"': ('KEY_APOSTROPHE', True),
        ',': ('KEY_COMMA', False), '<': ('KEY_COMMA', True),
        '.': ('KEY_DOT', False), '>': ('KEY_DOT', True),
        '/': ('KEY_SLASH', False), '?': ('KEY_SLASH', True),
    }

    return char_map.get(char, (None, False))


def unicode_char_to_linux_custom_xcompose(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert Unicode character events to Linux Xcompose sequences using custom XKB configuration.

    Takes an event in the standard JSON format and returns a list of events.
    For typeUnicodeString events, returns Xcompose sequence using Multi_key from custom XKB layout.
    The sequence format follows: Multi_key, less-than, hex values, greater-than
    This matches the format generated by generate-unicode-xcompose-from-unicodedata.py

    Args:
        event: Input event dictionary

    Returns:
        List of output events
    """
    # Only handle typeUnicodeString events
    if event.get("type") not in ("typeUnicodeString", "typeString"):
        return [event]

    # Get the string from the event
    string_content = event.get("string", "")
    if not string_content:
        return [event]

    input_tag = event.get("inputTag", "layout")

    # Handle multi-character strings by processing each character
    events = []
    for char in string_content:
        # Create a single-character event and process it recursively
        char_event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": char,
            "inputTag": input_tag
        }
        char_events = _process_single_character_xcompose(char_event)
        events.extend(char_events)

    return events


def _process_single_character_xcompose(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Process a single character typeUnicodeString event for Xcompose."""
    string_content = event.get("string", "")
    if len(string_content) != 1:
        return [event]  # Should not happen, but handle gracefully

    char = string_content[0]
    input_tag = event.get("inputTag", "layout")

    # Check if it's a printable ASCII character (32-126 range)
    if 32 <= ord(char) <= 126:
        return _ascii_char_to_key_events(char, input_tag)

    # Non-printable character - use Xcompose sequence
    # Format: Multi_key < hex_digits >
    code_point = ord(char)
    hex_string = f"{code_point:04x}"  # Lowercase hex with padding

    events = []

    # 1. Multi_key down and up (using scancode from custom XKB configuration)
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_COMPUTER",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_COMPUTER",
        "inputTag": input_tag
    })

    # 2. Less-than key down and up
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_LEFTSHIFT",  # Need shift for <
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_COMMA",  # , key with shift = <
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_COMMA",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_LEFTSHIFT",
        "inputTag": input_tag
    })

    # 3. Each hex digit (0-9, a-f)
    for digit in hex_string:
        key_name = _hex_digit_to_regular_key(digit)
        events.append({
            "category": "keyboard",
            "type": "keyDown",
            "keyName": key_name,
            "inputTag": input_tag
        })
        events.append({
            "category": "keyboard",
            "type": "keyUp",
            "keyName": key_name,
            "inputTag": input_tag
        })

    # 4. Greater-than key down and up
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_LEFTSHIFT",  # Need shift for >
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_DOT",  # . key with shift = >
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_DOT",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_LEFTSHIFT",
        "inputTag": input_tag
    })

    return events


def _hex_digit_to_regular_key(digit: str) -> str:
    """Convert a hex digit to the corresponding regular key name (not keypad)."""
    digit_map = {
        '0': 'KEY_0',
        '1': 'KEY_1',
        '2': 'KEY_2',
        '3': 'KEY_3',
        '4': 'KEY_4',
        '5': 'KEY_5',
        '6': 'KEY_6',
        '7': 'KEY_7',
        '8': 'KEY_8',
        '9': 'KEY_9',
        'a': 'KEY_A',  # Letter A (regular keys for A-F)
        'b': 'KEY_B',  # Letter B
        'c': 'KEY_C',  # Letter C
        'd': 'KEY_D',  # Letter D
        'e': 'KEY_E',  # Letter E
        'f': 'KEY_F',  # Letter F
        'A': 'KEY_A',  # Support uppercase too
        'B': 'KEY_B',
        'C': 'KEY_C',
        'D': 'KEY_D',
        'E': 'KEY_E',
        'F': 'KEY_F',
    }
    return digit_map.get(digit, 'KEY_0')  # Default to 0 if unknown


def unicode_char_to_linux_ibus(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Convert Unicode character events to Linux IBus Unicode input sequences.

    Takes an event in the standard JSON format and returns a list of events.
    For typeUnicodeString events, returns IBus Unicode input sequence.
    The sequence format is: Ctrl+Shift+U, hex digits, Space

    Note: IBus is not universally supported, so this is provided as an alternative
    to the custom Xcompose approach, but the Xcompose method is preferred.

    Args:
        event: Input event dictionary

    Returns:
        List of output events
    """
    # Only handle typeUnicodeString events
    if event.get("type") != "typeUnicodeString":
        return [event]

    # Get the string from the event
    string_content = event.get("string", "")
    if not string_content:
        return [event]

    input_tag = event.get("inputTag", "layout")

    # Handle multi-character strings by processing each character
    events = []
    for char in string_content:
        # Create a single-character event and process it recursively
        char_event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": char,
            "inputTag": input_tag
        }
        char_events = _process_single_character_ibus(char_event)
        events.extend(char_events)

    return events


def _process_single_character_ibus(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Process a single character typeUnicodeString event for IBus."""
    string_content = event.get("string", "")
    if len(string_content) != 1:
        return [event]  # Should not happen, but handle gracefully

    char = string_content[0]
    input_tag = event.get("inputTag", "layout")

    # Check if it's a printable ASCII character (32-126 range)
    if 32 <= ord(char) <= 126:
        return _ascii_char_to_key_events(char, input_tag)

    # Non-printable character - use IBus Unicode sequence
    # Format: Ctrl+Shift+U, hex digits, Space
    code_point = ord(char)
    hex_string = f"{code_point:x}"  # Lowercase hex without zero padding

    events = []

    # 1. Ctrl+Shift+U sequence
    # Press and hold Ctrl
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_LEFTCTRL",
        "inputTag": input_tag
    })

    # Press and hold Shift
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_LEFTSHIFT",
        "inputTag": input_tag
    })

    # Press and release U
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_U",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_U",
        "inputTag": input_tag
    })

    # Release Shift and Ctrl
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_LEFTSHIFT",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_LEFTCTRL",
        "inputTag": input_tag
    })

    # 2. Type hex digits (0-9, a-f)
    for digit in hex_string:
        key_name = _hex_digit_to_regular_key(digit)
        events.append({
            "category": "keyboard",
            "type": "keyDown",
            "keyName": key_name,
            "inputTag": input_tag
        })
        events.append({
            "category": "keyboard",
            "type": "keyUp",
            "keyName": key_name,
            "inputTag": input_tag
        })

    # 3. Press and release Space to complete the sequence
    events.append({
        "category": "keyboard",
        "type": "keyDown",
        "keyName": "KEY_SPACE",
        "inputTag": input_tag
    })
    events.append({
        "category": "keyboard",
        "type": "keyUp",
        "keyName": "KEY_SPACE",
        "inputTag": input_tag
    })

    return events
