from __future__ import annotations

import ast
import hashlib
import json
import operator
import re
from typing import Any

import httpx

from mine_gateway import resolve_mine_gateway_model_config


class UnsupportedChallenge(RuntimeError):
    def __init__(self, challenge_type: str, reason: str | None = None) -> None:
        msg = f"unsupported challenge type: {challenge_type}"
        if reason:
            msg = f"{msg} ({reason})"
        super().__init__(msg)


def solve_challenge(challenge: dict[str, Any]) -> str:
    challenge_type = str(challenge.get("question_type") or "unknown")
    if challenge_type == "content_understanding":
        return _solve_content_understanding(challenge)
    if challenge_type == "structured_extraction":
        return _solve_structured_extraction(challenge)
    if challenge_type in {"math", "arithmetic"}:
        expression = str(challenge.get("expression") or challenge.get("prompt") or "").strip()
        if not expression:
            raise UnsupportedChallenge(challenge_type)
        return str(_evaluate_math_expression(expression))
    if challenge_type in {"sha256_nonce", "hashcash"}:
        return _solve_sha256_nonce(challenge)
    if challenge_type == "hash_challenge":
        return _solve_hash_challenge(challenge)
    raise UnsupportedChallenge(challenge_type)


def _solve_content_understanding(challenge: dict[str, Any]) -> str:
    accepted = challenge.get("accepted_answer") or challenge.get("answer")
    if accepted:
        return str(accepted)
    prompt = str(challenge.get("prompt") or challenge.get("question") or "").strip()
    if not prompt:
        raise UnsupportedChallenge("content_understanding", "no prompt provided")
    extracted = _extract_answer_from_prompt(prompt)
    if extracted:
        return extracted
    return _llm_answer(prompt)


def _extract_answer_from_prompt(prompt: str) -> str | None:
    """Extract the answer keyword given directly in a PoW prompt (e.g. "输出 generic-ready 作为...")."""
    m = re.search(r"输出\s+(\S+)\s+作为", prompt)
    if m:
        return m.group(1)
    m = re.search(r"output\s+(\S+)\s+as\b", prompt, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _solve_structured_extraction(challenge: dict[str, Any]) -> str:
    content = str(challenge.get("content") or challenge.get("text") or "").strip()
    schema = challenge.get("schema") or challenge.get("fields")
    if not content:
        raise UnsupportedChallenge("structured_extraction", "no content provided")
    if not schema:
        raise UnsupportedChallenge("structured_extraction", "no schema provided")
    schema_str = json.dumps(schema, ensure_ascii=False) if isinstance(schema, (dict, list)) else str(schema)
    prompt = (
        f"Extract structured data from the following content according to this schema:\n\n"
        f"Schema: {schema_str}\n\n"
        f"Content:\n{content}\n\n"
        f"Return ONLY valid JSON matching the schema, no explanation."
    )
    return _llm_answer(prompt)


def _llm_answer(prompt: str) -> str:
    config = resolve_mine_gateway_model_config()
    if not config:
        raise UnsupportedChallenge("llm", "gateway not available")
    base_url = str(config.get("base_url") or "").rstrip("/")
    api_key = str(config.get("api_key") or "")
    model = str(config.get("model") or "")
    if not base_url or not api_key or not model:
        raise UnsupportedChallenge("llm", "incomplete gateway config")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}
    if config.get("openclaw_model"):
        payload["openclaw_model"] = config["openclaw_model"]
    resp = httpx.post(f"{base_url}/chat/completions", json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()


def _solve_hash_challenge(challenge: dict[str, Any]) -> str:
    """Solve dynamic SHA256 hash challenge from the submission gate.

    The server generates a random nonce and expects:
    SHA256(nonce) -> first 8 hex characters (first 4 bytes).
    """
    validation_meta = challenge.get("validation_meta") or {}
    nonce = str(validation_meta.get("nonce") or "").strip()
    if not nonce:
        # Fallback: extract nonce from prompt
        prompt = str(challenge.get("prompt") or "")
        import re
        m = re.search(r'SHA256\("([^"]+)"\)', prompt)
        if m:
            nonce = m.group(1)
    if not nonce:
        raise UnsupportedChallenge("hash_challenge", "no nonce found in challenge")
    digest = hashlib.sha256(nonce.encode("utf-8")).digest()
    return digest[:4].hex()


def _solve_sha256_nonce(challenge: dict[str, Any]) -> str:
    prefix = str(challenge.get("prefix") or "")
    if not prefix:
        difficulty = int(challenge.get("difficulty") or 0)
        prefix = "0" * max(0, difficulty)
    seed = str(challenge.get("input") or challenge.get("seed") or challenge.get("prompt") or "")
    separator = str(challenge.get("separator") or "")
    max_nonce = max(1, int(challenge.get("max_nonce") or 100_000))

    for nonce in range(max_nonce + 1):
        candidate = (
            seed.replace("{nonce}", str(nonce))
            if "{nonce}" in seed
            else f"{seed}{separator}{nonce}"
        )
        digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()
        if digest.startswith(prefix):
            answer_format = str(challenge.get("answer_format") or "nonce")
            if answer_format == "candidate":
                return candidate
            return str(nonce)
    raise UnsupportedChallenge(str(challenge.get("question_type") or "sha256_nonce"))


def _evaluate_math_expression(expression: str) -> int:
    tree = ast.parse(expression, mode="eval")
    return int(_eval_node(tree.body))


MAX_EXPONENT = 1000  # Prevent memory exhaustion from expressions like 2**999999999


def _safe_pow(base: int | float, exp: int | float) -> int | float:
    """Power operation with exponent limit to prevent memory exhaustion."""
    if isinstance(exp, (int, float)) and abs(exp) > MAX_EXPONENT:
        raise ValueError(f"exponent {exp} exceeds maximum allowed ({MAX_EXPONENT})")
    return operator.pow(base, exp)


def _eval_node(node: ast.AST) -> int | float:
    binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: _safe_pow,  # Use safe version with exponent limit
    }
    unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in binary_ops:
        return binary_ops[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in unary_ops:
        return unary_ops[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported math expression")
