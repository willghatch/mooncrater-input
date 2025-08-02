#!/usr/bin/env python3

import json
import logging
import sys
import threading
import time
import select
import os
import queue
from typing import Dict, Any, Callable, Optional, TextIO, List

# Set up logging
logger = logging.getLogger(__name__)


class FileInput:
    """Manages non-blocking file-based input for receiving JSON events from files or stdin."""

    def __init__(self, event_callback: Callable[[str, dict], None]):
        """Initialize with a callback function that receives (source_tag, json_event)."""
        self.event_callback = event_callback
        self.input_readers = {}  # tag -> reader info
        self.running = False
        self.reader_threads = {}  # tag -> thread
        self.event_queue = queue.Queue()  # Queue for events from all readers
        self.processing_thread = None

    def start(self):
        """Start the file input system."""
        self.running = True
        # Start the event processing thread
        self.processing_thread = threading.Thread(
            target=self._process_events, daemon=True
        )
        self.processing_thread.start()
        logger.info("File input system started")

    def stop(self):
        """Stop all file readers."""
        self.running = False

        # Stop all reader threads
        for tag, thread in self.reader_threads.items():
            if thread.is_alive():
                thread.join(timeout=1.0)

        # Wait for processing thread
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=1.0)

        logger.info("File input system stopped")

    def open_file_input(self, tag: str, file_path: str) -> bool:
        """Open a file for reading JSON events.

        Args:
            tag: A unique tag that identifies this file input
            file_path: Path to the file, or "stdin" for standard input
        """
        try:
            if file_path == "stdin":
                file_handle = sys.stdin
                readable_path = "stdin"
                is_fifo = False
            else:
                # Check if it's a FIFO/pipe for special handling
                is_fifo = False
                if os.path.exists(file_path):
                    try:
                        import stat

                        st = os.stat(file_path)
                        is_fifo = stat.S_ISFIFO(st.st_mode) or stat.S_ISREG(st.st_mode)
                    except (OSError, ImportError):
                        is_fifo = os.path.isfile(file_path)
                file_handle = open(file_path, "r")
                readable_path = file_path

            reader_info = {
                "file_handle": file_handle,
                "path": readable_path,
                "should_close": file_path != "stdin",
                "is_fifo": is_fifo,
                "buffer": "",  # Line buffer for partial reads
                "file_pos": 0,  # Track position for regular files
            }

            self.input_readers[tag] = reader_info

            # Start non-blocking reader thread
            reader_thread = threading.Thread(
                target=self._read_file_nonblocking, args=(tag, reader_info), daemon=True
            )
            self.reader_threads[tag] = reader_thread
            reader_thread.start()

            logger.info(
                f"Opened non-blocking file input with tag '{tag}' from {readable_path}"
            )
            return True

        except OSError as e:
            logger.error(f"Failed to open file input '{tag}' from {file_path}: {e}")
            return False

    def close_file_input(self, tag: str):
        """Close a file input by tag."""
        if tag in self.input_readers:
            reader_info = self.input_readers[tag]

            # Stop the reader thread
            if tag in self.reader_threads:
                thread = self.reader_threads[tag]
                if thread.is_alive():
                    thread.join(timeout=1.0)
                del self.reader_threads[tag]

            try:
                if reader_info["should_close"]:
                    reader_info["file_handle"].close()
            except OSError:
                pass
            del self.input_readers[tag]
            logger.info(f"Closed file input with tag '{tag}'")

    def _process_events(self):
        """Process events from the queue in the main processing thread."""
        while self.running:
            try:
                # Get event from queue with timeout
                event_data = self.event_queue.get(timeout=0.1)

                # Call the event callback
                if self.event_callback:
                    tag = event_data.get("_internal_tag", "unknown")
                    source_tag = event_data.get("_internal_source_tag", f"file-{tag}")

                    # Remove internal metadata
                    event_data.pop("_internal_tag", None)
                    event_data.pop("_internal_source_tag", None)

                    self.event_callback(source_tag, event_data)

                self.event_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error processing file input event: {e}")

    def _read_file_nonblocking(self, tag: str, reader_info: Dict):
        """Non-blocking file reader that works with regular files, FIFOs, and streams."""
        file_handle = reader_info["file_handle"]
        readable_path = reader_info["path"]
        is_stdin = readable_path == "stdin"

        logger.debug(f"Starting non-blocking reader for {readable_path}")

        try:
            while self.running and tag in self.input_readers:

                # For regular files, read all available content first
                if not is_stdin and not reader_info["is_fifo"]:
                    # Seek to last known position
                    file_handle.seek(reader_info["file_pos"])

                ready_to_read = True

                # Use select for stdin and FIFOs to avoid blocking
                if is_stdin or reader_info["is_fifo"]:
                    try:
                        if hasattr(select, "select"):
                            # Unix-like systems
                            ready, _, _ = select.select([file_handle], [], [], 0.1)
                            ready_to_read = bool(ready)
                        else:
                            # Windows - just try to read with a small timeout
                            ready_to_read = True
                    except (OSError, ValueError):
                        # Handle cases where select doesn't work (e.g., regular files on some systems)
                        ready_to_read = True

                if ready_to_read:
                    try:
                        # Read available data without blocking
                        if is_stdin:
                            # For stdin, use select and read carefully to avoid blocking
                            try:
                                # Try to make stdin non-blocking on Unix systems
                                import fcntl

                                fd = file_handle.fileno()
                                flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                                fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                                try:
                                    chunk = file_handle.read(1024)
                                except (IOError, BlockingIOError):
                                    chunk = None  # Would block
                            except (ImportError, AttributeError):
                                # Windows or system without fcntl - just try a small read
                                try:
                                    chunk = file_handle.read(1)
                                except:
                                    chunk = None
                        else:
                            # For regular files and FIFOs
                            chunk = file_handle.read(4096)

                        if chunk:
                            # Update file position for regular files
                            if not is_stdin and not reader_info["is_fifo"]:
                                reader_info["file_pos"] = file_handle.tell()

                            # Add chunk to buffer
                            reader_info["buffer"] += chunk

                            # Process complete lines
                            while "\n" in reader_info["buffer"]:
                                line, reader_info["buffer"] = reader_info[
                                    "buffer"
                                ].split("\n", 1)
                                line = line.strip()

                                if line:
                                    self._process_line(tag, line, readable_path)

                        elif not is_stdin and not reader_info["is_fifo"]:
                            # Regular file, no more data - wait a bit and check for new content
                            time.sleep(0.1)

                    except IOError as e:
                        if e.errno == 11:  # EAGAIN - would block
                            pass
                        else:
                            logger.warning(f"IOError reading from {readable_path}: {e}")
                    except Exception as e:
                        logger.error(f"Error reading from {readable_path}: {e}")
                        break
                else:
                    # Nothing ready to read, sleep briefly
                    time.sleep(0.1)

        except Exception as e:
            logger.error(f"Fatal error in file reader for {readable_path}: {e}")
        finally:
            logger.debug(f"File reader thread for {readable_path} exiting")

    def _process_line(self, tag: str, line: str, readable_path: str):
        """Process a single line of JSON input."""
        try:
            event_data = json.loads(line)

            # Add input metadata
            event_data["inputTag"] = tag
            event_data["inputKind"] = "file"

            # Add internal metadata for processing thread
            event_data["_internal_tag"] = tag
            event_data["_internal_source_tag"] = f"file-{tag}"

            # Queue the event for processing
            try:
                self.event_queue.put(event_data, timeout=0.1)
            except queue.Full:
                logger.warning(f"Event queue full, dropping event from {readable_path}")

        except json.JSONDecodeError as e:
            logger.warning(f"JSON decode error in file {readable_path}: {e}")
        except Exception as e:
            logger.error(f"Error processing line from {readable_path}: {e}")

    def close(self):
        """Clean up all file readers."""
        self.running = False

        # Close all readers
        for tag in list(self.input_readers.keys()):
            self.close_file_input(tag)

        # Wait for processing thread to finish
        if self.processing_thread and self.processing_thread.is_alive():
            self.processing_thread.join(timeout=2.0)


