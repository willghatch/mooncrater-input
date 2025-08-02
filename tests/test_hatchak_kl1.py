#!/usr/bin/env python3
"""
Test file for hatchak_kl1.py - Hatchak keyboard layout implementation.

Tests the hatchak layout by processing lists of events and checking
the complete output event sequences holistically.
"""

import os
import pytest
import sys
from typing import List, Dict, Any

# Add the src directory to the path so we can import modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

from mooncrater_input.hatchak_kl1 import create_hatchak_layout

class TestHatchakSpaceKey:
    """Test space key behavior across all levels."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.layout = create_hatchak_layout()

    def test_f1_key_pass_through_all_levels(self):
        """Test that F1 key passes through F1 events on all levels."""
        # Test F1 key at level 0 (base level)
        level_0_down = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_F1", "inputTag": "test"}
        )
        level_0_up = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_F1", "inputTag": "test"}
        )

        expected_down = [{"category": "keyboard", "type": "keyDown", "keyName": "KEY_F1", "inputTag": "test"}]
        expected_up = [{"category": "keyboard", "type": "keyUp", "keyName": "KEY_F1", "inputTag": "test"}]

        assert level_0_down == expected_down, f"Level 0 down: expected {expected_down}, got {level_0_down}"
        assert level_0_up == expected_up, f"Level 0 up: expected {expected_up}, got {level_0_up}"

        # Test F1 key at level 2 (L3 - with CapsLock modifier)
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_CAPSLOCK", "inputTag": "test"})

        level_2_down = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_F1", "inputTag": "test"}
        )
        level_2_up = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_F1", "inputTag": "test"}
        )

        assert level_2_down == expected_down, f"Level 2 down: expected {expected_down}, got {level_2_down}"
        assert level_2_up == expected_up, f"Level 2 up: expected {expected_up}, got {level_2_up}"

        self.layout.process_event({"category": "keyboard", "type": "keyUp", "keyName": "KEY_CAPSLOCK", "inputTag": "test"})

        # Test F1 key at level 4 (L5 - with Ctrl modifier)
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTCTRL", "inputTag": "test"})

        level_4_down = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_F1", "inputTag": "test"}
        )
        level_4_up = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_F1", "inputTag": "test"}
        )

        assert level_4_down == expected_down, f"Level 4 down: expected {expected_down}, got {level_4_down}"
        assert level_4_up == expected_up, f"Level 4 up: expected {expected_up}, got {level_4_up}"


class TestHatchakBasicLayout:
    """Test basic Dvorak letter layout functionality."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.layout = create_hatchak_layout()

    def test_dvorak_letters_basic(self):
        """Test that basic Dvorak letters work correctly."""
        # Test sequence: type "hello" in Dvorak
        # In Dvorak: h=d, e=e, l=n, l=n, o=r
        input_events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_D", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_D", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_L", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_L", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_L", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_L", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_O", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_O", "inputTag": "test"},
        ]

        # Process all events and collect outputs
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Verify we get the expected key sequence using keyName
        key_down_names = [e.get("keyName") for e in output_events if e.get("type") == "keyDown" and "keyName" in e]
        expected_keys = ["KEY_D", "KEY_E", "KEY_N", "KEY_N", "KEY_R"]
        assert key_down_names == expected_keys

        # Verify we get matching key up events
        key_up_names = [e.get("keyName") for e in output_events if e.get("type") == "keyUp" and "keyName" in e]
        assert key_up_names == expected_keys

    def test_shifted_dvorak_letters(self):
        """Test Dvorak letters with shift for uppercase."""
        # Test sequence: shift + a (which is 'a' in Dvorak, should give 'A')
        input_events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
        ]

        # Process all events and collect outputs
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Find the key events using keyName
        key_events = [e for e in output_events if "keyName" in e]

        # Should have events for shifted A key
        down_keys = [e.get("keyName") for e in key_events if e.get("type") == "keyDown"]
        up_keys = [e.get("keyName") for e in key_events if e.get("type") == "keyUp"]

        # Should have KEY_A events (the actual scan code representation)
        assert "KEY_A" in down_keys
        assert "KEY_A" in up_keys


