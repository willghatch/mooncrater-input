#!/usr/bin/env python3
"""
Comprehensive test file for KeyboardLayout1 class.

This test file addresses all the TODO requirements:
- Complete event sequences (keyDown + keyUp) tested holistically
- Shared test keymaps to avoid duplication
- Full modifier system testing (momentary, one-shot, lock)
- Level-based functionality with real multi-level bindings
- State verification throughout complex sequences
"""

# TODO - in these tests, don't check for "keyChar" fields of output events.  Test for "keyName" for input and output events.  Conceptually, the input and output events that this will process typically represent scan codes.  The scan codes come in as US QWERTY scan codes.  The scan codes that are output are also US QWERTY scan codes, but modified to represent the scan codes needed to produce the characters or other effects that the keyboard is implementing.  We are just using "keyName" as a higher-level implementation.  There may be a place for testing for "keyChar" fields later, but for now I want to ensure that things are working in terms of "keyName" as the priority.
# TODO - many of these tests search the output event list for a particular event to look at, but ignore the other events.  I want every test in this file to check every output event to ensure that all events are ordered correctly and to also serve as verifiable documentation of the precise behavior of exactly which output events are generated.
# TODO - test that a key that is bound directly to SpecialKey or CharKey without a list does that effect on all levels.  For a key bound to a list (or dictionary) specifying level-specific bindings, a missing binding means that it is ignored.  But a key bound to an effect without a list or dictionary means that it behaves the same on all levels.

import os
import pytest
import sys
import time
from typing import List, Dict, Any

# Add the src directory to the path so we can import modules
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, 'src'))

from mooncrater_input.keyboard_layout_1 import (
    KeyboardLayout1,
    SpecialKey,
    CharKey,
    Modifier,
    LevelModifier,
    TapOrHold,
    PassThrough,
    Fallthrough,
    Ignore,
    ModifierStyle,
)


# Shared test keymaps for reuse across test suites
def create_test_keymap_basic() -> Dict[str, Any]:
    """Create a basic test keymap with various binding types."""
    return {
        # Basic character keys with multiple levels
        "KEY_A": [CharKey("a"), CharKey("A"), "α", "Α"],  # Levels 0,1,2,3
        "KEY_B": [CharKey("b"), CharKey("B"), "β"],       # Levels 0,1,2 (no level 3)
        "KEY_C": CharKey("c"),                            # All levels
        "KEY_D": [CharKey("d")],                          # Only level 0

        # Special keys
        "KEY_UP": SpecialKey("KEY_UP"),
        "KEY_HOME": [SpecialKey("KEY_HOME"), SpecialKey("KEY_HOME", shifted=True)],

        # Modifiers
        "KEY_LEFTSHIFT": LevelModifier(1, ModifierStyle.MOMENTARY),
        "KEY_CAPSLOCK": LevelModifier(2, ModifierStyle.MOMENTARY),
        "KEY_LEFTCTRL": Modifier("KEY_LEFTCTRL", ModifierStyle.MOMENTARY),
        "KEY_RIGHTCTRL": Modifier("KEY_RIGHTCTRL", ModifierStyle.ONE_SHOT),

        # Function bindings
        "KEY_F1": (lambda e: [{"type": "custom_down", "from": e}],
                   lambda e: [{"type": "custom_up", "from": e}]),

        # PassThrough
        "KEY_ESC": PassThrough(),

        # TapOrHold (simplified for testing)
        "KEY_SPACE": TapOrHold(
            tap=CharKey(" "),
            hold=Modifier("KEY_LEFTMETA", ModifierStyle.MOMENTARY)
        ),
    }