class FileOutput:
    """Manages non-blocking file-based output for writing JSON events to files or stdout."""

    def __init__(self):
        """Initialize the file output system."""
        self.output_writers = {}  # tag -> writer info
        self.write_queue = queue.Queue()  # Queue for write operations
        self.running = False
        self.writer_thread = None

    def start(self):
        """Start the file output system."""
        if not self.running:
            self.running = True
            self.writer_thread = threading.Thread(
                target=self._writer_thread, daemon=True
            )
            self.writer_thread.start()
            logger.info("File output system started")

    def stop(self):
        """Stop the file output system."""
        self.running = False
        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=2.0)
        logger.info("File output system stopped")

    def open_file_output(self, tag: str, file_path: str) -> bool:
        """Open a file for writing JSON events.

        Args:
            tag: A unique tag that identifies this file output
            file_path: Path to the file, or "stdout" for standard output
        """
        try:
            if file_path == "stdout":
                file_handle = sys.stdout
                readable_path = "stdout"
            else:
                file_handle = open(file_path, "w")
                readable_path = file_path

            writer_info = {
                "file_handle": file_handle,
                "path": readable_path,
                "should_close": file_path != "stdout",
                "connection_status": "connected",
                "last_error": None,
            }

            self.output_writers[tag] = writer_info

            # Ensure writer thread is running
            if not self.running:
                self.start()

            logger.info(
                f"Opened non-blocking file output with tag '{tag}' to {readable_path}"
            )
            return True

        except OSError as e:
            logger.error(f"Failed to open file output '{tag}' to {file_path}: {e}")
            return False

    def get_connection_status(self, tag: str) -> dict:
        """Get connection status for a file output by tag."""
        if tag not in self.output_writers:
            return {
                "status": "not_found",
                "last_error": f"Output tag '{tag}' not found"
            }

        writer_info = self.output_writers[tag]
        try:
            # Check if file handle is still valid
            file_handle = writer_info["file_handle"]
            if hasattr(file_handle, "closed") and file_handle.closed:
                writer_info["connection_status"] = "disconnected"
                writer_info["last_error"] = "File handle is closed"

            return {
                "status": writer_info.get("connection_status", "unknown"),
                "last_error": writer_info.get("last_error"),
                "path": writer_info["path"]
            }
        except Exception as e:
            writer_info["connection_status"] = "failed"
            writer_info["last_error"] = str(e)
            return {
                "status": "failed",
                "last_error": str(e),
                "path": writer_info.get("path", "unknown")
            }

    def close_file_output(self, tag: str):
        """Close a file output by tag."""
        if tag in self.output_writers:
            writer_info = self.output_writers[tag]

            # Queue a close operation
            try:
                self.write_queue.put(("close", tag), timeout=1.0)
            except queue.Full:
                logger.warning(f"Write queue full, forcing close of {tag}")
                self._close_writer_sync(tag, writer_info)

            del self.output_writers[tag]
            logger.info(f"Queued close for file output with tag '{tag}'")

    def _close_writer_sync(self, tag: str, writer_info: Dict):
        """Synchronously close a writer (used by background thread)."""
        try:
            writer_info["file_handle"].flush()
            if writer_info["should_close"]:
                writer_info["file_handle"].close()
        except OSError as e:
            logger.warning(f"Error closing file output '{tag}': {e}")

    def send_events(self, tag: str, events: List[dict]) -> bool:
        """Send events to a file output (non-blocking).

        Args:
            tag: The tag identifying the file output
            events: List of JSON events to write

        Returns:
            True if events were queued successfully
        """
        if tag not in self.output_writers:
            logger.error(f"File output tag '{tag}' not found")
            return False

        # Queue the write operation
        try:
            self.write_queue.put(("write", tag, events), timeout=0.1)
            return True
        except queue.Full:
            logger.warning(
                f"Write queue full, dropping {len(events)} events for '{tag}'"
            )
            return False

    def _writer_thread(self):
        """Background thread that handles all file writing."""
        logger.debug("File output writer thread started")

        while self.running:
            try:
                # Get write operation from queue
                operation = self.write_queue.get(timeout=0.1)

                if operation[0] == "write":
                    _, tag, events = operation
                    self._write_events_sync(tag, events)
                elif operation[0] == "close":
                    _, tag = operation
                    if tag in self.output_writers:
                        writer_info = self.output_writers[tag]
                        self._close_writer_sync(tag, writer_info)

                self.write_queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in file output writer thread: {e}")

        logger.debug("File output writer thread exiting")

    def _write_events_sync(self, tag: str, events: List[dict]):
        """Synchronously write events (used by background thread)."""
        if tag not in self.output_writers:
            return

        writer_info = self.output_writers[tag]

        try:
            for event in events:
                json_line = json.dumps(event)
                writer_info["file_handle"].write(json_line + "\n")
            writer_info["file_handle"].flush()

        except Exception as e:
            logger.error(f"Error writing events to file output '{tag}': {e}")

    def close(self):
        """Clean up all file writers."""
        # Close all writers
        for tag in list(self.output_writers.keys()):
            self.close_file_output(tag)

        # Stop the writer thread
        self.stop()


