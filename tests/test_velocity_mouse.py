import math
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


def make_engine(
    pointer_config=None,
    scroll_config=None,
    pointer_profile=None,
    scroll_profile=None,
    maximum_tick_elapsed=0.05,
):
    pointer_config = pointer_config or MotionConfig("pointer", 100.0, 1.0, 1000.0)
    scroll_config = scroll_config or MotionConfig("scroll", 20.0, 1.0, 200.0)
    pointer_profile = pointer_profile or OutputProfile(OutputMode.POINTER, pointer_config)
    scroll_profile = scroll_profile or OutputProfile(OutputMode.SCROLL, scroll_config)
    return MotionEngine(
        pointer_profile,
        scroll_profile,
        maximum_tick_elapsed=maximum_tick_elapsed,
    )


@pytest.mark.parametrize(
    "config",
    [
        lambda: MotionConfig("pointer", math.nan, 1.0, 100.0),
        lambda: MotionConfig("pointer", 10.0, 0.0, 100.0),
        lambda: MotionConfig("pointer", 101.0, 1.0, 100.0),
        lambda: MotionConfig(
            "pointer",
            10.0,
            1.0,
            100.0,
            modifiers={"bad": SpeedModifier(ModifierKind.MULTIPLICATIVE, 0.0)},
        ),
    ],
)
def test_motion_config_rejects_values_that_cannot_produce_safe_speed(config):
    with pytest.raises(ValueError):
        config()


def test_elapsed_movement_normalizes_diagonals_cancels_opposites_and_caps_stalls():
    engine = make_engine(maximum_tick_elapsed=0.05)
    engine.press_direction(Direction.RIGHT, "right", 1.0)
    engine.press_direction(Direction.DOWN, "down", 1.0)

    diagonal = engine.tick(1.02)
    component = 2.0 / math.sqrt(2.0)
    assert diagonal.mode is OutputMode.POINTER
    assert diagonal.delta_x == pytest.approx(component)
    assert diagonal.delta_y == pytest.approx(component)

    engine.press_direction(Direction.LEFT, "left", 1.02)
    vertical = engine.tick(1.04)
    assert vertical.delta_x == pytest.approx(0.0)
    assert vertical.delta_y == pytest.approx(2.0)

    capped = engine.tick(2.0)
    assert capped.delta_y == pytest.approx(5.0)

    engine.release_direction(Direction.DOWN, "down", 2.0)
    assert engine.tick(2.01) is None


def test_direction_binding_identities_do_not_release_each_other():
    engine = make_engine()
    engine.press_direction(Direction.RIGHT, "primary", 0.0)
    engine.press_direction(Direction.RIGHT, "secondary", 0.0)
    engine.release_direction(Direction.RIGHT, "primary", 0.0)

    assert engine.tick(0.01).delta_x == pytest.approx(1.0)

    engine.release_direction(Direction.RIGHT, "secondary", 0.01)
    assert engine.tick(0.02) is None


def test_momentary_and_latched_modifiers_compose_and_clamp_in_fixed_order():
    config = MotionConfig(
        "pointer",
        20.0,
        1.0,
        100.0,
        modifiers={
            "boost": SpeedModifier(ModifierKind.ADDITIVE, 10.0),
            "turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 3.0),
            "extra": SpeedModifier(ModifierKind.MULTIPLICATIVE, 2.0),
        },
    )
    engine = make_engine(pointer_config=config)
    engine.press_speed_modifier(config, "boost", "boost-left", 0.0)
    engine.press_speed_modifier(config, "boost", "boost-right", 0.0)
    engine.toggle_speed_modifier(config, "turbo", 0.0)
    engine.set_speed_modifier(config, "extra", True, 0.0)
    engine.press_direction(Direction.RIGHT, "right", 0.0)

    assert engine.tick(0.01).delta_x == pytest.approx(1.0)

    engine.release_speed_modifier(config, "boost", "boost-left", 0.01)
    assert engine.tick(0.02).delta_x == pytest.approx(1.0)

    engine.release_speed_modifier(config, "boost", "boost-right", 0.02)
    assert engine.tick(0.03).delta_x == pytest.approx(1.0)

    engine.set_speed_modifier(config, "extra", False, 0.03)
    assert engine.tick(0.04).delta_x == pytest.approx(0.6)


