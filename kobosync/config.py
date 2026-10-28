from __future__ import annotations

import os
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    library_dir: Path = Path("library")
    data_dir: Path = Path("data")
    auth_token: str = ""
    public_url: str = ""
    proxy_store: bool = True
    host: str = "0.0.0.0"
    port: int = 8085
    kepubify: str = ""
    scan_interval: int = 30
    store_timeout: float = 20.0

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            library_dir=Path(os.environ.get("KOBOSYNC_LIBRARY", "library")),
            data_dir=Path(os.environ.get("KOBOSYNC_DATA", "data")),
            auth_token=os.environ.get("KOBOSYNC_TOKEN", "").strip(),
            public_url=os.environ.get("KOBOSYNC_PUBLIC_URL", "").strip().rstrip("/"),
            proxy_store=_env_bool("KOBOSYNC_PROXY_STORE", True),
            host=os.environ.get("KOBOSYNC_HOST", "0.0.0.0"),
            port=int(os.environ.get("KOBOSYNC_PORT", "8085")),
            kepubify=os.environ.get("KOBOSYNC_KEPUBIFY", "").strip(),
            scan_interval=int(os.environ.get("KOBOSYNC_SCAN_INTERVAL", "30")),
            store_timeout=float(os.environ.get("KOBOSYNC_STORE_TIMEOUT", "20")),
        )

    def prepare(self) -> "Config":
        """Resolve paths, create directories and make sure a token exists."""
        self.library_dir = Path(self.library_dir).expanduser().resolve()
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        self.library_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.covers_dir.mkdir(exist_ok=True)
        self.kepub_dir.mkdir(exist_ok=True)

        if not self.auth_token:
            token_file = self.data_dir / "token.txt"
            if token_file.exists():
                self.auth_token = token_file.read_text(encoding="utf-8").strip()
            if not self.auth_token:
                self.auth_token = secrets.token_hex(16)
                token_file.write_text(self.auth_token + "\n", encoding="utf-8")

        if self.kepubify == "":
            self.kepubify = shutil.which("kepubify") or ""
        elif self.kepubify.lower() in ("0", "false", "no", "off", "none"):
            self.kepubify = ""
        return self

    @property
    def db_path(self) -> Path:
        return self.data_dir / "kobosync.sqlite"

    @property
    def covers_dir(self) -> Path:
        return self.data_dir / "covers"

    @property
    def kepub_dir(self) -> Path:
        return self.data_dir / "kepub"
