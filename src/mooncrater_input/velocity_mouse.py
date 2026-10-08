"""Reusable state machine for velocity-based pointer and scroll movement.

The engine deliberately has no scheduler or output callback.  Callers update held
state from input events and call :meth:`MotionEngine.tick` with monotonic times.
Returned samples use real-valued relative units so platform adapters can preserve
their own fractional remainders when producing integer reports.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class Direction(Enum):
    """A logical movement direction before profile-specific axis transforms."""

    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


class OutputMode(Enum):
    """The adapter-facing destination for a motion sample."""

    POINTER = "pointer"
    SCROLL = "scroll"


class ModifierKind(Enum):
    """How a speed modifier participates in effective-speed calculation."""

    ADDITIVE = "additive"
    MULTIPLICATIVE = "multiplicative"


class BaseSpeedOperation(Enum):
    """A stateful one-shot operation on a motion configuration's base speed."""

    ADD = "add"
    MULTIPLY = "multiply"
    SET = "set"


def _finite_number(value: float, description: str) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        raise ValueError("{} must be a finite number".format(description))
    if not math.isfinite(converted):
        raise ValueError("{} must be a finite number".format(description))
    return converted


@dataclass(frozen=True)
class SpeedModifier:
    """A named modifier's additive offset or positive multiplier."""

    kind: ModifierKind
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ModifierKind):
            raise ValueError("modifier kind must be a ModifierKind")
        value = _finite_number(self.value, "modifier value")
        if self.kind is ModifierKind.MULTIPLICATIVE and value <= 0.0:
            raise ValueError("multiplicative modifier values must be positive")
        object.__setattr__(self, "value", value)


@dataclass(eq=False)
class MotionConfig:
    """Behavior settings whose base speed has engine-local runtime state.

    A single instance can be referenced by both output profiles to intentionally
    share base speed and modifier state.  Callers should treat instances as
    immutable after constructing an engine.
    """

    name: str
    base_speed: float
    minimum_speed: float
    maximum_speed: float
    modifiers: Dict[str, SpeedModifier] = field(default_factory=dict)
    normalize_diagonal: bool = True
    tap_nudge: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("motion configuration name must not be empty")
        self.base_speed = _finite_number(self.base_speed, "base speed")
        self.minimum_speed = _finite_number(self.minimum_speed, "minimum speed")
        self.maximum_speed = _finite_number(self.maximum_speed, "maximum speed")
        self.tap_nudge = _finite_number(self.tap_nudge, "tap nudge")
        if self.minimum_speed <= 0.0:
            raise ValueError("minimum speed must be positive")
        if self.maximum_speed < self.minimum_speed:
            raise ValueError("maximum speed must not be less than minimum speed")
        if not self.minimum_speed <= self.base_speed <= self.maximum_speed:
            raise ValueError("base speed must be within the configured speed range")
        if self.tap_nudge < 0.0:
            raise ValueError("tap nudge must not be negative")
        if not isinstance(self.modifiers, dict):
            raise ValueError("modifiers must be a dictionary")
        for name, modifier in self.modifiers.items():
            if not isinstance(name, str) or not name:
                raise ValueError("modifier names must not be empty")
            if not isinstance(modifier, SpeedModifier):
                raise ValueError("modifier values must be SpeedModifier instances")
        self.modifiers = dict(self.modifiers)


@dataclass(frozen=True)
class OutputProfile:
    """Maps logical motion into pointer or scroll axes."""

    mode: OutputMode
    motion_config: MotionConfig
    swap_axes: bool = False
    x_sign: int = 1
    y_sign: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.mode, OutputMode):
            raise ValueError("profile mode must be an OutputMode")
        if not isinstance(self.motion_config, MotionConfig):
            raise ValueError("profile motion_config must be a MotionConfig")
        if self.x_sign not in (-1, 1) or self.y_sign not in (-1, 1):
            raise ValueError("profile axis signs must be -1 or 1")

    def transform(self, delta_x: float, delta_y: float) -> Tuple[float, float]:
        """Apply axis swapping followed by the configured output signs."""
        if self.swap_axes:
            delta_x, delta_y = delta_y, delta_x
        return delta_x * self.x_sign, delta_y * self.y_sign


@dataclass(frozen=True)
class MotionSample:
    """A real-valued relative displacement tagged for an output adapter."""

    mode: OutputMode
    delta_x: float
    delta_y: float


@dataclass
class _MotionRuntime:
    base_speed: float
    held_modifiers: Dict[str, Set[Any]] = field(default_factory=dict)
    latched_modifiers: Set[str] = field(default_factory=set)


