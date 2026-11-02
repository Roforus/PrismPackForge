from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .common import PackError, download_url
from .network import https_context


def api(url: str, body=None, key: str = ""):
    headers = {"User-Agent": "PrismPackForge/0.1", "Accept": "application/json"}
    if key:
        headers["x-api-key"] = key
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    for attempt in range(3):
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=45, context=https_context()) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 429 or exc.code >= 500:
                time.sleep(1 + attempt * 2)
                continue
            raise PackError(f"API вернул HTTP {exc.code}: {url}") from exc
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise PackError(f"Нет связи с API: {url}") from exc
            time.sleep(1 + attempt)
    raise PackError(f"API временно недоступен: {url}")


def fingerprint(data: bytes) -> int:
    """CurseForge's whitespace-normalized MurmurHash2 (seed 1)."""
    data = data.translate(None, b"\x09\x0a\x0d\x20")
    m, mask = 0x5BD1E995, 0xFFFFFFFF
    h = (1 ^ len(data)) & mask
    end = len(data) & ~3
    for offset in range(0, end, 4):
        k = int.from_bytes(data[offset:offset + 4], "little")
        k = (k * m) & mask
        k ^= k >> 24
        k = (k * m) & mask
        h = ((h * m) ^ k) & mask
    tail = data[end:]
    if tail:
        h ^= int.from_bytes(tail, "little")
        h = (h * m) & mask
    h ^= h >> 13
    h = (h * m) & mask
    return (h ^ (h >> 15)) & mask


class Resolver:
    def __init__(self, curseforge_key: str = "", log=print):
        self.key = curseforge_key
        self.log = log

    def resolve(self, files: list[tuple[Path, str]]) -> dict[str, dict]:
        result = {}
        hashes = list(dict.fromkeys(h for _, h in files))
        for start in range(0, len(hashes), 100):
            batch = hashes[start:start + 100]
            self.log(f"Modrinth: проверка {len(batch)} файлов…")
            versions = api("https://api.modrinth.com/v2/version_files", {
                "hashes": batch, "algorithm": "sha512",
            })
            for h, version in versions.items():
                for file in version.get("files", []):
                    if file.get("hashes", {}).get("sha512") == h:
                        result[h] = {"provider": "modrinth", "url": download_url(file["url"]),
                                     "project_id": version["project_id"], "file_id": version["id"]}
                        break
        missing = [(p, h) for p, h in files if h not in result]
        if missing and self.key:
            self.log(f"CurseForge: проверка {len(missing)} файлов…")
            indexed = [(p, h, fingerprint(p.read_bytes())) for p, h in missing]
            for start in range(0, len(indexed), 100):
                batch = indexed[start:start + 100]
                matches = api("https://api.curseforge.com/v1/fingerprints/432", {
                    "fingerprints": [fp for _, _, fp in batch],
                }, self.key)["data"]["exactMatches"]
                for match in matches:
                    file = match["file"]
                    for path, h, fp in batch:
                        if match.get("file", {}).get("fileFingerprint") != fp:
                            continue
                        # Fingerprints are only 32-bit. Verify the cryptographic hash too.
                        with path.open("rb") as stream:
                            sha1 = hashlib.file_digest(stream, "sha1").hexdigest()
                        if not any(x["algo"] == 1 and x["value"].lower() == sha1
                                   for x in file.get("hashes", [])):
                            continue
                        url = file.get("downloadUrl")
                        if not url:
                            self.log(f"CurseForge запрещает прямую загрузку: {path.name}")
                            continue
                        result[h] = {"provider": "curseforge", "url": download_url(url),
                                     "project_id": file["modId"], "file_id": file["id"]}
        return result
