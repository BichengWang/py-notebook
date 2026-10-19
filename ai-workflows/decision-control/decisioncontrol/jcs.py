"""RFC 8785 JSON Canonicalization Scheme (JCS), standard library only.

Numbers are serialized as IEEE 754 doubles in ECMAScript Number.prototype.toString
form; integers must be within the I-JSON safe range. Object members are sorted by
UTF-16 code units. Strings must not contain lone surrogates. NaN and infinities
are rejected.
"""
import json
import math

SAFE_INTEGER = 2**53 - 1


def canonicalize(value: object) -> bytes:
    """Return the RFC 8785 canonical UTF-8 bytes of a JSON value."""
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts).encode("utf-8")


def _write(value: object, parts: list[str]) -> None:
    if value is None:
        parts.append("null")
    elif value is True:
        parts.append("true")
    elif value is False:
        parts.append("false")
    elif isinstance(value, int):
        if abs(value) > SAFE_INTEGER:
            raise ValueError(f"integer outside the I-JSON safe range: {value}")
        parts.append(_number(float(value)))
    elif isinstance(value, float):
        parts.append(_number(value))
    elif isinstance(value, str):
        parts.append(_string(value))
    elif isinstance(value, (list, tuple)):
        parts.append("[")
        for index, item in enumerate(value):
            if index:
                parts.append(",")
            _write(item, parts)
        parts.append("]")
    elif isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise ValueError(f"object key is not a string: {key!r}")
        parts.append("{")
        for index, key in enumerate(sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))):
            if index:
                parts.append(",")
            parts.append(_string(key))
            parts.append(":")
            _write(value[key], parts)
        parts.append("}")
    else:
        raise ValueError(f"not a JSON value: {type(value).__name__}")


def _string(text: str) -> str:
    if any(0xD800 <= ord(char) <= 0xDFFF for char in text):
        raise ValueError("string contains a lone surrogate")
    return json.dumps(text, ensure_ascii=False)


def _number(value: float) -> str:
    if not math.isfinite(value):
        raise ValueError(f"non-finite number: {value}")
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exponent_text = repr(abs(value)).partition("e")
    whole, _, fraction = mantissa.partition(".")
    raw = whole + fraction
    digits = raw.lstrip("0")
    point = len(whole) - (len(raw) - len(digits)) + (int(exponent_text) if exponent_text else 0)
    digits = digits.rstrip("0")
    count = len(digits)
    if count <= point <= 21:
        text = digits + "0" * (point - count)
    elif 0 < point <= 21:
        text = digits[:point] + "." + digits[point:]
    elif -6 < point <= 0:
        text = "0." + "0" * -point + digits
    else:
        exponent = point - 1
        head = digits if count == 1 else digits[0] + "." + digits[1:]
        text = f"{head}e{'+' if exponent >= 0 else '-'}{abs(exponent)}"
    return sign + text