class MotionEngine:
    """Deterministic state machine for game-like keyboard motion.

    Binding identities make duplicate physical bindings safe: releasing one key
    does not release another key that provides the same logical action.  Dash
    actions return an immediate sample in the currently held direction.
    """

    def __init__(
        self,
        pointer_profile: OutputProfile,
        scroll_profile: OutputProfile,
        initial_mode: OutputMode = OutputMode.POINTER,
        maximum_tick_elapsed: float = 0.05,
    ) -> None:
        if pointer_profile.mode is not OutputMode.POINTER:
            raise ValueError("pointer_profile must use pointer mode")
        if scroll_profile.mode is not OutputMode.SCROLL:
            raise ValueError("scroll_profile must use scroll mode")
        if not isinstance(initial_mode, OutputMode):
            raise ValueError("initial_mode must be an OutputMode")
        maximum_tick_elapsed = _finite_number(
            maximum_tick_elapsed, "maximum tick elapsed"
        )
        if maximum_tick_elapsed <= 0.0:
            raise ValueError("maximum tick elapsed must be positive")

        configs = [pointer_profile.motion_config, scroll_profile.motion_config]
        if configs[0] is not configs[1] and configs[0].name == configs[1].name:
            raise ValueError("distinct motion configurations must have unique names")

        self.pointer_profile = pointer_profile
        self.scroll_profile = scroll_profile
        self.initial_mode = initial_mode
        self.maximum_tick_elapsed = maximum_tick_elapsed
        self._runtime = {}  # type: Dict[MotionConfig, _MotionRuntime]
        for config in configs:
            if config not in self._runtime:
                self._runtime[config] = _MotionRuntime(config.base_speed)

        self._held_directions = {
            direction: set() for direction in Direction
        }  # type: Dict[Direction, Set[Any]]
        self._held_adjustments = set()  # type: Set[Any]
        self._held_dashes = set()  # type: Set[Any]
        self._momentary_swaps = set()  # type: Set[Any]
        self._gesture_directions = set()  # type: Set[Direction]
        self._gesture_moved = False
        self._pending_samples = []  # type: List[MotionSample]
        self._last_tick = None  # type: Optional[float]
        self._last_time = None  # type: Optional[float]
        self._latched_mode = initial_mode

    @property
    def latched_mode(self) -> OutputMode:
        """Return the persistent mode, excluding momentary swap state."""
        return self._latched_mode

    @property
    def effective_mode(self) -> OutputMode:
        """Return the mode currently selected for motion output."""
        if not self._momentary_swaps:
            return self._latched_mode
        if self._latched_mode is OutputMode.POINTER:
            return OutputMode.SCROLL
        return OutputMode.POINTER

    def _observe_time(self, now: float) -> float:
        now = _finite_number(now, "timestamp")
        if self._last_time is not None and now < self._last_time:
            raise ValueError("timestamps must be monotonic")
        self._last_time = now
        if self._last_tick is None:
            self._last_tick = now
        return now

    def _profile(self, mode: Optional[OutputMode] = None) -> OutputProfile:
        selected = self.effective_mode if mode is None else mode
        if selected is OutputMode.POINTER:
            return self.pointer_profile
        if selected is OutputMode.SCROLL:
            return self.scroll_profile
        raise ValueError("mode must be an OutputMode")

    def _resolve_config(self, config: MotionConfig) -> MotionConfig:
        if config not in self._runtime:
            raise ValueError("motion configuration does not belong to this engine")
        return config

    def _modifier(self, config: MotionConfig, name: str) -> SpeedModifier:
        self._resolve_config(config)
        try:
            return config.modifiers[name]
        except KeyError:
            raise ValueError("unknown speed modifier: {}".format(name))

    def press_direction(self, direction: Direction, binding_id: Any, now: float) -> None:
        """Hold a logical direction; repeating an already-held binding is harmless."""
        self._observe_time(now)
        if not isinstance(direction, Direction):
            raise ValueError("direction must be a Direction")
        was_idle = not self._has_held_direction()
        bindings = self._held_directions[direction]
        if binding_id in bindings:
            return
        bindings.add(binding_id)
        if was_idle:
            self._gesture_directions.clear()
            self._gesture_moved = False
        self._gesture_directions.add(direction)

    def release_direction(
        self, direction: Direction, binding_id: Any, now: float
    ) -> None:
        """Release one physical binding and queue a nudge for an unticked tap."""
        self._observe_time(now)
        if not isinstance(direction, Direction):
            raise ValueError("direction must be a Direction")
        self._held_directions[direction].discard(binding_id)
        if self._has_held_direction():
            return
        if self._gesture_directions and not self._gesture_moved:
            profile = self._profile()
            sample = self._sample_for_directions(
                self._gesture_directions,
                profile.motion_config.tap_nudge,
                profile,
            )
            if sample is not None:
                self._pending_samples.append(sample)
        self._gesture_directions.clear()
        self._gesture_moved = False

    def press_speed_modifier(
        self,
        config: MotionConfig,
        modifier_name: str,
        binding_id: Any,
        now: float,
    ) -> None:
        """Activate a momentary modifier for one physical binding."""
        self._observe_time(now)
        self._modifier(config, modifier_name)
        runtime = self._runtime[config]
        runtime.held_modifiers.setdefault(modifier_name, set()).add(binding_id)

    def release_speed_modifier(
        self,
        config: MotionConfig,
        modifier_name: str,
        binding_id: Any,
        now: float,
    ) -> None:
        """Release one physical binding for a momentary modifier."""
        self._observe_time(now)
        self._modifier(config, modifier_name)
        bindings = self._runtime[config].held_modifiers.get(modifier_name)
        if bindings is not None:
            bindings.discard(binding_id)
            if not bindings:
                del self._runtime[config].held_modifiers[modifier_name]

    def toggle_speed_modifier(
        self, config: MotionConfig, modifier_name: str, now: float
    ) -> bool:
        """Toggle a runtime-latched modifier and return its new state."""
        self._observe_time(now)
        self._modifier(config, modifier_name)
        latched = self._runtime[config].latched_modifiers
        if modifier_name in latched:
            latched.remove(modifier_name)
            return False
        latched.add(modifier_name)
        return True

    def set_speed_modifier(
        self, config: MotionConfig, modifier_name: str, enabled: bool, now: float
    ) -> None:
        """Explicitly enable or disable a runtime-latched modifier."""
        self._observe_time(now)
        self._modifier(config, modifier_name)
        latched = self._runtime[config].latched_modifiers
        if enabled:
            latched.add(modifier_name)
        else:
            latched.discard(modifier_name)

    def base_speed(self, config: MotionConfig) -> float:
        """Return an engine's current stored base speed for a configuration."""
        self._resolve_config(config)
        return self._runtime[config].base_speed

    def effective_speed(self, config: MotionConfig) -> float:
        """Calculate additive modifiers, then multipliers, then clamp."""
        self._resolve_config(config)
        runtime = self._runtime[config]
        additive = 0.0
        multiplier = 1.0
        momentary_names = [
            name for name, bindings in runtime.held_modifiers.items() if bindings
        ]
        for name in momentary_names + list(runtime.latched_modifiers):
            modifier = config.modifiers[name]
            if modifier.kind is ModifierKind.ADDITIVE:
                additive += modifier.value
            else:
                multiplier *= modifier.value
        speed = (runtime.base_speed + additive) * multiplier
        return min(config.maximum_speed, max(config.minimum_speed, speed))

    def press_base_adjustment(
        self,
        binding_id: Any,
        operation: BaseSpeedOperation,
        value: float,
        now: float,
        config: Optional[MotionConfig] = None,
    ) -> bool:
        """Apply an adjustment once per physical press and return whether it ran."""
        self._observe_time(now)
        if binding_id in self._held_adjustments:
            return False
        if not isinstance(operation, BaseSpeedOperation):
            raise ValueError("operation must be a BaseSpeedOperation")
        value = _finite_number(value, "base speed adjustment")
        if operation is BaseSpeedOperation.MULTIPLY and value <= 0.0:
            raise ValueError("base speed multiplication factor must be positive")
        selected = self._profile().motion_config if config is None else config
        self._resolve_config(selected)
        runtime = self._runtime[selected]
        if operation is BaseSpeedOperation.ADD:
            result = runtime.base_speed + value
        elif operation is BaseSpeedOperation.MULTIPLY:
            result = runtime.base_speed * value
        else:
            result = value
        runtime.base_speed = min(
            selected.maximum_speed, max(selected.minimum_speed, result)
        )
        self._held_adjustments.add(binding_id)
        return True

    def release_base_adjustment(self, binding_id: Any) -> None:
        """Allow a later physical press of an adjustment binding to apply again."""
        self._held_adjustments.discard(binding_id)

    def press_dash(
        self,
        binding_id: Any,
        now: float,
        *,
        distance: Optional[float] = None,
        velocity_multiplier: Optional[float] = None,
    ) -> Optional[MotionSample]:
        """Return one immediate dash sample in the currently held direction.

        Exactly one distance choice is required.  ``distance`` is independent of
        speed modifiers.  ``velocity_multiplier`` scales the effective speed for
        the current output profile, so a value of one represents one second of
        travel at that speed.  Repeated presses from a binding are ignored until
        :meth:`release_dash` re-arms it.
        """
        self._observe_time(now)
        if (distance is None) == (velocity_multiplier is None):
            raise ValueError(
                "exactly one of distance or velocity_multiplier is required"
            )
        configured_value = distance
        description = "dash distance"
        if velocity_multiplier is not None:
            configured_value = velocity_multiplier
            description = "dash velocity multiplier"
        configured_value = _finite_number(configured_value, description)
        if configured_value <= 0.0:
            raise ValueError("{} must be positive".format(description))
        if binding_id in self._held_dashes:
            return None

        self._held_dashes.add(binding_id)
        profile = self._profile()
        dash_distance = configured_value
        if velocity_multiplier is not None:
            dash_distance *= self.effective_speed(profile.motion_config)
        sample = self._sample_for_directions(
            self._active_direction_set(), dash_distance, profile
        )
        if sample is not None:
            self._gesture_moved = True
        return sample

    def release_dash(self, binding_id: Any) -> None:
        """Re-arm a dash binding for its next physical press."""
        self._held_dashes.discard(binding_id)

    def set_mode(self, mode: OutputMode, now: float) -> None:
        """Set the persistent output mode."""
        self._observe_time(now)
        if not isinstance(mode, OutputMode):
            raise ValueError("mode must be an OutputMode")
        self._latched_mode = mode

    def toggle_mode(self, now: float) -> OutputMode:
        """Toggle the persistent output mode and return its new value."""
        self._observe_time(now)
        if self._latched_mode is OutputMode.POINTER:
            self._latched_mode = OutputMode.SCROLL
        else:
            self._latched_mode = OutputMode.POINTER
        return self._latched_mode

    def press_momentary_swap(self, binding_id: Any, now: float) -> None:
        """Temporarily invert the latched mode until all swap bindings release."""
        self._observe_time(now)
        self._momentary_swaps.add(binding_id)

    def release_momentary_swap(self, binding_id: Any, now: float) -> None:
        """Release one physical momentary mode-swap binding."""
        self._observe_time(now)
        self._momentary_swaps.discard(binding_id)

    def _has_held_direction(self) -> bool:
        return any(self._held_directions.values())

    def _direction_vector(self, directions: Set[Direction]) -> Tuple[float, float]:
        horizontal = float(
            (Direction.RIGHT in directions) - (Direction.LEFT in directions)
        )
        vertical = float(
            (Direction.DOWN in directions) - (Direction.UP in directions)
        )
        return horizontal, vertical

    def _active_direction_set(self) -> Set[Direction]:
        return {
            direction
            for direction, bindings in self._held_directions.items()
            if bindings
        }

    def _sample_for_directions(
        self,
        directions: Set[Direction],
        distance: float,
        profile: OutputProfile,
    ) -> Optional[MotionSample]:
        delta_x, delta_y = self._direction_vector(directions)
        if delta_x == 0.0 and delta_y == 0.0:
            return None
        if profile.motion_config.normalize_diagonal and delta_x and delta_y:
            diagonal_scale = 1.0 / math.sqrt(2.0)
            delta_x *= diagonal_scale
            delta_y *= diagonal_scale
        delta_x, delta_y = profile.transform(delta_x * distance, delta_y * distance)
        return MotionSample(profile.mode, delta_x, delta_y)

    def tick(self, now: float) -> Optional[MotionSample]:
        """Return motion since the previous tick, or ``None`` when idle.

        A queued tap nudge takes precedence and resets the elapsed-time baseline,
        preventing a delayed tick from also producing an unrelated catch-up move.
        """
        previous_tick = self._last_tick
        now = self._observe_time(now)
        if previous_tick is None:
            previous_tick = now
        self._last_tick = now
        if self._pending_samples:
            return self._pending_samples.pop(0)

        directions = self._active_direction_set()
        if not directions:
            return None
        elapsed = min(now - previous_tick, self.maximum_tick_elapsed)
        if elapsed <= 0.0:
            return None
        profile = self._profile()
        sample = self._sample_for_directions(
            directions,
            self.effective_speed(profile.motion_config) * elapsed,
            profile,
        )
        if sample is not None:
            self._gesture_moved = True
        return sample

    def reset(self, now: float) -> None:
        """Clear held/runtime state and restore configured defaults and mode."""
        now = _finite_number(now, "timestamp")
        for direction in Direction:
            self._held_directions[direction].clear()
        for config, runtime in self._runtime.items():
            runtime.base_speed = config.base_speed
            runtime.held_modifiers.clear()
            runtime.latched_modifiers.clear()
        self._held_adjustments.clear()
        self._held_dashes.clear()
        self._momentary_swaps.clear()
        self._gesture_directions.clear()
        self._gesture_moved = False
        self._pending_samples.clear()
        self._latched_mode = self.initial_mode
        self._last_tick = now
        self._last_time = now
