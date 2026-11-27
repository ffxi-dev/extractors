"""Names, from retail-resources' releases: one folder of Parquet files per client version, mirrored from
ffxi-resources.sruon.dev. These are data, not code. Releases exist only from April 2026 on, so an older
capture takes the nearest release before its client version, or the first one."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ffxi_extractors import store

BASE = "https://ffxi-resources.sruon.dev"
# Cloudflare refuses urllib's own User-Agent there.
HEADERS = {"User-Agent": "ffxi-extractors (ffxi-dev)"}


def _get(url: str, timeout: int):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=timeout)


# Each release file as rows of ClickHouse's names: its kind, its id column, and its text column. A name is
# text, or a struct whose english field is the name. A spell's id in packets is its index.
KINDS = {
    "zones": ("zone", "id", "name"), "entities": ("entity", "entity_id", "name"),
    "items": ("item", "id", "name"),
    "keyitems": ("keyitem", "id", "name"), "spells": ("spell", "index", "name"),
    "abilities": ("ability", "id", "name"), "statuses": ("status", "id", "name"),
    "mob_skills": ("mob_skill", "id", "name"), "quests": ("quest", "id", "name"),
    "missions": ("mission", "id", "name"), "battle_messages": ("battle_message", "id", "text"),
}  # fmt: skip
MONTHS = {m: i for i, m in enumerate(("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
                                       "Nov", "Dec"), 1)}  # fmt: skip


def releases(folder: str | Path) -> list[str]:
    f = Path(folder)
    return (
        sorted(p.name for p in f.iterdir() if p.is_dir() and not p.name.endswith(".part"))
        if f.is_dir()
        else []
    )


def _fetch(base: str, version: str, name: str, into: Path) -> None:
    """One release file, or nothing if the release has none (yet)."""
    try:
        with (
            _get(f"{base}/versions/{version}/{name}.parquet", 600) as r,
            open(into / f"{name}.parquet.part", "wb") as out,
        ):
            shutil.copyfileobj(r, out, 1 << 20)
        (into / f"{name}.parquet.part").replace(into / f"{name}.parquet")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise


def _manifest(base: str, version: str) -> dict:
    """A release's files and their sha256, or {} if it has no manifest."""
    try:
        with _get(f"{base}/versions/{version}/manifest.json", 60) as r:
            return json.load(r).get("files", {})
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        return {}


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def sync(folder: str | Path, changed: list[str] | None = None, base: str = BASE) -> list[str]:
    """Mirror every release not yet here, any file a release here lacks, and any file its manifest says
    changed: retail-resources adds files to old releases when it learns a new DAT, and rewrites them when it
    fixes a parser. Returns the releases that changed, added to changed as each one does."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with _get(f"{base}/versions.json", 60) as r:
        listed = [v["version"] for v in json.load(r)["versions"]]
    changed = [] if changed is None else changed
    for v in listed:
        if (folder / v).is_dir():
            files = _manifest(base, v)
            had = {n: _digest(folder / v / f"{n}.parquet") for n in KINDS}
            want = {n: files.get(f"{n}.parquet", {}).get("sha256") for n in KINDS}
            stale = [n for n in KINDS if had[n] is None or want[n] not in (None, had[n])]
            for name in stale:
                _fetch(base, v, name, folder / v)
            if any(_digest(folder / v / f"{n}.parquet") != had[n] for n in stale):
                changed.append(v)
            continue
        part = folder / f"{v}.part"
        shutil.rmtree(part, ignore_errors=True)
        part.mkdir()
        for name in KINDS:
            _fetch(base, v, name, part)
        part.rename(folder / v)
        changed.append(v)
    return changed


def client_day(client_version: str | None, start_ms: int | None) -> date | None:
    """The day a client build dates from: 30251101_2 is 2025-11-01; captain's build reads
    `Version 18:08:44 Nov 12 2025`; with neither, the day the capture started."""
    v = client_version or ""
    if m := re.fullmatch(r"30(\d{2})(\d{2})(\d{2})_\d+", v):
        return date(2000 + int(m[1]), int(m[2]), int(m[3]))
    if (m := re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4})", v)) and m[1] in MONTHS:
        return date(int(m[3]), MONTHS[m[1]], int(m[2]))
    if start_ms:
        return datetime.fromtimestamp(start_ms / 1000, UTC).date()
    return None


def release_for(client_version: str | None, start_ms: int | None, known: list[str]) -> str | None:
    """The release whose names fit a capture: its own, else the latest before it, else the first."""
    if not known:
        return None
    if client_version in known:
        return client_version
    day = client_day(client_version, start_ms)
    # A folder whose name is no client version is no release.
    before = [r for r in known if day and (d := client_day(r, None)) and d <= day]
    return max(before) if before else min(known)


def _rows(release: str, path: Path, kind: str, id_col: str, col: str) -> pa.Table:
    t = pq.read_table(path)
    t = t.filter(pc.is_valid(t[id_col]))
    name = t[col]
    if pa.types.is_struct(name.type):
        name = pc.struct_field(name, "english")
    n = t.num_rows

    def text(c):
        return t[c].cast(pa.string()) if c in t.column_names else pa.nulls(n, pa.string())

    logs = pa.array([0] * n, pa.int64())
    if "log_id" in t.column_names:
        logs = t["log_id"].cast(pa.int64()).fill_null(0)
    return pa.table({
        "release": [release] * n, "kind": [kind] * n, "log_id": logs, "id": t[id_col].cast(pa.int64()),
        "name": name.cast(pa.string()), "name_passive": text("name_passive"), "log": text("log"),
    })  # fmt: skip


def _rare(release: str, path: Path) -> pa.Table:
    """The items a release flags Rare, as names of kind item_rare: a character holds one at most."""
    t = pq.read_table(path)
    flags = t["flags"].to_pylist() if "flags" in t.column_names else [None] * t.num_rows
    ids = [
        i for i, f in zip(t["id"].to_pylist(), flags, strict=True) if i is not None and "Rare" in (f or [])
    ]
    n = len(ids)
    return pa.table({
        "release": [release] * n, "kind": ["item_rare"] * n, "log_id": pa.array([0] * n, pa.int64()),
        "id": pa.array(ids, pa.int64()), "name": ["Rare"] * n, "name_passive": pa.nulls(n, pa.string()),
        "log": pa.nulls(n, pa.string()),
    })  # fmt: skip


# FFXI's job numbers, as the client and LSB number them.
JOBS = ("WAR", "MNK", "WHM", "BLM", "RDM", "THF", "PLD", "DRK", "BST", "BRD", "RNG", "SAM", "NIN", "DRG",
        "SMN", "BLU", "COR", "PUP", "DNC", "SCH", "GEO", "RUN")  # fmt: skip


def _spell_jobs(release: str, path: Path) -> pa.Table:
    """Each spell's jobs and the level each learns it at, as names of kind spell_job: log_id the job's number,
    name the job, log the level. A mob page's job hints read them (spell_jobs)."""
    t = pq.read_table(path)
    if "level_required" not in t.column_names:
        return pa.table({"id": pa.array([], pa.int64())})
    got = [
        (i, n, j, lv)
        for i, levels in zip(t["index"].to_pylist(), t["level_required"].to_pylist(), strict=True)
        if i is not None
        for n, j in enumerate(JOBS, 1)
        if (lv := (levels or {}).get(j)) is not None
    ]
    n = len(got)
    return pa.table({
        "release": [release] * n, "kind": ["spell_job"] * n,
        "log_id": pa.array([g[1] for g in got], pa.int64()), "id": pa.array([g[0] for g in got], pa.int64()),
        "name": [g[2] for g in got],
        "name_passive": pa.nulls(n, pa.string()), "log": [str(g[3]) for g in got],
    })  # fmt: skip


