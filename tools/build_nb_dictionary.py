#!/usr/bin/env python3
"""Build a Norwegian (Bokmål) dictionary for Kobo e-readers from Bokmålsordboka.

    python tools/build_nb_dictionary.py                # download/update and build
    python tools/build_nb_dictionary.py --no-update    # build from the local cache

The result, dicthtml-nb.zip, goes into the .kobo/custom-dict folder of each
Kobo (firmware 4.24 or newer).

Data: Bokmålsordboka, Universitetet i Bergen og Språkrådet, ordbøkene.no,
licensed CC BY 4.0. Every entry carries that attribution.

The Kobo dictionary format follows https://pgaskin.net/dictutil/dicthtml/format.html:
a zip with a marisa-trie index named "words" and gzip-compressed HTML files
named after the first two letters of the words they hold.
"""
from __future__ import annotations

import argparse
import gzip
import html
import json
import logging
import re
import sys
import tempfile
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nbdict_fetch  # noqa: E402

log = logging.getLogger("nbdict")

ATTRIBUTION = "Bokmålsordboka, Universitetet i Bergen og Språkrådet, ordbøkene.no, CC BY 4.0"
LOCALE = "nb"

WORD_CLASSES = {
    "NOUN": "substantiv", "VERB": "verb", "ADJ": "adjektiv", "ADV": "adverb", "PRON": "pronomen",
    "DET": "determinativ", "ADP": "preposisjon", "CCONJ": "konjunksjon", "SCONJ": "subjunksjon",
    "INTJ": "interjeksjon", "NUM": "tallord", "PROPN": "egennavn", "EXPR": "uttrykk",
    "ABBR": "forkortelse", "SYM": "symbol", "PFX": "prefiks", "SFX": "suffiks",
}
GENDERS = {"Masc": "hankjønn", "Fem": "hunkjønn", "Neuter": "intetkjønn"}
# Forms shown on the "bøying" line, per word class: (label prefix, tag test).
FORM_SLOTS = {
    "VERB": [("", lambda t: t == ("Pres",)), ("", lambda t: t == ("Past",)), ("har ", lambda t: t == ("<PerfPart>",))],
    "NOUN": [("", lambda t: t == ("Sing", "Def")), ("", lambda t: t == ("Plur", "Ind")),
             ("", lambda t: t == ("Plur", "Def"))],
    "ADJ": [("", lambda t: t[:2] == ("Pos", "Neuter")), ("", lambda t: t == ("Pos", "Plur")),
            ("", lambda t: "Cmp" in t), ("", lambda t: "Sup" in t and "Def" not in t)],
}


# ------------------------------------------------------------------ helpers

def esc(text: str) -> str:
    return html.escape(text, quote=True)


def lemma_text(text: str) -> str:
    """'legge seg [bort i|borti]' -> 'legge seg bort i/borti'."""
    return re.sub(r"\[([^\]]*)\]", lambda m: m.group(1).replace("|", "/"), text)


def kobo_prefix(word: str) -> str:
    """The dicthtml file a word belongs in; a port of dictutil's WordPrefix."""
    chars: List[str] = []
    for c in word:
        if len(chars) >= 2 or c == "\x00":
            break
        chars.append(c.lower())
    while chars and chars[0].isspace():
        chars.pop(0)
    while chars and chars[-1].isspace():
        chars.pop()
    if not chars:
        return "11"
    if not _is_cyrillic(chars[0]):
        while len(chars) < 2:
            chars.append("a")
        if not (chars[0].isalpha() and chars[1].isalpha()):
            return "11"
    return "".join(chars)


def _is_cyrillic(c: str) -> bool:
    try:
        return "CYRILLIC" in unicodedata.name(c)
    except ValueError:
        return False


def normalise_variant(word: str) -> str:
    return unicodedata.normalize("NFC", word.strip().lower())


# ---------------------------------------------------------------- rendering

