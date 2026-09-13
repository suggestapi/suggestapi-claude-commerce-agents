# SuggestAPI + Claude Commerce Agents

Drop-in [`StorefrontBackend`](https://github.com/anthropics/commerce-agents/blob/main/shopping-agent/core/shopping_agent/backend.py) for [Anthropic's commerce agents](https://github.com/anthropics/commerce-agents).

Claude Commerce already has `search_products` and `get_product_details`. This repo implements those methods over the [SuggestAPI Knowledge Gateway](https://agent.suggestapi.com). SuggestAPI retrieves and ranks products from the merchant's existing search stack. Claude compares, presents, and fills a session cart.

Do not add a custom Messages API autocomplete tool. That is not Claude Commerce.

```
Shopper
  → Claude Commerce shopping agent
  → search_products / get_product_details
  → SuggestAPIStorefront (this repo)
  → POST /oks/{tenant}/catalog/search
  → ranked products
  → Claude
```

Checkout is a merchant handoff (`POST /oks/{tenant}/checkout_sessions` → `continue_url`). This adapter does not capture payment.

## What this is not

- Not a hosted Claude Commerce agent
- Not `https://api.suggestapi.com/v1/predict`
- Not a replacement for Anthropic's shopping-agent runtime

## Check the mapper

No Anthropic packages required:

```bash
python3 check.py
```

## Wire into Anthropic's retail demo

```bash
git clone https://github.com/anthropics/commerce-agents.git
cd commerce-agents
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Put this repo on `PYTHONPATH` (or copy `map_product.py` and `suggestapi_backend.py` next to the retail API). Replace `MockRetail` with:

```python
from suggestapi_backend import SuggestAPIStorefront

backend = SuggestAPIStorefront(tenant="demo.suggestapi.com")
```

| Variable | Purpose |
|---|---|
| `SUGGESTAPI_TENANT` | Merchant domain, e.g. `demo.suggestapi.com` |
| `SUGGESTAPI_BASE_URL` | Gateway origin (default `https://agent.suggestapi.com`) |
| `SUGGESTAPI_API_KEY` | `x-api-key` when the gateway requires it |
| `ANTHROPIC_API_KEY` | Required by the Anthropic demo host, not by `check.py` |

A shopping pilot only needs search and product details. Cart methods here are in-memory for the session; orders are empty; policies come from `GET /oks/{tenant}/policies`.

## Gateway calls

- Search: `POST https://agent.suggestapi.com/oks/{tenant}/catalog/search`
- Details: `GET https://agent.suggestapi.com/oks/{tenant}/products/{id}`
- Checkout handoff: `POST https://agent.suggestapi.com/oks/{tenant}/checkout_sessions`

## References

- [Anatomy of effective commerce agents](https://claude.com/blog/the-anatomy-of-effective-commerce-agents)
- [Commerce agents use-case guide](https://platform.claude.com/docs/en/about-claude/use-case-guides/commerce-agents)
- [SuggestAPI Knowledge Gateway](https://github.com/suggestapi/suggestapi_agent)
