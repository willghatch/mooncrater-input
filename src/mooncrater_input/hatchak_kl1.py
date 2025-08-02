#!/usr/bin/env python3
"""
Hatchak keyboard layout implementation using KeyboardLayout1.

This is a simplified implementation of the Hatchak keyboard layout
based on the design at ~/dotfileswgh/external/misc/hatchak.

Key design principles from hatchak:
- Dvorak letter layout
- Level 3 shift for numbers (arranged like numpad)
- Modifiers on accessible positions
- Level 5 for control keys and navigation

This implementation focuses on the core layout without the complex
unicode characters and Greek letters from the full XKB version.
"""

from mooncrater_input.keyboard_layout_1 import (
    KeyboardLayout1,
    SpecialKey,
    CharKey,
    LevelModifier,
    Modifier,
    ModifierStyle,
    PassThrough,
)


def create_hatchak_layout() -> KeyboardLayout1:
    """Create the Hatchak keyboard layout."""

    layout_dict = {
        # Escape key
        "KEY_ESC": SpecialKey("KEY_ESC"),

        # Number row - modifiers and special keys
        #"KEY_GRAVE": SpecialKey("KEY_CAPSLOCK"),
        "KEY_GRAVE": "",
        "KEY_1": Modifier("KEY_LEFTHYPER", ModifierStyle.MOMENTARY),
        "KEY_2": Modifier("KEY_LEFTMETA", ModifierStyle.MOMENTARY),
        # TODO - need to add more high-layer keys to much of this row
        "KEY_3": [CharKey("\t"), SpecialKey("KEY_TAB", shifted=True), SpecialKey("KEY_BACKSPACE")],
        "KEY_4": [CharKey("="), CharKey("$"), "≠"],
        "KEY_5": [CharKey(";"), "∞"],
        "KEY_6": [CharKey(":"), "…"],
        "KEY_7": [CharKey("\\"), "°"],
        "KEY_8": [CharKey("/"), "÷"],
        "KEY_9": [CharKey("("), "", "◸", "◺", "◤", "◣"], # TODO - L2
        "KEY_0": [CharKey(")"), "", "◹", "◿", "◥", "◢"], # TODO - L2
        "KEY_MINUS": Modifier("KEY_LEFTMETA", ModifierStyle.MOMENTARY), # the super/windows key is called META here...
        "KEY_EQUAL": Modifier("KEY_RIGHTHYPER", ModifierStyle.MOMENTARY), # TODO - how to encode this
        "KEY_BACKSPACE": [SpecialKey("KEY_BACKSPACE"), SpecialKey("KEY_BACKSPACE"), SpecialKey("KEY_DELETE")],

        # Top row - Dvorak layout with L3 numbers
        "KEY_TAB": Modifier("KEY_LEFTALT", ModifierStyle.MOMENTARY),
        "KEY_Q": Modifier("KEY_LEFTCTRL", ModifierStyle.MOMENTARY),
        "KEY_W": [CharKey("-"), CharKey("_"), CharKey("|"), "¦"],
        "KEY_E": [CharKey("."), CharKey("?"), CharKey(","), "¿"],
        "KEY_R": [CharKey("p"), CharKey("P"), CharKey("<")],
        "KEY_T": [CharKey("y"), CharKey("Y"), CharKey(">")],
        "KEY_Y": [CharKey("f"), CharKey("F"), CharKey("^")],
        "KEY_U": [CharKey("g"), CharKey("G"), CharKey("7")],
        "KEY_I": [CharKey("c"), CharKey("C"), CharKey("8")],
        "KEY_O": [CharKey("r"), CharKey("R"), CharKey("9")],
        "KEY_P": [CharKey("l"), CharKey("L"), CharKey("~"), "¬"],
        "KEY_LEFTBRACE": Modifier("KEY_LEFTCTRL", ModifierStyle.MOMENTARY),
        "KEY_RIGHTBRACE": Modifier("KEY_LEFTALT", ModifierStyle.MOMENTARY),
        "KEY_BACKSLASH": Modifier("KEY_XF86DOS", ModifierStyle.MOMENTARY), # TODO - decide how to encode this.  Probably I need to use scancodes outside of the norm, or use weird events or something.

        # Home row - Dvorak layout with L3 numbers
        "KEY_CAPSLOCK": LevelModifier(2, ModifierStyle.MOMENTARY),
        "KEY_A": [CharKey("a"), CharKey("A"), CharKey("{"), "«", "‹"], # TODO - consider adding home as a modified version of A
        "KEY_S": [CharKey("o"), CharKey("O"), CharKey("}"), "»", "›"],
        "KEY_D": [CharKey("e"), CharKey("E"), CharKey("["), "“", "‘"],
        "KEY_F": [CharKey("u"), CharKey("U"), CharKey("]"), "”", "’"],
        "KEY_G": [CharKey("i"), CharKey("I"), CharKey("!"), "¡"],
        "KEY_H": [CharKey("d"), CharKey("D"), CharKey("*"), "•", SpecialKey("KEY_LEFT")],
        "KEY_J": [CharKey("h"), CharKey("H"), CharKey("4"), "⟅", SpecialKey("KEY_DOWN")],
        "KEY_K": [CharKey("t"), CharKey("T"), CharKey("5"), "⟆", SpecialKey("KEY_UP")],
        "KEY_L": [CharKey("n"), CharKey("N"), CharKey("6"), "", SpecialKey("KEY_RIGHT")],
        "KEY_SEMICOLON": [CharKey("s"), CharKey("S"), CharKey("+"), "±", SpecialKey("KEY_END")],
        "KEY_APOSTROPHE": LevelModifier(2, ModifierStyle.MOMENTARY),
        "KEY_ENTER": [SpecialKey("KEY_ENTER"), SpecialKey("KEY_ENTER", shifted=True)],

        # Bottom row - Dvorak layout with L3 numbers
        "KEY_LEFTSHIFT": LevelModifier(1, ModifierStyle.MOMENTARY),
        "KEY_Z": [CharKey("'"), CharKey("\""), CharKey("`"),],
        "KEY_X": [CharKey("q"), CharKey("Q"), CharKey("@")],
        "KEY_C": [CharKey("j"), CharKey("J"), CharKey("#")],
        "KEY_V": [CharKey("k"), CharKey("K"), SpecialKey("KEY_ESC"), SpecialKey("KEY_ESC", shifted=True)],
        "KEY_B": [CharKey("x"), CharKey("X"), CharKey("&")],
        "KEY_N": [CharKey("b"), CharKey("B"), CharKey("0"), "", "", SpecialKey("KEY_PAGEDOWN")],
        "KEY_M": [CharKey("m"), CharKey("M"), CharKey("1"), "", "", SpecialKey("KEY_PAGEUP")],
        "KEY_COMMA": [CharKey("w"), CharKey("W"), CharKey("2")],
        "KEY_DOT": [CharKey("v"), CharKey("V"), CharKey("3")],
        "KEY_SLASH": [CharKey("z"), CharKey("Z"), CharKey("%")],
        "KEY_RIGHTSHIFT": LevelModifier(1, ModifierStyle.MOMENTARY),

        # Space row
        "KEY_LEFTCTRL": LevelModifier(4, ModifierStyle.MOMENTARY),
        "KEY_LEFTMETA": Modifier("KEY_LEFTMETA", ModifierStyle.MOMENTARY),
        "KEY_LEFTALT": Modifier("KEY_LEFTALT", ModifierStyle.MOMENTARY),
        "KEY_SPACE": [SpecialKey("KEY_SPACE"), SpecialKey("KEY_SPACE", shifted=True), SpecialKey("KEY_SPACE"), SpecialKey("KEY_SPACE")],
        "KEY_RIGHTALT": Modifier("KEY_RIGHTALT", ModifierStyle.MOMENTARY),
        "KEY_RIGHTMETA": Modifier("KEY_RIGHTMETA", ModifierStyle.MOMENTARY),
        "KEY_RIGHTCTRL": LevelModifier(4, ModifierStyle.MOMENTARY),

        # Function keys (basic pass-through)
        "KEY_F1": SpecialKey("KEY_F1"),
        "KEY_F2": SpecialKey("KEY_F2"),
        "KEY_F3": SpecialKey("KEY_F3"),
        "KEY_F4": SpecialKey("KEY_F4"),
        "KEY_F5": SpecialKey("KEY_F5"),
        "KEY_F6": SpecialKey("KEY_F6"),
        "KEY_F7": SpecialKey("KEY_F7"),
        "KEY_F8": SpecialKey("KEY_F8"),
        "KEY_F9": SpecialKey("KEY_F9"),
        "KEY_F10": SpecialKey("KEY_F10"),
        "KEY_F11": SpecialKey("KEY_F11"),
        "KEY_F12": SpecialKey("KEY_F12"),

        # Arrow keys and navigation (pass through when not using L5)
        "KEY_UP": SpecialKey("KEY_UP"),
        "KEY_DOWN": SpecialKey("KEY_DOWN"),
        "KEY_LEFT": SpecialKey("KEY_LEFT"),
        "KEY_RIGHT": SpecialKey("KEY_RIGHT"),
        "KEY_HOME": SpecialKey("KEY_HOME"),
        "KEY_END": SpecialKey("KEY_END"),
        "KEY_PAGEUP": SpecialKey("KEY_PAGEUP"),
        "KEY_PAGEDOWN": SpecialKey("KEY_PAGEDOWN"),
        "KEY_INSERT": SpecialKey("KEY_INSERT"),
        "KEY_DELETE": SpecialKey("KEY_DELETE"),

        # Numpad (pass through)
        "KEY_NUMLOCK": SpecialKey("KEY_NUMLOCK"),
        "KEY_KP_DIVIDE": SpecialKey("KEY_KP_DIVIDE"),
        "KEY_KP_MULTIPLY": SpecialKey("KEY_KP_MULTIPLY"),
        "KEY_KP_MINUS": SpecialKey("KEY_KP_MINUS"),
        "KEY_KP_PLUS": SpecialKey("KEY_KP_PLUS"),
        "KEY_KP_ENTER": SpecialKey("KEY_KP_ENTER"),
        "KEY_KP_DOT": SpecialKey("KEY_KP_DOT"),
        "KEY_KP_0": SpecialKey("KEY_KP_0"),
        "KEY_KP_1": SpecialKey("KEY_KP_1"),
        "KEY_KP_2": SpecialKey("KEY_KP_2"),
        "KEY_KP_3": SpecialKey("KEY_KP_3"),
        "KEY_KP_4": SpecialKey("KEY_KP_4"),
        "KEY_KP_5": SpecialKey("KEY_KP_5"),
        "KEY_KP_6": SpecialKey("KEY_KP_6"),
        "KEY_KP_7": SpecialKey("KEY_KP_7"),
        "KEY_KP_8": SpecialKey("KEY_KP_8"),
        "KEY_KP_9": SpecialKey("KEY_KP_9"),
    }

    return KeyboardLayout1(layout_dict, name="hatchak")


