#!/usr/bin/env python3
"""
KeyboardLayout1 - A modern keyboard layout system with levels instead of layers.

This module provides a comprehensive keyboard layout system with features similar to
QMK and Kanata but with a different conceptual model based on numerical levels
that can be combined additively.
"""

import logging
import time
from typing import Dict, List, Union, Optional, Callable, Any
from dataclasses import dataclass, field
from enum import Enum


logger = logging.getLogger(__name__)


class ModifierStyle(Enum):
    """Styles for modifier key behavior."""
    MOMENTARY = "momentary"
    MOMENTARY_WITH_LATCH = "momentary_with_latch"
    ONE_SHOT = "one_shot"
    LOCK = "lock"


@dataclass
class SpecialKey:
    """Binding for special keys like arrows, F-keys, etc."""
    key_name: str
    shifted: bool = False


@dataclass
class CharKey:
    """Binding for character keys."""
    char: str


@dataclass
class Modifier:
    """A modifier key configuration."""
    mod: str  # The modifier key identifier (e.g., "KEY_LEFTCTRL")
    style: ModifierStyle
    is_level_modifier: bool = False
    level_value: int = 0  # For level modifiers, the numeric value to add
    double_press_to_lock: bool = False


@dataclass
class LevelModifier:
    """A level modifier that adds a numeric value to the current level."""
    level_value: int
    style: ModifierStyle = ModifierStyle.MOMENTARY
    double_press_to_lock: bool = False

    def to_modifier(self, key_name: str) -> Modifier:
        """Convert to a Modifier instance for internal use."""
        return Modifier(
            mod=key_name,
            style=self.style,
            is_level_modifier=True,
            level_value=self.level_value,
            double_press_to_lock=self.double_press_to_lock
        )


@dataclass
class TapOrHold:
    """A key that behaves differently when tapped vs held."""
    tap: Union[List[Any], Dict[int, Any], Modifier]  # What happens on tap
    hold: Modifier  # What happens on hold


@dataclass
class HoldSpecificHandleBoth:
    """Handler for specific key combinations in TapOrHoldSpecific."""
    down_handler: Callable[[Dict[str, Any], Dict[str, Any]], List[Dict[str, Any]]]  # (original_event, specific_key_event) -> events
    up_handler: Callable[[Dict[str, Any]], List[Dict[str, Any]]]  # (specific_key_up_event) -> events


@dataclass
class TapOrHoldSpecific:
    """A key that behaves differently when tapped vs held, with specific hold behaviors for certain keys."""
    tap: Union[List[Any], Dict[int, Any], Modifier]  # What happens on tap
    hold: Dict[str, Union[Modifier, HoldSpecificHandleBoth]]  # Mapping of key names to hold behaviors


class PassThrough:
    """Binding that passes through events unchanged."""
    pass


class Fallthrough:
    """Binding that falls through to a lower level's binding."""
    pass


class Ignore:
    """Binding that ignores the key press (same as empty string)."""
    pass


@dataclass
class KeyState:
    """State tracking for a single key."""
    is_pressed: bool = False
    press_time: float = 0.0
    is_tap_or_hold: bool = False
    tap_or_hold_resolved: bool = False
    resolved_as_hold: bool = False
    is_tap_or_hold_specific: bool = False
    tap_or_hold_specific_resolved: bool = False
    pending_specific_keys: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # key_name -> key_event
    active_binding: Any = None  # Store the binding that was used for key down


@dataclass
class ModifierState:
    """State tracking for modifiers."""
    is_active: bool = False
    is_latched: bool = False
    is_locked: bool = False
    is_one_shot: bool = False
    one_shot_used: bool = False
    last_press_time: float = 0.0
    press_count: int = 0
    level_value: int = 0  # For level modifiers, the numeric value to add


