import zipfile
from pathlib import Path

import pytest

from kobosync import epubfix
from kobosync.app import create_app
from kobosync.config import Config
from kobosync.epubmeta import read_metadata, split_authors

TOKEN = "testtoken"


def build_epub(path: Path, pages, creators=None, css="", opf_extra="", encryption=None, landmark_text=None):
    """pages: list of (id, body html)."""
    creators = creators or ['<dc:creator>A. Schrijver</dc:creator>']
    manifest = "\n".join(f'<item id="{pid}" href="{pid}.xhtml" media-type="application/xhtml+xml"/>' for pid, _ in pages)
    spine = "\n".join(f'<itemref idref="{pid}"/>' for pid, _ in pages)
    guide = f'<guide><reference type="text" href="{landmark_text}.xhtml"/></guide>' if landmark_text else ""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>Boek</dc:title>
    {''.join(creators)}
    <dc:language>nl</dc:language>
    {opf_extra}
  </metadata>
  <manifest>
    <item id="css" href="style.css" media-type="text/css"/>
    {manifest}
  </manifest>
  <spine>
    {spine}
  </spine>
  {guide}
</package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        if encryption:
            zf.writestr("META-INF/encryption.xml", encryption)
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/style.css", css)
        for pid, body in pages:
            zf.writestr(f"OEBPS/{pid}.xhtml",
                        f'<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                        f'<head><title>{pid}</title></head><body>{body}</body></html>')


def spine_of(path: Path):
    import re
    with zipfile.ZipFile(path) as zf:
        return re.findall(r'idref="([^"]+)"', zf.read("OEBPS/content.opf").decode())


STORY = "<h1>Hoofdstuk</h1>" + "<p>Het verhaal begint hier en gaat lang door.</p>" * 120


# ------------------------------------------------------------- 1. authors

@pytest.mark.parametrize("raw, expected", [
    ("Thomas Heerma van Voss en Maartje Wortel", ["Thomas Heerma van Voss", "Maartje Wortel"]),
    ("Jørn Lier Horst og Thomas Enger", ["Jørn Lier Horst", "Thomas Enger"]),
    ("Jørn Lier Horst & Thomas Enger", ["Jørn Lier Horst", "Thomas Enger"]),
    ("Anne Frank, Otto Frank and Miep Gies", ["Anne Frank", "Otto Frank", "Miep Gies"]),
    ("Anne Frank; Otto Frank", ["Anne Frank", "Otto Frank"]),
    ("Wortel, Maartje", ["Wortel, Maartje"]),           # sort form, not two people
    ("Jan en Annie de Graaf", ["Jan en Annie de Graaf"]),  # "Jan" alone is not a full name
    ("Hella S. Haasse", ["Hella S. Haasse"]),
])
def test_split_authors(raw, expected):
    assert split_authors([raw]) == expected


def test_split_authors_deduplicates():
    assert split_authors(["Maartje Wortel", "Thomas Heerma van Voss en Maartje Wortel"]) == [
        "Maartje Wortel", "Thomas Heerma van Voss"]


def test_illustrators_and_translators_are_not_authors(tmp_path):
    book = tmp_path / "b.epub"
    build_epub(book, [("p1", STORY)], creators=[
        '<dc:creator opf:role="aut">Auteur Een</dc:creator>',
        '<dc:creator opf:role="ill">Illustrator Twee</dc:creator>',
        '<dc:creator id="c3">Vertaler Drie</dc:creator>',
    ], opf_extra='<meta refines="#c3" property="role" scheme="marc:relators">trl</meta>')
    assert read_metadata(book).authors == ["Auteur Een"]


def test_only_non_authors_are_kept_as_fallback(tmp_path):
    book = tmp_path / "b.epub"
    build_epub(book, [("p1", STORY)], creators=['<dc:creator opf:role="edt">Redacteur Een</dc:creator>'])
    assert read_metadata(book).authors == ["Redacteur Een"]


# ------------------------------------------------------------------ 3. CSS

def test_fix_css_converts_fixed_sizes():
    css = ("body { font-size: 12pt; margin: 0px 20px; line-height: 24px !important }\n"
           "p{text-indent:16px;padding-left:-8px}\n"
           "h1 { font-size: 1.5em; margin-top: 2em }")
    out, n = epubfix.fix_css(css)
    assert "font-size: 1em" in out
    assert "margin: 0 1.25em" in out
    assert "line-height: 1.5em" in out and "important" not in out
    assert "text-indent:1em" in out and "padding-left:-0.5em" in out
    assert "h1 { font-size: 1.5em; margin-top: 2em }" in out
    assert n == 5


def test_fix_css_leaves_other_properties_alone():
    css = ("img { width: 300px; height: 200px; border: 1px solid black }\n"
           "@media (max-width: 600px) { a:hover { color: red } }\n"
           ".x { font-family: Georgia !important; font-size: small }")
    out, n = epubfix.fix_css(css)
    assert out == css and n == 0


def test_fix_markup_handles_style_blocks_and_attributes():
    html = ('<html><head><style>.t{font-size:36px}</style></head>'
            '<body><p style="font-size: 14px; color: red">x</p><img style="width: 50px"/></body></html>')
    out, n = epubfix.fix_markup(html)
    assert ".t{font-size:2.25em}" in out
    assert 'style="font-size: 0.875em; color: red"' in out
    assert 'style="width: 50px"' in out
    assert n == 2


# --------------------------------------------------------- 6. front matter

def test_rights_and_colophon_pages_move_to_the_end(tmp_path):
    src, dest = tmp_path / "in.epub", tmp_path / "out.epub"
    build_epub(src, [
        ("cover", "<p>Omslag</p>"),
        ("bokbasen_rights", "<p>Denne boken tilhører: Lezer</p>"),
        ("titel", "<h1>Titelpagina</h1>"),
        ("p004", "<h1>Colofon</h1><p>Dit e-book is gebaseerd op de eerste druk.</p>"),
        ("over", "<h1>Over het boek</h1><p>Flaptekst.</p>"),
        ("ch1", STORY),
        ("ch2", STORY),
    ], css="p { font-size: 1em }")
    report = epubfix.process(src, dest)
    assert len(report.moved) == 2
    assert spine_of(dest) == ["cover", "titel", "over", "ch1", "ch2", "bokbasen_rights", "p004"]
    assert spine_of(src)[1] == "bokbasen_rights"  # original untouched


def test_front_matter_only_before_the_text_landmark(tmp_path):
    src, dest = tmp_path / "in.epub", tmp_path / "out.epub"
    build_epub(src, [
        ("titel", "<h1>Titel</h1>"),
        ("ch1", STORY),
        ("copyright", "<p>Copyright 2024</p>"),
        ("ch2", STORY),
    ], landmark_text="ch1")
    report = epubfix.process(src, dest)
    assert not report.changed and not dest.exists()


def test_long_pages_are_never_moved(tmp_path):
    src, dest = tmp_path / "in.epub", tmp_path / "out.epub"
    build_epub(src, [("colofon", "<h1>Colofon</h1>" + STORY), ("ch1", STORY), ("ch2", STORY)])
    assert not epubfix.process(src, dest).changed


def test_fixed_layout_and_drm_are_skipped(tmp_path):
    pages = [("colofon", "<h1>Colofon</h1>"), ("ch1", STORY), ("ch2", STORY)]
    fixed = tmp_path / "fixed.epub"
    build_epub(fixed, pages, css="p{font-size:12px}",
               opf_extra='<meta property="rendition:layout">pre-paginated</meta>')
    assert epubfix.process(fixed, tmp_path / "o1.epub").skipped_reason == "vaste opmaak"

    drm = tmp_path / "drm.epub"
    build_epub(drm, pages, css="p{font-size:12px}", encryption=(
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        '<enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>'
        '</enc:EncryptedData></encryption>'))
    assert epubfix.process(drm, tmp_path / "o2.epub").skipped_reason == "DRM"

    fonts = tmp_path / "fonts.epub"
    build_epub(fonts, pages, css="p{font-size:12px}", encryption=(
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        '<enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>'
        '</enc:EncryptedData></encryption>'))
    assert epubfix.process(fonts, tmp_path / "o3.epub").changed


def test_processed_copy_is_a_valid_epub(tmp_path):
    src, dest = tmp_path / "in.epub", tmp_path / "out.epub"
    build_epub(src, [("colofon", "<h1>Colofon</h1>"), ("ch1", STORY), ("ch2", STORY)], css="p{margin:10px}")
    epubfix.process(src, dest)
    with zipfile.ZipFile(dest) as zf:
        assert zf.namelist()[0] == "mimetype"
        assert zf.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert zf.testzip() is None
        assert zf.read("OEBPS/style.css") == b"p{margin:0.625em}"


# ---------------------------------------------------------- 2. collections

@pytest.fixture
def server(tmp_path):
    library = tmp_path / "library"
    (library / "Thrillers" / "Noors").mkdir(parents=True)
    (library / "Romans").mkdir()
    build_epub(library / "Thrillers" / "Noors" / "arr.epub", [("ch1", STORY)])
    build_epub(library / "Romans" / "tetris.epub", [("ch1", STORY)])
    build_epub(library / "los.epub", [("ch1", STORY)])
    cfg = Config(library_dir=library, data_dir=tmp_path / "data", auth_token=TOKEN,
                 proxy_store=False, scan_interval=0, kepubify="none")
    app = create_app(cfg)
    return app, app.test_client(), library


def sync(client, token=None):
    headers = {"X-Kobo-DeviceId": "dev"}
    if token:
        headers["x-kobo-synctoken"] = token
    resp = client.get(f"/kobo/{TOKEN}/v1/library/sync", headers=headers)
    return resp.get_json(), resp.headers["x-kobo-synctoken"]


def tags_in(items):
    out = {}
    for item in items:
        for kind in ("NewTag", "ChangedTag", "DeletedTag"):
            if kind in item:
                tag = item[kind]["Tag"]
                out[tag.get("Name", tag["Id"])] = (kind, tag)
    return out


def test_folders_become_collections(server):
    app, client, _ = server
    items, token = sync(client)
    tags = tags_in(items)
    assert set(tags) == {"Thrillers / Noors", "Romans"}
    kind, tag = tags["Romans"]
    assert kind == "NewTag" and tag["Type"] == "UserTag"
    book_ids = {i["NewEntitlement"]["BookMetadata"]["Title"] and i["NewEntitlement"]["BookEntitlement"]["Id"]
                for i in items if "NewEntitlement" in i}
    assert len(book_ids) == 3
    assert tag["Items"][0]["Type"] == "ProductRevisionTagItem"
    assert tag["Items"][0]["RevisionId"] in book_ids
    # Tags come after the books they refer to.
    assert all("NewEntitlement" in i for i in items[:3])
    assert sync(client, token)[0] == []


def test_moving_and_emptying_folders(server):
    app, client, library = server
    items, token = sync(client)
    romans_id = tags_in(items)["Romans"][1]["Id"]
    (library / "Romans" / "tetris.epub").rename(library / "Thrillers" / "Noors" / "tetris.epub")
    items, token = sync(client, token)
    tags = tags_in(items)
    assert tags[romans_id][0] == "DeletedTag"
    assert tags["Thrillers / Noors"][0] == "ChangedTag"
    assert len(tags["Thrillers / Noors"][1]["Items"]) == 2
    assert sync(client, token)[0] == []


def test_device_changes_to_folder_collections_are_undone(server):
    app, client, _ = server
    items, token = sync(client)
    tag = tags_in(items)["Romans"][1]
    assert client.delete(f"/kobo/{TOKEN}/v1/library/tags/{tag['Id']}").status_code == 200
    items, token = sync(client, token)
    assert tags_in(items)["Romans"][0] == "ChangedTag"
    assert client.post(f"/kobo/{TOKEN}/v1/library/tags/{tag['Id']}/items/delete",
                       json={"Items": tag["Items"]}).status_code == 201
    items, token = sync(client, token)
    assert tags_in(items)["Romans"][1]["Items"] == tag["Items"]


def test_unknown_collections_are_left_to_kobo(server):
    _, client, _ = server
    resp = client.delete(f"/kobo/{TOKEN}/v1/library/tags/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 200 and resp.get_json() == {}  # stub, as the store is off here


def test_book_removed_on_device_leaves_its_collection(server):
    app, client, _ = server
    items, token = sync(client)
    romans = tags_in(items)["Romans"][1]
    client.delete(f"/kobo/{TOKEN}/v1/library/{romans['Items'][0]['RevisionId']}")
    items, token = sync(client, token)
    assert tags_in(items)[romans["Id"]][0] == "DeletedTag"


def test_collections_can_be_switched_off(tmp_path, server):
    app, client, library = server
    items, token = sync(client)
    cfg = Config(library_dir=library, data_dir=app.extensions["kobosync"].cfg.data_dir, auth_token=TOKEN,
                 proxy_store=False, scan_interval=0, kepubify="none", folder_collections=False)
    client2 = create_app(cfg).test_client()
    items, _ = sync(client2, token)
    assert {k for k, _ in tags_in(items).values()} == {"DeletedTag"}


def test_collection_urls_point_here(server):
    _, client, _ = server
    res = client.get(f"/kobo/{TOKEN}/v1/initialization").get_json()["Resources"]
    assert res["tags"] == f"http://localhost/kobo/{TOKEN}/v1/library/tags"
    assert res["delete_tag_items"].startswith(f"http://localhost/kobo/{TOKEN}/v1/library/tags/")
    assert res["book"].startswith("https://storeapi.kobo.com/")


# -------------------------------------------------------- reprocessing

def test_changed_settings_reprocess_books(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    build_epub(library / "b.epub", [("colofon", "<h1>Colofon</h1>"), ("ch1", STORY), ("ch2", STORY)],
               creators=["<dc:creator>Een Auteur en Twee Auteur</dc:creator>"])
    data = tmp_path / "data"

    def app_with(**kw):
        cfg = Config(library_dir=library, data_dir=data, auth_token=TOKEN, proxy_store=False,
                     scan_interval=0, kepubify="none", **kw)
        app = create_app(cfg)
        app.extensions["kobosync"].library.scan()
        return app

    app = app_with(split_authors=False, move_front_matter=False, fix_styles=False)
    book = app.extensions["kobosync"].db.all_books()[0]
    assert book["authors"] == ["Een Auteur en Twee Auteur"] and book["processed_path"] is None

    app = app_with()
    book = app.extensions["kobosync"].db.all_books()[0]
    assert book["authors"] == ["Een Auteur", "Twee Auteur"]
    path, _ = app.extensions["kobosync"].library.file_for_book(book)
    assert path.parent.name == "processed"
    assert spine_of(path) == ["ch1", "ch2", "colofon"]


# ------------------------------------------------- issue 12 and moved books

def test_collection_items_use_the_type_kobo_expects(server):
    _, client, _ = server
    items, _ = sync(client)
    for kind, tag in tags_in(items).values():
        assert {i["Type"] for i in tag["Items"]} == {"ProductRevisionTagItem"}


def test_old_collections_are_resent_after_upgrade(server):
    app, client, library = server
    items, token = sync(client)
    assert sync(client, token)[0] == []
    db = app.extensions["kobosync"].db
    db.set_meta("tag_format", "1")  # as written by the previous version
    client2 = create_app(app.extensions["kobosync"].cfg).test_client()
    items, token = sync(client2, token)
    assert {k for k, _ in tags_in(items).values()} == {"ChangedTag"}
    assert sync(client2, token)[0] == []


def set_progress(client, uuid, pct):
    client.put(f"/kobo/{TOKEN}/v1/library/{uuid}/state", json={"ReadingStates": [{
        "CurrentBookmark": {"ProgressPercent": pct}}]})


def test_moving_a_book_keeps_it_and_its_progress(server):
    app, client, library = server
    items, token = sync(client)
    books = {i["NewEntitlement"]["BookMetadata"]["Title"]: i["NewEntitlement"]["BookEntitlement"]["Id"]
             for i in items if "NewEntitlement" in i}
    db = app.extensions["kobosync"].db
    los = db.book_by_path("los.epub")
    set_progress(client, los["uuid"], 55)
    _, token = sync(client, token)

    (library / "los.epub").rename(library / "Romans" / "los.epub")
    items, token = sync(client, token)
    assert not any("NewEntitlement" in i for i in items)
    changed = [i["ChangedEntitlement"]["BookEntitlement"] for i in items if "ChangedEntitlement" in i]
    assert [(e["Id"], e["IsRemoved"]) for e in changed] == [(los["uuid"], False)]
    romans = tags_in(items)["Romans"][1]
    assert los["uuid"] in {i["RevisionId"] for i in romans["Items"]}
    state = client.get(f"/kobo/{TOKEN}/v1/library/{los['uuid']}/state").get_json()[0]
    assert state["CurrentBookmark"]["ProgressPercent"] == 55
    assert len(db.all_books()) == 3


def test_renaming_a_folder_keeps_the_books(server):
    app, client, library = server
    items, token = sync(client)
    db = app.extensions["kobosync"].db
    before = {b["uuid"] for b in db.all_books()}
    (library / "Thrillers").rename(library / "Spanning")
    items, token = sync(client, token)
    assert {b["uuid"] for b in db.all_books()} == before
    assert not any(b["archived"] for b in db.all_books())
    kinds = {name: kind for name, (kind, _) in tags_in(items).items()}
    assert kinds.get("Spanning / Noors") == "NewTag"
    assert "DeletedTag" in kinds.values()


def test_identical_copies_stay_separate_books(server):
    app, client, library = server
    sync(client)
    import shutil
    shutil.copy(library / "los.epub", library / "Romans" / "kopie.epub")
    app.extensions["kobosync"].library.scan()
    assert len(app.extensions["kobosync"].db.all_books()) == 4


def test_books_without_hash_are_matched_by_size(server):
    app, client, library = server
    sync(client)
    db = app.extensions["kobosync"].db
    los = db.book_by_path("los.epub")
    db.update_book(los["id"], touch=False, content_hash=None)  # imported by an older version
    (library / "los.epub").rename(library / "Romans" / "los.epub")
    app.extensions["kobosync"].library.scan()
    assert db.book_by_path("Romans/los.epub")["uuid"] == los["uuid"]


def test_book_removed_on_device_stays_removed_after_a_move(server):
    app, client, library = server
    items, token = sync(client)
    db = app.extensions["kobosync"].db
    los = db.book_by_path("los.epub")
    client.delete(f"/kobo/{TOKEN}/v1/library/{los['uuid']}")
    (library / "los.epub").rename(library / "Romans" / "los.epub")
    app.extensions["kobosync"].library.scan()
    moved = db.book_by_path("Romans/los.epub")
    assert moved["uuid"] == los["uuid"] and moved["archived"] and moved["archived_reason"] == "device"


def test_capitalised_items_route_is_handled(server):
    _, client, _ = server
    items, _ = sync(client)
    tag = tags_in(items)["Romans"][1]
    assert client.post(f"/kobo/{TOKEN}/v1/library/tags/{tag['Id']}/Items", json={"Items": []}).status_code == 201


def test_deleting_an_already_deleted_collection_is_not_echoed(server):
    app, client, library = server
    items, token = sync(client)
    romans = tags_in(items)["Romans"][1]
    (library / "Romans" / "tetris.epub").unlink()
    items, token = sync(client, token)
    assert tags_in(items)[romans["Id"]][0] == "DeletedTag"
    assert client.delete(f"/kobo/{TOKEN}/v1/library/tags/{romans['Id']}").status_code == 200
    assert sync(client, token)[0] == []