def get_hatchak_description() -> str:
    """Get a description of the Hatchak layout."""
    return """
Hatchak Keyboard Layout (KeyboardLayout1 Implementation)

This is a Dvorak-based layout with multiple levels for efficient typing:

Level 0 (Base): Standard Dvorak letters and basic punctuation
Level 1 (Shift): Uppercase letters and shifted punctuation
Level 2 (L3): Numbers arranged like a numpad on the right hand
Level 4 (L5): Navigation keys (arrows, home, end, page up/down)

Key Features:
- Dvorak letter arrangement for efficient typing
- Numbers accessible via L3 shift (CapsLock or Quote)
- Navigation keys on L5 (Ctrl keys) positioned on hjkl-like pattern
- Modifiers repositioned for better ergonomics:
  * Tab → Alt
  * CapsLock → L3 Shift
  * Q position → Ctrl
  * Ctrl positions → L5 Shift

Modifier Keys:
- Shift: Standard shift behavior (Level 1)
- L3 Shift: Access numbers and symbols (Level 2)
- L5 Shift: Access navigation and control keys (Level 4)
- Ctrl, Alt, Super, Hyper: Positioned for easy access

This layout aims to keep hands in the home position while providing
access to all commonly needed keys and functions.
"""


if __name__ == "__main__":
    # Demo the layout
    layout = create_hatchak_layout()
    print(get_hatchak_description())
    print(f"Layout has {len(layout.get_layout())} key bindings")
    print(f"Current level: {layout.get_current_level()}")
