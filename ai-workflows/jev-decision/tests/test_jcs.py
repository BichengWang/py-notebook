import json
import struct
import unittest
from pathlib import Path

from jevdecision.jcs import canonicalize

VECTORS = json.loads((Path(__file__).with_name("jcs_vectors.json")).read_text(encoding="utf-8"))


class CanonicalizeTests(unittest.TestCase):
    def test_every_number_vector(self):
        self.assertGreater(len(VECTORS["numbers"]), 600)
        for vector in VECTORS["numbers"]:
            value = struct.unpack(">d", bytes.fromhex(vector["ieee754"]))[0]
            with self.subTest(ieee754=vector["ieee754"]):
                self.assertEqual(canonicalize(value).decode("utf-8"), vector["expected"])

    def test_structure_vectors(self):
        for vector in VECTORS["structures"]:
            with self.subTest(input=vector["input"][:40]):
                self.assertEqual(canonicalize(json.loads(vector["input"])).decode("utf-8"), vector["expected"])

    def test_rejected_inputs(self):
        for text in VECTORS["rejected"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                canonicalize(json.loads(text))

    def test_non_finite_numbers_and_foreign_types_are_rejected(self):
        for value in (float("nan"), float("inf"), -float("inf"), {1: "x"}, object(), {"a": {2}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonicalize(value)


if __name__ == "__main__":
    unittest.main()
