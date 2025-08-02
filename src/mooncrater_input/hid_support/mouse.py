"""
HID Mouse interface with evdev-like API.
Provides individual button down/up events and precise movement control.
"""

import logging
from typing import Union, Set, Optional
from io import IOBase

from .keycodes import HIDMouseCodes
from .write import HIDWriter, HIDWriteError

logger = logging.getLogger(__name__)


class HIDMouse:
    """
    HID Mouse interface with evdev-like API.

    Provides fine-grained control:
    - Individual button down/up events
    - Separate relative and absolute movement modes
    - Precise scroll control
    - State tracking to prevent duplicate events
    """

    def __init__(
        self,
        device_path: str = "/dev/hidg1",
        absolute_mode: bool = False,
        writer: Optional[HIDWriter] = None,
    ):
        self.device_path = device_path
        self.absolute_mode = absolute_mode
        self.writer = writer or HIDWriter()

        # State tracking
        self.pressed_buttons: Set[int] = set()  # Currently pressed button bitmasks
        self.button_state = 0  # Current button bitmask

        # Position tracking for absolute mode
        self.abs_x = 0
        self.abs_y = 0

        # Button codes for convenience
        self.buttons = HIDMouseCodes

    def button_down(self, button: int) -> bool:
        """
        Press a mouse button down.

        Args:
            button: Button bitmask (use HIDMouseCodes.BTN_* constants)

        Returns:
            True if button state changed, False if already pressed
        """
        if button & self.button_state:
            return False  # Already pressed

        self.button_state |= button
        self._send_mouse_report()
        return True

    def button_up(self, button: int) -> bool:
        """
        Release a mouse button.

        Args:
            button: Button bitmask (use HIDMouseCodes.BTN_* constants)

        Returns:
            True if button state changed, False if not pressed
        """
        if not (button & self.button_state):
            return False  # Not pressed

        self.button_state &= ~button
        self._send_mouse_report()
        return True

    def button_press(self, button: int):
        """
        Send a button press (down then up).

        Args:
            button: Button bitmask (use HIDMouseCodes.BTN_* constants)
        """
        self.button_down(button)
        self.button_up(button)

    def left_click(self, hold: bool = False):
        """Click left mouse button."""
        if hold:
            self.button_down(HIDMouseCodes.BTN_LEFT)
        else:
            self.button_press(HIDMouseCodes.BTN_LEFT)

    def right_click(self, hold: bool = False):
        """Click right mouse button."""
        if hold:
            self.button_down(HIDMouseCodes.BTN_RIGHT)
        else:
            self.button_press(HIDMouseCodes.BTN_RIGHT)

    def middle_click(self, hold: bool = False):
        """Click middle mouse button."""
        if hold:
            self.button_down(HIDMouseCodes.BTN_MIDDLE)
        else:
            self.button_press(HIDMouseCodes.BTN_MIDDLE)

    def move_relative(self, delta_x: int, delta_y: int):
        """
        Move mouse cursor relatively.

        Args:
            delta_x: X movement (-127 to 127)
            delta_y: Y movement (-127 to 127)
        """
        if self.absolute_mode:
            raise ValueError("Mouse is in absolute mode, use move_absolute() instead")

        # Clamp values to valid range
        delta_x = max(-127, min(127, delta_x))
        delta_y = max(-127, min(127, delta_y))

        self._send_mouse_report(delta_x=delta_x, delta_y=delta_y)

    def move_absolute(self, x: int, y: int):
        """
        Move mouse cursor to absolute position.

        Args:
            x: Absolute X position (0 to 65535)
            y: Absolute Y position (0 to 65535)
        """
        if not self.absolute_mode:
            raise ValueError("Mouse is in relative mode, use move_relative() instead")

        # Clamp values to valid range
        x = max(0, min(65535, x))
        y = max(0, min(65535, y))

        self.abs_x = x
        self.abs_y = y
        self._send_mouse_report()

    def scroll_vertical(self, delta: int):
        """
        Scroll vertically.

        Args:
            delta: Scroll amount (-127 to 127, positive = up)
        """
        delta = max(-127, min(127, delta))
        self._send_mouse_report(scroll_y=delta)

    def scroll_horizontal(self, delta: int):
        """
        Scroll horizontally.

        Args:
            delta: Scroll amount (-127 to 127, positive = right)
        """
        delta = max(-127, min(127, delta))
        self._send_mouse_report(scroll_x=delta)

    def scroll(self, delta_x: int = 0, delta_y: int = 0):
        """
        Scroll in both directions.

        Args:
            delta_x: Horizontal scroll (-127 to 127, positive = right)
            delta_y: Vertical scroll (-127 to 127, positive = up)
        """
        delta_x = max(-127, min(127, delta_x))
        delta_y = max(-127, min(127, delta_y))
        self._send_mouse_report(scroll_x=delta_x, scroll_y=delta_y)

    def release_all(self):
        """Release all mouse buttons."""
        self.button_state = 0
        self._send_mouse_report()

    def get_button_state(self) -> int:
        """Get current button state bitmask."""
        return self.button_state

    def is_button_pressed(self, button: int) -> bool:
        """Check if a button is currently pressed."""
        return bool(self.button_state & button)

    def get_position(self) -> tuple:
        """Get current absolute position (only valid in absolute mode)."""
        if not self.absolute_mode:
            raise ValueError("Position tracking only available in absolute mode")
        return (self.abs_x, self.abs_y)

    def _send_mouse_report(
        self, delta_x: int = 0, delta_y: int = 0, scroll_x: int = 0, scroll_y: int = 0
    ):
        """Send the current mouse state as HID report."""

        if self.absolute_mode:
            # Absolute mouse report format (7 bytes):
            # Byte 0: Button state bitmask
            # Bytes 1-2: X position (little endian)
            # Bytes 3-4: Y position (little endian)
            # Byte 5: Vertical scroll
            # Byte 6: Horizontal scroll
            report = [
                self.button_state,
                self.abs_x & 0xFF,
                (self.abs_x >> 8) & 0xFF,
                self.abs_y & 0xFF,
                (self.abs_y >> 8) & 0xFF,
                scroll_y & 0xFF,
                scroll_x & 0xFF,
            ]
        else:
            # Relative mouse report format (5 bytes):
            # Byte 0: Button state bitmask
            # Byte 1: X delta (signed)
            # Byte 2: Y delta (signed)
            # Byte 3: Vertical scroll (signed)
            # Byte 4: Horizontal scroll (signed)
            report = [
                self.button_state,
                delta_x & 0xFF,
                delta_y & 0xFF,
                scroll_y & 0xFF,
                scroll_x & 0xFF,
            ]

        try:
            self.writer.write(self.device_path, report)
        except HIDWriteError as e:
            logger.error(f"Failed to send mouse report: {e}")
            raise

    def close(self):
        """Clean up resources."""
        self.release_all()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
