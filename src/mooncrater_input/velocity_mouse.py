"""Reusable state machine for velocity-based pointer and scroll movement."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Direction(Enum):
    LEFT = "left"
    RIGHT = "right"
    UP = "up"
    DOWN = "down"


class OutputMode(Enum):
    POINTER = "pointer"
    SCROLL = "scroll"


class ModifierKind(Enum):
    ADDITIVE = "additive"
    MULTIPLICATIVE = "multiplicative"


class BaseSpeedOperation(Enum):
    ADD = "add"
    MULTIPLY = "multiply"
    SET = "set"


@dataclass(frozen=True)
class SpeedModifier:
    kind: ModifierKind
    value: float


@dataclass(eq=False)
class MotionConfig:
    name: str
    base_speed: float
    minimum_speed: float
    maximum_speed: float
    modifiers: Dict[str, SpeedModifier] = field(default_factory=dict)
    normalize_diagonal: bool = True
    tap_nudge: float = 1.0


@dataclass(frozen=True)
class OutputProfile:
    mode: OutputMode
    motion_config: MotionConfig
    swap_axes: bool = False
    x_sign: int = 1
    y_sign: int = 1


@dataclass(frozen=True)
class MotionSample:
    mode: OutputMode
    delta_x: float
    delta_y: float


class MotionEngine:
    """Public API scaffold completed by the implementation commit."""

    def __init__(
        self,
        pointer_profile: OutputProfile,
        scroll_profile: OutputProfile,
        initial_mode: OutputMode = OutputMode.POINTER,
        maximum_tick_elapsed: float = 0.05,
    ) -> None:
        self.pointer_profile = pointer_profile
        self.scroll_profile = scroll_profile

    def __getattr__(self, name: str) -> Any:
        raise NotImplementedError(name)

    def press_direction(self, direction: Direction, binding_id: Any, now: float) -> None:
        raise NotImplementedError

    def tick(self, now: float) -> Optional[MotionSample]:
        raise NotImplementedError
