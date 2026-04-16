"""EIP-712 signing via awp-wallet CLI subprocess.

Since awp-wallet v1.4.0, the --token parameter is optional — plaintext
wallets don't need session auth. This signer no longer manages session
tokens; it calls awp-wallet directly without --token.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlsplit

from common import (
    DEFAULT_EIP712_CHAIN_ID,
    DEFAULT_EIP712_DOMAIN_NAME,
    DEFAULT_EIP712_VERIFYING_CONTRACT,
)

from eip712_primitives import (
    DEFAULT_SIGNED_HEADERS,
    keccak_hex as _keccak_hex,
    hash_query as _hash_query,
    hash_headers as _hash_headers,
    hash_body as _hash_body,
)


class WalletSigner:
    """Bridge to awp-wallet CLI for EIP-712 request signing.

    awp-wallet v1.4.0+: --token is optional, signing works without session.
    awp-wallet < v1.4.0: --token is required, falls back to token-based flow
                         with auto-renew on expiry.
    """

    def __init__(self, wallet_bin: str = "awp-wallet", session_token: str = "") -> None:
        self._bin = wallet_bin
        self._token = session_token
        self._signer_address: str | None = None
        self._token_optional: bool | None = None  # lazy-detected

    @property
    def session_token(self) -> str:
        return self._token

    def _run(self, *args: str) -> dict[str, Any]:
        import subprocess
        cmd = [self._bin, *args]
        env = os.environ.copy()
        if not env.get("HOME") and env.get("USERPROFILE"):
            env["HOME"] = env["USERPROFILE"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=env)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(f"awp-wallet failed (exit {result.returncode}): {stderr}")
        return json.loads(result.stdout)

    def get_address(self) -> str:
        if self._signer_address is None:
            resp = self._run("receive")
            addr = resp.get("address") or resp.get("eoaAddress") or ""
            if not addr:
                addresses = resp.get("addresses")
                if isinstance(addresses, list) and addresses:
                    first = addresses[0]
                    if isinstance(first, dict):
                        addr = first.get("address", "") or first.get("eoaAddress", "")
            if not addr:
                raise RuntimeError("awp-wallet receive did not return an address")
            self._signer_address = addr
        return self._signer_address

    def _is_token_optional(self) -> bool:
        """Detect whether awp-wallet supports tokenless signing (v1.4.0+)."""
        if self._token_optional is not None:
            return self._token_optional
        import re
        import subprocess
        try:
            result = subprocess.run(
                [self._bin, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            # Output may be "1.4.0", "v1.4.0", "awp-wallet 1.4.0", etc.
            m = re.search(r"(\d+)\.(\d+)", result.stdout.strip())
            if m:
                major, minor = int(m.group(1)), int(m.group(2))
                # v0.17.0+ and v1.4.0+ support optional token
                self._token_optional = (major, minor) >= (1, 4) or (major == 0 and minor >= 17)
            else:
                self._token_optional = False
        except Exception:
            self._token_optional = False
        return self._token_optional

    def sign_typed_data(self, typed_data: dict[str, Any]) -> str:
        """Sign EIP-712 typed data.

        v1.4.0+: no --token needed.
        < v1.4.0: uses --token with auto-renew on expiry.
        """
        data_json = json.dumps(typed_data, separators=(",", ":"))

        if self._is_token_optional():
            # v1.4.0+: 不需要 token
            resp = self._run("sign-typed-data", "--data", data_json)
        else:
            # 旧版: 需要 --token，过期时自动续签
            try:
                resp = self._run(
                    "sign-typed-data", "--token", self._token, "--data", data_json,
                )
            except RuntimeError as exc:
                err_msg = str(exc).lower()
                if "expired" not in err_msg and "invalid" not in err_msg:
                    raise
                self.renew_session()
                resp = self._run(
                    "sign-typed-data", "--token", self._token, "--data", data_json,
                )

        sig = resp.get("signature", "")
        if not sig:
            raise RuntimeError("awp-wallet sign-typed-data returned empty signature")
        return sig

    def renew_session(self, *, duration_seconds: int = 86400) -> dict[str, int | str]:
        """Renew wallet session. Kept for backward compat but no longer
        required for signing since v1.4.0."""
        from common import WALLET_SESSION_DURATION_SECONDS, persist_wallet_session
        issued_at = int(time.time())
        resp = self._run("unlock", "--duration", str(max(1, duration_seconds)), "--scope", "full")
        session_token = str(resp.get("sessionToken") or "").strip()
        if not session_token:
            raise RuntimeError("awp-wallet unlock did not return sessionToken")
        self._token = session_token
        os.environ["AWP_WALLET_TOKEN"] = session_token
        expires_at = issued_at + max(1, duration_seconds)
        os.environ["AWP_WALLET_TOKEN_EXPIRES_AT"] = str(expires_at)
        persist_wallet_session(session_token, expires_at=expires_at)
        return {
            "session_token": session_token,
            "issued_at": issued_at,
            "expires_at": expires_at,
        }

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
        body: Any = None,
        *,
        content_type: str = "application/json",
        chain_id: int = DEFAULT_EIP712_CHAIN_ID,
        domain_name: str = DEFAULT_EIP712_DOMAIN_NAME,
        domain_version: str = "1",
        verifying_contract: str = DEFAULT_EIP712_VERIFYING_CONTRACT,
    ) -> dict[str, str]:
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
            "X-Signer": self.get_address(),
            "X-Signature": signature if signature.startswith("0x") else f"0x{signature}",
            "X-Nonce": nonce_str,
            "X-Issued-At": str(message["issuedAt"]),
            "X-Expires-At": str(message["expiresAt"]),
            "X-Chain-Id": str(chain_id),
            "X-Signed-Headers": ",".join(DEFAULT_SIGNED_HEADERS),
        }
