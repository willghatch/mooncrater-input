"""
HID scancode definitions based on USB HID Usage Tables.
Similar to evdev.ecodes but for HID scancodes.
"""

# Primary scancode dictionary - this is the single source of truth
HID_KEY_SCANCODES = {
    # Error and special codes
    "KEY_NONE": 0x00,
    "KEY_ERROR_ROLLOVER": 0x01,
    "KEY_POST_FAIL": 0x02,
    "KEY_ERROR_UNDEFINED": 0x03,
    # Letters
    "KEY_A": 0x04,
    "KEY_B": 0x05,
    "KEY_C": 0x06,
    "KEY_D": 0x07,
    "KEY_E": 0x08,
    "KEY_F": 0x09,
    "KEY_G": 0x0A,
    "KEY_H": 0x0B,
    "KEY_I": 0x0C,
    "KEY_J": 0x0D,
    "KEY_K": 0x0E,
    "KEY_L": 0x0F,
    "KEY_M": 0x10,
    "KEY_N": 0x11,
    "KEY_O": 0x12,
    "KEY_P": 0x13,
    "KEY_Q": 0x14,
    "KEY_R": 0x15,
    "KEY_S": 0x16,
    "KEY_T": 0x17,
    "KEY_U": 0x18,
    "KEY_V": 0x19,
    "KEY_W": 0x1A,
    "KEY_X": 0x1B,
    "KEY_Y": 0x1C,
    "KEY_Z": 0x1D,
    # Numbers
    "KEY_1": 0x1E,
    "KEY_2": 0x1F,
    "KEY_3": 0x20,
    "KEY_4": 0x21,
    "KEY_5": 0x22,
    "KEY_6": 0x23,
    "KEY_7": 0x24,
    "KEY_8": 0x25,
    "KEY_9": 0x26,
    "KEY_0": 0x27,
    # Control keys
    "KEY_ENTER": 0x28,
    "KEY_ESC": 0x29,
    "KEY_BACKSPACE": 0x2A,
    "KEY_TAB": 0x2B,
    "KEY_SPACE": 0x2C,
    "KEY_MINUS": 0x2D,
    "KEY_EQUAL": 0x2E,
    "KEY_LEFTBRACE": 0x2F,
    "KEY_RIGHTBRACE": 0x30,
    "KEY_BACKSLASH": 0x31,
    "KEY_SEMICOLON": 0x33,
    "KEY_APOSTROPHE": 0x34,
    "KEY_GRAVE": 0x35,
    "KEY_COMMA": 0x36,
    "KEY_DOT": 0x37,
    "KEY_SLASH": 0x38,
    "KEY_CAPSLOCK": 0x39,
    # Function keys
    "KEY_F1": 0x3A,
    "KEY_F2": 0x3B,
    "KEY_F3": 0x3C,
    "KEY_F4": 0x3D,
    "KEY_F5": 0x3E,
    "KEY_F6": 0x3F,
    "KEY_F7": 0x40,
    "KEY_F8": 0x41,
    "KEY_F9": 0x42,
    "KEY_F10": 0x43,
    "KEY_F11": 0x44,
    "KEY_F12": 0x45,
    # Special keys
    "KEY_PRINTSCREEN": 0x46,
    "KEY_SCROLLLOCK": 0x47,
    "KEY_PAUSE": 0x48,
    "KEY_INSERT": 0x49,
    "KEY_HOME": 0x4A,
    "KEY_PAGEUP": 0x4B,
    "KEY_DELETE": 0x4C,
    "KEY_END": 0x4D,
    "KEY_PAGEDOWN": 0x4E,
    "KEY_RIGHT": 0x4F,
    "KEY_LEFT": 0x50,
    "KEY_DOWN": 0x51,
    "KEY_UP": 0x52,
    # Keypad
    "KEY_NUMLOCK": 0x53,
    "KEY_KP_SLASH": 0x54,
    "KEY_KP_ASTERISK": 0x55,
    "KEY_KP_MINUS": 0x56,
    "KEY_KP_PLUS": 0x57,
    "KEY_KP_ENTER": 0x58,
    "KEY_KP_1": 0x59,
    "KEY_KP_2": 0x5A,
    "KEY_KP_3": 0x5B,
    "KEY_KP_4": 0x5C,
    "KEY_KP_5": 0x5D,
    "KEY_KP_6": 0x5E,
    "KEY_KP_7": 0x5F,
    "KEY_KP_8": 0x60,
    "KEY_KP_9": 0x61,
    "KEY_KP_0": 0x62,
    "KEY_KP_DOT": 0x63,
    # Additional keys
    "KEY_APPLICATION": 0x65,  # Menu key
}

# Generate SCANCODE_* entries for all possible scancodes (0-255)
# This allows support for custom/unused scancodes beyond standard keys
for i in range(256):
    scancode_name = f"SCANCODE_{i}"
    HID_KEY_SCANCODES[scancode_name] = i

