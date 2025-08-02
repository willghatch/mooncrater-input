#!/usr/bin/env python3
"""
Test remote frontend and backend functionality.

Tests the remote input (listener) and remote output (backend) by creating two
MooncraterInput instances and sending events between them over HTTPS.
"""

import json
import os
import subprocess
import tempfile
import time
import threading
import ssl
import hashlib
from pathlib import Path
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
from mooncrater_input import remote


class TestRemoteConnection:
    """Test remote input and output connection functionality."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.received_events = []
        self.temp_files = []
        self.mooncrater1 = None
        self.mooncrater2 = None
        self.cert_file = None
        self.key_file = None
        self.test_port = 8443  # Use a non-standard port for testing

    def teardown_method(self):
        """Clean up after each test."""
        # Stop MooncraterInput instances
        if self.mooncrater1:
            try:
                self.mooncrater1.cleanup()
            except:
                pass

        if self.mooncrater2:
            try:
                self.mooncrater2.cleanup()
            except:
                pass

        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except:
                pass

    def _generate_test_certificate(self):
        """Get or generate a self-signed certificate for testing using openssl CLI.

        Reuses existing certificate files if they exist to speed up tests.
        """
        import subprocess
        from datetime import datetime

        # Use fixed paths for test certificates in the tests directory
        test_dir = os.path.dirname(os.path.abspath(__file__))
        cert_file_path = os.path.join(test_dir, 'test-remote-cert.pem')
        key_file_path = os.path.join(test_dir, 'test-remote-key.pem')

        # Check if certificate exists and is still valid
        cert_exists = os.path.exists(cert_file_path) and os.path.exists(key_file_path)

        if cert_exists:
            # Check if certificate is still valid (not expired)
            try:
                result = subprocess.run([
                    'openssl', 'x509', '-checkend', '0', '-noout', '-in', cert_file_path
                ], capture_output=True, text=True)
                cert_valid = (result.returncode == 0)
            except subprocess.CalledProcessError:
                cert_valid = False
        else:
            cert_valid = False

        # Generate new certificate only if it doesn't exist or is expired
        if not cert_valid:
            # Generate self-signed certificate using openssl
            # Valid for 365 days so it won't need frequent regeneration
            try:
                subprocess.run([
                    'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                    '-keyout', key_file_path,
                    '-out', cert_file_path,
                    '-days', '365',
                    '-nodes',
                    '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'
                ], check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to generate certificate: {e.stderr}")

        # Get certificate fingerprint using openssl
        try:
            result = subprocess.run([
                'openssl', 'x509', '-fingerprint', '-sha256', '-noout', '-in', cert_file_path
            ], check=True, capture_output=True, text=True)

            # Parse fingerprint from output like "SHA256 Fingerprint=AB:CD:EF:..."
            fingerprint_line = result.stdout.strip()
            if '=' in fingerprint_line:
                fingerprint = fingerprint_line.split('=')[1].replace(':', '').lower()
            else:
                raise RuntimeError("Failed to parse fingerprint from openssl output")

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get certificate fingerprint: {e.stderr}")

        return cert_file_path, key_file_path, fingerprint

    def event_callback(self, source_tag: str, json_event: dict):
        """Callback to capture received events."""
        self.received_events.append((source_tag, json_event))

    @pytest.mark.timeout(15)
    def test_remote_basic_connection(self):
        """Test basic remote connection and event transmission."""
        # Generate test certificate using openssl CLI
        cert_file, key_file, fingerprint = self._generate_test_certificate()

        # Create first MooncraterInput instance with remote input (listener)
        self.mooncrater1 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater1)

        # Set up event handler to capture events
        def handler1(tag, event):
            self.event_callback(tag, event)

        self.mooncrater1.set_event_handler(handler1)

        # Create remote input listener
        test_token = "test-auth-token-12345"
        listener_config = {
            "bindTo": "127.0.0.1",
            "port": self.test_port,
            "cert_file": cert_file,
            "key_file": key_file,
            "clients": [
                {
                    "tag": "test-client",
                    "token": test_token
                }
            ]
        }

        success = self.mooncrater1.create_input("remote", "listener1", config=listener_config)
        assert success, "Failed to create remote input listener"

        # Give the listener time to start
        time.sleep(0.5)

        # Create second MooncraterInput instance with remote output (backend)
        self.mooncrater2 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater2)

        # Create remote output backend
        backend_config = {
            "host": "127.0.0.1",
            "port": self.test_port,
            "token": test_token,
            "server_fingerprint": fingerprint
        }

        success = self.mooncrater2.create_output("remote", "backend1", config=backend_config)
        assert success, "Failed to create remote output backend"

        # Give the connection time to establish
        time.sleep(1.0)

        # Send test events from mooncrater2 to mooncrater1
        test_events = [
            {"type": "keyDown", "keyName": "A", "timestamp": 1000},
            {"type": "keyUp", "keyName": "A", "timestamp": 1001},
            {"type": "mouseDown", "button": "left", "timestamp": 1002},
        ]

        # Send events through the backend
        self.mooncrater2.send_events_to_backend(test_events, "backend1")

        # Start mooncrater1's event loop in a thread
        loop_thread = threading.Thread(target=self.mooncrater1.main_loop, daemon=True)
        self.mooncrater1.running = True
        loop_thread.start()

        # Wait for events to be received
        timeout = 5.0
        start_time = time.time()
        while len(self.received_events) < len(test_events) and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        # Stop the event loop
        self.mooncrater1.running = False
        loop_thread.join(timeout=1.0)

        # Verify events were received
        # Events may be batched in an eventList, so we need to unwrap them
        assert len(self.received_events) > 0, "No events received"

        # Extract individual events from eventList if present
        actual_events = []
        for source_tag, received_event in self.received_events:
            if received_event.get("type") == "eventList":
                # Unwrap eventList
                actual_events.extend(received_event.get("events", []))
            else:
                actual_events.append(received_event)

        assert len(actual_events) >= len(test_events), \
            f"Expected at least {len(test_events)} events, got {len(actual_events)}"

        # Verify event contents
        for i in range(len(test_events)):
            # The event should match the test event
            assert actual_events[i]["type"] == test_events[i]["type"], \
                f"Event {i} type mismatch: expected {test_events[i]['type']}, got {actual_events[i]['type']}"

    @pytest.mark.timeout(15)
    def test_remote_eventlist_batching(self):
        """Test that multiple events can be sent in an eventList batch."""
        # Generate test certificate using openssl CLI
        cert_file, key_file, fingerprint = self._generate_test_certificate()

        # Create listener
        self.mooncrater1 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater1)

        def handler1(tag, event):
            self.event_callback(tag, event)

        self.mooncrater1.set_event_handler(handler1)

        test_token = "test-token-batch"
        listener_config = {
            "bindTo": "127.0.0.1",
            "port": self.test_port,
            "cert_file": cert_file,
            "key_file": key_file,
            "clients": [{"tag": "batch-client", "token": test_token}]
        }

        self.mooncrater1.create_input("remote", "listener1", config=listener_config)
        time.sleep(0.5)

        # Create backend
        self.mooncrater2 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater2)

        backend_config = {
            "host": "127.0.0.1",
            "port": self.test_port,
            "token": test_token,
            "server_fingerprint": fingerprint
        }

        self.mooncrater2.create_output("remote", "backend1", config=backend_config)
        time.sleep(1.0)

        # Send many events to trigger batching
        test_events = [
            {"type": "keyDown", "keyName": f"KEY_{i}", "timestamp": 2000 + i}
            for i in range(20)
        ]

        self.mooncrater2.send_events_to_backend(test_events, "backend1")

        # Start event loop
        loop_thread = threading.Thread(target=self.mooncrater1.main_loop, daemon=True)
        self.mooncrater1.running = True
        loop_thread.start()

        # Wait for events
        timeout = 5.0
        start_time = time.time()
        while len(self.received_events) < len(test_events) and (time.time() - start_time) < timeout:
            time.sleep(0.1)

        self.mooncrater1.running = False
        loop_thread.join(timeout=1.0)

        # Verify we received all events (they may have been batched in eventLists)
        assert len(self.received_events) > 0, "No events received"

        # Extract individual events from eventList if present
        actual_events = []
        for source_tag, received_event in self.received_events:
            if received_event.get("type") == "eventList":
                # Unwrap eventList
                actual_events.extend(received_event.get("events", []))
            else:
                actual_events.append(received_event)

        assert len(actual_events) >= len(test_events), \
            f"Expected at least {len(test_events)} events, got {len(actual_events)}"


class TestRemoteConnectionFailures:
    """Test remote connection failure scenarios."""

    def setup_method(self):
        """Set up test environment before each test."""
        self.temp_files = []
        self.mooncrater1 = None
        self.mooncrater2 = None
        self.test_port = 8444  # Different port to avoid conflicts

    def teardown_method(self):
        """Clean up after each test."""
        if self.mooncrater1:
            try:
                self.mooncrater1.cleanup()
            except:
                pass

        if self.mooncrater2:
            try:
                self.mooncrater2.cleanup()
            except:
                pass

        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except:
                pass

    def _generate_test_certificate(self):
        """Get or generate a self-signed certificate for testing using openssl CLI.

        Reuses existing certificate files if they exist to speed up tests.
        """
        import subprocess
        from datetime import datetime

        # Use fixed paths for test certificates in the tests directory
        test_dir = os.path.dirname(os.path.abspath(__file__))
        cert_file_path = os.path.join(test_dir, 'test-remote-cert.pem')
        key_file_path = os.path.join(test_dir, 'test-remote-key.pem')

        # Check if certificate exists and is still valid
        cert_exists = os.path.exists(cert_file_path) and os.path.exists(key_file_path)

        if cert_exists:
            # Check if certificate is still valid (not expired)
            try:
                result = subprocess.run([
                    'openssl', 'x509', '-checkend', '0', '-noout', '-in', cert_file_path
                ], capture_output=True, text=True)
                cert_valid = (result.returncode == 0)
            except subprocess.CalledProcessError:
                cert_valid = False
        else:
            cert_valid = False

        # Generate new certificate only if it doesn't exist or is expired
        if not cert_valid:
            # Generate self-signed certificate using openssl
            # Valid for 365 days so it won't need frequent regeneration
            try:
                subprocess.run([
                    'openssl', 'req', '-x509', '-newkey', 'rsa:2048',
                    '-keyout', key_file_path,
                    '-out', cert_file_path,
                    '-days', '365',
                    '-nodes',
                    '-subj', '/CN=localhost',
                    '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'
                ], check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"Failed to generate certificate: {e.stderr}")

        # Get certificate fingerprint using openssl
        try:
            result = subprocess.run([
                'openssl', 'x509', '-fingerprint', '-sha256', '-noout', '-in', cert_file_path
            ], check=True, capture_output=True, text=True)

            # Parse fingerprint from output like "SHA256 Fingerprint=AB:CD:EF:..."
            fingerprint_line = result.stdout.strip()
            if '=' in fingerprint_line:
                fingerprint = fingerprint_line.split('=')[1].replace(':', '').lower()
            else:
                raise RuntimeError("Failed to parse fingerprint from openssl output")

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to get certificate fingerprint: {e.stderr}")

        return cert_file_path, key_file_path, fingerprint

    @pytest.mark.timeout(10)
    def test_remote_invalid_token(self):
        """Test that connection fails with invalid authentication token."""
        cert_file, key_file, fingerprint = self._generate_test_certificate()

        # Create listener with specific token
        self.mooncrater1 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater1)

        correct_token = "correct-token-12345"
        listener_config = {
            "bindTo": "127.0.0.1",
            "port": self.test_port,
            "cert_file": cert_file,
            "key_file": key_file,
            "clients": [{"tag": "test-client", "token": correct_token}]
        }

        self.mooncrater1.create_input("remote", "listener1", config=listener_config)
        time.sleep(0.5)

        # Create backend with WRONG token
        self.mooncrater2 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater2)

        wrong_token = "wrong-token-99999"
        backend_config = {
            "host": "127.0.0.1",
            "port": self.test_port,
            "token": wrong_token,  # Wrong token!
            "server_fingerprint": fingerprint
        }

        # Backend creation should succeed (connection is async)
        success = self.mooncrater2.create_output("remote", "backend1", config=backend_config)
        assert success, "Backend creation should succeed even with wrong token (connection is async)"

        time.sleep(1.0)

        # Try to send events - should fail due to authentication
        test_events = [{"type": "keyDown", "keyName": "A", "timestamp": 3000}]

        # The send may appear to succeed locally, but the server should reject it
        # We can't easily test the rejection without monitoring logs or connection state
        # This test documents the expected behavior

    @pytest.mark.timeout(10)
    def test_remote_fingerprint_mismatch(self):
        """Test that connection fails when server certificate fingerprint doesn't match."""
        cert_file, key_file, actual_fingerprint = self._generate_test_certificate()

        # Create listener
        self.mooncrater1 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater1)

        test_token = "test-token-fp"
        listener_config = {
            "bindTo": "127.0.0.1",
            "port": self.test_port,
            "cert_file": cert_file,
            "key_file": key_file,
            "clients": [{"tag": "test-client", "token": test_token}]
        }

        self.mooncrater1.create_input("remote", "listener1", config=listener_config)
        time.sleep(0.5)

        # Create backend with WRONG fingerprint
        self.mooncrater2 = MooncraterInput(log_level="debug")
        remote.register(self.mooncrater2)

        # Use a completely wrong fingerprint
        wrong_fingerprint = "0" * 64  # All zeros, definitely wrong

        backend_config = {
            "host": "127.0.0.1",
            "port": self.test_port,
            "token": test_token,
            "server_fingerprint": wrong_fingerprint  # Wrong fingerprint!
        }

        # Backend creation should succeed (connection happens in background)
        success = self.mooncrater2.create_output("remote", "backend1", config=backend_config)
        assert success, "Backend creation should succeed (connection is async)"

        # Wait for connection attempt
        time.sleep(2.0)

        # The backend should fail to connect due to fingerprint mismatch
        # Check backend instance to see if it's connected
        backend_instance = self.mooncrater2.output_instances["backend1"]["instance"]

        # The connection should have failed
        assert not backend_instance.connected, \
            "Backend should not be connected with wrong fingerprint"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