class Renderer:
    def __init__(self, concepts: Dict[str, dict]):
        self.concepts = concepts
        self.in_quote = False  # inside an example: the cited word needs no italics

    def concept(self, concept_id: str) -> str:
        found = self.concepts.get(concept_id) or {}
        return found.get("expansion") or concept_id

    def item(self, item: dict) -> str:
        kind = item.get("type_")
        if kind == "article_ref":
            if item.get("word_form"):
                return esc(item["word_form"])
            names = [lemma_text(l.get("lemma", "")) for l in item.get("lemmas", []) if l.get("lemma")]
            return esc("/".join(names))
        if kind == "usage":
            text = esc(item.get("text", ""))
            return text if self.in_quote else f"<i>{text}</i>"
        if kind == "fraction":
            return f"{item.get('numerator')}/{item.get('denominator')}"
        if kind in ("superscript", "subscript"):
            tag = "sup" if kind == "superscript" else "sub"
            return f"<{tag}>{esc(str(item.get('text', '')))}</{tag}>"
        if "content" in item:
            return self.fill(item.get("content", ""), item.get("items", []))
        if "id" in item:
            return esc(self.concept(item["id"]))
        if "text" in item:
            return esc(str(item["text"]))
        return ""

    def fill(self, content: str, items: List[dict]) -> str:
        """Replace each $ in content with the next rendered item."""
        parts = (content or "").split("$")
        out = [esc(parts[0])]
        for i, part in enumerate(parts[1:]):
            out.append(self.item(items[i]) if i < len(items) else "")
            out.append(esc(part))
        return "".join(out).strip()

    def example(self, el: dict) -> str:
        self.in_quote = True
        try:
            quote = self.fill(el.get("quote", {}).get("content", ""), el.get("quote", {}).get("items", []))
        finally:
            self.in_quote = False
        expl = self.fill(el.get("explanation", {}).get("content", ""), el.get("explanation", {}).get("items", []))
        if not quote:
            return ""
        return f"<i>{quote}</i>" + (f" ({expl})" if expl else "")

    def definition(self, d: dict, phrases: List[dict]) -> Tuple[str, List[str]]:
        """Render one definition: (its own text, rendered sub-definitions)."""
        texts: List[str] = []
        examples: List[str] = []
        subs: List[str] = []
        for el in d.get("elements", []):
            kind = el.get("type_")
            if kind == "explanation":
                text = self.fill(el.get("content", ""), el.get("items", []))
                if text:
                    texts.append(text)
            elif kind == "example":
                text = self.example(el)
                if text:
                    examples.append(text)
            elif kind == "definition":
                own, nested = self.definition(el, phrases)
                subs.append(own + self.numbered(nested))
            elif kind == "sub_article":
                phrases.append(el)
            elif kind == "compound_list":
                names = [self.item(ref) for ref in el.get("elements", [])]
                intro = self.fill(el.get("intro", {}).get("content", ""), el.get("intro", {}).get("items", []))
                if names:
                    texts.append(f"{intro}: {', '.join(names)}" if intro else ", ".join(names))
        own = "; ".join(texts)
        if examples:
            own += ("<br/>" if own else "") + "; ".join(examples)
        return own, subs

    @staticmethod
    def numbered(items: List[str]) -> str:
        items = [i for i in items if i]
        if not items:
            return ""
        return "<ol>" + "".join(f"<li>{i}</li>" for i in items) + "</ol>"

    def body(self, body: dict, phrases: List[dict]) -> str:
        out: List[str] = []
        for top in body.get("definitions", []):
            own, subs = self.definition(top, phrases)
            if own:
                out.append(f"<p>{own}</p>")
            if len(subs) == 1:
                out.append(f"<p>{subs[0]}</p>")
            else:
                out.append(self.numbered(subs))
        return "".join(out)

    def pronunciation(self, body: dict) -> str:
        pron = [self.fill(p.get("content", ""), p.get("items", [])) for p in body.get("pronunciation", [])]
        pron = [p for p in pron if p]
        return f"<p><small>uttale: [{', '.join(pron)}]</small></p>" if pron else ""

    def article(self, article: dict) -> str:
        body = article.get("body", {})
        parts: List[str] = []
        phrases: List[dict] = []
        parts.append(self.body(body, phrases))
        if phrases:
            items = []
            for ph in phrases:
                sub = ph.get("article", {})
                names = [lemma_text(l.get("lemma", "")) for l in sub.get("lemmas", []) if l.get("lemma")]
                names = names or [lemma_text(x) for x in ph.get("lemmas", []) if isinstance(x, str)]
                text = self.body(sub.get("body", {}), [])
                single = re.fullmatch(r"<p>((?:(?!<p>).)*)</p>", text, re.DOTALL)
                if single:  # one short meaning: keep it on the line of the expression
                    text = single.group(1)
                items.append(f"<li><b>{esc(', '.join(names))}</b> {text}</li>")
            parts.append("<p><b>faste uttrykk</b></p><ul>" + "".join(items) + "</ul>")
        etym = [self.fill(e.get("content", ""), e.get("items", [])) for e in body.get("etymology", [])]
        etym = [e for e in etym if e]
        if etym:
            parts.append(f"<p><small>opphav: {'; '.join(etym)}</small></p>")
        return "".join(parts)


