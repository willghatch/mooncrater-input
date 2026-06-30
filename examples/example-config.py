#!/usr/bin/env python3
"""
Example configuration file for Mooncrater Input

This demonstrates the new library-based architecture where the configuration
file imports and initializes the MooncraterInput library and registers
input/output types.
"""

import sys
import os
import time
import subprocess

# Add src directory to path to import mooncrater_input package
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from mooncrater_input.mooncrater_input_lib import MooncraterInput
from mooncrater_input.keyboard_layout_1 import KeyboardLayout1, TapOrHoldSpecific, HoldSpecificHandleBoth, PassThrough, LevelModifier, ModifierStyle
from mooncrater_input import unicode_handling

# Import and register input/output types
from mooncrater_input import evdev_input
from mooncrater_input import evdev_output
from mooncrater_input import socket_input
# There are a bunch of other input/output types, you can look through the source code.
# But I want to note:  There is a remote input/output type.  I read it briefly, and it looks fine, but I can't thoroughly guarantee it is totally safe.  So if you want to use it, please don't expose it to the internet -- be sure it is firewalled for use only in a secure network.
# Many of the input/output types are either for testing or a fun demo but probably not that useful in practice -- eg. the file_io makes sense for testing, but the remote and hid_gadget_devices input/outputs I don't actually use anymore past demoing.  But maybe I'll use them in the future!
# The hid_gadget_devices backend is actually interesting from the point of view of using a raspberry pi to turn a non-programmable keyboard into a programmable keyboard, but there are simpler ways to do that, such as, well, running something like mooncrater-input on the machine where you use said non-programmable keyboard.

# Create MooncraterInput instance
mi = MooncraterInput(log_level="info")

# Register all input/output types we want to use
evdev_input.register(mi)
evdev_input.default_auto_reconnect = False  # Set True to reconnect all devices on disconnect by default
evdev_output.register(mi)
socket_input.register(mi)

# Create local virtual devices with tag "main" - these will be our primary output
if not mi.create_output("virtual_evdev", "main"):
    import sys
    sys.exit(1)


# Socket input configuration - disabled by default.
# Set allow_commands_from_socket = True to allow commands (e.g. attach devices) via the socket.
# Set allow_events_from_socket = True to allow input events to be injected via the socket.
allow_commands_from_socket = False
allow_events_from_socket = False
# Uncomment the next line to enable the Unix domain socket input:
# mi.create_input("socket", "localsocket", socket_path="/tmp/mooncrater-input-socket")
# mi.create_input("socket", "localsocket", socket_path="/tmp/mooncrater-input-socket", mode=0o660)


# List of devices to capture.
# Replace these example paths with your actual device paths.
# Use `ls /dev/input/by-id/` or `ls /dev/input/by-path/` to find your devices.
devices_to_capture = {
    # "red-keyboard": {"device": "/dev/input/by-id/usb-0000_0000-event-kbd", "autoReconnect": True},
    # "gamer-mouse": "/dev/input/by-id/usb-ExampleVendor_USB_Receiver-if02-event-mouse",
}


# Global state management
globalState = {
    "currentMapping": None,  # Will be set to qwertyStandardMapping below
    "currentOutput": "main",
    "appState": {},
    "bindingState": {},
    "numpadMode": False,  # When True, swap number row keys to keypad number keys
    "mouseToScrollMode": False,  # When True, convert mouse movement to smooth scroll
    "mouse4Down": False,  # When True, mouse movement becomes scroll and scroll adjusts multiplier
    "mouseMovementMultiplier": 1.0,  # Multiplier for mouse movement events
    "allowMacroRecording": False,  # Must be toggled on before recording/playback works
    "macroMaxLength": 200,  # Auto-stop recording after this many events
}


# Mapping functions - convert between keyboard layouts
qwertyStandardMapping = KeyboardLayout1({}, unbound_handler="pass_through", name="qwerty")

# Mouse modifiers layout - handles mouse button 4 behavior
# Mouse button 4 (back button) toggles mouse movement -> scroll and scroll -> multiplier adjustment
def mouse4_down_handler(event):
    """Handle mouse button 4 down event - set global state."""
    globalState["mouse4Down"] = True
    print("Mouse button 4 pressed - mouse movement -> scroll, scroll -> adjust multiplier")
    update_status_file()
    return []

