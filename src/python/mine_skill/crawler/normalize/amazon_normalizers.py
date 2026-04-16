"""Amazon field normalizers.

Converts raw extracted text values to schema-compliant typed fields.
"""
from __future__ import annotations

import re
from typing import Any


def normalize_price(price_str: str | None) -> dict[str, Any]:
    """Parse price string to structured fields.

    Examples:
        "$19.99" → {"final_price": 19.99, "currency": "USD"}
        "€29,99" → {"final_price": 29.99, "currency": "EUR"}
        "JPY47,306" → {"final_price": 47306, "currency": "JPY"}
        "$19.99 - $29.99" → {"final_price": 19.99, "currency": "USD", "price_range": "$19.99 - $29.99"}

    Returns:
        Dict with: final_price (float), currency (str), initial_price (float, optional)
    """
    if not price_str:
        return {}

    result: dict[str, Any] = {}

    # Currency symbol/code mapping (check codes first, then symbols)
    currency_codes = {
        "JPY": "JPY",
        "CNY": "CNY",
        "USD": "USD",
        "EUR": "EUR",
        "GBP": "GBP",
        "INR": "INR",
        "CAD": "CAD",
        "AUD": "AUD",
    }
    currency_symbols = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "¥": "JPY",
        "₹": "INR",
        "CA$": "CAD",
        "AU$": "AUD",
        "A$": "AUD",
    }

    # Detect currency by code first (e.g., "JPY47,306")
    for code in currency_codes:
        if code in price_str.upper():
            result["currency"] = currency_codes[code]
            break

    # Then check symbols if no code found
    if "currency" not in result:
        for symbol, code in currency_symbols.items():
            if symbol in price_str:
                result["currency"] = code
                break

    # Determine if this is a currency that doesn't use decimals (JPY, etc.)
    no_decimal_currencies = {"JPY", "CNY", "KRW"}
    is_no_decimal = result.get("currency") in no_decimal_currencies

    # Extract price values
    # Pattern handles: $19.99, €29,99, $1,234.56, JPY47,306
    price_pattern = r"[\d,]+\.?\d*"
    matches = re.findall(price_pattern, price_str)

    if matches:
        prices = []
        for match in matches:
            try:
                # Handle different formats
                if is_no_decimal:
                    # For JPY/CNY: commas are thousands separators, no decimals
                    value = float(match.replace(",", ""))
                elif "," in match and "." not in match:
                    # European format: comma as decimal (e.g., €29,99)
                    # But only if it's likely a decimal (2 digits after comma)
                    if re.match(r"^\d+,\d{1,2}$", match):
                        value = float(match.replace(",", "."))
                    else:
                        # Thousands separator
                        value = float(match.replace(",", ""))
                else:
                    value = float(match.replace(",", ""))

                if value > 0:
                    prices.append(value)
            except ValueError:
                continue

        if len(prices) == 1:
            result["final_price"] = prices[0]
        elif len(prices) >= 2:
            # If multiple prices, first is usually original, second is sale price
            result["initial_price"] = max(prices)
            result["final_price"] = min(prices)

    # Extract discount percentage if present
    discount_match = re.search(r"(\d+)%\s*off", price_str, re.IGNORECASE)
    if discount_match:
        result["discount"] = f"{discount_match.group(1)}%"

    return result


def normalize_rating(rating_str: str | None) -> float | None:
    """Parse rating string to float.

    Examples:
        "4.5 out of 5 stars" → 4.5
        "4,5 von 5 Sternen" → 4.5
        "4.5" → 4.5

    Returns:
        Float rating value (0-5 scale) or None
    """
    if not rating_str:
        return None

    # Pattern: number (possibly with comma) followed by "out of" or similar
    match = re.search(r"(\d+[,.]?\d*)\s*(?:out of|von|sur|di|de)", rating_str, re.IGNORECASE)
    if match:
        value = match.group(1).replace(",", ".")
        try:
            return float(value)
        except ValueError:
            pass

    # Fallback: just extract first number
    match = re.search(r"(\d+[,.]?\d*)", rating_str)
    if match:
        value = match.group(1).replace(",", ".")
        try:
            result = float(value)
            # Sanity check: should be 0-5
            if 0 <= result <= 5:
                return result
        except ValueError:
            pass

    return None


