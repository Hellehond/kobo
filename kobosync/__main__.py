from __future__ import annotations

import argparse
import sys

from .app import configure_logging, create_app
from .config import Config
from .util import to_kobo_timestamp


def _cfg(args) -> Config:
    cfg = Config.from_env()
    if args.library:
        cfg.library_dir = args.library
    if args.data:
        cfg.data_dir = args.data
    return cfg


def cmd_serve(args) -> int:
    cfg = _cfg(args)
    if args.port:
        cfg.port = args.port
    if args.host:
        cfg.host = args.host
    if args.no_proxy:
        cfg.proxy_store = False
    app = create_app(cfg)
    library = app.extensions["kobosync"].library
    library.scan()
    print("kobosync gestart")
    print(f"  bibliotheek : {cfg.library_dir}")
    print(f"  data        : {cfg.data_dir}")
    print(f"  kepubify    : {cfg.kepubify or 'niet gevonden (EPUB wordt ongewijzigd aangeboden)'}")
    print(f"  Kobo store  : {'wordt doorgestuurd' if cfg.proxy_store else 'UIT (alleen eigen boeken)'}")
    shown = cfg.public_url or f"http://<ip-van-deze-machine>:{cfg.port}"
    print(f"  api_endpoint voor de e-readers: {shown}/kobo/{cfg.auth_token}")
    print(f"  statuspagina: {shown}/kobo/{cfg.auth_token}/status")
    try:
        from waitress import serve
    except ImportError:
        app.run(host=cfg.host, port=cfg.port, threaded=True)
    else:
        serve(app, host=cfg.host, port=cfg.port, threads=8)
    return 0


def cmd_scan(args) -> int:
    app = create_app(_cfg(args))
    stats = app.extensions["kobosync"].library.scan()
    print("Scan klaar: " + ", ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


def cmd_list(args) -> int:
    app = create_app(_cfg(args))
    rows = app.extensions["kobosync"].db.overview()
    if not rows:
        print("Geen boeken in de bibliotheek.")
        return 0
    print(f"{'id':>4}  {'status':<12} {'%':>5}  titel")
    for b in rows:
        pct = f"{b['progress_percent']:.0f}" if b["progress_percent"] is not None else "-"
        flag = f"  [gearchiveerd: {b['archived_reason']}]" if b["archived"] else ""
        print(f"{b['id']:>4}  {b['status'] or '-':<12} {pct:>5}  {b['title']} - {', '.join(b['authors'])}{flag}")
    return 0


def cmd_restore(args) -> int:
    app = create_app(_cfg(args))
    db = app.extensions["kobosync"].db
    book = db.book_by_id(args.id)
    if book is None:
        print(f"Geen boek met id {args.id}", file=sys.stderr)
        return 1
    db.restore_book(args.id)
    print(f"'{book['title']}' wordt bij de volgende sync weer aangeboden.")
    return 0


def cmd_token(args) -> int:
    cfg = _cfg(args).prepare()
    print(cfg.auth_token)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kobosync", description="Sync server voor eigen ebooks op Kobo e-readers.")
    parser.add_argument("--library", help="map met EPUB/KEPUB-bestanden (standaard: $KOBOSYNC_LIBRARY of ./library)")
    parser.add_argument("--data", help="map voor database, covers en token (standaard: $KOBOSYNC_DATA of ./data)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("serve", help="start de server")
    p.add_argument("--host")
    p.add_argument("--port", type=int)
    p.add_argument("--no-proxy", action="store_true", help="stuur niets door naar de Kobo store")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("scan", help="lees de bibliotheekmap opnieuw in")
    p.set_defaults(func=cmd_scan)
    p = sub.add_parser("list", help="toon boeken en leesvoortgang")
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("restore", help="bied een op het toestel verwijderd boek opnieuw aan")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_restore)
    p = sub.add_parser("token", help="toon het token voor de api_endpoint-url")
    p.set_defaults(func=cmd_token)

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    configure_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