def mouse4_up_handler(event):
    """Handle mouse button 4 up event - clear global state."""
    globalState["mouse4Down"] = False
    print("Mouse button 4 released")
    update_status_file()
    return []

mouseMods = KeyboardLayout1({
    # back is mouse 4, forward is mouse 5
    "BTN_BACK": (mouse4_down_handler, mouse4_up_handler),
}, unbound_handler="pass_through", name="mouseMods")

# Available mappings
globalState["currentMapping"] = qwertyStandardMapping


def get_current_mapping_name():
    """Get the name of the current mapping."""
    if hasattr(globalState["currentMapping"], "getName"):
        return globalState["currentMapping"].getName()
    else:
        return "Unknown"


def cycle_mapping():
    """Cycle to the next mapping in the list."""
    current_idx = mappings.index(globalState["currentMapping"])
    next_idx = (current_idx + 1) % len(mappings)
    globalState["currentMapping"] = mappings[next_idx]
    print(f"Switched to {get_current_mapping_name()} mapping")
    update_status_file()


def cycle_output():
    """Cycle to the next available output."""
    try:
        outputs = mi.get_output_tags()
        # Ensure all outputs are strings (tag names only)
        outputs = [str(tag) for tag in outputs]
    except Exception as e:
        print(f"Error getting output tags: {e}")
        return

    if not outputs:
        print("No outputs available")
        return

    current_output = str(globalState["currentOutput"])
    try:
        current_idx = outputs.index(current_output)
        next_idx = (current_idx + 1) % len(outputs)
    except ValueError:
        # Current output not in list, default to first
        next_idx = 0

    globalState["currentOutput"] = outputs[next_idx]
    print(f"Switched to output: {globalState['currentOutput']}")
    update_status_file()



def toggle_mouse_to_scroll():
    """Toggle mouse-to-scroll mode."""
    globalState["mouseToScrollMode"] = not globalState["mouseToScrollMode"]
    mode_str = "ON" if globalState["mouseToScrollMode"] else "OFF"
    print(f"Mouse-to-scroll mode: {mode_str}")
    update_status_file()


def toggle_allow_macro_recording():
    """Toggle whether macro recording/playback is allowed."""
    globalState["allowMacroRecording"] = not globalState["allowMacroRecording"]
    mode_str = "ENABLED" if globalState["allowMacroRecording"] else "DISABLED"
    print(f"Macro recording: {mode_str}")
    update_status_file()


def toggle_numpad_mode():
    """Toggle numpad mode: when on, number row keys are emitted as keypad number keys."""
    globalState["numpadMode"] = not globalState["numpadMode"]
    mode_str = "ON" if globalState["numpadMode"] else "OFF"
    print(f"Numpad mode: {mode_str}")
    update_status_file()


def handleMouseToScroll(events):
    """Convert mouse movement events to smooth scroll events when mouse-to-scroll mode is enabled."""
    if not globalState["mouseToScrollMode"]:
        return events

    processed_events = []
    for event in events:
        if (
            event.get("category") == "mouse"
            and event.get("type") == "mouseRel"
            and ("deltaX" in event or "deltaY" in event)
        ):

            # Convert mouse movement to smooth scroll
            # Scale mouse movement for reasonable scroll speed
            scale_factor = 0.1  # Adjust this value to change scroll sensitivity
            delta_x = event.get("deltaX", 0) * scale_factor
            delta_y = event.get("deltaY", 0) * scale_factor
            # invert y axis!
            delta_y = -delta_y

            # Create smooth scroll event instead of mouse movement
            scroll_event = {
                "category": "mouse",
                "type": "smoothScroll",
                "deltaX": delta_x,
                "deltaY": delta_y,
                "source": event["inputTag"],
            }
            processed_events.append(scroll_event)
        else:
            # Pass through other events unchanged
            processed_events.append(event)

    return processed_events


