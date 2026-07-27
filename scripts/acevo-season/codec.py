"""AC EVO launch-blob wire format.

A blob is base64 of: 4-byte big-endian uncompressed-JSON length, then
zlib-deflated UTF-8 JSON. The server only needs our blob to *decode* to the
intended JSON; byte-identity with the GUI's output is neither required nor
attempted.
"""
import base64
import json
import struct
import zlib


def decode(blob: str) -> object:
    raw = base64.b64decode(blob)
    declared = struct.unpack(">I", raw[:4])[0]
    data = zlib.decompress(raw[4:])
    if len(data) != declared:
        raise ValueError(f"length prefix {declared} != actual {len(data)}")
    return json.loads(data)


def encode(obj: object) -> str:
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = struct.pack(">I", len(data)) + zlib.compress(data, 9)
    return base64.b64encode(payload).decode("ascii")
