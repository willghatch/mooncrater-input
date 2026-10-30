import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from mooncrater_input.velocity_mouse import (
    BaseSpeedOperation,
    Direction,
    ModifierKind,
    MotionConfig,
    MotionEngine,
    OutputMode,
    OutputProfile,
    SpeedModifier,
)
from mooncrater_input.mouse_keys import (
    AdjustBaseSpeed,
    Button,
    Dash,
    DragLock,
    Exit,
    HoldKey,
    HoldScroll,
    Move,
    MouseKeysLayer,
    SpeedHold,
    SwitchLayout,
    ToggleScroll,
)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class Timer:
    """Stands in for PeriodicTimer; the test delivers ticks itself."""

    def __init__(self):
        self.is_running = False

    def start(self):
        self.is_running = True

    def stop(self):
        self.is_running = False


TICK = {"category": "timer", "type": "tick", "inputTag": "ticker"}


def down(key):
    return {"category": "keyboard", "type": "keyDown", "keyName": key, "inputTag": "kbd"}


def up(key):
    return {"category": "keyboard", "type": "keyUp", "keyName": key, "inputTag": "kbd"}


def repeat(key):
    return {"category": "keyboard", "type": "keyRepeat", "keyName": key, "inputTag": "kbd"}


ARROWS = {
    "KEY_E": Move(Direction.UP),
    "KEY_S": Move(Direction.LEFT),
    "KEY_D": Move(Direction.DOWN),
    "KEY_F": Move(Direction.RIGHT),
}