def register(mooncrater_input):
    """Register file_io types with a MooncraterInput instance.

    Args:
        mooncrater_input: MooncraterInput instance to register with
    """
    # FILE INPUT
    # Constructor for file input
    def create_file_input(mooncrater_input_instance, tag, file_path, **kwargs):
        # Create or get the shared FileInput instance
        if "file_input" not in mooncrater_input_instance.backend_storage:
            mooncrater_input_instance.backend_storage["file_input"] = FileInput(
                mooncrater_input_instance._create_input_handler("file")
            )
            if mooncrater_input_instance.running:
                mooncrater_input_instance.backend_storage["file_input"].start()

        file_input = mooncrater_input_instance.backend_storage["file_input"]
        if file_input.open_file_input(tag, file_path):
            return file_input
        else:
            raise RuntimeError(f"Failed to create file input '{tag}' from '{file_path}'")

    # Destructor for file input
    def destroy_file_input(mooncrater_input_instance, tag, instance):
        if "file_input" in mooncrater_input_instance.backend_storage:
            return mooncrater_input_instance.backend_storage["file_input"].close_file_input(tag)
        return False

    # Register the file input type
    mooncrater_input.register_input_type(
        type_name="file",
        constructor=lambda tag, **kwargs: create_file_input(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_file_input(mooncrater_input, tag, instance),
        metadata={
            "description": "File input for reading JSON events",
            "module": "file_io"
        }
    )

    # FILE OUTPUT
    # Constructor for file output
    def create_file_output(mooncrater_input_instance, tag, file_path, **kwargs):
        # Create or get the shared FileOutput instance
        if "file_output" not in mooncrater_input_instance.backend_storage:
            mooncrater_input_instance.backend_storage["file_output"] = FileOutput()

        file_output = mooncrater_input_instance.backend_storage["file_output"]
        if file_output.open_file_output(tag, file_path):
            return file_output
        else:
            raise RuntimeError(f"Failed to create file output '{tag}' at '{file_path}'")

    # Destructor for file output
    def destroy_file_output(mooncrater_input_instance, tag, instance):
        if "file_output" in mooncrater_input_instance.backend_storage:
            return mooncrater_input_instance.backend_storage["file_output"].close_file_output(tag)
        return False

    # Send events function for file output
    def send_events_file_output(mooncrater_input_instance, instance, events):
        # Find the tag for this instance
        for tag in instance.output_writers.keys():
            if instance == mooncrater_input_instance.file_output:
                return instance.send_events(tag, events)
        return False

    # Register the file output type
    mooncrater_input.register_output_type(
        type_name="file",
        constructor=lambda tag, **kwargs: create_file_output(mooncrater_input, tag, **kwargs),
        destructor=lambda tag, instance: destroy_file_output(mooncrater_input, tag, instance),
        send_events=lambda instance, events: send_events_file_output(mooncrater_input, instance, events),
        metadata={
            "description": "File output for writing JSON events",
            "module": "file_io"
        }
    )
