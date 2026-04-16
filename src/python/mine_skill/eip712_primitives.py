"""Shared EIP-712 hash primitives used by both WalletSigner and PrivateKeySigner.

Single source of truth for body/query/header hashing. Both signers import
from this module to guarantee identical output for the same input.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qsl, quote_plus, urlsplit

from Crypto.Hash import keccak

EMPTY_HASH = f"0x{'0' * 64}"
DEFAULT_SIGNED_HEADERS = ("content-type",)


def normalize_header_value(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def keccak_hex(data: str | bytes) -> str:
    """keccak256 hash of non-empty data."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    digest = keccak.new(digest_bits=256)
    digest.update(raw)
    return "0x" + digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_query(url: str) -> str:
    split = urlsplit(url)
    pairs = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        pairs.append((quote_plus(key), quote_plus(value)))
    if not pairs:
        return EMPTY_HASH
    pairs.sort()
    return keccak_hex("&".join(f"{key}={value}" for key, value in pairs))


def hash_headers(headers: dict[str, str], signed_headers: tuple[str, ...]) -> str:
    lines = []
    for header_name in sorted(signed_headers):
        value = headers.get(header_name)
        if value is None:
            continue
        lines.append(f"{header_name}:{normalize_header_value(value)}")
    if not lines:
        return EMPTY_HASH
    return keccak_hex("\n".join(lines))


def canonical_body(body: Any, content_type: str) -> str | bytes | None:
    if body is None:
        return None
    normalized_type = str(content_type or "").lower()
    if "application/json" in normalized_type:
        try:
            return canonical_json(body)
        except (TypeError, ValueError):
            pass
    if isinstance(body, str):
        return body
    if isinstance(body, bytes):
        return body
    try:
        return json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(body)


def hash_body(body: Any, content_type: str) -> str:
    cb = canonical_body(body, content_type)
    if cb is None:
        return EMPTY_HASH
    return keccak_hex(cb)