def handleMouseMods(events):
    """Handle mouse modifier logic when mouse button 4 is held."""
    processed_events = []

    for event in events:
        # Apply mouse modifier logic if mouse4 is down
        if globalState["mouse4Down"]:
            # Convert relative mouse movement to scroll events
            if (event.get("category") == "mouse" and
                event.get("type") == "mouseRel"):

                # Convert mouse movement to smooth scroll
                scale_factor = 0.1  # Adjust for scroll sensitivity
                delta_x = event.get("deltaX", 0) * scale_factor
                delta_y = event.get("deltaY", 0) * scale_factor
                # Invert y axis for natural scrolling
                delta_y = -delta_y

                scroll_event = {
                    "category": "mouse",
                    "type": "smoothScroll",
                    "deltaX": delta_x,
                    "deltaY": delta_y,
                    "source": event.get("inputTag", "mouseMods"),
                }
                processed_events.append(scroll_event)
                continue

            # Convert scroll events to mouse behavior adjustments
            elif (event.get("category") == "mouse" and
                  event.get("type") in ["scroll", "smoothScroll"]):

                # Ignore X axis, use Y axis to adjust multiplier
                delta_y = event.get("deltaY", 0)

                # Handle both regular scroll and smooth scroll
                adjustment = delta_y * 0.1

                # Adjust the mouse movement multiplier
                globalState["mouseMovementMultiplier"] += adjustment
                # Clamp to reasonable bounds
                globalState["mouseMovementMultiplier"] = max(0.1, min(10.0, globalState["mouseMovementMultiplier"]))

                print(f"Mouse movement multiplier adjusted to: {globalState['mouseMovementMultiplier']:.1f}")
                update_status_file()
                # Don't pass through scroll events when mouse4 is down
                continue

        else:
            # Apply mouse movement multiplier to all mouse movement events
            if (event.get("category") == "mouse" and
                event.get("type") == "mouseRel" and
                globalState["mouseMovementMultiplier"] != 1.0):

                # Scale the mouse movement
                delta_x = event.get("deltaX", 0) * globalState["mouseMovementMultiplier"]
                delta_y = event.get("deltaY", 0) * globalState["mouseMovementMultiplier"]

                modified_event = event.copy()
                modified_event["deltaX"] = delta_x
                modified_event["deltaY"] = delta_y
                processed_events.append(modified_event)
                continue

        # Pass through all other events unchanged
        processed_events.append(event)

    return processed_events



_NUMBER_TO_KP = {
    "KEY_0": "KEY_KP0",
    "KEY_1": "KEY_KP1",
    "KEY_2": "KEY_KP2",
    "KEY_3": "KEY_KP3",
    "KEY_4": "KEY_KP4",
    "KEY_5": "KEY_KP5",
    "KEY_6": "KEY_KP6",
    "KEY_7": "KEY_KP7",
    "KEY_8": "KEY_KP8",
    "KEY_9": "KEY_KP9",
}


def handleNumpadMode(events):
    """When numpadMode is on, swap number row key events to keypad number key events.

    Some applications (e.g. PIN entry dialogs) only accept one type or the other.
    This runs near the end of the output chain so the swap is independent of layout.
    """
    if not globalState["numpadMode"]:
        return events
    result = []
    for event in events:
        key = event.get("keyName")
        if event.get("category") == "keyboard" and key in _NUMBER_TO_KP:
            event = event.copy()
            event["keyName"] = _NUMBER_TO_KP[key]
            # Clear keyChar and scancode so the output uses keyName exclusively;
            # the char "5" would otherwise resolve back to KEY_5, not KEY_KP5.
            event.pop("keyChar", None)
            event.pop("scancode", None)
        result.append(event)
    return result


def handle_demo_string(event):
    """Send a synthetic string typing example."""
    synthetic_events = [
        {
            "category": "keyboard",
            "type": "typeQwertyString",
            "string": "hello",
            "inputTag": "synthetic",
        },
    ]
    print("Sending synthetic 'hello' string")
    mi.send_events_to_backend(synthetic_events, globalState["currentOutput"])
    return []


def handle_test_ultra(event):
    """Send Ultra+E to validate the Ultra modifier (Mod3/XF86Tools) is working."""
    events = [
        {"category": "keyboard", "type": "keyDown", "keyName": "KEY_ULTRA", "inputTag": "synthetic"},
        {"category": "keyboard", "type": "keyDown", "keyName": "KEY_E", "inputTag": "synthetic"},
        {"category": "keyboard", "type": "keyUp", "keyName": "KEY_E", "inputTag": "synthetic"},
        {"category": "keyboard", "type": "keyUp", "keyName": "KEY_ULTRA", "inputTag": "synthetic"},
    ]
    print("Testing Ultra modifier: sending KEY_ULTRA+E")
    mi.send_events_to_backend([translate_to_qwerty_mod_mooncrater(e) for e in events], "main")
    return []


