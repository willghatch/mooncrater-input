#!/usr/bin/env python3
"""
Generic Mouse Event Accumulator

This module provides a generic accumulator for mouse movement and scroll events
that can be used as a modifier in the event pipeline system.
"""

import logging
import threading
from typing import List, Dict, Any, Optional
from .modifier_pipeline import EventModifier

# Set up logging
logger = logging.getLogger(__name__)


class MouseEventAccumulator(EventModifier):
    """
    Generic mouse event accumulator that can handle both fractional accumulation
    and event coalescing for mouse movements and scroll events.
    """

    def __init__(
        self,
        name: str = "MouseEventAccumulator",
        accumulate_movement: bool = True,
        accumulate_scroll: bool = True,
        accumulate_smooth_scroll: bool = True,
        movement_multiplier=None,
        scroll_multiplier=None,
        max_movement_delta: int = 120,
        emit_fractional_movement: bool = False,
        emit_fractional_scroll: bool = True,
        drop_fractions_on_emit: bool = False,
    ):
        """
        Initialize the mouse event accumulator.

        Args:
            name: Name for this accumulator instance
            accumulate_movement: Whether to accumulate mouse movement events
            accumulate_scroll: Whether to accumulate regular scroll events
            accumulate_smooth_scroll: Whether to accumulate smooth scroll events
            movement_multiplier: Multiplier for relative mouse movement (None = no scaling)
            scroll_multiplier: Multiplier for scroll events (None = no scaling)
            max_movement_delta: Maximum absolute value for accumulated mouse movement before
                              splitting into multiple events (default: 120)
            emit_fractional_movement: If True, emit mouse movement with fractional component
                                     If False, emit only whole units (default: False)
            emit_fractional_scroll: If True, emit scroll events with fractional component as
                                   smoothScroll events. If False, emit only whole units as
                                   regular scroll events (default: True)
            drop_fractions_on_emit: If True, drop fractional parts when emitting instead of
                                   preserving them for the next flush (default: False)
        """
        self.name = name
        self.accumulate_movement = accumulate_movement
        self.accumulate_scroll = accumulate_scroll
        self.accumulate_smooth_scroll = accumulate_smooth_scroll
        self.max_movement_delta = max_movement_delta
        self.emit_fractional_movement = emit_fractional_movement
        self.emit_fractional_scroll = emit_fractional_scroll
        self.drop_fractions_on_emit = drop_fractions_on_emit

        # Multipliers - can be queried and set by user code
        self._movement_multiplier = movement_multiplier
        self._scroll_multiplier = scroll_multiplier

        # Thread-safe accumulators
        self.lock = threading.Lock()
        self.reset_state()

    def get_name(self) -> str:
        """Return the name of this modifier."""
        return self.name

    def get_movement_multiplier(self):
        """Get the current movement multiplier."""
        with self.lock:
            return self._movement_multiplier

    def set_movement_multiplier(self, multiplier):
        """Set the movement multiplier. Use None to disable scaling."""
        with self.lock:
            self._movement_multiplier = multiplier

    def get_scroll_multiplier(self):
        """Get the current scroll multiplier."""
        with self.lock:
            return self._scroll_multiplier

    def set_scroll_multiplier(self, multiplier):
        """Set the scroll multiplier. Use None to disable scaling."""
        with self.lock:
            self._scroll_multiplier = multiplier

    def reset_state(self):
        """Reset all accumulator state."""
        # Mouse movement accumulator (always use floats internally)
        self.mouse_delta_x = 0.0
        self.mouse_delta_y = 0.0
        self.has_mouse_movement = False

        # Scroll accumulator (always use floats internally)
        self.scroll_delta_x = 0.0
        self.scroll_delta_y = 0.0
        self.has_scroll = False

    def process_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process events through the accumulator.

        Args:
            events: List of events to process

        Returns:
            List of processed events with accumulated mouse/scroll events
        """
        if not events:
            return events

        # Separate eventList events from regular events
        eventlist_events = []
        regular_events = []

        for event in events:
            if event.get("type") == "eventList":
                eventlist_events.append(event)
            else:
                regular_events.append(event)

        processed_events = []

        # Process regular events as a batch
        if regular_events:
            processed_events.extend(self._process_single_event_batch(regular_events))

        # Process eventList events recursively
        for event in eventlist_events:
            sub_events = event.get("events", [])
            processed_sub_events = self.process_events(sub_events)
            # Create new eventList with processed sub-events
            processed_event = event.copy()
            processed_event["events"] = processed_sub_events
            processed_events.append(processed_event)

        return processed_events

    def _process_single_event_batch(
        self, events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process a batch of non-eventList events."""
        if not events:
            return events

        with self.lock:
            # Only coalesce consecutive events of the same type to preserve ordering
            return self._coalesce_consecutive_only(events)

    def _coalesce_consecutive_only(
        self, events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Only coalesce consecutive events of the same type to preserve event ordering."""
        if not events:
            return events

        output_events = []
        current_accumulator_events = []

        for event in events:
            if self._should_accumulate_event(event):
                # If this is the same type as what we're currently accumulating, add it
                if not current_accumulator_events or self._events_are_same_type(
                    current_accumulator_events[-1], event
                ):
                    current_accumulator_events.append(event)
                else:
                    # Different type - flush current accumulator and start new one
                    if current_accumulator_events:
                        output_events.extend(
                            self._process_consecutive_batch(current_accumulator_events)
                        )
                    current_accumulator_events = [event]
            else:
                # Non-accumulative event - flush any pending accumulation
                if current_accumulator_events:
                    output_events.extend(
                        self._process_consecutive_batch(current_accumulator_events)
                    )
                    current_accumulator_events = []
                output_events.append(event)

        # Flush any remaining accumulated events
        if current_accumulator_events:
            output_events.extend(
                self._process_consecutive_batch(current_accumulator_events)
            )

        return output_events

    def _events_are_same_type(
        self, event1: Dict[str, Any], event2: Dict[str, Any]
    ) -> bool:
        """Check if two events are the same type for consecutive coalescing."""
        return event1.get("category") == event2.get("category") and event1.get(
            "type"
        ) == event2.get("type")

    def _process_consecutive_batch(
        self, events: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Process a batch of consecutive events of the same type."""
        if not events:
            return []

        # Reset accumulators
        self.reset_state()

        # Accumulate all events
        for event in events:
            self._accumulate_event(event)

        # Return accumulated results
        return self._flush_accumulated_events()

    def _should_accumulate_event(self, event: Dict[str, Any]) -> bool:
        """Check if an event should be accumulated."""
        if event.get("category") != "mouse":
            return False

        event_type = event.get("type")

        if event_type == "mouseRel" and self.accumulate_movement:
            return "deltaX" in event or "deltaY" in event

        if event_type == "scroll" and self.accumulate_scroll:
            return "deltaX" in event or "deltaY" in event

        if event_type == "smoothScroll" and self.accumulate_smooth_scroll:
            return (
                "deltaX" in event
                or "deltaY" in event
                or "rawDeltaX" in event
                or "rawDeltaY" in event
            )

        return False

    def _accumulate_event(self, event: Dict[str, Any]):
        """Accumulate a mouse event into the appropriate accumulator."""
        event_type = event.get("type")

        if event_type == "mouseRel" and self.accumulate_movement:
            delta_x = float(event.get("deltaX", 0))
            delta_y = float(event.get("deltaY", 0))

            # Apply movement multiplier if set
            if self._movement_multiplier is not None and isinstance(
                self._movement_multiplier, (int, float)
            ):
                delta_x = delta_x * self._movement_multiplier
                delta_y = delta_y * self._movement_multiplier

            self.mouse_delta_x += delta_x
            self.mouse_delta_y += delta_y
            self.has_mouse_movement = True

        elif event_type == "scroll" and self.accumulate_scroll:
            delta_x = float(event.get("deltaX", 0))
            delta_y = float(event.get("deltaY", 0))

            # Apply scroll multiplier if set
            if self._scroll_multiplier is not None and isinstance(
                self._scroll_multiplier, (int, float)
            ):
                delta_x = delta_x * self._scroll_multiplier
                delta_y = delta_y * self._scroll_multiplier

            # Always accumulate as floats
            self.scroll_delta_x += delta_x
            self.scroll_delta_y += delta_y
            self.has_scroll = True

        elif event_type == "smoothScroll" and self.accumulate_smooth_scroll:
            # Extract smooth scroll deltas (prioritize deltaX/deltaY over raw values)
            delta_x = event.get("deltaX")
            delta_y = event.get("deltaY")

            # If float values not available, convert from raw values
            if delta_x is None:
                raw_delta_x = event.get("rawDeltaX", 0)
                delta_x = raw_delta_x / 120.0  # Convert evdev units to scroll units
            if delta_y is None:
                raw_delta_y = event.get("rawDeltaY", 0)
                delta_y = raw_delta_y / 120.0

            delta_x = float(delta_x or 0.0)
            delta_y = float(delta_y or 0.0)

            # Apply scroll multiplier if set
            if self._scroll_multiplier is not None and isinstance(
                self._scroll_multiplier, (int, float)
            ):
                delta_x = delta_x * self._scroll_multiplier
                delta_y = delta_y * self._scroll_multiplier

            # Always accumulate as floats
            self.scroll_delta_x += delta_x
            self.scroll_delta_y += delta_y
            self.has_scroll = True

    def _flush_accumulated_events(self) -> List[Dict[str, Any]]:
        """Flush accumulated events and return them as a list."""
        events = []

        # Flush mouse movement
        if self.has_mouse_movement and (
            self.mouse_delta_x != 0.0 or self.mouse_delta_y != 0.0
        ):
            if self.emit_fractional_movement:
                # Emit with fractional component - split if needed
                remaining_x = self.mouse_delta_x
                remaining_y = self.mouse_delta_y

                while remaining_x != 0.0 or remaining_y != 0.0:
                    # Calculate how much to emit in this event
                    delta_x = remaining_x
                    delta_y = remaining_y

                    if abs(delta_x) > self.max_movement_delta:
                        # Split X axis - preserve sign
                        delta_x = float(self.max_movement_delta) if delta_x > 0 else float(-self.max_movement_delta)

                    if abs(delta_y) > self.max_movement_delta:
                        # Split Y axis - preserve sign
                        delta_y = float(self.max_movement_delta) if delta_y > 0 else float(-self.max_movement_delta)

                    # Emit event with clamped deltas (fractional)
                    events.append(
                        {
                            "category": "mouse",
                            "type": "mouseRel",
                            "deltaX": delta_x,
                            "deltaY": delta_y,
                        }
                    )

                    # Update remaining values
                    remaining_x -= delta_x
                    remaining_y -= delta_y
            else:
                # Emit only whole units - split if needed
                # Extract whole parts
                whole_x = int(self.mouse_delta_x)
                whole_y = int(self.mouse_delta_y)

                # Keep fractional parts for next flush (unless drop_fractions_on_emit is True)
                if not self.drop_fractions_on_emit:
                    self.mouse_delta_x -= whole_x
                    self.mouse_delta_y -= whole_y

                # Split into multiple events if needed
                remaining_x = whole_x
                remaining_y = whole_y

                while remaining_x != 0 or remaining_y != 0:
                    delta_x = remaining_x
                    delta_y = remaining_y

                    if abs(delta_x) > self.max_movement_delta:
                        delta_x = self.max_movement_delta if delta_x > 0 else -self.max_movement_delta

                    if abs(delta_y) > self.max_movement_delta:
                        delta_y = self.max_movement_delta if delta_y > 0 else -self.max_movement_delta

                    # Emit event with whole units
                    events.append(
                        {
                            "category": "mouse",
                            "type": "mouseRel",
                            "deltaX": delta_x,
                            "deltaY": delta_y,
                        }
                    )

                    remaining_x -= delta_x
                    remaining_y -= delta_y

        # Flush scroll
        if self.has_scroll and (self.scroll_delta_x != 0.0 or self.scroll_delta_y != 0.0):
            if self.emit_fractional_scroll:
                # Emit as smoothScroll with fractional component
                events.append(
                    {
                        "category": "mouse",
                        "type": "smoothScroll",
                        "deltaX": self.scroll_delta_x,
                        "deltaY": self.scroll_delta_y,
                    }
                )
            else:
                # Emit only whole units as regular scroll
                whole_x = int(self.scroll_delta_x)
                whole_y = int(self.scroll_delta_y)

                # Keep fractional parts for next flush (unless drop_fractions_on_emit is True)
                if not self.drop_fractions_on_emit:
                    self.scroll_delta_x -= whole_x
                    self.scroll_delta_y -= whole_y

                # Only emit if there are whole units
                if whole_x != 0 or whole_y != 0:
                    events.append(
                        {
                            "category": "mouse",
                            "type": "scroll",
                            "deltaX": whole_x,
                            "deltaY": whole_y,
                        }
                    )

        # Reset state after flushing (except fractional parts if preserving them)
        self.has_mouse_movement = False
        if self.drop_fractions_on_emit or self.emit_fractional_movement:
            self.mouse_delta_x = 0.0
            self.mouse_delta_y = 0.0

        self.has_scroll = False
        if self.drop_fractions_on_emit or self.emit_fractional_scroll:
            self.scroll_delta_x = 0.0
            self.scroll_delta_y = 0.0

        return events
