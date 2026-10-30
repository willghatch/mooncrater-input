import os
import queue
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from mooncrater_input.mooncrater_input_lib import MooncraterInput
from mooncrater_input import periodic_timer


def drain(q):
    events = []
    while True:
        try:
            item_type, event = q.get_nowait()
        except queue.Empty:
            return events
        assert item_type == "json_event"
        events.append(event)


def wait_for_event(q, timeout=1.0):
    item_type, event = q.get(timeout=timeout)
    assert item_type == "json_event"
    return event


def test_timer_enqueues_tagged_ticks_only_while_started():
    mi = MooncraterInput()
    periodic_timer.register(mi)
    assert mi.create_input("periodic_timer", "ticker", interval=0.005)
    timer = mi.get_input_instance("ticker")
    try:
        # A fresh timer is stopped, so an idle mouse mode costs nothing.
        time.sleep(0.03)
        assert drain(mi.input_queue) == []

        timer.start()
        tick = wait_for_event(mi.input_queue)
        assert tick["category"] == "timer"
        assert tick["type"] == "tick"
        # Ticks are tagged so a layer can recognize its own timer.
        assert tick["inputTag"] == "ticker"
        wait_for_event(mi.input_queue)

        timer.stop()
        time.sleep(0.02)  # let an in-flight tick land
        drain(mi.input_queue)
        time.sleep(0.03)
        assert drain(mi.input_queue) == []

        # It can be restarted after stopping.
        timer.start()
        wait_for_event(mi.input_queue)
    finally:
        assert mi.remove_input("ticker")
    time.sleep(0.02)
    drain(mi.input_queue)
    time.sleep(0.03)
    assert drain(mi.input_queue) == []
