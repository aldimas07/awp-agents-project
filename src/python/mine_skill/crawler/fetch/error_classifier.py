"""Classify fetch errors into structured categories for agent decision-making."""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx


@dataclass(frozen=True, slots=True)
class FetchError:
    error_code: str       # e.g. "RATE_LIMITED", "AUTH_EXPIRED"
    agent_hint: str       # e.g. "wait_and_retry", "refresh_session"
    message: str          # human-readable description
    retryable: bool
    status_code: int | None = None


def classify_http_error(exc: Exception) -> FetchError:
    """Classify an httpx exception into a structured FetchError."""
    message = str(exc)
    lower_message = message.lower()

    if "err_too_many_redirects" in lower_message or "ns_error_redirect_loop" in lower_message:
        return FetchError(
            "AUTH_EXPIRED",
            "refresh_session",
            "Redirect loop or login wall detected",
            True,
        )

    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        request_url = str(getattr(exc.request, "url", "") or "")
        response_url = str(getattr(exc.response, "url", "") or "")
        joined_url = f"{request_url} {response_url}".lower()
        if code == 429:
            return FetchError("RATE_LIMITED", "wait_and_retry",
                              "Rate limit hit", True, code)
        if code in (401, 403):
            return FetchError("AUTH_EXPIRED", "refresh_session",
                              f"Auth failed ({code})", True, code)
        if code == 451:
            if "linkedin" in joined_url:
                return FetchError(
                    "LEGAL_RESTRICTED",
                    "switch_network_region",
                    "LinkedIn endpoint blocked by regional or legal restrictions",
                    False,
                    code,
                )
            return FetchError("LEGAL_RESTRICTED", "notify_user",
                              "Endpoint blocked for legal reasons", False, code)
        if code == 404:
            return FetchError("PAGE_NOT_FOUND", "skip",
                              "Page not found", False, code)
        if 500 <= code < 600:
            return FetchError("SERVER_ERROR", "retry_later",
                              f"Server error ({code})", True, code)

    if isinstance(exc, httpx.TimeoutException):
        return FetchError("NETWORK_ERROR", "retry",
                          "Request timed out", True)

    if isinstance(exc, httpx.ConnectError):
        return FetchError("NETWORK_ERROR", "retry",
                          "Connection failed", True)

    return FetchError("UNKNOWN_ERROR", "inspect", str(exc), True)


def classify_content(html: str | None, final_url: str) -> FetchError | None:
    """Detect content-level issues in a fetched page."""
    lower_final_url = final_url.lower()
    lower = (html or "").lower()
    # LinkedIn China flow: phone + real-name verification.
    # The Chinese strings below are functional UI text matches:
    # "添加电话号码" = "Add phone number", "实名认证" = "Real-name verification"
    if "/check/china/add-phone" in lower_final_url or (
        "添加电话号码" in (html or "")
        and "实名认证" in (html or "")
    ):
        return FetchError(
            "AUTH_PHONE_REQUIRED",
            "complete_phone_verification",
            "LinkedIn requires phone verification before access",
            False,
        )

    if html is None or len(html) < 200:
        return FetchError("CONTENT_EMPTY", "retry_with_browser",
                          "Page body is empty or too short", True)

    if "authwall" in lower or "/login" in final_url or "/checkpoint" in final_url:
        return FetchError("AUTH_EXPIRED", "refresh_session",
                          "Hit auth wall or login redirect", True)

    if re.search(r"captcha|robot check", lower):
        return FetchError("CAPTCHA", "escalate_backend",
                          "Captcha or robot check detected — will try next backend", True)

    if _looks_like_amazon_real_product_page(lower, final_url):
        return None

    if (
        _looks_like_amazon_product_shell(lower, final_url)
        or _looks_like_amazon_incomplete_twister_page(lower, final_url)
        or _looks_like_amazon_signed_out_recommendation_shell(lower, final_url)
    ):
        return FetchError("CONTENT_PARTIAL", "retry_with_browser",
                          "Amazon product page returned a shell page without product details", True)

    return None


