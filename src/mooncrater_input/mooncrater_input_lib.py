#!/usr/bin/env python3

import argparse
import asyncio
import json
import logging
import os
import queue
import select
import socket
import ssl
import sys
import threading
import time
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional, Any, Union, Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse, parse_qs

# Import only utility modules - input/output backends will be registered by user
from .utils import _log_global, json_event_for_network, set_global_log_level, handleTypeEvents, configure_unicode_handling
from .modifier_pipeline import ModifierPipeline

# Set up logging
logger = logging.getLogger(__name__)


@dataclass
class InputConfig:
    """Configuration for creating an input."""

    type: str
    tag: str
    create_func: Callable
    remove_func: Callable
    start_func: Optional[Callable] = None
    get_status_func: Optional[Callable] = None
    config_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputConfig:
    """Configuration for creating an output."""

    type: str
    tag: str
    create_func: Callable
    remove_func: Callable
    send_events_func: Callable
    get_status_func: Optional[Callable] = None
    config_params: Dict[str, Any] = field(default_factory=dict)


class GenericInputOutputManager:
    """Manages inputs and outputs through configuration objects."""

    def __init__(self, parent_input):
        self.parent_input = parent_input
        self.inputs: Dict[str, Any] = {}
        self.outputs: Dict[str, Any] = {}
        self.input_configs: Dict[str, InputConfig] = {}
        self.output_configs: Dict[str, OutputConfig] = {}
        self.inputs_by_type: Dict[str, List[str]] = {}
        self.outputs_by_type: Dict[str, List[str]] = {}

    def create_input(self, config: InputConfig, **kwargs) -> bool:
        """Create an input using the provided configuration."""
        try:
            # Merge config params with kwargs
            merged_params = {**(config.config_params or {}), **kwargs}

            # Call the create function
            instance = config.create_func(config.tag, **merged_params)

            # Store the instance and config
            self.inputs[config.tag] = instance
            self.input_configs[config.tag] = config

            # Update type mapping
            if config.type not in self.inputs_by_type:
                self.inputs_by_type[config.type] = []
            self.inputs_by_type[config.type].append(config.tag)

            # Call start function if provided
            if config.start_func:
                config.start_func(instance)

            logger.info(
                f"Created {config.type} input '{config.tag}' using generic interface"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create input {config.tag}: {e}")
            return False

    def create_output(self, config: OutputConfig, **kwargs) -> bool:
        """Create an output using the provided configuration."""
        try:
            # Merge config params with kwargs
            merged_params = {**(config.config_params or {}), **kwargs}

            # Call the create function
            instance = config.create_func(config.tag, **merged_params)

            # Store the instance and config
            self.outputs[config.tag] = instance
            self.output_configs[config.tag] = config

            # Update type mapping
            if config.type not in self.outputs_by_type:
                self.outputs_by_type[config.type] = []
            self.outputs_by_type[config.type].append(config.tag)

            logger.info(
                f"Created {config.type} output '{config.tag}' using generic interface"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to create output {config.tag}: {e}")
            return False

    def remove_input(self, tag: str) -> bool:
        """Remove an input by tag using the generic interface."""
        if tag in self.input_configs:
            config = self.input_configs[tag]
            instance = self.inputs.get(tag)

            try:
                # Call the remove function
                result = config.remove_func(tag, instance)

                # Clean up our records
                if result:
                    del self.inputs[tag]
                    del self.input_configs[tag]

                    # Remove from type mapping
                    if config.type in self.inputs_by_type:
                        self.inputs_by_type[config.type].remove(tag)
                        if not self.inputs_by_type[config.type]:
                            del self.inputs_by_type[config.type]

                logger.info(
                    f"Removed {config.type} input '{tag}' using generic interface"
                )
                return result
            except Exception as e:
                logger.error(f"Failed to remove input {tag}: {e}")
                return False

        return False

    def remove_output(self, tag: str) -> bool:
        """Remove an output by tag using the generic interface."""
        if tag in self.output_configs:
            config = self.output_configs[tag]
            instance = self.outputs.get(tag)

            try:
                # Call the remove function
                result = config.remove_func(tag, instance)

                # Clean up our records
                if result:
                    del self.outputs[tag]
                    del self.output_configs[tag]

                    # Remove from type mapping
                    if config.type in self.outputs_by_type:
                        self.outputs_by_type[config.type].remove(tag)
                        if not self.outputs_by_type[config.type]:
                            del self.outputs_by_type[config.type]

                logger.info(
                    f"Removed {config.type} output '{tag}' using generic interface"
                )
                return result
            except Exception as e:
                logger.error(f"Failed to remove output {tag}: {e}")
                return False

        return False

    def send_events_to_output(self, tag: str, events: List[dict]) -> bool:
        """Send events to an output using the generic interface."""
        if tag in self.output_configs:
            config = self.output_configs[tag]
            instance = self.outputs.get(tag)

            try:
                # Process events through modifier pipeline before sending to backend
                if tag in self.parent_input.modifier_pipelines:
                    pipeline = self.parent_input.modifier_pipelines[tag]
                    processed_events = pipeline.process_events(events)
                else:
                    processed_events = events
                return config.send_events_func(instance, processed_events)
            except Exception as e:
                logger.error(f"Failed to send events to output {tag}: {e}")
                return False

        return False

    def get_input_tags(self) -> List[str]:
        """Get list of all input tags managed by the generic interface."""
        return list(self.inputs.keys())

    def get_output_tags(self) -> List[str]:
        """Get list of all output tags managed by the generic interface."""
        return list(self.outputs.keys())

    def get_inputs_by_type(self, input_type: str) -> List[str]:
        """Get list of input tags of a specific type."""
        return self.inputs_by_type.get(input_type, [])

    def get_outputs_by_type(self, output_type: str) -> List[str]:
        """Get list of output tags of a specific type."""
        return self.outputs_by_type.get(output_type, [])

    def create_event_handler(self, tag: str, input_type: str):
        """Create an event handler for the given input that uses centralized processing."""

        def event_handler(json_event: dict):
            self.parent_input._centralized_event_processor(tag, input_type, json_event)

        return event_handler

    def get_input_kind_for_tag(self, tag: str) -> Optional[str]:
        """Get the input kind for a given input tag."""
        if tag in self.input_configs:
            return self.input_configs[tag].type
        return None

    def get_output_kind_for_tag(self, tag: str) -> Optional[str]:
        """Get the output kind for a given output tag."""
        if tag in self.output_configs:
            return self.output_configs[tag].type
        return None


# All class definitions have been moved to separate modules


class MooncraterInput:
    def __init__(self, config_file: Optional[str] = None, log_level: str = "info"):
        self.config_file = config_file

        # Set up logging level
        numeric_level = getattr(logging, log_level.upper(), None)
        if not isinstance(numeric_level, int):
            raise ValueError(f"Invalid log level: {log_level}")
        logging.basicConfig(level=numeric_level, format="[%(levelname)s] %(message)s")

        # Set global log level for other classes that still use the old system
        set_global_log_level(log_level)

        # Global configuration dictionary
        self.config = {}

        # Per-output tag configuration
        self.output_config = {}  # tag -> dict of configuration options

        # Event queues
        self.input_queue = queue.Queue()

        # Registration system for input/output types
        self.registered_input_types = {}  # type_name -> {constructor, destructor, ...}
        self.registered_output_types = {}  # type_name -> {constructor, destructor, send_events, ...}

        # Instance tracking (unified for all input/output types)
        self.input_instances = {}  # tag -> {type, instance, ...}
        self.output_instances = {}  # tag -> {type, instance, ...}

        # Backend storage (for plugins to use)
        # Plugins can store shared instances here (e.g., captured_devices, socket_input, file_input)
        self.backend_storage = {}  # plugin-specific storage area

        # Modifier pipelines for outputs
        self.modifier_pipelines = {}  # tag -> ModifierPipeline

        self.running = False

        # Configuration handlers
        self.event_handler = None

    def register_input_type(
        self,
        type_name: str,
        constructor: Callable,
        destructor: Callable,
        start_func: Optional[Callable] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Register a new input type.

        Args:
            type_name: String name for the type (used for tagging input events)
            constructor: Function to create new instances (signature varies by type)
            destructor: Function to remove instances (signature: destructor(tag, instance) -> bool)
            start_func: Optional function to start the input after creation
            metadata: Optional metadata about the input type
        """
        self.registered_input_types[type_name] = {
            "constructor": constructor,
            "destructor": destructor,
            "start_func": start_func,
            "metadata": metadata or {}
        }
        logger.info(f"Registered input type: {type_name}")

    def register_output_type(
        self,
        type_name: str,
        constructor: Callable,
        destructor: Callable,
        send_events: Callable,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Register a new output type.

        Args:
            type_name: String name for the type (used for tagging output)
            constructor: Function to create new instances (signature varies by type)
            destructor: Function to remove instances (signature: destructor(tag, instance) -> bool)
            send_events: Function to send events to output (signature: send_events(instance, events) -> bool)
            metadata: Optional metadata about the output type
        """
        self.registered_output_types[type_name] = {
            "constructor": constructor,
            "destructor": destructor,
            "send_events": send_events,
            "metadata": metadata or {}
        }
        logger.info(f"Registered output type: {type_name}")

    def create_input(self, type_name: str, tag: str, **kwargs) -> bool:
        """Create an input instance using a registered input type.

        Args:
            type_name: The registered type name
            tag: Unique tag for this input instance
            **kwargs: Arguments to pass to the constructor

        Returns:
            True if successful, False otherwise
        """
        if type_name not in self.registered_input_types:
            logger.error(f"Input type '{type_name}' not registered")
            return False

        reg = self.registered_input_types[type_name]

        try:
            # Call the constructor
            instance = reg["constructor"](tag, **kwargs)

            # Store the instance
            self.input_instances[tag] = {
                "type": type_name,
                "instance": instance,
                "registration": reg
            }

            # Call start function if provided
            if reg.get("start_func"):
                reg["start_func"](instance)

            logger.info(f"Created {type_name} input '{tag}'")
            return True

        except Exception as e:
            logger.error(f"Failed to create {type_name} input '{tag}': {e}")
            return False

    def create_output(self, type_name: str, tag: str, **kwargs) -> bool:
        """Create an output instance using a registered output type.

        Args:
            type_name: The registered type name
            tag: Unique tag for this output instance
            **kwargs: Arguments to pass to the constructor

        Returns:
            True if successful, False otherwise
        """
        if type_name not in self.registered_output_types:
            logger.error(f"Output type '{type_name}' not registered")
            return False

        reg = self.registered_output_types[type_name]

        try:
            # Call the constructor
            instance = reg["constructor"](tag, **kwargs)

            # Store the instance
            self.output_instances[tag] = {
                "type": type_name,
                "instance": instance,
                "registration": reg
            }

            logger.info(f"Created {type_name} output '{tag}'")
            return True

        except Exception as e:
            logger.error(f"Failed to create {type_name} output '{tag}': {e}")
            return False

    def remove_input(self, tag: str) -> bool:
        """Remove an input instance by tag.

        Args:
            tag: The tag identifying the input to remove

        Returns:
            True if successful, False otherwise
        """
        if tag not in self.input_instances:
            logger.warning(f"No input found with tag: {tag}")
            return False

        info = self.input_instances[tag]
        reg = info["registration"]

        try:
            # Call the destructor
            result = reg["destructor"](tag, info["instance"])

            if result:
                del self.input_instances[tag]
                logger.info(f"Removed {info['type']} input '{tag}'")

            return result

        except Exception as e:
            logger.error(f"Failed to remove input '{tag}': {e}")
            return False

    def remove_output(self, tag: str) -> bool:
        """Remove an output instance by tag.

        Args:
            tag: The tag identifying the output to remove

        Returns:
            True if successful, False otherwise
        """
        if tag not in self.output_instances:
            logger.warning(f"No output found with tag: {tag}")
            return False

        info = self.output_instances[tag]
        reg = info["registration"]

        try:
            # Call the destructor
            result = reg["destructor"](tag, info["instance"])

            if result:
                del self.output_instances[tag]
                # Also remove the modifier pipeline for this output
                if tag in self.modifier_pipelines:
                    del self.modifier_pipelines[tag]
                    logger.debug(f"Removed modifier pipeline for output '{tag}'")
                logger.info(f"Removed {info['type']} output '{tag}'")

            return result

        except Exception as e:
            logger.error(f"Failed to remove output '{tag}': {e}")
            return False

    def get_modifier_pipeline(self, tag: str) -> ModifierPipeline:
        """Get or create a modifier pipeline for an output tag.

        Args:
            tag: The output tag

        Returns:
            The modifier pipeline for the tag
        """
        if tag not in self.modifier_pipelines:
            self.modifier_pipelines[tag] = ModifierPipeline()
            logger.debug(f"Created new modifier pipeline for tag '{tag}'")

        return self.modifier_pipelines[tag]

    def remove_modifier_pipeline(self, tag: str) -> bool:
        """Remove the modifier pipeline for a tag.

        Args:
            tag: The output tag

        Returns:
            True if the pipeline was found and removed, False otherwise
        """
        if tag in self.modifier_pipelines:
            del self.modifier_pipelines[tag]
            logger.debug(f"Removed modifier pipeline for tag '{tag}'")
            return True
        return False

    def _centralized_event_processor(
        self, source_tag: str, input_kind: str, json_event: dict
    ):
        """Centralized event processor that ensures all events have proper tagging."""
        # Ensure the event has the required metadata fields, and that fields for this instance of mooncrater-input are used.
        json_event["inputTag"] = source_tag
        json_event["inputKind"] = input_kind
        self.input_queue.put(("json_event", json_event))

    def _create_input_handler(self, input_kind: str, source_tag: str = None, preprocessing_func=None):
        """Create a specialized input handler that closes over tag and input type.

        Args:
            input_kind: The type of input (e.g., "capturedDevice", "unixDomainSocket", "file", "remote")
            source_tag: Optional fixed source tag. If None, tag will be extracted from event or arguments
            preprocessing_func: Optional function to preprocess events before centralized processing

        Returns:
            Handler function specialized for this input type
        """
        def input_handler(*args, **kwargs):
            # Handle different argument patterns from different input types
            if len(args) == 2:
                # Pattern: handler(tag_or_path, json_event) - for socket, file, remote
                tag_or_path, json_event = args
                if source_tag is not None:
                    # Use fixed tag
                    final_tag = source_tag
                elif input_kind == "capturedDevice":
                    # Extract tag from event metadata for captured devices
                    final_tag = json_event.get("inputTag", "unknown_device")
                else:
                    # Use first argument as tag for socket/file/remote
                    final_tag = tag_or_path
            else:
                raise ValueError(f"Unexpected arguments to input handler: {args}")

            # Apply any preprocessing
            if preprocessing_func:
                json_event = preprocessing_func(json_event)

            # Process through centralized handler
            self._centralized_event_processor(final_tag, input_kind, json_event)

        return input_handler

    def _remote_preprocessing(self, json_event: dict) -> dict:
        """Preprocessing function for remote events to add timestamp."""
        json_event["remote-reception-unix-seconds"] = time.time()
        return json_event

    def send_events_to_backend(self, events: List[dict], backend_tag: str):
        """Send events to the specified backend using the generic output system."""
        # Process events through modifier pipeline before sending to backend
        if backend_tag in self.modifier_pipelines:
            pipeline = self.modifier_pipelines[backend_tag]
            processed_events = pipeline.process_events(events)
        else:
            processed_events = events

        # Check if this is a registered output
        if backend_tag in self.output_instances:
            info = self.output_instances[backend_tag]
            reg = info["registration"]
            try:
                reg["send_events"](info["instance"], processed_events)
            except Exception as e:
                logger.error(f"Failed to send events to output '{backend_tag}': {e}")
        else:
            logger.warning(f"Unknown backend tag: '{backend_tag}'")

    def get_output_tags(self) -> List[str]:
        """Get list of available output tags."""
        return list(self.output_instances.keys())

    def get_output_type(self, tag: str) -> str:
        """Get the output type for a given output tag.

        Args:
            tag: The output tag to check

        Returns:
            Output type string or "unknown"
        """
        if tag in self.output_instances:
            return self.output_instances[tag]["type"]
        return "unknown"

    def get_output_connection_status(self, tag: str) -> dict:
        """Get connection status for a specific output by tag.

        Args:
            tag: The output tag to check

        Returns:
            Dictionary with connection status information
        """
        if tag not in self.output_instances:
            return {
                "status": "not_found",
                "last_error": f"Output tag '{tag}' not found"
            }

        # Plugins can implement get_status methods to provide status
        # For now, return basic info
        return {
            "status": "unknown",
            "tag": tag,
            "type": self.output_instances[tag]["type"]
        }

    def set_event_handler(self, handler_func: Callable):
        """Set the custom event handler function."""
        self.event_handler = handler_func

    def set_input_led(self, tag, led_name: str, value: bool):
        """Set LED state on captured input devices.

        Args:
            tag: Tag of captured devices to set LED on, or True to set on all devices
            led_name: LED name (e.g., "capslock", "numlock", "scrolllock")
            value: True to turn on, False to turn off

        Returns:
            If tag is a string: True if LED was set on at least one device, False otherwise
            If tag is True: Number of devices that successfully set the LED
        """
        # Access the shared EvdevInputCapture instance if it exists
        if "captured_devices" in self.backend_storage:
            captured_devices = self.backend_storage["captured_devices"]
            if tag is True:
                # Set LED on all devices
                return captured_devices.set_led_all_devices(led_name, value)
            else:
                # Set LED on devices with specific tag
                return captured_devices.set_led(tag, led_name, value)
        else:
            logger.warning("No captured devices available for LED control")
            return False if tag is not True else 0

    def main_loop(self):
        """Main processing loop that handles JSON events."""
        while self.running:
            try:
                item_type, *args = self.input_queue.get(timeout=0.1)

                if item_type == "json_event":
                    json_event = args[0]
                    logger.debug(f"Processing JSON event from queue: {json_event}")

                    # Call custom event handler if one is set
                    if self.event_handler:
                        try:
                            logger.debug(
                                f"Calling event handler for inputTag '{json_event.get('inputTag')}'"
                            )
                            self.event_handler(json_event.get("inputTag"), json_event)
                            logger.debug("Event handler completed successfully")
                        except Exception as e:
                            logger.error(f"Error in event handler: {e}")
                            traceback.print_exc(file=sys.stderr)
                    else:
                        logger.debug("No event handler set, skipping event")

                self.input_queue.task_done()
            except queue.Empty:
                continue

    def run(self):
        """Start the Mooncrater Input system."""
        try:
            self.running = True

            logger.info("Mooncrater Input started")

            # Run main loop
            self.main_loop()

        except KeyboardInterrupt:
            logger.info("\nShutting down...")
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources."""
        self.running = False

        # Clean up all registered inputs
        for tag in list(self.input_instances.keys()):
            try:
                self.remove_input(tag)
            except Exception as e:
                logger.error(f"Error cleaning up input '{tag}': {e}")

        # Clean up all registered outputs
        for tag in list(self.output_instances.keys()):
            try:
                self.remove_output(tag)
            except Exception as e:
                logger.error(f"Error cleaning up output '{tag}': {e}")


# Library file - no main() function here
# Users should import MooncraterInput class and create their own instances
