import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { CanonicalizationError, canonicalizeRfc8785, pythonFloatRepr, serializePythonJsonV1 } from "../checks/canonical.mjs";
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

test("python-json-v1 serialization orders keys by code point and re-spells numbers as Python does", () => {
  const text = '{"\u{1F600}":2.50,"\uff5e":1e-07,"b":[true,null,"\\u0007\\u007f\u00e9"],"a":{}}';
  const value = parseJson(text, { number: rawNumber });
  assert.equal(
    serializePythonJsonV1(value).toString("utf8"),
    '{"a":{},"b":[true,null,"\\u0007\u007f\u00e9"],"\uff5e":1e-07,"\u{1F600}":2.5}',
  );
});

test("python-json-v1 differs from RFC 8785 only where documented", () => {
  const value = parseJson('{"x":[1,2],"a":"\u00e9"}', { number: rawNumber });
  assert.equal(serializePythonJsonV1(value).toString("utf8"), canonical('{"x":[1,2],"a":"\u00e9"}'));
});

const python = (code) => JSON.parse(execFileSync("python3", ["-c", code], { encoding: "utf8", maxBuffer: 1 << 26 }));
const spell = (text) => serializePythonJsonV1(parseJson(text, { number: rawNumber })).toString("utf8");

test("python-json-v1 number spelling: tokens Python never writes change the bytes", () => {
  for (const token of ["0.950", "1.50", "15e-1", "1E5", "1e5", "1e+5", "100000.0e0", "5.00", "1e-07", "1e+16", "0.0", "-0.0"]) {
    const canonicalSpelling = spell(`[${token}]`) === `[${token}]`;
    assert.equal(canonicalSpelling, ["1e-07", "1e+16", "0.0", "-0.0"].includes(token), token);
  }
  for (const token of ["0.95", "5.0", "1e-07", "1.5e+16", "1e+22", "123456789012345.0", "0.0001", "1e-05", "-0.0", "-2.5"]) {
    assert.equal(spell(`[${token}]`), `[${token}]`, token);
  }
  for (const token of ["-0"]) {
    assert.notEqual(spell(`[${token}]`), `[${token}]`, token);
  }
  assert.equal(spell("[0]"), "[0]");
  assert.equal(spell("[-7]"), "[-7]");
  assert.equal(spell("[123456789012345678901234567890]"), "[123456789012345678901234567890]");
  assert.throws(() => spell("[1e999]"), CanonicalizationError);
});

test("pythonFloatRepr agrees with Python's repr on 6000 doubles", () => {
  // Python writes its own repr of each double; Node parses it back exactly and re-spells it.
  const reprs = python(`
import json, math, random, struct
rng = random.Random(8785)
out = []
while len(out) < 3000:
    x = struct.unpack(">d", rng.getrandbits(64).to_bytes(8, "big"))[0]
    if math.isfinite(x):
        out.append(x)
for _ in range(1500):
    out.append(rng.uniform(-1000, 1000))
for _ in range(1500):
    out.append(float(rng.randint(-10**18, 10**18)) * 10.0 ** rng.randint(-25, 25))
out += [0.0, -0.0, 1.0, 0.1, 0.95, 1e15, 1e16, 9999999999999998.0, 1e-4, 1e-5, 1.5e300, 5e-324, 1.7976931348623157e308, 123456789012345680.0]
print(json.dumps([repr(x) for x in out]))
`);
  assert.ok(reprs.length >= 6000);
  for (const text of reprs) assert.equal(pythonFloatRepr(Number(text)), text);
});
