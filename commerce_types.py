"""Minimal shopping-agent records so this starter runs without commerce-agents installed."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


class Unavailable(Exception):
    pass


class StorefrontBackend:
    pass


@dataclass
class Product:
    product_id: str
    title: str
    brand: str | None = None
    price: float = 0.0
    currency: str = "USD"
    rating: float | None = None
    review_count: int | None = None
    image_url: str | None = None
    category: str | None = None
    labels: list[str] = field(default_factory=list)
    attributes: dict[str, str] = field(default_factory=dict)
    in_stock: bool = True
    short_description: str | None = None
    options: dict[str, list[str]] = field(default_factory=dict)
    option_values: dict[str, str] = field(default_factory=dict)
    variant_of: str | None = None

    @property
    def has_options(self) -> bool:
        return bool(self.options)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)

    def model_copy(self, update: dict[str, Any] | None = None) -> Product:
        return replace(self, **(update or {}))


@dataclass
class ProductDetails(Product):
    long_description: str | None = None
    specs: dict[str, str] = field(default_factory=dict)
    review_highlights: list[str] = field(default_factory=list)
    variants: list[Product] = field(default_factory=list)


@dataclass
class SearchFilters:
    category: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    min_rating: float | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    sort: str = "relevance"

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CartItem:
    product_id: str
    title: str
    price: float
    quantity: int = 1
    image_url: str | None = None
    option_values: dict[str, str] = field(default_factory=dict)
    variant_of: str | None = None

    def model_copy(self, update: dict[str, Any] | None = None) -> CartItem:
        return replace(self, **(update or {}))

    @property
    def line_total(self) -> float:
        return round(self.price * self.quantity, 2)


@dataclass
class Cart:
    items: list[CartItem] = field(default_factory=list)
    currency: str = "USD"

    @property
    def item_count(self) -> int:
        return sum(item.quantity for item in self.items)

    @property
    def subtotal(self) -> float:
        return round(sum(item.line_total for item in self.items), 2)


@dataclass
class CheckoutHandoff:
    url: str
    label: str | None = None
    seller: str | None = None


@dataclass
class UserPreferences:
    user_id: str
    display_name: str | None = None
    loyalty_tier: str | None = None
    default_location: str | None = None
    preferences: dict[str, str] = field(default_factory=dict)


@dataclass
class Order:
    order_id: str
    status: str = "processing"
    items: list[Any] = field(default_factory=list)
    total: float = 0.0
    currency: str = "USD"


@dataclass
class Policy:
    policy_id: str
    title: str
    category: str | None = None
    content: str = ""


@dataclass
class FulfillmentOption:
    method: str = "shipping"
    eta: str = ""
    fee: float = 0.0
    location: str | None = None


@dataclass
class ShoppingSessionContext:
    session_id: str
    user_id: str = "guest"


def from_row(cls: type, row: dict[str, Any]) -> Any:
    names = getattr(cls, "model_fields", None)
    if names is not None:
        return cls.model_validate({key: value for key, value in row.items() if key in names})
    names = getattr(cls, "__dataclass_fields__", {})
    return cls(**{key: value for key, value in row.items() if key in names})