def test_same_modifier_contributes_for_each_momentary_and_latched_activation():
    config = MotionConfig(
        "pointer",
        20.0,
        1.0,
        100.0,
        modifiers={"boost": SpeedModifier(ModifierKind.ADDITIVE, 10.0)},
    )
    engine = make_engine(pointer_config=config)
    engine.press_speed_modifier(config, "boost", "held-boost", 0.0)
    engine.set_speed_modifier(config, "boost", True, 0.0)
    engine.press_direction(Direction.RIGHT, "right", 0.0)

    assert engine.tick(0.01).delta_x == pytest.approx(0.4)


def test_base_speed_actions_are_sequential_clamped_and_repeat_safe():
    pointer = MotionConfig("pointer", 10.0, 5.0, 50.0)
    scroll = MotionConfig("scroll", 4.0, 1.0, 12.0)
    engine = make_engine(pointer_config=pointer, scroll_config=scroll)

    assert engine.press_base_adjustment("up", BaseSpeedOperation.ADD, 10.0, 0.0)
    assert not engine.press_base_adjustment("up", BaseSpeedOperation.ADD, 10.0, 0.1)
    engine.release_base_adjustment("up")
    assert engine.press_base_adjustment("double", BaseSpeedOperation.MULTIPLY, 2.0, 0.1)
    assert engine.base_speed(pointer) == pytest.approx(40.0)

    engine.press_momentary_swap("scroll-swap", 0.1)
    assert engine.press_base_adjustment("set", BaseSpeedOperation.SET, 100.0, 0.1)
    assert engine.base_speed(scroll) == pytest.approx(12.0)
    assert engine.base_speed(pointer) == pytest.approx(40.0)


def test_mode_selection_uses_effective_mode_and_profile_axis_transform():
    pointer = MotionConfig("pointer", 100.0, 1.0, 1000.0)
    scroll = MotionConfig("scroll", 20.0, 1.0, 200.0, normalize_diagonal=False)
    engine = make_engine(
        pointer_config=pointer,
        scroll_config=scroll,
        scroll_profile=OutputProfile(
            OutputMode.SCROLL,
            scroll,
            swap_axes=True,
            x_sign=-1,
            y_sign=1,
        ),
    )
    engine.press_direction(Direction.RIGHT, "right", 0.0)
    engine.press_direction(Direction.DOWN, "down", 0.0)
    engine.press_momentary_swap("swap-one", 0.0)
    engine.press_momentary_swap("swap-two", 0.0)

    sample = engine.tick(0.01)
    assert sample.mode is OutputMode.SCROLL
    assert (sample.delta_x, sample.delta_y) == pytest.approx((-0.2, 0.2))

    engine.toggle_mode(0.01)
    assert engine.effective_mode is OutputMode.POINTER
    engine.release_momentary_swap("swap-one", 0.01)
    assert engine.effective_mode is OutputMode.POINTER
    engine.release_momentary_swap("swap-two", 0.01)
    assert engine.effective_mode is OutputMode.SCROLL


