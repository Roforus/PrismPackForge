from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from .network import https_context


class PackError(Exception):
    """An actionable export or installation error."""


def digest(path: Path) -> str:
    h = hashlib.sha512()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise PackError(f"Недопустимый путь: {value!r}")
    parts = value.split("/")
    if any(p in ("", ".", "..") or p.endswith((".", " ")) for p in parts):
        raise PackError(f"Недопустимый путь: {value!r}")
    for part in parts:
        if re.search(r'[<>"|?*\x00-\x1f]', part) or re.fullmatch(
            r"(?i)(CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])(?:\..*)?", part
        ):
            raise PackError(f"Недопустимое имя: {part}")
    return PurePosixPath(value).as_posix()


def target_path(root: Path, relative: str) -> Path:
    relative_path(relative)
    root = root.resolve()
    candidate = root.joinpath(*relative.split("/"))
    # Resolve junctions as well as symbolic links, including missing leaf files.
    if not candidate.resolve().is_relative_to(root):
        raise PackError(f"Путь выходит за пределы папки сборки: {relative}")
    for part in [candidate, *candidate.parents]:
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise PackError(f"Ссылки в целевой папке не поддерживаются: {relative}")
    return candidate


def download_url(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if (parsed.scheme != "https" or parsed.username or parsed.password
            or parsed.port not in (None, 443)
            or not (host == "cdn.modrinth.com" or host.endswith(".forgecdn.net"))):
        raise PackError(f"Неподдерживаемый адрес загрузки: {url}")
    return url


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_file(url: str, output: Path, size: int) -> None:
    req = Request(download_url(url), headers={"User-Agent": "PrismPackForge/0.1"})
    with build_opener(SafeRedirect(), HTTPSHandler(context=https_context())).open(req, timeout=60) as response, output.open("wb") as stream:
        downloaded = 0
        while chunk := response.read(1024 * 1024):
            downloaded += len(chunk)
            if downloaded > size:
                raise PackError("Размер скачанного файла превышает ожидаемый")
            stream.write(chunk)
    if downloaded != size:
        raise PackError("Файл скачан не полностью")
