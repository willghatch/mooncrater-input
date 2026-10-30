"""Keyboard mouse-keys layer driven by the velocity motion engine.

A :class:`MouseKeysLayer` maps physical key names to actions using one of
several named layouts.  While a layout is active, every keyboard event is
consumed: bound keys perform their action and blank keys do nothing.  Other
events pass through.  While inactive, the layer passes everything through,
except the key-ups of keys that were held when mouse mode ended.

Motion is produced on timer ticks: the layer starts its timer (eg. a
``periodic_timer`` input) when a direction is pressed, turns its tick events
into ``mouseRel`` or ``smoothScroll`` events, and stops the timer when the
engine is idle.

``process_events`` returns two lists: the events that pass through (to go on
through the caller's keyboard mapping) and the events the layer generated
(mouse motion, mouse buttons, and modifier keys, which should skip the
keyboard mapping).
"""

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .velocity_mouse import (
    BaseSpeedOperation,
    Direction,
    MotionEngine,
    MotionSample,
    OutputMode,
)


@dataclass(frozen=True)
class Move:
    """Hold a direction."""

    direction: Direction


@dataclass(frozen=True)
class Button:
    """Hold a mouse button: "left", "middle", "right", "back", or "forward"."""

    button: str


@dataclass(frozen=True)
class HoldKey:
    """Hold a keyboard key, eg. a modifier for modified clicks."""

    key_name: str


@dataclass(frozen=True)
class SpeedHold:
    """Hold a named engine speed modifier (in every motion config that defines it)."""

    modifier_name: str


@dataclass(frozen=True)
class AdjustBaseSpeed:
    """Adjust the active motion config's base speed once per press."""

    operation: BaseSpeedOperation
    value: float


@dataclass(frozen=True)
class Dash:
    """Jump `velocity_multiplier` seconds of travel at the current speed."""

    velocity_multiplier: float


@dataclass(frozen=True)
class ToggleScroll:
    """Toggle between pointer motion and scrolling."""


@dataclass(frozen=True)
class HoldScroll:
    """Swap between pointer motion and scrolling while held."""


@dataclass(frozen=True)
class DragLock:
    """Latch the next button pressed until it is pressed again.

    Pressing drag lock again disarms it, or releases latched buttons.
    """


@dataclass(frozen=True)
class SwitchLayout:
    """Switch to another named layout."""

    name: str


@dataclass(frozen=True)
class Exit:
    """Leave mouse mode."""


def sample_to_events(sample: MotionSample, input_tag: str) -> List[dict]:
    """Convert an engine sample to a ``mouseRel`` or ``smoothScroll`` event."""
    kind = "mouseRel" if sample.mode is OutputMode.POINTER else "smoothScroll"
    return [{
        "category": "mouse",
        "type": kind,
        "deltaX": sample.delta_x,
        "deltaY": sample.delta_y,
        "inputTag": input_tag,
    }]


# Marks a held key whose release does nothing (blank keys, consumed button
# presses under drag lock).
_NO_RELEASE = object()