def _looks_like_amazon_product_shell(lower_html: str, final_url: str) -> bool:
    lower_url = final_url.lower()
    if "amazon." not in lower_url:
        return False
    if "/dp/" not in lower_url and "/gp/product/" not in lower_url:
        return False

    has_generic_amazon_title = (
        '<meta property="og:title" content="amazon"' in lower_html
        or "<title>amazon</title>" in lower_html
        or '<meta property="og:description" content="amazon"' in lower_html
    )
    has_product_markers = any(
        marker in lower_html
        for marker in (
            'id="producttitle"',
            'id="feature-bullets"',
            'id="acrcustomerreviewtext"',
            'id="bylineinfo"',
            'id="coreprice',
        )
    )
    has_shell_marker = "previewdoh/amazon.png" in lower_html or 'id="page-shell"' in lower_html
    return has_generic_amazon_title and has_shell_marker and not has_product_markers


def _looks_like_amazon_incomplete_twister_page(lower_html: str, final_url: str) -> bool:
    lower_url = final_url.lower()
    if "amazon." not in lower_url:
        return False
    if "/dp/" not in lower_url and "/gp/product/" not in lower_url:
        return False

    has_product_markers = any(
        marker in lower_html
        for marker in (
            'id="producttitle"',
            'id="feature-bullets"',
            'id="bylineinfo"',
        )
    )
    has_strong_detail_markers = any(
        marker in lower_html
        for marker in (
            'id="acrpopover"',
            'id="averagecustomerreviews_feature_div"',
            'id="customerreviews"',
            'id="reviewsmedialityfeature"',
            'id="productoverview_feature_div"',
        )
    )
    has_twister_marker = any(
        marker in lower_html
        for marker in (
            'id="twister"',
            'id="twister_feature_div"',
            'twisterjsinitializer',
        )
    )
    has_empty_variant_state = (
        '"colortoasin":{}' in lower_html
        or "'colortoasin': {'initial': '{}'}" in lower_html
        or '"landingasincolor":"initial"' in lower_html
    )
    has_full_variant_state = '"dimensiontoasinmap"' in lower_html or '"colortoasin":{"' in lower_html
    if has_strong_detail_markers:
        return False
    return has_product_markers and has_twister_marker and has_empty_variant_state and not has_full_variant_state


def _looks_like_amazon_real_product_page(lower_html: str, final_url: str) -> bool:
    lower_url = final_url.lower()
    if "amazon." not in lower_url:
        return False
    if "/dp/" not in lower_url and "/gp/product/" not in lower_url:
        return False

    markers = 0
    for marker in (
        'id="producttitle"',
        'id="feature-bullets"',
        'id="acrcustomerreviewtext"',
        'id="bylineinfo"',
        'id="averagecustomerreviews_feature_div"',
        'id="detailbullets_feature_div"',
    ):
        if marker in lower_html:
            markers += 1
    return markers >= 2


def _looks_like_amazon_signed_out_recommendation_shell(lower_html: str, final_url: str) -> bool:
    lower_url = final_url.lower()
    if "amazon." not in lower_url:
        return False
    if "/dp/" not in lower_url and "/gp/product/" not in lower_url:
        return False

    has_core_product_markers = any(
        marker in lower_html
        for marker in (
            'id="producttitle"',
            'id="feature-bullets"',
            'id="bylineinfo"',
            'id="coreprice',
            'id="acrpopover"',
            'id="add-to-cart-button"',
        )
    )
    if has_core_product_markers:
        return False

    has_recommendation_shell = (
        "after viewing product detail pages" in lower_html
        or "your recently viewed items and featured recommendations" in lower_html
    )
    has_signin_wall = "/ap/signin" in lower_html or "nav-action-signin-button" in lower_html
    return has_recommendation_shell and has_signin_wall


def classify(
    exc: Exception | None,
    html: str | None = None,
    final_url: str = "",
) -> FetchError | None:
    """Unified classifier: check exception first, then content."""
    if exc is not None:
        return classify_http_error(exc)
    if html is not None:
        return classify_content(html, final_url)
    return None
