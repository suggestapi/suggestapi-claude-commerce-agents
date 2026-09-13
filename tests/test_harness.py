#!/usr/bin/env python3
"""Integration tests for the shopping-agent harness. No network, no LLM."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from commerce_types import SearchFilters, ShoppingSessionContext  # noqa: E402
from harness import run_turn  # noqa: E402
from suggestapi_backend import SuggestAPIStorefront  # noqa: E402
from trace import case, done, intro, setup, step  # noqa: E402

FIXTURES = json.loads((Path(__file__).with_name("fixtures.json")).read_text())


def session() -> ShoppingSessionContext:
    return ShoppingSessionContext(session_id="s1", user_id="guest")


def backend_from_fixtures() -> SuggestAPIStorefront:
    return SuggestAPIStorefront(tenant="demo.suggestapi.com", fixtures=FIXTURES)


class CatalogHandler(BaseHTTPRequestHandler):
    catalog = FIXTURES

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if "/products/" in self.path and not self.path.endswith("/products"):
            product_id = self.path.rsplit("/", 1)[-1]
            document = (self.catalog.get("lookups") or {}).get(product_id)
            if not document:
                self._json({}, 404)
                return
            self._json({"ok": True, "data": document})
            return
        if self.path.endswith("/policies"):
            self._json({"data": {"items": self.catalog.get("policies") or []}})
            return
        self._json({"error": "not_found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.endswith("/catalog/search"):
            query = str(body.get("query") or "")
            tokens = [token for token in query.lower().split() if len(token) > 2]
            products = []
            for product in self.catalog.get("products") or []:
                haystack = json.dumps(product).lower()
                if not tokens or any(token in haystack for token in tokens):
                    products.append(product)
            self._json({"products": products})
            return
        if self.path.endswith("/checkout_sessions"):
            packed = ",".join(
                f"{item.get('id')}:{item.get('quantity')}"
                for item in (body.get("items") or [])
                if isinstance(item, dict) and item.get("id")
            )
            continue_url = str(self.catalog.get("checkout_continue") or "/checkout")
            base = continue_url.split("?", 1)[0]
            if packed:
                continue_url = f"{base}?items={packed}"
            self._json({"continue_url": continue_url, "status": "not_ready_for_payment"})
            return
        self._json({"error": "not_found"}, 404)


def serve_catalog() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), CatalogHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, f"http://{host}:{port}"


async def test_search_ranks_catalog() -> None:
    case(
        1,
        "search_products ranks catalog hits",
        testing="Claude Commerce calls search_products. SuggestAPI ranks; Claude does not.",
        do='search_products(query="oak", limit=8) against the guest fixture catalog',
        expect="one hit: sku_oak_case, Reserve Oak Case, $189.00, in stock",
    )
    store = backend_from_fixtures()
    products = await store.search_products(session(), "oak", limit=8)
    assert [product.product_id for product in products] == ["sku_oak_case"]
    assert products[0].price == 189.0
    assert products[0].title == "Reserve Oak Case"


async def test_price_filter_and_details() -> None:
    case(
        2,
        "filters then get_product_details",
        testing="Search filters ride on the catalog call. Details hydrate one id Claude already saw.",
        do="search_products(query=\"box\", max_price=150), then get_product_details(sku_oak_case)",
        expect="search returns only Chef Pairing Box ($124); details return Reserve Oak Case at $189",
    )
    store = backend_from_fixtures()
    filters = SearchFilters(max_price=150)
    products = await store.search_products(session(), "box", filters=filters, limit=8)
    assert [product.product_id for product in products] == ["sku_pairing_box"]
    step(
        "get_product_details",
        do="look up sku_oak_case (not in the filtered search set)",
        expect="full record, price $189.00",
    )
    details = await store.get_product_details(session(), "sku_oak_case")
    assert details is not None
    assert details.product_id == "sku_oak_case"
    assert details.price == 189.0


async def test_harness_search_cart_checkout() -> None:
    case(
        3,
        "shopper turn: search → cart → checkout",
        testing="The same loop as the browser demo. No LLM. Checkout does not capture payment.",
        do="shopper messages: search, add sku_oak_case, checkout",
        expect="ranked gifts, cart subtotal $189, merchant continue_url with that line item",
    )
    store = backend_from_fixtures()
    ctx = session()
    step(
        "search_products",
        do='shopper says "featured cellar gift"',
        expect="Reserve Oak Case and Chef Pairing Box in the ranked list",
    )
    searched = await run_turn(store, ctx, "featured cellar gift")
    assert searched["action"] == "search_products"
    ids = {product["product_id"] for product in searched["products"]}
    assert "sku_oak_case" in ids
    assert "sku_pairing_box" in ids

    step(
        "add_to_cart",
        do="add sku_oak_case quantity 1",
        expect="cart item_count 1, subtotal $189.00",
    )
    added = await run_turn(store, ctx, "add sku_oak_case")
    assert added["error"] is None
    assert added["cart"]["item_count"] == 1
    assert added["cart"]["subtotal"] == 189.0

    step(
        "checkout",
        do="handoff the session cart to merchant checkout",
        expect="continue_url /checkout?items=sku_oak_case:1, not a payment capture",
    )
    checked = await run_turn(store, ctx, "checkout")
    assert checked["action"] == "checkout"
    assert checked["handoffs"]
    assert checked["handoffs"][0]["url"] == "/checkout?items=sku_oak_case:1"


async def test_harness_unavailable() -> None:
    case(
        4,
        "unavailable stays out of the cart",
        testing="add_to_cart must refuse an out-of-stock id. SuggestAPI reports in_stock=false.",
        do='search "sold out", then add sku_sold_out',
        expect="tool response error=unavailable; cart unchanged",
    )
    store = backend_from_fixtures()
    ctx = session()
    step(
        "search_products",
        do='shopper says "sold out"',
        expect="Library Vintage with in_stock false",
    )
    await run_turn(store, ctx, "sold out")
    step(
        "add_to_cart",
        do="add sku_sold_out",
        expect="response error unavailable; no cart line",
    )
    added = await run_turn(store, ctx, "add sku_sold_out")
    assert added["error"] == "unavailable"


async def test_http_catalog_harness() -> None:
    case(
        5,
        "HTTP catalog (loopback SuggestAPI)",
        testing="Same tools over HTTP POST /catalog/search, not in-memory fixtures.",
        do="search Chef, add sku_pairing_box, checkout",
        expect="Chef Pairing Box at $124, then a merchant continue_url",
    )
    server, origin = serve_catalog()
    try:
        store = SuggestAPIStorefront(tenant="demo.suggestapi.com", base_url=origin)
        ctx = session()
        step(
            "search_products",
            do='shopper says "Chef" via loopback HTTP',
            expect="sku_pairing_box first",
        )
        searched = await run_turn(store, ctx, "Chef")
        assert searched["products"][0]["product_id"] == "sku_pairing_box"
        step(
            "add_to_cart",
            do="add sku_pairing_box",
            expect="cart subtotal $124.00",
        )
        await run_turn(store, ctx, "add sku_pairing_box")
        step(
            "checkout",
            do="handoff cart over HTTP checkout_sessions",
            expect="a continue_url",
        )
        checked = await run_turn(store, ctx, "checkout")
        assert checked["handoffs"][0]["url"]
    finally:
        server.shutdown()
        server.server_close()


def main() -> None:
    setup()
    intro(
        "SuggestAPI + Claude Commerce harness",
        "Guest catalog: tests/fixtures.json   (no network, no LLM, no API keys)",
        "Each test: what we test, what we do, what we expect, then request / response.",
    )

    async def run() -> None:
        await test_search_ranks_catalog()
        await test_price_filter_and_details()
        await test_harness_search_cart_checkout()
        await test_harness_unavailable()
        await test_http_catalog_harness()

    asyncio.run(run())
    done("ok  — 5 checks. Next: python3 demo/server.py   then open the printed URL")


if __name__ == "__main__":
    main()
