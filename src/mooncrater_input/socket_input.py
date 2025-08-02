#!/usr/bin/env python3

import json
import logging
import os
import queue
import select
import socket
import threading
from typing import Dict, Any, Callable

# Set up logging
logger = logging.getLogger(__name__)


class SocketInput:
    """Manages Unix domain socket input for receiving commands and events."""

    def __init__(self, event_callback: Callable[[str, dict], None]):
        """Initialize with a callback function that receives (source_tag, json_event)."""
        self.event_callback = event_callback
        self.socket_servers = {}  # tag -> socket server
        self.accept_threads = {}  # tag -> accept thread

    def open_socket_listener(self, tag: str, socket_path: str, mode: int = 0o600) -> bool:
        """Open a Unix domain socket listener for the given tag."""
        try:
            if os.path.exists(socket_path):
                os.unlink(socket_path)

            socket_server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            socket_server.bind(socket_path)
            os.chmod(socket_path, mode)
            socket_server.listen(5)
            socket_server.setblocking(False)

            self.socket_servers[tag] = {"server": socket_server, "path": socket_path}

            # Start accepting connections in a thread immediately
            thread = threading.Thread(
                target=self._accept_connections,
                args=(tag, socket_server),
                daemon=True
            )
            self.accept_threads[tag] = thread
            thread.start()

            logger.info(f"Opened socket listener with tag '{tag}' at {socket_path}")
            return True

        except OSError as e:
            logger.error(
                f"Failed to create socket listener '{tag}' at {socket_path}: {e}"
            )
            return False

    def close_socket_listener(self, tag: str):
        """Close a socket listener by tag."""
        if tag in self.socket_servers:
            server_info = self.socket_servers[tag]
            try:
                server_info["server"].close()
                if os.path.exists(server_info["path"]):
                    os.unlink(server_info["path"])
            except OSError:
                pass
            del self.socket_servers[tag]

            # Clean up accept thread
            if tag in self.accept_threads:
                del self.accept_threads[tag]

            logger.info(f"Closed socket listener with tag '{tag}'")

    def _accept_connections(self, tag: str, socket_server: socket.socket):
        """Accept connections for a specific socket server."""
        while tag in self.socket_servers:  # Keep running while this socket is open
            try:
                ready, _, _ = select.select([socket_server], [], [], 0.1)
                if ready:
                    client_socket, _ = socket_server.accept()
                    threading.Thread(
                        target=self._handle_client,
                        args=(tag, client_socket),
                        daemon=True,
                    ).start()
            except OSError:
                break

    def _handle_client(self, tag: str, client_socket: socket.socket):
        """Handle individual client connections."""
        try:
            with client_socket:
                buffer = b""
                while tag in self.socket_servers:  # Keep running while socket is open
                    ready, _, _ = select.select([client_socket], [], [], 0.1)
                    if ready:
                        # Keep reading until we would block or client disconnects
                        while True:
                            data = client_socket.recv(1024)
                            if not data:
                                # Client disconnected - process any remaining buffer
                                if buffer:
                                    # Try to process whatever's in the buffer
                                    self._process_json_buffer(tag, buffer)
                                break

                            buffer += data
                            buffer = self._process_json_buffer(tag, buffer)

                            # Check if more data is immediately available
                            ready_again, _, _ = select.select([client_socket], [], [], 0)
                            if not ready_again:
                                break  # No more data available right now

                        # If client disconnected (data was empty), exit outer loop
                        if not data:
                            break
        except OSError:
            pass

    def _process_json_buffer(self, tag: str, buffer: bytes) -> bytes:
        """Process buffer looking for complete JSON objects.

        Uses json.JSONDecoder.raw_decode() to properly parse JSON objects.
        Handles multi-line JSON and multiple JSON objects in buffer.
        Returns remaining buffer after processing complete JSON objects.
        """
        try:
            buffer_str = buffer.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning(f"Invalid UTF-8 data received on socket {tag}")
            return b""  # Drop invalid data

        decoder = json.JSONDecoder()
        start_pos = 0

        while start_pos < len(buffer_str):
            # Skip whitespace
            while start_pos < len(buffer_str) and buffer_str[start_pos].isspace():
                start_pos += 1

            if start_pos >= len(buffer_str):
                break

            try:
                # Use JSONDecoder.raw_decode to parse from current position
                event_data, end_pos = decoder.raw_decode(buffer_str, start_pos)

                # Add input metadata
                event_data["inputTag"] = tag
                event_data["inputKind"] = "unixDomainSocket"

                # Call the event callback
                if self.event_callback:
                    self.event_callback(f"socket-{tag}", event_data)

                # Move to position after the parsed JSON object (end_pos is absolute, not relative)
                start_pos = end_pos

            except json.JSONDecodeError as e:
                # Incomplete JSON object - save remaining buffer
                remaining_buffer = buffer_str[start_pos:]
                return remaining_buffer.encode("utf-8")
            except (TypeError, ValueError) as e:
                logger.warning(f"Invalid JSON data from socket {tag}: {e}")
                # Skip the problematic character and try again
                start_pos += 1

        # All complete JSON objects processed, no remaining data
        return b""

    def close(self):
        """Clean up all socket listeners."""
        for tag in list(self.socket_servers.keys()):
            self.close_socket_listener(tag)


def register(mooncrater_input):
    """Register socket_input types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # Constructor for socket input
    def create_socket_input(mooncrater_input_instance, tag, socket_path, mode=0o600, **kwargs):
        # Create or get the shared SocketInput instance
        if "socket_input" not in mooncrater_input_instance.backend_storage:
            mooncrater_input_instance.backend_storage["socket_input"] = SocketInput(
                mooncrater_input_instance._create_input_handler("unixDomainSocket")
            )

        socket_input = mooncrater_input_instance.backend_storage["socket_input"]
        if socket_input.open_socket_listener(tag, socket_path, mode=mode):
            return socket_input
        else:
            raise RuntimeError(f"Failed to create socket input '{tag}' at '{socket_path}'")

    # Destructor for socket input
    def destroy_socket_input(mooncrater_input_instance, tag, instance):
        if "socket_input" in mooncrater_input_instance.backend_storage:
            return mooncrater_input_instance.backend_storage["socket_input"].close_socket_listener(tag)
        return False

    # Register the socket input type
    mooncrater_input.register_input_type(
        type_name="socket",
        constructor=lambda tag, **kwargs: create_socket_input(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_socket_input(mooncrater_input, tag, instance),
        metadata={
            "description": "Unix domain socket input for receiving JSON events",
            "module": "socket_input"
        }
    )
