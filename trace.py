"""First-run traces: numbered cases, then request / response."""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator

log = logging.getLogger("suggestapi.harness")
_calls: ContextVar[list[dict[str, Any]] | None] = ContextVar("suggestapi_trace_calls", default=None)

WIDE = "=" * 72
THIN = "-" * 72


def setup(*, quiet: bool = False) -> None:
    if log.handlers:
        log.setLevel(logging.WARNING if quiet else logging.INFO)
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.WARNING if quiet else logging.INFO)
    log.propagate = False


def intro(*lines: str) -> None:
    log.info(WIDE)
    for line in lines:
        log.info(line)
    log.info(WIDE)


def case(number: int, title: str, *, testing: str, do: str, expect: str) -> None:
    log.info("")
    log.info(WIDE)
    log.info("TEST %s  %s", number, title)
    log.info(WIDE)
    log.info("  Testing    %s", testing)
    log.info("  Do         %s", do)
    log.info("  Expect     %s", expect)
    log.info("")


def step(title: str, *, do: str, expect: str) -> None:
    log.info(THIN)
    log.info("  Step       %s", title)
    log.info("  Do         %s", do)
    log.info("  Expect     %s", expect)
    log.info("")


def done(message: str) -> None:
    log.info("")
    log.info(WIDE)
    log.info(message)
    log.info(WIDE)


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _block(label: str, payload: Any) -> None:
    rendered = json.dumps(_plain(payload), indent=2, ensure_ascii=True)
    log.info("  %s", label)
    for line in rendered.splitlines():
        log.info("    %s", line)
    log.info("")


@contextmanager
def collect() -> Iterator[list[dict[str, Any]]]:
    buf: list[dict[str, Any]] = []
    token = _calls.set(buf)
    try:
        yield buf
    finally:
        _calls.reset(token)


def _push(kind: str, payload: Any) -> None:
    buf = _calls.get()
    if buf is not None:
        buf.append({"kind": kind, "payload": _plain(payload)})


def request(payload: Any) -> None:
    _block("request", payload)
    _push("request", payload)


def response(payload: Any) -> None:
    _block("response", payload)
    _push("response", payload)
