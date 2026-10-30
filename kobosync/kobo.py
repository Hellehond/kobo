"""The part of the Kobo store API that e-readers use for their library."""
from __future__ import annotations

import hmac
import logging
import os
import base64
import uuid as uuidlib
from typing import Any, Dict, List, Optional

import requests
from flask import (Blueprint, abort, current_app, g, jsonify, make_response, redirect,
                   render_template_string, request, send_file)

from . import store
from .resources import NATIVE_KOBO_RESOURCES
from .synctoken import SyncToken
from .util import now, parse_kobo_timestamp, to_kobo_timestamp

log = logging.getLogger(__name__)

bp = Blueprint("kobo", __name__, url_prefix="/kobo/<auth_token>")

SYNC_ITEM_LIMIT = 100
READ_STATUSES = ("ReadyToRead", "Reading", "Finished")
ALL_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]


class Context:
    def __init__(self, cfg, db, library):
        self.cfg = cfg
        self.db = db
        self.library = library


def ctx() -> Context:
    return current_app.extensions["kobosync"]


def base_url() -> str:
    return ctx().cfg.public_url or request.url_root.rstrip("/")


def api_prefix() -> str:
    return f"{base_url()}/kobo/{ctx().cfg.auth_token}"


# --------------------------------------------------------------- auth / device

@bp.url_value_preprocessor
def _pull_auth_token(endpoint, values):
    g.auth_token = (values or {}).pop("auth_token", "")


@bp.before_request
def _check_auth_token():
    if not hmac.compare_digest(g.get("auth_token", ""), ctx().cfg.auth_token):
        abort(401)
    device_id = request.headers.get("X-Kobo-DeviceId")
    if device_id:
        try:
            ctx().db.touch_device(device_id, request.headers.get("User-Agent"),
                                  synced=request.path.endswith("/v1/library/sync"))
        except Exception:  # never let bookkeeping break a sync
            log.exception("Could not record device %s", device_id)


# --------------------------------------------------------- JSON serialisation

def book_entitlement(book: Dict[str, Any]) -> Dict[str, Any]:
    archived = bool(book["archived"])
    return {
        "Accessibility": "Full",
        "ActivePeriod": {"From": to_kobo_timestamp(now())},
        "Created": to_kobo_timestamp(book["created"]),
        "CrossRevisionId": book["uuid"],
        "Id": book["uuid"],
        "IsRemoved": archived,
        "IsHiddenFromArchive": False,
        "IsLocked": False,
        "LastModified": to_kobo_timestamp(book["modified"]),
        "OriginCategory": "Imported",
        "RevisionId": book["uuid"],
        "Status": "Active",
    }


def download_urls(book: Dict[str, Any]) -> List[Dict[str, Any]]:
    path, fmt = ctx().library.file_for_book(book)
    try:
        size = path.stat().st_size
    except OSError:
        size = book["size"]
    kobo_format = "KEPUB" if fmt == "KEPUB" else "EPUB3"
    return [{
        "Format": kobo_format,
        "Size": size,
        "Url": f"{api_prefix()}/download/{book['id']}/{kobo_format}",
        "Platform": "Generic",
        "DrmType": "None",
    }]


