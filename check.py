#!/usr/bin/env python3
"""Self-check for Claude Commerce ↔ SuggestAPI field mapping. No network."""

from __future__ import annotations

from trace import collect, request, response
from map_product import (
    apply_client_filters,
    from_minor,
    oks_document_to_ucp_shape,
    search_request_body,
    to_minor,
    ucp_to_product,
)


def main() -> None:
    assert to_minor(18.0, "USD") == 1800
    assert from_minor(1800, "USD") == 18.0
    assert to_minor(1500, "JPY") == 1500

    plain = ucp_to_product(
        {
            "id": "sku_oak_case",
            "title": "Oak Wine Case",
            "description": {"plain": "Six-bottle oak case"},
            "price_range": {"min": {"amount": 8900, "currency": "USD"}, "max": {"amount": 8900, "currency": "USD"}},
            "media": [{"type": "image", "url": "https://cdn.example/oak.jpg"}],
            "categories": [{"value": "wine-storage", "taxonomy": "merchant"}],
            "variants": [
                {
                    "id": "sku_oak_case",
                    "title": "Oak Wine Case",
                    "price": {"amount": 8900, "currency": "USD"},
                    "availability": {"available": True},
                }
            ],
            "metadata": {"vendor": "Cellar Co", "availability": "in_stock"},
            "tags": ["oak"],
        }
    )
    assert plain["product_id"] == "sku_oak_case"
    assert plain["price"] == 89.0
    assert plain["in_stock"] is True
    assert plain["options"] == {}
    assert plain["image_url"] == "https://cdn.example/oak.jpg"
    assert plain["brand"] == "Cellar Co"
    assert plain["category"] == "wine-storage"

    family = ucp_to_product(
        {
            "id": "tee",
            "title": "Trail Tee",
            "description": {"plain": "Merino tee"},
            "price_range": {"min": {"amount": 2400, "currency": "USD"}, "max": {"amount": 2600, "currency": "USD"}},
            "variants": [
                {
                    "id": "tee-s",
                    "title": "Trail Tee S",
                    "price": {"amount": 2400, "currency": "USD"},
                    "availability": {"available": True},
                    "option_values": {"size": "S"},
                },
                {
                    "id": "tee-l",
                    "title": "Trail Tee L",
                    "price": {"amount": 2600, "currency": "USD"},
                    "availability": {"available": False},
                    "option_values": {"size": "L"},
                },
            ],
            "metadata": {},
        },
        details=True,
    )
    assert family["options"] == {"size": ["S", "L"]}
    assert family["price"] == 24.0
    assert family["in_stock"] is True
    assert len(family["variants"]) == 2
    assert family["variants"][1]["variant_of"] == "tee"
    assert family["variants"][1]["in_stock"] is False

    body = search_request_body(
        "hiking shoes",
        {"category": "footwear", "min_price": 40, "max_price": 180, "attributes": {"waterproof": "true"}},
        8,
    )
    assert body["query"] == "hiking shoes waterproof true"
    assert body["filters"]["categories"] == ["footwear"]
    assert body["filters"]["price"] == {"min": 4000, "max": 18000}
    assert body["pagination"]["limit"] == 8

    sorted_rows = apply_client_filters(
        [{"price": 20, "rating": 3}, {"price": 10, "rating": 5}],
        {"sort": "price_asc", "min_rating": 4},
    )
    assert sorted_rows == [{"price": 10, "rating": 5}]

    lifted = oks_document_to_ucp_shape(
        {
            "id": "sku_pairing_box",
            "title": "Pairing Box",
            "summary": "Tasting flight",
            "price": {"amount": 42, "currency": "USD"},
            "availability": "in_stock",
            "image": "https://cdn.example/box.jpg",
            "attributes": {"vendor": "Cellar Co", "category": "gifts"},
        }
    )
    mapped = ucp_to_product(lifted)
    assert mapped["product_id"] == "sku_pairing_box"
    assert mapped["price"] == 42.0
    assert mapped["category"] == "gifts"
    assert mapped["image_url"] == "https://cdn.example/box.jpg"
    with collect() as calls:
        request({"tool": "search_products", "query": "oak"})
        response([{"product_id": "sku_oak_case"}])
    assert calls[0]["kind"] == "request"
    assert calls[0]["payload"]["query"] == "oak"
    assert calls[1]["payload"][0]["product_id"] == "sku_oak_case"

    print("ok")


if __name__ == "__main__":
    main()