def make_layer(extra=None, other_layout=None):
    turbo = {"turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 3.0)}
    pointer = MotionConfig("pointer", 100.0, 1.0, 10000.0, modifiers=dict(turbo))
    scroll = MotionConfig("scroll", 10.0, 1.0, 1000.0, modifiers=dict(turbo))
    engine = MotionEngine(
        OutputProfile(OutputMode.POINTER, pointer),
        OutputProfile(OutputMode.SCROLL, scroll, y_sign=-1),
        maximum_tick_elapsed=1.0,
    )
    layout = dict(ARROWS)
    layout.update(extra or {})
    layouts = {"main": layout, "other": other_layout or {}}
    clock = Clock()
    timer = Timer()
    layer = MouseKeysLayer(engine, layouts, timer=timer, timer_tag="ticker", clock=clock)
    layer.enter("main")
    return layer, clock, timer, engine, pointer


def run(layer, *events):
    """Feed events, returning (passed through, generated)."""
    return layer.process_events(list(events))


def generated(layer, *events):
    passed, out = run(layer, *events)
    assert passed == []
    return out


def tick(layer, clock, dt=0.01):
    clock.now += dt
    return generated(layer, TICK)


def total_motion(events, kind):
    x = sum(e["deltaX"] for e in events if e["type"] == kind)
    y = sum(e["deltaY"] for e in events if e["type"] == kind)
    return x, y


def test_held_direction_moves_on_ticks_and_stops_the_timer_after_release():
    layer, clock, timer, _, _ = make_layer()
    assert not timer.is_running
    generated(layer, down("KEY_F"))
    assert timer.is_running

    out = tick(layer, clock) + tick(layer, clock)
    assert total_motion(out, "mouseRel") == pytest.approx((2.0, 0.0))

    generated(layer, up("KEY_F"))
    assert tick(layer, clock) == []
    # Nothing is held, so the timer stops rather than ticking forever.
    assert not timer.is_running


def test_speed_hold_scales_motion_and_dash_jumps_immediately():
    layer, clock, _, _, _ = make_layer({
        "KEY_A": SpeedHold("turbo"),
        "KEY_SPACE": Dash(0.5),
    })
    generated(layer, down("KEY_F"), down("KEY_A"))
    assert total_motion(tick(layer, clock), "mouseRel") == pytest.approx((3.0, 0.0))

    # Half a second of travel at the current (turbo) speed, without a tick.
    dash = generated(layer, down("KEY_SPACE"))
    assert total_motion(dash, "mouseRel") == pytest.approx((150.0, 0.0))
    # Key repeat does not dash again.
    assert generated(layer, repeat("KEY_SPACE"), down("KEY_SPACE")) == []


def test_base_speed_adjustment_changes_later_motion():
    layer, clock, _, _, _ = make_layer({
        "KEY_T": AdjustBaseSpeed(BaseSpeedOperation.MULTIPLY, 2.0),
    })
    generated(layer, down("KEY_T"), up("KEY_T"))
    generated(layer, down("KEY_F"))
    assert total_motion(tick(layer, clock), "mouseRel") == pytest.approx((2.0, 0.0))


def test_scroll_toggle_and_scroll_hold_route_motion_to_smooth_scroll():
    layer, clock, _, _, _ = make_layer({
        "KEY_A": ToggleScroll(),
        "KEY_SLASH": HoldScroll(),
    })
    generated(layer, down("KEY_SLASH"), down("KEY_D"))
    held = tick(layer, clock, 0.1)
    # Scroll profile: 10 notches/s, down key scrolls down (negative wheel).
    assert total_motion(held, "smoothScroll") == pytest.approx((0.0, -1.0))
    generated(layer, up("KEY_SLASH"))
    assert total_motion(tick(layer, clock), "mouseRel") == pytest.approx((0.0, 1.0))

    generated(layer, down("KEY_A"), up("KEY_A"))
    assert total_motion(tick(layer, clock, 0.1), "smoothScroll") == pytest.approx((0.0, -1.0))
    assert layer.scrolling


def test_blank_keys_and_repeats_are_swallowed_only_while_active():
    layer, clock, _, _, _ = make_layer()
    assert run(layer, down("KEY_Q"), repeat("KEY_Q"), up("KEY_Q")) == ([], [])
    mouse = {"category": "mouse", "type": "mouseRel", "deltaX": 3, "deltaY": 0}
    assert run(layer, mouse) == ([mouse], [])

    layer.exit()
    assert run(layer, down("KEY_Q"), up("KEY_Q")) == ([down("KEY_Q"), up("KEY_Q")], [])
    # A tick that was already queued when leaving mouse mode is dropped.
    assert run(layer, TICK) == ([], [])


def test_buttons_and_modifiers_stay_down_until_the_last_binding_releases():
    layer, _, _, _, _ = make_layer({
        "KEY_J": Button("left"),
        "KEY_M": Button("left"),
        "KEY_Q": HoldKey("KEY_LEFTMETA"),
    })
    out = generated(layer, down("KEY_Q"), down("KEY_J"), down("KEY_M"))
    assert [(e["type"], e.get("button") or e.get("keyName")) for e in out] == [
        ("keyDown", "KEY_LEFTMETA"),
        ("mouseDown", "left"),
    ]
    assert generated(layer, up("KEY_J")) == []
    out = generated(layer, up("KEY_M"), up("KEY_Q"))
    assert [(e["type"], e.get("button") or e.get("keyName")) for e in out] == [
        ("mouseUp", "left"),
        ("keyUp", "KEY_LEFTMETA"),
    ]


def test_drag_lock_holds_the_next_button_until_it_is_pressed_again():
    layer, _, _, _, _ = make_layer({
        "KEY_R": DragLock(),
        "KEY_V": Button("left"),
    })
    generated(layer, down("KEY_R"), up("KEY_R"))
    out = generated(layer, down("KEY_V"), up("KEY_V"))
    assert [(e["type"], e["button"]) for e in out] == [("mouseDown", "left")]

    out = generated(layer, down("KEY_V"), up("KEY_V"))
    assert [(e["type"], e["button"]) for e in out] == [("mouseUp", "left")]

    # Without drag lock armed, the button is an ordinary hold again.
    out = generated(layer, down("KEY_V"), up("KEY_V"))
    assert [(e["type"], e["button"]) for e in out] == [("mouseDown", "left"), ("mouseUp", "left")]


def test_exit_releases_everything_and_swallows_later_key_ups():
    layer, clock, timer, engine, pointer = make_layer({
        "KEY_T": AdjustBaseSpeed(BaseSpeedOperation.MULTIPLY, 2.0),
        "KEY_Q": HoldKey("KEY_LEFTSHIFT"),
        "KEY_J": Button("right"),
        "KEY_R": DragLock(),
        "KEY_V": Button("left"),
        "KEY_B": Exit(),
    })
    generated(layer, down("KEY_T"), up("KEY_T"))
    generated(layer, down("KEY_R"), up("KEY_R"), down("KEY_V"), up("KEY_V"))
    generated(layer, down("KEY_Q"), down("KEY_J"), down("KEY_F"))

    out = generated(layer, down("KEY_B"))
    released = {(e["type"], e.get("button") or e.get("keyName")) for e in out}
    assert released == {
        ("keyUp", "KEY_LEFTSHIFT"),
        ("mouseUp", "right"),
        ("mouseUp", "left"),
    }
    assert layer.active_layout is None
    assert not timer.is_running

    # Keys still held from mouse mode must not reach the underlying layout.
    assert run(layer, up("KEY_Q"), up("KEY_J"), up("KEY_F"), up("KEY_B")) == ([], [])
    assert run(layer, up("KEY_Q")) == ([up("KEY_Q")], [])

    # The user's base speed survives leaving and re-entering mouse mode.
    layer.enter("main")
    generated(layer, down("KEY_F"))
    assert total_motion(tick(layer, clock), "mouseRel") == pytest.approx((2.0, 0.0))


def test_switching_layouts_keeps_releasing_keys_by_their_original_action():
    layer, clock, _, _, _ = make_layer(
        {"KEY_J": Button("left"), "KEY_H": SwitchLayout("other")},
        other_layout={"KEY_J": Button("right"), "KEY_F": Move(Direction.LEFT)},
    )
    generated(layer, down("KEY_J"), down("KEY_H"))
    assert layer.active_layout == "other"
    out = generated(layer, up("KEY_J"))
    assert [(e["type"], e["button"]) for e in out] == [("mouseUp", "left")]

    generated(layer, down("KEY_F"))
    assert total_motion(tick(layer, clock), "mouseRel") == pytest.approx((-1.0, 0.0))
