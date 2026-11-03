import io
import zipfile
from pathlib import Path

import pytest

from kobosync import epubfix, stats, web
from kobosync.app import create_app
from kobosync.config import Config

from test_improvements import STORY, build_epub, spine_of

TOKEN = "testtoken"


def kobo_spans(html: str) -> str:
    """Mimic kepubify: wrap each paragraph's text in a KoboSpan."""
    out, n = [], 0
    for chunk in html.split("<p>"):
        if out:
            n += 1
            chunk = f'<span class="koboSpan" id="kobo.{n}.1">' + chunk.replace("</p>", "</span></p>", 1)
        out.append(chunk)
    return "<p>".join(out)


BOOK_PAGES = [
    ("cover", "<p>Omslag</p>"),
    ("over", "<h1>Over het boek</h1><p>Flaptekst.</p>"),
    ("titel", "<h1>Titelpagina</h1><p>Boek</p>"),
    ("ch1", "<h1>Hoofdstuk 1</h1>" + STORY),
    ("ch2", STORY),
]


def make_server(tmp_path, kepub=True, **kw):
    library = tmp_path / "library"
    library.mkdir(exist_ok=True)
    pages = [(pid, kobo_spans(body)) for pid, body in BOOK_PAGES] if kepub else BOOK_PAGES
    build_epub(library / ("boek.kepub.epub" if kepub else "boek.epub"), pages)
    cfg = Config(library_dir=library, data_dir=tmp_path / "data", auth_token=TOKEN,
                 proxy_store=False, scan_interval=0, kepubify="none", **kw)
    app = create_app(cfg)
    return app, app.test_client(), library


def sync(client, token=None):
    headers = {"X-Kobo-DeviceId": "dev"}
    if token:
        headers["x-kobo-synctoken"] = token
    resp = client.get(f"/kobo/{TOKEN}/v1/library/sync", headers=headers)
    return resp.get_json(), resp.headers["x-kobo-synctoken"]


def put_state(client, uuid, device="dev", **bookmark_and_more):
    body = {}
    if "progress" in bookmark_and_more or "location" in bookmark_and_more:
        body["CurrentBookmark"] = {"ProgressPercent": bookmark_and_more.get("progress")}
        if "location" in bookmark_and_more:
            body["CurrentBookmark"]["Location"] = bookmark_and_more["location"]
    if "status" in bookmark_and_more:
        body["StatusInfo"] = {"Status": bookmark_and_more["status"], "TimesStartedReading": 1}
    if "minutes" in bookmark_and_more:
        body["Statistics"] = {"SpentReadingMinutes": bookmark_and_more["minutes"]}
    resp = client.put(f"/kobo/{TOKEN}/v1/library/{uuid}/state", json={"ReadingStates": [body]},
                      headers={"X-Kobo-DeviceId": device})
    assert resp.status_code == 200


# ------------------------------------------------- 15. open at the story

def test_text_start_from_landmark(tmp_path):
    book = tmp_path / "b.epub"
    build_epub(book, [("titel", "<h1>Titel</h1>"), ("motto", "<p>Kort</p>"), ("ch1", "<p>kort begin</p>")],
               landmark_text="ch1")
    assert epubfix.find_text_start(book) == "OEBPS/ch1.xhtml"


def test_text_start_skips_front_matter(tmp_path):
    book = tmp_path / "b.epub"
    build_epub(book, BOOK_PAGES)
    assert epubfix.find_text_start(book) == "OEBPS/ch1.xhtml"


def test_short_prologue_counts_as_the_start(tmp_path):
    book = tmp_path / "b.epub"
    build_epub(book, [("titel", "<h1>Titelpagina</h1>"), ("opdracht", "<p>Voor Olga</p>"),
                      ("pro", "<h1>Proloog</h1><p>Het regende.</p>"), ("ch1", STORY)])
    assert epubfix.find_text_start(book) == "OEBPS/pro.xhtml"


def test_no_start_when_the_story_comes_first(tmp_path):
    book = tmp_path / "b.epub"
    build_epub(book, [("ch1", STORY), ("ch2", STORY)])
    assert epubfix.find_text_start(book) is None


def test_new_kepub_opens_at_the_story(tmp_path):
    _, client, _ = make_server(tmp_path)
    items, _ = sync(client)
    state = items[0]["NewEntitlement"]["ReadingState"]
    assert state["CurrentBookmark"]["Location"] == {
        "Value": "kobo.1.1", "Type": "KoboSpan", "Source": "OEBPS/ch1.xhtml"}
    assert state["StatusInfo"]["Status"] == "ReadyToRead"


def test_device_position_wins_once_reading(tmp_path):
    _, client, _ = make_server(tmp_path)
    items, token = sync(client)
    uuid = items[0]["NewEntitlement"]["BookEntitlement"]["Id"]
    put_state(client, uuid, progress=12, status="Reading",
              location={"Value": "kobo.9.1", "Type": "KoboSpan", "Source": "OEBPS/ch2.xhtml"})
    state = client.get(f"/kobo/{TOKEN}/v1/library/{uuid}/state").get_json()[0]
    assert state["CurrentBookmark"]["Location"]["Value"] == "kobo.9.1"