def normalize_reviews_count(count_str: str | None) -> int | None:
    """Parse review count string to integer.

    Examples:
        "1,234 ratings" → 1234
        "89,542 global ratings" → 89542
        "12K+ ratings" → 12000

    Returns:
        Integer count or None
    """
    if not count_str:
        return None

    text = count_str.strip().lower()

    # Handle K/M suffix
    k_match = re.search(r"(\d+(?:[.,]\d+)?)\s*k", text)
    if k_match:
        try:
            return int(float(k_match.group(1).replace(",", ".")) * 1000)
        except ValueError:
            pass

    m_match = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text)
    if m_match:
        try:
            return int(float(m_match.group(1).replace(",", ".")) * 1000000)
        except ValueError:
            pass

    # Extract plain number
    match = re.search(r"([\d,]+)", count_str)
    if match:
        try:
            return int(match.group(1).replace(",", ""))
        except ValueError:
            pass

    return None


def normalize_stock_status(availability_str: str | None) -> str | None:
    """Normalize availability text to stock status enum.

    Examples:
        "In Stock" → "in_stock"
        "Usually ships within 2-3 days" → "available"
        "Out of Stock" → "out_of_stock"
        "Only 5 left in stock" → "low_stock"

    Returns:
        One of: in_stock, available, low_stock, out_of_stock, preorder, None
    """
    if not availability_str:
        return None

    text = availability_str.lower()

    if "out of stock" in text or "currently unavailable" in text:
        return "out_of_stock"
    if "pre-order" in text or "preorder" in text:
        return "preorder"
    if "only" in text and "left" in text:
        return "low_stock"
    if "in stock" in text:
        return "in_stock"
    if "ships" in text or "available" in text or "delivery" in text:
        return "available"

    return None


def normalize_fulfillment(
    fulfillment_str: str | None,
    seller_str: str | None = None,
) -> dict[str, Any]:
    """Parse fulfillment/delivery text to structured fields.

    Examples:
        "FREE delivery Tomorrow" + "Ships from Amazon" → {"fulfillment_type": "FBA", "prime_eligible": True}
        "Ships from Seller XYZ" → {"fulfillment_type": "FBM"}

    Returns:
        Dict with: fulfillment_type (FBA/FBM/AMZ), shipping_speed_tier, prime_eligible
    """
    result: dict[str, Any] = {}

    combined = f"{fulfillment_str or ''} {seller_str or ''}".lower()

    # Determine fulfillment type
    if (
        "ships from amazon" in combined
        or "sold by amazon" in combined
        or ("delivery" in combined and "by amazon" in combined)
    ):
        result["fulfillment_type"] = "AMZ"
        result["prime_eligible"] = True
    elif "fulfilled by amazon" in combined or "ships from and sold by amazon" in combined:
        result["fulfillment_type"] = "FBA"
        result["prime_eligible"] = True
    elif "prime" in combined:
        result["fulfillment_type"] = "FBA"
        result["prime_eligible"] = True
    else:
        result["fulfillment_type"] = "FBM"

    # Determine shipping speed
    if "same-day" in combined or "same day" in combined:
        result["shipping_speed_tier"] = "same_day"
    elif "tomorrow" in combined or "next-day" in combined or "next day" in combined:
        result["shipping_speed_tier"] = "next_day"
    elif "2-day" in combined or "two-day" in combined:
        result["shipping_speed_tier"] = "two_day"
    elif "free delivery" in combined or "free shipping" in combined:
        result["shipping_speed_tier"] = "standard"

    return result


def extract_seller_contacts(detailed_info: str | None) -> dict[str, Any]:
    """Extract contact details from seller detailed info text."""
    if not detailed_info:
        return {}

    result: dict[str, Any] = {}
    email_match = re.search(r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", detailed_info, re.IGNORECASE)
    if email_match:
        result["seller_email"] = email_match.group(1)

    phone_match = re.search(r"(\+?\d[\d\s().-]{6,}\d)", detailed_info)
    if phone_match:
        result["seller_phone"] = phone_match.group(1).strip()

    return result


def normalize_date_text(date_str: str | None) -> str | None:
    """Normalize common Amazon date strings to ISO ``YYYY-MM-DD``."""
    if not date_str:
        return None

    cleaned = str(date_str).strip().replace("‎", "").replace("‏", "")

    # Chinese-locale date (e.g. Amazon.cn product detail)
    cn_match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", cleaned)
    if cn_match:
        year, month, day = cn_match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    en_match = re.search(
        r"(?:reviewed\s+in\s+.+?\s+on\s+)?([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
        cleaned,
        re.IGNORECASE,
    )
    if en_match:
        month_name, day, year = en_match.groups()
        month_map = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }
        month = month_map.get(month_name.lower())
        if month:
            return f"{int(year):04d}-{month:02d}-{int(day):02d}"

    return None