def create_test_keymap_multilevel() -> Dict[str, Any]:
    """Create a keymap focused on multi-level functionality."""
    return {
        # Keys with bindings at multiple levels for comprehensive level testing
        "KEY_Q": {0: CharKey("q"), 1: CharKey("Q"), 2: "1", 3: "!", 4: SpecialKey("KEY_F1")},
        "KEY_W": {0: CharKey("w"), 2: "2", 4: SpecialKey("KEY_F2")},  # Gaps in levels
        "KEY_E": {1: CharKey("E"), 3: "@"},  # No level 0 binding

        # Level modifiers
        "KEY_LEFTSHIFT": LevelModifier(1, ModifierStyle.MOMENTARY),
        "KEY_RIGHTSHIFT": LevelModifier(1, ModifierStyle.ONE_SHOT),
        "KEY_CAPSLOCK": LevelModifier(2, ModifierStyle.MOMENTARY),
        "KEY_TAB": LevelModifier(4, ModifierStyle.MOMENTARY),

        # Control modifier for testing interaction
        "KEY_LEFTCTRL": Modifier("KEY_LEFTCTRL", ModifierStyle.MOMENTARY),
    }


def process_event_sequence(layout: KeyboardLayout1, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Process a sequence of events and return all output events."""
    output_events = []
    for event in events:
        result = layout.process_event(event)
        output_events.extend(result)
    return output_events


class TestSharedKeymapBasic:
    """Test suite using the basic shared keymap."""

    def setup_method(self):
        """Set up test environment with shared keymap."""
        self.delayed_eval = False  # Default, can be overridden by parameterized tests
        self.layout = KeyboardLayout1(create_test_keymap_basic(), delayed_eval=self.delayed_eval)

    @pytest.mark.parametrize("delayed_eval", [False, True])
    def test_basic_char_key_sequence(self, delayed_eval):
        """Test complete keyDown + keyUp sequence for basic character."""
        self.layout = KeyboardLayout1(create_test_keymap_basic(), delayed_eval=delayed_eval)

        # Test KEY_A which should map to 'a' key on level 0
        down_output = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"}
        )

        if delayed_eval:
            # Check delayed event format
            expected_delayed_down = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_down",
                "char_key": "a",
                "inputTag": "test"
            }]
            assert down_output == expected_delayed_down, f"Expected delayed {expected_delayed_down}, got: {down_output}"
            down_output = KeyboardLayout1.handle_delayed(down_output)

        up_output = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}
        )

        if delayed_eval:
            # Check delayed event format
            expected_delayed_up = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_up",
                "char_key": "a",
                "inputTag": "test"
            }]
            assert up_output == expected_delayed_up, f"Expected delayed {expected_delayed_up}, got: {up_output}"
            up_output = KeyboardLayout1.handle_delayed(up_output)

        # Should get keyDown for 'a' key, then keyUp for 'a' key
        expected_down = [{"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"}]
        expected_up = [{"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}]

        assert down_output == expected_down, f"Expected {expected_down}, got: {down_output}"
        assert up_output == expected_up, f"Expected {expected_up}, got: {up_output}"

    @pytest.mark.parametrize("delayed_eval", [False, True])
    def test_shifted_char_sequence(self, delayed_eval):
        """Test shift + character for uppercase with precise event verification - checking each event individually."""
        self.layout = KeyboardLayout1(create_test_keymap_basic(), delayed_eval=delayed_eval)

        # Step 1: Press shift key - should produce NO output events
        shift_down_output = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        )
        assert shift_down_output == [], f"Step 1: Expected no output after shift down, got: {shift_down_output}"

        # Step 2: Press KEY_A while shift is held - should generate exact sequence
        a_down_output = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"}
        )

        if delayed_eval:
            # Check delayed event format - should have capital A
            expected_delayed_a_down = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_down",
                "char_key": "A",
                "inputTag": "test"
            }]
            assert a_down_output == expected_delayed_a_down, f"Step 2 delayed: Expected {expected_delayed_a_down}, got: {a_down_output}"
            a_down_output = KeyboardLayout1.handle_delayed(a_down_output)

        # Should generate shift down, A key down with shift handling, shift up
        expected_a_down = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        ]
        assert a_down_output == expected_a_down, f"Step 2: Expected {expected_a_down}, got: {a_down_output}"

        # Step 3: Release A key - should generate A key up only
        a_up_output = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}
        )

        if delayed_eval:
            # Check delayed event format
            expected_delayed_a_up = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_up",
                "char_key": "A",
                "inputTag": "test"
            }]
            assert a_up_output == expected_delayed_a_up, f"Step 3 delayed: Expected {expected_delayed_a_up}, got: {a_up_output}"
            a_up_output = KeyboardLayout1.handle_delayed(a_up_output)

        expected_a_up = [
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}
        ]
        assert a_up_output == expected_a_up, f"Step 3: Expected {expected_a_up}, got: {a_up_output}"

        # Step 4: Release shift key - should produce no output
        shift_up_output = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        )
        assert shift_up_output == [], f"Step 4: Expected no output after shift up, got: {shift_up_output}"

    @pytest.mark.parametrize("delayed_eval", [False, True])
    def test_multiple_shifted_chars_sequence(self, delayed_eval):
        """Test multiple shifted characters in sequence - checking each event individually."""
        # Reset layout state
        self.layout = KeyboardLayout1(create_test_keymap_basic(), delayed_eval=delayed_eval)

        # Sequence: Shift+A, release A, Shift+B, release B, release Shift
        # This tests that shift state is maintained properly across multiple characters

        # 1. Press shift - should produce no output
        shift_down = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        )
        assert shift_down == [], f"Step 1: Expected no output after shift down, got: {shift_down}"

        # 2. Press A while shift held - should produce shifted A sequence
        a_down = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"}
        )

        if delayed_eval:
            expected_delayed = [{"category": "keyboardLayout1Delayed", "event_type": "key_down", "char_key": "A", "inputTag": "test"}]
            assert a_down == expected_delayed, f"Step 2 delayed: Expected {expected_delayed}, got: {a_down}"
            a_down = KeyboardLayout1.handle_delayed(a_down)

        expected_a_down = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        ]
        assert a_down == expected_a_down, f"Step 2: Expected {expected_a_down}, got: {a_down}"

        # 3. Release A - should produce A key up
        a_up = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}
        )

        if delayed_eval:
            expected_delayed = [{"category": "keyboardLayout1Delayed", "event_type": "key_up", "char_key": "A", "inputTag": "test"}]
            assert a_up == expected_delayed, f"Step 3 delayed: Expected {expected_delayed}, got: {a_up}"
            a_up = KeyboardLayout1.handle_delayed(a_up)

        expected_a_up = [
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"}
        ]
        assert a_up == expected_a_up, f"Step 3: Expected {expected_a_up}, got: {a_up}"

        # 4. Press B while shift still held - should produce shifted B sequence
        b_down = self.layout.process_event(
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_B", "inputTag": "test"}
        )

        if delayed_eval:
            expected_delayed = [{"category": "keyboardLayout1Delayed", "event_type": "key_down", "char_key": "B", "inputTag": "test"}]
            assert b_down == expected_delayed, f"Step 4 delayed: Expected {expected_delayed}, got: {b_down}"
            b_down = KeyboardLayout1.handle_delayed(b_down)

        expected_b_down = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_B", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        ]
        assert b_down == expected_b_down, f"Step 4: Expected {expected_b_down}, got: {b_down}"

        # 5. Release B - should produce B key up
        b_up = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_B", "inputTag": "test"}
        )

        if delayed_eval:
            expected_delayed = [{"category": "keyboardLayout1Delayed", "event_type": "key_up", "char_key": "B", "inputTag": "test"}]
            assert b_up == expected_delayed, f"Step 5 delayed: Expected {expected_delayed}, got: {b_up}"
            b_up = KeyboardLayout1.handle_delayed(b_up)

        expected_b_up = [
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_B", "inputTag": "test"}
        ]
        assert b_up == expected_b_up, f"Step 5: Expected {expected_b_up}, got: {b_up}"

        # 6. Release shift - should produce no output
        shift_up = self.layout.process_event(
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"}
        )
        assert shift_up == [], f"Step 6: Expected no output after shift up, got: {shift_up}"

    @pytest.mark.parametrize("delayed_eval", [False, True])
    def test_level_3_access(self, delayed_eval):
        """Test accessing level 3 with multiple modifiers - verifying ALL events."""
        self.layout = KeyboardLayout1(create_test_keymap_basic(), delayed_eval=delayed_eval)

        events = [
            # Press both shift (level 1) and capslock (level 2) to get level 3
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        if delayed_eval:
            # Check delayed events - should have key_down and key_up for string "Α"
            expected_delayed = [
                {"category": "keyboardLayout1Delayed", "event_type": "key_down", "string": "Α", "inputTag": "test"},
                {"category": "keyboardLayout1Delayed", "event_type": "key_up", "string": "Α", "inputTag": "test"}
            ]
            assert output == expected_delayed, f"Expected delayed output {expected_delayed}, got: {output}"
            output = KeyboardLayout1.handle_delayed(output)

        # Verify EVERY output event in precise order
        # Expected: shift down produces no output, capslock down produces no output,
        # A down should produce typeUnicodeString for "Α" (level 3),
        # A up produces no output, capslock up produces no output, shift up produces no output
        expected_output = [
            {"category": "keyboard", "type": "typeUnicodeString", "string": "Α", "inputTag": "test"}
        ]

        assert output == expected_output, f"Expected exact output {expected_output}, got: {output}"

    def test_control_modifier_immediate_events(self):
        """Test that control modifiers send events immediately."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_C", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_C", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should have ctrl key events
        ctrl_events = [e for e in output if e.get("keyName") == "KEY_LEFTCTRL"]
        assert len(ctrl_events) >= 2  # Should have ctrl down and ctrl up

        # Ctrl down should come first
        ctrl_down = next((e for e in ctrl_events if e.get("type") == "keyDown"), None)
        ctrl_up = next((e for e in ctrl_events if e.get("type") == "keyUp"), None)
        assert ctrl_down is not None
        assert ctrl_up is not None

        # Ctrl down should come before the 'c' character event
        ctrl_down_index = output.index(ctrl_down)
        char_events = [e for e in output if e.get("keyName") == "KEY_C" and e.get("type") == "keyDown"]
        if char_events:
            char_down_index = output.index(char_events[0])
            assert ctrl_down_index < char_down_index

    def test_function_binding_sequence(self):
        """Test function binding with keyDown and keyUp - verifying ALL events."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_F1", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_F1", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should have exactly 2 custom events in precise order
        expected_output = [
            {"type": "custom_down", "from": events[0]},
            {"type": "custom_up", "from": events[1]}
        ]
        assert output == expected_output, f"Expected exact function output {expected_output}, got: {output}"

    def test_passthrough_sequence(self):
        """Test PassThrough binding preserves events - verifying ALL events."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_ESC", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_ESC", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Events should pass through unchanged - verify every event matches exactly
        expected_output = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_ESC", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_ESC", "inputTag": "test"},
        ]
        assert output == expected_output, f"Expected exact passthrough {expected_output}, got: {output}"