# Continue with regular key definitions
HID_KEY_SCANCODES.update({
    # Modifier keys (individual scancodes)
    "KEY_LEFTCTRL": 0xE0,
    "KEY_LEFTSHIFT": 0xE1,
    "KEY_LEFTALT": 0xE2,
    "KEY_LEFTMETA": 0xE3,
    "KEY_RIGHTCTRL": 0xE4,
    "KEY_RIGHTSHIFT": 0xE5,
    "KEY_RIGHTALT": 0xE6,
    "KEY_RIGHTMETA": 0xE7,
})

# Modifier bitmasks dictionary
HID_MODIFIER_MASKS = {
    "MOD_LCTRL": 0x01,
    "MOD_LSHIFT": 0x02,
    "MOD_LALT": 0x04,
    "MOD_LMETA": 0x08,
    "MOD_RCTRL": 0x10,
    "MOD_RSHIFT": 0x20,
    "MOD_RALT": 0x40,
    "MOD_RMETA": 0x80,
}

# Character to scancode mapping dictionary
CHAR_TO_SCANCODE = {
    # Letters (lowercase and uppercase map to same scancode)
    "a": HID_KEY_SCANCODES["KEY_A"],
    "A": HID_KEY_SCANCODES["KEY_A"],
    "b": HID_KEY_SCANCODES["KEY_B"],
    "B": HID_KEY_SCANCODES["KEY_B"],
    "c": HID_KEY_SCANCODES["KEY_C"],
    "C": HID_KEY_SCANCODES["KEY_C"],
    "d": HID_KEY_SCANCODES["KEY_D"],
    "D": HID_KEY_SCANCODES["KEY_D"],
    "e": HID_KEY_SCANCODES["KEY_E"],
    "E": HID_KEY_SCANCODES["KEY_E"],
    "f": HID_KEY_SCANCODES["KEY_F"],
    "F": HID_KEY_SCANCODES["KEY_F"],
    "g": HID_KEY_SCANCODES["KEY_G"],
    "G": HID_KEY_SCANCODES["KEY_G"],
    "h": HID_KEY_SCANCODES["KEY_H"],
    "H": HID_KEY_SCANCODES["KEY_H"],
    "i": HID_KEY_SCANCODES["KEY_I"],
    "I": HID_KEY_SCANCODES["KEY_I"],
    "j": HID_KEY_SCANCODES["KEY_J"],
    "J": HID_KEY_SCANCODES["KEY_J"],
    "k": HID_KEY_SCANCODES["KEY_K"],
    "K": HID_KEY_SCANCODES["KEY_K"],
    "l": HID_KEY_SCANCODES["KEY_L"],
    "L": HID_KEY_SCANCODES["KEY_L"],
    "m": HID_KEY_SCANCODES["KEY_M"],
    "M": HID_KEY_SCANCODES["KEY_M"],
    "n": HID_KEY_SCANCODES["KEY_N"],
    "N": HID_KEY_SCANCODES["KEY_N"],
    "o": HID_KEY_SCANCODES["KEY_O"],
    "O": HID_KEY_SCANCODES["KEY_O"],
    "p": HID_KEY_SCANCODES["KEY_P"],
    "P": HID_KEY_SCANCODES["KEY_P"],
    "q": HID_KEY_SCANCODES["KEY_Q"],
    "Q": HID_KEY_SCANCODES["KEY_Q"],
    "r": HID_KEY_SCANCODES["KEY_R"],
    "R": HID_KEY_SCANCODES["KEY_R"],
    "s": HID_KEY_SCANCODES["KEY_S"],
    "S": HID_KEY_SCANCODES["KEY_S"],
    "t": HID_KEY_SCANCODES["KEY_T"],
    "T": HID_KEY_SCANCODES["KEY_T"],
    "u": HID_KEY_SCANCODES["KEY_U"],
    "U": HID_KEY_SCANCODES["KEY_U"],
    "v": HID_KEY_SCANCODES["KEY_V"],
    "V": HID_KEY_SCANCODES["KEY_V"],
    "w": HID_KEY_SCANCODES["KEY_W"],
    "W": HID_KEY_SCANCODES["KEY_W"],
    "x": HID_KEY_SCANCODES["KEY_X"],
    "X": HID_KEY_SCANCODES["KEY_X"],
    "y": HID_KEY_SCANCODES["KEY_Y"],
    "Y": HID_KEY_SCANCODES["KEY_Y"],
    "z": HID_KEY_SCANCODES["KEY_Z"],
    "Z": HID_KEY_SCANCODES["KEY_Z"],
    # Numbers
    "0": HID_KEY_SCANCODES["KEY_0"],
    "1": HID_KEY_SCANCODES["KEY_1"],
    "2": HID_KEY_SCANCODES["KEY_2"],
    "3": HID_KEY_SCANCODES["KEY_3"],
    "4": HID_KEY_SCANCODES["KEY_4"],
    "5": HID_KEY_SCANCODES["KEY_5"],
    "6": HID_KEY_SCANCODES["KEY_6"],
    "7": HID_KEY_SCANCODES["KEY_7"],
    "8": HID_KEY_SCANCODES["KEY_8"],
    "9": HID_KEY_SCANCODES["KEY_9"],
    # Basic punctuation
    " ": HID_KEY_SCANCODES["KEY_SPACE"],
    "\t": HID_KEY_SCANCODES["KEY_TAB"],
    "\n": HID_KEY_SCANCODES["KEY_ENTER"],
    "\r": HID_KEY_SCANCODES["KEY_ENTER"],
    # Unshifted punctuation
    "-": HID_KEY_SCANCODES["KEY_MINUS"],
    "=": HID_KEY_SCANCODES["KEY_EQUAL"],
    "[": HID_KEY_SCANCODES["KEY_LEFTBRACE"],
    "]": HID_KEY_SCANCODES["KEY_RIGHTBRACE"],
    "\\": HID_KEY_SCANCODES["KEY_BACKSLASH"],
    ";": HID_KEY_SCANCODES["KEY_SEMICOLON"],
    "'": HID_KEY_SCANCODES["KEY_APOSTROPHE"],
    "`": HID_KEY_SCANCODES["KEY_GRAVE"],
    ",": HID_KEY_SCANCODES["KEY_COMMA"],
    ".": HID_KEY_SCANCODES["KEY_DOT"],
    "/": HID_KEY_SCANCODES["KEY_SLASH"],
    # Shifted punctuation
    "_": HID_KEY_SCANCODES["KEY_MINUS"],
    "+": HID_KEY_SCANCODES["KEY_EQUAL"],
    "{": HID_KEY_SCANCODES["KEY_LEFTBRACE"],
    "}": HID_KEY_SCANCODES["KEY_RIGHTBRACE"],
    "|": HID_KEY_SCANCODES["KEY_BACKSLASH"],
    ":": HID_KEY_SCANCODES["KEY_SEMICOLON"],
    '"': HID_KEY_SCANCODES["KEY_APOSTROPHE"],
    "~": HID_KEY_SCANCODES["KEY_GRAVE"],
    "<": HID_KEY_SCANCODES["KEY_COMMA"],
    ">": HID_KEY_SCANCODES["KEY_DOT"],
    "?": HID_KEY_SCANCODES["KEY_SLASH"],
    # Shifted numbers
    "!": HID_KEY_SCANCODES["KEY_1"],
    "@": HID_KEY_SCANCODES["KEY_2"],
    "#": HID_KEY_SCANCODES["KEY_3"],
    "$": HID_KEY_SCANCODES["KEY_4"],
    "%": HID_KEY_SCANCODES["KEY_5"],
    "^": HID_KEY_SCANCODES["KEY_6"],
    "&": HID_KEY_SCANCODES["KEY_7"],
    "*": HID_KEY_SCANCODES["KEY_8"],
    "(": HID_KEY_SCANCODES["KEY_9"],
    ")": HID_KEY_SCANCODES["KEY_0"],
}

