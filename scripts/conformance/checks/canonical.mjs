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

const INTEGER_TOKEN = /^-?(?:0|[1-9][0-9]*)$/;

/** Python's repr() of a float, which json.dumps uses: shortest round-trip digits, fixed notation for -4 <= exp10 < 16. */
export function pythonFloatRepr(value) {
  if (!Number.isFinite(value)) throw new CanonicalizationError("non-finite number");
  const negative = value < 0 || Object.is(value, -0);
  // toExponential() without an argument yields the shortest digits that round-trip.
  const [mantissa, exponentText] = Math.abs(value).toExponential().split("e");
  const exponent = Number(exponentText);
  const digits = mantissa.replace(".", "");
  let body;
  if (exponent >= -4 && exponent < 16) {
    if (exponent >= 0) {
      const whole = digits.padEnd(exponent + 1, "0");
      body = `${whole.slice(0, exponent + 1)}.${whole.slice(exponent + 1) || "0"}`;
    } else {
      body = `0.${"0".repeat(-exponent - 1)}${digits}`;
    }
  } else {
    const sign = exponent < 0 ? "-" : "+";
    body = `${digits[0]}${digits.length > 1 ? `.${digits.slice(1)}` : ""}e${sign}${String(Math.abs(exponent)).padStart(2, "0")}`;
  }
  return negative ? `-${body}` : body;
}

/**
 * Python's spelling of a number literal: an integer token must be canonical decimal (arbitrary
 * precision, no leading zeros, no "-0"); a float token must be repr() of the double it denotes.
 * Returns the canonical spelling, which differs from `text` when the token is not canonical.
 */
function pythonNumber(text) {
  if (INTEGER_TOKEN.test(text)) return BigInt(text).toString();
  return pythonFloatRepr(Number(text));
}

/**
 * python-json-v1 serialization of a value parsed with `number: rawNumber`. Every number is
 * re-spelled the way Python writes it, so a literal such as 0.950 or 1e5 yields different bytes
 * from a canonical file that contains it.
 */
export function serializePythonJsonV1(value) {
  return Buffer.from(pythonV1(value), "utf8");
}

function pythonV1(value) {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return JSON.stringify(checkString(value));
  if (value instanceof RawNumber) return pythonNumber(value.text);
  if (typeof value !== "object") throw new CanonicalizationError(`unsupported value of type ${typeof value}`);
  if (Array.isArray(value)) return `[${value.map(pythonV1).join(",")}]`;
  const members = Object.keys(value)
    .sort(compareCodePoints)
    .map((key) => `${JSON.stringify(checkString(key))}:${pythonV1(value[key])}`);
  return `{${members.join(",")}}`;
}
