"""The pages people look at: overview, reading statistics and upload."""
from __future__ import annotations

import hmac
import logging
import re
import secrets
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import render_template, request
from jinja2 import DictLoader

from . import epubfix, stats
from .kobo import bp, ctx
from .library import detect_format, file_hash

log = logging.getLogger(__name__)

STATUS_NAMES = {"ReadyToRead": "Ongelezen", "Reading": "Aan het lezen", "Finished": "Uitgelezen"}

TEMPLATES = {
    "base.html": """<!doctype html>
<html lang="nl"><head><meta charset="utf-8"><title>{% block title %}kobosync{% endblock %}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{--bg:#fbfaf7;--fg:#22211f;--muted:#76726b;--line:#e4e0d8;--card:#fff;--accent:#2f7d5b;--warn:#b0581b;--bar:#ece8df}
@media (prefers-color-scheme: dark){:root{--bg:#171716;--fg:#ecebe7;--muted:#a19d95;--line:#33322f;--card:#211f1d;--accent:#5cbf8f;--warn:#e19354;--bar:#2e2c29}}
*{box-sizing:border-box}body{font:16px/1.5 system-ui,-apple-system,sans-serif;margin:0;background:var(--bg);color:var(--fg)}
main{max-width:62rem;margin:0 auto;padding:1rem 1rem 3rem}
nav{display:flex;gap:1.25rem;align-items:baseline;flex-wrap:wrap;padding:.75rem 0 1rem;border-bottom:1px solid var(--line);margin-bottom:1.5rem}
nav strong{margin-right:auto}nav a{color:var(--muted);text-decoration:none}nav a.on{color:var(--fg);font-weight:600}
h1{font-size:1.5rem;margin:.25rem 0 1rem}h2{font-size:1.1rem;margin:2rem 0 .75rem}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:.45rem .5rem;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:.85rem}
.wrap{overflow-x:auto}.muted{color:var(--muted)}.small{font-size:.85rem}
.bar{background:var(--bar);height:.5rem;border-radius:.25rem;overflow:hidden;min-width:5rem}.bar i{display:block;height:100%;background:var(--accent)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(12rem,1fr));gap:.75rem}
.card{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:.9rem 1rem}
.card .big{font-size:1.8rem;font-weight:650;line-height:1.2}
.ok{color:var(--accent)}.late{color:var(--warn)}
form{background:var(--card);border:1px solid var(--line);border-radius:.5rem;padding:1rem}
label{display:block;font-weight:600;margin:.9rem 0 .3rem}label:first-child{margin-top:0}
input,select,button{font:inherit;color:inherit}
input[type=text],input[type=password],select{width:100%;padding:.5rem;border:1px solid var(--line);border-radius:.35rem;background:var(--bg)}
input[type=file]{width:100%}
button{margin-top:1.1rem;padding:.6rem 1.2rem;border:0;border-radius:.35rem;background:var(--accent);color:#fff;font-weight:600;cursor:pointer}
code{background:var(--bar);padding:.1rem .3rem;border-radius:.2rem}
.msg{padding:.75rem 1rem;border-radius:.5rem;border:1px solid var(--line);background:var(--card);margin-bottom:.5rem}
.msg.bad{border-color:var(--warn)}
.mbar{background:var(--accent);height:.5rem;border-radius:.25rem;margin:.35rem 0 .1rem}
@media (max-width:600px){nav{gap:.9rem}nav strong{width:100%}table{font-size:.9rem}th,td{padding:.4rem .3rem}.hide-sm{display:none}.card .big{font-size:1.5rem}}
</style></head><body><main>
<nav><strong>kobosync</strong>
<a href="{{ base }}/status" class="{{ 'on' if page == 'status' }}">Overzicht</a>
<a href="{{ base }}/statistieken" class="{{ 'on' if page == 'stats' }}">Statistieken</a>
<a href="{{ base }}/upload" class="{{ 'on' if page == 'upload' }}">Uploaden</a></nav>
{% block body %}{% endblock %}
</main></body></html>""",

    "status.html": """{% extends "base.html" %}{% block body %}
<h1>Overzicht</h1>
<p class="muted">{{ books|length }} boek(en) &middot; {{ devices|length }} toestel(len)</p>
<h2>Toestellen</h2>
{% if devices %}<div class="wrap"><table><tr><th>Toestel</th><th class="hide-sm">Laatst gezien</th><th>Laatste sync</th></tr>
{% for d in devices %}<tr><td><code>{{ d.device_id[:8] }}&hellip;</code><br><span class="muted small">{{ d.user_agent or '' }}</span></td>
<td class="hide-sm">{{ fmt(d.last_seen) }}</td><td>{{ fmt(d.last_sync) if d.last_sync else '-' }}</td></tr>{% endfor %}</table></div>
{% else %}<p class="muted">Nog geen toestel heeft contact gemaakt.</p>{% endif %}
<h2>Boeken</h2>
{% if books %}<div class="wrap"><table><tr><th>Titel</th><th>Status</th><th>Voortgang</th><th>Laatst gelezen</th></tr>
{% for b in books %}<tr>
<td>{{ b.title }}<br><span class="muted small">{{ b.authors|join(', ') }}{% if b.collection %} &middot; {{ b.collection }}{% endif %}{% if b.archived %} &middot; gearchiveerd ({{ b.archived_reason }}){% endif %}</span></td>
<td>{{ status_names.get(b.status, b.status) }}</td>
<td>{% if b.progress_percent is not none %}<div class="bar"><i style="width:{{ b.progress_percent }}%"></i></div><span class="small">{{ '%.0f'|format(b.progress_percent) }}%</span>{% else %}<span class="muted">-</span>{% endif %}</td>
<td>{{ fmt(b.state_modified) if b.progress_percent is not none else '-' }}</td></tr>{% endfor %}</table></div>
{% else %}<p class="muted">Nog geen boeken. Zet EPUB- of KEPUB-bestanden in de bibliotheekmap of gebruik <a href="{{ base }}/upload">Uploaden</a>.</p>{% endif %}
{% endblock %}""",

    "stats.html": """{% extends "base.html" %}{% block title %}Statistieken &middot; kobosync{% endblock %}{% block body %}
<h1>Statistieken {{ s.year }}</h1>
{% if s.years|length > 1 %}<p class="small">{% for y in s.years %}{% if y == s.year %}<strong>{{ y }}</strong>{% else %}<a href="?jaar={{ y }}">{{ y }}</a>{% endif %}{% if not loop.last %} &middot; {% endif %}{% endfor %}</p>{% endif %}
<div class="cards">
<div class="card"><div class="muted small">Uitgelezen</div><div class="big">{{ s.finished|length }}{% if s.goal %} <span class="muted small">van {{ s.goal }}</span>{% endif %}</div>
{% if s.goal %}<div class="bar" style="margin-top:.5rem"><i style="width:{{ [100, 100 * s.finished|length / s.goal]|min }}%"></i></div>
{% if s.expected_by_now is not none %}<div class="small {{ 'ok' if s.finished|length >= s.expected_by_now|round(0, 'floor') else 'late' }}">
{% if s.finished|length >= s.expected_by_now|round(0, 'floor') %}Op schema{% else %}{{ (s.expected_by_now|round(0, 'floor') - s.finished|length)|int }} boek(en) achter op schema{% endif %}</div>{% endif %}
{% else %}<div class="muted small">Stel een jaardoel in met KOBOSYNC_READING_GOAL</div>{% endif %}</div>
<div class="card"><div class="muted small">Leestijd</div><div class="big">{{ minutes(s.minutes) }}</div></div>
<div class="card"><div class="muted small">Bezig met lezen</div><div class="big">{{ s.reading|length }}</div></div>
</div>
<h2>Per maand</h2>
<div class="wrap"><table><tr><th>Maand</th><th>Uitgelezen</th><th>Leestijd</th></tr>
{% for m in s.months %}<tr><td>{{ m.name }}</td>
<td style="width:35%">{% if m.finished %}<div class="mbar" style="width:{{ 10 + 90 * m.finished / s.max_month_finished }}%"></div>{% endif %}<span class="small">{{ m.finished or '-' }}</span></td>
<td style="width:35%">{% if m.minutes %}<div class="mbar" style="width:{{ 10 + 90 * m.minutes / s.max_month_minutes }}%"></div>{% endif %}<span class="small">{{ minutes(m.minutes) if m.minutes else '-' }}</span></td></tr>{% endfor %}
</table></div>
<h2>Uitgelezen boeken</h2>
{% if s.finished %}<div class="wrap"><table><tr><th>Titel</th><th class="hide-sm">Begonnen</th><th>Uitgelezen</th><th>Duur</th><th>Leestijd</th></tr>
{% for b in s.finished %}<tr><td>{{ b.title }}<br><span class="muted small">{{ b.authors|join(', ') }}</span></td>
<td class="hide-sm">{{ b.started.strftime('%d-%m') if b.started else '-' }}</td><td>{{ b.finished.strftime('%d-%m') }}</td>
<td>{{ (b.days ~ ' dag' ~ ('en' if b.days != 1 else '')) if b.days else '-' }}</td><td>{{ minutes(b.minutes) if b.minutes else '-' }}</td></tr>{% endfor %}</table></div>
{% else %}<p class="muted">Nog geen boeken uitgelezen in {{ s.year }}.</p>{% endif %}
{% if s.reading %}<h2>Bezig met lezen</h2><div class="wrap"><table><tr><th>Titel</th><th>Voortgang</th><th>Leestijd</th></tr>
{% for b in s.reading %}<tr><td>{{ b.title }}<br><span class="muted small">{{ b.authors|join(', ') }}</span></td>
<td>{% if b.progress_percent is not none %}<div class="bar"><i style="width:{{ b.progress_percent }}%"></i></div><span class="small">{{ '%.0f'|format(b.progress_percent) }}%</span>{% else %}-{% endif %}</td>
<td>{{ minutes(b.spent_reading_minutes) if b.spent_reading_minutes else '-' }}</td></tr>{% endfor %}</table></div>{% endif %}
<p class="muted small" style="margin-top:2rem">Alleen je eigen boeken, geen Kobo-aankopen. Leestijd telt vanaf de versie van kobosync met statistieken. Uitgelezen boeken van daarvoor tellen mee op de datum waarop hun status veranderde.</p>
{% endblock %}""",

    "upload.html": """{% extends "base.html" %}{% block title %}Uploaden &middot; kobosync{% endblock %}{% block body %}
<h1>Boeken uploaden</h1>
{% for r in results %}<div class="msg {{ 'bad' if not r.ok }}"><strong>{{ r.name }}</strong><br>{{ r.message }}</div>{% endfor %}
{% if error %}<div class="msg bad">{{ error }}</div>{% endif %}
{% if not enabled %}
<p>Uploaden staat uit. Zet een wachtwoord in <code>.env</code> en herstart kobosync:</p>
<p><code>KOBOSYNC_UPLOAD_PASSWORD=een-lang-wachtwoord</code></p>
{% else %}
<form method="post" enctype="multipart/form-data">
<label for="boeken">EPUB- of KEPUB-bestanden</label>
<input id="boeken" type="file" name="boeken" accept=".epub,.kepub,application/epub+zip" multiple required>
<label for="map">Collectie</label>
<select id="map" name="map"><option value="">Geen collectie</option>
{% for f in folders %}<option value="{{ f }}" {{ 'selected' if f == chosen }}>{{ f.replace('/', ' / ') }}</option>{% endfor %}</select>
<label for="nieuwe_map">Of een nieuwe collectie</label>
<input id="nieuwe_map" type="text" name="nieuwe_map" placeholder="Bijvoorbeeld Thrillers/Noors" autocomplete="off">
<label for="wachtwoord">Wachtwoord</label>
<input id="wachtwoord" type="password" name="wachtwoord" required autocomplete="current-password">
<button type="submit">Uploaden</button>
<p class="muted small">Hooguit {{ max_mb }} MB per keer. Na het uploaden staan de boeken bij de volgende synchronisatie op je Kobo's.</p>
</form>{% endif %}
{% endblock %}""",
}


