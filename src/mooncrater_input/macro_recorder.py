#!/usr/bin/env python3
"""
MacroRecorder - A class for recording and playing back input event macros.

This module provides a macro recording system that can record sequences of input events
and play them back later. It supports multiple named recordings and configurable
event filtering.
"""

import logging
from typing import Dict, List, Union, Optional, Callable, Any


logger = logging.getLogger(__name__)


class MacroRecorder:
    """
    A macro recording system for input events.

    Features:
    - Record sequences of input events with optional string tags
    - Configurable predicate function to filter which events to record
    - Play back recorded macros by injecting them into the event stream
    - Support for multiple named recordings
    """

    def __init__(self, record_predicate: Optional[Callable[[Dict[str, Any]], bool]] = None):
        """
        Initialize the macro recorder.

        Args:
            record_predicate: Function that takes an event and returns True if it should be recorded.
                            If None, defaults to recording only keyboard events.
        """
        self.record_predicate = record_predicate or self._default_record_predicate
        self.recordings: Dict[str, List[Dict[str, Any]]] = {}  # tag -> list of events
        self.is_recording = False
        self.current_recording_tag: Optional[str] = None
        self.current_recording: List[Dict[str, Any]] = []

    def _default_record_predicate(self, event: Dict[str, Any]) -> bool:
        """Default predicate that records only keyboard events."""
        return event.get("category") == "keyboard"

    def startRecording(self, tag: Optional[str] = None) -> None:
        """
        Start recording events with an optional tag.

        Args:
            tag: Optional string tag for the recording. If None, uses "default".
        """
        if self.is_recording:
            logger.warning(f"Already recording with tag '{self.current_recording_tag}'. Stopping previous recording.")
            self.stopRecording()

        self.current_recording_tag = tag or "default"
        self.current_recording = []
        self.is_recording = True
        logger.info(f"Started recording macro with tag '{self.current_recording_tag}'")

    def stopRecording(self) -> None:
        """Stop recording and save the current recording."""
        if not self.is_recording:
            logger.warning("Not currently recording")
            return

        # Save the recording
        if self.current_recording_tag:
            self.recordings[self.current_recording_tag] = self.current_recording.copy()
            logger.info(f"Stopped recording macro '{self.current_recording_tag}' with {len(self.current_recording)} events")

        # Reset recording state
        self.is_recording = False
        self.current_recording_tag = None
        self.current_recording = []

    def getRecording(self, tag: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get a recorded macro by tag.

        Args:
            tag: Tag of the recording to retrieve. If None, uses "default".

        Returns:
            List of recorded events, or empty list if tag not found.
        """
        tag = tag or "default"
        return self.recordings.get(tag, [])

    def process(self, events: Union[Dict[str, Any], List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        Process events through the macro recorder.

        This method:
        1. Records events if currently recording and they match the predicate
        2. Detects macro playback events and injects recorded events
        3. Returns the original events (possibly with injected macro events)

        Args:
            events: Single event or list of events to process

        Returns:
            List of events (original events plus any injected macro playback events)
        """
        # Normalize input to list
        if isinstance(events, dict):
            event_list = [events]
        else:
            event_list = events

        output_events = []

        for event in event_list:
            # Check for macro playback event
            if (event.get("category") == "macro" and
                event.get("type") == "playback" and
                "tag" in event):

                tag = event["tag"]
                recording = self.getRecording(tag)
                if recording:
                    logger.info(f"Playing back macro '{tag}' with {len(recording)} events")
                    output_events.extend(recording)
                else:
                    logger.warning(f"No recording found for tag '{tag}'")
                # Don't pass through the macro playback event itself
                continue

            # Record the event if we're recording and it matches the predicate
            if self.is_recording and self.record_predicate(event):
                self.current_recording.append(event.copy())

            # Always pass through the original event
            output_events.append(event)

        return output_events

    def list_recordings(self) -> List[str]:
        """Get a list of all recording tags."""
        return list(self.recordings.keys())

    def delete_recording(self, tag: str) -> bool:
        """
        Delete a recording by tag.

        Args:
            tag: Tag of the recording to delete

        Returns:
            True if recording was deleted, False if tag not found
        """
        if tag in self.recordings:
            del self.recordings[tag]
            logger.info(f"Deleted recording '{tag}'")
            return True
        return False

    def clear_all_recordings(self) -> None:
        """Clear all recordings."""
        self.recordings.clear()
        logger.info("Cleared all recordings")

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the macro recorder."""
        return {
            "is_recording": self.is_recording,
            "current_recording_tag": self.current_recording_tag,
            "current_recording_length": len(self.current_recording) if self.is_recording else 0,
            "available_recordings": list(self.recordings.keys()),
            "total_recordings": len(self.recordings)
        }