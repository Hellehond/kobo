import gzip
import re
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import build_nb_dictionary as nb  # noqa: E402

CONCEPTS = {"jf": {"class": "relation", "expansion": "jamfør"}, "gr.": {"class": "language", "expansion": "gresk"}}


def paradigm(tags, forms, std="STANDARD", to=None):
    return {"tags": tags, "standardisation": std, "to": to,
            "inflection": [{"word_form": w, "tags": t} for w, t in forms]}


GAA = {
    "article_id": 1,
    "lemmas": [{"lemma": "gå", "hgno": 1, "paradigm_info": [paradigm(["VERB"], [
        ("gå", ["Inf"]), ("går", ["Pres"]), ("gikk", ["Past"]), ("gått", ["<PerfPart>"]), (None, []),
        ("gå", ["Imp"])])]}],
    "body": {
        "pronunciation": [{"type_": "pronunciation", "content": "gåː", "items": []}],
        "definitions": [{"type_": "definition", "elements": [
            {"type_": "definition", "elements": [
                {"type_": "explanation", "content": "bevege seg til fots; $ $", "items": [
                    {"type_": "relation", "id": "jf"},
                    {"type_": "article_ref", "lemmas": [{"lemma": "spasere"}]}]},
                {"type_": "example", "quote": {"content": "$ en tur", "items": [{"type_": "usage", "text": "gå"}]},
                 "explanation": {"content": "", "items": []}},
            ]},
            {"type_": "definition", "elements": [
                {"type_": "explanation", "content": "fungere", "items": []},
                {"type_": "sub_article", "lemmas": ["gå [an|ann]"], "article": {
                    "lemmas": [{"lemma": "gå [an|ann]"}],
                    "body": {"definitions": [{"type_": "definition", "elements": [
                        {"type_": "explanation", "content": "være mulig", "items": []}]}]}}},
            ]},
        ]}],
        "etymology": [{"type_": "etymology_language", "content": "fra $ <x>", "items": [{"type_": "language", "id": "gr."}]}],
    },
}

BIL = {
    "article_id": 2,
    "lemmas": [{"lemma": "bil", "paradigm_info": [paradigm(["NOUN", "Masc"], [
        ("bil", ["Sing", "Ind"]), ("bilen", ["Sing", "Def"]), ("biler", ["Plur", "Ind"]),
        ("bilene", ["Plur", "Def"])])]}],
    "body": {"definitions": [{"type_": "definition", "elements": [
        {"type_": "explanation", "content": "motorvogn", "items": []}]}]},
}


@pytest.mark.parametrize("word, prefix", [
    ("gå", "gå"), ("Gikk", "gi"), ("a", "aa"), (" b", "ba"), ("a-en", "11"), ("3D", "11"),
    ("", "11"), ("øy", "øy"), ("Ål", "ål"), ("ж", "ж"), ("x\x00y", "xa"),
])
def test_kobo_prefix_matches_dictutil(word, prefix):
    assert nb.kobo_prefix(word) == prefix


def test_lemma_text():
    assert nb.lemma_text("legge seg [bort i|borti]") == "legge seg bort i/borti"


def test_entry_rendering():
    entry = nb.build_entry(GAA, nb.Renderer(CONCEPTS))
    assert entry.headword == "gå" and entry.word_class == "verb"
    assert entry.forms_shown == ["går", "gikk", "har gått"]
    assert entry.variants == {"går", "gikk", "gått"}
    markup = entry.html()
    assert markup.startswith('<w><p><a name="gå" /><b>gå</b> <i>verb</i></p><var>')
    assert '<variant name="gikk"/>' in markup
    assert "uttale: [gåː]" in markup
    assert "bevege seg til fots; jamfør spasere" in markup
    assert "<i>gå en tur</i>" in markup  # cited word inside an example is not doubly italic
    assert "<ol><li>" in markup and "<li><b>gå an/ann</b> være mulig</li>" in markup
    assert "opphav: fra gresk &lt;x&gt;" in markup  # text is escaped
    assert nb.ATTRIBUTION in markup
    assert markup.endswith("</w>")


def test_noun_and_gender():
    entry = nb.build_entry(BIL, nb.Renderer({}))
    assert entry.word_class == "substantiv hankjønn"
    assert entry.forms_shown == ["bilen", "biler", "bilene"]


