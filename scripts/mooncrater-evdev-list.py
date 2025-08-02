#!/usr/bin/env python3
import evdev

[print(f"{p}: {evdev.InputDevice(p).name}") for p in evdev.list_devices()]
