"""
HID Keyboard interface with evdev-like API.
Provides individual keyDown/keyUp events by scancode.
"""

import logging
from typing import Union, Set, Optional
from io import IOBase

from .keycodes import (
    HIDKeyCodes,
    HIDMouseCodes,
    CHAR_TO_SCANCODE,
    SHIFTED_CHARS,
    HID_KEY_SCANCODES,
    HID_MODIFIER_MASKS,
)
from .write import HIDWriter, HIDWriteError

logger = logging.getLogger(__name__)


class HIDKeyboard:
    """
    HID Keyboard interface with evdev-like API.

    Unlike zero-hid, this provides fine-grained control:
    - Individual keyDown/keyUp events by scancode
    - Manual state management (keys stay down until explicitly released)
    - Support for modifier combinations
    - State tracking to prevent duplicate events
    """

    def __init__(
        self, device_path: str = "/dev/hidg0", writer: Optional[HIDWriter] = None
    ):
        self.device_path = device_path
        self.writer = writer or HIDWriter()

        # State tracking
        self.pressed_keys: Set[int] = set()  # Currently pressed key scancodes
        self.modifier_state = 0  # Current modifier bitmask

        # Key mapping for convenience
        self.keycodes = HIDKeyCodes

        # Modifier scancode to bitmask mapping
        self.modifier_scancode_to_bitmask = {
            HID_KEY_SCANCODES["KEY_LEFTCTRL"]: HID_MODIFIER_MASKS["MOD_LCTRL"],
            HID_KEY_SCANCODES["KEY_LEFTSHIFT"]: HID_MODIFIER_MASKS["MOD_LSHIFT"],
            HID_KEY_SCANCODES["KEY_LEFTALT"]: HID_MODIFIER_MASKS["MOD_LALT"],
            HID_KEY_SCANCODES["KEY_LEFTMETA"]: HID_MODIFIER_MASKS["MOD_LMETA"],
            HID_KEY_SCANCODES["KEY_RIGHTCTRL"]: HID_MODIFIER_MASKS["MOD_RCTRL"],
            HID_KEY_SCANCODES["KEY_RIGHTSHIFT"]: HID_MODIFIER_MASKS["MOD_RSHIFT"],
            HID_KEY_SCANCODES["KEY_RIGHTALT"]: HID_MODIFIER_MASKS["MOD_RALT"],
            HID_KEY_SCANCODES["KEY_RIGHTMETA"]: HID_MODIFIER_MASKS["MOD_RMETA"],
        }

    def key_down(self, scancode: int) -> bool:
        """
        Press a key down by scancode.

        Args:
            scancode: HID scancode (use HIDKeyCodes constants)

        Returns:
            True if key state changed, False if already pressed
        """
        # Check if this is a modifier key
        if scancode in self.modifier_scancode_to_bitmask:
            modifier_bit = self.modifier_scancode_to_bitmask[scancode]
            if self.modifier_state & modifier_bit:
                return False  # Already pressed
            self.modifier_state |= modifier_bit
            self._send_keyboard_report()
            return True

        # Regular key handling
        if scancode in self.pressed_keys:
            return False  # Already pressed

        self.pressed_keys.add(scancode)
        self._send_keyboard_report()
        return True

    def key_up(self, scancode: int) -> bool:
        """
        Release a key by scancode.

        Args:
            scancode: HID scancode (use HIDKeyCodes constants)

        Returns:
            True if key state changed, False if not pressed
        """
        # Check if this is a modifier key
        if scancode in self.modifier_scancode_to_bitmask:
            modifier_bit = self.modifier_scancode_to_bitmask[scancode]
            if not (self.modifier_state & modifier_bit):
                return False  # Not pressed
            self.modifier_state &= ~modifier_bit
            self._send_keyboard_report()
            return True

        # Regular key handling
        if scancode not in self.pressed_keys:
            return False  # Not pressed

        self.pressed_keys.remove(scancode)
        self._send_keyboard_report()
        return True

    def key_press(self, scancode: int, delay: float = 0.01):
        """
        Send a key press (down then up) with a small delay.

        Note: For modifier keys, this will quickly press and release the modifier,
        which may not be the desired behavior. Consider using key_down/key_up separately
        for modifiers that need to be held.

        Args:
            scancode: HID scancode (use HIDKeyCodes constants)
            delay: Delay between key down and key up in seconds (default: 0.01)
        """
        import time

        self.key_down(scancode)
        if delay > 0:
            time.sleep(delay)
        self.key_up(scancode)

    def modifier_down(self, modifier: int) -> bool:
        """
        Press a modifier key down.

        Args:
            modifier: Modifier bitmask (use HIDKeyCodes.MOD_* constants)

        Returns:
            True if modifier state changed
        """
        old_state = self.modifier_state
        self.modifier_state |= modifier

        if old_state != self.modifier_state:
            self._send_keyboard_report()
            return True
        return False

    def modifier_up(self, modifier: int) -> bool:
        """
        Release a modifier key.

        Args:
            modifier: Modifier bitmask (use HIDKeyCodes.MOD_* constants)

        Returns:
            True if modifier state changed
        """
        old_state = self.modifier_state
        self.modifier_state &= ~modifier

        if old_state != self.modifier_state:
            self._send_keyboard_report()
            return True
        return False

    def modifier_press(self, modifier: int):
        """
        Send a modifier press (down then up).

        Args:
            modifier: Modifier bitmask (use HIDKeyCodes.MOD_* constants)
        """
        self.modifier_down(modifier)
        self.modifier_up(modifier)

    def release_all(self):
        """Release all keys and modifiers."""
        self.pressed_keys.clear()
        self.modifier_state = 0
        self._send_keyboard_report()

    def type_string(self, text: str, delay: float = 0.0):
        """
        Type a string of text (simplified, basic ASCII only).

        Args:
            text: Text to type
            delay: Delay between keystrokes in seconds
        """
        import time

        for char in text:
            scancode = self._char_to_scancode(char)
            if scancode:
                # Handle shifted characters
                needs_shift = self._char_needs_shift(char)
                if needs_shift:
                    self.modifier_down(HIDKeyCodes.MOD_LSHIFT)

                self.key_press(scancode)

                if needs_shift:
                    self.modifier_up(HIDKeyCodes.MOD_LSHIFT)

                if delay > 0:
                    time.sleep(delay)

    def get_pressed_keys(self) -> Set[int]:
        """Get set of currently pressed key scancodes."""
        return self.pressed_keys.copy()

    def get_modifier_state(self) -> int:
        """Get current modifier state bitmask."""
        return self.modifier_state

    def is_key_pressed(self, scancode: int) -> bool:
        """Check if a key is currently pressed."""
        return scancode in self.pressed_keys

    def is_modifier_pressed(self, modifier: int) -> bool:
        """Check if a modifier is currently pressed."""
        return bool(self.modifier_state & modifier)

    def _send_keyboard_report(self):
        """Send the current keyboard state as HID report."""
        # HID keyboard report format:
        # Byte 0: Modifier keys bitmask
        # Byte 1: Reserved (always 0)
        # Bytes 2-7: Up to 6 pressed key scancodes

        report = [0] * 8
        report[0] = self.modifier_state
        report[1] = 0  # Reserved

        # Add up to 6 pressed keys
        pressed_list = list(self.pressed_keys)[:6]
        for i, scancode in enumerate(pressed_list):
            report[2 + i] = scancode

        try:
            self.writer.write(self.device_path, report)
        except HIDWriteError as e:
            logger.error(f"Failed to send keyboard report: {e}")
            raise

    def _char_to_scancode(self, char: str) -> Optional[int]:
        """Convert character to HID scancode."""
        return CHAR_TO_SCANCODE.get(char)

    def _char_needs_shift(self, char: str) -> bool:
        """Check if character requires shift modifier."""
        return char in SHIFTED_CHARS

    def close(self):
        """Clean up resources."""
        self.release_all()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
