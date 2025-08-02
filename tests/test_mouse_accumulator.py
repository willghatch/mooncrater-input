#!/usr/bin/env python3
"""
Test file for mouse event accumulator functionality.

Tests all features of the MouseEventAccumulator including multipliers,
coalescing behavior, fractional mode, and eventList handling.
Simple unit tests that test input and output event lists directly.
"""

import os
import sys
from typing import List, Dict, Any

# Add the src directory to the path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from mooncrater_input.mouse_accumulator import MouseEventAccumulator


# Convenience factory functions for testing

def create_fractional_scroll_accumulator(
    name: str = "FractionalScrollAccumulator",
    movement_multiplier=None,
    scroll_multiplier=None,
) -> MouseEventAccumulator:
    """
    Create an accumulator for fractional scroll events (like UART backend).
    Only emits whole scroll units, keeping fractional parts for next time.
    """
    return MouseEventAccumulator(
        name=name,
        accumulate_movement=False,  # Don't accumulate movement for UART
        accumulate_scroll=True,
        accumulate_smooth_scroll=True,
        emit_fractional_movement=False,
        emit_fractional_scroll=False,  # Emit whole units only, preserve fractions
        movement_multiplier=movement_multiplier,
        scroll_multiplier=scroll_multiplier,
    )


def create_coalescing_accumulator(
    name: str = "CoalescingAccumulator",
    movement_multiplier=None,
    scroll_multiplier=None,
) -> MouseEventAccumulator:
    """
    Create an accumulator for event coalescing (like remote backend).
    Accumulates all mouse movements and scroll events to reduce packet count.
    """
    return MouseEventAccumulator(
        name=name,
        accumulate_movement=True,
        accumulate_scroll=True,
        accumulate_smooth_scroll=True,
        emit_fractional_movement=False,
        emit_fractional_scroll=True,  # Emit smoothScroll with fractional values
        movement_multiplier=movement_multiplier,
        scroll_multiplier=scroll_multiplier,
    )


def create_movement_only_accumulator(
    name: str = "MovementAccumulator",
    movement_multiplier=None,
) -> MouseEventAccumulator:
    """
    Create an accumulator that only coalesces mouse movements.
    """
    return MouseEventAccumulator(
        name=name,
        accumulate_movement=True,
        accumulate_scroll=False,
        accumulate_smooth_scroll=False,
        emit_fractional_movement=False,
        movement_multiplier=movement_multiplier,
        scroll_multiplier=None,  # No scroll accumulation
    )


def test_accumulator_creation():
    """Test that MouseEventAccumulator can be created with various configurations."""
    print("Testing accumulator creation...")

    # Default accumulator
    acc = MouseEventAccumulator()
    assert acc.get_name() == "MouseEventAccumulator"
    assert acc.accumulate_movement == True
    assert acc.accumulate_scroll == True
    assert acc.accumulate_smooth_scroll == True
    assert acc.emit_fractional_movement == False
    assert acc.emit_fractional_scroll == True
    assert acc.drop_fractions_on_emit == False
    assert acc.get_movement_multiplier() is None
    assert acc.get_scroll_multiplier() is None

    # Custom accumulator
    acc2 = MouseEventAccumulator(
        name="TestAccumulator",
        accumulate_movement=False,
        accumulate_scroll=True,
        emit_fractional_movement=True,
        emit_fractional_scroll=False,
        drop_fractions_on_emit=True,
        movement_multiplier=2.0,
        scroll_multiplier=1.5,
    )
    assert acc2.get_name() == "TestAccumulator"
    assert acc2.accumulate_movement == False
    assert acc2.emit_fractional_movement == True
    assert acc2.emit_fractional_scroll == False
    assert acc2.drop_fractions_on_emit == True
    assert acc2.get_movement_multiplier() == 2.0
    assert acc2.get_scroll_multiplier() == 1.5

    print("✓ Accumulator creation tests passed")


def test_multiplier_setters_getters():
    """Test that multiplier setters and getters work correctly."""
    print("Testing multiplier setters and getters...")

    acc = MouseEventAccumulator()

    # Test movement multiplier
    acc.set_movement_multiplier(3.0)
    assert acc.get_movement_multiplier() == 3.0

    # Test scroll multiplier
    acc.set_scroll_multiplier(0.5)
    assert acc.get_scroll_multiplier() == 0.5

    # Test None values
    acc.set_movement_multiplier(None)
    acc.set_scroll_multiplier(None)
    assert acc.get_movement_multiplier() is None
    assert acc.get_scroll_multiplier() is None

    print("✓ Multiplier setter/getter tests passed")


def test_basic_mouse_movement_accumulation():
    """Test basic mouse movement event accumulation."""
    print("Testing basic mouse movement accumulation...")

    acc = MouseEventAccumulator()

    # Test mouse movement events
    input_events = [
        {"category": "mouse", "type": "mouseRel", "deltaX": 5, "deltaY": 10},
        {"category": "mouse", "type": "mouseRel", "deltaX": 3, "deltaY": -2},
        {"category": "mouse", "type": "mouseRel", "deltaX": -1, "deltaY": 4},
    ]

    output_events = acc.process_events(input_events)

    # Should accumulate into single event
    assert len(output_events) == 1
    assert output_events[0]["category"] == "mouse"
    assert output_events[0]["type"] == "mouseRel"
    assert output_events[0]["deltaX"] == 5 + 3 - 1  # 7
    assert output_events[0]["deltaY"] == 10 - 2 + 4  # 12

    print("✓ Basic mouse movement accumulation tests passed")


