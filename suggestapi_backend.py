"""Claude Commerce StorefrontBackend over SuggestAPI.

Drop this class into anthropics/commerce-agents in place of the retail mock
catalog. SuggestAPI owns retrieval and ranking; Claude owns comparison,
presentation, and cart reasoning. Checkout is a merchant storefront handoff.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from map_product import (
    apply_client_filters,
    oks_document_to_ucp_shape,
    search_request_body,
    ucp_to_product,
)

try:
    from shopping_agent import (
        Cart,
        CartItem,
        CheckoutHandoff,
        FulfillmentOption,
        Order,
        Policy,
        Product,
        ProductDetails,
        SearchFilters,
        ShoppingSessionContext,
        StorefrontBackend,
        Unavailable,
        UserPreferences,
    )
except ImportError:
    from commerce_types import (
        Cart,
        CartItem,
        CheckoutHandoff,
        FulfillmentOption,
        Order,
        Policy,
        Product,
        ProductDetails,
        SearchFilters,
        ShoppingSessionContext,
        StorefrontBackend,
        Unavailable,
        UserPreferences,
    )
from commerce_types import from_row
from trace import request, response


class SuggestAPIStorefront(StorefrontBackend):
    def __init__(
        self,
        tenant: str,
        base_url: str | None = None,
        api_key: str | None = None,
        fixtures: dict[str, Any] | None = None,
    ) -> None:
        self.tenant = tenant
        self.base_url = (base_url or os.environ.get("SUGGESTAPI_BASE_URL") or "https://agent.suggestapi.com").rstrip(
            "/"
        )
        self.api_key = api_key if api_key is not None else os.environ.get("SUGGESTAPI_API_KEY")
        self._fixtures = fixtures
        self._carts: dict[str, dict[str, CartItem]] = {}
        self._products: dict[str, Product] = {}

    def _headers(self) -> dict[str, str]:
        headers = {"accept": "application/json", "content-type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _request(self, method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._fixtures is not None:
            return self._fixture_request(method, path, body)
        url = f"{self.base_url}{path}"
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read().decode()
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return {}
            raise
        if not payload:
            return {}
        parsed = json.loads(payload)
        return parsed if isinstance(parsed, dict) else {}

    def _fixture_request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        fixtures = self._fixtures or {}
        if method == "POST" and path.endswith("/catalog/search"):
            query = str((body or {}).get("query") or "")
            tokens = [token for token in query.lower().split() if len(token) > 2]
            products = []
            for product in fixtures.get("products") or []:
                haystack = json.dumps(product).lower()
                if not tokens or any(token in haystack for token in tokens):
                    products.append(product)
            return {"products": products}
        if method == "GET" and "/products/" in path:
            product_id = urllib.parse.unquote(path.rsplit("/", 1)[-1])
            document = (fixtures.get("lookups") or {}).get(product_id)
            if not document:
                return {}
            return {"ok": True, "data": document}
        if method == "POST" and path.endswith("/checkout_sessions"):
            continue_url = str(fixtures.get("checkout_continue") or "/checkout")
            base = continue_url.split("?", 1)[0]
            items = (body or {}).get("items") or []
            packed = ",".join(
                f"{item.get('id')}:{item.get('quantity')}"
                for item in items
                if isinstance(item, dict) and item.get("id")
            )
            if packed:
                continue_url = f"{base}?items={packed}"
            return {"continue_url": continue_url, "status": "not_ready_for_payment"}
        if method == "GET" and path.endswith("/policies"):
            return {"data": {"items": fixtures.get("policies") or []}}
        return {}

    def _remember(self, product: Product) -> Product:
        self._products[product.product_id] = product
        return product

    def _as_product(self, record: dict[str, Any], *, details: bool) -> Product | ProductDetails:
        mapped = ucp_to_product(record, details=details)
        model = from_row(ProductDetails if details else Product, mapped)
        self._remember(model)
        if details and isinstance(model, ProductDetails):
            coerced: list[Product] = []
            for variant in model.variants:
                record = variant if isinstance(variant, Product) else from_row(Product, variant)
                coerced.append(self._remember(record))
            model.variants = coerced
        return model

    async def search_products(
        self,
        session: ShoppingSessionContext,
        query: str,
        filters: SearchFilters | None = None,
        limit: int = 8,
    ) -> list[Product]:
        del session
        filter_payload = filters.model_dump() if filters is not None else None
        body = search_request_body(query, filter_payload, limit)
        request(
            {
                "tool": "search_products",
                "via": "fixtures" if self._fixtures is not None else self.base_url,
                "tenant": self.tenant,
                "query": query,
                "filters": filter_payload,
                "limit": limit,
            }
        )
        payload = self._request("POST", f"/oks/{urllib.parse.quote(self.tenant)}/catalog/search", body)
        records = payload.get("products") if isinstance(payload.get("products"), list) else []
        mapped = apply_client_filters(
            [
                ucp_to_product(record, details=False)
                for record in records
                if isinstance(record, dict) and record.get("id")
            ],
            filter_payload,
        )[:limit]
        products: list[Product] = []
        for row in mapped:
            product = from_row(Product, row)
            self._remember(product)
            products.append(product)
        response(products)
        return products

    async def get_product_details(
        self, session: ShoppingSessionContext, product_id: str
    ) -> ProductDetails | None:
        del session
        encoded = urllib.parse.quote(product_id, safe="")
        request(
            {
                "tool": "get_product_details",
                "via": "fixtures" if self._fixtures is not None else self.base_url,
                "tenant": self.tenant,
                "product_id": product_id,
            }
        )
        payload = self._request("GET", f"/oks/{urllib.parse.quote(self.tenant)}/products/{encoded}")
        document = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if not isinstance(document, dict) or not document.get("id"):
            cached = self._products.get(product_id)
            details = from_row(ProductDetails, cached.model_dump()) if cached else None
            response(details)
            return details
        details = self._as_product(oks_document_to_ucp_shape(document), details=True)
        response(details)
        return details  # type: ignore[return-value]

    def _cart(self, session_id: str) -> Cart:
        items = list(self._carts.get(session_id, {}).values())
        currency = "USD"
        cached = next((self._products[item.product_id] for item in items if item.product_id in self._products), None)
        if cached is not None:
            currency = cached.currency
        return Cart(items=items, currency=currency)

    async def get_cart(self, session: ShoppingSessionContext) -> Cart:
        return self._cart(session.session_id)

    async def add_to_cart(self, session: ShoppingSessionContext, product_id: str, quantity: int) -> Cart:
        request({"tool": "add_to_cart", "product_id": product_id, "quantity": quantity})
        product = self._products.get(product_id) or await self.get_product_details(session, product_id)
        if product is None:
            response({"error": "unknown_product", "product_id": product_id})
            raise KeyError(product_id)
        if product.has_options:
            response({"error": "needs_variant", "product_id": product_id})
            raise KeyError(product_id)
        if not product.in_stock:
            response({"error": "unavailable", "product_id": product_id})
            raise Unavailable(product_id)
        lines = self._carts.setdefault(session.session_id, {})
        existing = lines.get(product_id)
        qty = quantity + (existing.quantity if existing else 0)
        lines[product_id] = CartItem(
            product_id=product.product_id,
            title=product.title,
            price=product.price,
            quantity=qty,
            image_url=product.image_url,
            option_values=product.option_values,
            variant_of=product.variant_of,
        )
        cart = self._cart(session.session_id)
        response(cart)
        return cart

    async def update_cart_item(self, session: ShoppingSessionContext, product_id: str, quantity: int) -> Cart:
        lines = self._carts.setdefault(session.session_id, {})
        if product_id not in lines:
            return self._cart(session.session_id)
        item = lines[product_id]
        lines[product_id] = item.model_copy(update={"quantity": quantity})
        return self._cart(session.session_id)

    async def remove_from_cart(self, session: ShoppingSessionContext, product_id: str) -> Cart:
        request({"tool": "remove_from_cart", "product_id": product_id})
        self._carts.setdefault(session.session_id, {}).pop(product_id, None)
        cart = self._cart(session.session_id)
        response(cart)
        return cart

    async def clear_cart(self, session: ShoppingSessionContext) -> Cart:
        request({"tool": "clear_cart"})
        self._carts[session.session_id] = {}
        cart = self._cart(session.session_id)
        response(cart)
        return cart

    async def get_preferences(self, session: ShoppingSessionContext) -> UserPreferences:
        return UserPreferences(user_id=session.user_id, display_name=None)

    async def checkout_handoff(self, session: ShoppingSessionContext, cart: Cart) -> list[CheckoutHandoff]:
        del session
        if not cart.items:
            request({"tool": "checkout", "items": []})
            response([])
            return []
        items = [{"id": item.product_id, "quantity": item.quantity} for item in cart.items]
        request(
            {
                "tool": "checkout",
                "via": "fixtures" if self._fixtures is not None else self.base_url,
                "items": items,
            }
        )
        payload = self._request(
            "POST",
            f"/oks/{urllib.parse.quote(self.tenant)}/checkout_sessions",
            {"items": items},
        )
        continue_url = payload.get("continue_url")
        if not continue_url:
            for link in payload.get("links") or []:
                if isinstance(link, dict) and link.get("type") in {"continue", "buyer_payment"} and link.get("url"):
                    continue_url = link["url"]
                    break
        if not isinstance(continue_url, str) or not continue_url:
            response([])
            return []
        handoffs = [CheckoutHandoff(url=continue_url, label="Continue on merchant checkout")]
        response(handoffs)
        return handoffs

    async def get_orders(self, session: ShoppingSessionContext, limit: int = 5) -> list[Order]:
        del session, limit
        return []

    async def get_order(self, session: ShoppingSessionContext, order_id: str) -> Order | None:
        del session, order_id
        return None

    async def search_policies(self, session: ShoppingSessionContext, query: str) -> list[Policy]:
        del session
        payload = self._request("GET", f"/oks/{urllib.parse.quote(self.tenant)}/policies")
        items = (payload.get("data") or {}).get("items") if isinstance(payload.get("data"), dict) else []
        if not isinstance(items, list):
            return []
        tokens = [token for token in query.lower().split() if token]
        policies: list[Policy] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            haystack = " ".join(
                str(item.get(key) or "") for key in ("title", "summary", "description")
            ).lower()
            if tokens and not all(token in haystack for token in tokens):
                continue
            policies.append(
                Policy(
                    policy_id=str(item["id"]),
                    title=str(item.get("title") or item["id"]),
                    category=str(item.get("type") or "policy"),
                    content=str(item.get("description") or item.get("summary") or ""),
                )
            )
        return policies

    async def get_fulfillment_options(
        self, session: ShoppingSessionContext, product_ids: list[str]
    ) -> list[FulfillmentOption]:
        del session, product_ids
        return [FulfillmentOption(method="shipping", eta="See merchant checkout", fee=0.0)]
