#!/usr/bin/env python3

import evdev
import sys
import select


def main():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]

    if not devices:
        print("No input devices found", file=sys.stderr)
        return 1

    print(f"Listening to {len(devices)} input devices:", file=sys.stderr)
    for device in devices:
        print(f"  {device.path}: {device.name}", file=sys.stderr)

    device_map = {device.fd: device for device in devices}

    try:
        while True:
            r, w, x = select.select(device_map, [], [])
            for fd in r:
                device = device_map[fd]
                try:
                    for event in device.read():
                        print(f"{device.path} {device.name}: {event}")
                except OSError:
                    # Device was disconnected
                    print(f"Device {device.path} disconnected", file=sys.stderr)
                    del device_map[fd]
                    if not device_map:
                        print("No devices remaining", file=sys.stderr)
                        return 0
    except KeyboardInterrupt:
        print("\nStopping...", file=sys.stderr)
        return 0
    except PermissionError:
        print("Permission denied. Try running with sudo.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
