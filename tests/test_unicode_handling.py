#!/usr/bin/env python3
"""
Test file for unicode_handling.py

Tests the unicode_char_to_windows_alt_code function with various inputs:
- Non-string events (should pass through unchanged)
- ASCII characters (should convert to key events with proper shift handling)
- Unicode characters (should convert to Alt+hex sequences)
- Multi-character strings (should handle each character appropriately)
"""

import os
import sys
import unittest

# Add the src directory to the path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from mooncrater_input.unicode_handling import unicode_char_to_windows_alt_code


class TestUnicodeHandling(unittest.TestCase):
    """Test cases for Unicode handling functionality."""

    def test_non_string_events_pass_through(self):
        """Test that non-string events are passed through unchanged."""
        # Regular keyboard event
        keyboard_event = {
            "category": "keyboard",
            "type": "keyDown",
            "keyName": "KEY_A",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(keyboard_event)
        self.assertEqual(result, [keyboard_event])

        # Mouse event
        mouse_event = {
            "category": "mouse",
            "type": "mouseRel",
            "deltaX": 10,
            "deltaY": 5,
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(mouse_event)
        self.assertEqual(result, [mouse_event])

        # Non-typeUnicodeString keyboard event
        other_event = {
            "category": "keyboard",
            "type": "keyUp",
            "keyName": "KEY_B",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(other_event)
        self.assertEqual(result, [other_event])

    def test_empty_string_event(self):
        """Test that empty string events are passed through unchanged."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)
        self.assertEqual(result, [event])

    def test_single_ascii_lowercase_letter(self):
        """Test single ASCII lowercase letter converts to key events."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "a",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}
        ]
        self.assertEqual(result, expected)

    def test_single_ascii_uppercase_letter(self):
        """Test single ASCII uppercase letter converts to key events with shift."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "A",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        ]
        self.assertEqual(result, expected)

    def test_single_ascii_digit(self):
        """Test single ASCII digit converts to key events."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "5",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_5", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_5", "inputTag": "test"}
        ]
        self.assertEqual(result, expected)

    def test_single_ascii_special_char_no_shift(self):
        """Test single ASCII special character that doesn't need shift."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": " ",  # Space
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_SPACE", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_SPACE", "inputTag": "test"}
        ]
        self.assertEqual(result, expected)

    def test_single_ascii_special_char_with_shift(self):
        """Test single ASCII special character that needs shift."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "!",  # Exclamation mark (shift+1)
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_1", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_1", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        ]
        self.assertEqual(result, expected)

    def test_single_unicode_character(self):
        """Test single Unicode character converts to Alt+hex sequence."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "α",  # Greek lowercase alpha (U+03B1)
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            # Alt down
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTALT", "inputTag": "test"},
            # Plus (keypad)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_PLUS", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_PLUS", "inputTag": "test"},
            # 0 (keypad)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_0", "inputTag": "test"},
            # 3 (keypad)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_3", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_3", "inputTag": "test"},
            # B (regular letter key)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_B", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_B", "inputTag": "test"},
            # 1 (keypad)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_1", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_1", "inputTag": "test"},
            # Alt up
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTALT", "inputTag": "test"},
        ]
        self.assertEqual(result, expected)

    def test_multi_character_ascii_string(self):
        """Test multi-character ASCII string converts each character."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "Hi",
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            # H (uppercase, needs shift)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            # i (lowercase, no shift)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_I", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_I", "inputTag": "test"}
        ]
        self.assertEqual(result, expected)

    def test_mixed_ascii_unicode_string(self):
        """Test string with both ASCII and Unicode characters."""
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "a€",  # 'a' (ASCII) + '€' (Unicode U+20AC)
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        expected = [
            # a (ASCII)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            # € (Unicode U+20AC)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTALT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_PLUS", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_PLUS", "inputTag": "test"},
            # 2 (keypad)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_2", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_2", "inputTag": "test"},
            # 0 (keypad)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_0", "inputTag": "test"},
            # A (regular letter key)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            # C (regular letter key)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_C", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_C", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTALT", "inputTag": "test"},
        ]
        self.assertEqual(result, expected)

    def test_unmappable_ascii_character(self):
        """Test ASCII character that can't be mapped to a key."""
        # Using a control character that's not in our mapping
        event = {
            "category": "keyboard",
            "type": "typeUnicodeString",
            "string": "\x00",  # NULL character
            "inputTag": "test"
        }
        result = unicode_char_to_windows_alt_code(event)

        # Should convert to Alt+hex sequence since it's non-printable
        expected = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTALT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_PLUS", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_PLUS", "inputTag": "test"},
            # 0000 (using keypad keys)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_KP_0", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTALT", "inputTag": "test"},
        ]
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()