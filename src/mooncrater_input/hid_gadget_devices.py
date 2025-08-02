#!/usr/bin/env python3

"""
USB HID Gadget backend for Mooncrater Input.
Similar to evdev_output.py but uses USB HID gadgets instead of evdev UInput devices.


NOTE - you need to set up the /dev/hidg* devices before this will work.
"""

from typing import List, Optional, Dict, Any, Union
import logging
import os
import subprocess
import tempfile
import atexit
import signal

# Set up logging
logger = logging.getLogger(__name__)


class HIDGadgetDeviceTag:
    """Manages a set of HID gadget devices under a single logical tag."""

    def __init__(
        self,
        tag: str,
        keyboard_device: str = "/dev/hidg0",
        mouse_device: str = "/dev/hidg1",
        absolute_mouse_device: str = "/dev/hidg2",
        gadget_dir: Optional[str] = None,
        remove_hidg_on_destruction: bool = False,
    ):
        self.tag = tag
        self.keyboard_device = keyboard_device
        self.mouse_device = mouse_device
        self.absolute_mouse_device = absolute_mouse_device
        self.gadget_dir = gadget_dir
        self.remove_hidg_on_destruction = remove_hidg_on_destruction

        # Import and initialize HID devices
        self._hid_support = None
        self._keyboard = None
        self._mouse = None
        self._absolute_mouse = None
        self._json_translator = None
        self.connection_status = "disconnected"
        self.last_error = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3

        # Try to initialize HID devices, but don't fail construction if it doesn't work
        try:
            self._ensure_hid_loaded()
            self.connection_status = "connected"
        except Exception as e:
            logger.error(f"Failed to initialize HID gadget devices for tag '{tag}': {e}")
            self.last_error = str(e)
            self.connection_status = "failed"

    def _ensure_hid_loaded(self):
        """Load HID support modules when first needed."""
        if self._hid_support is None:
            try:
                from .hid_support import HIDKeyboard, HIDMouse, HIDKeyCodes
                from .hid_support.keycodes import HIDMouseCodes

                # Create HID devices
                self._keyboard = HIDKeyboard(self.keyboard_device)
                self._mouse = HIDMouse(self.mouse_device, absolute_mode=False)
                self._absolute_mouse = HIDMouse(
                    self.absolute_mouse_device, absolute_mode=True
                )

                # Create JSON translator
                self._json_translator = self.JsonToHIDTranslator(
                    HIDKeyCodes, HIDMouseCodes
                )

                self._hid_support = {
                    "keyboard": self._keyboard,
                    "mouse": self._mouse,
                    "absolute_mouse": self._absolute_mouse,
                    "keycodes": HIDKeyCodes,
                    "mousecodes": HIDMouseCodes,
                }

                logger.info(f"HID gadget devices initialized for tag '{self.tag}'")

            except ImportError as e:
                raise ImportError(
                    f"hid-support package is required for HID gadget outputs. Error: {e}"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to initialize HID gadget devices: {e}")

    def send_json_event(self, json_event: dict):
        """Send a JSON event by translating to HID events."""
        try:
            # Check connection status and try to reconnect if needed
            if not self.is_connected():
                if not self._try_reconnect():
                    logger.warning(f"HID gadget device '{self.tag}' not connected, dropping event")
                    return

            if not self._json_translator:
                logger.warning(f"HID gadget device '{self.tag}' translator not available")
                return

            self._json_translator.translate_and_send(json_event, self._hid_support)

        except Exception as e:
            logger.error(f"Error sending event to HID gadget device '{self.tag}': {e}")
            self.connection_status = "failed"
            self.last_error = str(e)

    # def send_keyboard_event(self, event_type: str, scancode: int, **kwargs):
    #     """Send a keyboard event directly."""
    #     if not self._keyboard:
    #         return

    #     print(f"hid send_keyboard_event with {event_type}, hid {scancode=}")
    #     try:
    #         if event_type == "key_down":
    #             self._keyboard.key_down(scancode)
    #         elif event_type == "key_up":
    #             self._keyboard.key_up(scancode)
    #         elif event_type == "key_press":
    #             self._keyboard.key_press(scancode)
    #         else:
    #             logger.warning(f"Unknown keyboard event type: {event_type}")
    #     except Exception as e:
    #         logger.error(f"Failed to send keyboard event: {e}")

    # def send_mouse_event(self, event_type: str, **kwargs):
    #     """Send a mouse event directly."""
    #     mouse = self._mouse
    #     if kwargs.get('absolute', False):
    #         mouse = self._absolute_mouse

    #     if not mouse:
    #         return

    #     try:
    #         if event_type == "button_down":
    #             mouse.button_down(kwargs.get('button', 0))
    #         elif event_type == "button_up":
    #             mouse.button_up(kwargs.get('button', 0))
    #         elif event_type == "button_press":
    #             mouse.button_press(kwargs.get('button', 0))
    #         elif event_type == "move_relative":
    #             mouse.move_relative(kwargs.get('delta_x', 0), kwargs.get('delta_y', 0))
    #         elif event_type == "move_absolute":
    #             mouse.move_absolute(kwargs.get('x', 0), kwargs.get('y', 0))
    #         elif event_type == "scroll":
    #             mouse.scroll(kwargs.get('delta_x', 0), kwargs.get('delta_y', 0))
    #         else:
    #             logger.warning(f"Unknown mouse event type: {event_type}")
    #     except Exception as e:
    #         logger.error(f"Failed to send mouse event: {e}")

    def release_all(self):
        """Release all keys and buttons."""
        try:
            if self._keyboard:
                self._keyboard.release_all()
            if self._mouse:
                self._mouse.release_all()
            if self._absolute_mouse:
                self._absolute_mouse.release_all()
        except Exception as e:
            logger.error(f"Failed to release all inputs for HID gadget '{self.tag}': {e}")
            self.connection_status = "failed"
            self.last_error = str(e)

    def is_connected(self) -> bool:
        """Check if HID gadget devices are connected and working."""
        return (self.connection_status == "connected" and
                self._hid_support is not None and
                self._keyboard is not None and
                self._mouse is not None and
                self._absolute_mouse is not None)

    def get_connection_status(self) -> dict:
        """Get detailed connection status information."""
        return {
            "status": self.connection_status,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "keyboard_device": self.keyboard_device,
            "mouse_device": self.mouse_device,
            "absolute_mouse_device": self.absolute_mouse_device
        }

    def _try_reconnect(self) -> bool:
        """Try to reconnect HID gadget devices."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts reached for HID gadget device '{self.tag}'")
            return False

        self.reconnect_attempts += 1
        logger.info(f"Attempting to reconnect HID gadget device '{self.tag}' (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")

        try:
            # Close existing devices
            self.close()

            # Clear state
            self._hid_support = None
            self._keyboard = None
            self._mouse = None
            self._absolute_mouse = None
            self._json_translator = None

            # Try to reload HID support
            self._ensure_hid_loaded()

            self.connection_status = "connected"
            self.last_error = None
            self.reconnect_attempts = 0

            logger.info(f"Successfully reconnected HID gadget device '{self.tag}'")
            return True

        except Exception as e:
            logger.error(f"Failed to reconnect HID gadget device '{self.tag}': {e}")
            self.connection_status = "failed"
            self.last_error = str(e)
            return False

    def close(self):
        """Close all HID gadget devices."""
        try:
            if self._keyboard:
                self._keyboard.close()
            if self._mouse:
                self._mouse.close()
            if self._absolute_mouse:
                self._absolute_mouse.close()
        except Exception as e:
            logger.error(f"Failed to close HID devices for '{self.tag}': {e}")
        finally:
            self.connection_status = "disconnected"
            self._hid_support = None
            self._keyboard = None
            self._mouse = None
            self._absolute_mouse = None

    class JsonToHIDTranslator:
        """Translates JSON events to HID gadget events."""

        def __init__(self, keycodes_module, mousecodes_module):
            self.keycodes = keycodes_module
            self.mousecodes = mousecodes_module

        def translate_and_send(self, json_event: dict, hid_devices: dict):
            """Translate a JSON event and send it to appropriate HID device."""

            # Handle eventList - recursively process multiple events
            if json_event.get("type") == "eventList":
                event_list = json_event.get("events", [])
                for sub_event in event_list:
                    self.translate_and_send(sub_event, hid_devices)
                return

            # Determine category from category field or event type
            category = self._determine_category(json_event)

            # Route to appropriate handler
            if category == "keyboard":
                self._handle_keyboard_event(json_event, hid_devices["keyboard"])
            elif category == "mouse":
                # Determine if absolute or relative mouse
                if json_event.get("absolute", False) or json_event.get("type") in [
                    "mouseAbs"
                ]:
                    self._handle_mouse_event(
                        json_event, hid_devices["absolute_mouse"], absolute=True
                    )
                else:
                    self._handle_mouse_event(
                        json_event, hid_devices["mouse"], absolute=False
                    )
            elif category == "touchpad":
                # Treat touchpad events as absolute mouse for now
                self._handle_mouse_event(
                    json_event, hid_devices["absolute_mouse"], absolute=True
                )

        def _handle_keyboard_event(self, json_event: dict, keyboard):
            """Handle keyboard events."""
            event_type = json_event.get("type", "")

            # Handle typeQwertyString - convert string to multiple keyPress events
            if event_type == "typeQwertyString":
                string_to_type = json_event.get("string", "")
                keyboard.type_string(string_to_type)
                return

            # Get scancode with priority: keyChar -> keyName -> scancode field
            scancode = None

            # First try keyChar
            if "keyChar" in json_event and json_event["keyChar"]:
                scancode = self._char_to_hid_scancode(json_event["keyChar"])

            # Then try keyName if keyChar didn't work
            if not scancode and "keyName" in json_event and json_event["keyName"]:
                scancode = self._keyname_to_hid_scancode(json_event["keyName"])

            # Finally try direct scancode field
            # if not scancode and 'scancode' in json_event:
            #     # Convert evdev scancode to HID scancode if needed
            #     scancode = self._evdev_to_hid_scancode(json_event['scancode'])

            print(f"hid _handle_keyboard_event with {event_type}, hid {scancode=}")

            if scancode:
                if event_type == "keyDown":
                    keyboard.key_down(scancode)
                elif event_type == "keyUp":
                    keyboard.key_up(scancode)
                elif event_type == "keyPress":
                    keyboard.key_press(scancode)

        def _handle_mouse_event(self, json_event: dict, mouse, absolute: bool = False):
            """Handle mouse events."""
            event_type = json_event.get("type", "")

            if event_type in ["mouseDown", "mouseUp"]:
                button = json_event.get("button")
                button_code = {
                    "left": self.mousecodes.BTN_LEFT,
                    "right": self.mousecodes.BTN_RIGHT,
                    "middle": self.mousecodes.BTN_MIDDLE,
                    "back": self.mousecodes.BTN_BACK,
                    "forward": self.mousecodes.BTN_FORWARD,
                }.get(button, 0)

                if button_code:
                    if event_type == "mouseDown":
                        mouse.button_down(button_code)
                    else:
                        mouse.button_up(button_code)

            elif event_type == "mouseRel":
                if not absolute:
                    delta_x = json_event.get("deltaX", 0)
                    delta_y = json_event.get("deltaY", 0)
                    if delta_x != 0 or delta_y != 0:
                        mouse.move_relative(delta_x, delta_y)

            elif event_type == "mouseAbs":
                if absolute:
                    x = json_event.get("x", 0)
                    y = json_event.get("y", 0)
                    mouse.move_absolute(x, y)

            elif event_type in ["scroll", "smoothScroll"]:
                # Handle both regular and smooth scroll
                delta_x = json_event.get("deltaX", 0)
                delta_y = json_event.get("deltaY", 0)

                # For smooth scroll, try raw values first
                if event_type == "smoothScroll":
                    raw_delta_x = json_event.get("rawDeltaX")
                    raw_delta_y = json_event.get("rawDeltaY")

                    if raw_delta_x is not None:
                        delta_x = int(raw_delta_x / 120)  # Convert raw to discrete
                    elif delta_x != 0:
                        delta_x = int(delta_x)

                    if raw_delta_y is not None:
                        delta_y = int(raw_delta_y / 120)  # Convert raw to discrete
                    elif delta_y != 0:
                        delta_y = int(delta_y)

                if delta_x != 0 or delta_y != 0:
                    mouse.scroll(delta_x, delta_y)

            # Handle touchpad events as absolute mouse
            elif event_type in ["touchDown", "touchUp"]:
                # Map touch events to left button for now
                if event_type == "touchDown":
                    mouse.button_down(self.mousecodes.BTN_LEFT)
                else:
                    mouse.button_up(self.mousecodes.BTN_LEFT)

            elif event_type == "touchpadAbs" and absolute:
                # Map touchpad absolute coordinates to mouse absolute
                axis = json_event.get("axis")
                value = json_event.get("value", 0)

                if axis == "x":
                    # Scale to mouse coordinate range (assuming touchpad range 0-1024)
                    x = int((value / 1024.0) * 65535)
                    current_pos = (
                        mouse.get_position()
                        if hasattr(mouse, "get_position")
                        else (0, 0)
                    )
                    mouse.move_absolute(x, current_pos[1])
                elif axis == "y":
                    # Scale to mouse coordinate range (assuming touchpad range 0-768)
                    y = int((value / 768.0) * 65535)
                    current_pos = (
                        mouse.get_position()
                        if hasattr(mouse, "get_position")
                        else (0, 0)
                    )
                    mouse.move_absolute(current_pos[0], y)

        def _char_to_hid_scancode(self, char: str) -> Optional[int]:
            """Convert character to HID scancode."""
            # Use the mapping from keyboard.py
            char_map = {
                # Letters (both cases map to same scancode)
                "a": self.keycodes.KEY_A,
                "A": self.keycodes.KEY_A,
                "b": self.keycodes.KEY_B,
                "B": self.keycodes.KEY_B,
                "c": self.keycodes.KEY_C,
                "C": self.keycodes.KEY_C,
                "d": self.keycodes.KEY_D,
                "D": self.keycodes.KEY_D,
                "e": self.keycodes.KEY_E,
                "E": self.keycodes.KEY_E,
                "f": self.keycodes.KEY_F,
                "F": self.keycodes.KEY_F,
                "g": self.keycodes.KEY_G,
                "G": self.keycodes.KEY_G,
                "h": self.keycodes.KEY_H,
                "H": self.keycodes.KEY_H,
                "i": self.keycodes.KEY_I,
                "I": self.keycodes.KEY_I,
                "j": self.keycodes.KEY_J,
                "J": self.keycodes.KEY_J,
                "k": self.keycodes.KEY_K,
                "K": self.keycodes.KEY_K,
                "l": self.keycodes.KEY_L,
                "L": self.keycodes.KEY_L,
                "m": self.keycodes.KEY_M,
                "M": self.keycodes.KEY_M,
                "n": self.keycodes.KEY_N,
                "N": self.keycodes.KEY_N,
                "o": self.keycodes.KEY_O,
                "O": self.keycodes.KEY_O,
                "p": self.keycodes.KEY_P,
                "P": self.keycodes.KEY_P,
                "q": self.keycodes.KEY_Q,
                "Q": self.keycodes.KEY_Q,
                "r": self.keycodes.KEY_R,
                "R": self.keycodes.KEY_R,
                "s": self.keycodes.KEY_S,
                "S": self.keycodes.KEY_S,
                "t": self.keycodes.KEY_T,
                "T": self.keycodes.KEY_T,
                "u": self.keycodes.KEY_U,
                "U": self.keycodes.KEY_U,
                "v": self.keycodes.KEY_V,
                "V": self.keycodes.KEY_V,
                "w": self.keycodes.KEY_W,
                "W": self.keycodes.KEY_W,
                "x": self.keycodes.KEY_X,
                "X": self.keycodes.KEY_X,
                "y": self.keycodes.KEY_Y,
                "Y": self.keycodes.KEY_Y,
                "z": self.keycodes.KEY_Z,
                "Z": self.keycodes.KEY_Z,
                # Numbers
                "0": self.keycodes.KEY_0,
                "1": self.keycodes.KEY_1,
                "2": self.keycodes.KEY_2,
                "3": self.keycodes.KEY_3,
                "4": self.keycodes.KEY_4,
                "5": self.keycodes.KEY_5,
                "6": self.keycodes.KEY_6,
                "7": self.keycodes.KEY_7,
                "8": self.keycodes.KEY_8,
                "9": self.keycodes.KEY_9,
                # Basic characters
                " ": self.keycodes.KEY_SPACE,
                "\t": self.keycodes.KEY_TAB,
                "\n": self.keycodes.KEY_ENTER,
                "\r": self.keycodes.KEY_ENTER,
            }
            return char_map.get(char)

        def _keyname_to_hid_scancode(self, keyname: str) -> Optional[int]:
            """Convert keyName string to HID scancode."""
            # Handle SCANCODE_* format for custom scancodes (e.g., "SCANCODE_175")
            if keyname.startswith("SCANCODE_"):
                try:
                    scancode_num = int(keyname[9:])  # Extract number after "SCANCODE_"
                    if 0 <= scancode_num <= 255:
                        return scancode_num
                except ValueError:
                    pass  # Invalid number format, fall through to other methods

            # Handle standard HID key names
            if hasattr(self.keycodes, keyname):
                return getattr(self.keycodes, keyname)

            # Handle common key name variants
            keyname_variants = {
                # Letters
                "A": self.keycodes.KEY_A,
                "B": self.keycodes.KEY_B,
                "C": self.keycodes.KEY_C,
                "D": self.keycodes.KEY_D,
                "E": self.keycodes.KEY_E,
                "F": self.keycodes.KEY_F,
                "G": self.keycodes.KEY_G,
                "H": self.keycodes.KEY_H,
                "I": self.keycodes.KEY_I,
                "J": self.keycodes.KEY_J,
                "K": self.keycodes.KEY_K,
                "L": self.keycodes.KEY_L,
                "M": self.keycodes.KEY_M,
                "N": self.keycodes.KEY_N,
                "O": self.keycodes.KEY_O,
                "P": self.keycodes.KEY_P,
                "Q": self.keycodes.KEY_Q,
                "R": self.keycodes.KEY_R,
                "S": self.keycodes.KEY_S,
                "T": self.keycodes.KEY_T,
                "U": self.keycodes.KEY_U,
                "V": self.keycodes.KEY_V,
                "W": self.keycodes.KEY_W,
                "X": self.keycodes.KEY_X,
                "Y": self.keycodes.KEY_Y,
                "Z": self.keycodes.KEY_Z,
                # Numbers
                "0": self.keycodes.KEY_0,
                "1": self.keycodes.KEY_1,
                "2": self.keycodes.KEY_2,
                "3": self.keycodes.KEY_3,
                "4": self.keycodes.KEY_4,
                "5": self.keycodes.KEY_5,
                "6": self.keycodes.KEY_6,
                "7": self.keycodes.KEY_7,
                "8": self.keycodes.KEY_8,
                "9": self.keycodes.KEY_9,
                # Common keys
                "SPACE": self.keycodes.KEY_SPACE,
                "ENTER": self.keycodes.KEY_ENTER,
                "TAB": self.keycodes.KEY_TAB,
                "BACKSPACE": self.keycodes.KEY_BACKSPACE,
                "DELETE": self.keycodes.KEY_DELETE,
                "ESC": self.keycodes.KEY_ESC,
                "ESCAPE": self.keycodes.KEY_ESC,
                # Arrow keys
                "UP": self.keycodes.KEY_UP,
                "DOWN": self.keycodes.KEY_DOWN,
                "LEFT": self.keycodes.KEY_LEFT,
                "RIGHT": self.keycodes.KEY_RIGHT,
                # Function keys
                "F1": self.keycodes.KEY_F1,
                "F2": self.keycodes.KEY_F2,
                "F3": self.keycodes.KEY_F3,
                "F4": self.keycodes.KEY_F4,
                "F5": self.keycodes.KEY_F5,
                "F6": self.keycodes.KEY_F6,
                "F7": self.keycodes.KEY_F7,
                "F8": self.keycodes.KEY_F8,
                "F9": self.keycodes.KEY_F9,
                "F10": self.keycodes.KEY_F10,
                "F11": self.keycodes.KEY_F11,
                "F12": self.keycodes.KEY_F12,
            }

            return keyname_variants.get(keyname.upper())

        def _evdev_to_hid_scancode(self, evdev_scancode: int) -> Optional[int]:
            """Convert evdev scancode to HID scancode (basic mapping)."""
            # This is a simplified mapping - in practice you'd want a complete lookup table
            # For now, assume the scancodes are similar enough for basic keys
            return evdev_scancode
            # if 4 <= evdev_scancode <= 57:  # Basic HID scancode range
            #     return evdev_scancode
            # return None

        def _determine_category(self, json_event: dict) -> str:
            """Determine the event category from category field or event type."""
            # First try explicit category field
            if "category" in json_event and json_event["category"]:
                return json_event["category"]

            # Fallback: determine category from event type
            event_type = json_event.get("type", "")

            # Keyboard event types
            keyboard_types = {
                "keyUp",
                "keyDown",
                "keyPress",
                "keyRepeat",
                "typeCharQwerty",
                "keyDownQwerty",
                "keyUpQwerty",
                "typeStringQwerty",
                "typeQwertyString",
            }

            # Mouse event types
            mouse_types = {
                "mouseUp",
                "mouseDown",
                "mouseRel",
                "mouseAbs",
                "scroll",
                "smoothScroll",
                "mouseRelative",
                "mouseAbsolute",
            }

            # Touchpad event types
            touchpad_types = {
                "touchUp",
                "touchDown",
                "touchpadAbs",
                "touchpadRel",
                "touchpadAbsolute",
                "touchpadRelative",
            }

            if event_type in keyboard_types:
                return "keyboard"
            elif event_type in mouse_types:
                return "mouse"
            elif event_type in touchpad_types:
                return "touchpad"

            # Default fallback based on fields
            if "keyChar" in json_event or "keyName" in json_event:
                return "keyboard"
            elif "button" in json_event:
                return "mouse"

            return "keyboard"  # Final fallback


def init_usb_gadget(
    manufacturer_name: str,
    product_name: str,
    serial_number: str,
    id_vendor: Union[str, int],
    id_product: Union[str, int],
    gadget_dir: str = "g1",
):
    """
    Initialize USB HID gadget devices.

    Creates keyboard, relative mouse, and absolute mouse HID gadgets.

    Gadget setup based on https://github.com/thewh1teagle/zero-hid/blob/6e99b87e5d4c36382a193824e1fbda6f3d85a6e6/usb_gadget/init_usb_gadget which is LGPL3+ licensed.

    Args:
        manufacturer_name: Manufacturer name string
        product_name: Product name string
        serial_number: Serial number string
        id_vendor: Vendor ID as hex string (e.g. "0x1234") or integer
        id_product: Product ID as hex string (e.g. "0xabcd") or integer
        gadget_dir: Directory name for the gadget (default: "g1")
    """

    # Validate and convert vendor/product IDs
    def validate_hex_id(value: Union[str, int], name: str) -> str:
        if isinstance(value, str):
            if not value.startswith("0x") or len(value) != 6:
                raise ValueError(
                    f"{name} string must be in format '0x1234' (6 characters)"
                )
            try:
                int(value, 16)
            except ValueError:
                raise ValueError(f"{name} string '{value}' is not valid hexadecimal")
            return value
        elif isinstance(value, int):
            if not (0 <= value <= 0xFFFF):
                raise ValueError(
                    f"{name} integer must be in range 0-65535 (0x0000-0xFFFF)"
                )
            return f"0x{value:04x}"
        else:
            raise ValueError(f"{name} must be a hex string or integer")

    vendor_hex = validate_hex_id(id_vendor, "id_vendor")
    product_hex = validate_hex_id(id_product, "id_product")
    try:
        # Load libcomposite module
        subprocess.run(["modprobe", "libcomposite"], check=True)

        # Navigate to gadget config directory
        full_gadget_dir = f"/sys/kernel/config/usb_gadget/{gadget_dir}"
        os.makedirs(full_gadget_dir, exist_ok=True)
        os.chdir(full_gadget_dir)

        # Set device IDs
        with open("idVendor", "w") as f:
            f.write(vendor_hex)
        with open("idProduct", "w") as f:
            f.write(product_hex)
        with open("bcdDevice", "w") as f:
            f.write("0x0100")  # v1.0.0
        with open("bcdUSB", "w") as f:
            f.write("0x0200")  # USB2

        # Set device strings
        strings_dir = "strings/0x409"
        os.makedirs(strings_dir, exist_ok=True)
        with open(f"{strings_dir}/serialnumber", "w") as f:
            f.write(serial_number)
        with open(f"{strings_dir}/manufacturer", "w") as f:
            f.write(manufacturer_name)
        with open(f"{strings_dir}/product", "w") as f:
            f.write(product_name)

        # Create keyboard function
        keyboard_func_dir = "functions/hid.keyboard"
        os.makedirs(keyboard_func_dir, exist_ok=True)
        with open(f"{keyboard_func_dir}/protocol", "w") as f:
            f.write("1")  # Keyboard
        with open(f"{keyboard_func_dir}/subclass", "w") as f:
            f.write("1")  # Boot interface subclass
        with open(f"{keyboard_func_dir}/report_length", "w") as f:
            f.write("8")

        # Keyboard HID report descriptor
        keyboard_report_desc = bytes(
            [
                0x05,
                0x01,  # Usage Page (Generic Desktop Ctrls)
                0x09,
                0x06,  # Usage (Keyboard)
                0xA1,
                0x01,  # Collection (Application)
                0x05,
                0x08,  #   Usage Page (LEDs)
                0x19,
                0x01,  #   Usage Minimum (Num Lock)
                0x29,
                0x03,  #   Usage Maximum (Scroll Lock)
                0x15,
                0x00,  #   Logical Minimum (0)
                0x25,
                0x01,  #   Logical Maximum (1)
                0x75,
                0x01,  #   Report Size (1)
                0x95,
                0x03,  #   Report Count (3)
                0x91,
                0x02,  #   Output (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position,Non-volatile)
                0x09,
                0x4B,  #   Usage (Generic Indicator)
                0x95,
                0x01,  #   Report Count (1)
                0x91,
                0x02,  #   Output (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position,Non-volatile)
                0x95,
                0x04,  #   Report Count (4)
                0x91,
                0x01,  #   Output (Const,Array,Abs,No Wrap,Linear,Preferred State,No Null Position,Non-volatile)
                0x05,
                0x07,  #   Usage Page (Kbrd/Keypad)
                0x19,
                0xE0,  #   Usage Minimum (0xE0)
                0x29,
                0xE7,  #   Usage Maximum (0xE7)
                0x95,
                0x08,  #   Report Count (8)
                0x81,
                0x02,  #   Input (Data,Var,Abs,No Wrap,Linear,Preferred State,No Null Position)
                0x75,
                0x08,  #   Report Size (8)
                0x95,
                0x01,  #   Report Count (1)
                0x81,
                0x01,  #   Input (Const,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
                0x19,
                0x00,  #   Usage Minimum (0x00)
                0x29,
                0x91,  #   Usage Maximum (0x91)
                0x26,
                0xFF,
                0x00,  #   Logical Maximum (255)
                0x95,
                0x06,  #   Report Count (6)
                0x81,
                0x00,  #   Input (Data,Array,Abs,No Wrap,Linear,Preferred State,No Null Position)
                0xC0,  # End Collection
            ]
        )
        with open(f"{keyboard_func_dir}/report_desc", "wb") as f:
            f.write(keyboard_report_desc)

        # Create mouse relative function
        mouse_rel_func_dir = "functions/hid.mouse_relative"
        os.makedirs(mouse_rel_func_dir, exist_ok=True)
        with open(f"{mouse_rel_func_dir}/protocol", "w") as f:
            f.write("0")
        with open(f"{mouse_rel_func_dir}/subclass", "w") as f:
            f.write("0")
        with open(f"{mouse_rel_func_dir}/report_length", "w") as f:
            f.write("7")

        # Mouse relative HID report descriptor
        mouse_rel_report_desc = bytes(
            [
                0x05,
                0x01,  # USAGE_PAGE (Generic Desktop)
                0x09,
                0x02,  # USAGE (Mouse)
                0xA1,
                0x01,  # COLLECTION (Application)
                #   8-buttons
                0x05,
                0x09,  #   USAGE_PAGE (Button)
                0x19,
                0x01,  #   USAGE_MINIMUM (Button 1)
                0x29,
                0x08,  #   USAGE_MAXIMUM (Button 8)
                0x15,
                0x00,  #   LOGICAL_MINIMUM (0)
                0x25,
                0x01,  #   LOGICAL_MAXIMUM (1)
                0x95,
                0x08,  #   REPORT_COUNT (8)
                0x75,
                0x01,  #   REPORT_SIZE (1)
                0x81,
                0x02,  #   INPUT (Data,Var,Abs)
                #   x,y relative coordinates
                0x05,
                0x01,  #   USAGE_PAGE (Generic Desktop)
                0x09,
                0x30,  #   USAGE (X)
                0x09,
                0x31,  #   USAGE (Y)
                0x15,
                0x81,  #   LOGICAL_MINIMUM (-127)
                0x25,
                0x7F,  #   LOGICAL_MAXIMUM (127)
                0x75,
                0x08,  #   REPORT_SIZE (16)
                0x95,
                0x02,  #   REPORT_COUNT (2)
                0x81,
                0x06,  #   INPUT (Data,Var,Rel)
                #   vertical wheel
                0x09,
                0x38,  #   USAGE (wheel)
                0x15,
                0x81,  #   LOGICAL_MINIMUM (-127)
                0x25,
                0x7F,  #   LOGICAL_MAXIMUM (127)
                0x75,
                0x08,  #   REPORT_SIZE (8)
                0x95,
                0x01,  #   REPORT_COUNT (1)
                0x81,
                0x06,  #   INPUT (Data,Var,Rel)
                #   horizontal wheel
                0x05,
                0x0C,  #   USAGE_PAGE (Consumer Devices)
                0x0A,
                0x38,
                0x02,  #   USAGE (AC Pan)
                0x15,
                0x81,  #   LOGICAL_MINIMUM (-127)
                0x25,
                0x7F,  #   LOGICAL_MAXIMUM (127)
                0x75,
                0x08,  #   REPORT_SIZE (8)
                0x95,
                0x01,  #   REPORT_COUNT (1)
                0x81,
                0x06,  #   INPUT (Data,Var,Rel)
                0xC0,  # END_COLLECTION
            ]
        )
        with open(f"{mouse_rel_func_dir}/report_desc", "wb") as f:
            f.write(mouse_rel_report_desc)

        # Create mouse absolute function
        mouse_abs_func_dir = "functions/hid.mouse_absolute"
        os.makedirs(mouse_abs_func_dir, exist_ok=True)
        with open(f"{mouse_abs_func_dir}/protocol", "w") as f:
            f.write("0")
        with open(f"{mouse_abs_func_dir}/subclass", "w") as f:
            f.write("0")
        with open(f"{mouse_abs_func_dir}/report_length", "w") as f:
            f.write("7")

        # Mouse absolute HID report descriptor
        mouse_abs_report_desc = bytes(
            [
                0x05,
                0x01,  # USAGE_PAGE (Generic Desktop)
                0x09,
                0x02,  # USAGE (Mouse)
                0xA1,
                0x01,  # COLLECTION (Application)
                #   8-buttons
                0x05,
                0x09,  #   USAGE_PAGE (Button)
                0x19,
                0x01,  #   USAGE_MINIMUM (Button 1)
                0x29,
                0x08,  #   USAGE_MAXIMUM (Button 8)
                0x15,
                0x00,  #   LOGICAL_MINIMUM (0)
                0x25,
                0x01,  #   LOGICAL_MAXIMUM (1)
                0x95,
                0x08,  #   REPORT_COUNT (8)
                0x75,
                0x01,  #   REPORT_SIZE (1)
                0x81,
                0x02,  #   INPUT (Data,Var,Abs)
                #   x,y absolute coordinates
                0x05,
                0x01,  #   USAGE_PAGE (Generic Desktop)
                0x09,
                0x30,  #   USAGE (X)
                0x09,
                0x31,  #   USAGE (Y)
                0x15,
                0x00,  #   LOGICAL_MINIMUM (0)
                0x26,
                0xFF,
                0x7F,  #   LOGICAL_MAXIMUM (65535)
                0x75,
                0x10,  #   REPORT_SIZE (16)
                0x95,
                0x02,  #   REPORT_COUNT (2)
                0x81,
                0x02,  #   INPUT (Data,Var,RAbs)
                #   vertical wheel
                0x09,
                0x38,  #   USAGE (wheel)
                0x15,
                0x81,  #   LOGICAL_MINIMUM (-127)
                0x25,
                0x7F,  #   LOGICAL_MAXIMUM (127)
                0x75,
                0x08,  #   REPORT_SIZE (8)
                0x95,
                0x01,  #   REPORT_COUNT (1)
                0x81,
                0x06,  #   INPUT (Data,Var,Rel)
                #   horizontal wheel
                0x05,
                0x0C,  #   USAGE_PAGE (Consumer Devices)
                0x0A,
                0x38,
                0x02,  #   USAGE (AC Pan)
                0x15,
                0x81,  #   LOGICAL_MINIMUM (-127)
                0x25,
                0x7F,  #   LOGICAL_MAXIMUM (127)
                0x75,
                0x08,  #   REPORT_SIZE (8)
                0x95,
                0x01,  #   REPORT_COUNT (1)
                0x81,
                0x06,  #   INPUT (Data,Var,Rel)
                0xC0,  # END_COLLECTION
            ]
        )
        with open(f"{mouse_abs_func_dir}/report_desc", "wb") as f:
            f.write(mouse_abs_report_desc)

        # Create configuration
        config_dir = "configs/c.1"
        os.makedirs(config_dir, exist_ok=True)
        with open(f"{config_dir}/MaxPower", "w") as f:
            f.write("250")

        # Set configuration strings
        config_strings_dir = f"{config_dir}/strings/0x409"
        os.makedirs(config_strings_dir, exist_ok=True)
        with open(f"{config_strings_dir}/configuration", "w") as f:
            f.write("Config 1: ECM network")

        # Link functions to configuration
        # Use relative paths since we're in the gadget directory
        os.symlink(keyboard_func_dir, f"{config_dir}/hid.keyboard")
        os.symlink(mouse_rel_func_dir, f"{config_dir}/hid.mouse_relative")
        os.symlink(mouse_abs_func_dir, f"{config_dir}/hid.mouse_absolute")

        # Enable the gadget
        # List UDC devices and use the first one (equivalent to: ls /sys/class/udc > UDC)
        udc_devices = os.listdir("/sys/class/udc")
        if udc_devices:
            with open("UDC", "w") as f:
                # Write all UDC device names, one per line, as bash ls would
                f.write("\n".join(udc_devices))

        # Set device permissions
        os.chmod("/dev/hidg0", 0o777)  # Keyboard
        os.chmod("/dev/hidg1", 0o777)  # Mouse Relative
        os.chmod("/dev/hidg2", 0o777)  # Mouse Absolute

        logger.info("USB HID gadget initialization completed successfully")

    except Exception as e:
        logger.error(f"Failed to initialize USB HID gadget: {e}")
        raise


def remove_usb_gadget(gadget_dir: str = "g1"):
    """
    Remove USB HID gadget devices.

    This function is likely to be less tested and maybe not work, compared to init_usb_gadget.

    Gadget removal based on https://github.com/thewh1teagle/zero-hid/blob/6e99b87e5d4c36382a193824e1fbda6f3d85a6e6/usb_gadget/remove_usb_gadget which is LGPL3+ licensed.

    Args:
        gadget_dir: Directory name for the gadget (default: "g1")
    """
    try:
        full_gadget_dir = f"/sys/kernel/config/usb_gadget/{gadget_dir}"

        if not os.path.exists(full_gadget_dir):
            logger.info("Gadget does not exist, nothing to remove")
            return

        os.chdir(full_gadget_dir)

        # Disable gadget
        with open("UDC", "r") as f:
            udc_content = f.read().strip()
        if udc_content:
            with open("UDC", "w") as f:
                f.write("")

        # Remove functions from configs
        configs_pattern = "configs/*"
        functions_pattern = "functions/*"
        strings_dir = "strings/0x409"

        # Get actual directories
        config_dirs = [
            d for d in os.listdir("configs") if os.path.isdir(f"configs/{d}")
        ]
        function_dirs = [
            d for d in os.listdir("functions") if os.path.isdir(f"functions/{d}")
        ]

        # Remove function links from configs
        for config in config_dirs:
            config_path = f"configs/{config}"
            for function in function_dirs:
                link_path = f"{config_path}/{function}"
                if os.path.islink(link_path):
                    os.unlink(link_path)

            # Remove config strings
            config_strings_path = f"{config_path}/{strings_dir}"
            if os.path.exists(config_strings_path):
                os.rmdir(config_strings_path)

            # Remove config directory
            os.rmdir(config_path)

        # Remove function directories
        for function in function_dirs:
            function_path = f"functions/{function}"
            if os.path.exists(function_path):
                os.rmdir(function_path)

        # Remove device strings
        if os.path.exists(strings_dir):
            os.rmdir(strings_dir)

        # Go back and remove gadget directory
        os.chdir("..")
        os.rmdir(gadget_dir)

        logger.info("USB HID gadget removal completed successfully")

    except Exception as e:
        logger.error(f"Failed to remove USB HID gadget: {e}")
        raise


def register(mooncrater_input):
    """Register hid_gadget_devices types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # Track instances that need cleanup
    instances_to_cleanup = []

    def cleanup_all_gadgets():
        """Clean up all gadgets that need removal on exit."""
        for instance in instances_to_cleanup[:]:  # Copy list to avoid modification during iteration
            if instance.remove_hidg_on_destruction and instance.gadget_dir:
                try:
                    logger.info(f"Cleaning up USB gadget '{instance.gadget_dir}' on exit")
                    remove_usb_gadget(instance.gadget_dir)
                except Exception as e:
                    logger.error(f"Failed to clean up USB gadget '{instance.gadget_dir}': {e}")

    def signal_handler(signum, frame):
        """Handle signals by cleaning up gadgets."""
        logger.info(f"Received signal {signum}, cleaning up USB gadgets")
        cleanup_all_gadgets()
        # Re-raise the signal to allow default handling
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    # Register cleanup handlers
    atexit.register(cleanup_all_gadgets)
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Constructor for usb_gadget output
    def create_usb_gadget(mooncrater_input_instance, tag, initialize_hidg_devices=False, **kwargs):
        gadget_dir = None
        remove_hidg_on_destruction = False

        # Handle device initialization if needed
        if initialize_hidg_devices:
            hidg_devices = ["/dev/hidg0", "/dev/hidg1", "/dev/hidg2"]
            missing_devices = [
                dev for dev in hidg_devices if not os.path.exists(dev)
            ]

            if missing_devices:
                logger.info(
                    f"Missing hidg devices: {missing_devices}, running initialization function"
                )
                try:
                    # initialize_hidg_devices should be a dict with the required keys
                    if not isinstance(initialize_hidg_devices, dict):
                        raise ValueError(
                            "initialize_hidg_devices must be a dictionary with keys: "
                            "manufacturer_name, product_name, serial_number, id_vendor, id_product"
                        )

                    # Extract required parameters from the dictionary
                    required_keys = ["manufacturer_name", "product_name", "serial_number", "id_vendor", "id_product"]
                    missing_keys = [key for key in required_keys if key not in initialize_hidg_devices]
                    if missing_keys:
                        raise ValueError(
                            f"initialize_hidg_devices dictionary missing required keys: {missing_keys}"
                        )

                    # Extract gadget_dir and remove_hidg_on_destruction
                    gadget_dir = initialize_hidg_devices.get("gadget_dir", "g1")
                    remove_hidg_on_destruction = initialize_hidg_devices.get("remove_hidg_on_destruction", True)

                    # Pass through to init_usb_gadget
                    init_usb_gadget(
                        manufacturer_name=initialize_hidg_devices["manufacturer_name"],
                        product_name=initialize_hidg_devices["product_name"],
                        serial_number=initialize_hidg_devices["serial_number"],
                        id_vendor=initialize_hidg_devices["id_vendor"],
                        id_product=initialize_hidg_devices["id_product"],
                        gadget_dir=gadget_dir
                    )
                    logger.info("USB gadget initialization completed successfully")
                except Exception as e:
                    logger.error(f"USB gadget initialization failed: {e}")
                    raise RuntimeError(
                        f"Failed to initialize USB gadget devices: {e}"
                    )

        gadget_device = HIDGadgetDeviceTag(
            tag,
            gadget_dir=gadget_dir,
            remove_hidg_on_destruction=remove_hidg_on_destruction
        )

        # Add to cleanup list if needed
        if remove_hidg_on_destruction and gadget_dir:
            instances_to_cleanup.append(gadget_device)

        return gadget_device

    # Destructor for usb_gadget output
    def destroy_usb_gadget(mooncrater_input_instance, tag, instance):
        try:
            # Close the HID devices first
            instance.close()

            # Remove USB gadget if requested
            if instance.remove_hidg_on_destruction and instance.gadget_dir:
                try:
                    logger.info(f"Removing USB gadget '{instance.gadget_dir}' for tag '{tag}'")
                    remove_usb_gadget(instance.gadget_dir)
                except Exception as e:
                    logger.error(f"Failed to remove USB gadget '{instance.gadget_dir}': {e}")

            # Remove from cleanup list
            if instance in instances_to_cleanup:
                instances_to_cleanup.remove(instance)

            return True
        except Exception as e:
            logger.error(f"Error closing usb_gadget {tag}: {e}")
            return False

    # Send events function for usb_gadget output
    def send_events_usb_gadget(mooncrater_input_instance, instance, events):
        try:
            for json_event in events:
                instance.send_json_event(json_event)
            return True
        except Exception as e:
            logger.error(f"Failed to send events to USB gadget: {e}")
            return False

    # Register the usb_gadget output type
    mooncrater_input.register_output_type(
        type_name="usb_gadget",
        constructor=lambda tag, **kwargs: create_usb_gadget(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_usb_gadget(mooncrater_input, tag, instance),
        send_events=lambda instance, events: send_events_usb_gadget(mooncrater_input, instance, events),
        metadata={
            "description": "USB HID gadget output devices",
            "module": "hid_gadget_devices"
        }
    )
