#!/usr/bin/env python3

import json
import logging
import random
import ssl
import socket
import threading
import time
import traceback
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import List
from .utils import _log_global, json_event_for_network

# Set up logging
logger = logging.getLogger(__name__)


class RemoteEventHandler(BaseHTTPRequestHandler):
    """HTTP handler for receiving events from remote clients."""

    def __init__(self, request, client_address, server):
        self.event_handler = server.event_handler
        super().__init__(request, client_address, server)

    def log_message(self, format, *args):
        """Override to reduce HTTP server logging noise."""
        pass

    def do_POST(self):
        """Handle POST requests containing JSON events."""
        try:
            # Check path
            if self.path != "/events":
                self.send_error(404, "Not Found")
                return

            # Authenticate client
            auth_result = self._authenticate_client()
            if not auth_result:
                self.send_error(401, "Unauthorized")
                return

            client_tag, auth_method = auth_result

            # Read content
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_error(400, "No content")
                return

            # Use self.rfile instead of self.request.recv for proper HTTP handling
            body = self.rfile.read(content_length).decode("utf-8")

            # Parse JSON
            try:
                event_data = json.loads(body)
            except json.JSONDecodeError as e:
                logger.warning(f"JSON decode error from {client_tag}: {e}")
                self.send_error(400, "Invalid JSON")
                return

            # Validate it's a dict (JSON event)
            if not isinstance(event_data, dict):
                logger.warning(
                    f"Event from {client_tag} is not a JSON object: {type(event_data)}"
                )
                self.send_error(400, "Event must be a JSON object")
                return

            # Process event through centralized processor
            try:
                self.event_handler(client_tag, event_data)
            except Exception as e:
                logger.error(f"Error processing event from {client_tag}: {e}")
                raise

            # Send response
            response_data = {
                "status": "received",
                "client": client_tag,
                "auth": auth_method,
            }
            response_json = json.dumps(response_data)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response_json)))
            self.send_header("Connection", "keep-alive")  # Allow connection reuse
            self.end_headers()
            self.wfile.write(response_json.encode("utf-8"))
            self.wfile.flush()  # Ensure data is sent immediately

        except Exception as e:
            logger.error(f"Exception in do_POST: {e}")
            traceback.print_exc(file=sys.stderr)

            try:
                self.send_error(500, f"Internal Server Error: {str(e)}")
            except Exception as send_error_exc:
                logger.error(f"Failed to send error response: {send_error_exc}")

    def _authenticate_client(self):
        """Authenticate client using token. Returns (tag, auth_method) or None."""
        server = self.server
        clients_config = server.clients_config

        # Try token authentication
        auth_header = self.headers.get("Authorization", "")

        if auth_header.startswith("Bearer "):
            provided_token = auth_header[7:]  # Remove "Bearer " prefix

            # Check against configured tokens
            for client in clients_config:
                if "token" in client:
                    if client["token"] == provided_token:
                        return (client["tag"], "token")

        # Sleep a random amount of time before returning failure to mitigate timing attacks
        time.sleep(random.uniform(0, 0.2))
        return None

    def do_GET(self):
        """Handle GET requests for health checks."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")


class RemoteListener:
    """HTTPS server that listens for events from remote clients."""

    def __init__(self, event_handler, config):
        self.event_handler = event_handler
        self.config = config
        self.server = None
        self.server_thread = None
        self.running = False

        # Validate config
        required_fields = ["bindTo", "port", "cert_file", "key_file", "clients"]
        for field in required_fields:
            if field not in config:
                raise ValueError(
                    f"Remote listener config missing required field: {field}"
                )

        # Validate clients configuration
        if not isinstance(config["clients"], list):
            raise ValueError("Remote listener 'clients' must be a list")

        for i, client in enumerate(config["clients"]):
            if "tag" not in client:
                raise ValueError(f"Remote listener client {i} missing 'tag' field")

            # Check authentication method
            if "token" not in client:
                raise ValueError(
                    f"Remote listener client {i} (tag: {client['tag']}) must have 'token' for authentication"
                )

    def start(self):
        """Start the HTTPS server."""
        try:
            # Create HTTP server
            server_address = (self.config["bindTo"], self.config["port"])
            self.server = HTTPServer(server_address, RemoteEventHandler)
            self.server.event_handler = self.event_handler
            self.server.clients_config = self.config["clients"]

            # Set up SSL context
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(
                self.config["cert_file"], self.config["key_file"]
            )

            # Since we only use token authentication, don't require client certificates
            ssl_context.verify_mode = ssl.CERT_NONE

            # Wrap socket with SSL
            self.server.socket = ssl_context.wrap_socket(
                self.server.socket, server_side=True
            )

            # Start server in thread
            self.running = True
            self.server_thread = threading.Thread(target=self._run_server, daemon=True)
            self.server_thread.start()

            logger.info(
                f"Remote listener started on https://{self.config['bindTo']}:{self.config['port']}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start remote listener: {e}")
            return False

    def _run_server(self):
        """Run the HTTPS server loop."""
        try:
            self.server.timeout = 1.0  # Socket timeout for checking if we should stop

            while self.running:
                try:
                    request = None
                    client_address = None

                    try:
                        # Accept a connection with timeout
                        request, client_address = self.server.get_request()

                        # Verify the request (SSL handshake, etc.)
                        if self.server.verify_request(request, client_address):
                            # Process the request
                            self.server.process_request(request, client_address)
                        else:
                            self.server.handle_error(request, client_address)

                    except socket.timeout:
                        # Expected timeout - just continue the loop to check if we should stop
                        continue
                    except socket.error:
                        # Handle socket errors gracefully
                        continue
                    finally:
                        # Always try to close the request socket if it was opened
                        if request:
                            try:
                                self.server.shutdown_request(request)
                            except:
                                pass

                except Exception as e:
                    if self.running:  # Only log if we weren't intentionally stopped
                        logger.error(f"Remote listener error: {e}")
                        # Continue running even after errors
                        time.sleep(0.1)  # Brief pause to prevent tight error loops

        except Exception as e:
            logger.error(f"Remote listener fatal error: {e}")
            traceback.print_exc(file=sys.stderr)

    def stop(self):
        """Stop the HTTPS server."""
        self.running = False
        if self.server:
            self.server.server_close()
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1.0)


class RemoteBackend:
    """Manages a persistent remote backend connection for KVM-like functionality."""

    def __init__(self, tag: str, config: dict):
        self.tag = tag
        self.config = config
        self.connection = None  # Persistent HTTP connection
        self.connected = False
        self.ssl_context = None
        self.base_url = None
        self.headers = {}  # Common headers for all requests
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2.0  # seconds

        # Event buffering for batch sending
        self.event_buffer = []
        self.buffer_lock = threading.Lock()
        self.buffer_thread = None
        self.buffer_running = False
        self.batch_size = 20  # Max events per batch
        self.batch_timeout = 0.016  # 60 FPS (16ms)
        self.last_send_time = time.time()

        # Optional modifier pipeline for batched events
        self.modifier_pipeline = config.get("modifier_pipeline", None)

        # Validate config
        required_fields = ["host", "port"]
        for field in required_fields:
            if field not in config:
                raise ValueError(
                    f"Remote backend config missing required field: {field}"
                )

        # Must have token for authentication
        if "token" not in config:
            raise ValueError(
                f"Remote backend config must have 'token' for authentication"
            )

    def connect(self):
        """Establish a persistent connection to the remote backend (non-blocking)."""

        # Start connection in background thread to avoid blocking main thread
        def connect_worker():
            try:
                # Reset reconnection attempts when connect() is called explicitly
                self.reconnect_attempts = 0

                self._setup_ssl_context()
                self._setup_headers()

                # Try to establish connection
                success = self._establish_connection()
                if success:
                    logger.info(
                        f"Successfully connected to remote backend '{self.tag}'"
                    )
                else:
                    logger.warning(f"Failed to connect to remote backend '{self.tag}'")

            except Exception as e:
                logger.error(f"Failed to initialize remote backend {self.tag}: {e}")

        # Always return True immediately to not block caller
        # Connection status will be updated asynchronously
        threading.Thread(target=connect_worker, daemon=True).start()
        return True

    def _setup_ssl_context(self):
        """Set up SSL context based on configuration."""
        import ssl

        # Create SSL context
        ssl_context = ssl.create_default_context()

        # Handle server certificate verification
        if "server_fingerprint" in self.config:
            # Use custom fingerprint verification
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            # We'll verify the fingerprint manually
            self.expected_fingerprint = (
                self.config["server_fingerprint"].lower().replace(":", "")
            )
        elif self.config.get("skip_cert_verification", False):
            # Explicitly skip certificate verification (not recommended for production)
            logger.warning(
                f"Skipping certificate verification for remote backend '{self.tag}' - this is insecure!"
            )
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
        else:
            # No verification method specified - this is an error
            raise ValueError(
                f"Remote backend '{self.tag}' must specify server verification method: "
                "either 'server_fingerprint' or 'skip_cert_verification=True'"
            )

        # Client authentication is now only token-based (no certificates)

        self.ssl_context = ssl_context
        self.base_url = f"https://{self.config['host']}:{self.config['port']}"

    def _setup_headers(self):
        """Set up common headers for all requests."""
        self.headers = {
            "Content-Type": "application/json",
            "Connection": "keep-alive",
            "User-Agent": "mooncrater-input",
        }

        # Add authentication
        if "token" in self.config:
            self.headers["Authorization"] = f"Bearer {self.config['token']}"

    def _establish_connection(self):
        """Establish the persistent HTTP connection."""
        import http.client
        import ssl

        try:
            # Create persistent HTTPS connection
            host = self.config["host"]
            port = self.config["port"]

            # Handle custom fingerprint verification
            if hasattr(self, "expected_fingerprint"):
                # For fingerprint verification, we need to handle SSL manually
                self.connection = http.client.HTTPSConnection(
                    host, port, context=self.ssl_context, timeout=10
                )

                # Connect and verify fingerprint
                self.connection.connect()
                cert_der = self.connection.sock.getpeercert(binary_form=True)
                if cert_der:
                    import hashlib

                    actual_fingerprint = hashlib.sha256(cert_der).hexdigest()
                    if actual_fingerprint != self.expected_fingerprint:
                        raise ssl.SSLError(
                            f"Server certificate fingerprint mismatch. Expected: {self.expected_fingerprint}, Got: {actual_fingerprint}"
                        )
            else:
                # Standard SSL verification
                self.connection = http.client.HTTPSConnection(
                    host, port, context=self.ssl_context, timeout=10
                )
                self.connection.connect()

            # Test connection with health check
            self.connection.putrequest("GET", "/health")
            for header, value in self.headers.items():
                if header != "Content-Type":  # Skip content-type for GET
                    self.connection.putheader(header, value)
            self.connection.endheaders()

            response = self.connection.getresponse()
            response_data = response.read()  # Read and discard response body

            if response.status in [
                200,
                404,
            ]:  # 404 is OK if health endpoint doesn't exist
                self.connected = True
                self.reconnect_attempts = 0

                # Start the buffer processing thread
                self._start_buffer_thread()

                logger.info(
                    f"Connected to remote backend '{self.tag}' at {self.base_url}"
                )
                return True
            else:
                logger.error(
                    f"Health check failed for remote backend {self.tag}: HTTP {response.status}"
                )
                self._close_connection()
                return False

        except Exception as e:
            logger.error(f"Failed to connect to remote backend {self.tag}: {e}")
            self._close_connection()
            return False

    def _close_connection(self):
        """Close the persistent connection."""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass
            self.connection = None
        self.connected = False

    def _start_buffer_thread(self):
        """Start the buffer processing thread."""
        if self.buffer_thread and self.buffer_thread.is_alive():
            return  # Already running

        self.buffer_running = True
        self.buffer_thread = threading.Thread(target=self._buffer_worker, daemon=True)
        self.buffer_thread.start()

    def _stop_buffer_thread(self):
        """Stop the buffer processing thread."""
        self.buffer_running = False
        if self.buffer_thread and self.buffer_thread.is_alive():
            self.buffer_thread.join(timeout=0.1)  # Brief wait for cleanup

    def _buffer_worker(self):
        """Background thread that processes the event buffer."""

        while self.buffer_running:
            try:
                current_time = time.time()
                should_flush = False

                with self.buffer_lock:
                    buffer_size = len(self.event_buffer)
                    time_since_last_send = current_time - self.last_send_time

                    # Flush if buffer is full or timeout reached
                    if buffer_size >= self.batch_size or (
                        buffer_size > 0 and time_since_last_send >= self.batch_timeout
                    ):
                        should_flush = True

                if should_flush:
                    self._flush_buffer()

                # Sleep for a short time to avoid busy waiting
                time.sleep(0.001)  # 1ms

            except Exception as e:
                if self.buffer_running:  # Only log if not shutting down
                    logger.error(f"Error in buffer worker for {self.tag}: {e}")
                time.sleep(0.01)  # Brief pause on error

        # Final flush on shutdown
        self._flush_buffer()

    def _flush_buffer(self):
        """Flush the current event buffer."""
        events_to_send = []

        with self.buffer_lock:
            if not self.event_buffer:
                return  # Nothing to flush

            events_to_send = self.event_buffer[:]
            self.event_buffer.clear()
            self.last_send_time = time.time()

        if not events_to_send:
            return

        # Process events through modifier pipeline if one is configured
        if self.modifier_pipeline is not None:
            try:
                events_to_send = self.modifier_pipeline.process_events(events_to_send)
                logger.debug(
                    f"Processed batch through modifier pipeline for remote backend '{self.tag}'"
                )
            except Exception as e:
                logger.error(
                    f"Error processing events through modifier pipeline for {self.tag}: {e}"
                )
                # Continue with unmodified events on error

        if not events_to_send:
            return  # All events were filtered out by pipeline

        # Create eventList event if we have multiple events
        if len(events_to_send) > 1:
            event_list = {
                "type": "eventList",
                "category": "eventList",
                "events": events_to_send,
            }
            self._send_event_immediate(event_list)
        elif len(events_to_send) == 1:
            # Single event, send directly
            self._send_event_immediate(events_to_send[0])

    def _try_reconnect(self):
        """Attempt to reconnect if connection is lost."""
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.error(
                f"Max reconnection attempts ({self.max_reconnect_attempts}) reached for remote backend {self.tag}"
            )
            return False

        self.reconnect_attempts += 1
        logger.info(
            f"Attempting to reconnect to remote backend {self.tag} (attempt {self.reconnect_attempts}/{self.max_reconnect_attempts})"
        )

        # Wait before reconnecting
        time.sleep(self.reconnect_delay)

        # Close old connection
        self._close_connection()

        # Try to reconnect
        return self._establish_connection()

    def send_events(self, events: List[dict]):
        """Buffer events for batch sending to remote backend."""
        if not self.connected:
            # Drop events when disconnected - don't block main thread
            logger.debug(
                f"Dropping {len(events)} events to disconnected remote backend '{self.tag}'"
            )
            return False

        # Add events to buffer for batch processing
        with self.buffer_lock:
            for event in events:
                event_data = json_event_for_network(event)
                self.event_buffer.append(event_data)

        return True

    def _send_event_immediate(self, event_data: dict):
        """Send a single event immediately (used by buffer worker)."""
        try:
            if not self.connection:
                return False

            # Send POST request
            json_data = json.dumps(event_data)

            self.connection.putrequest("POST", "/events")
            for header, value in self.headers.items():
                self.connection.putheader(header, value)
            self.connection.putheader("Content-Length", str(len(json_data)))
            self.connection.endheaders()
            self.connection.send(json_data.encode("utf-8"))

            # Get response
            response = self.connection.getresponse()
            response_data = response.read()  # Read and consume response body

            if response.status == 200:
                return True
            else:
                logger.warning(
                    f"Remote backend {self.tag} returned HTTP {response.status}"
                )
                return False

        except Exception as e:
            logger.error(f"Error sending batch event to {self.tag}: {e}")
            self.connected = False
            return False

    def close(self):
        """Close the persistent remote connection."""
        logger.info(f"Closing connection to remote backend {self.tag}")
        self._stop_buffer_thread()
        self._close_connection()


def register(mooncrater_input):
    """Register remote types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # REMOTE OUTPUT
    # Constructor for remote output
    def create_remote_output(mooncrater_input_instance, tag, config, **kwargs):
        backend = RemoteBackend(tag, config)
        backend.connect()  # Try to connect, but don't fail if it doesn't work
        return backend

    # Destructor for remote output
    def destroy_remote_output(mooncrater_input_instance, tag, instance):
        try:
            instance.close()
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error closing remote output {tag}: {e}")
            return False

    # Send events function for remote output
    def send_events_remote_output(mooncrater_input_instance, instance, events):
        try:
            if not instance.connected:
                instance.connect()
            instance.send_events(events)
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Failed to send events to remote: {e}")
            return False

    # Register the remote output type
    mooncrater_input.register_output_type(
        type_name="remote",
        constructor=lambda tag, **kwargs: create_remote_output(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_remote_output(mooncrater_input, tag, instance),
        send_events=lambda instance, events: send_events_remote_output(mooncrater_input, instance, events),
        metadata={
            "description": "Remote output for sending events over HTTPS",
            "module": "remote"
        }
    )

    # REMOTE INPUT
    # Constructor for remote input (listener)
    def create_remote_input(mooncrater_input_instance, tag, config, **kwargs):
        remote_handler = mooncrater_input_instance._create_input_handler(
            input_kind="remote",
            source_tag=tag,
            preprocessing_func=mooncrater_input_instance._remote_preprocessing
        )
        listener = RemoteListener(remote_handler, config)
        if listener.start():
            return listener
        else:
            raise RuntimeError(f"Failed to create remote input listener")

    # Destructor for remote input
    def destroy_remote_input(mooncrater_input_instance, tag, instance):
        try:
            instance.stop()
            return True
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error stopping remote input {tag}: {e}")
            return False

    # Register the remote input type
    mooncrater_input.register_input_type(
        type_name="remote",
        constructor=lambda tag, **kwargs: create_remote_input(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_remote_input(mooncrater_input, tag, instance),
        metadata={
            "description": "Remote input listener for receiving events over HTTPS",
            "module": "remote"
        }
    )