def install(app) -> None:
    app.jinja_loader = DictLoader(TEMPLATES)


def _base() -> str:
    return f"{request.script_root}/kobo/{ctx().cfg.auth_token}"


def _fmt_factory():
    tz = stats.zone(ctx().cfg.timezone)

    def fmt(epoch):
        return datetime.fromtimestamp(epoch, tz).strftime("%d-%m-%Y %H:%M") if epoch else "-"
    return fmt


# ------------------------------------------------------------------- status

@bp.route("/status")
def status_page():
    c = ctx()
    c.library.scan_if_due()
    books = c.db.overview()
    for book in books:
        name = c.library.collection_name(book["path"])
        book["collection"] = name
    return render_template("status.html", page="status", base=_base(), books=books, devices=c.db.devices(),
                           fmt=_fmt_factory(), status_names=STATUS_NAMES)


# --------------------------------------------------------------- statistics

@bp.route("/statistieken")
def stats_page():
    c = ctx()
    year = request.args.get("jaar", type=int)
    s = stats.year_stats(c.db, year, c.cfg.reading_goal, c.cfg.timezone)
    return render_template("stats.html", page="stats", base=_base(), s=s, minutes=stats.format_minutes)


# ------------------------------------------------------------------- upload

_BAD_CHARS = re.compile(r'[\x00-\x1f\\:*?"<>|]')


