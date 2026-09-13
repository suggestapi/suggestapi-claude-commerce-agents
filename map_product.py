"""Map SuggestAPI UCP/OKS catalog records onto Claude Commerce product dicts.

The shopping agent ranks nothing: SuggestAPI already ranked the hits. This module
only translates fields into the StorefrontBackend Product / ProductDetails shape
from anthropics/commerce-agents (shopping_agent.types).
"""

from __future__ import annotations

from typing import Any

ZERO_DECIMAL = frozenset(
    "BIF CLP DJF GNF JPY KMF KRW MGA PYG RWF UGX VND VUV XAF XOF XPF".split()
)


def from_minor(amount: int | float | None, currency: str | None) -> float:
    if amount is None:
        return 0.0
    exponent = 0 if (currency or "USD").upper() in ZERO_DECIMAL else 2
    return round(float(amount) / (10**exponent), 2)


def to_minor(amount: float | None, currency: str | None) -> int:
    if amount is None:
        return 0
    exponent = 0 if (currency or "USD").upper() in ZERO_DECIMAL else 2
    return int(round(float(amount) * (10**exponent)))


def _plain(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        inner = value.get("plain")
        if isinstance(inner, str) and inner.strip():
            return inner.strip()
    return None


def _first_image(record: dict[str, Any]) -> str | None:
    media = record.get("media")
    if isinstance(media, list):
        for item in media:
            if isinstance(item, dict) and isinstance(item.get("url"), str):
                return item["url"]
    for key in ("image", "image_url"):
        if isinstance(record.get(key), str) and record[key]:
            return record[key]
    images = record.get("images")
    if isinstance(images, list) and images and isinstance(images[0], str):
        return images[0]
    return None


def _category(record: dict[str, Any]) -> str | None:
    categories = record.get("categories")
    if isinstance(categories, list) and categories:
        first = categories[0]
        if isinstance(first, dict) and isinstance(first.get("value"), str):
            return first["value"]
        if isinstance(first, str):
            return first
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    for key in ("category", "product_type"):
        value = metadata.get(key) if metadata else record.get(key)
        if isinstance(value, str) and value:
            return value
    attrs = record.get("attributes")
    if isinstance(attrs, dict) and isinstance(attrs.get("category"), str):
        return attrs["category"]
    return None


def _price_currency(record: dict[str, Any]) -> tuple[float, str]:
    price_range = record.get("price_range")
    if isinstance(price_range, dict) and isinstance(price_range.get("min"), dict):
        money = price_range["min"]
        currency = str(money.get("currency") or "USD")
        return from_minor(money.get("amount"), currency), currency
    price = record.get("price")
    if isinstance(price, dict):
        currency = str(price.get("currency") or "USD")
        amount = price.get("amount")
        if isinstance(amount, (int, float)):
            return float(amount), currency
    variant = _variants(record)
    if variant:
        money = variant[0].get("price") if isinstance(variant[0].get("price"), dict) else {}
        currency = str(money.get("currency") or "USD")
        return from_minor(money.get("amount"), currency), currency
    return 0.0, "USD"


def _variants(record: dict[str, Any]) -> list[dict[str, Any]]:
    raw = record.get("variants")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict) and item.get("id")]


def _in_stock(record: dict[str, Any]) -> bool:
    variants = _variants(record)
    if variants:
        flags = []
        for variant in variants:
            availability = variant.get("availability")
            if isinstance(availability, dict) and "available" in availability:
                flags.append(bool(availability["available"]))
        if flags:
            return any(flags)
    availability = record.get("availability")
    if isinstance(availability, str):
        return availability.lower() != "out_of_stock"
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("availability"), str):
        return str(metadata["availability"]).lower() != "out_of_stock"
    return True


def _option_values(variant: dict[str, Any]) -> dict[str, str]:
    raw = variant.get("option_values")
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v is not None}
    return {}


def _family_options(variants: list[dict[str, Any]]) -> dict[str, list[str]]:
    collected: dict[str, list[str]] = {}
    for variant in variants:
        for key, value in _option_values(variant).items():
            bucket = collected.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
    return collected