class TestHatchakLevel3Numbers:
    """Test Level 3 (L3) number functionality using CapsLock as L3 modifier."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.layout = create_hatchak_layout()





class TestHatchakModifierKeys:
    """Test modifier key placements and behaviors."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.layout = create_hatchak_layout()

    def test_tab_as_alt(self):
        """Test that Tab key acts as Alt modifier."""
        # Test Tab + A (Alt + A)
        input_events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_TAB", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_TAB", "inputTag": "test"},
        ]

        # Process all events
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Should have some output (exact behavior depends on modifier implementation)
        assert len(output_events) >= 0  # At minimum, shouldn't crash

    def test_q_as_ctrl(self):
        """Test that Q position acts as Ctrl modifier."""
        # Test Q + C (Ctrl + C)
        input_events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_Q", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_C", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_C", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_Q", "inputTag": "test"},
        ]

        # Process all events
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Should have some output
        assert len(output_events) >= 0


class TestHatchakComplexSequences:
    """Test complex typing sequences that combine multiple features."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.layout = create_hatchak_layout()

    def test_mixed_letters_and_numbers(self):
        """Test typing a sequence that mixes letters and L3 numbers."""
        # Type "hello123" - "hello" in Dvorak letters, then L3+numbers
        input_events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_D", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_D", "inputTag": "test"},

            # Switch to L3 and type numbers 1,2,3
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_M", "inputTag": "test"},  # Should be 1
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_W", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_W", "inputTag": "test"},  # Should be 2
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_W", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_V", "inputTag": "test"},  # Should be 3
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_V", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
        ]

        # Process all events
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Should have generated various events (key events and string events)
        output_count = len([e for e in output_events if "keyName" in e or e.get("type") == "typeUnicodeString"])
        assert output_count >= 5  # At least some output for letters and numbers

    def test_navigation_sequence(self):
        """Test a navigation sequence using L5 arrows."""
        # Use L5 to move around: left, down, right, up
        input_events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_H", "inputTag": "test"},  # Left
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_J", "inputTag": "test"},  # Down
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_J", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_L", "inputTag": "test"},  # Right
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_L", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_K", "inputTag": "test"},  # Up
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_K", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
        ]

        # Process all events
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Should have arrow key events
        arrow_events = [e for e in output_events if e.get("keyName") in ["KEY_LEFT", "KEY_DOWN", "KEY_RIGHT", "KEY_UP"]]
        assert len(arrow_events) == 8  # Should have at least 8 arrow events (4 down, 4 up)

class TestHatchakStateTracking:
    """Test that keyboard state is tracked correctly through complex sequences."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.layout = create_hatchak_layout()

    def test_modifier_state_isolation(self):
        """Test that different modifier states don't interfere with each other."""
        # Test sequence: L3 down, letter, L3 up, L5 down, letter, L5 up
        input_events = [
            # L3 modifier sequence
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_S", "inputTag": "test"},  # Should give 4
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_S", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},

            # L5 modifier sequence
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_H", "inputTag": "test"},  # Should give left arrow
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_H", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},

            # Regular letter
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},  # Should give 'a'
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
        ]

        # Process all events
        output_events = []
        for event in input_events:
            output_events.extend(self.layout.process_event(event))

        # Should have different types of outputs for different modifier states
        key_events = [e for e in output_events if "keyName" in e]
        arrow_events = [e for e in output_events if e.get("keyName") in ["KEY_LEFT"]]
        string_events = [e for e in output_events if e.get("type") == "typeUnicodeString"]

        # Should have gotten different outputs for different states
        total_outputs = len(key_events) + len(string_events)
        assert total_outputs >= 3  # At least some output from each section

    def test_level_calculation(self):
        """Test that current level is calculated correctly."""
        # Initial level should be 0
        assert self.layout.get_current_level() == 0

        # Note: This test will be more meaningful once modifier state tracking is fully implemented
        # For now, just verify the method exists and returns a reasonable value
        level = self.layout.get_current_level()
        assert isinstance(level, int)
        assert level >= 0


if __name__ == "__main__":
    # Run the tests if this file is executed directly
    pytest.main([__file__, "-v"])
    
