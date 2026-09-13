# SuggestAPI + Claude Commerce Agents

A starter [`StorefrontBackend`](https://github.com/anthropics/commerce-agents/blob/main/shopping-agent/core/shopping_agent/backend.py) that points [Anthropic's commerce agents](https://github.com/anthropics/commerce-agents) at SuggestAPI for product discovery.

Claude Commerce already calls `search_products` and `get_product_details`. This adapter implements those methods: SuggestAPI returns ranked catalog results, and Claude compares, presents, and fills the cart.

Checkout stays on the merchant storefront. SuggestAPI does not take payment.

## Quick start

```bash
python3 check.py
```

Then clone Anthropic's reference shopping agent and swap the mock catalog for this backend:

```bash
git clone https://github.com/anthropics/commerce-agents.git
cd commerce-agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Put this repo on `PYTHONPATH`, or copy `map_product.py` and `suggestapi_backend.py` next to the retail API. Replace `MockRetail` with:

```python
from suggestapi_backend import SuggestAPIStorefront

backend = SuggestAPIStorefront(tenant="your-store.example.com")
```

| Variable | Purpose |
|---|---|
| `SUGGESTAPI_TENANT` | Merchant domain whose catalog SuggestAPI should search |
| `SUGGESTAPI_BASE_URL` | SuggestAPI agent API (default `https://agent.suggestapi.com`) |
| `SUGGESTAPI_API_KEY` | Optional `x-api-key` if your SuggestAPI project requires it |
| `ANTHROPIC_API_KEY` | Required by Anthropic's demo host, not by `check.py` |

Copy `.env.example` and fill in your values.

A first integration only needs search and product details. The cart in this starter is in-memory for the session so you can try the shopping agent without wiring a storefront cart.

## Docs

- [Anatomy of effective commerce agents](https://claude.com/blog/the-anatomy-of-effective-commerce-agents)
- [Commerce agents use-case guide](https://platform.claude.com/docs/en/about-claude/use-case-guides/commerce-agents)
- [SuggestAPI](https://suggestapi.com)