# -------------------------------------------------------------------- entries

@dataclass
class Entry:
    headword: str
    other_lemmas: List[str]
    word_class: str
    forms_shown: List[str]
    variants: Set[str] = field(default_factory=set)
    pronunciation: str = ""
    body: str = ""

    def html(self) -> str:
        names = ", ".join(esc(n) for n in [self.headword, *self.other_lemmas])
        head = f'<p><a name="{esc(self.headword)}" /><b>{names}</b>'
        if self.word_class:
            head += f" <i>{esc(self.word_class)}</i>"
        head += "</p>"
        var = "<var>" + "".join(f'<variant name="{esc(v)}"/>' for v in sorted(self.variants)) + "</var>"
        forms = f"<p><small>bøying: {esc(', '.join(self.forms_shown))}</small></p>" if self.forms_shown else ""
        return (f"<w>{head}{var}{self.pronunciation}{forms}{self.body}"
                f"<p><small>{esc(ATTRIBUTION)}</small></p></w>")

    def words(self) -> Set[str]:
        return {self.headword.strip(), *self.variants}


def word_class(lemmas: List[dict]) -> str:
    classes: List[str] = []
    genders: List[str] = []
    for lemma in lemmas:
        for paradigm in lemma.get("paradigm_info", []):
            tags = paradigm.get("tags") or []
            if tags and tags[0] in WORD_CLASSES and WORD_CLASSES[tags[0]] not in classes:
                classes.append(WORD_CLASSES[tags[0]])
            for tag in tags[1:]:
                if tag in GENDERS and GENDERS[tag] not in genders:
                    genders.append(GENDERS[tag])
    text = ", ".join(classes)
    if genders and "substantiv" in classes:
        text += " " + " eller ".join(genders)
    return text


def forms_line(lemma: dict) -> List[str]:
    """Key inflected forms, alternatives joined with a slash: 'bedøver, bedøvet/bedøva, har bedøvet/bedøva'."""
    paradigms = [p for p in lemma.get("paradigm_info", [])
                 if p.get("to") is None and p.get("standardisation") == "STANDARD" and p.get("tags")]
    if not paradigms:
        return []
    slots = FORM_SLOTS.get(paradigms[0]["tags"][0], [])
    shown: List[str] = []
    for prefix, test in slots:
        forms: List[str] = []
        for paradigm in paradigms:
            for form in paradigm.get("inflection", []):
                word = (form.get("word_form") or "").strip()
                if word and test(tuple(form.get("tags") or ())) and word not in forms:
                    forms.append(word)
                    break
        if forms:
            shown.append(prefix + "/".join(forms))
    return shown


