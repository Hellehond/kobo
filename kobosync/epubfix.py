"""Make a reader-friendlier copy of an EPUB for the Kobo.

Two independent fixes, each optional:

* CSS clean-up: fixed font sizes, line heights, margins and indents in px/pt
  are turned into em, and ``!important`` is dropped from those properties.
  Publishers' absolute sizes otherwise stop the Kobo's font-size and margin
  settings from working.

* Front matter: rights pages, watermark pages and colophons that sit before
  the actual text are moved to the end of the reading order, so a book opens
  at its title page or first chapter instead of a page of legal text.

The original file is never modified.  Fixed-layout books and books with real
DRM are left alone.
"""
from __future__ import annotations

import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

# Font obfuscation is not DRM; anything else in encryption.xml is.
FONT_OBFUSCATION = {"http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC"}

TEXT_EXTENSIONS = (".xhtml", ".html", ".htm", ".xml")
CSS_EXTENSIONS = (".css",)

# --------------------------------------------------------------------- CSS

_PROPS = r"(?:font-size|line-height|text-indent|margin(?:-top|-bottom|-left|-right)?|padding(?:-top|-bottom|-left|-right)?)"
_DECL = re.compile(r"(?P<pre>(?:^|[;{\s]))(?P<prop>" + _PROPS + r")(?P<colon>\s*:\s*)(?P<val>[^;}{\"'<>]*)",
                   re.IGNORECASE)
_LENGTH = re.compile(r"(?<![\w.#-])(?P<num>-?\d*\.?\d+)\s*(?P<unit>px|pt)\b", re.IGNORECASE)
_IMPORTANT = re.compile(r"\s*!\s*important", re.IGNORECASE)
_STYLE_ATTR = re.compile(r"(?P<pre>\sstyle\s*=\s*)(?P<q>[\"'])(?P<val>.*?)(?P=q)", re.IGNORECASE | re.DOTALL)
_STYLE_BLOCK = re.compile(r"(?P<open><style\b[^>]*>)(?P<css>.*?)(?P<close></style\s*>)", re.IGNORECASE | re.DOTALL)

# 16px and 12pt are the CSS reference size of 1em.
_PER_EM = {"px": 16.0, "pt": 12.0}


def _format_em(value: float) -> str:
    if abs(value) < 1e-9:
        return "0"
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return f"{text}em"


def _convert_lengths(value: str) -> str:
    def repl(m: re.Match) -> str:
        number = float(m.group("num"))
        return _format_em(number / _PER_EM[m.group("unit").lower()])
    return _LENGTH.sub(repl, value)


def fix_css(css: str) -> Tuple[str, int]:
    """Return the cleaned CSS and the number of declarations changed."""
    changed = 0

    def repl(m: re.Match) -> str:
        nonlocal changed
        value = m.group("val")
        new = _IMPORTANT.sub("", _convert_lengths(value))
        if new != value:
            changed += 1
        return m.group("pre") + m.group("prop") + m.group("colon") + new

    return _DECL.sub(repl, css), changed


def fix_markup(text: str) -> Tuple[str, int]:
    """Clean <style> blocks and style="" attributes in an (X)HTML document."""
    total = 0

    def block(m: re.Match) -> str:
        nonlocal total
        css, n = fix_css(m.group("css"))
        total += n
        return m.group("open") + css + m.group("close")

    def attr(m: re.Match) -> str:
        nonlocal total
        css, n = fix_css(m.group("val"))
        total += n
        return m.group("pre") + m.group("q") + css + m.group("q")

    text = _STYLE_BLOCK.sub(block, text)
    text = _STYLE_ATTR.sub(attr, text)
    return text, total


# ------------------------------------------------------------ front matter

# Words that mark a page as legal/rights/colophon material, in the languages
# a Dutch reader is likely to come across.
_FRONT_ID_WORDS = re.compile(
    r"(rights|watermark|watermerk|colofon|colophon|kolofon|copyright|impressum|legal|disclaimer|rettigheter)",
    re.IGNORECASE)
_FRONT_TEXT_START = re.compile(
    r"^\s*(colofon|colophon|kolofon|copyright|impressum|verantwoording|rettigheter|denne boken tilhører|"
    r"dit e-?book (is|werd)|this e-?book (is|was)|watermerk|watermark)",
    re.IGNORECASE)