def test_plain_epub_without_kepubify_gets_no_position(tmp_path):
    _, client, _ = make_server(tmp_path, kepub=False)
    items, _ = sync(client)
    assert "Location" not in items[0]["NewEntitlement"]["ReadingState"]["CurrentBookmark"]


def test_unopened_books_get_the_position_after_upgrading(tmp_path):
    app, client, library = make_server(tmp_path, open_at_text=False)
    items, token = sync(client)
    assert "Location" not in items[0]["NewEntitlement"]["ReadingState"]["CurrentBookmark"]
    cfg = app.extensions["kobosync"].cfg
    cfg.open_at_text = True
    client2 = create_app(cfg).test_client()
    items, token = sync(client2, token)
    kinds = [list(i)[0] for i in items]
    state = items[0][kinds[0]]["ReadingState"]
    assert state["CurrentBookmark"]["Location"]["Source"] == "OEBPS/ch1.xhtml"
    assert sync(client2, token)[0] == []


# ---------------------------------------------------------- 3. hyphenation

def test_add_hyphenation():
    doc = '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>x</title></head><body><p>a</p></body></html>'
    out, done = epubfix.add_hyphenation(doc, "nl")
    assert done and "hyphens: auto" in out and 'xml:lang="nl" lang="nl"' in out
    assert out.index("kobosync: woordafbreking") < out.index("</head>")
    again, done2 = epubfix.add_hyphenation(out, "nl")
    assert again == out and not done2
    kept, _ = epubfix.add_hyphenation(doc.replace("<html ", '<html lang="en" '), "nl")
    assert 'lang="nl"' not in kept


def test_hyphenation_in_processed_copy(tmp_path):
    src, dest = tmp_path / "in.epub", tmp_path / "out.epub"
    build_epub(src, [("ch1", STORY), ("ch2", STORY)])
    report = epubfix.process(src, dest, fix_styles=False, move_front_matter=False, hyphenate=True)
    assert report.hyphenated == 2
    from xml.etree import ElementTree as ET
    with zipfile.ZipFile(dest) as zf:
        root = ET.fromstring(zf.read("OEBPS/ch1.xhtml"))
        assert root.get("lang") == "nl"
        assert "hyphens" in zf.read("OEBPS/ch1.xhtml").decode()


# -------------------------------------------------------------- 6. upload

def epub_bytes(tmp_path, name="up.epub", **kw) -> bytes:
    path = tmp_path / name
    build_epub(path, [("ch1", STORY + name)], **kw)
    return path.read_bytes()


def upload(client, files, password="geheim", **form):
    data = {"wachtwoord": password, **form,
            "boeken": [(io.BytesIO(content), name) for name, content in files]}
    return client.post(f"/kobo/{TOKEN}/upload", data=data, content_type="multipart/form-data")


@pytest.fixture
def up(tmp_path, monkeypatch):
    monkeypatch.setattr(web.time, "sleep", lambda s: None)
    library = tmp_path / "library"
    (library / "Romans").mkdir(parents=True)
    cfg = Config(library_dir=library, data_dir=tmp_path / "data", auth_token=TOKEN, proxy_store=False,
                 scan_interval=0, kepubify="none", upload_password="geheim", upload_max_mb=1)
    app = create_app(cfg)
    return app, app.test_client(), library, tmp_path


def test_upload_is_off_without_password(tmp_path):
    cfg = Config(library_dir=tmp_path / "lib", data_dir=tmp_path / "data", auth_token=TOKEN,
                 proxy_store=False, scan_interval=0, kepubify="none")
    client = create_app(cfg).test_client()
    assert "Uploaden staat uit" in client.get(f"/kobo/{TOKEN}/upload").get_data(as_text=True)
    upload(client, [("a.epub", epub_bytes(tmp_path))])
    assert list((tmp_path / "lib").iterdir()) == []


def test_upload_needs_the_right_password(up):
    app, client, library, tmp = up
    resp = upload(client, [("a.epub", epub_bytes(tmp))], password="fout")
    assert resp.status_code == 403
    assert not (library / "a.epub").exists()


def test_upload_into_a_new_collection(up):
    app, client, library, tmp = up
    resp = upload(client, [("a.epub", epub_bytes(tmp, "a.epub")), ("b.kepub.epub", epub_bytes(tmp, "b.epub"))],
                  nieuwe_map="Thrillers/Noors")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200 and text.count("Toegevoegd") == 2
    assert (library / "Thrillers" / "Noors" / "a.epub").exists()
    assert (library / "Thrillers" / "Noors" / "b.kepub.epub").exists()
    db = app.extensions["kobosync"].db
    assert {b["path"] for b in db.all_books()} == {"Thrillers/Noors/a.epub", "Thrillers/Noors/b.kepub.epub"}
    assert [t["name"] for t in db.all_tags()] == ["Thrillers / Noors"]
    assert not [p for p in library.rglob(".upload-*")]