def handle_test_beyond(event):
    """Send Beyond+E to validate the Beyond modifier (Mod5/XF86Word) is working."""
    events = [
        {"category": "keyboard", "type": "keyDown", "keyName": "KEY_BEYOND", "inputTag": "synthetic"},
        {"category": "keyboard", "type": "keyDown", "keyName": "KEY_E", "inputTag": "synthetic"},
        {"category": "keyboard", "type": "keyUp", "keyName": "KEY_E", "inputTag": "synthetic"},
        {"category": "keyboard", "type": "keyUp", "keyName": "KEY_BEYOND", "inputTag": "synthetic"},
    ]
    print("Testing Beyond modifier: sending KEY_BEYOND+E")
    mi.send_events_to_backend([translate_to_qwerty_mod_mooncrater(e) for e in events], "main")
    return []


def create_global_control_layout():
    """Create a KeyboardLayout1 for global control bindings."""

    def handle_control_prefix_down(mod_event, prefix_event):
        """Handler for when KEY_4 + KEY_9 is pressed (enter control mode)."""
        print("Entered control mode - next key will be a control command")
        # Activate level 1 using one-shot modifier
        return []

    def handle_control_prefix_up(prefix_event):
        """Handler for when the control prefix key is released."""
        # Keep control mode active until a command is executed
        return []

    # Control command functions

    def handle_show_status(event):
        """Show status."""
        try:
            outputs = mi.get_output_tags()
            # Ensure all outputs are strings (tag names only)
            output_tags = [str(tag) for tag in outputs]
        except Exception as e:
            print(f"Error getting output tags: {e}")
            output_tags = ["unknown"]

        mouse_scroll_status = "ON" if globalState["mouseToScrollMode"] else "OFF"
        current_output_tag = str(globalState["currentOutput"])
        print(f"Status - Current output: {current_output_tag}")
        print(f"Available outputs: {', '.join(output_tags)}")
        print(f"Current mapping: {get_current_mapping_name()}")
        print(f"Mouse-to-scroll mode: {mouse_scroll_status}")
        print(f"Numpad mode: {'ON' if globalState.get('numpadMode', False) else 'OFF'}")
        print(f"Allow macro recording: {globalState.get('allowMacroRecording', False)}")
        print(f"Macro max length: {globalState.get('macroMaxLength', 200)}")
        return []

    def handle_macro_record_toggle(event):
        """Toggle macro recording on/off, if allowed."""
        if not globalState["allowMacroRecording"]:
            print("Macro recording is disabled. Toggle allowMacroRecording first (4+9, p).")
            return []
        if macroRecorder.is_recording:
            macroRecorder.stopRecording()
        else:
            macroRecorder.startRecording("user")
        update_status_file()
        return []

    def handle_macro_playback(event):
        """Play back the recorded macro, if allowed."""
        if not globalState["allowMacroRecording"]:
            print("Macro playback is disabled. Toggle allowMacroRecording first (4+9, p).")
            return []
        playback_event = {
            "category": "macro",
            "type": "playback",
            "tag": "user",
            "inputTag": "synthetic"
        }
        status = macroRecorder.get_status()
        if "user" in status["available_recordings"]:
            recording = macroRecorder.getRecording("user")
            print(f"Would play back macro 'user' with {len(recording)} events")
            return [playback_event]
        else:
            print("No macro recorded yet...")
        return []

    def handle_macro_status(event):
        """Show macro recorder status."""
        status = macroRecorder.get_status()
        print(f"Macro Status:")
        print(f"  Recording: {status['is_recording']}")
        if status['is_recording']:
            print(f"  Current tag: {status['current_recording_tag']}")
            print(f"  Events recorded: {status['current_recording_length']}")
        print(f"  Available recordings: {status['available_recordings']}")
        return []


    # Create the layout with KEY_4 as tap-or-hold and control commands on layer 1
    layout = {
        # Layer 0 (default): passthrough for all keys
        "KEY_4": {
            0: TapOrHoldSpecific(
                tap=PassThrough(),  # When tapped alone, pass through normally
                hold={
                    # When held with KEY_9, activate layer 1 (control mode)
                    "KEY_9": LevelModifier(1, style=ModifierStyle.ONE_SHOT),
                }
            )
        },

        # Control command keys - layer 0: passthrough, layer 1: control functions
        "KEY_S": {
            0: PassThrough(),
            1: (lambda event: cycle_output() or [], lambda event: [])  # Function pair for switch output
        },
        "KEY_M": {
            0: PassThrough(),
            1: (lambda event: cycle_mapping() or [], lambda event: [])  # Function pair for switch mapping
        },
        "KEY_K": {
            0: PassThrough(),
            1: (handle_show_status, lambda event: [])  # Function pair for show status
        },
        "KEY_O": {
            0: PassThrough(),
            1: (handle_macro_record_toggle, lambda event: [])  # Toggle recording (requires allowMacroRecording)
        },
        "KEY_R": {
            0: PassThrough(),
            1: (handle_macro_playback, lambda event: [])  # Play back macro
        },
        "KEY_COMMA": {
            0: PassThrough(),
            1: (handle_macro_status, lambda event: [])  # Show macro status
        }
    }

    return KeyboardLayout1(layout, unbound_handler="pass_through", name="global_control")