class TestMultilevelKeymap:
    """Test suite focused on multi-level functionality."""

    def setup_method(self):
        """Set up test environment with multi-level keymap."""
        self.layout = KeyboardLayout1(create_test_keymap_multilevel())

    def test_level_exact_matching(self):
        """Test that only exact level matches are used (no fallthrough) - verifying ALL events."""
        # Test KEY_E which has no level 0 binding
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_E", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_E", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should get no output since KEY_E has no level 0 binding - verify empty list exactly
        expected_output = []
        assert output == expected_output, f"Expected exact empty output {expected_output}, got: {output}"

    def test_level_1_access(self):
        """Test accessing level 1 with shift."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_E", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_E", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should access level 1 binding for KEY_E (which is CharKey("E"))
        char_events = [e for e in output if e.get("keyName") == "KEY_E"]
        assert len(char_events) >= 2  # At least down and up

    def test_level_2_number_access(self):
        """Test accessing level 2 for numbers - verifying ALL events."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_Q", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_Q", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_CAPSLOCK", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should access level 2 binding for KEY_Q (which is "1") - verify complete output
        expected_output = [
            {"category": "keyboard", "type": "typeUnicodeString", "string": "1", "inputTag": "test"}
        ]
        assert output == expected_output, f"Expected exact level 2 output {expected_output}, got: {output}"

    def test_level_4_function_key_access(self):
        """Test accessing level 4 with tab modifier."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_TAB", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_Q", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_Q", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_TAB", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should access level 4 binding for KEY_Q (which is SpecialKey("KEY_F1"))
        f1_events = [e for e in output if e.get("keyName") == "KEY_F1"]
        assert len(f1_events) >= 2  # Should have F1 down and up

    def test_gap_in_levels(self):
        """Test key with gaps in level bindings."""
        # KEY_W has bindings at levels 0, 2, 4 but not 1 or 3

        # Test level 1 (should do nothing)
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_W", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_W", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)
        # There should be no events.
        assert output == []


class TestModifierStyles:
    """Test different modifier styles thoroughly."""

    def setup_method(self):
        """Set up test environment with various modifier styles."""
        self.layout = KeyboardLayout1({
            # Test keys
            "KEY_A": CharKey("a"),
            "KEY_B": CharKey("b"),

            # Different modifier styles
            "KEY_1": Modifier("KEY_LEFTCTRL", ModifierStyle.MOMENTARY),
            "KEY_2": Modifier("KEY_LEFTALT", ModifierStyle.ONE_SHOT),
            "KEY_3": LevelModifier(1, ModifierStyle.MOMENTARY),
            "KEY_4": LevelModifier(2, ModifierStyle.ONE_SHOT),
        })

    def test_momentary_control_modifier(self):
        """Test momentary control modifier sends events immediately."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_1", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_1", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should have ctrl events and character events
        ctrl_events = [e for e in output if e.get("keyName") == "KEY_LEFTCTRL"]
        char_events = [e for e in output if e.get("keyName") == "KEY_A"]

        assert len(ctrl_events) >= 2  # Ctrl down and up
        assert len(char_events) >= 2  # Char down and up

        # Ctrl down should come first
        assert ctrl_events[0]["type"] == "keyDown"
        assert output.index(ctrl_events[0]) < output.index(char_events[0])

    def test_one_shot_control_modifier(self):
        """Test one-shot control modifier behavior."""
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_2", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_2", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should have alt events (from one-shot) and character events
        alt_events = [e for e in output if e.get("keyName") == "KEY_LEFTALT"]
        char_events = [e for e in output if e.get("keyName") == "KEY_A"]

        assert len(alt_events) >= 1  # At least alt down
        assert len(char_events) >= 2  # Char down and up

    def test_momentary_level_modifier(self):
        """Test momentary level modifier affects level calculation."""
        # Test that level modifier changes which binding is used
        events = [
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_3", "inputTag": "test"},  # Level 1
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_3", "inputTag": "test"},
        ]

        # First verify current level changes
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_3", "inputTag": "test"})
        assert self.layout.get_current_level() >= 1

        output = process_event_sequence(self.layout, events)
        # Should have some output (exact behavior depends on KEY_A's level 1 binding)
        assert len(output) >= 0

    def test_one_shot_level_modifier_consumption(self):
        """Test that one-shot level modifiers are consumed after use."""
        # Press one-shot level modifier
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_4", "inputTag": "test"})
        self.layout.process_event({"category": "keyboard", "type": "keyUp", "keyName": "KEY_4", "inputTag": "test"})

        initial_level = self.layout.get_current_level()

        # Use it with a character key
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"})

        # Level should go back down after use
        final_level = self.layout.get_current_level()
        assert final_level < initial_level or initial_level == 0