# Characters that require shift modifier
SHIFTED_CHARS = {
    "A",
    "B",
    "C",
    "D",
    "E",
    "F",
    "G",
    "H",
    "I",
    "J",
    "K",
    "L",
    "M",
    "N",
    "O",
    "P",
    "Q",
    "R",
    "S",
    "T",
    "U",
    "V",
    "W",
    "X",
    "Y",
    "Z",
    "!",
    "@",
    "#",
    "$",
    "%",
    "^",
    "&",
    "*",
    "(",
    ")",
    "_",
    "+",
    "{",
    "}",
    "|",
    ":",
    '"',
    "~",
    "<",
    ">",
    "?",
}


class HIDKeyCodes:
    """USB HID keyboard scancodes - provides constants as class attributes."""

    def __getattr__(self, name):
        """Look up constants from the main dictionary."""
        if name in HID_KEY_SCANCODES:
            return HID_KEY_SCANCODES[name]
        elif name in HID_MODIFIER_MASKS:
            return HID_MODIFIER_MASKS[name]
        raise AttributeError(
            f"'{self.__class__.__name__}' object has no attribute '{name}'"
        )

    @classmethod
    def get_key_name(cls, scancode):
        """Get the name of a key by its scancode."""
        for name, value in HID_KEY_SCANCODES.items():
            if value == scancode:
                return name
        return f"UNKNOWN_{scancode:02X}"


# Create a singleton instance for backward compatibility
HIDKeyCodes = HIDKeyCodes()


class HIDMouseCodes:
    """USB HID mouse button codes."""

    # Mouse buttons (bitmask)
    BTN_LEFT = 0x01
    BTN_RIGHT = 0x02
    BTN_MIDDLE = 0x04
    BTN_BACK = 0x08
    BTN_FORWARD = 0x10
