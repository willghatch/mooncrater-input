#!/usr/bin/env python3

import logging
from typing import List, Optional

# Set up logging
logger = logging.getLogger(__name__)


class EvdevOutputVirtualDevice:
    """Manages a set of virtual devices under a single logical tag."""

    def __init__(self, tag: str, exception_on_error: bool = False):
        self.tag = tag
        self.devices = {}
        self._json_translator = None
        self._evdev = None
        self._UInput = None
        self._e = None
        self.connection_status = "disconnected"
        self.last_error = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3

        # Try to create devices
        try:
            self._create_devices()
            self.connection_status = "connected"
        except Exception as e:
            logger.error(f"Failed to create virtual devices for tag '{tag}': {e}")
            self.last_error = str(e)
            self.connection_status = "failed"

            # If exception_on_error is True, re-raise the exception
            if exception_on_error:
                raise

    def _ensure_evdev_loaded(self):
        """Load evdev modules when first needed."""
        if self._evdev is None:
            try:
                import evdev
                from evdev import UInput, ecodes as e

                self._evdev = evdev
                self._UInput = UInput
                self._e = e
                self._json_translator = self.JsonToEvdevTranslator(e)
            except ImportError:
                raise ImportError(
                    "evdev package is required for virtual device outputs. Install with: pip install evdev"
                )

    def _create_devices(self):
        """Create the virtual keyboard, mouse, and trackpad devices."""
        self._ensure_evdev_loaded()

        # Keyboard device
        keyboard_caps = {
            self._e.EV_KEY: list(range(self._e.KEY_ESC, self._e.KEY_MICMUTE + 1))
        }
        self.devices["keyboard"] = self._UInput(
            keyboard_caps, name=f"mooncrater-input-{self.tag}-kbd", version=0x3
        )

        # Mouse device
        mouse_caps = {
            self._e.EV_KEY: [
                self._e.BTN_LEFT,
                self._e.BTN_RIGHT,
                self._e.BTN_MIDDLE,
                self._e.BTN_BACK,
                self._e.BTN_FORWARD,
            ],
            self._e.EV_REL: [
                self._e.REL_X,
                self._e.REL_Y,
                self._e.REL_WHEEL,
                self._e.REL_HWHEEL,
                self._e.REL_WHEEL_HI_RES,
                self._e.REL_HWHEEL_HI_RES,
            ],
        }
        self.devices["mouse"] = self._UInput(
            mouse_caps, name=f"mooncrater-input-{self.tag}-mouse", version=0x3
        )

        # Trackpad device
        trackpad_caps = {
            self._e.EV_KEY: [
                self._e.BTN_LEFT,
                self._e.BTN_RIGHT,
                self._e.BTN_MIDDLE,
                self._e.BTN_BACK,
                self._e.BTN_FORWARD,
                self._e.BTN_TOUCH,
            ],
            self._e.EV_REL: [
                self._e.REL_X,
                self._e.REL_Y,
                self._e.REL_WHEEL,
                self._e.REL_HWHEEL,
                self._e.REL_WHEEL_HI_RES,
                self._e.REL_HWHEEL_HI_RES,
            ],
            self._e.EV_ABS: {
                self._e.ABS_X: (0, 1024, 0, 0),
                self._e.ABS_Y: (0, 768, 0, 0),
                self._e.ABS_PRESSURE: (0, 255, 0, 0),
            },
        }
        self.devices["trackpad"] = self._UInput(
            trackpad_caps, name=f"mooncrater-input-{self.tag}-trackpad", version=0x3
        )

    def send_json_event(self, json_event: dict):
        """Send a JSON event by translating to evdev events."""
        try:
            # Check connection status and try to reconnect if needed
            if not self.is_connected():
                if not self._try_reconnect():
                    logger.warning(f"Virtual device '{self.tag}' not connected, dropping event")
                    return

            if not self._json_translator:
                logger.warning(f"Virtual device '{self.tag}' translator not available")
                return

            evdev_events = self._json_translator.translate(json_event)

            # Determine which device type to use based on event category
            device_type = {
                "keyboard": "keyboard",
                "mouse": "mouse",
                "touchpad": "trackpad",
            }.get(
                json_event.get("category"), "keyboard"
            )  # Default to keyboard

            # Send each evdev event
            for event_type, code, value in evdev_events:
                self.send_event(device_type, event_type, code, value)

        except Exception as e:
            logger.error(f"Error sending event to virtual device '{self.tag}': {e}")
            self.connection_status = "failed"
            self.last_error = str(e)

    def send_event(self, device_type: str, event_type: int, code: int, value: int):
        """Send an event to the specified device type."""
        try:
            if device_type in self.devices:
                self.devices[device_type].write(event_type, code, value)
                self.devices[device_type].syn()
        except Exception as e:
            logger.error(f"Error writing to virtual device '{self.tag}' type '{device_type}': {e}")
            self.connection_status = "failed"
            self.last_error = str(e)
            raise

    def is_connected(self) -> bool:
        """Check if virtual devices are connected and working."""
        return self.connection_status == "connected" and len(self.devices) > 0

    def get_connection_status(self) -> dict:
        """Get detailed connection status information."""
        return {
            "status": self.connection_status,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "device_count": len(self.devices)
        }

    def _try_reconnect(self) -> bool:
        """Try to reconnect virtual devices."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts reached for virtual device '{self.tag}'")
            return False

        self.reconnect_attempts += 1
        logger.info(f"Attempting to reconnect virtual device '{self.tag}' (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")

        try:
            # Close existing devices
            self.close()

            # Clear state
            self.devices.clear()
            self._json_translator = None

            # Try to recreate devices
            self._create_devices()

            self.connection_status = "connected"
            self.last_error = None
            self.reconnect_attempts = 0

            logger.info(f"Successfully reconnected virtual device '{self.tag}'")
            return True

        except Exception as e:
            logger.error(f"Failed to reconnect virtual device '{self.tag}': {e}")
            self.connection_status = "failed"
            self.last_error = str(e)
            return False

    def close(self):
        """Close all virtual devices."""
        for device in self.devices.values():
            try:
                device.close()
            except OSError:
                pass
        self.connection_status = "disconnected"

    class JsonToEvdevTranslator:
        """Translates JSON events back to evdev events."""

        def __init__(self, e_module):
            self.e = e_module
            # Fractional accumulation for smooth mouse movement
            self.fractional_x = 0.0
            self.fractional_y = 0.0

        def translate(self, json_event: dict) -> List[tuple]:
            """Translate a JSON event dictionary back to evdev events (type, code, value)."""
            events = []

            # Handle eventList - recursively process multiple events
            if json_event.get("type") == "eventList":
                event_list = json_event.get("events", [])
                for sub_event in event_list:
                    events.extend(self.translate(sub_event))
                return events

            # TODO - maybe have an option to use the original event as a fallback.
            # if json_event.get("originalEvdevEvent"):
            #     return [json_event["originalEvdevEvent"]]

            # Determine category from category field or event type
            category = self._determine_category(json_event)

            # Keyboard events
            if category == "keyboard":
                # Handle typeQwertyString - convert string to multiple keyPress events
                if json_event.get("type") == "typeQwertyString":
                    string_to_type = json_event.get("string", "")
                    for char in string_to_type:
                        scancode = self._char_to_scancode(char)
                        if scancode:
                            events.append((self.e.EV_KEY, scancode, 1))
                            events.append((self.e.EV_KEY, scancode, 0))
                else:
                    # Get scancode with priority: keyChar -> keyName -> scancode field
                    scancode = None

                    # First try keyChar
                    if "keyChar" in json_event and json_event["keyChar"]:
                        scancode = self._char_to_scancode(json_event["keyChar"])

                    # Then try keyName if keyChar didn't work
                    if (
                        not scancode
                        and "keyName" in json_event
                        and json_event["keyName"]
                    ):
                        scancode = self._keyname_to_scancode(json_event["keyName"])

                    # Finally try direct scancode field
                    if not scancode and "scancode" in json_event:
                        scancode = json_event["scancode"]

                    if scancode:
                        if json_event.get("type") == "keyDown":
                            events.append((self.e.EV_KEY, scancode, 1))
                        elif json_event.get("type") == "keyUp":
                            events.append((self.e.EV_KEY, scancode, 0))
                        elif json_event.get("type") == "keyPress":
                            events.append((self.e.EV_KEY, scancode, 1))
                            events.append((self.e.EV_KEY, scancode, 0))

            # Mouse events
            elif category == "mouse":
                if json_event.get("type") in ["mouseDown", "mouseUp"]:
                    button = json_event.get("button")
                    value = 1 if json_event.get("type") == "mouseDown" else 0
                    button_code = {
                        "left": self.e.BTN_LEFT,
                        "right": self.e.BTN_RIGHT,
                        "middle": self.e.BTN_MIDDLE,
                        "back": self.e.BTN_BACK,
                        "forward": self.e.BTN_FORWARD,
                    }.get(button)

                    if button_code:
                        events.append((self.e.EV_KEY, button_code, value))

                elif json_event.get("type") == "mouseRel":
                    # Handle deltaX/deltaY format with fractional accumulation
                    delta_x = json_event.get("deltaX", 0)
                    delta_y = json_event.get("deltaY", 0)

                    # Accumulate fractional values
                    self.fractional_x += delta_x
                    self.fractional_y += delta_y

                    # Extract integer parts for sending
                    int_x = int(self.fractional_x)
                    int_y = int(self.fractional_y)

                    # Keep fractional remainders for next time
                    self.fractional_x -= int_x
                    self.fractional_y -= int_y

                    # Send integer movements if non-zero
                    if int_x != 0:
                        events.append((self.e.EV_REL, self.e.REL_X, int_x))
                    if int_y != 0:
                        events.append((self.e.EV_REL, self.e.REL_Y, int_y))

                elif json_event.get("type") == "scroll":
                    # Handle new deltaX/deltaY format
                    # Send both regular and high-res events, like real hardware does
                    delta_x = json_event.get("deltaX", 0)
                    delta_y = json_event.get("deltaY", 0)
                    if delta_x != 0:
                        events.append((self.e.EV_REL, self.e.REL_HWHEEL, delta_x))
                        events.append((self.e.EV_REL, self.e.REL_HWHEEL_HI_RES, delta_x * 120))
                    if delta_y != 0:
                        events.append((self.e.EV_REL, self.e.REL_WHEEL, delta_y))
                        events.append((self.e.EV_REL, self.e.REL_WHEEL_HI_RES, delta_y * 120))

                elif json_event.get("type") == "smoothScroll":
                    # Handle smooth scroll - prefer raw values if available, fall back to float
                    # Send both regular and high-res events, like real hardware does
                    raw_delta_x = json_event.get("rawDeltaX")
                    raw_delta_y = json_event.get("rawDeltaY")
                    delta_x = json_event.get("deltaX", 0)
                    delta_y = json_event.get("deltaY", 0)

                    # Send high-resolution events
                    if raw_delta_x is not None and raw_delta_x != 0:
                        events.append(
                            (self.e.EV_REL, self.e.REL_HWHEEL_HI_RES, raw_delta_x)
                        )
                        # Also send regular wheel event (convert from raw: 120 units = 1 notch)
                        regular_x = round(raw_delta_x / 120.0)
                        if regular_x != 0:
                            events.append((self.e.EV_REL, self.e.REL_HWHEEL, regular_x))
                    elif delta_x != 0:
                        # Convert float delta back to raw (multiply by 120)
                        raw_x = int(delta_x * 120)
                        events.append((self.e.EV_REL, self.e.REL_HWHEEL_HI_RES, raw_x))
                        # Also send regular wheel event
                        regular_x = round(delta_x)
                        if regular_x != 0:
                            events.append((self.e.EV_REL, self.e.REL_HWHEEL, regular_x))

                    if raw_delta_y is not None and raw_delta_y != 0:
                        events.append(
                            (self.e.EV_REL, self.e.REL_WHEEL_HI_RES, raw_delta_y)
                        )
                        # Also send regular wheel event (convert from raw: 120 units = 1 notch)
                        regular_y = round(raw_delta_y / 120.0)
                        if regular_y != 0:
                            events.append((self.e.EV_REL, self.e.REL_WHEEL, regular_y))
                    elif delta_y != 0:
                        # Convert float delta back to raw (multiply by 120)
                        raw_y = int(delta_y * 120)
                        events.append((self.e.EV_REL, self.e.REL_WHEEL_HI_RES, raw_y))
                        # Also send regular wheel event
                        regular_y = round(delta_y)
                        if regular_y != 0:
                            events.append((self.e.EV_REL, self.e.REL_WHEEL, regular_y))

            # Touchpad events
            elif category == "touchpad":
                if json_event.get("type") in ["touchDown", "touchUp"]:
                    value = 1 if json_event.get("type") == "touchDown" else 0
                    events.append((self.e.EV_KEY, self.e.BTN_TOUCH, value))

                elif json_event.get("type") == "touchpadAbs":
                    axis = json_event.get("axis")
                    value = json_event.get("value", 0)
                    axis_code = {
                        "x": self.e.ABS_X,
                        "y": self.e.ABS_Y,
                        "pressure": self.e.ABS_PRESSURE,
                    }.get(axis)

                    if axis_code:
                        events.append((self.e.EV_ABS, axis_code, value))

            # Add sync event if we generated any events
            if events:
                events.append((self.e.EV_SYN, self.e.SYN_REPORT, 0))

            return events

        def _char_to_scancode(self, char: str) -> Optional[int]:
            """Convert character to scancode (complete QWERTY mapping)."""
            char_map = {
                # Letters (both cases)
                "a": self.e.KEY_A,
                "A": self.e.KEY_A,
                "b": self.e.KEY_B,
                "B": self.e.KEY_B,
                "c": self.e.KEY_C,
                "C": self.e.KEY_C,
                "d": self.e.KEY_D,
                "D": self.e.KEY_D,
                "e": self.e.KEY_E,
                "E": self.e.KEY_E,
                "f": self.e.KEY_F,
                "F": self.e.KEY_F,
                "g": self.e.KEY_G,
                "G": self.e.KEY_G,
                "h": self.e.KEY_H,
                "H": self.e.KEY_H,
                "i": self.e.KEY_I,
                "I": self.e.KEY_I,
                "j": self.e.KEY_J,
                "J": self.e.KEY_J,
                "k": self.e.KEY_K,
                "K": self.e.KEY_K,
                "l": self.e.KEY_L,
                "L": self.e.KEY_L,
                "m": self.e.KEY_M,
                "M": self.e.KEY_M,
                "n": self.e.KEY_N,
                "N": self.e.KEY_N,
                "o": self.e.KEY_O,
                "O": self.e.KEY_O,
                "p": self.e.KEY_P,
                "P": self.e.KEY_P,
                "q": self.e.KEY_Q,
                "Q": self.e.KEY_Q,
                "r": self.e.KEY_R,
                "R": self.e.KEY_R,
                "s": self.e.KEY_S,
                "S": self.e.KEY_S,
                "t": self.e.KEY_T,
                "T": self.e.KEY_T,
                "u": self.e.KEY_U,
                "U": self.e.KEY_U,
                "v": self.e.KEY_V,
                "V": self.e.KEY_V,
                "w": self.e.KEY_W,
                "W": self.e.KEY_W,
                "x": self.e.KEY_X,
                "X": self.e.KEY_X,
                "y": self.e.KEY_Y,
                "Y": self.e.KEY_Y,
                "z": self.e.KEY_Z,
                "Z": self.e.KEY_Z,
                # Numbers
                "0": self.e.KEY_0,
                "1": self.e.KEY_1,
                "2": self.e.KEY_2,
                "3": self.e.KEY_3,
                "4": self.e.KEY_4,
                "5": self.e.KEY_5,
                "6": self.e.KEY_6,
                "7": self.e.KEY_7,
                "8": self.e.KEY_8,
                "9": self.e.KEY_9,
                # Punctuation and symbols (unshifted)
                "`": self.e.KEY_GRAVE,
                "~": self.e.KEY_GRAVE,
                "-": self.e.KEY_MINUS,
                "_": self.e.KEY_MINUS,
                "=": self.e.KEY_EQUAL,
                "+": self.e.KEY_EQUAL,
                "[": self.e.KEY_LEFTBRACE,
                "{": self.e.KEY_LEFTBRACE,
                "]": self.e.KEY_RIGHTBRACE,
                "}": self.e.KEY_RIGHTBRACE,
                "\\": self.e.KEY_BACKSLASH,
                "|": self.e.KEY_BACKSLASH,
                ";": self.e.KEY_SEMICOLON,
                ":": self.e.KEY_SEMICOLON,
                "'": self.e.KEY_APOSTROPHE,
                '"': self.e.KEY_APOSTROPHE,
                ",": self.e.KEY_COMMA,
                "<": self.e.KEY_COMMA,
                ".": self.e.KEY_DOT,
                ">": self.e.KEY_DOT,
                "/": self.e.KEY_SLASH,
                "?": self.e.KEY_SLASH,
                # Shifted number row symbols
                "!": self.e.KEY_1,
                "@": self.e.KEY_2,
                "#": self.e.KEY_3,
                "$": self.e.KEY_4,
                "%": self.e.KEY_5,
                "^": self.e.KEY_6,
                "&": self.e.KEY_7,
                "*": self.e.KEY_8,
                "(": self.e.KEY_9,
                ")": self.e.KEY_0,
                # Whitespace
                " ": self.e.KEY_SPACE,
                "\t": self.e.KEY_TAB,
                "\n": self.e.KEY_ENTER,
            }
            return char_map.get(char)

        def _keyname_to_scancode(self, keyname: str) -> Optional[int]:
            """Convert keyName string to scancode."""
            # Handle SCANCODE_* format for custom scancodes (e.g., "SCANCODE_175")
            if keyname.startswith("SCANCODE_"):
                try:
                    scancode_num = int(keyname[9:])  # Extract number after "SCANCODE_"
                    if 0 <= scancode_num <= 255:
                        return scancode_num
                except ValueError:
                    pass  # Invalid number format, fall through to other methods

            # Handle standard evdev key names (e.g., "KEY_A", "KEY_ENTER", etc.)
            if hasattr(self.e, keyname):
                code = getattr(self.e, keyname)
                # Verify it's actually a key code (in the valid range)
                if (
                    isinstance(code, int)
                    and self.e.KEY_RESERVED <= code <= self.e.KEY_MAX
                ):
                    return code

            # Handle common key name variants without KEY_ prefix
            keyname_variants = {
                # Letters
                "A": self.e.KEY_A,
                "B": self.e.KEY_B,
                "C": self.e.KEY_C,
                "D": self.e.KEY_D,
                "E": self.e.KEY_E,
                "F": self.e.KEY_F,
                "G": self.e.KEY_G,
                "H": self.e.KEY_H,
                "I": self.e.KEY_I,
                "J": self.e.KEY_J,
                "K": self.e.KEY_K,
                "L": self.e.KEY_L,
                "M": self.e.KEY_M,
                "N": self.e.KEY_N,
                "O": self.e.KEY_O,
                "P": self.e.KEY_P,
                "Q": self.e.KEY_Q,
                "R": self.e.KEY_R,
                "S": self.e.KEY_S,
                "T": self.e.KEY_T,
                "U": self.e.KEY_U,
                "V": self.e.KEY_V,
                "W": self.e.KEY_W,
                "X": self.e.KEY_X,
                "Y": self.e.KEY_Y,
                "Z": self.e.KEY_Z,
                # Numbers
                "0": self.e.KEY_0,
                "1": self.e.KEY_1,
                "2": self.e.KEY_2,
                "3": self.e.KEY_3,
                "4": self.e.KEY_4,
                "5": self.e.KEY_5,
                "6": self.e.KEY_6,
                "7": self.e.KEY_7,
                "8": self.e.KEY_8,
                "9": self.e.KEY_9,
                # Common key names
                "SPACE": self.e.KEY_SPACE,
                "ENTER": self.e.KEY_ENTER,
                "TAB": self.e.KEY_TAB,
                "BACKSPACE": self.e.KEY_BACKSPACE,
                "DELETE": self.e.KEY_DELETE,
                "ESC": self.e.KEY_ESC,
                "ESCAPE": self.e.KEY_ESC,
                "SHIFT": self.e.KEY_LEFTSHIFT,
                "CTRL": self.e.KEY_LEFTCTRL,
                "ALT": self.e.KEY_LEFTALT,
                "META": self.e.KEY_LEFTMETA,
                "SUPER": self.e.KEY_LEFTMETA,
                # Arrow keys
                "UP": self.e.KEY_UP,
                "DOWN": self.e.KEY_DOWN,
                "LEFT": self.e.KEY_LEFT,
                "RIGHT": self.e.KEY_RIGHT,
                "ARROW_UP": self.e.KEY_UP,
                "ARROW_DOWN": self.e.KEY_DOWN,
                "ARROW_LEFT": self.e.KEY_LEFT,
                "ARROW_RIGHT": self.e.KEY_RIGHT,
                # Function keys
                "F1": self.e.KEY_F1,
                "F2": self.e.KEY_F2,
                "F3": self.e.KEY_F3,
                "F4": self.e.KEY_F4,
                "F5": self.e.KEY_F5,
                "F6": self.e.KEY_F6,
                "F7": self.e.KEY_F7,
                "F8": self.e.KEY_F8,
                "F9": self.e.KEY_F9,
                "F10": self.e.KEY_F10,
                "F11": self.e.KEY_F11,
                "F12": self.e.KEY_F12,
                # Punctuation key names
                "MINUS": self.e.KEY_MINUS,
                "EQUAL": self.e.KEY_EQUAL,
                "GRAVE": self.e.KEY_GRAVE,
                "LEFTBRACE": self.e.KEY_LEFTBRACE,
                "RIGHTBRACE": self.e.KEY_RIGHTBRACE,
                "BACKSLASH": self.e.KEY_BACKSLASH,
                "SEMICOLON": self.e.KEY_SEMICOLON,
                "APOSTROPHE": self.e.KEY_APOSTROPHE,
                "COMMA": self.e.KEY_COMMA,
                "DOT": self.e.KEY_DOT,
                "PERIOD": self.e.KEY_DOT,
                "SLASH": self.e.KEY_SLASH,
            }

            return keyname_variants.get(keyname.upper())

        def _determine_category(self, json_event: dict) -> Optional[str]:
            """Determine the event category from category field or event type."""
            # First try explicit category field
            if "category" in json_event and json_event["category"]:
                return json_event["category"]

            # Fallback: determine category from event type
            event_type = json_event.get("type", "")

            # Special event types
            if event_type == "eventList":
                return "eventList"

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

            # Default fallback - try to infer from other fields
            if "keyChar" in json_event or "keyName" in json_event:
                return "keyboard"
            elif "button" in json_event and json_event["button"] in [
                "left",
                "right",
                "middle",
                "back",
                "forward",
            ]:
                return "mouse"
            elif "axis" in json_event or "delta" in json_event:
                # Could be mouse or touchpad, default to mouse
                return "mouse"

            # Final fallback
            return "unknown"


def register(mooncrater_input):
    """Register evdev_output types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # Constructor for virtual_evdev output
    def create_virtual_evdev(mooncrater_input_instance, tag, exceptionOnError=True, **kwargs):
        # Each virtual_evdev output gets its own instance
        virtual_device = EvdevOutputVirtualDevice(tag, exception_on_error=exceptionOnError)
        return virtual_device

    # Destructor for virtual_evdev output
    def destroy_virtual_evdev(mooncrater_input_instance, tag, instance):
        try:
            instance.close()
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error closing virtual_evdev {tag}: {e}")
            return False

    # Send events function for virtual_evdev output
    def send_events_virtual_evdev(mooncrater_input_instance, instance, events):
        try:
            for json_event in events:
                instance.send_json_event(json_event)
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to send events to virtual evdev: {e}")
            return False

    # Register the virtual_evdev output type
    mooncrater_input.register_output_type(
        type_name="virtual_evdev",
        constructor=lambda tag, **kwargs: create_virtual_evdev(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_virtual_evdev(mooncrater_input, tag, instance),
        send_events=lambda instance, events: send_events_virtual_evdev(mooncrater_input, instance, events),
        metadata={
            "description": "Virtual evdev output devices",
            "module": "evdev_output"
        }
    )