# Create the global control layout instance
global_control_layout = create_global_control_layout()

# Extend the layout with additional bindings (demo of extending an existing KeyboardLayout1)
global_control_layout = global_control_layout.merge_layout({
    "KEY_D": {
        0: PassThrough(),
        1: (handle_demo_string, lambda event: [])  # Function pair for demo string
    },
    "KEY_SEMICOLON": {
        0: PassThrough(),
        1: (lambda event: toggle_mouse_to_scroll() or [], lambda event: [])  # Function pair for toggle scroll
    },
    "KEY_P": {
        0: PassThrough(),
        1: (lambda event: toggle_allow_macro_recording() or [], lambda event: [])  # Toggle allowMacroRecording
    },
    "KEY_N": {
        0: PassThrough(),
        1: (lambda event: toggle_numpad_mode() or [], lambda event: [])  # Toggle numpad mode
    },
    "KEY_U": {
        0: PassThrough(),
        1: (handle_test_ultra, lambda event: [])  # Send Ultra+E to validate Ultra modifier
    },
    "KEY_B": {
        0: PassThrough(),
        1: (handle_test_beyond, lambda event: [])  # Send Beyond+E to validate Beyond modifier
    },
})

def handleGlobalScancodeBindings(events):
    """Handle global key bindings using KeyboardLayout1 and TapOrHoldSpecific."""
    # Process all events through the layout (handles both normal keys and control mode)
    return global_control_layout.process_events(events)


from mooncrater_input import hatchak_kl1
from mooncrater_input.hatchak_kl1 import create_hatchak_layout
hatchakKbd = create_hatchak_layout()
mappings = [
    qwertyStandardMapping,
    hatchakKbd,
]

# Intercept QMK UNICODE_MODE_WINDOWS sequences (Alt+KP+<hex>) and convert them
# to typeUnicodeString events so the existing unicode output path handles them.
windows_unicode_capture = unicode_handling.WindowsUnicodeCapture()

# Macro recorder setup
from mooncrater_input.macro_recorder import MacroRecorder
macroRecorder = MacroRecorder()

# Status update to file class
import asyncio
import threading
import os
from datetime import datetime