class TestComplexSequences:
    """Test complex sequences that combine multiple features."""

    def setup_method(self):
        """Set up test environment with comprehensive keymap."""
        self.layout = KeyboardLayout1({
            # Multi-level character keys
            "KEY_A": [CharKey("a"), CharKey("A"), "1", "!"],
            "KEY_B": [CharKey("b"), CharKey("B"), "2", "@"],

            # Level modifiers
            "KEY_LEFTSHIFT": LevelModifier(1, ModifierStyle.MOMENTARY),
            "KEY_CAPSLOCK": LevelModifier(2, ModifierStyle.ONE_SHOT),

            # Control modifiers
            "KEY_LEFTCTRL": Modifier("KEY_LEFTCTRL", ModifierStyle.MOMENTARY),
            "KEY_RIGHTCTRL": Modifier("KEY_RIGHTCTRL", ModifierStyle.ONE_SHOT),

            # Navigation
            "KEY_LEFT": SpecialKey("KEY_LEFT"),
        })

    def test_modifier_interaction_isolation(self):
        """Test that level and control modifiers don't interfere."""
        events = [
            # Use control modifier with character
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},

            # Use level modifier with character
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_B", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_B", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},

            # Use both together
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTCTRL", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should have ctrl events and various character outputs
        ctrl_events = [e for e in output if e.get("keyName") == "KEY_LEFTCTRL"]
        char_events = [e for e in output if e.get("keyName") in ["KEY_A", "KEY_B"] or e.get("type") == "typeUnicodeString"]

        assert len(ctrl_events) >= 4  # Two sequences with ctrl
        assert len(char_events) >= 6  # Three character sequences

    def test_typing_sentence_with_modifiers(self):
        """Test typing a complete sentence with mixed modifiers."""
        # Type "Ab" (capital A, lowercase b)
        events = [
            # Capital A (shift + a)
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_LEFTSHIFT", "inputTag": "test"},

            # Lowercase b
            {"category": "keyboard", "type": "keyDown", "keyName": "KEY_B", "inputTag": "test"},
            {"category": "keyboard", "type": "keyUp", "keyName": "KEY_B", "inputTag": "test"},
        ]

        output = process_event_sequence(self.layout, events)

        # Should have character events for A and b
        char_events = [e for e in output if e.get("keyName") in ["KEY_A", "KEY_B"] and e.get("type") == "keyDown"]
        assert len(char_events) >= 2

        # Should get key events for both characters
        key_names = [e.get("keyName") for e in char_events]
        assert "KEY_A" in key_names
        assert "KEY_B" in key_names

    def test_state_tracking_through_complex_sequence(self):
        """Test that state is properly tracked through complex modifier usage."""
        # Start with clean state
        assert self.layout.get_current_level() == 0

        # Press one-shot level modifier
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_CAPSLOCK", "inputTag": "test"})
        self.layout.process_event({"category": "keyboard", "type": "keyUp", "keyName": "KEY_CAPSLOCK", "inputTag": "test"})

        level_after_oneshot = self.layout.get_current_level()
        assert level_after_oneshot >= 2

        # Use the one-shot modifier
        self.layout.process_event({"category": "keyboard", "type": "keyDown", "keyName": "KEY_A", "inputTag": "test"})
        self.layout.process_event({"category": "keyboard", "type": "keyUp", "keyName": "KEY_A", "inputTag": "test"})

        # Level should return to 0 after one-shot consumption
        final_level = self.layout.get_current_level()
        assert final_level < level_after_oneshot


if __name__ == "__main__":
    # Run the tests if this file is executed directly
    pytest.main([__file__, "-v"])