def lacking(con, folder: str | Path) -> bool:
    """Whether the store lacks a kind of name this code loads from the releases here, as names an older
    version loaded do: item_rare and spell_job came after them."""
    folder = Path(folder)
    want = set()
    for r in releases(folder):
        want |= {kind for file, (kind, _, _) in KINDS.items() if (folder / r / f"{file}.parquet").exists()}
        if (folder / r / "items.parquet").exists():
            want.add("item_rare")
        if (folder / r / "spells.parquet").exists():
            want.add("spell_job")
    return bool(want - {k for (k,) in store.rows(con, "SELECT DISTINCT kind FROM names")})


def load(con, folder: str | Path) -> None:
    """Replace ClickHouse's names, and names_one built from them, with every release mirrored here, at
    once."""
    folder = Path(folder)
    for t in ("names", "names_one"):
        con.command(f"DROP TABLE IF EXISTS {t}_next SYNC")
        con.command(f"CREATE TABLE {t}_next AS {t}")
    for r in releases(folder):
        for file, (kind, id_col, col) in KINDS.items():
            if (folder / r / f"{file}.parquet").exists():
                store.insert(con, "names_next", _rows(r, folder / r / f"{file}.parquet", kind, id_col, col))
        if (folder / r / "items.parquet").exists():
            store.insert(con, "names_next", _rare(r, folder / r / "items.parquet"))
        if (folder / r / "spells.parquet").exists():
            store.insert(con, "names_next", _spell_jobs(r, folder / r / "spells.parquet"))
    store.pick_names(con, "names_next", "names_one_next")
    for t in ("names", "names_one"):
        con.command(f"EXCHANGE TABLES {t} AND {t}_next")
        con.command(f"DROP TABLE {t}_next SYNC")
