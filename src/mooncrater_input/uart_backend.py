#!/usr/bin/env python3
"""
UART Backend for Mooncrater Input

This module implements UART communication to a microcontroller
running QMK firmware. It sends keyboard and mouse events over UART half-duplex.

Usage:
    from uart_backend import UARTBackend

    backend = UARTBackend('/dev/serial0', 115200)
    backend.start()

    # Send events
    backend.send_key_down('KEY_A')
    backend.send_mouse_move(10, -5)
    backend.send_string("Hello World!")

    backend.stop()
"""

import serial
import threading
import time
import logging
from typing import List, Dict, Any, Optional
from enum import IntEnum
import queue
import sys
import os

from .hid_support.keycodes import HID_KEY_SCANCODES


# Set up logging
logger = logging.getLogger(__name__)


class UARTCommand(IntEnum):
    """UART protocol command bytes"""

    KEY_DOWN = 0x01
    KEY_UP = 0x02
    KEY_PRESS = 0x03
    MOUSE_MOVE = 0x10
    MOUSE_BUTTON_DOWN = 0x11
    MOUSE_BUTTON_UP = 0x12
    MOUSE_WHEEL = 0x13
    MACRO_ASCII_STRING = 0x31
    MACRO_UNICODE_STRING = 0x32
    UNICODE_CYCLE_MODE = 0x33
    RESET_STATE = 0xFF


