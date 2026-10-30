"""Periodic timer input: enqueues tick events while started.

A config creates one with ``mi.create_input("periodic_timer", tag,
interval=seconds)`` and gets it back with ``mi.get_input_instance(tag)``.
The timer starts stopped; ``start()`` and ``stop()`` control it.  While
running it enqueues ``{"category": "timer", "type": "tick"}`` events tagged
with its input tag, so they reach the config's event handler on the same
thread as every other input event.
"""

import threading
import time


class PeriodicTimer:
    """Calls ``handler(tag, tick_event)`` every ``interval`` seconds while started."""

    def __init__(self, handler, tag, interval):
        if not interval > 0:
            raise ValueError("interval must be positive")
        self._handler = handler
        self._tag = tag
        self._interval = float(interval)
        self._running = threading.Event()
        self._closed = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name=f"periodic-timer-{tag}", daemon=True
        )
        self._thread.start()

    @property
    def is_running(self):
        return self._running.is_set()

    def start(self):
        self._running.set()

    def stop(self):
        self._running.clear()

    def close(self):
        self._closed.set()
        self._running.set()  # wake the loop so it can exit
        self._thread.join(timeout=1.0)

    def _loop(self):
        while True:
            self._running.wait()
            if self._closed.is_set():
                return
            # Schedule from the start of a run so ticks do not drift, but do
            # not try to catch up after a stall.
            next_time = time.monotonic() + self._interval
            while self._running.is_set() and not self._closed.is_set():
                delay = next_time - time.monotonic()
                if delay > 0:
                    # Wakes early on close; a stop is noticed after the sleep.
                    self._closed.wait(delay)
                if not self._running.is_set() or self._closed.is_set():
                    break
                self._handler(self._tag, {"category": "timer", "type": "tick"})
                next_time = max(next_time + self._interval, time.monotonic())


def register(mooncrater_input):
    """Register the ``periodic_timer`` input type with a MooncraterInput instance."""

    def create_periodic_timer(tag, interval, **kwargs):
        handler = mooncrater_input._create_input_handler("timer", source_tag=tag)
        return PeriodicTimer(handler, tag, interval)

    def destroy_periodic_timer(tag, instance):
        instance.close()
        return True

    mooncrater_input.register_input_type(
        type_name="periodic_timer",
        constructor=create_periodic_timer,
        destructor=destroy_periodic_timer,
        metadata={
            "description": "Enqueues tick events at a fixed interval while started",
            "module": "periodic_timer",
        },
    )