def ucp_to_product(record: dict[str, Any], *, details: bool = False) -> dict[str, Any]:
    product_id = str(record.get("id") or "")
    title = str(record.get("title") or product_id)
    description = _plain(record.get("description")) or _plain(record.get("summary"))
    price, currency = _price_currency(record)
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    variants = _variants(record)
    distinct = [v for v in variants if str(v.get("id")) != product_id]
    is_family = len(distinct) >= 1 and len(variants) > 1

    product: dict[str, Any] = {
        "product_id": product_id,
        "title": title,
        "brand": metadata.get("vendor") if isinstance(metadata.get("vendor"), str) else None,
        "price": price,
        "currency": currency,
        "image_url": _first_image(record),
        "category": _category(record),
        "labels": [tag for tag in (record.get("tags") or []) if isinstance(tag, str)],
        "attributes": {},
        "in_stock": _in_stock(record),
        "short_description": description,
        "options": _family_options(variants) if is_family else {},
        "option_values": {},
        "variant_of": None,
    }

    if details:
        product["long_description"] = description
        product["specs"] = {
            str(k): str(v)
            for k, v in metadata.items()
            if v is not None and k not in {"availability"}
        }
        product["review_highlights"] = []
        product["variants"] = []
        if is_family:
            product["variants"] = [
                {
                    "product_id": str(variant["id"]),
                    "title": str(variant.get("title") or title),
                    "brand": product["brand"],
                    "price": from_minor(
                        (variant.get("price") or {}).get("amount") if isinstance(variant.get("price"), dict) else None,
                        (variant.get("price") or {}).get("currency") if isinstance(variant.get("price"), dict) else currency,
                    )
                    if isinstance(variant.get("price"), dict)
                    else price,
                    "currency": (
                        str(variant["price"]["currency"])
                        if isinstance(variant.get("price"), dict) and variant["price"].get("currency")
                        else currency
                    ),
                    "image_url": product["image_url"],
                    "category": product["category"],
                    "labels": [],
                    "attributes": {},
                    "in_stock": bool((variant.get("availability") or {}).get("available", True))
                    if isinstance(variant.get("availability"), dict)
                    else True,
                    "short_description": _plain(variant.get("description")) or description,
                    "options": {},
                    "option_values": _option_values(variant),
                    "variant_of": product_id,
                }
                for variant in variants
            ]
            in_stock_prices = [row["price"] for row in product["variants"] if row["in_stock"]]
            if in_stock_prices:
                product["price"] = min(in_stock_prices)
    return product


def oks_document_to_ucp_shape(document: dict[str, Any]) -> dict[str, Any]:
    """Lift a GET /oks/{tenant}/products/{id} document toward the UCP product shape."""
    if "price_range" in document and "variants" in document:
        return document
    price = document.get("price") if isinstance(document.get("price"), dict) else {}
    currency = str(price.get("currency") or "USD")
    amount = price.get("amount")
    minor = to_minor(float(amount), currency) if isinstance(amount, (int, float)) else 0
    return {
        "id": document.get("id"),
        "title": document.get("title"),
        "description": {"plain": _plain(document.get("description")) or _plain(document.get("summary")) or ""},
        "url": document.get("url"),
        "media": [{"type": "image", "url": document["image"]}] if isinstance(document.get("image"), str) else [],
        "price_range": {"min": {"amount": minor, "currency": currency}, "max": {"amount": minor, "currency": currency}},
        "variants": [
            {
                "id": document.get("id"),
                "title": document.get("title"),
                "price": {"amount": minor, "currency": currency},
                "availability": {
                    "available": str(document.get("availability") or "in_stock").lower() != "out_of_stock"
                },
            }
        ],
        "metadata": {
            "availability": document.get("availability"),
            "vendor": (document.get("attributes") or {}).get("vendor")
            if isinstance(document.get("attributes"), dict)
            else None,
            "product_type": (document.get("attributes") or {}).get("product_type")
            if isinstance(document.get("attributes"), dict)
            else None,
            "category": (document.get("attributes") or {}).get("category")
            if isinstance(document.get("attributes"), dict)
            else None,
        },
        "tags": (document.get("attributes") or {}).get("tags")
        if isinstance(document.get("attributes"), dict)
        else [],
    }


def search_request_body(query: str, filters: dict[str, Any] | None, limit: int) -> dict[str, Any]:
    body: dict[str, Any] = {"query": query, "pagination": {"limit": max(1, limit)}}
    if not filters:
        return body
    ucp_filters: dict[str, Any] = {}
    category = filters.get("category")
    if isinstance(category, str) and category.strip():
        ucp_filters["categories"] = [category.strip()]
    min_price = filters.get("min_price")
    max_price = filters.get("max_price")
    currency = "USD"
    if min_price is not None or max_price is not None:
        price: dict[str, int] = {}
        if isinstance(min_price, (int, float)):
            price["min"] = to_minor(float(min_price), currency)
        if isinstance(max_price, (int, float)):
            price["max"] = to_minor(float(max_price), currency)
        ucp_filters["price"] = price
    if ucp_filters:
        body["filters"] = ucp_filters
    attributes = filters.get("attributes")
    if isinstance(attributes, dict) and attributes:
        # ponytail: UCP catalog search has no generic attribute filter; fold into query.
        extra = " ".join(f"{key} {value}" for key, value in attributes.items() if value)
        if extra:
            body["query"] = f"{query} {extra}".strip()
    return body


def apply_client_filters(products: list[dict[str, Any]], filters: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not filters:
        return products
    min_rating = filters.get("min_rating")
    if isinstance(min_rating, (int, float)):
        products = [
            product
            for product in products
            if product.get("rating") is None or float(product["rating"]) >= float(min_rating)
        ]
    sort = filters.get("sort") or "relevance"
    if sort == "price_asc":
        products = sorted(products, key=lambda product: product.get("price") or 0)
    elif sort == "price_desc":
        products = sorted(products, key=lambda product: product.get("price") or 0, reverse=True)
    elif sort == "rating":
        products = sorted(products, key=lambda product: product.get("rating") or 0, reverse=True)
    return products
