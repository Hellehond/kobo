import json
import zipfile
from pathlib import Path

import pytest

from kobosync.app import create_app
from kobosync.config import Config
from kobosync.synctoken import SyncToken

TOKEN = "testtoken"


def make_epub(path: Path, title="Testboek", author="A. Schrijver", series=None):
    series_meta = ""
    if series:
        series_meta = (f'<meta name="calibre:series" content="{series}"/>'
                       '<meta name="calibre:series_index" content="2"/>')
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>nl</dc:language>
    <dc:publisher>Uitgeverij X</dc:publisher>
    <dc:date>2021-05-04</dc:date>
    <dc:identifier opf:scheme="ISBN">9789000000001</dc:identifier>
    <dc:description>&lt;p&gt;Een &lt;b&gt;beschrijving&lt;/b&gt;.&lt;/p&gt;</dc:description>
    <meta name="cover" content="cover-img"/>
    {series_meta}
  </metadata>
  <manifest>
    <item id="cover-img" href="cover.jpg" media-type="image/jpeg"/>
    <item id="ch1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="ch1"/></spine>
</package>"""
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr("META-INF/container.xml",
                    '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        zf.writestr("OEBPS/content.opf", opf)
        zf.writestr("OEBPS/cover.jpg", b"\xff\xd8\xff\xe0JFIF-fake")
        zf.writestr("OEBPS/ch1.xhtml", "<html><body><p>Hallo</p></body></html>")


@pytest.fixture
def env(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    make_epub(library / "testboek.epub", series="Reeks")
    cfg = Config(library_dir=library, data_dir=tmp_path / "data", auth_token=TOKEN,
                 proxy_store=False, scan_interval=0, kepubify="none")
    app = create_app(cfg)
    app.testing = True
    return app, app.test_client(), library


def sync(client, token=None, device="dev-A"):
    headers = {"X-Kobo-DeviceId": device}
    if token:
        headers["x-kobo-synctoken"] = token
    resp = client.get(f"/kobo/{TOKEN}/v1/library/sync", headers=headers)
    assert resp.status_code == 200
    return resp.get_json(), resp.headers["x-kobo-synctoken"], resp.headers


def test_wrong_token_is_rejected(env):
    _, client, _ = env
    assert client.get("/kobo/verkeerd/v1/library/sync").status_code == 401


def test_first_sync_delivers_new_entitlement(env):
    app, client, _ = env
    items, token, headers = sync(client)
    assert len(items) == 1
    ent = items[0]["NewEntitlement"]
    md = ent["BookMetadata"]
    assert md["Title"] == "Testboek"
    assert md["Contributors"] == ["A. Schrijver"]
    assert md["Language"] == "nl"
    assert md["Isbn"] == "9789000000001"
    assert md["Series"]["Name"] == "Reeks" and md["Series"]["Number"] == 2
    assert md["Description"] == "Een beschrijving ."
    assert md["DownloadUrls"][0]["Format"] == "EPUB3"
    assert ent["BookEntitlement"]["IsRemoved"] is False
    assert ent["ReadingState"]["StatusInfo"]["Status"] == "ReadyToRead"
    assert "x-kobo-sync" not in headers

    # The download URL works and serves the file.
    url = md["DownloadUrls"][0]["Url"]
    path = url.split("/kobo/", 1)[1]
    resp = client.get(f"/kobo/{path}")
    assert resp.status_code == 200
    assert resp.data[:2] == b"PK"

    # Cover image through the template used by the device.
    uuid = md["CoverImageId"]
    resp = client.get(f"/kobo/{TOKEN}/{uuid}/300/400/false/image.jpg")
    assert resp.status_code == 200
    resp = client.get(f"/kobo/{TOKEN}/{uuid}/300/400/80/isGreyscale/image.jpg")
    assert resp.status_code == 200

    # A second sync with the returned token is empty.
    items2, token2, _ = sync(client, token)
    assert items2 == []


def test_reading_state_round_trip_between_two_devices(env):
    app, client, _ = env
    items, token_a, _ = sync(client, device="dev-A")
    uuid = items[0]["NewEntitlement"]["BookMetadata"]["EntitlementId"]
    _, token_b, _ = sync(client, device="dev-B")

    put = client.put(f"/kobo/{TOKEN}/v1/library/{uuid}/state", json={"ReadingStates": [{
        "EntitlementId": uuid,
        "LastModified": "2024-01-02T03:04:05Z",
        "StatusInfo": {"Status": "Reading", "TimesStartedReading": 1,
                       "LastTimeStartedReading": "2024-01-02T03:00:00.1234567Z"},
        "Statistics": {"SpentReadingMinutes": 12, "RemainingTimeMinutes": 100},
        "CurrentBookmark": {"ProgressPercent": 42.5, "ContentSourceProgressPercent": 10,
                            "Location": {"Value": "kobo.1.3", "Type": "KoboSpan", "Source": "ch1.xhtml"}},
    }]}, headers={"X-Kobo-DeviceId": "dev-A"})
    assert put.status_code == 200
    body = put.get_json()
    assert body["RequestResult"] == "Success"
    assert body["UpdateResults"][0]["CurrentBookmarkResult"] == {"Result": "Success"}
    assert body["UpdateResults"][0]["StatusInfoResult"] == {"Result": "Success"}

    # GET returns what we stored.
    got = client.get(f"/kobo/{TOKEN}/v1/library/{uuid}/state").get_json()
    assert got[0]["CurrentBookmark"]["ProgressPercent"] == 42.5
    assert got[0]["CurrentBookmark"]["Location"]["Value"] == "kobo.1.3"
    assert got[0]["StatusInfo"]["Status"] == "Reading"
    assert got[0]["Statistics"]["SpentReadingMinutes"] == 12

    # Device B's next sync carries the changed reading state.
    items_b, token_b2, _ = sync(client, token_b, device="dev-B")
    assert len(items_b) == 1
    state = items_b[0]["ChangedReadingState"]["ReadingState"]
    assert state["EntitlementId"] == uuid
    assert state["CurrentBookmark"]["ProgressPercent"] == 42.5
    assert state["StatusInfo"]["TimesStartedReading"] == 1

    # And nothing more after that.
    assert sync(client, token_b2, device="dev-B")[0] == []

    # Devices were recorded.
    ids = {d["device_id"] for d in app.extensions["kobosync"].db.devices()}
    assert ids == {"dev-A", "dev-B"}


def test_delete_from_device_archives_for_both(env):
    app, client, _ = env
    items, token_a, _ = sync(client, device="dev-A")
    uuid = items[0]["NewEntitlement"]["BookMetadata"]["EntitlementId"]
    _, token_b, _ = sync(client, device="dev-B")

    assert client.delete(f"/kobo/{TOKEN}/v1/library/{uuid}").status_code == 204
    items_b, _, _ = sync(client, token_b, device="dev-B")
    assert items_b[0]["ChangedEntitlement"]["BookEntitlement"]["IsRemoved"] is True

    # restore -> offered again
    book = app.extensions["kobosync"].db.book_by_uuid(uuid)
    app.extensions["kobosync"].db.restore_book(book["id"])
    items_a, _, _ = sync(client, token_a, device="dev-A")
    assert items_a[0]["ChangedEntitlement"]["BookEntitlement"]["IsRemoved"] is False


def test_file_removed_and_readded(env):
    app, client, library = env
    items, token, _ = sync(client)
    (library / "testboek.epub").unlink()
    items, token, _ = sync(client, token)
    assert items[0]["ChangedEntitlement"]["BookEntitlement"]["IsRemoved"] is True
    make_epub(library / "testboek.epub")
    items, token, _ = sync(client, token)
    assert items[0]["ChangedEntitlement"]["BookEntitlement"]["IsRemoved"] is False
    assert sync(client, token)[0] == []


def test_new_book_appears_on_later_sync(env):
    app, client, library = env
    _, token, _ = sync(client)
    make_epub(library / "tweede.kepub.epub", title="Tweede")
    items, token, _ = sync(client, token)
    assert [i["NewEntitlement"]["BookMetadata"]["Title"] for i in items] == ["Tweede"]
    assert items[0]["NewEntitlement"]["BookMetadata"]["DownloadUrls"][0]["Format"] == "KEPUB"


def test_store_token_is_kept(env):
    _, client, _ = env
    # First contact from a device that still carries Kobo's own token.
    items, token, _ = sync(client, "abc.def")
    parsed = SyncToken.from_headers({"x-kobo-synctoken": token})
    assert parsed.raw_kobo_store_token == "abc.def"
    assert parsed.books_last_id >= 1


def test_initialization_points_images_here(env):
    _, client, _ = env
    resp = client.get(f"/kobo/{TOKEN}/v1/initialization")
    assert resp.status_code == 200
    res = resp.get_json()["Resources"]
    assert res["image_url_template"].endswith("/{ImageId}/{Width}/{Height}/false/image.jpg")
    assert f"/kobo/{TOKEN}/" in res["image_url_template"]
    assert resp.headers["x-kobo-apitoken"] == "e30="


def test_unknown_routes_are_stubbed_without_proxy(env):
    _, client, _ = env
    assert client.get(f"/kobo/{TOKEN}/v1/user/profile").get_json() == {}
    assert client.post(f"/kobo/{TOKEN}/v1/auth/device", json={"UserKey": "k"}).get_json()["UserKey"] == "k"
    assert client.get(f"/kobo/{TOKEN}/status").status_code == 200


def test_proxy_mode_redirects_unknown_gets(tmp_path):
    cfg = Config(library_dir=tmp_path / "lib", data_dir=tmp_path / "data", auth_token=TOKEN,
                 proxy_store=True, scan_interval=0, kepubify="none")
    client = create_app(cfg).test_client()
    resp = client.get(f"/kobo/{TOKEN}/v1/products/deals?x=1")
    assert resp.status_code == 307
    assert resp.headers["Location"] == "https://storeapi.kobo.com/v1/products/deals?x=1"
    resp = client.get(f"/kobo/{TOKEN}/v1/library/00000000-0000-0000-0000-00000000abcd/state")
    assert resp.status_code == 307
    assert resp.headers["Location"].endswith("/v1/library/00000000-0000-0000-0000-00000000abcd/state")
    resp = client.get(f"/kobo/{TOKEN}/00000000-0000-0000-0000-00000000abcd/100/200/false/image.jpg")
    assert resp.status_code == 307
    assert resp.headers["Location"].startswith("https://cdn.kobo.com/book-images/")


def test_public_url_is_used_behind_a_proxy(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    make_epub(library / "boek.epub")
    cfg = Config(library_dir=library, data_dir=tmp_path / "data", auth_token=TOKEN, proxy_store=False,
                 scan_interval=0, kepubify="none", public_url="https://kobo.example.org")
    client = create_app(cfg).test_client()
    # The proxy talks plain HTTP to kobosync, as Caddy and cloudflared do.
    items, _, _ = sync(client)
    url = items[0]["NewEntitlement"]["BookMetadata"]["DownloadUrls"][0]["Url"]
    assert url.startswith(f"https://kobo.example.org/kobo/{TOKEN}/download/")
    res = client.get(f"/kobo/{TOKEN}/v1/initialization").get_json()["Resources"]
    assert res["image_url_template"].startswith(f"https://kobo.example.org/kobo/{TOKEN}/")
