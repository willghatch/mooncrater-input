#!/usr/bin/env python3
"""
Test socket input functionality.

Tests the socket input by creating a MooncraterInput instance with a socket input,
sending events over the Unix domain socket, and verifying they are all received.
"""

import json
import os
import socket
import tempfile
import time
import threading
import sys

# Make pytest optional
try:
    import pytest
except ImportError:
    # Create mock pytest decorators if pytest is not available
    class MockPytest:
        class mark:
            @staticmethod
            def timeout(seconds):
                def decorator(func):
                    return func
                return decorator
        @staticmethod
        def skip(msg):
            raise Exception(f"Test skipped: {msg}")
    pytest = MockPytest()

# Add the src directory to the path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from mooncrater_input.mooncrater_input_lib import MooncraterInput
from mooncrater_input import socket_input


class TestSocketConnection:
    """Test socket input connection functionality."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.received_events = []
        self.temp_files = []
        self.mooncrater = None
        self.socket_path = None

    def teardown_method(self):
        """Clean up after each test."""
        # Stop MooncraterInput instance
        if self.mooncrater:
            try:
                self.mooncrater.cleanup()
            except:
                pass

        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except:
                pass

    @pytest.mark.timeout(15)
    def test_socket_to_file_basic(self):
        """Test basic socket input event reception."""
        # Create temporary socket file
        socket_fd, self.socket_path = tempfile.mkstemp(prefix="test_socket_", suffix=".sock")
        os.close(socket_fd)
        os.unlink(self.socket_path)  # Remove the file so socket can bind to it
        self.temp_files.append(self.socket_path)

        # Create MooncraterInput instance
        self.mooncrater = MooncraterInput(log_level="debug")
        socket_input.register(self.mooncrater)

        # Create socket input
        success = self.mooncrater.create_input("socket", "test-socket", socket_path=self.socket_path)
        assert success, "Failed to create socket input"

        # Set up event handler to collect received events
        def handler(tag, event):
            self.received_events.append((tag, event))

        self.mooncrater.set_event_handler(handler)

        # Start the event loop in a thread
        loop_thread = threading.Thread(target=self.mooncrater.main_loop, daemon=True)
        self.mooncrater.running = True
        loop_thread.start()

        # Give the socket listener time to start
        time.sleep(0.5)

        # Connect to the socket and send test events
        test_events = [
            {"type": "keyDown", "keyName": "KEY_A", "timestamp": 1000},
            {"type": "keyUp", "keyName": "KEY_A", "timestamp": 1001},
            {"type": "mouseDown", "button": "left", "timestamp": 1002},
        ]

        # Send events over the socket
        client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_socket.connect(self.socket_path)

        for event in test_events:
            json_data = json.dumps(event) + "\n"
            client_socket.sendall(json_data.encode("utf-8"))

        # Give a moment for all data to be sent before closing
        time.sleep(0.1)
        client_socket.close()

        # Wait for events to be processed
        timeout = 5.0
        start_time = time.time()
        while len(self.received_events) < len(test_events) and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        # Stop the event loop
        self.mooncrater.running = False
        loop_thread.join(timeout=1.0)

        # Verify events were received
        assert len(self.received_events) == len(test_events), \
            f"Expected {len(test_events)} events, got {len(self.received_events)}"

        # Verify event contents
        for i in range(len(test_events)):
            tag, received_event = self.received_events[i]
            assert tag == "socket-test-socket", f"Event {i} has wrong tag: {tag}"
            assert received_event["type"] == test_events[i]["type"], \
                f"Event {i} type mismatch: expected {test_events[i]['type']}, got {received_event['type']}"

    @pytest.mark.timeout(15)
    def test_socket_multiple_events_batched(self):
        """Test that multiple events sent quickly are all processed."""
        # Create temporary socket file
        socket_fd, self.socket_path = tempfile.mkstemp(prefix="test_socket_batch_", suffix=".sock")
        os.close(socket_fd)
        os.unlink(self.socket_path)
        self.temp_files.append(self.socket_path)

        # Create MooncraterInput instance
        self.mooncrater = MooncraterInput(log_level="debug")
        socket_input.register(self.mooncrater)

        # Create socket input
        self.mooncrater.create_input("socket", "test-socket", socket_path=self.socket_path)

        # Set up event handler to collect received events
        def handler(tag, event):
            self.received_events.append((tag, event))

        self.mooncrater.set_event_handler(handler)

        # Start event loop
        loop_thread = threading.Thread(target=self.mooncrater.main_loop, daemon=True)
        self.mooncrater.running = True
        loop_thread.start()

        time.sleep(0.5)

        # Send many events quickly
        test_events = [
            {"type": "keyDown", "keyName": f"KEY_{i}", "timestamp": 2000 + i}
            for i in range(20)
        ]

        client_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client_socket.connect(self.socket_path)

        # Send all events as a batch
        for event in test_events:
            json_data = json.dumps(event) + "\n"
            client_socket.sendall(json_data.encode("utf-8"))

        client_socket.close()

        # Wait for all events to be processed
        timeout = 5.0
        start_time = time.time()
        while len(self.received_events) < len(test_events) and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        # Stop the event loop
        self.mooncrater.running = False
        loop_thread.join(timeout=1.0)

        # Verify all events were received
        assert len(self.received_events) == len(test_events), \
            f"Expected {len(test_events)} events, got {len(self.received_events)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
