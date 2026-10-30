import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

ecodes = pytest.importorskip("evdev").ecodes

from mooncrater_input.evdev_output import EvdevOutputVirtualDevice


def summed(translator, events, code):
    total = 0
    for event in events:
        for _type, event_code, value in translator.translate(event):
            if event_code == code:
                total += value
    return total


@pytest.mark.parametrize("sign", [1, -1])
def test_small_float_smooth_scrolls_add_up_to_whole_notches(sign):
    # Eg. keyboard scrolling at a slow speed: many sub-notch steps per notch.
    translator = EvdevOutputVirtualDevice.JsonToEvdevTranslator(ecodes)
    events = [
        {"category": "mouse", "type": "smoothScroll", "deltaX": 0.0, "deltaY": sign * 0.04}
        for _ in range(50)
    ]
    hi_res = summed(translator, events, ecodes.REL_WHEEL_HI_RES)
    translator = EvdevOutputVirtualDevice.JsonToEvdevTranslator(ecodes)
    notches = summed(translator, events, ecodes.REL_WHEEL)
    assert hi_res == sign * 240
    assert notches == sign * 2