def test_shared_motion_config_shares_runtime_speed_and_modifier_state():
    shared = MotionConfig(
        "shared",
        10.0,
        1.0,
        100.0,
        modifiers={"turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 2.0)},
    )
    engine = make_engine(
        pointer_config=shared,
        scroll_config=shared,
        pointer_profile=OutputProfile(OutputMode.POINTER, shared),
        scroll_profile=OutputProfile(OutputMode.SCROLL, shared),
    )
    engine.set_speed_modifier(shared, "turbo", True, 0.0)
    engine.press_base_adjustment("increase", BaseSpeedOperation.ADD, 5.0, 0.0)
    engine.release_base_adjustment("increase")
    engine.set_mode(OutputMode.SCROLL, 0.0)
    engine.press_direction(Direction.UP, "up", 0.0)

    sample = engine.tick(0.01)
    assert sample.mode is OutputMode.SCROLL
    assert sample.delta_y == pytest.approx(-0.3)


def test_short_diagonal_tap_emits_one_normalized_nudge_on_next_tick():
    pointer = MotionConfig("pointer", 100.0, 1.0, 1000.0, tap_nudge=3.0)
    engine = make_engine(pointer_config=pointer)
    engine.press_direction(Direction.RIGHT, "right", 0.0)
    engine.press_direction(Direction.UP, "up", 0.001)
    engine.release_direction(Direction.RIGHT, "right", 0.002)
    engine.release_direction(Direction.UP, "up", 0.003)

    nudge = engine.tick(0.004)
    component = 3.0 / math.sqrt(2.0)
    assert nudge.mode is OutputMode.POINTER
    assert nudge.delta_x == pytest.approx(component)
    assert nudge.delta_y == pytest.approx(-component)
    assert engine.tick(0.01) is None


def test_fixed_dash_uses_direction_ignores_speed_and_is_repeat_safe():
    pointer = MotionConfig(
        "pointer",
        10.0,
        1.0,
        100.0,
        modifiers={"turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 4.0)},
        tap_nudge=3.0,
    )
    engine = make_engine(pointer_config=pointer)
    engine.set_speed_modifier(pointer, "turbo", True, 0.0)
    engine.press_direction(Direction.RIGHT, "right", 0.0)
    engine.press_direction(Direction.UP, "up", 0.0)

    dash = engine.press_dash("dash", 0.0, distance=12.0)
    component = 12.0 / math.sqrt(2.0)
    assert dash.mode is OutputMode.POINTER
    assert dash.delta_x == pytest.approx(component)
    assert dash.delta_y == pytest.approx(-component)
    assert engine.press_dash("dash", 0.0, distance=12.0) is None

    engine.release_dash("dash")
    assert engine.press_dash("dash", 0.0, distance=12.0) == dash
    engine.release_direction(Direction.RIGHT, "right", 0.0)
    engine.release_direction(Direction.UP, "up", 0.0)
    assert engine.tick(0.01) is None


def test_velocity_scaled_dash_uses_effective_profile_speed_and_transform():
    scroll = MotionConfig(
        "scroll",
        20.0,
        1.0,
        200.0,
        modifiers={"turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 3.0)},
    )
    engine = make_engine(
        scroll_config=scroll,
        scroll_profile=OutputProfile(
            OutputMode.SCROLL,
            scroll,
            swap_axes=True,
            x_sign=-1,
            y_sign=1,
        ),
    )
    engine.set_speed_modifier(scroll, "turbo", True, 0.0)
    engine.press_momentary_swap("scroll-swap", 0.0)
    engine.press_direction(Direction.RIGHT, "right", 0.0)

    dash = engine.press_dash("dash", 0.0, velocity_multiplier=0.5)

    assert dash.mode is OutputMode.SCROLL
    assert dash.delta_x == pytest.approx(0.0)
    assert dash.delta_y == pytest.approx(30.0)


def test_dash_requires_one_positive_distance_choice_and_a_net_direction():
    engine = make_engine()
    assert engine.press_dash("idle", 0.0, distance=10.0) is None

    with pytest.raises(ValueError):
        engine.press_dash("missing", 0.0)
    with pytest.raises(ValueError):
        engine.press_dash("ambiguous", 0.0, distance=10.0, velocity_multiplier=0.5)
    with pytest.raises(ValueError):
        engine.press_dash("negative", 0.0, distance=-1.0)
    with pytest.raises(ValueError):
        engine.press_dash("not-finite", 0.0, velocity_multiplier=math.nan)


def test_reset_restores_defaults_and_clears_all_runtime_state():
    config = MotionConfig(
        "pointer",
        10.0,
        1.0,
        100.0,
        modifiers={"turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 2.0)},
    )
    engine = make_engine(pointer_config=config)
    engine.set_speed_modifier(config, "turbo", True, 0.0)
    engine.press_base_adjustment("increase", BaseSpeedOperation.ADD, 5.0, 0.0)
    engine.press_direction(Direction.RIGHT, "right", 0.0)
    engine.set_mode(OutputMode.SCROLL, 0.0)

    engine.reset(1.0)

    assert engine.base_speed(config) == pytest.approx(10.0)
    assert engine.latched_mode is OutputMode.POINTER
    assert engine.tick(1.01) is None


def test_engine_rejects_profiles_with_wrong_modes_or_duplicate_config_names():
    pointer = MotionConfig("same", 10.0, 1.0, 100.0)
    other_pointer = MotionConfig("same", 20.0, 1.0, 100.0)
    scroll = MotionConfig("scroll", 10.0, 1.0, 100.0)

    with pytest.raises(ValueError):
        MotionEngine(
            OutputProfile(OutputMode.SCROLL, pointer),
            OutputProfile(OutputMode.SCROLL, scroll),
        )

    with pytest.raises(ValueError):
        MotionEngine(
            OutputProfile(OutputMode.POINTER, pointer),
            OutputProfile(OutputMode.SCROLL, other_pointer),
        )


def test_motion_after_an_idle_gap_starts_at_the_press_not_the_last_tick():
    # A timer that stops while idle leaves the last tick far in the past.
    engine = make_engine(maximum_tick_elapsed=1.0)
    engine.press_direction(Direction.RIGHT, "right", 0.0)
    engine.tick(0.1)
    engine.release_direction(Direction.RIGHT, "right", 0.1)

    engine.press_direction(Direction.RIGHT, "right", 10.0)
    sample = engine.tick(10.01)
    # 100 units/s for 10 ms, not a catch-up jump from the idle gap.
    assert sample.delta_x == pytest.approx(1.0)


def test_is_idle_only_when_nothing_is_held_or_queued():
    engine = make_engine()
    assert engine.is_idle()
    engine.press_direction(Direction.UP, "up", 1.0)
    assert not engine.is_idle()
    # An unticked tap queues a nudge that still needs a tick.
    engine.release_direction(Direction.UP, "up", 1.0)
    assert not engine.is_idle()
    assert engine.tick(1.01) is not None
    assert engine.is_idle()


def test_release_held_stops_motion_but_keeps_base_speed_and_latched_state():
    config = MotionConfig(
        "pointer", 100.0, 1.0, 1000.0,
        modifiers={
            "turbo": SpeedModifier(ModifierKind.MULTIPLICATIVE, 3.0),
            "lock": SpeedModifier(ModifierKind.MULTIPLICATIVE, 2.0),
        },
    )
    engine = make_engine(pointer_config=config)
    engine.press_base_adjustment("up", BaseSpeedOperation.MULTIPLY, 2.0, 1.0)
    engine.toggle_speed_modifier(config, "lock", 1.0)
    engine.press_speed_modifier(config, "turbo", "turbo-key", 1.0)
    engine.press_direction(Direction.RIGHT, "right", 1.0)
    engine.press_momentary_swap("swap", 1.0)

    engine.release_held(1.0)

    assert engine.tick(1.01) is None
    assert engine.is_idle()
    assert engine.effective_mode is OutputMode.POINTER
    assert engine.base_speed(config) == pytest.approx(200.0)
    # The latched modifier stays; the held turbo does not.
    assert engine.effective_speed(config) == pytest.approx(400.0)
    # The adjustment binding is re-armed.
    assert engine.press_base_adjustment("up", BaseSpeedOperation.MULTIPLY, 2.0, 1.1)
