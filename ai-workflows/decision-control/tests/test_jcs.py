"""RFC 8785 conformance of the bundled canonicalizer against the shared vectors."""
import json
from pathlib import Path
import struct
import unittest

from decisioncontrol.jcs import canonicalize

VECTORS = json.loads((Path(__file__).parent / "jcs_vectors.json").read_text(encoding="utf-8"))


class JcsVectorTests(unittest.TestCase):
    def test_every_number_matches_the_expected_text(self):
        self.assertGreaterEqual(len(VECTORS["numbers"]), 600)
        for vector in VECTORS["numbers"]:
            value = struct.unpack(">d", bytes.fromhex(vector["ieee754"]))[0]
            with self.subTest(ieee754=vector["ieee754"]):
                self.assertEqual(canonicalize(value), vector["expected"].encode("utf-8"))

    def test_structures_are_canonicalized_byte_for_byte(self):
        self.assertGreaterEqual(len(VECTORS["structures"]), 4)
        for index, vector in enumerate(VECTORS["structures"]):
            with self.subTest(index=index):
                self.assertEqual(canonicalize(json.loads(vector["input"])), vector["expected"].encode("utf-8"))

    def test_rejected_inputs_raise_value_error(self):
        self.assertGreaterEqual(len(VECTORS["rejected"]), 5)
        for text in VECTORS["rejected"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                canonicalize(json.loads(text))

    def test_non_finite_and_non_json_values_are_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), {1: "x"}, {"x": object()}, b"bytes", {"a": {1, 2}}):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                canonicalize(value)

    def test_keys_sort_by_utf16_code_units(self):
        self.assertEqual(canonicalize({"\ue000": 1, "\U00010000": 2}), '{"\U00010000":2,"\ue000":1}'.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