def book_metadata(book: Dict[str, Any]) -> Dict[str, Any]:
    authors = book["authors"] or ["Onbekend"]
    pubdate = book["pubdate"] if book["pubdate"] else book["created"]
    metadata = {
        "Categories": ["00000000-0000-0000-0000-000000000001"],
        "CoverImageId": book["uuid"],
        "CrossRevisionId": book["uuid"],
        "CurrentDisplayPrice": {"CurrencyCode": "EUR", "TotalAmount": 0},
        "CurrentLoveDisplayPrice": {"TotalAmount": 0},
        "Description": book["description"] or "",
        "DownloadUrls": download_urls(book),
        "EntitlementId": book["uuid"],
        "ExternalIds": [],
        "Genre": "00000000-0000-0000-0000-000000000001",
        "IsEligibleForKoboLove": False,
        "IsInternetArchive": False,
        "IsPreOrder": False,
        "IsSocialEnabled": True,
        "Language": book["language"] or "en",
        "PhoneticPronunciations": {},
        "PublicationDate": to_kobo_timestamp(pubdate),
        "Publisher": {"Imprint": "", "Name": book["publisher"] or ""},
        "RevisionId": book["uuid"],
        "Title": book["title"],
        "WorkId": book["uuid"],
        "ContributorRoles": [{"Name": name} for name in authors],
        "Contributors": list(authors),
    }
    if book["isbn"]:
        metadata["Isbn"] = book["isbn"]
    if book["series"]:
        index = book["series_index"]
        metadata["Series"] = {
            "Name": book["series"],
            "Number": int(index) if index is not None and float(index).is_integer() else index,
            "NumberFloat": index,
            # Stable id derived from the series name, so all volumes share it.
            "Id": str(uuidlib.uuid5(uuidlib.NAMESPACE_URL, "kobosync:series:" + book["series"])),
        }
    return metadata