def clean_folder(value: str) -> Optional[str]:
    """A safe relative folder below the library, or None when it is not acceptable."""
    value = (value or "").replace("\\", "/").strip().strip("/")
    if not value:
        return ""
    parts = []
    for part in value.split("/"):
        part = _BAD_CHARS.sub("", part).strip()
        if not part or part in (".", "..") or part.startswith(".") or len(part) > 100:
            return None
        parts.append(part)
    return "/".join(parts)


def clean_filename(value: str) -> Optional[str]:
    name = _BAD_CHARS.sub("", (value or "").replace("\\", "/").rsplit("/", 1)[-1]).strip()
    if not name or name.startswith(".") or len(name) > 200:
        return None
    if not detect_format(Path(name)):
        return None
    return name


def _free_name(folder: Path, name: str) -> Path:
    target = folder / name
    if not target.exists():
        return target
    for suffix in (".kepub.epub", ".kepub", ".epub"):
        if name.lower().endswith(suffix):
            stem, ext = name[: -len(suffix)], name[-len(suffix):]
            break
    n = 2
    while (folder / f"{stem} ({n}){ext}").exists():
        n += 1
    return folder / f"{stem} ({n}){ext}"


def _check_epub(path: Path) -> Optional[str]:
    """Why this file cannot be used, or None when it is fine."""
    if not zipfile.is_zipfile(path):
        return "Dit is geen EPUB-bestand."
    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        if "META-INF/container.xml" not in names:
            return "Dit is geen EPUB-bestand."
        if epubfix._has_drm(zf):
            return "Dit boek heeft DRM en kan niet op je Kobo gelezen worden via kobosync."
    return None