class StatusUpdateToFile:
    """A class that asynchronously updates a file with status information."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self._loop = None
        self._thread = None
        self._stop_event = threading.Event()
        self._start_async_loop()

    def _start_async_loop(self):
        """Start the async event loop in a separate thread."""
        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._loop.run_until_complete(self._run_until_stopped())

        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()

    async def _run_until_stopped(self):
        """Keep the event loop running until stopped."""
        while not self._stop_event.is_set():
            await asyncio.sleep(0.1)

    def update(self, status_string: str):
        if self._loop and not self._loop.is_closed():
            # Schedule the async update
            asyncio.run_coroutine_threadsafe(self._async_update(status_string), self._loop)

    async def _async_update(self, status_string: str):
        """Asynchronously update the file with the status string."""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)

            # Write the status string to the file, replacing the entire contents
            with open(self.file_path, 'w') as f:
                f.write(status_string)
                f.flush()
        except Exception as e:
            print(f"Error updating status file {self.file_path}: {e}")

    def close(self):
        """Stop the async loop and clean up."""
        if self._stop_event:
            self._stop_event.set()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)

# Create status updater instance
statusUpdater = StatusUpdateToFile("/tmp/mooncrater-input-status")

def update_status_file():
    """Update the status file with current system status."""
    try:
        # Gather current status information
        current_output = str(globalState["currentOutput"])
        current_mapping = get_current_mapping_name()

        # Get current keyboard layout level
        current_level = 0
        if hasattr(globalState["currentMapping"], "current_level"):
            current_level = globalState["currentMapping"].current_level

        # Get current modifier state
        modifier_state = "none"
        if hasattr(globalState["currentMapping"], "modifier_state") and globalState["currentMapping"].modifier_state:
            modifier_state = str(globalState["currentMapping"].modifier_state)

        # Get mouse multiplier
        mouse_multiplier = globalState.get("mouseMovementMultiplier", 1.0)

        # Get macro recording status
        macro_status = macroRecorder.get_status()
        macro_recording = ""
        if globalState.get("allowMacroRecording", False):
            macro_recording = "MACRO REC" if macro_status["is_recording"] else "MACRO OK"
            if macro_status["is_recording"]:
                macro_recording += f" ({macro_status['current_recording_tag']})"

        # Get mouse-to-scroll mode
        mouse_scroll_mode = "on" if globalState.get("mouseToScrollMode", False) else "off"

        # Get mouse4 button state
        mouse4_state = "pressed" if globalState.get("mouse4Down", False) else "released"

        # Format status string
        numpad_str = "NP|" if globalState.get("numpadMode", False) else ""
        status_lines = [
            f"O:{current_output}|",
            f"KM:{current_mapping}|",
            f"L{current_level}|",
            f"Mod:{modifier_state}|",
            f"MouseMul:{mouse_multiplier:.1f}|",
            numpad_str,
            #f"Mouse-to-Scroll: {mouse_scroll_mode}",
            #f"Mouse4: {mouse4_state}",
            f"{macro_recording}"
        ]

        status_string = "".join(status_lines)
        statusUpdater.update(status_string)

    except Exception as e:
        print(f"Error updating status: {e}")


def attach_all_evdev_keyboards_and_mice(extra_exclude=None):
    """Attach all evdev keyboards and mice from /dev/input except mooncrater virtual devices.

    A keyboard is any device with EV_KEY capabilities in the KEY_ESC..KEY_MICMUTE range.
    A mouse is any device with EV_REL REL_X or REL_Y axes.

    Args:
        extra_exclude: Optional list of device specifiers (paths or names) to additionally
                       exclude beyond mooncrater's own virtual evdev outputs.
    """
    try:
        import evdev
        from evdev import ecodes as e
    except ImportError:
        print("evdev not available; cannot attach devices")
        return

    exclude_set = set(extra_exclude) if extra_exclude else set()

    if "captured_devices" not in mi.backend_storage:
        mi.backend_storage["captured_devices"] = evdev_input.EvdevInputCapture(
            mi._create_input_handler("capturedDevice")
        )

    captured = mi.backend_storage["captured_devices"]

    try:
        all_paths = evdev.list_devices()
    except (OSError, PermissionError) as err:
        print(f"Could not list /dev/input devices: {err}")
        return

    for path in all_paths:
        try:
            dev = evdev.InputDevice(path)
            name = dev.name
            caps = dev.capabilities()
            dev.close()
        except (OSError, PermissionError):
            continue

        if "mooncrater-input" in name:
            continue

        if path in exclude_set or name in exclude_set:
            continue

        if path in captured.captured_devices or path in captured.device_identifiers:
            continue
        if name in set(captured.device_identifiers.values()):
            continue

        keys = caps.get(e.EV_KEY, [])
        rel_axes = caps.get(e.EV_REL, [])
        is_keyboard = any(e.KEY_ESC <= k <= e.KEY_MICMUTE for k in keys)
        is_mouse = e.REL_X in rel_axes or e.REL_Y in rel_axes

        if not (is_keyboard or is_mouse):
            continue

        if captured.capture_device(path, "captures"):
            print(f"Attached: {name} ({path})")
        else:
            print(f"Failed to attach: {name} ({path})")


def handle_socket_command(event):
    """Dispatch a command received over the Unix domain socket.

    Supported commands (send as JSON with category "command"):

      {"category": "command", "type": "attach_evdev_devices",
       "devices": ["/dev/input/event0", "My Keyboard Name", ...]}

          Capture each listed device (path or evdev name) into the
          "captures" group.

      {"category": "command", "type": "attach_all_evdev_except",
       "exclude": ["/dev/input/event0", ...]}

          Attach every keyboard and mouse in /dev/input except
          mooncrater virtual outputs and the devices in "exclude"
          (paths or names).  "exclude" may be omitted.
    """
    cmd_type = event.get("type")

    if cmd_type == "attach_evdev_devices":
        devices = event.get("devices", [])
        if not devices:
            print("attach_evdev_devices: no devices specified")
            return
        if "captured_devices" not in mi.backend_storage:
            print("attach_evdev_devices: no evdev capture backend available")
            return
        captured = mi.backend_storage["captured_devices"]
        for identifier in devices:
            if captured.capture_device(identifier, "captures"):
                print(f"Attached: {identifier}")
            else:
                print(f"Failed to attach: {identifier}")

    elif cmd_type == "attach_all_evdev_except":
        exclude = event.get("exclude", None)
        attach_all_evdev_keyboards_and_mice(extra_exclude=exclude)

    else:
        print(f"Unknown socket command type: {cmd_type!r}")


# Maps virtual modifier key names used in keyboard layouts to the actual evdev key names
# that appear in the qwerty-mod-mooncrater XKB file:
#   KEY_CLOSECD      (evdev 160) -> XKB 168 -> <MOD2> -> Hyper_L  (Mod2)
#   KEY_EJECTCD      (evdev 161) -> XKB 169 -> <MOD3> -> XF86Tools (Mod3 / Ultra)
#   KEY_EJECTCLOSECD (evdev 162) -> XKB 170 -> <MOD5> -> XF86Word  (Mod5 / Beyond)
_HYPER_KEYS = {"KEY_HYPER", "KEY_LEFTHYPER", "KEY_RIGHTHYPER"}

def translate_hyper_to_numlock(event):
    if event.get("category") != "keyboard":
        return event
    if event.get("keyName") in _HYPER_KEYS:
        event = event.copy()
        event["keyName"] = "KEY_NUMLOCK"
        event.pop("keyChar", None)
        event.pop("scancode", None)
    return event


def translate_to_qwerty_mod_mooncrater(event):
    if event.get("category") != "keyboard":
        return event
    _translation = {
        "KEY_HYPER":      "KEY_CLOSECD",
        "KEY_LEFTHYPER":  "KEY_CLOSECD",
        "KEY_RIGHTHYPER": "KEY_CLOSECD",
        "KEY_ULTRA":      "KEY_EJECTCD",
        "KEY_BEYOND":     "KEY_EJECTCLOSECD",
    }
    keyName = event.get("keyName")
    if keyName in _translation:
        event = event.copy()
        event["keyName"] = _translation[keyName]
        event.pop("keyChar", None)
    return event


def handler(device, jsonEvent):
    """Main event handler - processes all input events through the pipeline."""
    #print(f"Handling: {jsonEvent}")

    # Intercept commands delivered via the Unix domain socket before the event
    # pipeline.  Commands use category "command" so they are never forwarded to
    # any output backend.
    if (jsonEvent.get("category") == "command" and
            jsonEvent.get("inputKind") == "unixDomainSocket"):
        if allow_commands_from_socket:
            handle_socket_command(jsonEvent)
        return

    # Drop all other events arriving via the socket if socket events are not allowed.
    if (jsonEvent.get("inputKind") == "unixDomainSocket" and
            not allow_events_from_socket):
        return

    # Put event in a list for pipeline processing
    # If it's an eventList type, splice it (flatten the events)
    if jsonEvent.get("type") == "eventList":
        events = jsonEvent.get("events", [])
    else:
        events = [jsonEvent]

    # Note that mice that give smooth scroll events give both smooth and
    # non-smooth events, but the device code filters out one or the other so
    # that we just see one here.

    # (0) Convert QMK UNICODE_MODE_WINDOWS Alt+KP+<hex> sequences to typeUnicodeString events
    events = windows_unicode_capture.process_events(events)

    # (1) Handle global scancode-based key bindings
    # This handles modifier+prefix combinations for control commands
    events = handleGlobalScancodeBindings(events)

    # If events were consumed by control bindings, don't process further
    if not events:
        return

    # (1.5) Handle mouse modifiers using mouseMods keymap
    # Process through the mouseMods layout which handles mouse button 4 state changes
    events = mouseMods.process_events(events)

    # Apply mouse button 4 bindings and modifier logic
    events = handleMouseMods(events)

    # If events were consumed by mouse modifiers, don't process further
    if not events:
        return

    # (2) Apply current keyboard layout mapping
    if hasattr(globalState["currentMapping"], "process_events"):
        events = globalState["currentMapping"].process_events(events)
    else:
        events = globalState["currentMapping"](events)


    # (3) Handle mouse-to-scroll conversion if enabled
    events = handleMouseToScroll(events)

    # TODO - I maybe want global keyboard mappings in terms of the current keyboard layout, which can go here.

    # Filter out unknown categories of events.
    # I think these unknown events are Sync events, and I'm not sure how important they are.
    events = [event for event in events if event.get("category", None) != "unknown"]

    events = macroRecorder.process(events)

    # Auto-stop recording if macro exceeds max length
    if macroRecorder.is_recording and len(macroRecorder.current_recording) >= globalState["macroMaxLength"]:
        print(f"Macro recording auto-stopped: reached max length of {globalState['macroMaxLength']} events")
        macroRecorder.stopRecording()
        update_status_file()

    # (5) Swap number row keys to keypad keys if numpad mode is active
    events = handleNumpadMode(events)

    # (6) Send to output
    for event in events:
        #print(f"output handle for event: {event}")
        useOutput = None
        # Check if event has a targetOutput field to override the current output
        if "targetOutput" in event:
            useOutput = event["targetOutput"]
        else:
            useOutput = globalState["currentOutput"]

        if useOutput == "main":
            # Translate KEY_LEFTHYPER and KEY_RIGHTHYPER to SCANCODE_165
            if event.get("category") == "keyboard" and event.get("type") in ("typeUnicodeString", "typeString"):
                events = unicode_handling.unicode_char_to_linux_custom_xcompose(event)
                event = {"type": "eventList", "events": events}
                # TODO - maybe use ydotool or something instead of this xcompose stuff
            if event.get("category") == "keyboard":
                event = translate_to_qwerty_mod_mooncrater(event)

        #print(f"sending event: {event}")
        mi.send_events_to_backend([event], useOutput)


# Register our main event handler
mi.set_event_handler(handler)

#### Now that the handler is set, capture inputs.

# Capture input devices exclusively
mi.create_input("evdev_capture", "captures", device_identifiers=devices_to_capture)

# Or just try to capture everything.
#attach_all_evdev_keyboards_and_mice()


print("=== Mooncrater Input Configuration Loaded ===")
print(f"Current mapping: {get_current_mapping_name()}")
print(f"Current output: {globalState['currentOutput']}")
try:
    output_tags = [str(tag) for tag in mi.get_output_tags()]
    print("Available outputs:", ', '.join(output_tags))
except Exception as e:
    print(f"Available outputs: Error getting output tags - {e}")
print("")
print("Control commands (4/= + 9/(, then):  [qwerty/hatchak]")
print("  s/o - Switch output device")
print("  m/m - Switch keyboard mapping")
print("  k/t - Show status")
print("  d/e - Send demo 'hello' sequence")
print("  ;/s - Toggle mouse-to-scroll mode")
print("  p/l - Toggle allowMacroRecording (must enable before recording/playback)")
print("  o/r - Toggle macro recording (start/stop, requires allowMacroRecording)")
print("  r/p - Play back recorded macro (requires allowMacroRecording)")
print("  ,/w - Show macro recorder status")
print("  n/n - Toggle numpad mode (swap number row to keypad keys)")
print("===========================================")

# Initialize status file with current state
update_status_file()


# Example of setting up a timer-based synthetic event
def send_periodic_event():
    """Example of how to send synthetic events on a timer."""
    # This could be used for things like keepalive signals
    # or periodic status updates
    pass


# You could set up threading.Timer calls here for periodic events
# import threading
# timer = threading.Timer(60.0, send_periodic_event)  # Every 60 seconds
# timer.daemon = True
# timer.start()

# Run the MooncraterInput instance
if __name__ == "__main__":
    mi.run()
