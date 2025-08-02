#!/usr/bin/env python3
"""
Generate Xcompose configuration file for Unicode characters from Unicode data.

This script downloads UnicodeData.txt from unicode.org and generates an Xcompose
configuration file that allows entering any Unicode character using the sequence:
<Multi_key> <less> <hex_digits> <greater>

For example, to enter U+15FA: <Multi_key> <less> <1> <5> <f> <a> <greater>
"""

import argparse
import os
import sys
import urllib.request
from pathlib import Path


def download_unicode_data(cache_file):
    """Download UnicodeData.txt if not cached."""
    if cache_file.exists():
        print(f"Using cached Unicode data: {cache_file}")
        return

    print("Downloading UnicodeData.txt...")
    url = "http://www.unicode.org/Public/UNIDATA/UnicodeData.txt"

    try:
        urllib.request.urlretrieve(url, cache_file)
        print(f"Downloaded and cached to: {cache_file}")
    except Exception as e:
        print(f"Error downloading Unicode data: {e}", file=sys.stderr)
        sys.exit(1)


def parse_unicode_data(data_file, limit=None):
    """Parse UnicodeData.txt and yield code points."""
    with open(data_file, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            fields = line.split(';')
            if len(fields) < 1:
                continue

            try:
                code_point = fields[0]
                code_point_int = int(code_point, 16)

                if limit and code_point_int >= limit:
                    continue

                yield code_point.lower()

            except ValueError:
                print(f"Warning: Invalid code point on line {line_num}: {fields[0]}", file=sys.stderr)
                continue


def generate_xcompose_entry(code_point):
    """Generate Xcompose entry for a code point."""
    # Create the key sequence with individual digit keys
    digits = list(code_point)
    key_sequence = " ".join(f"<{digit}>" for digit in digits)
    code_point_int = int(code_point, 16)

    # skip suppogates
    if 0xd800 <= code_point_int and code_point_int <= 0xdfff:
        return ""

    # Create the full line
    #return f'<Multi_key> <less> {key_sequence} <greater> : "\\0x{code_point}"'
    return f'<Multi_key> <less> {key_sequence} <greater> : "{chr(code_point_int)}"'


def main():
    parser = argparse.ArgumentParser(
        description="Generate Xcompose configuration for Unicode characters"
    )
    parser.add_argument(
        "--limit",
        type=lambda x: int(x, 0),  # Allow hex input with 0x prefix
        help="Only generate entries for code points below this value (default: no limit)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache",
        help="Directory to cache UnicodeData.txt (default: ~/.cache)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("unicode-xcompose"),
        help="Output file name (default: unicode-xcompose)"
    )

    args = parser.parse_args()

    # Ensure cache directory exists
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = args.cache_dir / "UnicodeData.txt"

    # Download Unicode data if needed
    download_unicode_data(cache_file)

    # Generate Xcompose entries
    print(f"Generating Xcompose entries...")
    if args.limit:
        print(f"Limiting to code points below 0x{args.limit:X}")

    entry_count = 0
    with open(args.output, 'w', encoding='utf-8') as output_file:
        output_file.write("# Generated Unicode Xcompose configuration\n")
        output_file.write("# Use <Multi_key> <less> <hex_digits> <greater> to enter Unicode characters\n")
        output_file.write("# For example: <Multi_key> <less> <1> <5> <f> <a> <greater> for U+15FA\n\n")

        for code_point in parse_unicode_data(cache_file, args.limit):
            entry = generate_xcompose_entry(code_point)
            output_file.write(entry + "\n")
            entry_count += 1

            if entry_count % 10000 == 0:
                print(f"Generated {entry_count} entries...")

    print(f"Generated {entry_count} Xcompose entries in {args.output}")


if __name__ == "__main__":
    main()