def _folders(root: Path) -> List[str]:
    found = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if path.is_dir() and not any(part.startswith(".") for part in rel.parts):
            found.append(rel.as_posix())
    return found


@bp.route("/upload", methods=["GET", "POST"])
def upload_page():
    c = ctx()
    root = c.cfg.library_dir
    enabled = bool(c.cfg.upload_password)
    page: Dict[str, Any] = dict(page="upload", base=_base(), enabled=enabled, results=[], error=None,
                                folders=_folders(root), chosen="", max_mb=c.cfg.upload_max_mb)
    if request.method == "GET" or not enabled:
        return render_template("upload.html", **page)

    if not hmac.compare_digest(request.form.get("wachtwoord", "").encode(), c.cfg.upload_password.encode()):
        time.sleep(1)  # slow down guessing
        log.warning("Upload refused: wrong password from %s", request.remote_addr)
        page["error"] = "Verkeerd wachtwoord."
        return render_template("upload.html", **page), 403

    folder = clean_folder(request.form.get("nieuwe_map") or request.form.get("map") or "")
    if folder is None:
        page["error"] = "Die mapnaam kan niet. Gebruik gewone letters en cijfers, zonder punt vooraan."
        return render_template("upload.html", **page), 400
    target_dir = (root / folder).resolve() if folder else root
    if root not in target_dir.parents and target_dir != root:
        page["error"] = "Die map ligt buiten de bibliotheek."
        return render_template("upload.html", **page), 400

    files = [f for f in request.files.getlist("boeken") if f and f.filename]
    if not files:
        page["error"] = "Kies minstens één bestand."
        return render_template("upload.html", **page), 400

    # Folders this upload creates, deepest first, to remove again if they stay empty.
    new_dirs = [d for d in [target_dir, *target_dir.parents] if root in d.parents and not d.exists()]
    known = {b["content_hash"]: b for b in c.db.all_books() if b.get("content_hash")}
    saved: List[Dict[str, Any]] = []
    for upload in files:
        name = clean_filename(upload.filename)
        if not name:
            page["results"].append({"name": upload.filename, "ok": False,
                                    "message": "Alleen .epub- en .kepub.epub-bestanden kunnen."})
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        tmp = target_dir / f".upload-{secrets.token_hex(6)}.part"
        try:
            upload.save(str(tmp))
            problem = _check_epub(tmp)
            if problem:
                page["results"].append({"name": name, "ok": False, "message": problem})
                continue
            digest = file_hash(tmp)
            if digest in known:
                book = known[digest]
                page["results"].append({"name": name, "ok": False,
                                        "message": f"Staat al in de bibliotheek als {book['path']}."})
                continue
            final = _free_name(target_dir, name)
            tmp.replace(final)
            known[digest] = {"path": final.relative_to(root).as_posix()}
            saved.append({"name": name, "path": final.relative_to(root).as_posix(), "hash": digest})
            log.info("Uploaded %s", final.relative_to(root).as_posix())
        finally:
            if tmp.exists():
                tmp.unlink()

    for new_dir in new_dirs:
        # Nothing usable was uploaded there: do not leave an empty new folder behind.
        if new_dir.exists() and not any(new_dir.iterdir()):
            new_dir.rmdir()
    if saved:
        c.library.scan()
        by_hash = {b["content_hash"]: b for b in c.db.all_books() if b.get("content_hash")}
        for item in saved:
            book = by_hash.get(item["hash"])
            title = f"{book['title']} van {', '.join(book['authors'])}" if book else item["path"]
            where = f" in de collectie {folder.replace('/', ' / ')}" if folder else ""
            page["results"].append({"name": item["name"], "ok": True, "message": f"Toegevoegd: {title}{where}."})
    page["folders"] = _folders(root)
    page["chosen"] = folder
    return render_template("upload.html", **page)