class MouseKeysLayer:
    """Turns physical key events into mouse events while a layout is active.

    Args:
        engine: The motion engine; its state (eg. base speed) persists across
            exits and layout switches.
        layouts: Layout name -> {physical key name -> action}.
        timer: Object with ``start()`` and ``stop()`` that causes tick events
            to arrive, eg. a ``PeriodicTimer``.
        timer_tag: The ``inputTag`` of the timer's tick events.
        clock: Monotonic time source.
        on_change: Called with no arguments after the active layout or the
            pointer/scroll mode changes, eg. to update a status display.
        input_tag: ``inputTag`` for generated events.
    """

    def __init__(
        self,
        engine: MotionEngine,
        layouts: Dict[str, Dict[str, Any]],
        timer=None,
        timer_tag: Optional[str] = None,
        clock: Callable[[], float] = time.monotonic,
        on_change: Optional[Callable[[], None]] = None,
        input_tag: str = "mouseKeys",
    ) -> None:
        self.engine = engine
        self.layouts = layouts
        self.timer = timer
        self.timer_tag = timer_tag
        self.clock = clock
        self.on_change = on_change
        self.input_tag = input_tag
        self.active_layout = None  # type: Optional[str]
        self._held = {}  # type: Dict[str, Any]  # key name -> action pressed with
        self._swallow_up = set()  # keys held through exit
        self._button_counts = {}  # type: Dict[str, int]
        self._key_counts = {}  # type: Dict[str, int]
        self._latched_buttons = set()
        self._drag_armed = False

    @property
    def scrolling(self) -> bool:
        """Whether motion currently scrolls instead of moving the pointer."""
        return self.engine.effective_mode is OutputMode.SCROLL

    def enter(self, layout_name: str) -> None:
        """Activate a layout, or switch to it if mouse mode is already active."""
        if layout_name not in self.layouts:
            raise ValueError("unknown mouse keys layout: {}".format(layout_name))
        self.active_layout = layout_name
        self._changed()

    def exit(self) -> List[dict]:
        """Leave mouse mode, returning events that release held buttons and keys."""
        out = []  # type: List[dict]
        if self.active_layout is None:
            return out
        now = self.clock()
        for key_name, action in list(self._held.items()):
            out.extend(self._release_output(action))
            self._swallow_up.add(key_name)
        self._held.clear()
        for button in sorted(self._latched_buttons):
            out.append(self._button_event("mouseUp", button))
        self._latched_buttons.clear()
        self._drag_armed = False
        self.engine.release_held(now)
        self.engine.set_mode(OutputMode.POINTER, now)
        self._stop_timer()
        self.active_layout = None
        self._changed()
        return out

    def process_events(self, events: List[dict]) -> Tuple[List[dict], List[dict]]:
        """Process events, returning (passed-through events, generated events)."""
        passed = []  # type: List[dict]
        generated = []  # type: List[dict]
        for event in events:
            if self._is_own_tick(event):
                generated.extend(self._tick())
                continue
            if event.get("category") != "keyboard" or "keyName" not in event:
                passed.append(event)
                continue
            key_name = event["keyName"]
            event_type = event.get("type")
            if event_type == "keyUp" and key_name in self._swallow_up:
                self._swallow_up.discard(key_name)
                continue
            if self.active_layout is None:
                passed.append(event)
                continue
            if event_type == "keyDown":
                generated.extend(self._press(key_name))
            elif event_type == "keyUp":
                generated.extend(self._release(key_name))
            # Repeats and other keyboard events are swallowed.
        return passed, generated

    # Event handling

    def _is_own_tick(self, event: dict) -> bool:
        return (
            self.timer_tag is not None
            and event.get("category") == "timer"
            and event.get("inputTag") == self.timer_tag
        )

    def _tick(self) -> List[dict]:
        if self.active_layout is None:
            self._stop_timer()
            return []
        out = []  # type: List[dict]
        sample = self.engine.tick(self.clock())
        if sample is not None:
            out.extend(sample_to_events(sample, self.input_tag))
        if self.engine.is_idle():
            self._stop_timer()
        return out

    def _press(self, key_name: str) -> List[dict]:
        if key_name in self._held:
            return []
        action = self.layouts[self.active_layout].get(key_name)
        now = self.clock()
        out = []  # type: List[dict]
        self._held[key_name] = action
        if action is None:
            self._held[key_name] = _NO_RELEASE
        elif isinstance(action, Move):
            self.engine.press_direction(action.direction, key_name, now)
            self._start_timer()
        elif isinstance(action, Button):
            out.extend(self._press_button(key_name, action.button))
        elif isinstance(action, HoldKey):
            count = self._key_counts.get(action.key_name, 0)
            self._key_counts[action.key_name] = count + 1
            if count == 0:
                out.append(self._key_event("keyDown", action.key_name))
        elif isinstance(action, SpeedHold):
            for config in self._configs_with(action.modifier_name):
                self.engine.press_speed_modifier(config, action.modifier_name, key_name, now)
        elif isinstance(action, AdjustBaseSpeed):
            self.engine.press_base_adjustment(key_name, action.operation, action.value, now)
        elif isinstance(action, Dash):
            sample = self.engine.press_dash(
                key_name, now, velocity_multiplier=action.velocity_multiplier
            )
            if sample is not None:
                out.extend(sample_to_events(sample, self.input_tag))
        elif isinstance(action, ToggleScroll):
            self.engine.toggle_mode(now)
            self._changed()
        elif isinstance(action, HoldScroll):
            self.engine.press_momentary_swap(key_name, now)
            self._changed()
        elif isinstance(action, DragLock):
            if self._latched_buttons:
                for button in sorted(self._latched_buttons):
                    out.append(self._button_event("mouseUp", button))
                self._latched_buttons.clear()
                self._drag_armed = False
            else:
                self._drag_armed = not self._drag_armed
        elif isinstance(action, SwitchLayout):
            self.enter(action.name)
        elif isinstance(action, Exit):
            out.extend(self.exit())
        else:
            raise ValueError("unknown mouse keys action: {!r}".format(action))
        return out

    def _press_button(self, key_name: str, button: str) -> List[dict]:
        if button in self._latched_buttons:
            self._latched_buttons.discard(button)
            self._held[key_name] = _NO_RELEASE
            if self._button_counts.get(button, 0) == 0:
                return [self._button_event("mouseUp", button)]
            return []
        if self._drag_armed:
            self._drag_armed = False
            self._latched_buttons.add(button)
            self._held[key_name] = _NO_RELEASE
            if self._button_counts.get(button, 0) == 0:
                return [self._button_event("mouseDown", button)]
            return []
        count = self._button_counts.get(button, 0)
        self._button_counts[button] = count + 1
        if count == 0:
            return [self._button_event("mouseDown", button)]
        return []

    def _release(self, key_name: str) -> List[dict]:
        if key_name not in self._held:
            # Pressed before mouse mode started; the caller flushed it.
            return []
        action = self._held.pop(key_name)
        now = self.clock()
        out = self._release_output(action)
        if isinstance(action, Move):
            self.engine.release_direction(action.direction, key_name, now)
        elif isinstance(action, SpeedHold):
            for config in self._configs_with(action.modifier_name):
                self.engine.release_speed_modifier(config, action.modifier_name, key_name, now)
        elif isinstance(action, AdjustBaseSpeed):
            self.engine.release_base_adjustment(key_name)
        elif isinstance(action, Dash):
            self.engine.release_dash(key_name)
        elif isinstance(action, HoldScroll):
            self.engine.release_momentary_swap(key_name, now)
            self._changed()
        return out

    def _release_output(self, action) -> List[dict]:
        """Events that releasing `action` sends: button and key ups."""
        if isinstance(action, Button):
            count = self._button_counts.get(action.button, 0) - 1
            if count > 0:
                self._button_counts[action.button] = count
                return []
            self._button_counts.pop(action.button, None)
            if action.button in self._latched_buttons:
                return []
            return [self._button_event("mouseUp", action.button)]
        if isinstance(action, HoldKey):
            count = self._key_counts.get(action.key_name, 0) - 1
            if count > 0:
                self._key_counts[action.key_name] = count
                return []
            self._key_counts.pop(action.key_name, None)
            return [self._key_event("keyUp", action.key_name)]
        return []

    # Helpers

    def _configs_with(self, modifier_name: str):
        configs = []
        for profile in (self.engine.pointer_profile, self.engine.scroll_profile):
            config = profile.motion_config
            if modifier_name in config.modifiers and config not in configs:
                configs.append(config)
        return configs

    def _button_event(self, event_type: str, button: str) -> dict:
        return {"category": "mouse", "type": event_type, "button": button,
                "inputTag": self.input_tag}

    def _key_event(self, event_type: str, key_name: str) -> dict:
        return {"category": "keyboard", "type": event_type, "keyName": key_name,
                "inputTag": self.input_tag}

    def _start_timer(self) -> None:
        if self.timer is not None:
            self.timer.start()

    def _stop_timer(self) -> None:
        if self.timer is not None:
            self.timer.stop()

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()