def test_upload_into_an_existing_folder_and_name_clash(up):
    app, client, library, tmp = up
    (library / "Romans" / "a.epub").write_bytes(epub_bytes(tmp, "ander.epub"))
    upload(client, [("a.epub", epub_bytes(tmp, "a.epub"))], map="Romans")
    assert (library / "Romans" / "a (2).epub").exists()


def test_upload_rejects_duplicates_and_non_epubs(up):
    app, client, library, tmp = up
    content = epub_bytes(tmp, "a.epub")
    upload(client, [("a.epub", content)])
    text = upload(client, [("kopie.epub", content), ("notitie.txt", b"hallo"),
                           ("nep.epub", b"geen zip")], nieuwe_map="Nieuw").get_data(as_text=True)
    assert "Staat al in de bibliotheek als a.epub" in text
    assert "Alleen .epub" in text and "geen EPUB-bestand" in text
    assert not (library / "Nieuw").exists()  # nothing saved: no empty folder left


def test_upload_rejects_drm(up):
    app, client, library, tmp = up
    drm = epub_bytes(tmp, "drm.epub", encryption=(
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
        '<enc:EncryptedData><enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>'
        '</enc:EncryptedData></encryption>'))
    assert "DRM" in upload(client, [("drm.epub", drm)]).get_data(as_text=True)
    assert not (library / "drm.epub").exists()


@pytest.mark.parametrize("folder", ["../buiten", ".verborgen", "a/../../b", "/etc/x/.."])
def test_upload_rejects_unsafe_folders(up, folder):
    app, client, library, tmp = up
    resp = upload(client, [("a.epub", epub_bytes(tmp))], nieuwe_map=folder)
    assert resp.status_code == 400
    assert not list(tmp.glob("buiten")) and not list(library.rglob("a.epub"))


def test_upload_strips_paths_from_file_names(up):
    app, client, library, tmp = up
    upload(client, [("../../evil.epub", epub_bytes(tmp))])
    assert (library / "evil.epub").exists() and not (tmp / "evil.epub").exists()


def test_upload_size_limit(up):
    app, client, library, tmp = up
    resp = upload(client, [("groot.epub", b"x" * (2 * 1024 * 1024))])
    assert resp.status_code == 413


def test_clean_folder():
    assert web.clean_folder(" Thrillers / Noors/ ") == "Thrillers/Noors"
    assert web.clean_folder("Romans\\Nederlands") == "Romans/Nederlands"
    assert web.clean_folder("") == ""
    assert web.clean_folder("a/../b") is None


# ---------------------------------------------------------- 7. statistics

@pytest.mark.parametrize("prev, new, secs, expected", [
    (None, 25, None, 25),     # first report for the book
    (30, 45, 3600, 15),       # read 15 more minutes
    (45, 40, 3600, 0),        # a lower total adds nothing
    (10, 300, 600, 15),       # capped by the time that passed
    (None, 5000, None, 600),  # absurd value capped
    (10, None, 60, 0),        # no statistics in the report
])
def test_minutes_added(prev, new, secs, expected):
    assert stats.minutes_added(prev, new, secs) == expected


def test_statistics_page(tmp_path):
    app, client, _ = make_server(tmp_path, reading_goal=12)
    items, _ = sync(client)
    uuid = items[0]["NewEntitlement"]["BookEntitlement"]["Id"]
    put_state(client, uuid, progress=10, status="Reading", minutes=20)
    # An hour later, on the other device.
    import sqlite3
    with sqlite3.connect(app.extensions["kobosync"].cfg.db_path) as con:
        con.execute("UPDATE reading_events SET ts = ts - 3600")
    put_state(client, uuid, device="other", progress=100, status="Finished", minutes=35)
    events = app.extensions["kobosync"].db.reading_events()
    assert [e["minutes_added"] for e in events] == [20, 15]

    s = stats.year_stats(app.extensions["kobosync"].db, None, 12, "Europe/Amsterdam")
    assert s.minutes == 35 and len(s.finished) == 1
    assert s.finished[0]["days"] == 1 and s.finished[0]["minutes"] == 35
    assert sum(m.finished for m in s.months) == 1

    page = client.get(f"/kobo/{TOKEN}/statistieken").get_data(as_text=True)
    assert "Boek" in page and "van 12" in page and "35 min" in page


def test_books_finished_before_statistics_still_count(tmp_path):
    app, client, _ = make_server(tmp_path)
    app.extensions["kobosync"].library.scan()
    db = app.extensions["kobosync"].db
    book = db.all_books()[0]
    import time
    db.update_state(book["id"], status="Finished", status_last_modified=time.time())
    s = stats.year_stats(db, None, 0, "Europe/Amsterdam")
    assert [b["title"] for b in s.finished] == ["Boek"] and s.finished[0]["started"] is None


def test_pages_render(tmp_path):
    _, client, _ = make_server(tmp_path)
    for page in ("status", "statistieken", "upload"):
        resp = client.get(f"/kobo/{TOKEN}/{page}")
        assert resp.status_code == 200 and "<nav>" in resp.get_data(as_text=True)
    assert client.get("/kobo/fout/statistieken").status_code == 401
