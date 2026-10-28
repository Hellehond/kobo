"""Extract the metadata a Kobo device needs (title, authors, cover, ...) from an EPUB/KEPUB."""
from __future__ import annotations

import logging
import posixpath
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import unquote
from xml.etree import ElementTree as ET

log = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


@dataclass
class BookMeta:
    title: str
    authors: List[str] = field(default_factory=list)
    language: Optional[str] = None
    publisher: Optional[str] = None
    description: Optional[str] = None
    pubdate: Optional[str] = None
    isbn: Optional[str] = None
    series: Optional[str] = None
    series_index: Optional[float] = None
    cover: Optional[Tuple[bytes, str]] = None  # (bytes, extension)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _attr(el: ET.Element, name: str) -> Optional[str]:
    """Attribute lookup that ignores namespaces (opf:scheme vs scheme)."""
    for key, value in el.attrib.items():
        if _local(key) == name:
            return value
    return None


def title_from_filename(path: Path) -> str:
    name = path.name
    for suffix in (".kepub.epub", ".kepub", ".epub"):
        if name.lower().endswith(suffix):
            name = name[: -len(suffix)]
            break
    return name.replace("_", " ").strip() or path.name


def _find_opf(zf: zipfile.ZipFile) -> str:
    try:
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        for el in container.iter():
            if _local(el.tag) == "rootfile" and el.get("full-path"):
                return el.get("full-path")
    except (KeyError, ET.ParseError):
        pass
    for name in zf.namelist():
        if name.lower().endswith(".opf"):
            return name
    raise KeyError("no OPF package document found")


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _find_cover_href(root: ET.Element, metadata: Optional[ET.Element], manifest: Optional[ET.Element]) -> Optional[Tuple[str, str]]:
    if manifest is None:
        return None
    items = [el for el in manifest if _local(el.tag) == "item"]
    by_id = {el.get("id"): el for el in items if el.get("id")}

    def result(el: ET.Element) -> Optional[Tuple[str, str]]:
        href = el.get("href")
        media = (el.get("media-type") or "").lower()
        if not href:
            return None
        if media not in IMAGE_EXTENSIONS and not re.search(r"\.(jpe?g|png|gif|webp)$", href, re.I):
            return None
        return href, media

    # EPUB 3: manifest item with properties="cover-image"
    for el in items:
        props = (el.get("properties") or "").split()
        if "cover-image" in props:
            found = result(el)
            if found:
                return found
    # EPUB 2: <meta name="cover" content="item-id"/>
    if metadata is not None:
        for el in metadata:
            if _local(el.tag) == "meta" and el.get("name") == "cover" and el.get("content"):
                target = by_id.get(el.get("content"))
                if target is not None:
                    found = result(target)
                    if found:
                        return found
    # Heuristic: an image whose id or href mentions "cover"
    for el in items:
        ident = (el.get("id") or "").lower()
        href = (el.get("href") or "").lower()
        if "cover" in ident or "cover" in href:
            found = result(el)
            if found:
                return found
    return None


def read_metadata(path: Path) -> BookMeta:
    meta = BookMeta(title=title_from_filename(path))
    try:
        with zipfile.ZipFile(path) as zf:
            opf_path = _find_opf(zf)
            root = ET.fromstring(zf.read(opf_path))
            metadata = next((c for c in root if _local(c.tag) == "metadata"), None)
            manifest = next((c for c in root if _local(c.tag) == "manifest"), None)
            if metadata is not None:
                _parse_metadata(metadata, meta)
            cover = _find_cover_href(root, metadata, manifest)
            if cover:
                href, media = cover
                cover_path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), unquote(href)))
                try:
                    data = zf.read(cover_path)
                    ext = IMAGE_EXTENSIONS.get(media) or Path(cover_path).suffix.lower() or ".jpg"
                    if data:
                        meta.cover = (data, ext)
                except KeyError:
                    log.warning("%s: cover %s not found in archive", path.name, cover_path)
    except (zipfile.BadZipFile, ET.ParseError, KeyError, OSError) as exc:
        log.warning("%s: could not read metadata (%s); using filename", path.name, exc)
    return meta


def _parse_metadata(metadata: ET.Element, meta: BookMeta) -> None:
    titles: List[str] = []
    collections = {}  # id -> {"name":..., "type":..., "position":...}
    refinements = []
    for el in metadata:
        tag = _local(el.tag)
        text = (el.text or "").strip()
        if tag == "title" and text:
            titles.append(text)
        elif tag == "creator" and text:
            meta.authors.append(text)
        elif tag == "language" and text and not meta.language:
            meta.language = text
        elif tag == "publisher" and text and not meta.publisher:
            meta.publisher = text
        elif tag == "description" and text and not meta.description:
            meta.description = _strip_html(text)
        elif tag == "date" and text and not meta.pubdate:
            meta.pubdate = text
        elif tag == "identifier" and text:
            scheme = (_attr(el, "scheme") or "").lower()
            value = text
            if value.lower().startswith("urn:isbn:"):
                value = value[9:]
                scheme = "isbn"
            digits = value.replace("-", "").replace(" ", "")
            if scheme == "isbn" or (digits.isdigit() and len(digits) in (10, 13) and digits.startswith("97")):
                meta.isbn = meta.isbn or digits
        elif tag == "meta":
            name = el.get("name")
            prop = el.get("property")
            content = el.get("content")
            if name == "calibre:series" and content:
                meta.series = content
            elif name == "calibre:series_index" and content:
                try:
                    meta.series_index = float(content)
                except ValueError:
                    pass
            elif prop == "belongs-to-collection" and text:
                collections[el.get("id") or text] = {"name": text, "type": None, "position": None}
            elif prop in ("collection-type", "group-position") and el.get("refines"):
                refinements.append((el.get("refines").lstrip("#"), prop, text))
    for ref_id, prop, text in refinements:
        if ref_id in collections:
            key = "type" if prop == "collection-type" else "position"
            collections[ref_id][key] = text
    if not meta.series:
        for col in collections.values():
            if col["type"] in (None, "series"):
                meta.series = col["name"]
                try:
                    meta.series_index = float(col["position"]) if col["position"] else None
                except ValueError:
                    meta.series_index = None
                break
    if titles:
        meta.title = titles[0]
    if meta.language:
        meta.language = meta.language.split("-")[0].lower() or None
