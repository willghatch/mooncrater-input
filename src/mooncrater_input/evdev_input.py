#!/usr/bin/env python3

import ctypes
import logging
import os
import select
import struct
import threading
import time
from typing import Optional, Callable
from .utils import _log_global

# Set up logging
logger = logging.getLogger(__name__)

# Global default for auto-reconnect behaviour.  Set this to True in your
# config file to enable reconnection for all captured devices unless
# overridden per-device with the "autoReconnect" key.
default_auto_reconnect = False


class EvdevInputCapture:
    """Manages evdev input device capture and translation to JSON events."""

    def __init__(self, event_callback):
        """Initialize with a callback function that receives (device_path, json_event)."""
        self.event_callback = event_callback
        self.captured_devices = {}  # path -> InputDevice
        self.device_tags = {}  # path -> tag
        self.device_identifiers = {}  # path -> original identifier used to capture (name or path)
        self.device_names = {}  # path -> custom device name
        self.device_scroll_types = {}  # path -> scroll type ("smooth", "non-smooth", or "auto")
        self.device_detected_smooth = {}  # path -> bool (for auto-detect)
        self.device_monitors = []  # List of monitoring threads
        self._evdev_translator = None
        self.auto_reconnect = default_auto_reconnect
        self.reconnect_attempts = {}  # path -> attempt count
        self.max_reconnect_attempts = 5  # Maximum reconnection attempts
        self.reconnect_delay = 2.0  # Delay between reconnection attempts (seconds)
        self.device_auto_reconnect = {}  # path -> bool or None (None = use global default)
        self.device_max_reconnect_attempts = {}  # path -> int or None
        self.device_reconnect_delay = {}  # path -> float or None
        self._input_watcher_fd = None  # inotify fd for /dev/input
        self._input_watcher_thread = None  # thread reading the inotify fd

    def set_auto_reconnect(self, enabled: bool):
        """Enable or disable automatic reconnection for captured evdev inputs.

        Args:
            enabled: True to enable auto-reconnection, False to disable (default)
        """
        self.auto_reconnect = enabled
        if enabled:
            logger.info("Auto-reconnection enabled for captured evdev inputs")
            if any(
                self._get_device_auto_reconnect(p) for p in self.device_tags
            ):
                self._ensure_input_watcher()
        else:
            logger.info("Auto-reconnection disabled for captured evdev inputs")

    def _ensure_evdev_loaded(self):
        """Load evdev modules when first needed."""
        if self._evdev_translator is None:
            try:
                import evdev
                from evdev import ecodes as e

                self._evdev = evdev
                self._e = e
                self._evdev_translator = self.EvdevToJsonTranslator(evdev, e)
            except ImportError:
                raise ImportError(
                    "evdev package is required for input device capture. Install with: pip install evdev"
                )

    def _get_device_auto_reconnect(self, device_path: str) -> bool:
        """Return per-device auto-reconnect setting, falling back to the global default."""
        v = self.device_auto_reconnect.get(device_path)
        return self.auto_reconnect if v is None else v

    def _get_device_max_reconnect_attempts(self, device_path: str) -> int:
        """Return per-device max reconnect attempts, falling back to the global default."""
        v = self.device_max_reconnect_attempts.get(device_path)
        return self.max_reconnect_attempts if v is None else v

    def _get_device_reconnect_delay(self, device_path: str) -> float:
        """Return per-device reconnect delay, falling back to the global default."""
        v = self.device_reconnect_delay.get(device_path)
        return self.reconnect_delay if v is None else v

    def capture_device(
        self,
        identifier: str,
        tag: str,
        device_name: str = None,
        scroll_type: str = "auto",
        auto_reconnect: bool = None,
        max_reconnect_attempts: int = None,
        reconnect_delay: float = None,
    ) -> bool:
        """Capture an input device by name or path, associating it with a tag.

        Args:
            identifier: Device path or device name to capture
            tag: Tag to associate with this device
            device_name: Custom name to use in JSON events (defaults to identifier)
            scroll_type: Scroll event handling mode: "smooth", "non-smooth", or "auto" (default)
                        - "smooth": Only send smooth scroll events, filter out non-smooth
                        - "non-smooth": Only send non-smooth scroll events, filter out smooth
                        - "auto": Auto-detect (assume non-smooth until first smooth scroll seen)
            auto_reconnect: Override global auto-reconnect setting for this device (None = use global)
            max_reconnect_attempts: Override global max reconnect attempts for this device (None = use global)
            reconnect_delay: Override global reconnect delay for this device (None = use global)
        """
        self._ensure_evdev_loaded()

        try:
            device, device_path = self._resolve_identifier(identifier)

            if not device:
                return False

            # Check if this is one of our virtual devices
            if "mooncrater-input" in device.name:
                logger.error(f"Cannot capture virtual device '{device.name}'")
                return False

            device.grab()
            self.captured_devices[device_path] = device
            self.device_tags[device_path] = tag
            self.device_identifiers[device_path] = identifier
            self.device_names[device_path] = device_name or identifier
            self.device_scroll_types[device_path] = scroll_type
            self.device_detected_smooth[device_path] = False
            self.device_auto_reconnect[device_path] = auto_reconnect
            self.device_max_reconnect_attempts[device_path] = max_reconnect_attempts
            self.device_reconnect_delay[device_path] = reconnect_delay
            self._start_device_monitor(device, device_path)
            if self._get_device_auto_reconnect(device_path):
                self._ensure_input_watcher()
            logger.info(
                f"Captured device: {device.name} ({device_path}) with tag '{tag}', device name '{self.device_names[device_path]}', and scroll type '{scroll_type}'"
            )
            return True

        except (OSError, PermissionError) as e:
            logger.error(f"Failed to capture device '{identifier}': {e}")
            return False

    def _resolve_identifier(self, identifier: str):
        """Resolve a user-supplied identifier (device path or device name) to
        an open InputDevice plus its current /dev/input path.

        Returns (device, path) on success, (None, None) if the identifier cannot
        be matched to any currently present device.
        """
        if os.path.exists(identifier):
            try:
                return self._evdev.InputDevice(identifier), identifier
            except (OSError, PermissionError):
                return None, None

        try:
            paths = self._evdev.list_devices()
        except (OSError, PermissionError):
            return None, None

        for path in paths:
            try:
                candidate = self._evdev.InputDevice(path)
            except (OSError, PermissionError):
                continue
            if candidate.name == identifier:
                return candidate, path
            try:
                candidate.close()
            except Exception:
                pass
        return None, None

    def release_device(self, identifier: str) -> bool:
        """Release a captured device."""
        device_path = None

        # Find the device path
        if identifier in self.captured_devices:
            device_path = identifier
        else:
            for path, device in self.captured_devices.items():
                if device.name == identifier:
                    device_path = path
                    break

        if device_path and device_path in self.captured_devices:
            try:
                self.captured_devices[device_path].ungrab()
                del self.captured_devices[device_path]
                if device_path in self.device_identifiers:
                    del self.device_identifiers[device_path]
                if device_path in self.device_names:
                    del self.device_names[device_path]
                if device_path in self.device_scroll_types:
                    del self.device_scroll_types[device_path]
                if device_path in self.device_detected_smooth:
                    del self.device_detected_smooth[device_path]
                if device_path in self.device_auto_reconnect:
                    del self.device_auto_reconnect[device_path]
                if device_path in self.device_max_reconnect_attempts:
                    del self.device_max_reconnect_attempts[device_path]
                if device_path in self.device_reconnect_delay:
                    del self.device_reconnect_delay[device_path]
                logger.info(f"Released device: {device_path}")
                return True
            except OSError as e:
                logger.error(f"Failed to release device '{device_path}': {e}")
                return False

        return False

    def release_devices_by_tag(self, tag: str) -> bool:
        """Release all captured devices associated with a tag."""
        devices_to_release = []

        # Find all devices with this tag
        for device_path, device_tag in self.device_tags.items():
            if device_tag == tag:
                devices_to_release.append(device_path)

        if not devices_to_release:
            logger.warning(f"No devices found with tag '{tag}'")
            return False

        # Release all devices with this tag
        success = True
        for device_path in devices_to_release:
            try:
                if device_path in self.captured_devices:
                    self.captured_devices[device_path].ungrab()
                    del self.captured_devices[device_path]
                if device_path in self.device_tags:
                    del self.device_tags[device_path]
                if device_path in self.device_identifiers:
                    del self.device_identifiers[device_path]
                if device_path in self.device_names:
                    del self.device_names[device_path]
                if device_path in self.device_scroll_types:
                    del self.device_scroll_types[device_path]
                if device_path in self.device_detected_smooth:
                    del self.device_detected_smooth[device_path]
                if device_path in self.device_auto_reconnect:
                    del self.device_auto_reconnect[device_path]
                if device_path in self.device_max_reconnect_attempts:
                    del self.device_max_reconnect_attempts[device_path]
                if device_path in self.device_reconnect_delay:
                    del self.device_reconnect_delay[device_path]
                logger.info(f"Released device: {device_path} (tag: {tag})")
            except OSError as e:
                logger.error(f"Failed to release device '{device_path}': {e}")
                success = False

        return success

    def _start_device_monitor(self, device, device_path: str):
        """Start monitoring a captured device in a separate thread."""

        def monitor():
            try:
                for event in device.read_loop():
                    # Get the input tag and device name for this device
                    input_tag = self.device_tags.get(device_path, "unknown")
                    device_name = self.device_names.get(device_path, device_path)

                    # Translate evdev event to JSON event
                    json_event = self._evdev_translator.translate(
                        device, event, device_name, input_tag
                    )
                    if json_event and self.event_callback:
                        # Apply scroll type filtering
                        if self._should_filter_scroll_event(device_path, json_event):
                            continue
                        self.event_callback(device_path, json_event)
            except OSError:
                # Device disconnected
                logger.warning(f"Device disconnected: {device_path}")

                # Clean up the disconnected device
                if device_path in self.captured_devices:
                    del self.captured_devices[device_path]

                # Try to reconnect if auto-reconnection is enabled
                if self._get_device_auto_reconnect(device_path):
                    self._attempt_reconnect(device_path)

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        self.device_monitors.append(thread)

    def _attempt_reconnect(self, device_path: str):
        """Attempt to reconnect to a disconnected device.

        Re-resolves the device from the originally-configured identifier on
        every attempt, so devices configured by name are found at whatever
        /dev/input node the kernel assigned after replug, not only at the
        path they first happened to occupy.
        """
        if device_path not in self.device_tags:
            return  # Device was not properly tagged

        tag = self.device_tags[device_path]
        identifier = self.device_identifiers.get(device_path, device_path)

        # Initialize reconnect attempts counter if needed
        if device_path not in self.reconnect_attempts:
            self.reconnect_attempts[device_path] = 0

        def reconnect_worker():
            current_path = device_path
            while (self._get_device_auto_reconnect(current_path) and
                   self.reconnect_attempts.get(current_path, 0) < self._get_device_max_reconnect_attempts(current_path)):

                self.reconnect_attempts[current_path] += 1
                logger.info(f"Attempting to reconnect '{identifier}' (attempt {self.reconnect_attempts[current_path]}/{self._get_device_max_reconnect_attempts(current_path)})")

                # Wait before attempting reconnection
                time.sleep(self._get_device_reconnect_delay(current_path))

                new_device, new_path = self._resolve_identifier(identifier)
                if new_device is None:
                    continue

                # Check if this is one of our virtual devices
                if "mooncrater-input" in new_device.name:
                    logger.error(f"Cannot reconnect to virtual device '{new_device.name}'")
                    break

                try:
                    new_device.grab()
                except (OSError, PermissionError) as e:
                    logger.debug(f"Failed to grab reconnected device '{identifier}' at '{new_path}': {e}")
                    continue

                # If the device came back at a different /dev/input path,
                # migrate all per-device state keyed on the old path.
                if new_path != current_path:
                    self._rekey_device(current_path, new_path)
                    current_path = new_path

                self.captured_devices[current_path] = new_device
                self._start_device_monitor(new_device, current_path)

                # Reset reconnect attempts on successful reconnection
                self.reconnect_attempts[current_path] = 0

                logger.info(f"Successfully reconnected '{identifier}' as {new_device.name} ({current_path}) with tag '{tag}'")
                return

            # Max attempts reached or auto-reconnect disabled
            if current_path in self.reconnect_attempts:
                if self.reconnect_attempts[current_path] >= self._get_device_max_reconnect_attempts(current_path):
                    logger.error(f"Max reconnection attempts reached for '{identifier}'")
                del self.reconnect_attempts[current_path]

        # Start reconnection in a separate thread
        reconnect_thread = threading.Thread(target=reconnect_worker, daemon=True)
        reconnect_thread.start()

    def _rekey_device(self, old_path: str, new_path: str):
        """Move all per-device state from old_path to new_path.

        Used when a reconnecting device is found at a different /dev/input
        node than the one it previously occupied.
        """
        if old_path == new_path:
            return
        for d in (
            self.captured_devices,
            self.device_tags,
            self.device_identifiers,
            self.device_names,
            self.device_scroll_types,
            self.device_detected_smooth,
            self.device_auto_reconnect,
            self.device_max_reconnect_attempts,
            self.device_reconnect_delay,
            self.reconnect_attempts,
        ):
            if old_path in d:
                d[new_path] = d.pop(old_path)

    def _ensure_input_watcher(self):
        """Start an inotify watcher on /dev/input to retrigger reconnect attempts.

        The watcher runs once per EvdevInputCapture instance and fires
        `_trigger_reconnect_for_disconnected` whenever a new `/dev/input/event*`
        node appears, giving disconnected devices a fresh chance to reconnect
        after a user unplug/replug even if the initial retry burst already
        exhausted.
        """
        if self._input_watcher_thread is not None:
            return

        # Constants from <sys/inotify.h>; stable Linux ABI.
        IN_NONBLOCK = 0o4000
        IN_CLOEXEC = 0o2000000
        IN_CREATE = 0x00000100
        IN_MOVED_TO = 0x00000080

        try:
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
        except OSError as e:
            logger.warning(f"inotify watcher unavailable (libc load failed): {e}")
            return

        libc.inotify_init1.argtypes = [ctypes.c_int]
        libc.inotify_init1.restype = ctypes.c_int
        libc.inotify_add_watch.argtypes = [
            ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32
        ]
        libc.inotify_add_watch.restype = ctypes.c_int

        fd = libc.inotify_init1(IN_NONBLOCK | IN_CLOEXEC)
        if fd < 0:
            err = ctypes.get_errno()
            logger.warning(f"inotify_init1 failed (errno={err}); auto-reconnect will not react to new USB events")
            return

        wd = libc.inotify_add_watch(fd, b"/dev/input", IN_CREATE | IN_MOVED_TO)
        if wd < 0:
            err = ctypes.get_errno()
            logger.warning(f"inotify_add_watch on /dev/input failed (errno={err}); auto-reconnect will not react to new USB events")
            try:
                os.close(fd)
            except OSError:
                pass
            return

        self._input_watcher_fd = fd
        self._input_watcher_thread = threading.Thread(
            target=self._input_watcher_worker,
            args=(fd,),
            daemon=True,
            name="evdev-input-inotify",
        )
        self._input_watcher_thread.start()
        logger.info("Started /dev/input inotify watcher for reconnection retries")

    def _input_watcher_worker(self, fd: int):
        """Read inotify events from `fd` and retrigger reconnects on new event* nodes."""
        header_fmt = "iIII"  # wd, mask, cookie, len
        header_size = struct.calcsize(header_fmt)
        try:
            while self._input_watcher_fd == fd:
                try:
                    r, _, _ = select.select([fd], [], [], 1.0)
                except (OSError, ValueError):
                    return
                if not r:
                    continue
                try:
                    data = os.read(fd, 4096)
                except BlockingIOError:
                    continue
                except OSError:
                    return
                if not data:
                    continue
                pos = 0
                relevant = False
                while pos + header_size <= len(data):
                    _wd, _mask, _cookie, nlen = struct.unpack_from(
                        header_fmt, data, pos
                    )
                    pos += header_size
                    name = data[pos:pos + nlen].rstrip(b"\x00").decode(
                        "utf-8", errors="replace"
                    )
                    pos += nlen
                    if name.startswith("event"):
                        relevant = True
                if relevant:
                    self._trigger_reconnect_for_disconnected()
        finally:
            try:
                os.close(fd)
            except OSError:
                pass

    def _trigger_reconnect_for_disconnected(self):
        """Kick off a fresh reconnect attempt for every tagged-but-disconnected device."""
        for device_path in list(self.device_tags.keys()):
            if device_path in self.captured_devices:
                continue
            if device_path in self.reconnect_attempts:
                continue
            if not self._get_device_auto_reconnect(device_path):
                continue
            logger.info(
                f"New /dev/input node detected; retrying reconnect for '{device_path}'"
            )
            self._attempt_reconnect(device_path)

    def _should_filter_scroll_event(self, device_path: str, json_event: dict) -> bool:
        """Determine if a scroll event should be filtered based on device scroll type configuration.

        Args:
            device_path: Path to the device
            json_event: The JSON event to potentially filter

        Returns:
            True if the event should be filtered (not sent), False if it should be sent
        """
        # Only filter scroll events
        event_type = json_event.get("type")
        if event_type not in ["scroll", "smoothScroll"]:
            return False

        scroll_type = self.device_scroll_types.get(device_path, "auto")

        # For smooth scroll events, update auto-detect tracker
        if event_type == "smoothScroll" and scroll_type == "auto":
            if not self.device_detected_smooth.get(device_path, False):
                self.device_detected_smooth[device_path] = True
                logger.info(f"Device {device_path} detected as smooth scroll capable")

        # Apply filtering based on scroll type
        if scroll_type == "smooth":
            # Only allow smooth scroll events
            return event_type == "scroll"
        elif scroll_type == "non-smooth":
            # Only allow non-smooth scroll events
            return event_type == "smoothScroll"
        elif scroll_type == "auto":
            # Auto-detect mode: if we've seen smooth scroll, filter out non-smooth
            if self.device_detected_smooth.get(device_path, False):
                return event_type == "scroll"
            else:
                # Haven't seen smooth scroll yet, filter out smooth scroll events
                return event_type == "smoothScroll"

        return False

    def set_led(self, tag: str, led_name: str, value: bool) -> bool:
        """Set LED state on captured devices with the specified tag.

        Args:
            tag: Tag of captured devices to set LED on
            led_name: LED name (e.g., "capslock", "numlock", "scrolllock")
            value: True to turn on, False to turn off

        Returns:
            True if LED was set on at least one device, False otherwise
        """
        self._ensure_evdev_loaded()

        # Map friendly LED names to evdev LED codes
        led_map = {
            "capslock": self._e.LED_CAPSL,
            "numlock": self._e.LED_NUML,
            "scrolllock": self._e.LED_SCROLLL,
            "compose": self._e.LED_COMPOSE,
            "kana": self._e.LED_KANA,
            "sleep": self._e.LED_SLEEP,
            "suspend": self._e.LED_SUSPEND,
            "mute": self._e.LED_MUTE,
            "misc": self._e.LED_MISC,
            "mail": self._e.LED_MAIL,
            "charging": self._e.LED_CHARGING,
        }

        led_code = led_map.get(led_name.lower())
        if led_code is None:
            logger.warning(f"Unknown LED name: {led_name}")
            return False

        led_value = 1 if value else 0
        success = False

        # Set LED on all devices with the specified tag
        for device_path, device_tag in self.device_tags.items():
            if device_tag == tag:
                device = self.captured_devices.get(device_path)
                if device:
                    try:
                        device.set_led(led_code, led_value)
                        logger.debug(f"Set LED {led_name} to {value} on device {device_path}")
                        success = True
                    except (OSError, AttributeError) as e:
                        # Device doesn't support this LED or there's a permission issue
                        logger.debug(f"Could not set LED {led_name} on device {device_path}: {e}")

        return success

    def set_led_all_devices(self, led_name: str, value: bool) -> int:
        """Set LED state on all captured devices.

        Args:
            led_name: LED name (e.g., "capslock", "numlock", "scrolllock")
            value: True to turn on, False to turn off

        Returns:
            Number of devices that successfully set the LED
        """
        self._ensure_evdev_loaded()

        # Map friendly LED names to evdev LED codes
        led_map = {
            "capslock": self._e.LED_CAPSL,
            "numlock": self._e.LED_NUML,
            "scrolllock": self._e.LED_SCROLLL,
            "compose": self._e.LED_COMPOSE,
            "kana": self._e.LED_KANA,
            "sleep": self._e.LED_SLEEP,
            "suspend": self._e.LED_SUSPEND,
            "mute": self._e.LED_MUTE,
            "misc": self._e.LED_MISC,
            "mail": self._e.LED_MAIL,
            "charging": self._e.LED_CHARGING,
        }

        led_code = led_map.get(led_name.lower())
        if led_code is None:
            logger.warning(f"Unknown LED name: {led_name}")
            return 0

        led_value = 1 if value else 0
        success_count = 0

        # Set LED on all captured devices
        for device_path, device in self.captured_devices.items():
            try:
                device.set_led(led_code, led_value)
                logger.debug(f"Set LED {led_name} to {value} on device {device_path}")
                success_count += 1
            except (OSError, AttributeError) as e:
                # Device doesn't support this LED or there's a permission issue
                logger.debug(f"Could not set LED {led_name} on device {device_path}: {e}")

        return success_count

    def close(self):
        """Clean up all captured devices."""
        for device in self.captured_devices.values():
            try:
                device.ungrab()
            except OSError:
                pass

        self.captured_devices.clear()
        self.device_tags.clear()
        self.device_identifiers.clear()
        self.device_names.clear()
        self.device_scroll_types.clear()
        self.device_detected_smooth.clear()
        self.device_auto_reconnect.clear()
        self.device_max_reconnect_attempts.clear()
        self.device_reconnect_delay.clear()
        self.device_monitors.clear()

        fd = self._input_watcher_fd
        self._input_watcher_fd = None
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        self._input_watcher_thread = None

    class EvdevToJsonTranslator:
        """Translates evdev events to JSON events."""

        def __init__(self, evdev_module, e_module):
            self.evdev = evdev_module
            self.e = e_module

        def translate(
            self, device, event, source_tag: str, input_tag: str
        ) -> Optional[dict]:
            """Translate an evdev event to a JsonEvent."""

            # Get timestamp in seconds from epoch as a floating point number
            timestamp = time.time()

            # Skip sync events for now - they'll be handled by the virtual device layer
            if event.type == self.e.EV_SYN:
                return None

            # Key events
            if event.type == self.e.EV_KEY:
                # Determine if this is a keyboard key or mouse button
                if event.code >= self.e.KEY_ESC and event.code <= self.e.KEY_MICMUTE:
                    category = "keyboard"
                    if event.value == 1:
                        event_type = "keyDown"
                    elif event.value == 0:
                        event_type = "keyUp"
                    else:
                        event_type = "keyRepeat"

                    # Get key name for easier processing
                    try:
                        key_name = self.evdev.ecodes.KEY[event.code]
                        key_char = self._scancode_to_char(event.code)
                    except KeyError:
                        key_name = f"KEY_{event.code}"
                        key_char = None

                    return {
                        "category": category,
                        "type": event_type,
                        "scancode": event.code,
                        "keyName": key_name,
                        "keyChar": key_char,
                        "inputTag": input_tag,
                        "inputKind": "capturedDevice",
                        "device": source_tag,
                        "evdev-unix-seconds": timestamp,
                        "originalEvdevEvent": (event.type, event.code, event.value),
                    }

                # Mouse buttons
                elif event.code in [
                    self.e.BTN_LEFT,
                    self.e.BTN_RIGHT,
                    self.e.BTN_MIDDLE,
                    self.e.BTN_SIDE,
                    self.e.BTN_EXTRA,
                    self.e.BTN_BACK,
                    self.e.BTN_FORWARD,
                ]:
                    category = "mouse"
                    event_type = "mouseDown" if event.value == 1 else "mouseUp"
                    button_name = {
                        self.e.BTN_LEFT: "left",
                        self.e.BTN_RIGHT: "right",
                        self.e.BTN_MIDDLE: "middle",
                        self.e.BTN_SIDE: "back",  # Mouse button 4
                        self.e.BTN_EXTRA: "forward",  # Mouse button 5
                        self.e.BTN_BACK: "back",  # Alternative mouse button 4
                        self.e.BTN_FORWARD: "forward",  # Alternative mouse button 5
                    }.get(event.code, "unknown")

                    return {
                        "category": category,
                        "type": event_type,
                        "button": button_name,
                        "scancode": event.code,
                        "inputTag": input_tag,
                        "inputKind": "capturedDevice",
                        "device": source_tag,
                        "evdev-unix-seconds": timestamp,
                        "originalEvdevEvent": (event.type, event.code, event.value),
                    }

                # Touch events
                elif event.code == self.e.BTN_TOUCH:
                    category = "touchpad"
                    event_type = "touchDown" if event.value == 1 else "touchUp"

                    return {
                        "category": category,
                        "type": event_type,
                        "scancode": event.code,
                        "inputTag": input_tag,
                        "inputKind": "capturedDevice",
                        "device": source_tag,
                        "evdev-unix-seconds": timestamp,
                        "originalEvdevEvent": (event.type, event.code, event.value),
                    }

            # Relative movement events
            elif event.type == self.e.EV_REL:
                if event.code in [self.e.REL_X, self.e.REL_Y]:
                    category = "mouse"  # Could be touchpad, but default to mouse
                    event_type = "mouseRel"

                    # Always use deltaX/deltaY format, set unused axis to 0
                    delta_x = event.value if event.code == self.e.REL_X else 0
                    delta_y = event.value if event.code == self.e.REL_Y else 0

                    return {
                        "category": category,
                        "type": event_type,
                        "deltaX": delta_x,
                        "deltaY": delta_y,
                        "inputTag": input_tag,
                        "inputKind": "capturedDevice",
                        "device": source_tag,
                        "evdev-unix-seconds": timestamp,
                        "originalEvdevEvent": (event.type, event.code, event.value),
                    }

                elif event.code in [self.e.REL_WHEEL, self.e.REL_HWHEEL]:
                    category = "mouse"
                    event_type = "scroll"

                    # Always use deltaX/deltaY format, set unused axis to 0
                    delta_x = event.value if event.code == self.e.REL_HWHEEL else 0
                    delta_y = event.value if event.code == self.e.REL_WHEEL else 0

                    return {
                        "category": category,
                        "type": event_type,
                        "deltaX": delta_x,
                        "deltaY": delta_y,
                        "inputTag": input_tag,
                        "inputKind": "capturedDevice",
                        "device": source_tag,
                        "evdev-unix-seconds": timestamp,
                        "originalEvdevEvent": (event.type, event.code, event.value),
                    }

                # High-resolution smooth scroll events
                elif event.code in [self.e.REL_WHEEL_HI_RES, self.e.REL_HWHEEL_HI_RES]:
                    category = "mouse"
                    event_type = "smoothScroll"

                    # Convert raw value to scroll units (120 evdev units = 1.0 scroll unit)
                    scroll_delta = event.value / 120.0
                    delta_x = (
                        scroll_delta if event.code == self.e.REL_HWHEEL_HI_RES else 0.0
                    )
                    delta_y = (
                        scroll_delta if event.code == self.e.REL_WHEEL_HI_RES else 0.0
                    )

                    # Also provide raw values
                    raw_delta_x = (
                        event.value if event.code == self.e.REL_HWHEEL_HI_RES else 0
                    )
                    raw_delta_y = (
                        event.value if event.code == self.e.REL_WHEEL_HI_RES else 0
                    )

                    return {
                        "category": category,
                        "type": event_type,
                        "deltaX": delta_x,
                        "deltaY": delta_y,
                        "rawDeltaX": raw_delta_x,
                        "rawDeltaY": raw_delta_y,
                        "inputTag": input_tag,
                        "inputKind": "capturedDevice",
                        "device": source_tag,
                        "evdev-unix-seconds": timestamp,
                        "originalEvdevEvent": (event.type, event.code, event.value),
                    }

            # Absolute positioning events
            elif event.type == self.e.EV_ABS:
                category = "touchpad"
                event_type = "touchpadAbs"

                axis_name = {
                    self.e.ABS_X: "x",
                    self.e.ABS_Y: "y",
                    self.e.ABS_PRESSURE: "pressure",
                }.get(event.code, f"abs_{event.code}")

                return {
                    "category": category,
                    "type": event_type,
                    "axis": axis_name,
                    "value": event.value,
                    "inputTag": input_tag,
                    "inputKind": "capturedDevice",
                    "device": source_tag,
                    "originalEvdevEvent": (event.type, event.code, event.value),
                }

            # Unknown event type
            return {
                "category": "unknown",
                "type": "raw",
                "evdev_type": event.type,
                "evdev_code": event.code,
                "evdev_value": event.value,
                "inputTag": input_tag,
                "inputKind": "capturedDevice",
                "device": source_tag,
                "originalEvdevEvent": (event.type, event.code, event.value),
            }

        def _scancode_to_char(self, scancode: int) -> Optional[str]:
            """Convert scancode to character (complete QWERTY mapping)."""
            qwerty_map = {
                # Letters
                self.e.KEY_A: "a",
                self.e.KEY_B: "b",
                self.e.KEY_C: "c",
                self.e.KEY_D: "d",
                self.e.KEY_E: "e",
                self.e.KEY_F: "f",
                self.e.KEY_G: "g",
                self.e.KEY_H: "h",
                self.e.KEY_I: "i",
                self.e.KEY_J: "j",
                self.e.KEY_K: "k",
                self.e.KEY_L: "l",
                self.e.KEY_M: "m",
                self.e.KEY_N: "n",
                self.e.KEY_O: "o",
                self.e.KEY_P: "p",
                self.e.KEY_Q: "q",
                self.e.KEY_R: "r",
                self.e.KEY_S: "s",
                self.e.KEY_T: "t",
                self.e.KEY_U: "u",
                self.e.KEY_V: "v",
                self.e.KEY_W: "w",
                self.e.KEY_X: "x",
                self.e.KEY_Y: "y",
                self.e.KEY_Z: "z",
                # Numbers
                self.e.KEY_0: "0",
                self.e.KEY_1: "1",
                self.e.KEY_2: "2",
                self.e.KEY_3: "3",
                self.e.KEY_4: "4",
                self.e.KEY_5: "5",
                self.e.KEY_6: "6",
                self.e.KEY_7: "7",
                self.e.KEY_8: "8",
                self.e.KEY_9: "9",
                # Punctuation and symbols (unshifted)
                self.e.KEY_GRAVE: "`",
                self.e.KEY_MINUS: "-",
                self.e.KEY_EQUAL: "=",
                self.e.KEY_LEFTBRACE: "[",
                self.e.KEY_RIGHTBRACE: "]",
                self.e.KEY_BACKSLASH: "\\",
                self.e.KEY_SEMICOLON: ";",
                self.e.KEY_APOSTROPHE: "'",
                self.e.KEY_COMMA: ",",
                self.e.KEY_DOT: ".",
                self.e.KEY_SLASH: "/",
                # Whitespace
                self.e.KEY_SPACE: " ",
                self.e.KEY_TAB: "\t",
                self.e.KEY_ENTER: "\n",
                # Numpad numbers
                self.e.KEY_KP0: "0",
                self.e.KEY_KP1: "1",
                self.e.KEY_KP2: "2",
                self.e.KEY_KP3: "3",
                self.e.KEY_KP4: "4",
                self.e.KEY_KP5: "5",
                self.e.KEY_KP6: "6",
                self.e.KEY_KP7: "7",
                self.e.KEY_KP8: "8",
                self.e.KEY_KP9: "9",
                # Numpad symbols
                self.e.KEY_KPDOT: ".",
                self.e.KEY_KPSLASH: "/",
                self.e.KEY_KPASTERISK: "*",
                self.e.KEY_KPMINUS: "-",
                self.e.KEY_KPPLUS: "+",
                self.e.KEY_KPENTER: "\n",
                self.e.KEY_KPEQUAL: "=",
            }
            return qwerty_map.get(scancode)


