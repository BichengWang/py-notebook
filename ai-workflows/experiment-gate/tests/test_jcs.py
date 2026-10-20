"""RFC 8785 canonicalization against vectors produced by an independent implementation."""
import json
import struct
import unittest
from pathlib import Path

from expgate.jcs import canonicalize

VECTORS = json.loads((Path(__file__).with_name("jcs_vectors.json")).read_text(encoding="utf-8"))


class JcsVectorTest(unittest.TestCase):
    def test_numbers_match_the_vectors(self):
        self.assertEqual(len(VECTORS["numbers"]), 647)
        for vector in VECTORS["numbers"]:
            value = struct.unpack(">d", bytes.fromhex(vector["ieee754"]))[0]
            with self.subTest(ieee754=vector["ieee754"]):
                self.assertEqual(canonicalize(value).decode("utf-8"), vector["expected"])

    def test_structures_match_the_vectors(self):
        self.assertEqual(len(VECTORS["structures"]), 4)
        for vector in VECTORS["structures"]:
            with self.subTest(input=vector["input"][:40]):
                self.assertEqual(canonicalize(json.loads(vector["input"])).decode("utf-8"), vector["expected"])

    def test_rejected_inputs_raise_value_error(self):
        self.assertEqual(len(VECTORS["rejected"]), 5)
        for text in VECTORS["rejected"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                canonicalize(json.loads(text))

    def test_non_finite_numbers_and_foreign_types_raise_value_error(self):
        for value in (float("nan"), float("inf"), -float("inf"), {1: "x"}, {"a": {1, 2}}, b"x", object()):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                canonicalize(value)

    def test_integral_floats_and_integers_agree(self):
        self.assertEqual(canonicalize({"a": 2.0, "b": 2, "c": -0.0}), b'{"a":2,"b":2,"c":0}')

    def test_keys_sort_by_utf16_code_units(self):
        # U+FF5E sorts before an astral character in code points but after it in UTF-16.
        self.assertEqual(canonicalize({"\uff5e": 1, "\U0001f600": 2}).decode("utf-8"),
                         '{"\U0001f600":2,"\uff5e":1}')


if __name__ == "__main__":
    unittest.main()