def test_alternative_forms_are_joined():
    lemma = {"lemma": "bedøve", "paradigm_info": [
        paradigm(["VERB"], [("bedøver", ["Pres"]), ("bedøva", ["Past"]), ("bedøva", ["<PerfPart>"])]),
        paradigm(["VERB"], [("bedøver", ["Pres"]), ("bedøvet", ["Past"]), ("bedøvet", ["<PerfPart>"])]),
        paradigm(["VERB"], [("bedøvte", ["Past"])], std="REGISTERED"),
    ]}
    assert nb.forms_line(lemma) == ["bedøver", "bedøva/bedøvet", "har bedøva/bedøvet"]


def read_dict(path):
    with zipfile.ZipFile(path) as zf:
        docs = {n: gzip.decompress(zf.read(n)).decode() for n in zf.namelist() if n.endswith(".html")}
        return zf, docs, zf.read("words")


def test_dictionary_file(tmp_path):
    marisa_trie = pytest.importorskip("marisa_trie")
    renderer = nb.Renderer(CONCEPTS)
    entries = [nb.build_entry(a, renderer) for a in (GAA, BIL)]
    out = tmp_path / "dicthtml-nb.zip"
    stats = nb.write_kobo_dictionary(entries, out)
    assert stats["entries"] == 2

    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        docs = {n: gzip.decompress(zf.read(n)).decode() for n in names if n.endswith(".html")}
        (tmp_path / "words").write_bytes(zf.read("words"))
    # "gikk" starts with other letters than "gå": the entry is copied there.
    assert {"words", "gå.html", "gi.html", "bi.html"} <= names
    assert '<a name="gå" />' in docs["gi.html"] and '<variant name="gikk"/>' in docs["gi.html"]
    for doc in docs.values():
        assert doc.startswith('<?xml version="1.0" encoding="utf-8"?><html>') and doc.endswith("</html>")
        assert doc.count("<w>") == doc.count("</w>")

    trie = marisa_trie.Trie()
    trie.load(str(tmp_path / "words"))
    assert {"gå", "gikk", "gått", "bil", "bilene"} <= set(trie.keys())


def test_entries_are_sorted_shortest_first(tmp_path):
    pytest.importorskip("marisa_trie")
    renderer = nb.Renderer({})
    arts = []
    for i, word in enumerate(["bilene", "bi", "bil"]):
        art = {"article_id": i, "lemmas": [{"lemma": word, "paradigm_info": []}],
               "body": {"definitions": []}}
        arts.append(nb.build_entry(art, renderer))
    out = tmp_path / "d.zip"
    nb.write_kobo_dictionary(arts, out)
    with zipfile.ZipFile(out) as zf:
        doc = gzip.decompress(zf.read("bi.html")).decode()
    assert re.findall(r'<a name="([^"]+)" />', doc) == ["bi", "bil", "bilene"]


def test_expressions_do_not_claim_their_words():
    art = {"article_id": 9, "lemmas": [{"lemma": "i/til en viss grad", "paradigm_info": []}],
           "body": {"definitions": []}}
    assert nb.build_entry(art, nb.Renderer({})).variants == set()
    two = {"article_id": 10, "lemmas": [{"lemma": "veidekke/vegdekke", "paradigm_info": []}],
           "body": {"definitions": []}}
    assert {"veidekke", "vegdekke"} <= nb.build_entry(two, nb.Renderer({})).variants


def test_exact_headwords_come_before_forms(tmp_path):
    pytest.importorskip("marisa_trie")
    renderer = nb.Renderer({})
    fare = {"article_id": 1, "lemmas": [{"lemma": "fare", "paradigm_info": [
        paradigm(["VERB"], [("fare", ["Inf"]), ("for", ["Past"])])]}], "body": {"definitions": []}}
    prep = {"article_id": 2, "lemmas": [{"lemma": "for", "paradigm_info": []}], "body": {"definitions": []}}
    out = tmp_path / "d.zip"
    nb.write_kobo_dictionary([nb.build_entry(a, renderer) for a in (fare, prep)], out)
    with zipfile.ZipFile(out) as zf:
        doc = gzip.decompress(zf.read("fo.html")).decode()
    assert re.findall(r'<a name="([^"]+)" />', doc) == ["for", "fare"]
