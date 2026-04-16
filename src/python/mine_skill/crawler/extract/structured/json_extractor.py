"""Structured field extraction from API JSON responses and HTML metadata."""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..models import StructuredFields


def _safe_get(data: dict, *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dict keys."""
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, default)
    return current


def _extract_og_meta(soup: BeautifulSoup, url: str) -> dict[str, Any]:
    """Extract OpenGraph and standard meta tags."""
    fields: dict[str, Any] = {}
    sources: dict[str, str] = {}
    is_amazon = "amazon." in url.lower()

    # Title
    og_title = soup.find("meta", property="og:title")
    og_title_content = og_title.get("content").strip() if og_title and og_title.get("content") else ""
    if og_title_content and not (is_amazon and og_title_content.lower() == "amazon"):
        fields["title"] = og_title_content
        sources["title"] = "html_meta:og:title"
    elif soup.title and soup.title.string:
        fields["title"] = soup.title.string.strip()
        sources["title"] = "html_meta:title"

    # Description
    og_desc = soup.find("meta", property="og:description")
    og_desc_content = og_desc.get("content").strip() if og_desc and og_desc.get("content") else ""
    if og_desc_content and not (is_amazon and og_desc_content.lower() == "amazon"):
        fields["description"] = og_desc_content
        sources["description"] = "html_meta:og:description"
    else:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            fields["description"] = meta_desc["content"]
            sources["description"] = "html_meta:description"

    # Canonical URL
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href"):
        fields["canonical_url"] = urljoin(url, canonical["href"])
        sources["canonical_url"] = "html_meta:canonical"

    # Type
    og_type = soup.find("meta", property="og:type")
    if og_type and og_type.get("content"):
        fields["og_type"] = og_type["content"]
        sources["og_type"] = "html_meta:og:type"

    # Image
    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        fields["image_url"] = urljoin(url, og_image["content"])
        sources["image_url"] = "html_meta:og:image"

    return {"fields": fields, "sources": sources}


class JsonExtractor:
    """Extract structured fields from API JSON and HTML metadata."""

    def extract_document_from_json(
        self,
        *,
        json_data: dict[str, Any],
        platform: str,
        resource_type: str,
        canonical_url: str,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        extracted = self._extract_via_platform_adapter(
            json_data=json_data,
            platform=platform,
            resource_type=resource_type,
            canonical_url=canonical_url,
            content_type=content_type,
        )
        if extracted is None:
            structured = self.extract_from_json(
                json_data=json_data,
                platform=platform,
                resource_type=resource_type,
                canonical_url=canonical_url,
            )
            plain_text, markdown = self._render_generic_document(structured)
            return {
                "structured": structured,
                "plain_text": plain_text,
                "markdown": markdown,
            }

        raw_structured = extracted.get("structured")
        platform_fields = raw_structured if isinstance(raw_structured, dict) else {}
        if platform == "linkedin":
            linkedin_fields = platform_fields.get("linkedin")
            if isinstance(linkedin_fields, dict) and linkedin_fields:
                platform_fields = linkedin_fields
        metadata = extracted.get("metadata") if isinstance(extracted.get("metadata"), dict) else {}
        description = (
            metadata.get("description")
            or (platform_fields.get("description") if isinstance(platform_fields, dict) else None)
            or (platform_fields.get("headline") if isinstance(platform_fields, dict) else None)
            or extracted.get("plain_text")
            or self._description_from_metadata(metadata)
        )
        title = (
            metadata.get("title")
            or (platform_fields.get("title") if isinstance(platform_fields, dict) else None)
        )
        field_sources = {
            key: f"legacy_platform:{platform}"
            for key, value in (platform_fields.items() if isinstance(platform_fields, dict) else [])
            if value not in (None, "", [], {})
        }
        if title:
            field_sources.setdefault("title", f"legacy_platform:{platform}")
        if description:
            field_sources.setdefault("description", f"legacy_platform:{platform}")
        structured = StructuredFields(
            platform=platform,
            resource_type=resource_type,
            title=title,
            description=description,
            canonical_url=canonical_url,
            platform_fields=platform_fields if isinstance(platform_fields, dict) else {},
            field_sources=field_sources,
        )
        plain_text = extracted.get("plain_text") or ""
        markdown = extracted.get("markdown") or ""
        if not plain_text and (structured.title or structured.description or structured.platform_fields):
            plain_text, markdown = self._render_generic_document(structured)
        elif not markdown and plain_text:
            if structured.title:
                markdown = f"# {structured.title}\n\n{plain_text}".strip()
            else:
                markdown = plain_text
        return {
            "structured": structured,
            "plain_text": plain_text,
            "markdown": markdown,
        }

    def extract_from_json(
        self,
        json_data: dict[str, Any],
        platform: str,
        resource_type: str,
        canonical_url: str,
    ) -> StructuredFields:
        """Extract structured fields from an API JSON response."""
        fields: dict[str, Any] = {}
        sources: dict[str, str] = {}
        title = None
        description = None

        # LinkedIn Voyager API
        if platform == "linkedin":
            title, description, fields, sources = self._extract_linkedin_fields(json_data, resource_type)
        # Generic JSON: try common patterns
        else:
            title = (
                _safe_get(json_data, "title")
                or _safe_get(json_data, "name")
                or _safe_get(json_data, "data", "title")
            )
            if title:
                sources["title"] = "api_json"
            description = (
                _safe_get(json_data, "description")
                or _safe_get(json_data, "summary")
                or _safe_get(json_data, "data", "description")
            )
            if description:
                sources["description"] = "api_json"

        return StructuredFields(
            platform=platform,
            resource_type=resource_type,
            title=title,
            description=description,
            canonical_url=canonical_url,
            platform_fields=fields,
            field_sources=sources,
        )

    def extract_from_html(
        self,
        html: str,
        platform: str,
        resource_type: str,
        url: str,
    ) -> StructuredFields:
        """Extract structured fields from HTML meta tags."""
        soup = BeautifulSoup(html, "html.parser")
        meta = _extract_og_meta(soup, url)
        fields = meta["fields"]
        sources = meta["sources"]

        if platform == "amazon":
            if resource_type == "product":
                amazon = self._extract_amazon_product_html(soup, url)
                fields.update(amazon["fields"])
                sources.update(amazon["sources"])
            elif resource_type == "review":
                amazon = self._extract_amazon_review_html(soup, url)
                fields.update(amazon["fields"])
                sources.update(amazon["sources"])
            elif resource_type == "seller":
                amazon = self._extract_amazon_seller_html(soup, url)
                fields.update(amazon["fields"])
                sources.update(amazon["sources"])
        elif platform == "base":
            base = self._extract_base_html(soup, url, resource_type)
            fields.update(base["fields"])
            sources.update(base["sources"])

        return StructuredFields(
            platform=platform,
            resource_type=resource_type,
            title=fields.pop("title", None),
            description=fields.pop("description", None),
            canonical_url=fields.pop("canonical_url", url),
            platform_fields=fields,
            field_sources=sources,
        )

    def _extract_amazon_product_html(
        self,
        soup: BeautifulSoup,
        canonical_url: str,
    ) -> dict[str, dict[str, Any]]:
        fields: dict[str, Any] = {}
        sources: dict[str, str] = {}

        def set_field(name: str, value: Any, source: str) -> None:
            if value in (None, "", [], {}):
                return
            fields[name] = value
            sources[name] = source

        def set_if_missing(name: str, value: Any, source: str) -> None:
            if name in fields:
                return
            set_field(name, value, source)

        # Extract ASIN and marketplace from URL (REQUIRED fields for schema compliance)
        asin = self._extract_asin_from_url(canonical_url)
        marketplace = self._extract_marketplace_from_url(canonical_url)

        if asin:
            set_field("asin", asin, "amazon_url:asin")
            set_field("marketplace", marketplace, "amazon_url:marketplace")
            set_field("dedup_key", f"{asin}:{marketplace}", "computed:asin+marketplace")
            # Canonical URL: normalized format https://www.amazon.{marketplace}/dp/{asin}
            set_field("canonical_url", f"https://www.amazon.{marketplace}/dp/{asin}", "computed:canonical")

        # Store original URL if different from canonical
        set_field("URL", canonical_url, "fetch:original_url")

        # Title extraction with multiple fallback selectors
        title_node = soup.select_one(
            "#productTitle, "
            "#title, "
            "[data-feature-name='title'] span, "
            "#titleSection #title span, "
            "h1#title span, "
            "h1.product-title"
        )
        if title_node is not None:
            title_text = title_node.get_text(" ", strip=True)
            if title_text:
                set_field("title", title_text, "amazon_html:title")

        byline_node = soup.select_one("#bylineInfo")
        if byline_node is not None:
            byline_text = byline_node.get_text(" ", strip=True)
            brand = self._normalize_amazon_brand(byline_text)
            set_field("brand", brand, "amazon_html:#bylineInfo")
            if byline_node.get("href"):
                set_field("brand_url", urljoin(canonical_url, str(byline_node["href"])), "amazon_html:#bylineInfo@href")

        price_node = soup.select_one(
            "#corePrice_feature_div .a-offscreen, "
            "#corePrice_desktop .a-offscreen, "
            "#apex_desktop .a-offscreen, "
            ".a-price .a-offscreen"
        )
        if price_node is not None:
            set_field("price", price_node.get_text(" ", strip=True), "amazon_html:price")

        availability_node = soup.select_one(
            "#availability .a-color-success, "
            "#availability span, "
            "#availability_feature_div span.a-color-success, "
            "#availability_feature_div #availability span, "
            "#outOfStock .a-color-price, "
            "#outOfStock .a-text-bold"
        )
        if availability_node is not None:
            availability_text = availability_node.get_text(" ", strip=True)
            if availability_node.find_parent(id="outOfStock") is not None:
                out_of_stock = availability_node.find_parent(id="outOfStock")
                if out_of_stock is not None:
                    availability_text = out_of_stock.get_text(" ", strip=True)
            set_field("availability", availability_text, "amazon_html:availability")

        rating_node = soup.select_one("#averageCustomerReviews_feature_div .a-icon-alt, #acrPopover .a-icon-alt")
        if rating_node is not None:
            set_field("rating", rating_node.get_text(" ", strip=True), "amazon_html:rating")

        review_count_node = soup.select_one("#acrCustomerReviewText")
        if review_count_node is not None:
            set_field("reviews_count", review_count_node.get_text(" ", strip=True), "amazon_html:#acrCustomerReviewText")

        no_reviews_text = soup.find(string=re.compile(r"no customer reviews yet", re.IGNORECASE))
        if no_reviews_text is not None:
            if "rating" not in fields:
                set_field("rating", "No customer reviews yet", "amazon_html:no_reviews")
            if "reviews_count" not in fields:
                set_field("reviews_count", "0 reviews", "amazon_html:no_reviews")

        category_nodes = soup.select("#wayfinding-breadcrumbs_feature_div a")
        if category_nodes:
            categories = [
                node.get_text(" ", strip=True)
                for node in category_nodes
                if node.get_text(" ", strip=True)
            ]
            set_field("categories", categories, "amazon_html:breadcrumbs")
            set_field("breadcrumbs", categories, "amazon_html:breadcrumbs")
            set_field("category", categories, "amazon_html:breadcrumbs")
            set_field("category_tree", " > ".join(categories), "computed:category_tree")

        bullet_nodes = soup.select("#feature-bullets .a-list-item")
        if bullet_nodes:
            bullets = []
            for node in bullet_nodes:
                text = node.get_text(" ", strip=True)
                if text:
                    bullets.append(text)
            set_field("bullet_points", bullets, "amazon_html:#feature-bullets")

        if "categories" not in fields:
            meta_title = soup.find("meta", attrs={"name": "title"})
            title_text = meta_title.get("content", "").strip() if meta_title is not None else ""
            if not title_text and soup.title and soup.title.string:
                title_text = soup.title.string.strip()
            category = self._extract_amazon_meta_category(title_text)
            if category:
                category_list = [category]
                set_field("categories", category_list, "amazon_html:meta_title_category")
                set_field("breadcrumbs", category_list, "amazon_html:meta_title_category")
                set_field("category", category_list, "amazon_html:meta_title_category")
                set_field("category_tree", category, "computed:category_tree")
        if "categories" not in fields:
            department_option = soup.select_one("select#searchDropdownBox option[selected], #searchDropdownBox option[selected]")
            department_text = department_option.get_text(" ", strip=True) if department_option is not None else ""
            if department_text and department_text.lower() not in {"all", "all departments"}:
                category_list = [department_text]
                set_field("categories", category_list, "amazon_html:search_department")
                set_field("breadcrumbs", category_list, "amazon_html:search_department")
                set_field("category", category_list, "amazon_html:search_department")
                set_field("category_tree", department_text, "computed:category_tree")

        if "categories" not in fields:
            department_node = soup.select_one("#nav-search-label-id, #searchDropdownBox option[selected]")
            if department_node is not None:
                department_text = department_node.get_text(" ", strip=True)
                if department_text:
                    category_list = [department_text]
                    set_field("categories", category_list, "amazon_html:search_department")
                    set_field("breadcrumbs", category_list, "amazon_html:search_department")
                    set_field("category", category_list, "amazon_html:search_department")
                    set_field("category_tree", department_text, "computed:category_tree")

        image_nodes = soup.select("#imgTagWrapperId img[src], #altImages img[src]")
        if image_nodes:
            images: list[str] = []
            for node in image_nodes:
                src = node.get("src")
                if not src:
                    continue
                absolute = urljoin(canonical_url, str(src))
                if absolute not in images:
                    images.append(absolute)
            set_field("images", images, "amazon_html:images")
            # Prefer an actual product image over viewer chrome/icons.
            product_images = [image for image in images if self._is_amazon_product_image(image)]
            if product_images:
                set_field("main_image", product_images[0], "amazon_html:product_images[0]")
            elif images:
                set_field("main_image", images[0], "amazon_html:images[0]")

        # Check for A+ content presence
        aplus_modules = soup.select(".aplus-module, #aplus")
        if aplus_modules:
            set_field("a_plus_content_present", True, "amazon_html:.aplus-module")

        description_node = soup.select_one("#productDescription, #productDescription_feature_div, #bookDescription_feature_div")
        if description_node is not None:
            set_field("description", description_node.get_text(" ", strip=True), "amazon_html:description")

        fulfillment_node = soup.select_one(
            "#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE, "
            "#deliveryBlockMessage, "
            "#mir-layout-DELIVERY_BLOCK-slot-DELIVERY_MESSAGE, "
            "#exports_desktop_qualifiedBuybox_deliveryPromiseMessaging_feature_div"
        )
        if fulfillment_node is not None:
            set_field("fulfillment", fulfillment_node.get_text(" ", strip=True), "amazon_html:fulfillment")
        elif "availability" in fields and re.search(r"unavailable|out of stock|back in stock", str(fields["availability"]), re.IGNORECASE):
            set_field("fulfillment", fields["availability"], "amazon_html:availability_fallback")

        variant_nodes = soup.select("#twister li[data-defaultasin], #twister li[data-asin]")
        twister_variant_state = self._extract_amazon_twister_variant_state(soup)
        if variant_nodes:
            variants: list[dict[str, Any]] = []
            for node in variant_nodes:
                asin = node.get("data-defaultasin") or node.get("data-asin")
                label = node.get("title")
                if not label:
                    image = node.select_one("img[alt]")
                    if image is not None:
                        label = image.get("alt")
                variant: dict[str, Any] = {}
                if asin:
                    variant["asin"] = str(asin)
                if label:
                    variant["label"] = str(label).strip()
                if asin and str(asin) in twister_variant_state:
                    variant.update(twister_variant_state[str(asin)])
                if variant:
                    variants.append(variant)
            set_field("variants", variants, "amazon_html:variants")

        embedded_json_objects = self._extract_amazon_embedded_json_objects(soup)

        if "price" not in fields:
            embedded_price = self._extract_amazon_embedded_price(embedded_json_objects)
            if embedded_price:
                set_field("price", embedded_price, "amazon_html:embedded_json_price")

        if "variants" not in fields:
            embedded_variants = self._extract_amazon_embedded_variants(embedded_json_objects)
            if embedded_variants:
                for variant in embedded_variants:
                    asin = variant.get("asin")
                    if isinstance(asin, str) and asin in twister_variant_state:
                        variant.update(twister_variant_state[asin])
                set_field("variants", embedded_variants, "amazon_html:embedded_json_variants")

        seller_node = soup.select_one("#merchant-info")
        if seller_node is not None:
            seller_text = seller_node.get_text(" ", strip=True)
            set_field("seller_name", seller_text, "amazon_html:#merchant-info")
            # Extract seller_id from link
            seller_link = seller_node.select_one("a[href*='seller=']")
            if seller_link:
                href = seller_link.get("href", "")
                seller_id_match = re.search(r"seller=([A-Z0-9]+)", href)
                if seller_id_match:
                    set_field("seller_id", seller_id_match.group(1), "amazon_html:#merchant-info@href")

        # Extract coupon availability
        coupon_node = soup.select_one(
            "#promoPriceBlockMessage_feature_div, "
            ".promoPriceBlockMessage, "
            "[data-csa-c-content-id='coupon']"
        )
        if coupon_node:
            set_field("coupon_available", True, "amazon_html:coupon_badge")

        # Extract Subscribe & Save availability
        sns_node = soup.select_one("#snsAccordionRowMiddle, #subscribeAndSaveFeature, #sns-accordion")
        if sns_node:
            set_field("subscribe_and_save_available", True, "amazon_html:sns_widget")

        # Extract Prime eligibility
        prime_node = soup.select_one(
            "#prime-badge, "
            ".a-icon-prime, "
            "[data-feature-name='primeShippingFlag'], "
            "#deliveryBlockMessage .a-icon-prime"
        )
        if prime_node:
            set_field("prime_eligible", True, "amazon_html:prime_badge")

        # Extract Best Sellers Rank
        bsr_node = soup.select_one("#productDetails_detailBullets_sections1, #detailBulletsWrapper_feature_div")
        if bsr_node:
            bsr_text = bsr_node.get_text(" ", strip=True)
            bsr_data = self._parse_best_sellers_rank(bsr_text)
            if bsr_data:
                set_field("best_sellers_rank", bsr_data, "amazon_html:product_details_bsr")

        # Extract sales volume hint (e.g., "10K+ bought in past month")
        sales_hint_node = soup.select_one(
            "#social-proofing-faceout-title-tk_bought, "
            "[data-csa-c-content-id='social-proofing'], "
            ".social-proofing-faceout-title"
        )
        if sales_hint_node:
            set_field("sales_volume_hint", sales_hint_node.get_text(" ", strip=True), "amazon_html:sales_hint")

        # Extract answered questions count
        qa_node = soup.select_one("#askATFLink span, #ask-btf_feature_div .a-size-base")
        if qa_node:
            qa_text = qa_node.get_text(" ", strip=True)
            qa_match = re.search(r"(\d+)\s*(?:answered|questions)", qa_text, re.IGNORECASE)
            if qa_match:
                set_field("answered_questions_count", int(qa_match.group(1)), "amazon_html:qa_count")

        # Extract product details table fields
        details_tables = soup.select(
            "#productDetails_techSpec_section_1 tr, "
            "#productDetails_detailBullets_sections1 tr, "
            "#detailBullets_feature_div li, "
            "#detailBulletsWrapper_feature_div li, "
            "#prodDetails tr"
        )
        extracted_features: list[str] = []
        for row in details_tables:
            label_node = row.select_one("th, .a-text-bold, .prodDetSectionEntry")
            value_node = row.select_one("td, .a-span9, .prodDetAttrValue")
            label = label_node.get_text(" ", strip=True) if label_node else ""
            value = value_node.get_text(" ", strip=True) if value_node else ""
            if label and not value:
                row_text = row.get_text(" ", strip=True)
                value = row_text.replace(label, "", 1).strip(" :：\u200e\u200f")
            if not label or not value:
                continue
            normalized_label = re.sub(r"[\s\u200e\u200f]+", "", label).strip(" :：").lower()

            # Amazon.cn and other localized labels (CN UI strings)
            if "datefirstavailable" in normalized_label or "上架时间" in label:
                set_field(
                    "date_first_available",
                    self._normalize_amazon_date_text(value) or value,
                    "amazon_html:product_details",
                )
            elif "productdimensions" in normalized_label or "packagedimensions" in normalized_label or "尺寸" in label:
                set_field("product_dimensions", value, "amazon_html:product_details")
            elif "itemweight" in normalized_label or "productweight" in normalized_label or "商品重量" in label:
                set_field("product_weight", value, "amazon_html:product_details")
            elif "warranty" in normalized_label:
                set_field("warranty_info", value, "amazon_html:product_details")
            elif "countryoforigin" in normalized_label:
                set_field("country_of_origin", value, "amazon_html:product_details")
            elif "manufacturer" in normalized_label and "manufacturer" not in fields:
                set_field("manufacturer", value, "amazon_html:product_details")
            elif "model" in normalized_label and "number" in normalized_label:
                set_field("model_number", value, "amazon_html:product_details")
            elif "亚马逊热销商品排名" in label or "bestsellersrank" in normalized_label:
                bsr_data = self._parse_best_sellers_rank(f"{label} {value}")
                if bsr_data:
                    set_field("best_sellers_rank", bsr_data, "amazon_html:product_details_bsr")
            else:
                extracted_features.append(f"{label.strip(' :：')}: {value}")

        if extracted_features:
            set_field("features", extracted_features, "amazon_html:product_details_features")
        elif "bullet_points" in fields:
            set_field("features", fields["bullet_points"], "computed:features_from_bullets")

        if {
            "date_first_available",
            "product_dimensions",
            "product_weight",
            "warranty_info",
        } - set(fields):
            for label, value in self._extract_amazon_detail_bullets_pairs(soup):
                normalized_label = re.sub(r"[\s\u200e\u200f]+", "", label).strip(" :").lower()
                if "date_first_available" not in fields and (
                    "datefirstavailable" in normalized_label or "publicationdate" in normalized_label
                ):
                    set_field(
                        "date_first_available",
                        self._normalize_amazon_date_text(value) or value,
                        "amazon_html:detail_bullets_pairs",
                    )
                elif "product_dimensions" not in fields and (
                    "productdimensions" in normalized_label
                    or "packagedimensions" in normalized_label
                    or normalized_label == "dimensions"
                    or "dimensions" in normalized_label
                ):
                    set_field("product_dimensions", value, "amazon_html:detail_bullets_pairs")
                elif "product_weight" not in fields and (
                    "itemweight" in normalized_label or "productweight" in normalized_label or normalized_label == "weight"
                ):
                    set_field("product_weight", value, "amazon_html:detail_bullets_pairs")
                elif "warranty_info" not in fields and "warranty" in normalized_label:
                    set_field("warranty_info", value, "amazon_html:detail_bullets_pairs")

        if "product_dimensions" not in fields or "product_weight" not in fields:
            content_grid_rows = soup.select("table.a-bordered tr")
            for row in content_grid_rows:
                cells = row.select("td")
                if len(cells) < 2:
                    continue
                label = cells[0].get_text(" ", strip=True)
                value = cells[1].get_text(" ", strip=True)
                normalized_label = re.sub(r"[\s\u200e\u200f]+", "", label).strip(" :").lower()
                if not label or not value:
                    continue
                if "product_dimensions" not in fields and normalized_label in {"size", "dimensions", "productdimensions"}:
                    set_field("product_dimensions", value, "amazon_html:content_grid_table")
                elif "product_weight" not in fields and normalized_label in {"weight", "itemweight", "productweight"}:
                    set_field("product_weight", value, "amazon_html:content_grid_table")
                elif "warranty_info" not in fields and normalized_label in {"softwaresecurityupdates", "warranty"}:
                    set_field("warranty_info", value, "amazon_html:content_grid_table")

        # Extract variant dimensions (sizes, colors, styles)
        twister_labels = soup.select("#twister .a-row.a-spacing-small")
        for label_row in twister_labels:
            label_text = label_row.get_text(" ", strip=True).lower()
            options = label_row.find_next_sibling()
            if not options:
                continue
            option_values = [
                opt.get_text(" ", strip=True)
                for opt in options.select("li[data-defaultasin] img[alt], li[data-asin] img[alt], option")
                if opt.get_text(" ", strip=True)
            ]
            if not option_values:
                option_values = [
                    opt.get("alt", "") or opt.get_text(" ", strip=True)
                    for opt in options.select("li img[alt], li span.a-size-base")
                ]
            option_values = [v for v in option_values if v and v.lower() not in ("select", "choose")]

            if "size" in label_text and option_values:
                set_field("sizes", option_values, "amazon_html:twister_sizes")
            elif "color" in label_text and option_values:
                set_field("colors", option_values, "amazon_html:twister_colors")
            elif "style" in label_text and option_values:
                set_field("styles", option_values, "amazon_html:twister_styles")

        # Extract frequently bought together
        fbt_node = soup.select_one("#sims-fbt, #sims-fbt-content")
        if fbt_node:
            fbt_items: list[dict[str, Any]] = []
            for item in fbt_node.select(".sims-fbt-image-box, .sims-fbt-carousel-item"):
                item_asin = item.get("data-asin") or item.get("data-p13n-asin-metadata", "")
                title_node = item.select_one(".sims-fbt-truncate-name, a[title]")
                item_title = title_node.get_text(" ", strip=True) if title_node else None
                if item_asin:
                    fbt_item: dict[str, Any] = {"asin": str(item_asin)}
                    if item_title:
                        fbt_item["title"] = item_title
                    fbt_items.append(fbt_item)
            if fbt_items:
                set_field("frequently_bought_together", fbt_items, "amazon_html:fbt_widget")
        if "frequently_bought_together" not in fields:
            fbt_items = self._extract_amazon_fbt_items(soup)
            if fbt_items:
                set_field("frequently_bought_together", fbt_items, "amazon_html:fbt_widget_fallback")

        # Extract customers also viewed
        cav_node = soup.select_one("#sp_detail, #sp_detail2, [data-component-type='sp_detail']")
        if cav_node:
            cav_items: list[dict[str, Any]] = []
            for item in cav_node.select("[data-asin], .s-result-item"):
                item_asin = item.get("data-asin")
                title_node = item.select_one(".a-link-normal[title], .a-text-normal")
                item_title = title_node.get_text(" ", strip=True) if title_node else None
                if item_asin:
                    cav_item: dict[str, Any] = {"asin": str(item_asin)}
                    if item_title:
                        cav_item["title"] = item_title
                    cav_items.append(cav_item)
            if cav_items:
                set_field("customers_also_viewed", cav_items, "amazon_html:cav_widget")
        elif "customers_also_viewed" not in fields:
            compare_items, compare_attributes = self._extract_amazon_compare_table(soup)
            if compare_items:
                set_field("customers_also_viewed", compare_items, "amazon_html:compare_widget")
            dimensions = compare_attributes.get("dimensions")
            if dimensions:
                set_field("product_dimensions", dimensions, "amazon_html:compare_widget")

        # Extract video presence
        video_node = soup.select_one(
            "#videoblock, "
            "[data-action='a-carousel-video'], "
            ".vse-vpp-video-container"
        )
        if video_node:
            set_field("has_video", True, "amazon_html:video_present")

        # Keep the legacy "category" alias for enrich inputs after emitting
        # schema-aligned category fields for downstream consumers.
        if "category" not in fields and "categories" in fields:
            set_field("category", fields["categories"], "computed:category_alias")

        # Compute image_count
        if "images" in fields and isinstance(fields["images"], list):
            set_field("image_count", len(fields["images"]), "computed:image_count")

        return {"fields": fields, "sources": sources}

    def _is_amazon_product_image(self, url: str) -> bool:
        lowered = str(url or "").lower()
        if not lowered:
            return False
        blocked_markers = (
            "transparent-pixel",
            "360_icon",
            "icon_73x73",
            "play-icon",
            "video._cb",
            ".gif",
        )
        if any(marker in lowered for marker in blocked_markers):
            return False
        return any(marker in lowered for marker in ("/images/i/", "m.media-amazon.com/images/i/", "images-na.ssl-images-amazon.com/images/i/"))

    def _extract_amazon_detail_bullets_pairs(self, soup: BeautifulSoup) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for item in soup.select("#detailBulletsWrapper_feature_div li, #detailBullets_feature_div li"):
            label_node = item.select_one(".a-text-bold")
            if label_node is None:
                continue
            label = label_node.get_text(" ", strip=True).strip(" :")
            text = item.get_text(" ", strip=True)
            value = text.replace(label_node.get_text(" ", strip=True), "", 1).strip(" :")
            if label and value:
                pairs.append((label, value))
        return pairs

    def _extract_amazon_fbt_items(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        container = soup.select_one("[cel_widget_id*='sims-fbt'], [id*='sims-fbt']")
        if container is None:
            return []
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in container.select("[data-asin], [id^='ProductTitle-']"):
            asin = item.get("data-asin")
            if not asin:
                link = item.select_one("a[href*='/dp/'], a[href*='/gp/product/']")
                if link is not None:
                    href = link.get("href", "")
                    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", href)
                    if match:
                        asin = match.group(1)
            if not asin or asin in seen:
                continue
            seen.add(asin)
            title_node = item.select_one("a[title], .a-size-base")
            title = title_node.get_text(" ", strip=True) if title_node is not None else None
            entry: dict[str, Any] = {"asin": asin}
            if title:
                entry["title"] = title
            items.append(entry)
        for hidden in container.select("input[name*='[asin]'][value]"):
            asin = str(hidden.get("value") or "").strip()
            if not asin or asin in seen:
                continue
            seen.add(asin)
            items.insert(0, {"asin": asin})
        return items

    def _extract_amazon_compare_table(self, soup: BeautifulSoup) -> tuple[list[dict[str, Any]], dict[str, str]]:
        compare = soup.select_one("#compare table.ucc-v2-widget__table, #compare")
        if compare is None:
            return [], {}

        rows = []
        for tr in compare.select("tr"):
            cells = [
                cell.get_text(" ", strip=True)
                for cell in tr.select("th, td")
            ]
            if cells:
                rows.append(cells)
        if len(rows) < 3:
            return [], {}

        device_row = next((row for row in rows if row and row[0].strip().upper() == "DEVICE"), None)
        if not device_row:
            return [], {}

        products: list[dict[str, Any]] = []
        for anchor in compare.select("a[href*='/dp/'][title]"):
            href = str(anchor.get("href") or "").strip()
            title = anchor.get("title") or anchor.get_text(" ", strip=True)
            asin_match = re.search(r"/dp/([A-Z0-9]{10})", href)
            if not asin_match or not title:
                continue
            asin = asin_match.group(1)
            if any(item.get("asin") == asin for item in products):
                continue
            products.append(
                {
                    "asin": asin,
                    "title": str(title).strip(),
                    "url": urljoin("https://www.amazon.com", href),
                }
            )

        attributes: dict[str, str] = {}
        for row in rows:
            if len(row) < 2:
                continue
            label = row[0].strip().lower()
            values = [value.strip() for value in row[1:] if value.strip() and value.strip() != "-"]
            if not values:
                continue
            if label == "dimensions":
                attributes["dimensions"] = values[0]
        return products, attributes

    def _extract_amazon_seller_html(
        self,
        soup: BeautifulSoup,
        canonical_url: str,
    ) -> dict[str, dict[str, Any]]:
        fields: dict[str, Any] = {}
        sources: dict[str, str] = {}

        def set_field(name: str, value: Any, source: str) -> None:
            if value in (None, "", [], {}):
                return
            fields[name] = value
            sources[name] = source

        seller_id = self._extract_seller_id_from_url(canonical_url)
        marketplace = self._extract_marketplace_from_url(canonical_url)
        if seller_id:
            set_field("seller_id", seller_id, "amazon_url:seller_id")
            set_field("marketplace", marketplace, "amazon_url:marketplace")
            set_field("dedup_key", f"{seller_id}:{marketplace}", "computed:seller_id+marketplace")
            set_field("canonical_url", f"https://www.amazon.{marketplace}/sp?seller={seller_id}", "computed:canonical")
        set_field("URL", canonical_url, "fetch:original_url")

        seller_name_node = soup.select_one("#seller-name, #seller-profile-container h1, h1")
        if seller_name_node is not None:
            seller_name = seller_name_node.get_text(" ", strip=True)
            set_field("title", seller_name, "amazon_html:seller_name")
            set_field("seller_name", seller_name, "amazon_html:seller_name")

        seller_rating_node = soup.select_one(
            "#seller-rating, "
            "#seller-info-feedback-summary, "
            ".seller-rating, "
            "a[href*='#'] .a-icon-alt"
        )
        if seller_rating_node is not None:
            set_field("seller_rating", seller_rating_node.get_text(" ", strip=True), "amazon_html:seller_rating")

        feedback_count_node = soup.select_one("#feedback-count, #seller-feedback-count, .feedback-count")
        if feedback_count_node is not None:
            set_field("feedback_count", feedback_count_node.get_text(" ", strip=True), "amazon_html:feedback_count")
        elif seller_rating_node is not None:
            summary_text = seller_rating_node.get_text(" ", strip=True)
            feedback_match = re.search(r"\(([\d,]+)\s+ratings?\)|共\s*([\d,]+)\s*条评价|([\d,]+)\s*ratings?", summary_text, re.IGNORECASE)
            if feedback_match:
                feedback_value = next(group for group in feedback_match.groups() if group)
                set_field("feedback_count", f"{feedback_value} ratings", "amazon_html:seller_rating_summary")

        seller_since_node = soup.select_one("#seller-since, .seller-since")
        if seller_since_node is not None:
            set_field("seller_since", seller_since_node.get_text(" ", strip=True), "amazon_html:seller_since")

        description_node = soup.select_one(
            ".about-seller, "
            "#seller-description, "
            "#page-section-detail-seller-info .a-spacing-small, "
            "h3 + div"
        )
        if description_node is not None:
            set_field("description", description_node.get_text(" ", strip=True), "amazon_html:seller_description")

        return_policy_node = soup.select_one(
            ".return-policy, "
            "#page-section-return-policy, "
            "#page-section-return-policy .a-section"
        )
        if return_policy_node is not None:
            set_field("return_policy", return_policy_node.get_text(" ", strip=True), "amazon_html:return_policy")

        detailed_info_node = soup.select_one(
            ".detailed-info, "
            "#page-section-detailed-seller-info, "
            "#page-section-detailed-seller-info .a-section"
        )
        if detailed_info_node is not None:
            set_field("detailed_info", detailed_info_node.get_text(" ", strip=True), "amazon_html:detailed_info")

        product_cards = soup.select("#seller-listings .seller-product, .seller-product")
        if product_cards:
            product_listings: list[dict[str, Any]] = []
            for card in product_cards:
                product: dict[str, Any] = {}
                asin = card.get("data-asin")
                if asin:
                    product["asin"] = str(asin)
                link_node = card.select_one("a.seller-product-link[href], a[href*='/dp/']")
                if link_node is not None:
                    title = link_node.get_text(" ", strip=True)
                    href = link_node.get("href")
                    if title:
                        product["title"] = title
                    if href:
                        product["url"] = urljoin(canonical_url, str(href))
                price_node = card.select_one(".a-price .a-offscreen, .seller-product-price")
                if price_node is not None:
                    product["price"] = price_node.get_text(" ", strip=True)
                rating_node = card.select_one(".a-icon-alt, .seller-product-rating")
                if rating_node is not None:
                    product["rating"] = rating_node.get_text(" ", strip=True)
                if product:
                    product_listings.append(product)
            set_field("product_listings", product_listings, "amazon_html:product_listings")

        return {"fields": fields, "sources": sources}

    def _extract_amazon_review_html(
        self,
        soup: BeautifulSoup,
        canonical_url: str,
    ) -> dict[str, dict[str, Any]]:
        fields: dict[str, Any] = {}
        sources: dict[str, str] = {}

        def set_field(name: str, value: Any, source: str) -> None:
            if value in (None, "", [], {}):
                return
            fields[name] = value
            sources[name] = source

        review_id = self._extract_review_id_from_url(canonical_url)
        marketplace = self._extract_marketplace_from_url(canonical_url)
        if review_id:
            set_field("review_id", review_id, "amazon_url:review_id")
            set_field("marketplace", marketplace, "amazon_url:marketplace")
            set_field("dedup_key", f"{review_id}:{marketplace}", "computed:review_id+marketplace")
            set_field("canonical_url", f"https://www.amazon.{marketplace}/gp/customer-reviews/{review_id}", "computed:canonical")
        set_field("URL", canonical_url, "fetch:original_url")

        review_node = soup.select_one("[data-hook='review'], [id^='customer_review-'], [id^='review-']")
        if review_node is None:
            return {"fields": fields, "sources": sources}

        asin = review_node.get("data-asin")
        if not asin:
            product_link = review_node.select_one("a[href*='/dp/'], a[href*='/gp/product/']")
            if product_link is not None:
                asin = self._extract_asin_from_url(urljoin(canonical_url, str(product_link.get("href", ""))))
        if asin:
            set_field("asin", str(asin).strip(), "amazon_html:review@data-asin")

        author_node = review_node.select_one(".a-profile-name, [data-hook='review-author']")
        if author_node is not None:
            author_name = author_node.get_text(" ", strip=True)
            set_field("author_name", author_name, "amazon_html:review_author")
            set_field("reviewer_name", author_name, "amazon_html:review_author")

        author_link = review_node.select_one("a[href*='/gp/profile/'], a[href*='/hz/profile/']")
        if author_link is not None:
            href = str(author_link.get("href", ""))
            author_id = href.rstrip("/").split("/")[-1]
            if author_id:
                set_field("author_id", author_id, "amazon_html:review_author_link")

        title_node = review_node.select_one("[data-hook='review-title'], .review-title")
        if title_node is not None:
            set_field("review_headline", title_node.get_text(" ", strip=True), "amazon_html:review_title")

        rating_node = review_node.select_one("[data-hook='review-star-rating'], .review-rating")
        if rating_node is not None:
            set_field("rating", rating_node.get_text(" ", strip=True), "amazon_html:review_rating")

        body_node = review_node.select_one("[data-hook='review-body'], .review-text-content, .review-text")
        if body_node is not None:
            review_text = body_node.get_text(" ", strip=True)
            set_field("review_text", review_text, "amazon_html:review_body")
            set_field("plain_text", review_text, "amazon_html:review_body")

        date_node = review_node.select_one("[data-hook='review-date'], .review-date")
        if date_node is not None:
            date_text = date_node.get_text(" ", strip=True)
            set_field("date_posted", date_text, "amazon_html:review_date")
            country_match = re.search(r"reviewed in\s+(.+?)\s+on\s+", date_text, re.IGNORECASE)
            if country_match:
                set_field("review_country", country_match.group(1).strip(), "amazon_html:review_date")

        if review_node.select_one("[data-hook='avp-badge'], [data-hook='vine-badge']") is not None:
            set_field("verified_purchase", True, "amazon_html:verified_purchase")

        variant_purchased = self._extract_amazon_review_variant_purchased(review_node)
        if variant_purchased:
            set_field("variant_purchased", variant_purchased, "amazon_html:review_variant")

        helpful_node = review_node.select_one("[data-hook='helpful-vote-statement']")
        if helpful_node is not None:
            helpful_text = helpful_node.get_text(" ", strip=True)
            helpful_match = re.search(r"([\d,]+)", helpful_text)
            if helpful_match:
                set_field("helpful_count", int(helpful_match.group(1).replace(",", "")), "amazon_html:helpful_count")

        review_images: list[str] = []
        for image in review_node.select("img[src]"):
            src = image.get("src")
            if not src:
                continue
            absolute = urljoin(canonical_url, str(src))
            if absolute not in review_images:
                review_images.append(absolute)
        if review_images:
            set_field("review_images", review_images, "amazon_html:review_images")

        seller_response_node = review_node.select_one("[data-hook='seller-comment'], .review-comment")
        if seller_response_node is not None:
            set_field("seller_response", seller_response_node.get_text(" ", strip=True), "amazon_html:seller_response")

        return {"fields": fields, "sources": sources}

    def _normalize_amazon_brand(self, byline_text: str) -> str:
        text = byline_text.strip()
        if not text:
            return text

        localized_author_match = re.match(r"(?:author|作者)\s+(.+?)(?:\s*\((?:author|作者)\))?$", text, flags=re.IGNORECASE)
        if localized_author_match:
            return localized_author_match.group(1).strip()

        visit_match = re.match(r"visit the\s+(.+?)\s+store$", text, flags=re.IGNORECASE)
        if visit_match:
            return visit_match.group(1).strip()

        brand_match = re.match(r"brand:\s*(.+)$", text, flags=re.IGNORECASE)
        if brand_match:
            return brand_match.group(1).strip()

        return text

    def _extract_amazon_meta_category(self, title_text: str) -> str | None:
        text = title_text.strip()
        if not text:
            return None
        match = re.search(r":\s*([^:]+?)\s*:\s*([^:]+?)\s*$", text)
        if match:
            return match.group(2).strip()
        return None

    def _extract_amazon_review_variant_purchased(self, review_node: Any) -> str | None:
        containers = review_node.select(
            "[data-hook='format-strip'], "
            "[data-hook='format-strip-linkless'], "
            ".review-format-strip, "
            ".format-strip"
        )
        variant_parts: list[str] = []
        seen: set[str] = set()

        def add_part(text: str) -> None:
            cleaned = re.sub(r"\s+", " ", text).strip(" |")
            normalized_key = cleaned.lower()
            if not cleaned or normalized_key in seen:
                return
            seen.add(normalized_key)
            variant_parts.append(cleaned)

        for container in containers:
            candidates = [
                node.get_text(" ", strip=True)
                for node in container.select("a, span")
                if node.get_text(" ", strip=True)
            ]
            if not candidates:
                candidates = [part.strip() for part in container.get_text(" ", strip=True).split("|")]
            for candidate in candidates:
                if self._looks_like_amazon_variant_text(candidate):
                    add_part(candidate)

        if variant_parts:
            return " | ".join(variant_parts)
        return None

    def _looks_like_amazon_variant_text(self, text: str) -> bool:
        cleaned = re.sub(r"\s+", " ", text).strip(" |")
        if not cleaned:
            return False
        lowered = cleaned.lower()
        if any(
            phrase in lowered
            for phrase in (
                "verified purchase",
                "vine customer review",
                "reviewed in",
                "helpful",
                "people found this helpful",
            )
        ):
            return False

        prefix, separator, _ = cleaned.partition(":")
        if not separator:
            return False

        variant_prefixes = {
            "color",
            "size",
            "style",
            "pattern",
            "flavor",
            "configuration",
            "item package quantity",
            "capacity",
            "scent",
            "design",
            "material",
            "edition",
            "format",
            "platform",
            "model",
            "pack",
        }
        return prefix.strip().lower() in variant_prefixes

    def _parse_best_sellers_rank(self, text: str) -> dict[str, int]:
        """Parse Best Sellers Rank from product details text.

        Input example:
        "Best Sellers Rank: #45 in Electronics (See Top 100 in Electronics)
         #2 in Over-Ear Headphones"

        Returns:
        {"Electronics": 45, "Over-Ear Headphones": 2}
        """
        bsr_data: dict[str, int] = {}
        # Pattern: #123 in Category Name
        matches = re.findall(r"#([\d,]+)\s+in\s+([^(#\n]+)", text)
        for rank_str, category in matches:
            try:
                rank = int(rank_str.replace(",", ""))
                category_clean = category.strip().rstrip(")")
                if category_clean:
                    bsr_data[category_clean] = rank
            except ValueError:
                continue

        localized_matches = re.findall(r"([^:：\n]+?)商品里排第\s*([\d,]+)\s*名", text)
        for category, rank_str in localized_matches:
            try:
                rank = int(rank_str.replace(",", ""))
            except ValueError:
                continue
            category_clean = category.strip()
            if category_clean:
                bsr_data[category_clean] = rank
        return bsr_data

    def _normalize_amazon_date_text(self, text: str) -> str | None:
        cleaned = text.strip().replace("‎", "").replace("‏", "")
        cleaned = re.sub(r"\s+", "", cleaned)
        match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", cleaned)
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
        english_match = re.search(
            r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})",
            text,
        )
        if english_match:
            month_name, day, year = english_match.groups()
            month_map = {
                "january": 1, "february": 2, "march": 3, "april": 4,
                "may": 5, "june": 6, "july": 7, "august": 8,
                "september": 9, "october": 10, "november": 11, "december": 12,
            }
            month = month_map.get(month_name.lower())
            if month:
                return f"{int(year):04d}-{month:02d}-{int(day):02d}"
        return None

    def _extract_asin_from_url(self, url: str) -> str | None:
        """Extract ASIN from Amazon URL.

        Supports patterns:
        - /dp/B0ABCD1234
        - /gp/product/B0ABCD1234
        - /dp/B0ABCD1234/ref=...
        """
        match = re.search(r'/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?#]|$)', url)
        return match.group(1) if match else None

    def _extract_seller_id_from_url(self, url: str) -> str | None:
        parsed = urlparse(url)
        for key in ("seller", "merchant", "me"):
            candidate = parse_qs(parsed.query).get(key, [None])[0]
            if candidate and re.fullmatch(r"[A-Z0-9]{10,20}", candidate, re.IGNORECASE):
                return candidate.upper()
        return None

    def _extract_review_id_from_url(self, url: str) -> str | None:
        match = re.search(r"/gp/customer-reviews/([A-Z0-9]+)(?:[/?#]|$)", url, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).upper()

    def _extract_marketplace_from_url(self, url: str) -> str:
        """Extract marketplace code from Amazon URL.

        Examples:
        - amazon.com → 'com'
        - amazon.co.uk → 'co.uk'
        - amazon.de → 'de'
        """
        match = re.search(r'amazon\.([a-z.]+)', url, re.IGNORECASE)
        return match.group(1) if match else 'com'

    def _extract_amazon_embedded_json_objects(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        objects: list[dict[str, Any]] = []
        for script in soup.select("script"):
            script_text = script.string or script.get_text()
            if not script_text:
                continue
            # Match parseJSON('...') — use greedy match to handle apostrophes in JSON values
            for match in re.finditer(r"""parseJSON\('(?P<json>\{.*?)\'\)""", script_text, flags=re.DOTALL):
                raw_json = match.group("json")
                # Unescape JS single-quote escaping
                raw_json = raw_json.replace("\\'", "'")
                try:
                    parsed = json.loads(raw_json)
                except json.JSONDecodeError:
                    # Try finding the last valid JSON closing brace
                    last_brace = raw_json.rfind("}")
                    if last_brace > 0:
                        try:
                            parsed = json.loads(raw_json[:last_brace + 1])
                        except json.JSONDecodeError:
                            continue
                    else:
                        continue
                if isinstance(parsed, dict):
                    objects.append(parsed)
        return objects

    def _extract_amazon_twister_variant_state(self, soup: BeautifulSoup) -> dict[str, dict[str, Any]]:
        state_by_asin: dict[str, dict[str, Any]] = {}
        for script in soup.select('script[data-amazon-twister-responses="true"]'):
            script_text = script.string or script.get_text()
            if not script_text.strip():
                continue
            try:
                payloads = json.loads(script_text)
            except json.JSONDecodeError:
                continue
            if not isinstance(payloads, list):
                continue
            for payload in payloads:
                if not isinstance(payload, dict):
                    continue
                body = payload.get("body")
                if not isinstance(body, str) or not body.strip():
                    continue
                for chunk in body.split("&&&"):
                    entry = chunk.strip()
                    if not entry:
                        continue
                    try:
                        parsed = json.loads(entry)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(parsed, dict):
                        continue
                    asin = parsed.get("ASIN")
                    if not isinstance(asin, str) or not asin.strip():
                        continue
                    content = parsed.get("Value", {}).get("content", {}) if isinstance(parsed.get("Value"), dict) else {}
                    if not isinstance(content, dict):
                        continue
                    variant_state: dict[str, Any] = {}
                    twister_slot_json = content.get("twisterSlotJson")
                    if isinstance(twister_slot_json, dict):
                        price = twister_slot_json.get("price")
                        if price not in (None, "", [], {}):
                            variant_state["price"] = self._extract_amazon_twister_price_text(content) or str(price)
                        is_available = twister_slot_json.get("isAvailable")
                        if isinstance(is_available, bool):
                            variant_state["availability"] = "In Stock" if is_available else "Unavailable"
                    if variant_state:
                        state_by_asin[asin.strip()] = variant_state
        return state_by_asin

    def _extract_amazon_twister_price_text(self, content: dict[str, Any]) -> str | None:
        twister_slot_div = content.get("twisterSlotDiv")
        if not isinstance(twister_slot_div, str) or not twister_slot_div.strip():
            return None
        soup = BeautifulSoup(twister_slot_div, "html.parser")
        price_node = soup.select_one(".a-offscreen, .a-price")
        if price_node is None:
            return None
        text = price_node.get_text(" ", strip=True)
        return text or None

    def _extract_amazon_embedded_price(self, objects: list[dict[str, Any]]) -> str | None:
        def find_price(value: Any) -> str | None:
            if isinstance(value, dict):
                for path in (
                    ("priceToPay", "price"),
                    ("priceToPay", "displayPrice"),
                    ("dealPrice", "price"),
                    ("apexPriceToPay", "price"),
                    ("apexPriceToPay", "displayPrice"),
                    ("price",),
                    ("displayPrice",),
                ):
                    current: Any = value
                    for key in path:
                        if not isinstance(current, dict):
                            current = None
                            break
                        current = current.get(key)
                    if isinstance(current, (str, int, float)) and str(current).strip():
                        return str(current).strip()
                for nested in value.values():
                    nested_price = find_price(nested)
                    if nested_price:
                        return nested_price
            elif isinstance(value, list):
                for item in value:
                    nested_price = find_price(item)
                    if nested_price:
                        return nested_price
            return None

        for obj in objects:
            price = find_price(obj)
            if price:
                return price
        return None

    def _extract_amazon_embedded_variants(self, objects: list[dict[str, Any]]) -> list[dict[str, Any]]:
        variants: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def append_variant(label: str, asin: str) -> None:
            normalized_label = label.strip()
            normalized_asin = asin.strip()
            if not normalized_label or not normalized_asin:
                return
            key = (normalized_label, normalized_asin)
            if key in seen:
                return
            seen.add(key)
            variants.append({"asin": normalized_asin, "label": normalized_label})

        def extract_from_mapping(mapping: Any) -> None:
            if isinstance(mapping, str):
                try:
                    parsed = json.loads(mapping)
                except json.JSONDecodeError:
                    return
                extract_from_mapping(parsed)
                return
            if not isinstance(mapping, dict):
                return
            for label, value in mapping.items():
                if isinstance(value, str):
                    append_variant(str(label), value)
                elif isinstance(value, dict):
                    asin = value.get("asin")
                    if isinstance(asin, str):
                        append_variant(str(label), asin)

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                if "colorToAsin" in value:
                    extract_from_mapping(value["colorToAsin"])
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for obj in objects:
            visit(obj)
        return variants

    def _extract_linkedin_fields(
        self,
        json_data: dict[str, Any],
        resource_type: str,
    ) -> tuple[str | None, str | None, dict[str, Any], dict[str, str]]:
        fields: dict[str, Any] = {}
        sources: dict[str, str] = {}
        title = None
        description = None

        included = json_data.get("included", [])
        if not isinstance(included, list):
            included = []

        if resource_type == "profile":
            for item in included:
                if "Profile" in item.get("$type", ""):
                    first = item.get("firstName", "")
                    last = item.get("lastName", "")
                    title = f"{first} {last}".strip() or None
                    description = item.get("headline")
                    fields["public_identifier"] = item.get("publicIdentifier")
                    fields["entity_urn"] = item.get("entityUrn")
                    sources.update({k: "api_json:voyager" for k in ("title", "description", "public_identifier", "entity_urn")})
                    break

        elif resource_type == "company":
            for item in included:
                item_type = item.get("$type", "")
                if "Company" in item_type or "Organization" in item_type:
                    if item.get("name"):
                        title = item["name"]
                        description = item.get("description") or item.get("tagline")
                        fields["universal_name"] = item.get("universalName")
                        fields["staff_count"] = item.get("staffCount")
                        fields["industry"] = (item.get("industries") or [None])[0]
                        sources.update({k: "api_json:voyager" for k in ("title", "description", "universal_name", "staff_count", "industry")})
                        break

        elif resource_type == "job":
            for item in included:
                if "JobPosting" in item.get("$type", ""):
                    title = item.get("title")
                    desc_obj = item.get("description")
                    if isinstance(desc_obj, dict):
                        description = desc_obj.get("text")
                    elif isinstance(desc_obj, str):
                        description = desc_obj
                    fields["entity_urn"] = item.get("entityUrn")
                    sources.update({k: "api_json:voyager" for k in ("title", "description", "entity_urn")})
                    break

        return title, description, fields, sources

    def _extract_base_html(
        self,
        soup: BeautifulSoup,
        canonical_url: str,
        resource_type: str,
    ) -> dict[str, dict[str, Any]]:
        fields: dict[str, Any] = {}
        sources: dict[str, str] = {}

        def set_field(name: str, value: Any, source: str) -> None:
            if value in (None, "", [], {}):
                return
            fields[name] = value
            sources[name] = source

        def set_if_missing(name: str, value: Any, source: str) -> None:
            if name in fields:
                return
            set_field(name, value, source)

        title_node = soup.select_one("main h1, #ContentPlaceHolder1_maincontentinner h1")
        if title_node is not None:
            set_field("title", title_node.get_text(" ", strip=True), "base_html:h1")

        for script in soup.select('script[type="application/ld+json"]'):
            raw_json = script.string or script.get_text()
            if not raw_json.strip():
                continue
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(data, dict):
                continue
            if data.get("@type") == "Product":
                set_field("title", data.get("name"), "base_html:ldjson")
                set_field("description", data.get("description"), "base_html:ldjson")
                offers = data.get("offers")
                if isinstance(offers, dict):
                    set_field("price_usd", offers.get("price"), "base_html:ldjson:offers.price")
                    set_field("price_currency", offers.get("priceCurrency"), "base_html:ldjson:offers.priceCurrency")

        description_text = fields.get("description")
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc is not None and meta_desc.get("content"):
            meta_description = meta_desc.get("content", "").strip()
            if not description_text and meta_description:
                set_field("description", meta_description, "base_html:meta_description")

            token_rep = re.search(r"Token Rep:\s*([^|]+)", meta_description, flags=re.IGNORECASE)
            price = re.search(r"Price:\s*([^|]+)", meta_description, flags=re.IGNORECASE)
            market_cap = re.search(r"Onchain Market Cap:\s*([^|]+)", meta_description, flags=re.IGNORECASE)
            holders = re.search(r"Holders:\s*([^|]+)", meta_description, flags=re.IGNORECASE)
            contract_status = re.search(r"Contract:\s*([^|]+)", meta_description, flags=re.IGNORECASE)
            transactions = re.search(r"Transactions:\s*([^|]+)", meta_description, flags=re.IGNORECASE)

            if token_rep:
                set_if_missing("token_reputation", token_rep.group(1).strip(), "base_html:meta_description")
            if price:
                set_if_missing("price_usd", price.group(1).strip(), "base_html:meta_description")
            if market_cap:
                set_if_missing("market_cap", market_cap.group(1).strip(), "base_html:meta_description")
            if holders:
                set_if_missing("holders", holders.group(1).strip(), "base_html:meta_description")
            if contract_status:
                set_if_missing("contract_status", contract_status.group(1).strip(), "base_html:meta_description")
            if transactions:
                set_if_missing("transactions", transactions.group(1).strip(), "base_html:meta_description")

        if resource_type == "contract":
            source_code_node = soup.select_one("#verifiedbytecode2, #editor, pre")
            if source_code_node is not None:
                set_field("source_code", source_code_node.get_text("\n", strip=True), "base_html:source_code")

        return {"fields": fields, "sources": sources}

    def _extract_via_platform_adapter(
        self,
        *,
        json_data: dict[str, Any],
        platform: str,
        resource_type: str,
        canonical_url: str,
        content_type: str | None,
    ) -> dict[str, Any] | None:
        fetched = {
            "url": canonical_url,
            "content_type": content_type or "application/json",
            "json_data": json_data,
        }
        record = {
            "platform": platform,
            "resource_type": resource_type,
        }
        if platform == "wikipedia":
            from crawler.platforms.wikipedia import _extract_wikipedia

            return _extract_wikipedia(record, fetched)
        if platform == "base":
            from crawler.platforms.base_chain import _extract_base

            return _extract_base(record, fetched)
        if platform == "linkedin":
            from crawler.platforms.linkedin import _extract_linkedin

            return _extract_linkedin(record, fetched)
        return None

    def _render_generic_document(self, structured: StructuredFields) -> tuple[str, str]:
        text_parts: list[str] = []
        if structured.title:
            text_parts.append(structured.title)
        if structured.description:
            text_parts.append(structured.description)
        for key, value in structured.platform_fields.items():
            if value is not None and value != "" and not isinstance(value, (dict, list)):
                text_parts.append(f"{key}: {value}")

        plain_text = "\n\n".join(text_parts)
        markdown_parts: list[str] = []
        if structured.title:
            markdown_parts.append(f"# {structured.title}")
        if structured.description:
            markdown_parts.append(str(structured.description))
        for key, value in structured.platform_fields.items():
            if value is not None and value != "" and not isinstance(value, (dict, list)):
                markdown_parts.append(f"**{key}**: {value}")
        markdown = "\n\n".join(markdown_parts)
        return plain_text, markdown

    def _description_from_metadata(self, metadata: dict[str, Any]) -> str | None:
        pageprops = metadata.get("pageprops")
        if isinstance(pageprops, dict):
            shortdesc = pageprops.get("wikibase-shortdesc")
            if isinstance(shortdesc, str) and shortdesc.strip():
                return shortdesc.strip()
        return None
