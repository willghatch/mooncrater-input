# Mooncrater-Input Tests

This directory contains tests for the mooncrater-input system.

## Running Tests

1. Install test dependencies:
   ```bash
   pip install -r requirements-test.txt
   ```

2. Run all tests:
   ```bash
   pytest
   ```

3. Run with verbose output:
   ```bash
   pytest -v
   ```

## Test Coverage

Current tests cover:
- File input and output functionality
- Unix socket input functionality
- Basic integration through main MooncraterInput control flow
- Configuration namespace functions

## Notes

These tests are conservative and focus on capturing current behavior rather than 
changing functionality. Tests involving hardware (evdev, hid) are not included 
as they require special devices and permissions.

Some tests are marked with TODO comments where current behavior seems incomplete
or potentially wrong - these capture the current state for future reference.