def test_mouse_movement_with_multiplier():
    """Test mouse movement with multiplier applied."""
    print("Testing mouse movement with multiplier...")

    acc = MouseEventAccumulator(movement_multiplier=2.0)

    input_events = [
        {"category": "mouse", "type": "mouseRel", "deltaX": 5, "deltaY": 10},
        {"category": "mouse", "type": "mouseRel", "deltaX": 3, "deltaY": -2},
    ]

    output_events = acc.process_events(input_events)

    # Should accumulate and multiply
    assert len(output_events) == 1
    assert output_events[0]["deltaX"] == int((5 + 3) * 2.0)  # 16
    assert output_events[0]["deltaY"] == int((10 - 2) * 2.0)  # 16

    print("✓ Mouse movement with multiplier tests passed")


def test_scroll_accumulation_emit_smooth():
    """Test scroll event accumulation with smoothScroll emission."""
    print("Testing scroll accumulation with smoothScroll emission...")

    acc = MouseEventAccumulator(
        accumulate_movement=False, emit_fractional_scroll=True
    )

    input_events = [
        {"category": "mouse", "type": "scroll", "deltaX": 1, "deltaY": 2},
        {"category": "mouse", "type": "scroll", "deltaX": 2, "deltaY": -1},
        {"category": "mouse", "type": "scroll", "deltaX": -1, "deltaY": 1},
    ]

    output_events = acc.process_events(input_events)

    # Should accumulate into single smoothScroll event (emit_fractional_scroll=True)
    assert len(output_events) == 1
    assert output_events[0]["category"] == "mouse"
    assert output_events[0]["type"] == "smoothScroll"
    assert output_events[0]["deltaX"] == 1.0 + 2.0 - 1.0  # 2.0
    assert output_events[0]["deltaY"] == 2.0 - 1.0 + 1.0  # 2.0

    print("✓ Scroll accumulation with smoothScroll emission tests passed")


def test_scroll_accumulation_emit_whole_units():
    """Test scroll accumulation emitting only whole units."""
    print("Testing scroll accumulation emitting whole units...")

    acc = MouseEventAccumulator(
        accumulate_movement=False, emit_fractional_scroll=False
    )

    # Test with fractional values that should accumulate
    input_events = [
        {"category": "mouse", "type": "smoothScroll", "deltaX": 0.3, "deltaY": 0.7},
        {"category": "mouse", "type": "smoothScroll", "deltaX": 0.4, "deltaY": 0.8},
        {"category": "mouse", "type": "smoothScroll", "deltaX": 0.5, "deltaY": 0.2},
    ]

    output_events = acc.process_events(input_events)

    # Should accumulate fractional parts and emit whole units
    # 0.3 + 0.4 + 0.5 = 1.2 -> emit 1, keep 0.2
    # 0.7 + 0.8 + 0.2 = 1.7 -> emit 1, keep 0.7
    assert len(output_events) == 1
    assert output_events[0]["category"] == "mouse"
    assert output_events[0]["type"] == "scroll"
    assert output_events[0]["deltaX"] == 1
    assert output_events[0]["deltaY"] == 1

    print("✓ Scroll accumulation emitting whole units tests passed")


def test_scroll_with_multiplier_emits_smooth():
    """Test that scroll events with multipliers emit as smoothScroll."""
    print("Testing scroll with multiplier emission...")

    acc = MouseEventAccumulator(
        accumulate_movement=False,
        scroll_multiplier=1.5,
        emit_fractional_scroll=True,  # Default behavior
    )

    input_events = [{"category": "mouse", "type": "scroll", "deltaX": 2, "deltaY": 1}]

    output_events = acc.process_events(input_events)

    # Should emit as smoothScroll with fractional values
    assert len(output_events) == 1
    assert output_events[0]["category"] == "mouse"
    assert output_events[0]["type"] == "smoothScroll"
    assert output_events[0]["deltaX"] == 2 * 1.5  # 3.0
    assert output_events[0]["deltaY"] == 1 * 1.5  # 1.5

    print("✓ Scroll with multiplier emission tests passed")


