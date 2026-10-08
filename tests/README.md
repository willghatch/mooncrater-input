# Mooncrater-Input Tests

This directory contains tests for the mooncrater-input system.

## Running Tests

The standard way to run the tests is the `run-tests.sh` script at the repo root.
It uses `uv` to create a virtualenv at `./venv` (gitignored), installs the package and test dependencies into it, and runs pytest from this directory.
Extra arguments are passed to pytest:
   ```bash
   ./run-tests.sh
   ./run-tests.sh test_tap_or_hold_specific.py -k rapid
   ```

To run the tests manually instead:

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