class UARTBackend:
    """UART backend for sending events to QMK microcontroller"""

    # USB HID keycode mapping - use complete definitions from hid_support/keycodes.py
    KEY_MAP = HID_KEY_SCANCODES

    # Mouse button mapping
    MOUSE_BUTTON_MAP = {
        "left": 0x01,
        "right": 0x02,
        "middle": 0x04,
        "back": 0x08,
        "forward": 0x10,
    }

    # Maximum bytes per string chunk
    send_string_max_bytes = 62

    def __init__(self, serial_port: str = "/dev/serial0", baud_rate: int = 115200,
                 chunk_delay_qwerty_seconds: float = 0.5, chunk_delay_unicode_seconds: float = 2.0):
        """
        Initialize UART backend.

        Args:
            serial_port: Serial device path (e.g., '/dev/serial0', '/dev/ttyUSB0')
            baud_rate: Communication baud rate (must match microcontroller)
            chunk_delay_qwerty_seconds: Delay in seconds between QWERTY string chunks (default: 0.5s)
            chunk_delay_unicode_seconds: Delay in seconds between Unicode string chunks (default: 2.0s)
        """
        self.serial_port = serial_port
        self.baud_rate = baud_rate
        self.chunk_delay_qwerty_seconds = chunk_delay_qwerty_seconds
        self.chunk_delay_unicode_seconds = chunk_delay_unicode_seconds
        self.serial = None
        self.running = False
        self.tx_queue = queue.Queue()  # Now handles both packets and string operations
        self.tx_thread = None
        self.connection_status = "disconnected"
        self.last_error = None
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        # Fractional accumulation for smooth mouse movement
        self.fractional_x = 0.0
        self.fractional_y = 0.0

    def start(self) -> bool:
        """
        Start the UART backend.

        Returns:
            True if started successfully, False otherwise
        """
        try:
            # Open serial port
            self.serial = serial.Serial(
                port=self.serial_port,
                baudrate=self.baud_rate,
                bytesize=8,
                parity=serial.PARITY_NONE,
                stopbits=1,
                timeout=0.1,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )

            # Start transmission thread
            self.running = True
            self.tx_thread = threading.Thread(
                target=self._tx_thread_worker, daemon=True
            )
            self.tx_thread.start()

            # Send reset command to initialize microcontroller state
            self.reset_state()

            self.connection_status = "connected"
            self.last_error = None
            self.reconnect_attempts = 0

            logger.info(
                f"UART backend started on {self.serial_port} at {self.baud_rate} baud"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start UART backend: {e}")
            self.connection_status = "failed"
            self.last_error = str(e)
            return False

    def stop(self):
        """Stop the UART backend and close serial port."""
        self.running = False
        self.connection_status = "disconnected"

        if self.tx_thread:
            self.tx_thread.join(timeout=1.0)

        if self.serial:
            try:
                self.serial.close()
            except:
                pass
            self.serial = None

        logger.info("UART backend stopped")

    def _tx_thread_worker(self):
        """Worker thread for transmitting packets and handling string operations with delays."""
        while self.running:
            try:
                # Get item from queue (blocking with timeout)
                item = self.tx_queue.get(timeout=0.1)

                if item and self.serial and self.serial.is_open:
                    if isinstance(item, bytes):
                        # Simple packet - send directly
                        self.serial.write(item)
                        self.serial.flush()
                    elif isinstance(item, dict) and item.get('type') == 'string_operation':
                        # String operation - handle chunking with delays in background thread
                        self._handle_string_operation_async(item)
                    elif item:
                        logger.warning(f"Unknown item type in transmission queue: {type(item)}")

                self.tx_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing transmission queue item: {e}")

    def _handle_string_operation_async(self, operation: dict):
        """
        Handle string operations with chunking and delays in the background thread.
        This prevents blocking the main event processing thread.
        """
        try:
            text = operation['text']
            is_qwerty_mode = operation['is_qwerty_mode']

            # Choose encoding and command based on mode
            if is_qwerty_mode:
                encoding = "ascii"
                command = UARTCommand.MACRO_ASCII_STRING
            else:
                encoding = "utf-8"
                command = UARTCommand.MACRO_UNICODE_STRING

            max_bytes = self.send_string_max_bytes
            start_idx = 0

            # Track if we're sending multiple chunks for logging
            total_bytes = text.encode(encoding)
            if len(total_bytes) > max_bytes:
                logger.warning(
                    f"{'QWERTY' if is_qwerty_mode else 'Unicode'} string too long "
                    f"({len(total_bytes)} bytes), sending in chunks"
                )

            chunk_count = 0
            while start_idx < len(text):
                if is_qwerty_mode:
                    # For ASCII strings, we can split by character count since each char = 1 byte
                    end_idx = min(start_idx + max_bytes, len(text))
                    chunk = text[start_idx:end_idx]
                    chunk_bytes = chunk.encode(encoding)
                else:
                    # For Unicode strings, find the largest substring that fits within max_bytes
                    end_idx = start_idx + 1
                    while end_idx <= len(text):
                        chunk = text[start_idx:end_idx]
                        chunk_bytes = chunk.encode(encoding)

                        if len(chunk_bytes) > max_bytes:
                            # Previous substring was the largest that fits
                            end_idx -= 1
                            break

                        if end_idx == len(text):
                            # We've reached the end of the string
                            break

                        end_idx += 1

                    # Safety check for Unicode mode
                    if end_idx <= start_idx:
                        # Single character too large, skip it
                        logger.error(f"Single character too large for packet: {text[start_idx]}")
                        start_idx += 1
                        continue

                    chunk = text[start_idx:end_idx]
                    chunk_bytes = chunk.encode(encoding)

                # Create and send the packet directly (we're already in the transmission thread)
                packet = self._create_packet(command, chunk_bytes)
                self.serial.write(packet)
                self.serial.flush()

                chunk_count += 1
                start_idx = end_idx

                # Add delay between chunks if there are multiple chunks
                # This only blocks the transmission thread, not the main thread
                if len(total_bytes) > max_bytes and start_idx < len(text):
                    delay_seconds = self.chunk_delay_qwerty_seconds if is_qwerty_mode else self.chunk_delay_unicode_seconds
                    time.sleep(delay_seconds)

        except Exception as e:
            logger.error(f"Error handling async string operation: {e}")

    def _create_packet(self, command: int, data: bytes) -> bytes:
        """
        Create a UART protocol packet.

        Args:
            command: Command byte
            data: Data payload

        Returns:
            Complete packet bytes
        """
        if len(data) > self.send_string_max_bytes:
            logger.warning(f"Data too long ({len(data)} bytes), truncating to {self.send_string_max_bytes}")
            data = data[:self.send_string_max_bytes]

        # Calculate checksum (XOR of length + command + data)
        length = len(data)
        checksum = length ^ command
        for byte in data:
            checksum ^= byte
        checksum &= 0xFF

        # Build packet: [START] [LENGTH] [COMMAND] [DATA...] [CHECKSUM]
        packet = bytes([0xAA, length, command]) + data + bytes([checksum])

        return packet

    def _send_packet(self, command: int, data: bytes = b""):
        """
        Queue a packet for transmission.

        Args:
            command: Command byte
            data: Data payload
        """
        packet = self._create_packet(command, data)

        try:
            self.tx_queue.put(packet, timeout=0.1)
        except queue.Full:
            logger.warning("Transmission queue full, dropping packet")

    def is_connected(self) -> bool:
        """Check if UART backend is connected and working."""
        return (self.connection_status == "connected" and
                self.serial is not None and
                self.serial.is_open and
                self.running)

    def get_connection_status(self) -> dict:
        """Get detailed connection status information."""
        return {
            "status": self.connection_status,
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "serial_port": self.serial_port,
            "baud_rate": self.baud_rate,
            "running": self.running
        }

    def _try_reconnect(self) -> bool:
        """Try to reconnect UART backend."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(f"Max reconnection attempts reached for UART backend")
            return False

        self.reconnect_attempts += 1
        logger.info(f"Attempting to reconnect UART backend (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})")

        try:
            # Stop current operation
            self.stop()

            # Try to restart
            return self.start()

        except Exception as e:
            logger.error(f"Failed to reconnect UART backend: {e}")
            self.connection_status = "failed"
            self.last_error = str(e)
            return False

    def _keyname_to_hid(self, keyname: str) -> int:
        """Convert Linux keyname to USB HID keycode."""
        return self.KEY_MAP.get(keyname, 0)

    def _button_to_mask(self, button: str) -> int:
        """Convert mouse button name to bitmask."""
        return self.MOUSE_BUTTON_MAP.get(button, 0)

    def _encode_mouse_delta(self, delta: float) -> tuple[int, int]:
        """
        Encode mouse delta to signed 16-bit little-endian bytes.

        Returns:
            (low_byte, high_byte) tuple
        """
        # Clamp to 16-bit signed range
        delta_int = max(-32768, min(32767, int(delta)))

        # Convert to unsigned for byte encoding
        if delta_int < 0:
            delta_uint = delta_int + 65536
        else:
            delta_uint = delta_int

        low_byte = delta_uint & 0xFF
        high_byte = (delta_uint >> 8) & 0xFF

        return low_byte, high_byte

    def _encode_scroll_delta(self, delta: float) -> int:
        """Encode scroll delta to signed 8-bit integer.  Only sends normal
        scroll events, smooth scroll or high-res scroll not currently supported
        by QMK at time of writing, I think."""

        scroll_int = max(-128, min(127, int(delta)))

        if scroll_int < 0:
            return scroll_int + 256
        else:
            return scroll_int

    # Public API methods

    def send_key_down(self, keyname: str):
        """Send key press down event."""
        keycode = self._keyname_to_hid(keyname)
        if keycode:
            self._send_packet(UARTCommand.KEY_DOWN, bytes([keycode]))
        else:
            logger.warning(f"Unknown key: {keyname}")

    def send_key_up(self, keyname: str):
        """Send key release event."""
        keycode = self._keyname_to_hid(keyname)
        if keycode:
            self._send_packet(UARTCommand.KEY_UP, bytes([keycode]))
        else:
            logger.warning(f"Unknown key: {keyname}")

    def send_key_press(self, keyname: str):
        """Send key tap (press + release) event."""
        keycode = self._keyname_to_hid(keyname)
        if keycode:
            self._send_packet(UARTCommand.KEY_PRESS, bytes([keycode]))
        else:
            logger.warning(f"Unknown key: {keyname}")

    def send_mouse_move(self, delta_x: float, delta_y: float):
        """Send mouse relative movement with fractional accumulation."""
        # Accumulate fractional values
        self.fractional_x += delta_x
        self.fractional_y += delta_y

        # Extract integer parts for sending
        int_x = int(self.fractional_x)
        int_y = int(self.fractional_y)

        # Keep fractional remainders for next time
        self.fractional_x -= int_x
        self.fractional_y -= int_y

        # Send integer movements if non-zero
        if int_x != 0 or int_y != 0:
            x_low, x_high = self._encode_mouse_delta(int_x)
            y_low, y_high = self._encode_mouse_delta(int_y)

            data = bytes([x_low, x_high, y_low, y_high])
            self._send_packet(UARTCommand.MOUSE_MOVE, data)

    def send_mouse_button_down(self, button: str):
        """Send mouse button press."""
        button_mask = self._button_to_mask(button)
        if button_mask:
            self._send_packet(UARTCommand.MOUSE_BUTTON_DOWN, bytes([button_mask]))
        else:
            logger.warning(f"Unknown mouse button: {button}")

    def send_mouse_button_up(self, button: str):
        """Send mouse button release."""
        button_mask = self._button_to_mask(button)
        if button_mask:
            self._send_packet(UARTCommand.MOUSE_BUTTON_UP, bytes([button_mask]))
        else:
            logger.warning(f"Unknown mouse button: {button}")

    def send_mouse_wheel(self, delta_x: float, delta_y: float):
        """Send mouse wheel scroll."""
        x_scroll = self._encode_scroll_delta(delta_x)
        y_scroll = self._encode_scroll_delta(delta_y)
        data = bytes([x_scroll, y_scroll])
        self._send_packet(UARTCommand.MOUSE_WHEEL, data)

    def send_string(self, text: str):
        """
        Send string macro, automatically choosing between QWERTY and Unicode modes.

        This method automatically determines whether to use MACRO_ASCII_STRING or
        MACRO_UNICODE_STRING based on the character content:
        - Uses QWERTY mode (MACRO_ASCII_STRING) if all characters are typeable ASCII
        - Uses Unicode mode (MACRO_UNICODE_STRING) otherwise

        Args:
            text: String to send
        """
        if self._is_typeable_ascii(text):
            self.send_qwerty_string(text)
        else:
            self.send_unicode_string(text)

    def send_qwerty_string(self, text: str):
        """
        Send string using QWERTY/ASCII keyboard characters only.

        Only uses MACRO_ASCII_STRING for characters that can be typed on a typical keyboard.
        This excludes control characters, null bytes, etc.

        Args:
            text: String containing only printable ASCII keyboard characters
        """
        try:
            # Verify all characters are printable ASCII that can be typed on keyboard
            if not self._is_typeable_ascii(text):
                raise ValueError("Text contains non-typeable characters for QWERTY mode")

            self._queue_string_operation(text, is_qwerty_mode=True)
        except (UnicodeEncodeError, ValueError) as e:
            logger.error(f"Failed to encode QWERTY string: {e}")

    def send_unicode_string(self, text: str):
        """
        Send string that may contain Unicode characters.

        Uses MACRO_UNICODE_STRING for any string that contains non-ASCII or
        non-printable characters.

        Args:
            text: String that may contain Unicode characters
        """
        try:
            self._queue_string_operation(text, is_qwerty_mode=False)
        except UnicodeEncodeError as e:
            logger.error(f"Failed to encode Unicode string: {e}")

    def _queue_string_operation(self, text: str, is_qwerty_mode: bool):
        """
        Queue a string operation for asynchronous processing by the transmission thread.

        Args:
            text: The string to send
            is_qwerty_mode: True for ASCII/QWERTY mode, False for Unicode mode
        """
        operation = {
            'type': 'string_operation',
            'text': text,
            'is_qwerty_mode': is_qwerty_mode
        }

        try:
            self.tx_queue.put(operation, timeout=0.1)
        except queue.Full:
            logger.warning("Transmission queue full, dropping string operation")

    def _is_typeable_ascii(self, text: str) -> bool:
        """
        Check if text contains only ASCII characters that can be typed on a typical keyboard.

        This includes:
        - Space (0x20) through tilde (0x7E)
        - Tab (0x09) and newline (0x0A)

        This excludes control characters like null bytes, BEL, etc.

        Args:
            text: Text to check

        Returns:
            True if all characters are typeable ASCII
        """
        for char in text:
            code = ord(char)
            # Allow printable ASCII (space through tilde), tab, and newline
            if not ((0x20 <= code <= 0x7E) or code == 0x09 or code == 0x0A):
                return False
        return True

    def send_unicode_cycle_mode(self):
        """Cycle QMK's unicode input mode (Windows, macOS, Linux, etc.)."""
        self._send_packet(UARTCommand.UNICODE_CYCLE_MODE)

    def reset_state(self):
        """Reset microcontroller state."""
        self._send_packet(UARTCommand.RESET_STATE)

    # Integration with Mooncrater Input events

    def process_mooncrater_event(self, event: Dict[str, Any]):
        """
        Process an event from mooncrater-input.py and send appropriate UART commands.

        Args:
            event: Mooncrater Input event dictionary
        """
        try:
            # Check connection and try to reconnect if needed
            if not self.is_connected():
                if not self._try_reconnect():
                    logger.warning("UART backend not connected, dropping event")
                    return

            category = event.get("category")
            event_type = event.get("type")

            if category == "keyboard":
                self._process_keyboard_event(event)
            elif category == "mouse":
                self._process_mouse_event(event)
            else:
                logger.debug(f"Ignoring event category: {category}")

        except Exception as e:
            logger.error(f"Error processing event in UART backend: {e}")
            self.connection_status = "failed"
            self.last_error = str(e)

    def _process_keyboard_event(self, event: Dict[str, Any]):
        """Process keyboard events from Mooncrater Input."""
        event_type = event.get("type")
        keyname = event.get("keyName", "")

        if event_type == "keyDown":
            self.send_key_down(keyname)
        elif event_type == "keyUp":
            self.send_key_up(keyname)
        elif event_type == "keyPress":
            self.send_key_press(keyname)
        elif event_type == "typeString":
            text = event.get("string", "")
            self.send_string(text)
        elif event_type == "typeQwertyString":
            text = event.get("string", "")
            self.send_qwerty_string(text)
        elif event_type == "typeUnicodeString":
            text = event.get("string", "")
            self.send_unicode_string(text)
        elif event_type == "unicodeCycleMode":
            self.send_unicode_cycle_mode()
        else:
            logger.debug(f"Ignoring keyboard event type: {event_type}")

    def _process_mouse_event(self, event: Dict[str, Any]):
        """Process mouse events from Mooncrater Input."""
        event_type = event.get("type")

        if event_type == "mouseRel":
            delta_x = event.get("deltaX", 0)
            delta_y = event.get("deltaY", 0)
            self.send_mouse_move(delta_x, delta_y)

        elif event_type == "mouseButton":
            button = event.get("button", "")
            state = event.get("state", "")

            if state == "down":
                self.send_mouse_button_down(button)
            elif state == "up":
                self.send_mouse_button_up(button)

        elif event_type == "mouseDown":
            button = event.get("button", "")
            self.send_mouse_button_down(button)

        elif event_type == "mouseUp":
            button = event.get("button", "")
            self.send_mouse_button_up(button)

        elif event_type == "scroll":
            # Handle regular scroll events (usually integer values)
            delta_x = event.get("deltaX", 0)
            delta_y = event.get("deltaY", 0)
            self.send_mouse_wheel(float(delta_x), float(delta_y))

        elif event_type == "smoothScroll":
            # Handle smooth scroll events (fractional values)
            delta_x = event.get("deltaX", 0.0)
            delta_y = event.get("deltaY", 0.0)
            self.send_mouse_wheel(delta_x, delta_y)

        else:
            logger.debug(f"Ignoring mouse event type: {event_type}")


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    # Example usage
    backend = UARTBackend("/dev/serial0", 115200)

    if backend.start():
        try:
            # Test keyboard events
            backend.send_key_press("KEY_H")
            time.sleep(0.1)
            backend.send_key_press("KEY_I")
            time.sleep(0.1)

            # Test string macro
            backend.send_string("Hello from Host!")
            time.sleep(0.5)

            # Test mouse events
            backend.send_mouse_move(100, -50)
            time.sleep(0.1)
            backend.send_mouse_button_down("left")
            time.sleep(0.1)
            backend.send_mouse_button_up("left")

        finally:
            backend.stop()
    else:
        print("Failed to start UART backend")


def create_uart_backend_for_mooncrater_input(
    serial_port: str = "/dev/serial0", baud_rate: int = 115200,
    chunk_delay_qwerty_seconds: float = 0.5, chunk_delay_unicode_seconds: float = 2.0
) -> UARTBackend:
    """
    Factory function for creating UART backend for use with mooncrater-input.py

    This function would be called from mooncrater-input.py configuration files.

    Example usage in config:
        uart_backend = create_uart_backend_for_mooncrater_input()
        uart_backend.start()

        def enhanced_handler(device, json_event):
            # Process through normal Mooncrater Input logic first
            # ...

            # Then send to UART backend
            uart_backend.process_mooncrater_event(json_event)

        set_event_handler(enhanced_handler)
    """
    return UARTBackend(serial_port, baud_rate, chunk_delay_qwerty_seconds, chunk_delay_unicode_seconds)


def register(mooncrater_input):
    """Register uart_backend types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # Constructor for uart output
    def create_uart_output(mooncrater_input_instance, tag, serial_port="/dev/serial0", baud_rate=115200, **kwargs):
        try:
            backend = UARTBackend(serial_port, baud_rate)

            if backend.start():
                logger.info(f"UART backend '{tag}' started successfully")
            else:
                logger.warning(f"Failed to start UART backend '{tag}' - will retry when needed")

            return backend
        except ImportError as e:
            raise RuntimeError(f"UART backend not available: {e}")
        except Exception as e:
            logger.error(f"Failed to create UART backend '{tag}': {e}")
            raise

    # Destructor for uart output
    def destroy_uart_output(mooncrater_input_instance, tag, instance):
        try:
            instance.stop()
            return True
        except Exception as e:
            logger.error(f"Error stopping UART backend {tag}: {e}")
            return False

    # Send events function for uart output
    def send_events_uart_output(mooncrater_input_instance, instance, events):
        try:
            for json_event in events:
                instance.process_mooncrater_event(json_event)
            return True
        except Exception as e:
            logger.error(f"Failed to send events to UART: {e}")
            return False

    # Register the uart output type
    mooncrater_input.register_output_type(
        type_name="uart",
        constructor=lambda tag, **kwargs: create_uart_output(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_uart_output(mooncrater_input, tag, instance),
        send_events=lambda instance, events: send_events_uart_output(mooncrater_input, instance, events),
        metadata={
            "description": "UART serial output for microcontroller HID devices",
            "module": "uart_backend"
        }
    )