def normalize_verified_purchase(value: Any) -> bool | None:
    """Coerce common verified-purchase values to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if not value:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "verified purchase"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    return None


def normalize_sales_volume_hint(value: str | None) -> int | None:
    """Parse sales hint text like ``10K+ bought in past month`` into an integer."""
    if not value:
        return None

    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([km])?\+?", value.strip(), re.IGNORECASE)
    if not match:
        return None

    value_text, suffix = match.groups()
    try:
        numeric = float(value_text.replace(",", "."))
    except ValueError:
        return None

    multiplier = 1
    if suffix:
        suffix = suffix.lower()
        if suffix == "k":
            multiplier = 1000
        elif suffix == "m":
            multiplier = 1000000
    estimated = int(numeric * multiplier)
    return estimated or None


def normalize_amazon_record(record: dict[str, Any]) -> dict[str, Any]:
    """Apply all normalizations to an Amazon product record.

    This is the main entry point for normalizing extracted fields.

    Args:
        record: Raw extracted record with text fields

    Returns:
        Record with normalized typed fields added
    """
    normalized = dict(record)
    resource_type = str(record.get("resource_type") or "").strip().lower()

    raw_rating = record.get("rating") or record.get("structured", {}).get("rating")
    if raw_rating and isinstance(raw_rating, str):
        rating_value = normalize_rating(raw_rating)
        if rating_value is not None:
            normalized["rating"] = rating_value

    if resource_type == "seller":
        raw_seller_rating = record.get("seller_rating") or record.get("structured", {}).get("seller_rating")
        if raw_seller_rating:
            stars = normalize_rating(str(raw_seller_rating))
            if stars is not None:
                normalized["stars"] = stars
        raw_feedbacks = record.get("feedback_count") or record.get("structured", {}).get("feedback_count")
        if raw_feedbacks:
            normalized["feedbacks"] = str(raw_feedbacks)
        detailed_info = record.get("detailed_info") or record.get("structured", {}).get("detailed_info")
        if detailed_info:
            normalized.update(extract_seller_contacts(str(detailed_info)))
        return normalized

    if resource_type == "review":
        helpful = record.get("helpful_count") or record.get("structured", {}).get("helpful_count")
        if isinstance(helpful, str):
            helpful_value = normalize_reviews_count(helpful)
            if helpful_value is not None:
                normalized["helpful_count"] = helpful_value
        verified_purchase = record.get("verified_purchase") or record.get("structured", {}).get("verified_purchase")
        normalized_verified_purchase = normalize_verified_purchase(verified_purchase)
        if normalized_verified_purchase is not None:
            normalized["verified_purchase"] = normalized_verified_purchase
        raw_date = record.get("date_posted") or record.get("structured", {}).get("date_posted")
        if raw_date:
            normalized_date = normalize_date_text(str(raw_date))
            if normalized_date is not None:
                normalized["date_posted"] = normalized_date
        variant_purchased = record.get("variant_purchased") or record.get("structured", {}).get("variant_purchased")
        if variant_purchased:
            normalized["variant_purchased"] = str(variant_purchased).strip()
        return normalized

    # Default to product normalization.
    raw_price = record.get("price") or record.get("structured", {}).get("price")
    if raw_price:
        price_data = normalize_price(str(raw_price))
        for key, value in price_data.items():
            if key not in normalized:
                normalized[key] = value

    raw_reviews = record.get("reviews_count") or record.get("structured", {}).get("reviews_count")
    if raw_reviews and isinstance(raw_reviews, str):
        reviews_value = normalize_reviews_count(raw_reviews)
        if reviews_value is not None:
            normalized["reviews_count"] = reviews_value

    raw_availability = record.get("availability") or record.get("structured", {}).get("availability")
    if raw_availability:
        stock_status = normalize_stock_status(str(raw_availability))
        if stock_status:
            normalized["stock_status"] = stock_status

    raw_fulfillment = record.get("fulfillment") or record.get("structured", {}).get("fulfillment")
    raw_seller = record.get("seller_name") or record.get("structured", {}).get("seller_name")
    if raw_fulfillment or raw_seller:
        fulfillment_data = normalize_fulfillment(
            str(raw_fulfillment) if raw_fulfillment else None,
            str(raw_seller) if raw_seller else None,
        )
        for key, value in fulfillment_data.items():
            if key not in normalized:
                normalized[key] = value

    if "estimated_monthly_sales" not in normalized:
        sales_hint = record.get("sales_volume_hint") or record.get("structured", {}).get("sales_volume_hint")
        estimated_monthly_sales = normalize_sales_volume_hint(str(sales_hint)) if sales_hint else None
        if estimated_monthly_sales is not None:
            normalized["estimated_monthly_sales"] = estimated_monthly_sales

    return normalized
