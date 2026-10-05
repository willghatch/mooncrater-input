#!/usr/bin/env python3
"""
Tests that evdev capture and virtual_evdev output survive unusual keys and errors.

The virtual devices use a recording stand-in for evdev.UInput, since /dev/uinput
is usually unavailable in test environments.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

evdev = pytest.importorskip("evdev")
from evdev import ecodes as e

from mooncrater_input.evdev_input import EvdevInputCapture
from mooncrater_input.evdev_output import EvdevOutputVirtualDevice


class RecordingUInput:
    """Stand-in for evdev.UInput that records writes instead of using /dev/uinput."""

    written = []
    fail_next_write = False
    fail_construction = False

    def __init__(self, caps, name=None, version=None):
        if RecordingUInput.fail_construction:
            raise OSError("uinput unavailable")
        self.name = name

    def write(self, event_type, code, value):
        if RecordingUInput.fail_next_write:
            RecordingUInput.fail_next_write = False
            raise OSError("write failed")
        RecordingUInput.written.append((event_type, code, value))

    def syn(self):
        pass

    def close(self):
        pass


@pytest.fixture
def output(monkeypatch):
    RecordingUInput.written = []
    RecordingUInput.fail_next_write = False
    RecordingUInput.fail_construction = False
    monkeypatch.setattr(evdev, "UInput", RecordingUInput)
    device = EvdevOutputVirtualDevice("main", exception_on_error=True)
    yield device
    device.close()


def key_down(key_name, scancode=None):
    event = {"category": "keyboard", "type": "keyDown", "keyName": key_name}
    if scancode is not None:
        event["scancode"] = scancode
    return event


def key_writes():
    return [w for w in RecordingUInput.written if w[0] == e.EV_KEY]


def test_captured_mute_key_has_single_string_key_name():
    translator = EvdevInputCapture.EvdevToJsonTranslator(evdev, e)
    event = evdev.InputEvent(0, 0, e.EV_KEY, e.KEY_MUTE, 1)

    json_event = translator.translate(None, event, "/dev/input/event0", "captures")

    assert json_event["keyName"] == "KEY_MUTE"
    assert set(json_event["keyNames"]) == {"KEY_MUTE", "KEY_MIN_INTERESTING"}


def test_output_accepts_tuple_key_name(output):
    output.send_json_event(key_down(("KEY_MIN_INTERESTING", "KEY_MUTE")))

    assert key_writes() == [(e.EV_KEY, e.KEY_MUTE, 1)]


def test_output_keeps_working_after_untranslatable_event(output):
    # A malformed mouse delta makes translation raise.
    output.send_json_event(
        {"category": "mouse", "type": "mouseRel", "deltaX": "bogus", "deltaY": 0}
    )
    output.send_json_event(key_down("KEY_A"))

    assert key_writes() == [(e.EV_KEY, e.KEY_A, 1)]


def test_output_keeps_working_after_write_error_and_reconnect(output):
    RecordingUInput.fail_next_write = True
    output.send_json_event(key_down("KEY_A"))
    output.send_json_event(key_down("KEY_B"))

    assert (e.EV_KEY, e.KEY_B, 1) in key_writes()


def test_output_retries_reconnect_after_cooldown(output):
    output.reconnect_cooldown_seconds = 0
    RecordingUInput.fail_next_write = True
    output.send_json_event(key_down("KEY_A"))

    # Exhaust reconnection attempts while the virtual devices cannot be created.
    RecordingUInput.fail_construction = True
    for _ in range(output.max_reconnect_attempts + 1):
        output.send_json_event(key_down("KEY_B"))

    RecordingUInput.fail_construction = False
    output.send_json_event(key_down("KEY_C"))

    assert key_writes() == [(e.EV_KEY, e.KEY_C, 1)]