def register(mooncrater_input):
    """Register evdev_input types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # Constructor wrapper for evdev_capture input
    def create_evdev_capture(mooncrater_input_instance, tag, device_identifiers, **kwargs):
        # Create or get the shared EvdevInputCapture instance
        if "captured_devices" not in mooncrater_input_instance.backend_storage:
            mooncrater_input_instance.backend_storage["captured_devices"] = EvdevInputCapture(
                mooncrater_input_instance._create_input_handler("capturedDevice")
            )

        captured_devices = mooncrater_input_instance.backend_storage["captured_devices"]
        captured_any = False

        # Handle both list and dictionary formats
        if isinstance(device_identifiers, dict):
            for device_name, device_config in device_identifiers.items():
                # Support three formats:
                # 1. {"name": "/path/to/device"} - simple path
                # 2. {"name": True} - use name as path
                # 3. {"name": {"device": "/path", "scrollType": "auto"}} - full config
                if isinstance(device_config, dict):
                    # Full configuration object
                    identifier = device_config.get("device", device_name)
                    custom_name = device_name
                    scroll_type = device_config.get("scrollType", "auto")
                    per_device_auto_reconnect = device_config.get("autoReconnect", None)
                    per_device_max_attempts = device_config.get("maxReconnectAttempts", None)
                    per_device_reconnect_delay = device_config.get("reconnectDelay", None)
                elif device_config is True:
                    identifier = device_name
                    custom_name = device_name
                    scroll_type = "auto"
                    per_device_auto_reconnect = None
                    per_device_max_attempts = None
                    per_device_reconnect_delay = None
                else:
                    identifier = device_config
                    custom_name = device_name
                    scroll_type = "auto"
                    per_device_auto_reconnect = None
                    per_device_max_attempts = None
                    per_device_reconnect_delay = None

                if captured_devices.capture_device(
                    identifier, tag, custom_name, scroll_type,
                    per_device_auto_reconnect, per_device_max_attempts, per_device_reconnect_delay
                ):
                    captured_any = True
        else:
            for identifier in device_identifiers:
                if captured_devices.capture_device(identifier, tag):
                    captured_any = True

        if captured_any:
            return captured_devices
        else:
            raise RuntimeError(f"Failed to capture any devices for tag '{tag}'")

    # Destructor for evdev_capture input
    def destroy_evdev_capture(mooncrater_input_instance, tag, instance):
        if "captured_devices" in mooncrater_input_instance.backend_storage:
            return mooncrater_input_instance.backend_storage["captured_devices"].release_devices_by_tag(tag)
        return False

    # Register the evdev_capture input type
    mooncrater_input.register_input_type(
        type_name="evdev_capture",
        constructor=lambda tag, **kwargs: create_evdev_capture(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_evdev_capture(mooncrater_input, tag, instance),
        metadata={
            "description": "Capture evdev input devices",
            "module": "evdev_input"
        }
    )