_FRONT_EPUB_TYPES = {"copyright-page", "colophon", "imprint", "legal"}
MAX_FRONT_TEXT = 2500  # a longer page is not a colophon
_TAG = re.compile(r"<[^>]+>")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _visible_text(markup: str) -> str:
    body = re.search(r"<body\b[^>]*>(.*)</body>", markup, re.IGNORECASE | re.DOTALL)
    text = body.group(1) if body else markup
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = _TAG.sub(" ", text)
    text = re.sub(r"&#160;|&nbsp;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_front_matter(item_id: str, href: str, markup: str, landmark_types: List[str]) -> bool:
    if any(t in _FRONT_EPUB_TYPES for t in landmark_types):
        return True
    epub_types = set()
    for m in re.finditer(r"epub:type\s*=\s*[\"']([^\"']+)[\"']", markup):
        epub_types.update(m.group(1).split())
    text = _visible_text(markup)
    if len(text) > MAX_FRONT_TEXT:
        return False
    if epub_types & _FRONT_EPUB_TYPES:
        return True
    if _FRONT_ID_WORDS.search(item_id) or _FRONT_ID_WORDS.search(posixpath.basename(href)):
        return True
    title = re.search(r"<title[^>]*>(.*?)</title>", markup, re.IGNORECASE | re.DOTALL)
    title_text = _TAG.sub("", title.group(1)).strip() if title else ""
    return bool(_FRONT_TEXT_START.match(text) or _FRONT_TEXT_START.match(title_text))


# ------------------------------------------------------------------ result

@dataclass
class FixReport:
    css_changes: int = 0
    hyphenated: int = 0
    moved: List[str] = field(default_factory=list)
    skipped_reason: Optional[str] = None

    @property
    def changed(self) -> bool:
        return bool(self.css_changes or self.moved or self.hyphenated)

    def summary(self) -> str:
        if self.skipped_reason:
            return f"niet bewerkt ({self.skipped_reason})"
        parts = []
        if self.css_changes:
            parts.append(f"{self.css_changes} opmaakregel(s) aangepast")
        if self.hyphenated:
            parts.append(f"woordafbreking in {self.hyphenated} bestand(en)")
        if self.moved:
            parts.append("naar achteren verplaatst: " + ", ".join(self.moved))
        return "; ".join(parts) or "geen wijzigingen nodig"


# -------------------------------------------------------------------- main

def _find_opf(zf: zipfile.ZipFile) -> Optional[str]:
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        for el in container.iter():
            if _local(el.tag) == "rootfile" and el.get("full-path"):
                return el.get("full-path")
    except (KeyError, ET.ParseError):
        pass
    return next((n for n in zf.namelist() if n.lower().endswith(".opf")), None)


def _has_drm(zf: zipfile.ZipFile) -> bool:
    try:
        root = ET.fromstring(zf.read("META-INF/encryption.xml"))
    except KeyError:
        return False
    except ET.ParseError:
        return True
    algorithms = {el.get("Algorithm") for el in root.iter() if _local(el.tag) == "EncryptionMethod"}
    return bool(algorithms - FONT_OBFUSCATION)


def _decode(data: bytes) -> Optional[str]:
    for encoding in ("utf-8", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _landmarks(zf: zipfile.ZipFile, opf_dir: str, root: ET.Element, manifest: Dict[str, Dict[str, str]]) -> Tuple[Dict[str, List[str]], Optional[str]]:
    """Map archive path -> landmark types, plus the path where the text starts."""
    types: Dict[str, List[str]] = {}
    start: Optional[str] = None

    def add(href: str, kind: str, base: str) -> None:
        nonlocal start
        path = posixpath.normpath(posixpath.join(base, unquote(href.split("#", 1)[0])))
        types.setdefault(path, []).append(kind)
        if kind in ("text", "bodymatter", "start") and start is None:
            start = path

    for el in root.iter():
        if _local(el.tag) == "reference" and el.get("href") and el.get("type"):
            add(el.get("href"), el.get("type").lower(), opf_dir)
    nav = next((m for m in manifest.values() if "nav" in m.get("properties", "").split()), None)
    if nav:
        try:
            markup = zf.read(nav["path"]).decode("utf-8", "replace")
        except KeyError:
            markup = ""
        section = re.search(r"<nav\b[^>]*epub:type\s*=\s*[\"'][^\"']*landmarks[^\"']*[\"'][^>]*>(.*?)</nav>",
                            markup, re.IGNORECASE | re.DOTALL)
        if section:
            for m in re.finditer(r"<a\b([^>]*)>", section.group(1)):
                attrs = m.group(1)
                href = re.search(r"href\s*=\s*[\"']([^\"']+)", attrs)
                kind = re.search(r"epub:type\s*=\s*[\"']([^\"']+)", attrs)
                if href and kind:
                    for k in kind.group(1).split():
                        add(href.group(1), k.lower(), posixpath.dirname(nav["path"]))
    return types, start


_ITEMREF = re.compile(r"<itemref\b[^>]*?(?:/>|>\s*</itemref>)", re.IGNORECASE | re.DOTALL)
_SPINE = re.compile(r"(<spine\b[^>]*>)(.*?)(</spine>)", re.IGNORECASE | re.DOTALL)


def _reorder_spine(opf_text: str, move_ids: List[str]) -> str:
    m = _SPINE.search(opf_text)
    if not m:
        return opf_text
    inner = m.group(2)
    refs = _ITEMREF.findall(inner)
    keep, moved = [], []
    for ref in refs:
        idref = re.search(r"idref\s*=\s*[\"']([^\"']+)", ref)
        (moved if idref and idref.group(1) in move_ids else keep).append(ref)
    indent = re.search(r"\n([ \t]*)<itemref", inner)
    sep = "\n" + (indent.group(1) if indent else "    ")
    trailing = re.search(r"(\s*)$", inner).group(1) or "\n"
    new_inner = sep + sep.join(keep + moved) + trailing
    return opf_text[:m.start(2)] + new_inner + opf_text[m.end(2):]


def _plan_front_matter(zf, opf_path, root) -> List[Tuple[str, str]]:
    """Return (idref, label) for spine items to move to the end."""
    opf_dir = posixpath.dirname(opf_path)
    manifest: Dict[str, Dict[str, str]] = {}
    for el in root.iter():
        if _local(el.tag) == "item" and el.get("id") and el.get("href"):
            manifest[el.get("id")] = {
                "path": posixpath.normpath(posixpath.join(opf_dir, unquote(el.get("href")))),
                "href": el.get("href"),
                "properties": el.get("properties") or "",
            }
    spine = [el for el in root.iter() if _local(el.tag) == "itemref" and el.get("idref") in manifest]
    if len(spine) < 3:
        return []
    landmark_types, text_start = _landmarks(zf, opf_dir, root, manifest)

    # Only look at the opening of the book: before the "text starts here"
    # landmark if there is one, else the first few items.
    window = min(len(spine) - 1, max(8, len(spine) // 7))
    if text_start:
        for i, el in enumerate(spine):
            if manifest[el.get("idref")]["path"] == text_start:
                window = min(window, i) if i > 0 else window
                break

    planned = []
    for el in spine[:window]:
        info = manifest[el.get("idref")]
        try:
            markup = _decode(zf.read(info["path"])) or ""
        except KeyError:
            continue
        if _looks_like_front_matter(el.get("idref"), info["href"], markup, landmark_types.get(info["path"], [])):
            label = posixpath.basename(info["href"])
            heading = _visible_text(markup)[:40].strip()
            planned.append((el.get("idref"), f"{label} ({heading})" if heading else label))
    if len(planned) >= len(spine):
        return []
    return planned


def process(src: Path, dest: Path, fix_styles: bool = True, move_front_matter: bool = True,
            hyphenate: bool = False) -> FixReport:
    """Write an improved copy of ``src`` to ``dest`` if anything needs changing.

    ``dest`` only exists afterwards when the report says something changed.
    """
    report = FixReport()
    if dest.exists():
        dest.unlink()
    if not (fix_styles or move_front_matter or hyphenate):
        return report
    try:
        with zipfile.ZipFile(src) as zf:
            if _has_drm(zf):
                report.skipped_reason = "DRM"
                return report
            opf_path = _find_opf(zf)
            if not opf_path:
                report.skipped_reason = "geen OPF"
                return report
            opf_bytes = zf.read(opf_path)
            opf_text = _decode(opf_bytes)
            if opf_text is None:
                report.skipped_reason = "onleesbare OPF"
                return report
            root = ET.fromstring(opf_bytes)
            if re.search(r"rendition:layout[^<]*pre-paginated", opf_text):
                report.skipped_reason = "vaste opmaak"
                return report

            replacements: Dict[str, bytes] = {}
            if move_front_matter:
                planned = _plan_front_matter(zf, opf_path, root)
                if planned:
                    new_opf = _reorder_spine(opf_text, [idref for idref, _ in planned])
                    if new_opf != opf_text:
                        ET.fromstring(new_opf.encode("utf-8"))  # must still be valid XML
                        replacements[opf_path] = new_opf.encode("utf-8")
                        report.moved = [label for _, label in planned]

            language = _book_language(root)
            for info in zf.infolist():
                name = info.filename.lower()
                is_css = name.endswith(CSS_EXTENSIONS)
                is_doc = (name.endswith((".xhtml", ".html", ".htm")) and not name.startswith("meta-inf/"))
                if not ((fix_styles and (is_css or is_doc or name.endswith(".xml"))) or (hyphenate and is_doc)):
                    continue
                if info.filename == opf_path or name.startswith("meta-inf/"):
                    continue
                text = _decode(zf.read(info))
                if text is None:
                    continue
                new = text
                if fix_styles:
                    new, count = (fix_css if is_css else fix_markup)(new)
                    report.css_changes += count
                if hyphenate and is_doc:
                    new, done = add_hyphenation(new, language)
                    report.hyphenated += int(done)
                if new != text:
                    replacements[info.filename] = new.encode("utf-8")

            if not replacements:
                return report
            _write_copy(zf, dest, replacements)
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError) as exc:
        log.warning("%s: kon geen bewerkte kopie maken (%s); origineel wordt gebruikt", src.name, exc)
        if dest.exists():
            dest.unlink()
        return FixReport(skipped_reason=f"fout: {exc}")
    return report


def _write_copy(zf: zipfile.ZipFile, dest: Path, replacements: Dict[str, bytes]) -> None:
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with zipfile.ZipFile(tmp, "w") as out:
        infos = zf.infolist()
        # The mimetype entry must come first and be stored uncompressed.
        infos.sort(key=lambda i: i.filename != "mimetype")
        for info in infos:
            data = replacements.get(info.filename)
            if data is None:
                data = zf.read(info)
            new_info = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new_info.external_attr = info.external_attr
            new_info.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            out.writestr(new_info, data)
    tmp.replace(dest)


# ------------------------------------------------------------ hyphenation

HYPHENATE_MARKER = "kobosync: woordafbreking"
HYPHENATE_STYLE = (
    f'<style type="text/css">/* {HYPHENATE_MARKER} */\n'
    "p, li, dd, blockquote, td { -webkit-hyphens: auto; -epub-hyphens: auto; hyphens: auto; "
    "adobe-hyphenate: auto; }\n"
    "h1, h2, h3, h4, h5, h6 { -webkit-hyphens: manual; -epub-hyphens: manual; hyphens: manual; "
    "adobe-hyphenate: none; }\n"
    "</style>")
_HEAD_END = re.compile(r"</head\s*>", re.IGNORECASE)
_HTML_OPEN = re.compile(r"<html\b([^>]*)>", re.IGNORECASE)


def add_hyphenation(markup: str, language: Optional[str]) -> Tuple[str, bool]:
    """Ask the renderer to hyphenate body text.  Hyphenation needs a language,
    so the book's language is set on <html> when the document has none."""
    if HYPHENATE_MARKER in markup:
        return markup, False
    head = _HEAD_END.search(markup)
    if not head:
        return markup, False
    markup = markup[:head.start()] + HYPHENATE_STYLE + markup[head.start():]
    if language:
        html = _HTML_OPEN.search(markup)
        if html and not re.search(r"\blang\s*=", html.group(1)):
            attrs = html.group(1) + f' xml:lang="{language}" lang="{language}"'
            markup = markup[:html.start()] + f"<html{attrs}>" + markup[html.end():]
    return markup, True


def _book_language(root: ET.Element) -> Optional[str]:
    for el in root.iter():
        if _local(el.tag) == "language" and (el.text or "").strip():
            lang = el.text.strip()
            return lang if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{1,8})*", lang) else None
    return None


# --------------------------------------------------------------- text start

# Headings of pages that come before the story itself.
_FRONT_TITLES = re.compile(
    r"^\s*(cover|omslag|titel(pagina)?|title( page)?|inhoud(sopgave)?|contents|table of contents|innhold|"
    r"opdracht|dedication|tilegnelse|motto|epigra(af|ph|f)|over (het boek|de auteurs?|deze uitgave)|"
    r"about the (book|authors?)|om (boken|forfatter(ne|en)?)|colofon|colophon|kolofon|copyright|"
    r"van dezelfde auteurs?|ook (van|verschenen)|i samme serie|av samme forfatter|also by)\b",
    re.IGNORECASE)
# Headings that mark the start of the story, even on a short page.
_STORY_TITLES = re.compile(
    r"^\s*(proloog|prologue|prolog|hoofdstuk|chapter|kapittel|kapitel|deel|part|del|een|één|one|en|"
    r"1|i)\b[\s.:]*", re.IGNORECASE)
_HEADING = re.compile(r"<h([1-4])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
MIN_STORY_TEXT = 1200  # a page with this much text is not front matter


def _first_heading(markup: str) -> str:
    body = re.search(r"<body\b.*", markup, re.IGNORECASE | re.DOTALL)
    m = _HEADING.search(body.group(0) if body else markup)
    return re.sub(r"\s+", " ", _TAG.sub(" ", m.group(2))).strip() if m else ""


def find_text_start(path: Path) -> Optional[str]:
    """Archive path of the document where the story starts, or None when the
    book already opens there (or the start cannot be told)."""
    try:
        with zipfile.ZipFile(path) as zf:
            opf_path = _find_opf(zf)
            if not opf_path:
                return None
            root = ET.fromstring(zf.read(opf_path))
            opf_dir = posixpath.dirname(opf_path)
            manifest: Dict[str, Dict[str, str]] = {}
            for el in root.iter():
                if _local(el.tag) == "item" and el.get("id") and el.get("href"):
                    manifest[el.get("id")] = {
                        "path": posixpath.normpath(posixpath.join(opf_dir, unquote(el.get("href")))),
                        "href": el.get("href"),
                        "properties": el.get("properties") or "",
                    }
            spine = [manifest[el.get("idref")]["path"] for el in root.iter()
                     if _local(el.tag) == "itemref" and el.get("idref") in manifest
                     and (el.get("linear") or "yes").lower() != "no"]
            if len(spine) < 2:
                return None
            _, landmark = _landmarks(zf, opf_dir, root, manifest)
            if landmark in spine:
                return landmark if landmark != spine[0] else None

            window = spine[:max(8, min(15, len(spine) // 3))]
            for doc in window:
                try:
                    markup = _decode(zf.read(doc)) or ""
                except KeyError:
                    continue
                types = set()
                for m in re.finditer(r"epub:type\s*=\s*[\"']([^\"']+)[\"']", markup):
                    types.update(m.group(1).split())
                heading = _first_heading(markup)
                text = _visible_text(markup)
                if types & {"bodymatter", "chapter", "prologue", "part"}:
                    found = doc
                elif _FRONT_TITLES.match(heading) or _FRONT_TITLES.match(text) or types & _FRONT_EPUB_TYPES:
                    continue
                elif _STORY_TITLES.match(heading) or len(text) >= MIN_STORY_TEXT:
                    found = doc
                else:
                    continue
                return found if found != spine[0] else None
    except (zipfile.BadZipFile, ET.ParseError, OSError, KeyError):
        return None
    return None


_KOBO_SPAN = re.compile(r"""id\s*=\s*["'](kobo\.\d+\.\d+)["']""")


def first_kobo_span(path: Path, doc: str) -> Optional[str]:
    """The first KoboSpan id in a KEPUB document, where a bookmark can point."""
    try:
        with zipfile.ZipFile(path) as zf:
            m = _KOBO_SPAN.search(zf.read(doc).decode("utf-8", "replace"))
    except (zipfile.BadZipFile, OSError, KeyError):
        return None
    return m.group(1) if m else None
