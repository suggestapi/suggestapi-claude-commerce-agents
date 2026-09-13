#!/usr/bin/env python3
"""Browser shopper: search → cart → merchant checkout, over the same harness tests use."""

from __future__ import annotations

import errno
import json
import os
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from commerce_types import ShoppingSessionContext  # noqa: E402
from harness import dump_cart, run_turn  # noqa: E402
from suggestapi_backend import SuggestAPIStorefront  # noqa: E402
from trace import collect, intro, setup, step  # noqa: E402

WEB = Path(__file__).with_name("web")
FIXTURES = json.loads((ROOT / "tests" / "fixtures.json").read_text())
HOST = os.environ.get("DEMO_HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
PORT = int(os.environ.get("PORT") or os.environ.get("DEMO_PORT") or "8765")


def build_backend() -> SuggestAPIStorefront:
    live = os.environ.get("SUGGESTAPI_LIVE") == "1"
    tenant = os.environ.get("SUGGESTAPI_TENANT") or FIXTURES["tenant"]
    if live:
        return SuggestAPIStorefront(tenant=tenant)
    return SuggestAPIStorefront(tenant=tenant, fixtures=FIXTURES)


BACKEND = build_backend()
SESSIONS: dict[str, ShoppingSessionContext] = {}


def checkout_page(items_param: str) -> bytes:
    catalog = {
        str(product["id"]): product
        for product in FIXTURES.get("products") or []
        if isinstance(product, dict) and product.get("id")
    }
    rows: list[str] = []
    total = 0.0
    for part in items_param.split(","):
        sku, _, qty_raw = part.partition(":")
        sku = sku.strip()
        if not sku:
            continue
        try:
            qty = max(1, int(qty_raw or "1"))
        except ValueError:
            qty = 1
        product = catalog.get(sku) or {}
        title = str(product.get("title") or sku)
        money = ((product.get("price_range") or {}).get("min") or {}) if isinstance(product.get("price_range"), dict) else {}
        amount = money.get("amount") if isinstance(money, dict) else None
        price = round(float(amount) / 100, 2) if isinstance(amount, (int, float)) else 0.0
        line = round(price * qty, 2)
        total += line
        rows.append(
            f"<li><span>{qty} × {title}</span><span>${line:.2f}</span></li>"
        )
    body = "".join(rows) or "<li class='empty'>No line items on this handoff.</li>"
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Merchant checkout</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    body {{ margin: 0; font: 16px/1.5 Inter, ui-sans-serif, system-ui, sans-serif; background: #ffffff; color: #000000; }}
    main {{ max-width: 32rem; margin: 2rem auto; padding: 0 1.25rem; }}
    h1 {{ font-weight: 700; letter-spacing: -0.02em; }}
    ul {{ padding: 0; list-style: none; }}
    li {{ display: flex; justify-content: space-between; gap: 1rem; margin: 0.5rem 0; }}
    code {{ font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 0.86em; }}
    a {{ color: #00b4c8; }}
    .empty {{ color: #5b6578; }}
  </style>
</head>
<body>
  <main>
    <p>Merchant storefront stand-in · SuggestAPI does not take payment</p>
    <h1>Checkout</h1>
    <ul>{body}</ul>
    <p>Subtotal ${total:.2f}</p>
    <p><a href="/">Back to shopper</a></p>
  </main>
</body>
</html>
"""
    return html.encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        if self.path.startswith("/api/"):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _session(self) -> tuple[str, ShoppingSessionContext]:
        cookie = self.headers.get("cookie") or ""
        sid = ""
        for part in cookie.split(";"):
            name, _, value = part.strip().partition("=")
            if name == "sid":
                sid = value
        if not sid or sid not in SESSIONS:
            sid = uuid.uuid4().hex
            SESSIONS[sid] = ShoppingSessionContext(session_id=sid, user_id="guest")
        return sid, SESSIONS[sid]

    def _send(self, status: int, body: bytes, content_type: str, sid: str | None = None) -> None:
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        if sid:
            self.send_header("set-cookie", f"sid={sid}; Path=/; HttpOnly; SameSite=Lax")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, sid: str) -> None:
        self._send(200, json.dumps(payload).encode(), "application/json", sid)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        sid, ctx = self._session()
        if path in {"/", "/index.html"}:
            self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8", sid)
            return
        if path == "/checkout":
            items = (parse_qs(urlparse(self.path).query).get("items") or [""])[0]
            self._send(200, checkout_page(items), "text/html; charset=utf-8", sid)
            return
        if path == "/api/state":
            import asyncio

            cart = asyncio.run(BACKEND.get_cart(ctx))
            self._json({"cart": dump_cart(cart), "tenant": BACKEND.tenant}, sid)
            return
        self._send(404, b"not found", "text/plain", sid)

    def do_POST(self) -> None:  # noqa: N802
        import asyncio

        path = urlparse(self.path).path
        sid, ctx = self._session()
        length = int(self.headers.get("content-length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        if path == "/api/turn":
            message = str(payload.get("message") or "")
            step(
                f"browser session {sid[:8]}",
                do=f"shopper says {message!r}",
                expect="request / response for the matching Claude Commerce tool",
            )
            with collect() as calls:
                result = asyncio.run(run_turn(BACKEND, ctx, message))
            result["calls"] = calls
            self._json(result, sid)
            return
        self._send(404, b"not found", "text/plain", sid)


class DemoServer(ThreadingHTTPServer):
    allow_reuse_address = True


def bind(host: str, port: int) -> tuple[DemoServer, int]:
    last: OSError | None = None
    for candidate in range(port, port + 10):
        try:
            return DemoServer((host, candidate), Handler), candidate
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
            last = error
    raise OSError(f"ports {port}-{port + 9} already in use") from last


def main() -> None:
    setup()
    server, port = bind(HOST, PORT)
    mode = "live SuggestAPI" if os.environ.get("SUGGESTAPI_LIVE") == "1" else "guest fixtures"
    extra = f"  ({PORT} was busy)" if port != PORT else ""
    intro(
        f"SuggestAPI shopper  ({mode})",
        f"Open http://{HOST}:{port}{extra}  — examples: oak, box, featured cellar gift, sold out, Chef",
        "Each turn logs Testing/Do/Expect style steps, then request / response.",
    )
    print(f"http://{HOST}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
