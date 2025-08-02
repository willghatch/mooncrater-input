#!/usr/bin/env python3
"""
Event Modifier Pipeline System

This module provides a flexible pipeline system for modifying events before they
are sent to backend outputs. Modifier pipelines can be attached to any output type.
"""

import logging
from typing import List, Dict, Any, Callable, Optional
from abc import ABC, abstractmethod

# Set up logging
logger = logging.getLogger(__name__)


class EventModifier(ABC):
    """Abstract base class for event modifiers."""

    @abstractmethod
    def process_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process a list of events and return modified events.

        Args:
            events: List of JSON events to process

        Returns:
            List of processed JSON events (may be different length than input)
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """Return a descriptive name for this modifier."""
        pass


class ModifierPipeline:
    """
    A pipeline of event modifiers that can be attached to any output backend.
    Events flow through the modifiers in order before being sent to the backend.
    """

    def __init__(self):
        """Initialize a modifier pipeline."""
        self.modifiers: List[EventModifier] = []
        self.enabled = True

    def add_modifier(self, modifier: EventModifier) -> None:
        """
        Add a modifier to the end of the pipeline.

        Args:
            modifier: The modifier to add
        """
        self.modifiers.append(modifier)
        logger.debug(f"Added modifier '{modifier.get_name()}' to pipeline")

    def remove_modifier(self, modifier: EventModifier) -> bool:
        """
        Remove a modifier from the pipeline.

        Args:
            modifier: The modifier to remove

        Returns:
            True if the modifier was found and removed, False otherwise
        """
        try:
            self.modifiers.remove(modifier)
            logger.debug(f"Removed modifier '{modifier.get_name()}' from pipeline")
            return True
        except ValueError:
            logger.warning(
                f"Modifier '{modifier.get_name()}' not found in pipeline"
            )
            return False

    def remove_modifier_by_name(self, name: str) -> bool:
        """
        Remove the first modifier with the given name from the pipeline.

        Args:
            name: The name of the modifier to remove

        Returns:
            True if a modifier was found and removed, False otherwise
        """
        for modifier in self.modifiers:
            if modifier.get_name() == name:
                return self.remove_modifier(modifier)
        return False

    def clear_modifiers(self) -> None:
        """Remove all modifiers from the pipeline."""
        self.modifiers.clear()
        logger.debug("Cleared all modifiers from pipeline")

    def get_modifier_names(self) -> List[str]:
        """Return a list of modifier names in pipeline order."""
        return [modifier.get_name() for modifier in self.modifiers]

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the entire pipeline."""
        self.enabled = enabled
        logger.debug(f"Pipeline {'enabled' if enabled else 'disabled'}")

    def is_enabled(self) -> bool:
        """Return whether the pipeline is enabled."""
        return self.enabled

    def process_events(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process events through the modifier pipeline.

        Args:
            events: List of input events

        Returns:
            List of processed events after going through all modifiers
        """
        if not self.enabled or not self.modifiers:
            return events

        processed_events = events

        for modifier in self.modifiers:
            try:
                processed_events = modifier.process_events(processed_events)
                logger.debug(
                    f"Modifier '{modifier.get_name()}' processed {len(events)} -> {len(processed_events)} events"
                )
            except Exception as e:
                logger.error(
                    f"Error in modifier '{modifier.get_name()}': {e}"
                )
                # Continue with unmodified events if a modifier fails
                continue

        return processed_events
