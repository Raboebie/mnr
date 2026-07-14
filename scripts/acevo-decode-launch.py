#!/usr/bin/env python3
"""Decode AC EVO server launch blobs.

The AC EVO dedicated server takes its whole config on the command line:

    AssettoCorsaEVOServer.exe -serverconfig <blob> -seasondefinition <blob>

Each blob is base64 of: 4-byte big-endian uncompressed length, then zlib-deflated
JSON. This prints the JSON back out.

Usage:
    acevo-decode-launch.py <blob> [<blob> ...]
    acevo-decode-launch.py --bat ac_evo_launch.bat
    cat ac_evo_launch.bat | acevo-decode-launch.py -
"""

import argparse
import base64
import json
import re
import struct
import sys
import zlib

# -serverconfig AAACoXic...  /  -seasondefinition AAACvHic...
ARG_RE = re.compile(r"-(serverconfig|seasondefinition)\s+([A-Za-z0-9+/=]+)")


def decode(blob: str):
    raw = base64.b64decode(blob)
    declared = struct.unpack(">I", raw[:4])[0]
    data = zlib.decompress(raw[4:])
    if len(data) != declared:
        print(
            f"warning: length prefix says {declared}, got {len(data)}",
            file=sys.stderr,
        )
    return json.loads(data)


def emit(name: str, blob: str) -> None:
    try:
        print(f"===== {name} =====")
        print(json.dumps(decode(blob), indent=2))
        print()
    except Exception as exc:
        print(f"{name}: failed to decode: {exc}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("blobs", nargs="*", help="base64 blob(s), or - to read stdin")
    ap.add_argument("--bat", help="a launch .bat/.cmd to scrape blobs out of")
    args = ap.parse_args()

    text = None
    if args.bat:
        with open(args.bat, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    elif args.blobs == ["-"]:
        text = sys.stdin.read()

    if text is not None:
        found = ARG_RE.findall(text)
        if not found:
            print("no -serverconfig/-seasondefinition blobs found", file=sys.stderr)
            return 1
        for name, blob in found:
            emit(name, blob)
        return 0

    if not args.blobs:
        ap.print_help()
        return 1

    for i, blob in enumerate(args.blobs, 1):
        emit(f"blob {i}", blob)
    return 0


if __name__ == "__main__":
    sys.exit(main())