class KeyboardLayout1:
    """
    A modern keyboard layout system with numerical levels instead of layers.

    Features:
    - Level-based system where levels combine additively
    - Two types of modifiers: ControlModifiers (send events) and LevelModifiers (internal)
    - TapOrHold keys for context-sensitive behavior
    - Multiple binding types: SpecialKey, CharKey, strings, functions, PassThrough
    - Configurable handling of unbound events
    """

    def __init__(self, layout_dict: Dict[str, Any],
                 unbound_handler: str = "pass_through",
                 unbound_handler_func: Optional[Callable] = None,
                 name: str = "",
                 delayed_eval: bool = False):
        """
        Initialize the keyboard layout.

        Args:
            layout_dict: Dictionary mapping key names to bindings
            unbound_handler: How to handle unbound events - "drop", "pass_through", or "function"
            unbound_handler_func: Custom function for handling unbound events (if unbound_handler="function")
            name: Name of the keyboard layout
            delayed_eval: When True, send delayed evaluation events instead of immediate key events
        """
        self.name = name
        self.unbound_handler = unbound_handler
        self.unbound_handler_func = unbound_handler_func
        self.delayed_eval = delayed_eval

        # Normalize the layout dictionary
        self.layout = self._normalize_layout(layout_dict)

        # State tracking
        self.key_states: Dict[str, KeyState] = {}
        self.control_modifier_states: Dict[str, ModifierState] = {}
        self.level_modifier_states: Dict[str, ModifierState] = {}
        self.consumed_by_tap_or_hold_specific: Dict[str, str] = {}  # consumed_key -> tap_or_hold_key

        # Timing configuration
        self.tap_or_hold_timeout = 0.2  # 200ms threshold for tap vs hold
        self.double_press_timeout = 0.3  # 300ms threshold for double press

    def _normalize_layout(self, layout_dict: Dict[str, Any]) -> Dict[str, Dict[int, Any]]:
        """
        Normalize the layout dictionary to canonical form.
        Converts lists to dictionaries with integer keys.
        Converts LevelModifier instances to Modifier instances.
        Marks single bindings for all-levels behavior.
        """
        normalized = {}

        for key_name, binding in layout_dict.items():
            if isinstance(binding, list):
                # Convert list to dictionary with indices as keys
                normalized_binding = {}
                for i, item in enumerate(binding):
                    if isinstance(item, LevelModifier):
                        normalized_binding[i] = item.to_modifier(key_name)
                    else:
                        normalized_binding[i] = item
                normalized[key_name] = normalized_binding
            elif isinstance(binding, dict):
                # Already a dictionary, ensure integer keys and convert LevelModifiers
                normalized_binding = {}
                for k, v in binding.items():
                    if k == "__all_levels__":
                        # Preserve special markers
                        normalized_binding[k] = v
                    elif isinstance(v, LevelModifier):
                        normalized_binding[int(k)] = v.to_modifier(key_name)
                    else:
                        normalized_binding[int(k)] = v
                normalized[key_name] = normalized_binding
            else:
                # Single binding - mark for all-levels behavior
                if isinstance(binding, LevelModifier):
                    # Store with special marker for all-levels behavior
                    normalized[key_name] = {"__all_levels__": True, 0: binding.to_modifier(key_name)}
                else:
                    # Store with special marker for all-levels behavior
                    normalized[key_name] = {"__all_levels__": True, 0: binding}

        return normalized

    def merge_layout(self, other: Union[Dict[str, Any], 'KeyboardLayout1']) -> 'KeyboardLayout1':
        """
        Create a new KeyboardLayout1 by merging with another layout.
        This is a functional update that doesn't mutate either input.

        Args:
            other: Either a dictionary of key bindings or a KeyboardLayout1 instance

        Returns:
            A new KeyboardLayout1 instance with merged bindings
        """
        merged_dict = {}

        # Start with our layout
        for key_name, levels in self.layout.items():
            merged_dict[key_name] = levels.copy()

        # Normalize the other layout if it's a dictionary
        if isinstance(other, dict):
            other_layout = self._normalize_layout(other)
        else:
            other_layout = other.layout

        # Add/override with other layout
        for key_name, levels in other_layout.items():
            if key_name in merged_dict:
                # Merge the level dictionaries
                merged_dict[key_name].update(levels)
            else:
                merged_dict[key_name] = levels.copy()

        return KeyboardLayout1(
            layout_dict=merged_dict,
            unbound_handler=self.unbound_handler,
            unbound_handler_func=self.unbound_handler_func,
            name=self.name,
            delayed_eval=self.delayed_eval
        )

    def getName(self) -> str:
        """Get the name of this keyboard layout."""
        return self.name

    def get_layout(self) -> Dict[str, Dict[int, Any]]:
        """Get the current layout dictionary."""
        return self.layout.copy()

    def set_layout(self, layout_dict: Dict[str, Any]):
        """Set a new layout dictionary."""
        self.layout = self._normalize_layout(layout_dict)
        # Clear state when layout changes
        self.key_states.clear()
        self.control_modifier_states.clear()
        self.level_modifier_states.clear()
        self.consumed_by_tap_or_hold_specific.clear()

    def clear_state(self):
        """Clear all keyboard state (for testing)."""
        self.key_states.clear()
        self.control_modifier_states.clear()
        self.level_modifier_states.clear()
        self.consumed_by_tap_or_hold_specific.clear()

    def get_current_level(self) -> int:
        """Calculate the current level based on active level modifiers."""
        level = 0
        for mod_name, state in self.level_modifier_states.items():
            if state.is_active or state.is_latched or state.is_locked or (state.is_one_shot and not state.one_shot_used):
                level += state.level_value
        return level

    def get_modifier_states(self) -> Dict[str, Dict[str, bool]]:
        """Get current state of all modifiers for status reporting."""
        control_states = {
            mod: {
                "active": state.is_active,
                "latched": state.is_latched,
                "locked": state.is_locked,
                "one_shot": state.is_one_shot and not state.one_shot_used
            }
            for mod, state in self.control_modifier_states.items()
        }

        level_states = {
            mod: {
                "active": state.is_active,
                "latched": state.is_latched,
                "locked": state.is_locked,
                "one_shot": state.is_one_shot and not state.one_shot_used
            }
            for mod, state in self.level_modifier_states.items()
        }

        return {
            "control_modifiers": control_states,
            "level_modifiers": level_states,
            "current_level": self.get_current_level()
        }

    def process_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a list of input events and return all accumulated output events.

        Args:
            events: List of input events to process

        Returns:
            List of all output events from processing the input events
        """
        output_events = []
        for event in events:
            result = self.process_event(event)
            output_events.extend(result)
        return output_events

    def process_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Process an input event and return a list of output events.

        Handles eventList events recursively and processes keyboard/mouse events
        according to the current layout and level.
        """
        # Handle eventList events recursively
        if event.get("type") == "eventList":
            result_events = []
            for sub_event in event.get("events", []):
                result_events.extend(self.process_event(sub_event))
            return result_events

        # Only process keyboard and mouse button events
        if event.get("category") not in ["keyboard", "mouse"]:
            return [event]

        # For mouse events, only handle button events (mouseDown/mouseUp)
        if event.get("category") == "mouse" and event.get("type", "") not in ["mouseDown", "mouseUp"]:
            return [event]

        key_name = event.get("keyName", "")
        event_type = event.get("type", "")

        # For mouse button events, normalize the key name and event type for internal processing
        if event.get("category") == "mouse" and event_type in ["mouseDown", "mouseUp"]:
            if not key_name and "button" in event:
                # Convert button field to a keyName format for consistency
                button = event.get("button")
                key_name = f"BTN_{button.upper()}"

            # Convert mouse button event types to the internal format expected by the rest of the code
            if event_type == "mouseDown":
                event_type = "buttonDown"
            elif event_type == "mouseUp":
                event_type = "buttonUp"

        if not key_name:
            return self._handle_unbound_event(event)

        # Check if this key was consumed by a TapOrHoldSpecific
        if key_name in self.consumed_by_tap_or_hold_specific:
            if event_type == "keyUp" or event_type == "buttonUp":
                # Handle the key up for consumed keys
                return self._handle_consumed_key_up(key_name, event)
            else:
                # Key down was already handled when it was consumed
                return []

        # Initialize key state if needed
        if key_name not in self.key_states:
            self.key_states[key_name] = KeyState()

        key_state = self.key_states[key_name]

        if event_type == "keyDown" or event_type == "buttonDown":
            return self._handle_key_down(key_name, event, key_state)
        elif event_type == "keyUp" or event_type == "buttonUp":
            return self._handle_key_up(key_name, event, key_state)
        else:
            return self._handle_unbound_event(event)

    def _handle_key_down(self, key_name: str, event: Dict[str, Any], key_state: KeyState) -> List[Dict[str, Any]]:
        """Handle key down events."""
        if key_state.is_pressed:
            # Key repeat - ignore for now
            return []

        key_state.is_pressed = True
        key_state.press_time = time.time()

        # Check if this key triggers any TapOrHoldSpecific behaviors
        specific_trigger_events = self._check_for_tap_or_hold_specific_trigger(key_name, event)

        # If this key was consumed by a TapOrHoldSpecific, don't process it normally
        if key_name in self.consumed_by_tap_or_hold_specific:
            return specific_trigger_events

        # Check if this key has any bindings
        if key_name not in self.layout:
            # Consume one-shot modifiers even for unbound keys
            self._consume_one_shot_modifiers()
            unbound_events = self._handle_unbound_event(event)
            return specific_trigger_events + unbound_events

        current_level = self.get_current_level()
        levels = self.layout[key_name]

        # Find the binding for the current level, handling fallthrough
        binding = self._resolve_binding(levels, current_level)

        if binding is None:
            # No binding for this level - key does nothing
            return []

        # Consume one-shot modifiers when a non-modifier key is pressed
        self._consume_one_shot_modifiers()

        # Store the binding that was used for this key down
        key_state.active_binding = binding
        # Handle different binding types
        output_events = []
        if isinstance(binding, TapOrHoldSpecific):
            output_events.extend(self._handle_tap_or_hold_specific_down(key_name, event, key_state, binding))
        elif isinstance(binding, TapOrHold):
            output_events.extend(self._handle_tap_or_hold_down(key_name, event, key_state, binding))
        elif isinstance(binding, Modifier):
            output_events.extend(self._handle_modifier_down(key_name, event, binding))
        elif isinstance(binding, PassThrough):
            output_events.extend([event])
        else:
            # Regular binding (SpecialKey, CharKey, string, or function pair)
            output_events.extend(self._handle_regular_binding_down(binding, event))

        # Add any TapOrHoldSpecific trigger events
        output_events.extend(specific_trigger_events)

        return output_events

    def _handle_key_up(self, key_name: str, event: Dict[str, Any], key_state: KeyState) -> List[Dict[str, Any]]:
        """Handle key up events."""
        if not key_state.is_pressed:
            return []

        key_state.is_pressed = False

        # Check if this keyUp should trigger any TapOrHoldSpecific keys to resolve as tap
        tap_trigger_events = self._check_for_tap_or_hold_specific_trigger_on_key_up(key_name, event)

        # Check if this key has any bindings
        if key_name not in self.layout:
            unbound_events = self._handle_unbound_event(event)
            return tap_trigger_events + unbound_events

        # Use the binding that was stored during key down
        if hasattr(key_state, "active_binding") and key_state.active_binding is not None:
            binding = key_state.active_binding
        else:
            # Fallback to re-resolving if no stored binding (shouldn't normally happen)
            current_level = self.get_current_level()
            levels = self.layout[key_name]
            binding = self._resolve_binding(levels, current_level)
        if binding is None:
            # No binding for this level - key does nothing
            return tap_trigger_events

        # Handle different binding types and clear the stored binding
        result = []
        if isinstance(binding, TapOrHoldSpecific):
            result = self._handle_tap_or_hold_specific_up(key_name, event, key_state, binding)
        elif isinstance(binding, TapOrHold):
            result = self._handle_tap_or_hold_up(key_name, event, key_state, binding)
        elif isinstance(binding, Modifier):
            result = self._handle_modifier_up(key_name, event, binding)
        elif isinstance(binding, PassThrough):
            result = [event]
        else:
            # Regular binding (SpecialKey, CharKey, string, or function pair)
            result = self._handle_regular_binding_up(binding, event)

        # Clear the stored binding after processing
        key_state.active_binding = None
        return tap_trigger_events + result

    def _handle_tap_or_hold_down(self, key_name: str, event: Dict[str, Any],
                                key_state: KeyState, binding: TapOrHold) -> List[Dict[str, Any]]:
        """Handle key down for TapOrHold bindings."""
        key_state.is_tap_or_hold = True
        key_state.tap_or_hold_resolved = False

        # Check if another key gets pressed before timeout to determine hold
        # For now, we'll defer the decision until key up or another key press
        return []

    def _handle_tap_or_hold_up(self, key_name: str, event: Dict[str, Any],
                              key_state: KeyState, binding: TapOrHold) -> List[Dict[str, Any]]:
        """Handle key up for TapOrHold bindings."""
        if not key_state.is_tap_or_hold:
            return []

        elapsed = time.time() - key_state.press_time

        if not key_state.tap_or_hold_resolved:
            # No other key was pressed, treat as tap
            key_state.tap_or_hold_resolved = True
            key_state.resolved_as_hold = False

            # Process the tap binding
            return self._process_tap_binding(binding.tap, event)
        elif key_state.resolved_as_hold:
            # Was resolved as hold, send modifier up
            if isinstance(binding.hold, Modifier):
                return self._handle_modifier_up(binding.hold.mod, event, binding.hold)

        return []

    def _process_tap_binding(self, tap_binding: Union[List[Any], Dict[int, Any], Modifier],
                           event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Process a tap binding from TapOrHold."""
        if isinstance(tap_binding, Modifier):
            # Tap is a modifier action (latch, one-shot, lock)
            return self._handle_modifier_tap(tap_binding, event)
        elif isinstance(tap_binding, list):
            # Process each item in the list
            output_events = []
            for item in tap_binding:
                down_events = self._handle_regular_binding_down(item, event)
                up_events = self._handle_regular_binding_up(item, event)
                output_events.extend(down_events + up_events)
            return output_events
        elif isinstance(tap_binding, PassThrough):
            # PassThrough tap: generate both down and up events for the original key
            key_name = event.get("keyName", "")
            return [
                self._create_output_event(event, "keyDown", key_name),
                self._create_output_event(event, "keyUp", key_name)
            ]
        else:
            # Tap is a regular binding, simulate key down and up
            down_events = self._handle_regular_binding_down(tap_binding, event)
            up_events = self._handle_regular_binding_up(tap_binding, event)
            return down_events + up_events

    def _handle_tap_or_hold_specific_down(self, key_name: str, event: Dict[str, Any],
                                        key_state: KeyState, binding: TapOrHoldSpecific) -> List[Dict[str, Any]]:
        """Handle key down for TapOrHoldSpecific bindings."""
        key_state.is_tap_or_hold_specific = True
        key_state.tap_or_hold_specific_resolved = False
        key_state.pending_specific_keys.clear()

        # Check if any other keys are currently pressed to determine potential hold behavior
        # For now, we'll defer the decision until another key is pressed or key up
        return []

    def _handle_tap_or_hold_specific_up(self, key_name: str, event: Dict[str, Any],
                                      key_state: KeyState, binding: TapOrHoldSpecific) -> List[Dict[str, Any]]:
        """Handle key up for TapOrHoldSpecific bindings."""
        if not key_state.is_tap_or_hold_specific:
            return []

        if not key_state.tap_or_hold_specific_resolved:
            # No specific key was pressed, treat as tap
            key_state.tap_or_hold_specific_resolved = True

            # Process the tap binding
            return self._process_tap_binding(binding.tap, event)
        else:
            # Was resolved as hold, handle up events for any remaining specific keys
            output_events = []

            # Only handle up events for keys that are still marked as consumed
            # (i.e., haven't been released yet)
            remaining_specific_keys = {}
            for specific_key, specific_event in key_state.pending_specific_keys.items():
                if specific_key in self.consumed_by_tap_or_hold_specific:
                    remaining_specific_keys[specific_key] = specific_event

            for specific_key, specific_event in remaining_specific_keys.items():
                if specific_key in binding.hold:
                    hold_binding = binding.hold[specific_key]
                    if isinstance(hold_binding, HoldSpecificHandleBoth):
                        # Call the up handler
                        up_event = {
                            "category": specific_event.get("category", "keyboard"),
                            "type": "keyUp",
                            "keyName": specific_key,
                            "inputTag": specific_event.get("inputTag", "layout")
                        }
                        result = hold_binding.up_handler(up_event)
                        output_events.extend(result if isinstance(result, list) else [result] if result else [])
                    elif isinstance(hold_binding, Modifier):
                        # Send modifier up
                        output_events.extend(self._handle_modifier_up(hold_binding.mod, event, hold_binding))
                    elif isinstance(hold_binding, LevelModifier):
                        # Convert LevelModifier to Modifier and send modifier up
                        modifier = hold_binding.to_modifier(specific_key)
                        output_events.extend(self._handle_modifier_up(modifier.mod, event, modifier))

            # Clean up consumed keys
            for consumed_key in list(self.consumed_by_tap_or_hold_specific.keys()):
                if self.consumed_by_tap_or_hold_specific[consumed_key] == key_name:
                    del self.consumed_by_tap_or_hold_specific[consumed_key]

            key_state.pending_specific_keys.clear()

        # Reset TapOrHoldSpecific state for future activations
        key_state.tap_or_hold_specific_resolved = False
        return output_events

    def _check_for_tap_or_hold_specific_trigger(self, trigger_key_name: str, trigger_event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check if any TapOrHoldSpecific keys should be triggered by this key press."""
        output_events = []

        for key_name, key_state in self.key_states.items():
            if (key_state.is_tap_or_hold_specific and
                not key_state.tap_or_hold_specific_resolved and
                key_state.is_pressed and
                key_name != trigger_key_name):  # Don't resolve a key's own TapOrHoldSpecific

                # Find the binding for this TapOrHoldSpecific key
                if key_name not in self.layout:
                    continue

                current_level = self.get_current_level()
                levels = self.layout[key_name]
                binding = self._resolve_binding(levels, current_level)

                if not isinstance(binding, TapOrHoldSpecific):
                    continue

                if trigger_key_name in binding.hold:
                    # This is a specific key for this TapOrHoldSpecific
                    key_state.tap_or_hold_specific_resolved = True
                    key_state.pending_specific_keys[trigger_key_name] = trigger_event

                    # Mark this key as consumed by the TapOrHoldSpecific
                    self.consumed_by_tap_or_hold_specific[trigger_key_name] = key_name

                    hold_binding = binding.hold[trigger_key_name]

                    if isinstance(hold_binding, HoldSpecificHandleBoth):
                        # Call the down handler with both events
                        original_event = {
                            "category": "keyboard",
                            "type": "keyDown",
                            "keyName": key_name,
                            "inputTag": trigger_event.get("inputTag", "layout")
                        }
                        result = hold_binding.down_handler(original_event, trigger_event)
                        output_events.extend(result if isinstance(result, list) else [result] if result else [])
                    elif isinstance(hold_binding, Modifier):
                        # Activate the modifier
                        output_events.extend(self._handle_modifier_down(hold_binding.mod, trigger_event, hold_binding))
                    elif isinstance(hold_binding, LevelModifier):
                        # Convert LevelModifier to Modifier and activate it
                        modifier = hold_binding.to_modifier(trigger_key_name)
                        output_events.extend(self._handle_modifier_down(modifier.mod, trigger_event, modifier))

                    # This trigger key should not be processed normally
                    return output_events

                else:
                    # This is not a specific key, so immediately send the tap binding
                    key_state.tap_or_hold_specific_resolved = True

                    # Process the tap binding
                    # Create a synthetic event for the TapOrHoldSpecific key
                    # We need to determine if this was originally a mouse or keyboard event
                    synthetic_event = {
                        "keyName": key_name,
                        "inputTag": trigger_event.get("inputTag", "layout")
                    }
                    # If the key_name looks like a mouse button, create a mouse event
                    if key_name.startswith("BTN_"):
                        synthetic_event["category"] = "mouse"
                        synthetic_event["button"] = key_name[4:].lower()
                        synthetic_event["type"] = "mouseDown"
                    else:
                        synthetic_event["category"] = "keyboard"
                        synthetic_event["type"] = "keyDown"
                    original_event = synthetic_event
                    tap_events = self._process_tap_binding(binding.tap, original_event)
                    output_events.extend(tap_events)

        # If we processed any TapOrHoldSpecific triggers but the trigger key was not consumed,
        # we should continue processing it normally by returning an empty list here
        # The key will then be processed normally after this check
        return output_events

    def _check_for_tap_or_hold_specific_trigger_on_key_up(self, trigger_key_name: str, trigger_event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Check if any TapOrHoldSpecific keys should be triggered to tap by this key release."""
        output_events = []

        for key_name, key_state in self.key_states.items():
            if (key_state.is_tap_or_hold_specific and
                not key_state.tap_or_hold_specific_resolved and
                key_state.is_pressed and
                key_name != trigger_key_name):  # Don't resolve a key's own TapOrHoldSpecific

                # Find the binding for this TapOrHoldSpecific key
                if key_name not in self.layout:
                    continue

                current_level = self.get_current_level()
                levels = self.layout[key_name]
                binding = self._resolve_binding(levels, current_level)

                if not isinstance(binding, TapOrHoldSpecific):
                    continue

                # Check if the released key is NOT a specific hold key
                if trigger_key_name not in binding.hold:
                    # This is an unrelated key being released, so trigger tap
                    key_state.tap_or_hold_specific_resolved = True

                    # Process the tap binding
                    # Create a synthetic event for the TapOrHoldSpecific key
                    synthetic_event = {
                        "keyName": key_name,
                        "inputTag": trigger_event.get("inputTag", "layout")
                    }
                    # If the key_name looks like a mouse button, create a mouse event
                    if key_name.startswith("BTN_"):
                        synthetic_event["category"] = "mouse"
                        synthetic_event["button"] = key_name[4:].lower()
                        synthetic_event["type"] = "mouseDown"
                    else:
                        synthetic_event["category"] = "keyboard"
                        synthetic_event["type"] = "keyDown"
                    original_event = synthetic_event
                    tap_events = self._process_tap_binding(binding.tap, original_event)
                    output_events.extend(tap_events)

        return output_events

    def _handle_consumed_key_up(self, key_name: str, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle key up for keys that were consumed by TapOrHoldSpecific."""
        if key_name not in self.consumed_by_tap_or_hold_specific:
            return []

        tap_or_hold_key = self.consumed_by_tap_or_hold_specific[key_name]

        # Find the TapOrHoldSpecific binding
        if tap_or_hold_key not in self.layout:
            # Clean up and return
            del self.consumed_by_tap_or_hold_specific[key_name]
            return []

        current_level = self.get_current_level()
        levels = self.layout[tap_or_hold_key]
        binding = self._resolve_binding(levels, current_level)

        if not isinstance(binding, TapOrHoldSpecific):
            # Clean up and return
            del self.consumed_by_tap_or_hold_specific[key_name]
            return []

        if key_name not in binding.hold:
            # Clean up and return
            del self.consumed_by_tap_or_hold_specific[key_name]
            return []

        hold_binding = binding.hold[key_name]
        output_events = []

        if isinstance(hold_binding, HoldSpecificHandleBoth):
            # Call the up handler
            result = hold_binding.up_handler(event)
            output_events.extend(result if isinstance(result, list) else [result] if result else [])
        elif isinstance(hold_binding, Modifier):
            # Send modifier up
            output_events.extend(self._handle_modifier_up(hold_binding.mod, event, hold_binding))
        elif isinstance(hold_binding, LevelModifier):
            # Convert LevelModifier to Modifier and send modifier up
            modifier = hold_binding.to_modifier(key_name)
            output_events.extend(self._handle_modifier_up(modifier.mod, event, modifier))

        # Clean up
        del self.consumed_by_tap_or_hold_specific[key_name]

        # Reset the key state for the consumed key
        if key_name in self.key_states:
            self.key_states[key_name].is_pressed = False

        return output_events

    def _handle_modifier_down(self, key_name: str, event: Dict[str, Any], modifier: Modifier) -> List[Dict[str, Any]]:
        """Handle modifier key down events."""
        if modifier.is_level_modifier:
            # Handle level modifiers
            if modifier.mod not in self.level_modifier_states:
                self.level_modifier_states[modifier.mod] = ModifierState()

            state = self.level_modifier_states[modifier.mod]
            state.level_value = modifier.level_value  # Store the level value
            current_time = time.time()

            if modifier.style == ModifierStyle.MOMENTARY:
                state.is_active = True
                return []  # Level modifiers don't send events

            elif modifier.style == ModifierStyle.ONE_SHOT:
                state.is_one_shot = True
                state.one_shot_used = False
                return []

            elif modifier.style == ModifierStyle.LOCK:
                # Toggle lock state
                state.is_locked = not state.is_locked
                return []

            elif modifier.style == ModifierStyle.MOMENTARY_WITH_LATCH:
                # Check for double press
                if (current_time - state.last_press_time) < self.double_press_timeout:
                    state.press_count += 1
                else:
                    state.press_count = 1

                state.last_press_time = current_time

                if state.press_count >= 2 and modifier.double_press_to_lock:
                    state.is_locked = not state.is_locked
                else:
                    state.is_active = True
                return []

        else:
            # Handle control modifiers
            if modifier.mod not in self.control_modifier_states:
                self.control_modifier_states[modifier.mod] = ModifierState()

            state = self.control_modifier_states[modifier.mod]
            current_time = time.time()

            if modifier.style == ModifierStyle.MOMENTARY:
                state.is_active = True
                # Send the control modifier key down event immediately
                return [self._create_output_event(event, "keyDown", modifier.mod)]

            elif modifier.style == ModifierStyle.ONE_SHOT:
                state.is_one_shot = True
                state.one_shot_used = False
                # Send the control modifier key down event
                return [self._create_output_event(event, "keyDown", modifier.mod)]

            elif modifier.style == ModifierStyle.LOCK:
                # Toggle lock state and send corresponding event
                state.is_locked = not state.is_locked
                if state.is_locked:
                    return [self._create_output_event(event, "keyDown", modifier.mod)]
                else:
                    return [self._create_output_event(event, "keyUp", modifier.mod)]

            # Handle other styles...
            return []

    def _handle_modifier_up(self, key_name: str, event: Dict[str, Any], modifier: Modifier) -> List[Dict[str, Any]]:
        """Handle modifier key up events."""
        if modifier.is_level_modifier:
            if modifier.mod in self.level_modifier_states:
                state = self.level_modifier_states[modifier.mod]

                if modifier.style == ModifierStyle.MOMENTARY:
                    state.is_active = False
                elif modifier.style == ModifierStyle.MOMENTARY_WITH_LATCH:
                    if not state.is_locked:
                        # Check if we should latch (no other keys were pressed)
                        state.is_latched = True  # Simplified logic for now
                        state.is_active = False
                elif modifier.style == ModifierStyle.ONE_SHOT:
                    if state.one_shot_used:
                        state.is_one_shot = False
                        state.one_shot_used = False
            return []  # Level modifiers don't send key up events

        else:
            # Handle control modifiers
            if modifier.mod in self.control_modifier_states:
                state = self.control_modifier_states[modifier.mod]

                if modifier.style == ModifierStyle.MOMENTARY:
                    state.is_active = False
                    # Send the control modifier key up event
                    return [self._create_output_event(event, "keyUp", modifier.mod)]
                elif modifier.style == ModifierStyle.ONE_SHOT:
                    if state.one_shot_used:
                        state.is_one_shot = False
                        return [self._create_output_event(event, "keyUp", modifier.mod)]
            return []

    def _handle_modifier_tap(self, modifier: Modifier, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle modifier tap events."""
        if modifier.is_level_modifier:
            if modifier.mod not in self.level_modifier_states:
                self.level_modifier_states[modifier.mod] = ModifierState()

            state = self.level_modifier_states[modifier.mod]

            if modifier.style == ModifierStyle.ONE_SHOT:
                state.is_one_shot = True
                state.one_shot_used = False
            elif modifier.style == ModifierStyle.LOCK:
                state.is_locked = not state.is_locked
            elif modifier.style == ModifierStyle.MOMENTARY_WITH_LATCH:
                state.is_latched = not state.is_latched

            return []  # Level modifiers don't send events

        else:
            # Handle control modifier tap
            if modifier.style == ModifierStyle.ONE_SHOT:
                return [
                    self._create_output_event(event, "keyDown", modifier.mod),
                    self._create_output_event(event, "keyUp", modifier.mod)
                ]
            # Add other tap behaviors as needed
            return []

    def _handle_regular_binding_down(self, binding: Any, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle key down for regular bindings."""
        if isinstance(binding, SpecialKey):
            # Create delayed event
            delayed = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_down",
                "key_name": binding.key_name,
                "shifted": binding.shifted,
                "inputTag": event.get("inputTag", "layout")
            }]
            if not self.delayed_eval:
                return KeyboardLayout1.handle_delayed(delayed)
            else:
                return delayed

        elif isinstance(binding, CharKey):
            # Create delayed event
            delayed = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_down",
                "char_key": binding.char,
                "inputTag": event.get("inputTag", "layout")
            }]
            if not self.delayed_eval:
                return KeyboardLayout1.handle_delayed(delayed)
            else:
                return delayed

        elif isinstance(binding, str):
            # String binding - ignore empty strings
            if binding == "":
                return []  # Empty string is treated as ignore

            # Create delayed event
            delayed = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_down",
                "string": binding,
                "inputTag": event.get("inputTag", "layout")
            }]
            if not self.delayed_eval:
                return KeyboardLayout1.handle_delayed(delayed)
            else:
                return delayed

        elif isinstance(binding, tuple) and len(binding) == 2 and callable(binding[0]):
            # Function pair - call the down function
            try:
                result = binding[0](event)
                return result if isinstance(result, list) else [result] if result else []
            except Exception as e:
                logger.error(f"Error in key down function: {e}")
                return []

        elif isinstance(binding, PassThrough):
            # PassThrough - return the original event unchanged
            return [event]

        return []

    def _create_output_event(self, original_event: Dict[str, Any], event_type: str, key_name: str = None) -> Dict[str, Any]:
        """Create an output event based on the original event format and target key."""
        # Determine output format based on the target key_name, not the original event
        # If key_name starts with BTN_, it's a mouse button output
        # Otherwise, it's a keyboard output

        if key_name and key_name.startswith("BTN_"):
            # Output should be a mouse button event
            # Convert internal button event types back to mouse event types
            if event_type == "buttonDown":
                mouse_event_type = "mouseDown"
            elif event_type == "buttonUp":
                mouse_event_type = "mouseUp"
            else:
                mouse_event_type = event_type

            result_event = {
                "category": "mouse",
                "type": mouse_event_type,
                "inputTag": original_event.get("inputTag", "layout")
            }

            # Extract button name from BTN_ format
            button_name = key_name[4:].lower()  # Remove BTN_ prefix and lowercase
            result_event["button"] = button_name

            return result_event
        else:
            # Output should be a keyboard event
            return {
                "category": "keyboard",
                "type": event_type,
                "keyName": key_name or original_event.get("keyName", ""),
                "inputTag": original_event.get("inputTag", "layout")
            }

    def _handle_regular_binding_up(self, binding: Any, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle key up for regular bindings."""
        if isinstance(binding, SpecialKey):
            # Create delayed event
            delayed = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_up",
                "key_name": binding.key_name,
                "shifted": binding.shifted,
                "inputTag": event.get("inputTag", "layout")
            }]
            if not self.delayed_eval:
                return KeyboardLayout1.handle_delayed(delayed)
            else:
                return delayed

        elif isinstance(binding, CharKey):
            # Create delayed event
            delayed = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_up",
                "char_key": binding.char,
                "inputTag": event.get("inputTag", "layout")
            }]
            if not self.delayed_eval:
                return KeyboardLayout1.handle_delayed(delayed)
            else:
                return delayed

        elif isinstance(binding, str):
            # String binding - ignore empty strings
            if binding == "":
                return []  # Empty string is treated as ignore

            # Create delayed event
            delayed = [{
                "category": "keyboardLayout1Delayed",
                "event_type": "key_up",
                "string": binding,
                "inputTag": event.get("inputTag", "layout")
            }]
            if not self.delayed_eval:
                return KeyboardLayout1.handle_delayed(delayed)
            else:
                return delayed

        elif isinstance(binding, tuple) and len(binding) == 2 and callable(binding[1]):
            # Function pair - call the up function
            try:
                result = binding[1](event)
                return result if isinstance(result, list) else [result] if result else []
            except Exception as e:
                logger.error(f"Error in key up function: {e}")
                return []

        elif isinstance(binding, PassThrough):
            # PassThrough - return the original event unchanged
            return [event]

        return []

    def _handle_unbound_event(self, event: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Handle events for keys that don't have bindings."""
        if self.unbound_handler == "drop":
            return []
        elif self.unbound_handler == "pass_through":
            return [event]
        elif self.unbound_handler == "function" and self.unbound_handler_func:
            try:
                result = self.unbound_handler_func(event)
                return result if isinstance(result, list) else [result] if result else []
            except Exception as e:
                logger.error(f"Error in unbound handler function: {e}")
                return [event]  # Fall back to pass through
        else:
            return [event]

    def _consume_one_shot_modifiers(self):
        """Mark one-shot modifiers as used when a non-modifier key is pressed."""
        for state in self.level_modifier_states.values():
            if state.is_one_shot and not state.one_shot_used:
                state.one_shot_used = True

        for state in self.control_modifier_states.values():
            if state.is_one_shot and not state.one_shot_used:
                state.one_shot_used = True

    def _resolve_binding(self, levels: Dict[int, Any], current_level: int) -> Any:
        """
        Resolve the binding for a key at the current level, handling fallthrough.

        Args:
            levels: Dictionary of level to binding mappings for a key
            current_level: The current level to resolve

        Returns:
            The resolved binding, or None if no binding found
        """
        # Check if key is marked for all-levels behavior
        if levels.get("__all_levels__", False):
            # Return the binding at level 0, which works for all levels
            return levels.get(0)

        # Check for exact level match first
        if current_level in levels:
            binding = levels[current_level]

            # Handle special bindings
            if isinstance(binding, Fallthrough):
                # Explicit fallthrough - look at lower levels
                for level in range(current_level - 1, -1, -1):
                    if level in levels:
                        binding = levels[level]
                        if isinstance(binding, Fallthrough):
                            continue  # Keep looking at lower levels
                        elif isinstance(binding, Ignore) or binding == "":
                            return None  # Ignore this key press
                        else:
                            return binding
                # No binding found after fallthrough
                return None
            elif isinstance(binding, Ignore) or binding == "":
                return None  # Ignore this key press
            else:
                return binding

        # No binding found at current level
        return None

    @staticmethod
    def handle_delayed(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Handle delayed evaluation events by converting them to normal keyboard events.

        Takes a list of events and returns a list of events where:
        - Events with category "keyboardLayout1Delayed" are expanded to normal keyboard events
        - Other events pass through unchanged
        - Event list events are recursively processed and flattened

        Args:
            events: List of events to process

        Returns:
            Flattened list of events with delayed events expanded
        """
        output_events = []

        for event in events:
            # Handle eventList events recursively
            if event.get("type") == "eventList":
                sub_events = KeyboardLayout1.handle_delayed(event.get("events", []))
                output_events.extend(sub_events)
                continue

            # Handle delayed evaluation events
            if event.get("category") == "keyboardLayout1Delayed":
                event_type = event.get("event_type", "")
                input_tag = event.get("inputTag", "layout")

                # Handle CharKey events
                if "char_key" in event:
                    char = event["char_key"]
                    key_name, needs_shift = KeyboardLayout1._static_char_to_key_name(char)

                    if key_name is None:
                        # Character not representable, skip
                        continue

                    if event_type == "key_down":
                        if needs_shift:
                            output_events.append({
                                "category": "keyboard",
                                "type": "keyDown",
                                "keyName": "KEY_LEFTSHIFT",
                                "inputTag": input_tag
                            })

                        output_events.append({
                            "category": "keyboard",
                            "type": "keyDown",
                            "keyName": key_name,
                            "inputTag": input_tag
                        })

                        if needs_shift:
                            output_events.append({
                                "category": "keyboard",
                                "type": "keyUp",
                                "keyName": "KEY_LEFTSHIFT",
                                "inputTag": input_tag
                            })

                    elif event_type == "key_up":
                        output_events.append({
                            "category": "keyboard",
                            "type": "keyUp",
                            "keyName": key_name,
                            "inputTag": input_tag
                        })

                # Handle string events
                elif "string" in event:
                    string = event["string"]

                    if event_type == "key_down":
                        output_events.append({
                            "category": "keyboard",
                            "type": "typeUnicodeString",
                            "string": string,
                            "inputTag": input_tag
                        })
                    # key_up for strings does nothing in normal mode, so skip

                # Handle SpecialKey events
                elif "key_name" in event:
                    key_name = event["key_name"]
                    shifted = event.get("shifted", False)

                    if event_type == "key_down":
                        if shifted:
                            output_events.append({
                                "category": "keyboard",
                                "type": "keyDown",
                                "keyName": "KEY_LEFTSHIFT",
                                "inputTag": input_tag
                            })

                        output_events.append({
                            "category": "keyboard",
                            "type": "keyDown",
                            "keyName": key_name,
                            "inputTag": input_tag
                        })

                        if shifted:
                            output_events.append({
                                "category": "keyboard",
                                "type": "keyUp",
                                "keyName": "KEY_LEFTSHIFT",
                                "inputTag": input_tag
                            })

                    elif event_type == "key_up":
                        output_events.append({
                            "category": "keyboard",
                            "type": "keyUp",
                            "keyName": key_name,
                            "inputTag": input_tag
                        })
            else:
                # Pass through other events unchanged
                output_events.append(event)

        return output_events

    @staticmethod
    def _static_char_to_key_name(char: str) -> tuple[str, bool]:
        """
        Static version of _char_to_key_name for use in static methods.

        Convert a character to the corresponding US QWERTY keyName and shift requirement.

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
