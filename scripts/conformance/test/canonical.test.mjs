import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { CanonicalizationError, canonicalizeRfc8785, serializePythonJsonV1 } from "../checks/canonical.mjs";
import { parseJson, rawNumber } from "../checks/json.mjs";

// Vectors shared with the Python packages: RFC 8785 Appendix B numbers, the RFC's structure
// examples, and inputs a canonicalizer must reject. Expected strings were produced by Node.js.
const vectors = JSON.parse(readFileSync(fileURLToPath(new URL("./jcs_vectors.json", import.meta.url)), "utf8"));
const canonical = (text) => canonicalizeRfc8785(parseJson(text)).toString("utf8");

test("RFC 8785 number serialization", () => {
  assert.equal(vectors.numbers.length, 647);
  for (const { ieee754, expected } of vectors.numbers) {
    const view = new DataView(new ArrayBuffer(8));
    view.setBigUint64(0, BigInt(`0x${ieee754}`));
    const value = view.getFloat64(0);
    if (!Number.isFinite(value)) continue;
    assert.equal(canonicalizeRfc8785(value).toString("utf8"), expected, ieee754);
  }
});

test("RFC 8785 structures", () => {
  assert.equal(vectors.structures.length, 4);
  for (const { input, expected } of vectors.structures) assert.equal(canonical(input), expected);
});

test("RFC 8785 rejects what I-JSON forbids", () => {
  for (const input of vectors.rejected) {
    assert.throws(() => canonical(input), CanonicalizationError, input);
  }
  assert.throws(() => canonicalizeRfc8785(NaN), CanonicalizationError);
  assert.throws(() => canonicalizeRfc8785(Infinity), CanonicalizationError);
  assert.throws(() => canonicalizeRfc8785(undefined), CanonicalizationError);
});

test("RFC 8785 orders keys by UTF-16 code unit, not code point", () => {
  // U+FF5E sorts after U+1F600 by code point but before it by UTF-16 code units (D83D < FF5E).
  assert.equal(canonical('{"\\uff5e":1,"\\ud83d\\ude00":2}'), '{"\ud83d\ude00":2,"\uff5e":1}');
});

test("python-json-v1 serialization orders keys by code point and keeps number literals", () => {
  const text = '{"\u{1F600}":2.50,"\uff5e":1e-07,"b":[true,null,"\\u0007\\u007f\u00e9"],"a":{}}';
  const value = parseJson(text, { number: rawNumber });
  assert.equal(
    serializePythonJsonV1(value).toString("utf8"),
    '{"a":{},"b":[true,null,"\\u0007\u007f\u00e9"],"\uff5e":1e-07,"\u{1F600}":2.50}',
  );
});

test("python-json-v1 differs from RFC 8785 only where documented", () => {
  const value = parseJson('{"x":[1,2],"a":"\u00e9"}', { number: rawNumber });
  assert.equal(serializePythonJsonV1(value).toString("utf8"), canonical('{"x":[1,2],"a":"\u00e9"}'));
});