def reading_state_response(book: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    status_info = {
        "LastModified": to_kobo_timestamp(state["status_last_modified"]),
        "Status": state["status"] if state["status"] in READ_STATUSES else "ReadyToRead",
        "TimesStartedReading": state["times_started_reading"] or 0,
    }
    if state["last_time_started_reading"]:
        status_info["LastTimeStartedReading"] = to_kobo_timestamp(state["last_time_started_reading"])

    statistics = {"LastModified": to_kobo_timestamp(state["statistics_last_modified"])}
    if state["spent_reading_minutes"] is not None:
        statistics["SpentReadingMinutes"] = state["spent_reading_minutes"]
    if state["remaining_time_minutes"] is not None:
        statistics["RemainingTimeMinutes"] = state["remaining_time_minutes"]

    bookmark = {"LastModified": to_kobo_timestamp(state["bookmark_last_modified"])}
    if state["progress_percent"] is not None:
        bookmark["ProgressPercent"] = state["progress_percent"]
    if state["content_source_progress_percent"] is not None:
        bookmark["ContentSourceProgressPercent"] = state["content_source_progress_percent"]
    if state["location_value"]:
        bookmark["Location"] = {
            "Value": state["location_value"],
            "Type": state["location_type"],
            "Source": state["location_source"],
        }

    return {
        "EntitlementId": book["uuid"],
        "Created": to_kobo_timestamp(state["created"]),
        "LastModified": to_kobo_timestamp(state["last_modified"]),
        "PriorityTimestamp": to_kobo_timestamp(state["priority_timestamp"]),
        "StatusInfo": status_info,
        "Statistics": statistics,
        "CurrentBookmark": bookmark,
    }


def tag_response(tag: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Created": to_kobo_timestamp(tag["created"]),
        "Id": tag["uuid"],
        "Items": [{"RevisionId": uuid, "Type": "ProductRevisionTag"} for uuid in tag["items"]],
        "LastModified": to_kobo_timestamp(tag["modified"]),
        "Name": tag["name"],
        "Type": "UserTag",
    }


def collection_results(token: SyncToken, new_token: SyncToken) -> List[Dict[str, Any]]:
    results = []
    for tag in ctx().db.changed_tags(token.tags_last_modified):
        new_token.tags_last_modified = max(new_token.tags_last_modified, tag["modified"])
        device_knows_it = tag["created"] <= token.tags_last_modified
        if tag["deleted"]:
            if device_knows_it:
                results.append({"DeletedTag": {"Tag": {
                    "Id": tag["uuid"], "LastModified": to_kobo_timestamp(tag["modified"])}}})
        elif device_knows_it:
            results.append({"ChangedTag": {"Tag": tag_response(tag)}})
        else:
            results.append({"NewTag": {"Tag": tag_response(tag)}})
    return results


# ------------------------------------------------------------------- sync

@bp.route("/v1/library/sync")
def library_sync():
    c = ctx()
    c.library.scan_if_due()
    c.library.reconcile_collections()  # a device may have removed a book
    token = SyncToken.from_headers(request.headers)
    new_token = token.copy()
    results: List[Dict[str, Any]] = []
    entitled_ids: List[int] = []
    states_from_entitlements = token.reading_state_last_modified

    books = c.db.changed_books(token.books_last_modified, token.books_last_id, SYNC_ITEM_LIMIT + 1)
    more = len(books) > SYNC_ITEM_LIMIT
    for book in books[:SYNC_ITEM_LIMIT]:
        new_token.books_last_modified = book["modified"]
        new_token.books_last_id = book["id"]
        new_token.books_last_created = max(new_token.books_last_created, book["created"])
        is_new = book["created"] > token.books_last_created
        if is_new and book["archived"]:
            continue  # the device never had it; nothing to remove
        entitlement = {
            "BookEntitlement": book_entitlement(book),
            "BookMetadata": book_metadata(book),
        }
        state = c.db.get_or_create_state(book["id"])
        if state["last_modified"] > token.reading_state_last_modified:
            entitlement["ReadingState"] = reading_state_response(book, state)
            states_from_entitlements = max(states_from_entitlements, state["last_modified"])
        entitled_ids.append(book["id"])
        results.append({"NewEntitlement" if is_new else "ChangedEntitlement": entitlement})

    states = c.db.changed_states(token.reading_state_last_modified, entitled_ids, SYNC_ITEM_LIMIT + 1)
    states_truncated = len(states) > SYNC_ITEM_LIMIT
    more = more or states_truncated
    states_high_water = token.reading_state_last_modified
    for state in states[:SYNC_ITEM_LIMIT]:
        states_high_water = max(states_high_water, state["last_modified"])
        book = c.db.book_by_id(state["book_id"])
        if book is None or book["archived"]:
            continue
        results.append({"ChangedReadingState": {"ReadingState": reading_state_response(book, state)}})
    # When this page of states is incomplete, do not skip past states that
    # fall between its last entry and the ones delivered inside entitlements.
    new_token.reading_state_last_modified = (
        states_high_water if states_truncated else max(states_high_water, states_from_entitlements))
    new_token.archive_last_modified = new_token.books_last_modified

    headers: Dict[str, str] = {}
    if more:
        headers["x-kobo-sync"] = "continue"
    else:
        # Collections only once all their books have been delivered.
        results.extend(collection_results(token, new_token))
    if not more and c.cfg.proxy_store:
        # Our own page is complete, so merge in whatever the real store has.
        try:
            upstream = store.forward(c.cfg.auth_token, c.cfg.store_timeout, sync_token=token)
            upstream.raise_for_status()
            store_items = upstream.json()
            if isinstance(store_items, list):
                results.extend(store_items)
            new_token.raw_kobo_store_token = upstream.headers.get("x-kobo-synctoken", token.raw_kobo_store_token)
            for name in ("x-kobo-sync", "x-kobo-sync-mode", "x-kobo-recent-reads"):
                if name in upstream.headers:
                    headers[name] = upstream.headers[name]
        except (requests.RequestException, ValueError) as exc:
            log.warning("Kobo store sync failed, returning local results only: %s", exc)

    new_token.to_headers(headers)
    log.info("Sync for device %s: %d item(s)%s", request.headers.get("X-Kobo-DeviceId", "?"),
             len(results), " (more to come)" if more else "")
    return make_response(jsonify(results), 200, headers)


# ------------------------------------------------------- per-book endpoints

@bp.route("/v1/library/<book_uuid>/metadata")
def library_metadata(book_uuid):
    book = ctx().db.book_by_uuid(book_uuid)
    if book is None:
        return store.redirect_or_proxy(ctx().cfg)
    return jsonify([book_metadata(book)])


@bp.route("/v1/library/<book_uuid>/state", methods=["GET", "PUT"])
def library_state(book_uuid):
    c = ctx()
    book = c.db.book_by_uuid(book_uuid)
    if book is None:
        return store.redirect_or_proxy(c.cfg)
    if request.method == "GET":
        return jsonify([reading_state_response(book, c.db.get_or_create_state(book["id"]))])

    payload = request.get_json(force=True, silent=True) or {}
    reading_states = payload.get("ReadingStates") or []
    if not reading_states:
        abort(400, "ReadingStates missing")
    incoming = reading_states[0]
    ts = now()
    fields: Dict[str, Any] = {"last_modified": ts, "priority_timestamp": ts}
    result: Dict[str, Any] = {"EntitlementId": book["uuid"]}

    bookmark = incoming.get("CurrentBookmark")
    if bookmark:
        location = bookmark.get("Location") or {}
        fields.update(
            progress_percent=bookmark.get("ProgressPercent"),
            content_source_progress_percent=bookmark.get("ContentSourceProgressPercent"),
            location_value=location.get("Value"),
            location_type=location.get("Type"),
            location_source=location.get("Source"),
            bookmark_last_modified=ts,
        )
        result["CurrentBookmarkResult"] = {"Result": "Success"}

    statistics = incoming.get("Statistics")
    if statistics:
        fields.update(
            spent_reading_minutes=statistics.get("SpentReadingMinutes"),
            remaining_time_minutes=statistics.get("RemainingTimeMinutes"),
            statistics_last_modified=ts,
        )
        result["StatisticsResult"] = {"Result": "Success"}

    status_info = incoming.get("StatusInfo")
    if status_info:
        status = status_info.get("Status")
        if status in READ_STATUSES:
            fields["status"] = status
        fields["times_started_reading"] = int(status_info.get("TimesStartedReading") or 0)
        started = parse_kobo_timestamp(status_info.get("LastTimeStartedReading"))
        if started:
            fields["last_time_started_reading"] = started
        fields["status_last_modified"] = ts
        result["StatusInfoResult"] = {"Result": "Success"}

    c.db.update_state(book["id"], **fields)
    log.info("Reading state for '%s' from device %s: %s %s%%", book["title"],
             request.headers.get("X-Kobo-DeviceId", "?"), fields.get("status", ""),
             fields.get("progress_percent", ""))
    return jsonify({"RequestResult": "Success", "UpdateResults": [result]})


@bp.route("/v1/library/<book_uuid>", methods=["DELETE"])
def library_delete(book_uuid):
    c = ctx()
    book = c.db.book_by_uuid(book_uuid)
    if book is None:
        return store.redirect_or_proxy(c.cfg)
    c.db.archive_book(book["id"], "device")
    log.info("'%s' removed from the library by device %s", book["title"],
             request.headers.get("X-Kobo-DeviceId", "?"))
    return "", 204


# -------------------------------------------------------------- collections
#
# Folder collections are managed through the library folders.  When a device
# renames, empties or deletes one, the request is acknowledged and the
# collection is re-sent on the next sync, so all devices stay in line with the
# folders.  Requests about any other collection go to the Kobo store.

def _folder_tag_or_store(tag_id: str):
    tag = ctx().db.tag_by_uuid(tag_id)
    if tag is None or tag["source"] != "folder":
        return None, store.redirect_or_proxy(ctx().cfg)
    ctx().db.update_tag(tag["id"])  # bump: re-send the folder's version
    log.info("Device %s tried to change folder collection '%s'; it will be restored on the next sync",
             request.headers.get("X-Kobo-DeviceId", "?"), tag["name"])
    return tag, None


@bp.route("/v1/library/tags/<tag_id>", methods=["DELETE", "PUT"])
def tag_change(tag_id):
    tag, fallback = _folder_tag_or_store(tag_id)
    return fallback if fallback is not None else ("", 200)


@bp.route("/v1/library/tags/<tag_id>/items", methods=["POST"])
@bp.route("/v1/library/tags/<tag_id>/items/delete", methods=["POST"])
def tag_items(tag_id):
    tag, fallback = _folder_tag_or_store(tag_id)
    return fallback if fallback is not None else ("", 201)


@bp.route("/download/<int:book_id>/<fmt>")
def download(book_id, fmt):
    c = ctx()
    book = c.db.book_by_id(book_id)
    if book is None:
        abort(404)
    path, actual = c.library.file_for_book(book)
    if not path.exists():
        abort(404)
    name = f"{book['title']}.kepub.epub" if actual == "KEPUB" else f"{book['title']}.epub"
    name = "".join(ch for ch in name if ch not in '\\/:*?"<>|')
    return send_file(path, mimetype="application/epub+zip", as_attachment=True, download_name=name,
                     conditional=True)


@bp.route("/<book_uuid>/<int:width>/<int:height>/<quality>/<is_greyscale>/image.jpg")
@bp.route("/<book_uuid>/<int:width>/<int:height>/<is_greyscale>/image.jpg")
def cover_image(book_uuid, width, height, is_greyscale, quality=None):
    c = ctx()
    book = c.db.book_by_uuid(book_uuid)
    if book is None or not book["cover"] or not (c.cfg.covers_dir / book["cover"]).exists():
        if c.cfg.proxy_store and book is None:
            return redirect(f"{store.IMAGE_HOST_URL}/{book_uuid}/{width}/{height}/false/image.jpg", code=307)
        abort(404)
    return send_file(c.cfg.covers_dir / book["cover"], conditional=True)


# ---------------------------------------------------- bootstrap / auth stubs

@bp.route("/v1/initialization")
def initialization():
    c = ctx()
    resources: Optional[Dict[str, Any]] = None
    if c.cfg.proxy_store:
        try:
            upstream = store.forward(c.cfg.auth_token, c.cfg.store_timeout)
            upstream.raise_for_status()
            resources = upstream.json().get("Resources")
        except (requests.RequestException, ValueError, AttributeError) as exc:
            log.warning("Could not fetch initialization data from Kobo, using built-in copy: %s", exc)
    if not resources:
        resources = dict(NATIVE_KOBO_RESOURCES)
    prefix = api_prefix()
    # Route collection requests through us, so changes to folder collections
    # are seen here; requests about Kobo's own collections are passed on.
    for key in ("tags", "tag_items", "delete_tag", "delete_tag_items", "rename_tag"):
        value = resources.get(key)
        if isinstance(value, str) and value.startswith(store.STORE_API_URL):
            resources[key] = prefix + value[len(store.STORE_API_URL):]
    resources["image_host"] = base_url()
    resources["image_url_quality_template"] = (
        prefix + "/{ImageId}/{Width}/{Height}/{Quality}/isGreyscale/image.jpg")
    resources["image_url_template"] = prefix + "/{ImageId}/{Width}/{Height}/false/image.jpg"
    response = make_response(jsonify({"Resources": resources}))
    response.headers["x-kobo-apitoken"] = "e30="
    return response


@bp.route("/v1/auth/device", methods=["POST"])
@bp.route("/v1/auth/refresh", methods=["POST"])
def auth():
    c = ctx()
    if c.cfg.proxy_store:
        try:
            return store.proxy_response(c.cfg.auth_token, c.cfg.store_timeout)
        except requests.RequestException as exc:
            log.warning("Kobo auth endpoint unreachable, answering locally: %s", exc)
    content = request.get_json(silent=True) or {}
    return jsonify({
        "AccessToken": base64.b64encode(os.urandom(24)).decode("ascii"),
        "RefreshToken": base64.b64encode(os.urandom(24)).decode("ascii"),
        "TokenType": "Bearer",
        "TrackingId": str(uuidlib.uuid4()),
        "UserKey": content.get("UserKey", ""),
    })


@bp.route("/v1/analytics/gettests", methods=["GET", "POST"])
def get_tests():
    c = ctx()
    if c.cfg.proxy_store:
        return store.redirect_or_proxy(c.cfg)
    return jsonify({"Result": "Success", "TestKey": request.headers.get("X-Kobo-userkey", ""), "Tests": {}})


@bp.route("/v1/user/loyalty/benefits")
def loyalty_benefits():
    c = ctx()
    if c.cfg.proxy_store:
        return store.redirect_or_proxy(c.cfg)
    return jsonify({"Benefits": {}})


# ------------------------------------------------------------------ status

STATUS_TEMPLATE = """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>kobosync</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font:15px/1.4 system-ui,sans-serif;margin:2rem auto;max-width:60rem;padding:0 1rem;color:#222}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #ddd;vertical-align:top}
th{background:#f3f3f3}.muted{color:#777}.bar{background:#eee;height:.5rem;border-radius:.25rem;overflow:hidden;min-width:6rem}
.bar i{display:block;height:100%;background:#2b7}code{background:#f3f3f3;padding:.1rem .3rem}
</style></head><body>
<h1>kobosync</h1>
<p>Bibliotheek: <code>{{ library }}</code> &middot; {{ books|length }} boek(en) &middot; {{ devices|length }} toestel(len)</p>
<h2>Toestellen</h2>
{% if devices %}<table><tr><th>Toestel</th><th>Laatst gezien</th><th>Laatste sync</th></tr>
{% for d in devices %}<tr><td><code>{{ d.device_id[:8] }}&hellip;</code><br><span class="muted">{{ d.user_agent or '' }}</span></td>
<td>{{ fmt(d.last_seen) }}</td><td>{{ fmt(d.last_sync) if d.last_sync else '-' }}</td></tr>{% endfor %}</table>
{% else %}<p class="muted">Nog geen toestel heeft contact gemaakt.</p>{% endif %}
<h2>Boeken</h2>
{% if books %}<table><tr><th>Titel</th><th>Formaat</th><th>Status</th><th>Voortgang</th><th>Laatst gelezen</th></tr>
{% for b in books %}<tr>
<td>{{ b.title }}<br><span class="muted">{{ b.authors|join(', ') }}{% if b.archived %} &middot; gearchiveerd ({{ b.archived_reason }}){% endif %}</span></td>
<td>{{ 'KEPUB' if b.kepub_path else b.format }}</td>
<td>{{ {'ReadyToRead':'Ongelezen','Reading':'Aan het lezen','Finished':'Uitgelezen'}.get(b.status, b.status) }}</td>
<td>{% if b.progress_percent is not none %}<div class="bar"><i style="width:{{ b.progress_percent }}%"></i></div>{{ '%.0f'|format(b.progress_percent) }}%{% else %}<span class="muted">-</span>{% endif %}</td>
<td>{{ fmt(b.state_modified) if b.progress_percent is not none else '-' }}</td></tr>{% endfor %}</table>
{% else %}<p class="muted">Nog geen boeken. Zet EPUB- of KEPUB-bestanden in de bibliotheekmap.</p>{% endif %}
</body></html>"""


@bp.route("/status")
def status_page():
    c = ctx()
    c.library.scan_if_due()
    from datetime import datetime

    def fmt(epoch):
        return datetime.fromtimestamp(epoch).strftime("%d-%m-%Y %H:%M") if epoch else "-"

    return render_template_string(STATUS_TEMPLATE, books=c.db.overview(), devices=c.db.devices(),
                                  library=str(c.cfg.library_dir), fmt=fmt)


# ------------------------------------------------------------- everything else

@bp.route("/", defaults={"path": ""}, methods=ALL_METHODS)
@bp.route("/<path:path>", methods=ALL_METHODS)
def catch_all(path):
    return store.redirect_or_proxy(ctx().cfg)
