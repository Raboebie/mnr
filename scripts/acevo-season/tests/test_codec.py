import base64
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codec import encode, decode


def test_semantic_round_trip():
    obj = {
        "name": "MNR | Monday Night Racing",
        "port": 34597,
        "cars": ["ferrari_296", "porsche_992"],
        "nested": {"temp": 24.5, "rain": 0.0, "enabled": True},
    }
    assert decode(encode(obj)) == obj


def test_length_prefix_is_uncompressed_length():
    obj = {"k": "v" * 5000}
    raw = base64.b64decode(encode(obj))
    declared = struct.unpack(">I", raw[:4])[0]
    expected = len(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    assert declared == expected


def test_decode_rejects_length_mismatch():
    data = json.dumps({"a": 1}).encode("utf-8")
    import zlib
    bad = base64.b64encode(struct.pack(">I", len(data) + 5) + zlib.compress(data)).decode("ascii")
    with pytest.raises(ValueError):
        decode(bad)
