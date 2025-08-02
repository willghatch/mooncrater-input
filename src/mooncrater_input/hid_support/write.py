"""
Low-level HID writing functionality.
Based on zero-hid's write module but simplified for our needs.
"""

import logging
import multiprocessing
import dataclasses
from typing import Any, List, Union
from io import IOBase

logger = logging.getLogger(__name__)


class HIDWriteError(Exception):
    """Exception raised when HID write operations fail."""

    pass


@dataclasses.dataclass
class ProcessResult:
    """Result of a process execution."""

    return_value: Any = None
    exception: Exception = None

    def was_successful(self) -> bool:
        return self.exception is None


class ProcessWithResult(multiprocessing.Process):
    """A multiprocessing.Process that tracks results."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_conn, self.child_conn = multiprocessing.Pipe()

    def run(self):
        """Method to be run in sub-process."""
        result = ProcessResult()
        try:
            if self._target:
                result.return_value = self._target(*self._args, **self._kwargs)
        except Exception as e:
            result.exception = e
            raise
        finally:
            self.child_conn.send(result)

    def result(self):
        """Get the result from the child process."""
        return self.parent_conn.recv() if self.parent_conn.poll() else None


def _write_to_hid_interface_immediately(hid_dev: Union[str, IOBase], buffer: List[int]):
    """Write buffer to HID interface immediately."""
    try:
        if isinstance(hid_dev, str):
            with open(hid_dev, "ab+") as f:
                f.seek(0)
                f.write(bytearray(buffer))
                f.flush()
        else:
            # Handle different types of mock devices
            if hasattr(hid_dev, "mode") and "b" in hid_dev.mode:
                # Binary mode file-like object
                hid_dev.seek(0)
                hid_dev.write(bytearray(buffer))
                hid_dev.flush()
            else:
                # Text mode file-like object (like StringIO) - write hex representation
                hid_dev.seek(0)
                hex_data = " ".join(f"{b:02x}" for b in buffer)
                hid_dev.write(hex_data + "\n")
                if hasattr(hid_dev, "flush"):
                    hid_dev.flush()
    except (BlockingIOError, OSError) as e:
        logger.error(f"Failed to write to HID interface: {hid_dev}. Error: {e}")
        raise


class HIDWriter:
    """Handles writing to HID interfaces with error handling and timeouts."""

    def __init__(self, timeout: float = 0.5):
        self.timeout = timeout

    def write(self, hid_dev: Union[str, IOBase], buffer: List[int]):
        """Write buffer to HID interface with timeout protection."""
        if logger.getEffectiveLevel() == logging.DEBUG:
            logger.debug(
                "writing to HID interface %s: %s",
                hid_dev,
                " ".join(["0x%02x" % x for x in buffer]),
            )

        # Use multiprocessing to avoid hanging on blocked writes
        write_process = ProcessWithResult(
            target=_write_to_hid_interface_immediately,
            args=(hid_dev, buffer),
            daemon=True,
        )
        write_process.start()
        write_process.join(timeout=self.timeout)

        if write_process.is_alive():
            write_process.kill()
            self._wait_for_process_exit(write_process)

        result = write_process.result()
        if result is None or not result.was_successful():
            raise HIDWriteError(
                f"Failed to write to HID interface: {hid_dev}. "
                f"Is USB cable connected and gadget module installed?"
            )

    def _wait_for_process_exit(self, target_process: ProcessWithResult):
        """Wait for a process to exit cleanly."""
        max_attempts = 3
        for _ in range(max_attempts):
            target_process.join(timeout=0.1)
            if not target_process.is_alive():
                break
