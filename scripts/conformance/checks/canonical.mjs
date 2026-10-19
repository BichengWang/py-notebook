// Independent canonicalizers for the two canonical forms the records use.
//
//   rfc8785        JSON Canonicalization Scheme (RFC 8785): members sorted by UTF-16 code
//                  units, ECMAScript number and string serialization, no whitespace.
//                  JSON.stringify already implements the required number and string forms.
//   python-json-v1 json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
//                  as UTF-8: members sorted by code point.

import { RawNumber } from "./json.mjs";

export class CanonicalizationError extends Error {
  constructor(message) {
    super(message);
    this.name = "CanonicalizationError";
  }
}

function checkString(value) {
  if (!value.isWellFormed()) throw new CanonicalizationError("string contains a lone surrogate");
  return value;
}

/** RFC 8785 canonical form of a parsed JSON value, as UTF-8 bytes. */
export function canonicalizeRfc8785(value) {
  return Buffer.from(jcs(value), "utf8");
}

function jcs(value) {
  if (value === null) return "null";
  switch (typeof value) {
    case "boolean":
      return value ? "true" : "false";
    case "number":
      if (!Number.isFinite(value)) throw new CanonicalizationError("non-finite number");
      return JSON.stringify(value);
    case "bigint":
      throw new CanonicalizationError(`integer ${value} is outside the I-JSON range +-(2^53-1)`);
    case "string":
      return JSON.stringify(checkString(value));
    case "object":
      break;
    default:
      throw new CanonicalizationError(`unsupported value of type ${typeof value}`);
  }
  if (value instanceof RawNumber) throw new CanonicalizationError("raw number literals cannot be canonicalized");
  if (Array.isArray(value)) return `[${value.map(jcs).join(",")}]`;
  // The default sort compares UTF-16 code units, which is what RFC 8785 section 3.2.3 requires.
  const members = Object.keys(value).sort().map((key) => `${JSON.stringify(checkString(key))}:${jcs(value[key])}`);
  return `{${members.join(",")}}`;
}

function compareCodePoints(a, b) {
  const left = Array.from(a, (char) => char.codePointAt(0));
  const right = Array.from(b, (char) => char.codePointAt(0));
  const length = Math.min(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    if (left[index] !== right[index]) return left[index] - right[index];
  }
  return left.length - right.length;
}

/**
 * python-json-v1 serialization of a value parsed with `number: rawNumber`, so each number keeps
 * the literal the Python writer produced (float formatting is not re-derived here: the digest and
 * the deep comparison cover the values, this covers key order, separators and string escapes).
 */
export function serializePythonJsonV1(value) {
  return Buffer.from(pythonV1(value), "utf8");
}

function pythonV1(value) {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(checkString(value));
  if (value instanceof RawNumber) return value.text;
  if (typeof value !== "object") throw new CanonicalizationError(`unsupported value of type ${typeof value}`);
  if (Array.isArray(value)) return `[${value.map(pythonV1).join(",")}]`;
  const members = Object.keys(value)
    .sort(compareCodePoints)
    .map((key) => `${JSON.stringify(checkString(key))}:${pythonV1(value[key])}`);
  return `{${members.join(",")}}`;
}