def test_mixed_events_with_non_accumulative():
    """Test handling of mixed accumulative and non-accumulative events."""
    print("Testing mixed events with non-accumulative...")

    acc = MouseEventAccumulator()

    input_events = [
        {"category": "mouse", "type": "mouseRel", "deltaX": 5, "deltaY": 10},
        {"category": "keyboard", "type": "keyDown", "key": "A"},
        {"category": "mouse", "type": "mouseRel", "deltaX": 3, "deltaY": -2},
        {"category": "mouse", "type": "scroll", "deltaX": 1, "deltaY": 1},
    ]

    output_events = acc.process_events(input_events)

    # Should have: accumulated mouse movement, keyboard event, accumulated mouse movement, smoothScroll (emit_fractional_scroll=True by default)
    assert len(output_events) == 4
    assert output_events[0]["type"] == "mouseRel"
    assert output_events[0]["deltaX"] == 5
    assert output_events[1]["type"] == "keyDown"
    assert output_events[2]["type"] == "mouseRel"
    assert output_events[2]["deltaX"] == 3
    assert output_events[3]["type"] == "smoothScroll"
    assert output_events[3]["deltaX"] == 1.0

    print("✓ Mixed events with non-accumulative tests passed")


def test_consecutive_event_coalescing():
    """Test that only consecutive events of the same type are coalesced."""
    print("Testing consecutive event coalescing...")

    acc = MouseEventAccumulator()

    input_events = [
        {"category": "mouse", "type": "mouseRel", "deltaX": 1, "deltaY": 1},
        {"category": "mouse", "type": "mouseRel", "deltaX": 2, "deltaY": 2},
        {"category": "mouse", "type": "scroll", "deltaX": 1, "deltaY": 1},
        {"category": "mouse", "type": "mouseRel", "deltaX": 3, "deltaY": 3},
        {"category": "mouse", "type": "scroll", "deltaX": 2, "deltaY": 2},
    ]

    output_events = acc.process_events(input_events)

    # Should have: movement(1+2), scroll(1), movement(3), scroll(2)
    # This preserves event ordering
    assert len(output_events) == 4
    assert output_events[0]["type"] == "mouseRel"
    assert output_events[0]["deltaX"] == 3.0  # 1 + 2
    assert output_events[1]["type"] == "smoothScroll"  # emit_fractional_scroll=True by default
    assert output_events[1]["deltaX"] == 1.0
    assert output_events[2]["type"] == "mouseRel"
    assert output_events[2]["deltaX"] == 3
    assert output_events[3]["type"] == "smoothScroll"
    assert output_events[3]["deltaX"] == 2.0

    print("✓ Consecutive event coalescing tests passed")


def test_eventlist_recursive_handling():
    """Test that eventList events are handled recursively."""
    print("Testing eventList recursive handling...")

    acc = MouseEventAccumulator()

    # Create an eventList containing mouse events
    input_events = [
        {
            "type": "eventList",
            "category": "eventList",
            "events": [
                {"category": "mouse", "type": "mouseRel", "deltaX": 5, "deltaY": 10},
                {"category": "mouse", "type": "mouseRel", "deltaX": 3, "deltaY": -2},
            ],
        }
    ]

    output_events = acc.process_events(input_events)

    # Should process the eventList and accumulate the sub-events
    assert len(output_events) == 1
    assert output_events[0]["type"] == "eventList"
    assert len(output_events[0]["events"]) == 1
    sub_event = output_events[0]["events"][0]
    assert sub_event["category"] == "mouse"
    assert sub_event["type"] == "mouseRel"
    assert sub_event["deltaX"] == 8  # 5 + 3
    assert sub_event["deltaY"] == 8  # 10 + (-2)

    print("✓ EventList recursive handling tests passed")


def test_factory_functions():
    """Test the convenience factory functions."""
    print("Testing factory functions...")

    # Test fractional accumulator
    frac_acc = create_fractional_scroll_accumulator(
        "TestFractional", scroll_multiplier=2.0
    )
    assert frac_acc.get_name() == "TestFractional"
    assert frac_acc.emit_fractional_scroll == False
    assert frac_acc.accumulate_movement == False
    assert frac_acc.get_scroll_multiplier() == 2.0

    # Test coalescing accumulator
    coal_acc = create_coalescing_accumulator(
        "TestCoalescing", movement_multiplier=1.5
    )
    assert coal_acc.get_name() == "TestCoalescing"
    assert coal_acc.emit_fractional_scroll == True
    assert coal_acc.accumulate_movement == True
    assert coal_acc.get_movement_multiplier() == 1.5

    print("✓ Factory function tests passed")


def run_all_tests():
    """Run all tests with timeout protection."""
    print("Running mouse event accumulator tests...")
    print("=" * 50)

    try:
        test_accumulator_creation()
        test_multiplier_setters_getters()
        test_basic_mouse_movement_accumulation()
        test_mouse_movement_with_multiplier()
        test_scroll_accumulation_emit_smooth()
        test_scroll_accumulation_emit_whole_units()
        test_scroll_with_multiplier_emits_smooth()
        test_mixed_events_with_non_accumulative()
        test_consecutive_event_coalescing()
        test_eventlist_recursive_handling()
        test_factory_functions()

        print("=" * 50)
        print("✅ All tests passed successfully!")
        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    import signal
    import sys

    def timeout_handler(signum, frame):
        print("❌ Tests timed out!")
        sys.exit(1)

    # Set a 30-second timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(30)

    try:
        success = run_all_tests()
        signal.alarm(0)  # Cancel timeout
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("❌ Tests interrupted!")
        sys.exit(1)
