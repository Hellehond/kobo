"""Forwarding of requests we do not handle ourselves to the real Kobo store."""
from __future__ import annotations

import logging
from typing import Optional

import requests
from flask import jsonify, make_response, redirect, request

from .synctoken import SYNC_TOKEN_HEADER, SyncToken

log = logging.getLogger(__name__)

STORE_API_URL = "https://storeapi.kobo.com"
IMAGE_HOST_URL = "https://cdn.kobo.com/book-images"

# Headers that describe this particular connection rather than the payload.
_HOP_HEADERS = {"connection", "content-encoding", "content-length", "transfer-encoding", "keep-alive"}
_SKIP_OUTGOING = {"host", "content-length", "transfer-encoding"}


def store_url(auth_token: str) -> str:
    """Translate the current request URL into the equivalent Kobo store URL."""
    prefix = f"/kobo/{auth_token}"
    full = request.full_path.rstrip("?")
    _, found, rest = full.partition(prefix)
    if not found:
        rest = request.full_path.rstrip("?")
    if not rest.startswith("/"):
        rest = "/" + rest
    return STORE_API_URL + rest


def forward(auth_token: str, timeout: float, sync_token: Optional[SyncToken] = None) -> requests.Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_OUTGOING}
    if sync_token is not None:
        headers = {k: v for k, v in headers.items() if k.lower() != SYNC_TOKEN_HEADER}
        if sync_token.raw_kobo_store_token:
            headers[SYNC_TOKEN_HEADER] = sync_token.raw_kobo_store_token
    return requests.request(
        request.method, store_url(auth_token), headers=headers, data=request.get_data(),
        allow_redirects=False, timeout=(5, timeout))


def proxy_response(auth_token: str, timeout: float):
    upstream = forward(auth_token, timeout)
    headers = [(k, v) for k, v in upstream.headers.items() if k.lower() not in _HOP_HEADERS]
    return make_response(upstream.content, upstream.status_code, headers)


def redirect_or_proxy(cfg):
    """What to do with a request about store content.

    GET requests are redirected so the device talks to Kobo directly.  Other
    methods are proxied, because the device turns redirected PUT/POST requests
    into GETs.
    """
    if not cfg.proxy_store:
        return jsonify({})
    if request.method == "GET":
        return redirect(store_url(cfg.auth_token), code=307)
    try:
        return proxy_response(cfg.auth_token, cfg.store_timeout)
    except requests.RequestException as exc:
        log.warning("Kobo store unreachable for %s %s: %s", request.method, request.path, exc)
        return make_response(jsonify({"Result": "Error", "Message": "Kobo store unreachable"}), 502)
