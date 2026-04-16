"""Direct private key signer for EIP-712 signatures (no awp-wallet dependency)."""
from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from eth_account import Account
from eth_account.messages import encode_typed_data

try:
    from common import (
        DEFAULT_EIP712_CHAIN_ID,
        DEFAULT_EIP712_DOMAIN_NAME,
        DEFAULT_EIP712_VERIFYING_CONTRACT,
    )
except ImportError:
    DEFAULT_EIP712_CHAIN_ID = 8453
    DEFAULT_EIP712_DOMAIN_NAME = "aDATA"
    DEFAULT_EIP712_VERIFYING_CONTRACT = "0xAB41eE5C44D4568aD802D104A6dAB1Fe09C590D1"

try:
    from eip712_primitives import (
        EMPTY_HASH,
        DEFAULT_SIGNED_HEADERS,
        keccak_hex as _keccak_hex,
        hash_query as _hash_query,
        hash_headers as _hash_headers,
        hash_body as _hash_body,
    )
except ImportError:
    # Standalone fallback when eip712_primitives is not available
    import json
    from Crypto.Hash import keccak
    from urllib.parse import parse_qsl, quote_plus

    EMPTY_HASH = f"0x{'0' * 64}"
    DEFAULT_SIGNED_HEADERS = ("content-type",)

    def _keccak_hex(data):
        raw = data.encode("utf-8") if isinstance(data, str) else data
        d = keccak.new(digest_bits=256); d.update(raw)
        return "0x" + d.hexdigest()

    def _hash_query(url):
        split = urlsplit(url)
        pairs = sorted((quote_plus(k), quote_plus(v)) for k, v in parse_qsl(split.query, keep_blank_values=True))
        return EMPTY_HASH if not pairs else _keccak_hex("&".join(f"{k}={v}" for k, v in pairs))

    def _hash_headers(headers, signed_headers):
        lines = [f"{h}:{' '.join(str(headers.get(h) or '').strip().split())}" for h in sorted(signed_headers) if headers.get(h) is not None]
        return EMPTY_HASH if not lines else _keccak_hex("\n".join(lines))

    def _hash_body(body, content_type):
        if body is None: return EMPTY_HASH
        ct = str(content_type or "").lower()
        if "application/json" in ct:
            try: return _keccak_hex(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            except (TypeError, ValueError): pass
        if isinstance(body, (str, bytes)): return _keccak_hex(body)
        try: return _keccak_hex(json.dumps(body, ensure_ascii=False))
        except (TypeError, ValueError): return _keccak_hex(str(body))


class PrivateKeySigner:
    """EIP-712 signer using raw private key."""

    def __init__(self, private_key: str) -> None:
        self._account = Account.from_key(private_key)
        self._address = self._account.address

    @property
    def signer_address(self) -> str:
        return self._address

    def get_address(self) -> str:
        """Address accessor compatible with WalletSigner.get_address()."""
        return self._address

    def sign_typed_data(self, typed_data: dict[str, Any]) -> str:
        """Sign EIP-712 typed data and return signature."""
        signable = encode_typed_data(full_message=typed_data)
        signed = self._account.sign_message(signable)
        return signed.signature.hex()

    def build_typed_data(
        self,
        *,
        method: str,
        url: str,
        body: Any,
        content_type: str,
        now: int,
        nonce: int,
        chain_id: int = DEFAULT_EIP712_CHAIN_ID,
        domain_name: str = DEFAULT_EIP712_DOMAIN_NAME,
        domain_version: str = "1",
        verifying_contract: str = DEFAULT_EIP712_VERIFYING_CONTRACT,
        signed_headers: tuple[str, ...] = DEFAULT_SIGNED_HEADERS,
    ) -> dict[str, Any]:
        """Build EIP-712 typed data matching platform's APIRequest schema."""
        split = urlsplit(url)
        request_headers = {
            "content-type": content_type,
        }

        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "APIRequest": [
                    {"name": "method", "type": "string"},
                    {"name": "host", "type": "string"},
                    {"name": "path", "type": "string"},
                    {"name": "queryHash", "type": "bytes32"},
                    {"name": "headersHash", "type": "bytes32"},
                    {"name": "bodyHash", "type": "bytes32"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "issuedAt", "type": "uint256"},
                    {"name": "expiresAt", "type": "uint256"},
                ],
            },
            "primaryType": "APIRequest",
            "domain": {
                "name": domain_name,
                "version": domain_version,
                "chainId": chain_id,
                "verifyingContract": verifying_contract,
            },
            "message": {
                "method": method.upper(),
                "host": split.netloc,
                "path": split.path or "/",
                "queryHash": _hash_query(url),
                "headersHash": _hash_headers(request_headers, signed_headers),
                "bodyHash": _hash_body(body, content_type),
                "nonce": nonce,
                "issuedAt": now,
                "expiresAt": now + 300,
            },
        }

    def build_auth_headers(
        self,
        method: str,
        url: str,
        body: dict[str, Any] | None = None,
        *,
        content_type: str = "application/json",
        chain_id: int = DEFAULT_EIP712_CHAIN_ID,
        domain_name: str = DEFAULT_EIP712_DOMAIN_NAME,
        domain_version: str = "1",
        verifying_contract: str = DEFAULT_EIP712_VERIFYING_CONTRACT,
    ) -> dict[str, str]:
        """Build EIP-712 signed auth headers for API request."""
        now = int(time.time())
        nonce = secrets.randbits(52)  # 52-bit int, safe for all JSON parsers
        nonce_str = str(nonce)

        typed_data = self.build_typed_data(
            method=method,
            url=url,
            body=body,
            content_type=content_type,
            now=now,
            nonce=nonce,
            chain_id=chain_id,
            domain_name=domain_name,
            domain_version=domain_version,
            verifying_contract=verifying_contract,
        )
        signature = self.sign_typed_data(typed_data)
        message = typed_data["message"]

        return {
            "Content-Type": content_type,
            "X-Signer": self._address,
            "X-Signature": f"0x{signature}" if not signature.startswith("0x") else signature,
            "X-Nonce": nonce_str,
            "X-Issued-At": str(message["issuedAt"]),
            "X-Expires-At": str(message["expiresAt"]),
            "X-Chain-Id": str(chain_id),
            "X-Signed-Headers": ",".join(DEFAULT_SIGNED_HEADERS),
        }
