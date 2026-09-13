"""Deterministic shopping-agent harness over StorefrontBackend.

This is the loop Claude Commerce runs for catalog tools, without an LLM:
search → inspect results → cart → merchant checkout handoff.
"""

from __future__ import annotations

from typing import Any

from commerce_types import Cart, ShoppingSessionContext
from suggestapi_backend import SuggestAPIStorefront, Unavailable


def dump_product(product: Any) -> dict[str, Any]:
    return product.model_dump() if hasattr(product, "model_dump") else dict(product)


def dump_cart(cart: Cart) -> dict[str, Any]:
    return {
        "currency": cart.currency,
        "item_count": cart.item_count,
        "subtotal": cart.subtotal,
        "items": [
            {
                "product_id": item.product_id,
                "title": item.title,
                "price": item.price,
                "quantity": item.quantity,
                "image_url": item.image_url,
            }
            for item in cart.items
        ],
    }


async def run_turn(
    backend: SuggestAPIStorefront,
    session: ShoppingSessionContext,
    message: str,
) -> dict[str, Any]:
    text = message.strip()
    lowered = text.lower()
    cart = await backend.get_cart(session)

    if lowered in {"checkout", "buy", "pay"} or lowered.startswith("checkout"):
        handoffs = await backend.checkout_handoff(session, cart)
        return {
            "action": "checkout",
            "reply": "Continue on the merchant storefront to complete purchase."
            if handoffs
            else "Add something to the cart before checkout.",
            "products": [],
            "cart": dump_cart(cart),
            "handoffs": [{"url": item.url, "label": item.label} for item in handoffs],
        }

    if lowered in {"clear cart", "clear", "empty cart"}:
        cart = await backend.clear_cart(session)
        return {
            "action": "clear_cart",
            "reply": "Cart emptied.",
            "products": [],
            "cart": dump_cart(cart),
            "handoffs": [],
        }

    if lowered.startswith("remove "):
        product_id = text.split(None, 1)[1].strip()
        cart = await backend.remove_from_cart(session, product_id)
        return {
            "action": "remove_from_cart",
            "reply": f"Removed {product_id} from the cart.",
            "products": [],
            "cart": dump_cart(cart),
            "handoffs": [],
        }

    if lowered.startswith("add "):
        product_id = text.split(None, 1)[1].strip()
        try:
            cart = await backend.add_to_cart(session, product_id, 1)
            reply = f"Added {product_id} to the cart."
            error = None
        except Unavailable:
            reply = f"{product_id} is sold out."
            error = "unavailable"
        except KeyError:
            reply = f"No product {product_id} in this session. Search first."
            error = "unknown_product"
        return {
            "action": "add_to_cart",
            "reply": reply,
            "error": error,
            "products": [],
            "cart": dump_cart(cart),
            "handoffs": [],
        }

    products = await backend.search_products(session, text, limit=8)
    titles = ", ".join(product.title for product in products) or "nothing matching"
    return {
        "action": "search_products",
        "reply": f"SuggestAPI ranked {len(products)} product(s): {titles}.",
        "products": [dump_product(product) for product in products],
        "cart": dump_cart(cart),
        "handoffs": [],
    }