def build_entry(article: dict, renderer: Renderer) -> Optional[Entry]:
    lemmas = [l for l in article.get("lemmas", []) if l.get("lemma")]
    if not lemmas:
        return None
    names = []
    for lemma in lemmas:
        name = lemma_text(lemma["lemma"]).strip()
        if name and name not in names:
            names.append(name)
    headword = names[0]
    entry = Entry(headword=headword, other_lemmas=names[1:], word_class=word_class(lemmas), forms_shown=[])

    for name in names:
        # "veidekke/vegdekke" holds two spellings; "i/til en viss grad" is one
        # expression, whose parts must not become words of their own.
        if not any(c.isspace() for c in name):
            for part in name.split("/"):
                entry.variants.add(normalise_variant(part))
    for lemma in lemmas:
        for paradigm in lemma.get("paradigm_info", []):
            for form in paradigm.get("inflection", []):
                word = (form.get("word_form") or "").strip()
                if word and not any(c.isspace() for c in word):
                    entry.variants.add(normalise_variant(word))
    entry.forms_shown = forms_line(lemmas[0])
    entry.variants.discard(headword.strip())
    entry.variants = {v for v in entry.variants if v}
    entry.pronunciation = renderer.pronunciation(article.get("body", {}))
    entry.body = renderer.article(article)
    return entry


# --------------------------------------------------------------------- writer

def write_kobo_dictionary(entries: Iterable[Entry], out: Path) -> Dict[str, int]:
    import marisa_trie

    files: Dict[str, List[Tuple[tuple, str]]] = defaultdict(list)
    words: Set[str] = set()
    count = 0
    for entry in entries:
        count += 1
        words |= entry.words()
        markup = entry.html()
        # The entry must be in the file of every prefix it can be found by,
        # or Kobo silently ignores the headword or variant there.
        by_prefix: Dict[str, str] = {}
        for word in [entry.headword, *sorted(entry.variants, key=lambda w: (len(w), w))]:
            by_prefix.setdefault(kobo_prefix(word), word)
        head = entry.headword.lower()
        for prefix, word in by_prefix.items():
            # Kobo shows every match in file order: shortest words first (its
            # fallback takes the first prefix match), and for each word the
            # entries that have it as headword before those where it is a form.
            files[prefix].append(((len(word), word.lower(), head != word.lower(), len(head), head), markup))

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with tempfile.TemporaryDirectory() as tmpdir:
        trie_path = Path(tmpdir) / "words"
        marisa_trie.Trie(sorted(words)).save(str(trie_path))
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.write(trie_path, "words", compress_type=zipfile.ZIP_DEFLATED)
            for prefix in sorted(files):
                # Shortest first: Kobo falls back to the first prefix match.
                rows = sorted(files[prefix], key=lambda r: r[0])
                doc = '<?xml version="1.0" encoding="utf-8"?><html>' + "\n".join(r[1] for r in rows) + "</html>"
                zf.writestr(f"{prefix}.html", gzip.compress(doc.encode("utf-8"), 9),
                            compress_type=zipfile.ZIP_STORED)
    tmp.replace(out)
    return {"entries": count, "words": len(words), "files": len(files)}


def build(cache: nbdict_fetch.Cache, out: Path) -> Dict[str, int]:
    concepts = json.loads(cache.get_file("concepts.json") or b'{"concepts": {}}')["concepts"]
    renderer = Renderer(concepts)

    def entries():
        for article in cache.articles():
            entry = build_entry(article, renderer)
            if entry is not None:
                yield entry

    return write_kobo_dictionary(entries(), out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", default="build/nbdict-cache.sqlite", help="local copy of the articles")
    parser.add_argument("--out", default=f"build/dicthtml-{LOCALE}.zip", help="dictionary file to write")
    parser.add_argument("--no-update", action="store_true", help="do not download, use the cache as it is")
    parser.add_argument("--limit", type=int, help="download at most this many articles (for testing)")
    parser.add_argument("--workers", type=int, default=nbdict_fetch.WORKERS,
                        help=f"parallel downloads, at most 8 (default {nbdict_fetch.WORKERS})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    cache = nbdict_fetch.Cache(Path(args.cache))
    if not args.no_update:
        nbdict_fetch.update(cache, limit=args.limit, workers=args.workers)
    stats = build(cache, Path(args.out))
    size = Path(args.out).stat().st_size / 1024 / 1024
    log.info("Wrote %s: %d entries, %d words, %d files, %.1f MB", args.out, stats["entries"], stats["words"],
             stats["files"], size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
