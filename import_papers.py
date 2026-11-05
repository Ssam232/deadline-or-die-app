"""
Moves papers from queue/*.json into two Zotero collections: "To Read" and "LCR HCR CVxR".

Deadline or Die already reads "To Read", so a paper imported here shows up in the app with no
change to the app itself. "LCR HCR CVxR" is the permanent record of everything the search sent.
An item in two collections is one item in Zotero, not a duplicate. Runs in GitHub Actions, where the Zotero key lives as a secret.

Rules:
  - Metadata comes from Crossref or Europe PMC, never from the queue file alone, and is checked
    against the queued title. A failed lookup or a title mismatch still adds the paper, using what
    the queue supplied, but tags it "needs-check" and leaves the DOI off.
  - A paper already in the library is skipped. Existing items are never edited or deleted, apart
    from one-time steps on earlier imports (tag "paper-scout"): adding them to "LCR HCR CVxR", and
    writing the read order from reading-order.json.
  - Read order lives in the item's Extra field as "Read order: B07 (Core)", so sorting by Extra in
    Zotero and the list in Deadline or Die agree. A new paper's "level" puts it at the end of that level.
  - A queue file moves to done/ only once every paper in it has been handled.
"""
from __future__ import annotations

import difflib
import html
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

ZOTERO = os.getenv("ZOTERO_API_BASE", "https://api.zotero.org")
CROSSREF = os.getenv("CROSSREF_BASE", "https://api.crossref.org")
EPMC = os.getenv("EPMC_BASE", "https://www.ebi.ac.uk/europepmc/webservices/rest")
UA = {"User-Agent": "deadline-or-die-paper-importer (github.com/Ssam232/deadline-or-die-app)"}
ROOT = Path(os.getenv("QUEUE_ROOT", "."))
PROJECT = "LCR HCR CVxR"
BACKFILL_MARKER = "backfill-lcr-hcr-cvxr.done"
ORDER_FILE = "reading-order.json"
ORDER_MARKER = "reading-order.done"
LEVELS = {"foundational": ("A", "Foundational"), "core": ("B", "Core"),
          "specialized": ("C", "Specialized"), "niche": ("D", "Niche")}
LETTER_NAMES = {letter: name for letter, name in LEVELS.values()}
ORDER_LINE = re.compile(r"^Read order:\s*([A-D])(\d+).*$", re.M | re.I)
MATCH = 0.72
BATCH = 50


class ImportFailure(RuntimeError):
    pass


def norm_doi(doi: str | None) -> str:
    d = (doi or "").strip().lower()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", d)


def norm_title(title: str | None) -> str:
    t = re.sub(r"<[^>]+>", " ", html.unescape(title or "")).lower()
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def same_title(a: str | None, b: str | None) -> bool:
    x, y = norm_title(a), norm_title(b)
    if not x or not y:
        return False
    return difflib.SequenceMatcher(None, x, y).ratio() >= MATCH or x in y or y in x


def clean_text(text: str | None) -> str:
    t = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", t).strip()


# ---- metadata -------------------------------------------------------------------------------

def from_crossref(doi: str) -> dict | None:
    r = requests.get(f"{CROSSREF}/works/{requests.utils.quote(doi, safe='/')}", headers=UA, timeout=30)
    if r.status_code != 200:
        return None
    m = r.json().get("message", {})
    parts = ((m.get("issued") or {}).get("date-parts") or [[]])[0]
    creators = []
    for a in m.get("author", []) or []:
        if a.get("family"):
            creators.append({"creatorType": "author", "firstName": a.get("given", ""), "lastName": a["family"]})
        elif a.get("name"):
            creators.append({"creatorType": "author", "name": a["name"]})
    return {
        "title": clean_text((m.get("title") or [""])[0]),
        "creators": creators,
        "abstractNote": clean_text(m.get("abstract")),
        "publicationTitle": clean_text((m.get("container-title") or [""])[0]),
        "volume": m.get("volume", ""),
        "issue": m.get("issue", ""),
        "pages": m.get("page", ""),
        "date": "-".join(str(p).zfill(2) if i else str(p) for i, p in enumerate(parts)),
        "ISSN": (m.get("ISSN") or [""])[0],
        "DOI": norm_doi(m.get("DOI") or doi),
    }


def from_epmc(paper: dict) -> dict | None:
    if paper.get("pmcid"):
        query = f"PMCID:{paper['pmcid']}"
    elif paper.get("pmid"):
        query = f"EXT_ID:{paper['pmid']} AND SRC:MED"
    else:
        return None
    r = requests.get(f"{EPMC}/search", headers=UA, timeout=30,
                     params={"query": query, "resultType": "core", "format": "json", "pageSize": 1})
    if r.status_code != 200:
        return None
    hits = (r.json().get("resultList") or {}).get("result") or []
    if not hits:
        return None
    h = hits[0]
    creators = []
    for a in (h.get("authorList") or {}).get("author", []) or []:
        if a.get("lastName"):
            creators.append({"creatorType": "author", "firstName": a.get("firstName", ""), "lastName": a["lastName"]})
        elif a.get("collectiveName"):
            creators.append({"creatorType": "author", "name": a["collectiveName"]})
    journal = h.get("journalInfo") or {}
    return {
        "title": clean_text(h.get("title")),
        "creators": creators,
        "abstractNote": clean_text(h.get("abstractText")),
        "publicationTitle": clean_text((journal.get("journal") or {}).get("title")),
        "volume": journal.get("volume", ""),
        "issue": journal.get("issue", ""),
        "pages": h.get("pageInfo", ""),
        "date": journal.get("printPublicationDate") or h.get("firstPublicationDate") or h.get("pubYear", ""),
        "ISSN": (journal.get("journal") or {}).get("issn", ""),
        "DOI": norm_doi(h.get("doi")),
    }


def resolve(paper: dict) -> tuple[dict | None, str]:
    """Returns (metadata, "") or (None, reason). Network errors count as a failed lookup."""
    claimed = paper.get("title", "")
    tried = []
    for source, fetch in (("Crossref", lambda: from_crossref(norm_doi(paper["doi"])) if paper.get("doi") else None),
                          ("Europe PMC", lambda: from_epmc(paper))):
        try:
            meta = fetch()
        except requests.RequestException as e:
            tried.append(f"{source} error: {type(e).__name__}")
            continue
        if meta is None:
            continue
        if claimed and not same_title(claimed, meta["title"]):
            tried.append(f'{source} returned a different title: "{meta["title"][:70]}"')
            continue
        return meta, ""
    return None, "; ".join(tried) or "no identifier resolved"


def build_item(paper: dict, collections: list[str]) -> dict:
    tags = [{"tag": t} for t in paper.get("tags", [])] + [{"tag": "paper-scout"}]
    if paper.get("kind") == "webpage":
        return {"itemType": "webpage", "title": paper["title"], "url": paper.get("url", ""), "creators": [],
                "websiteTitle": paper.get("source", ""), "date": paper.get("date", ""),
                "tags": tags, "collections": collections, "relations": {}}
    meta, why = resolve(paper)
    if meta is None:
        print(f"  needs-check: {paper.get('title', '?')[:70]} ({why})")
        tags.append({"tag": "needs-check"})
        meta = {"title": paper.get("title", "(untitled)"), "creators": [], "abstractNote": "", "publicationTitle": "",
                "volume": "", "issue": "", "pages": "", "date": paper.get("date", ""), "ISSN": "", "DOI": ""}
    doi = meta["DOI"]
    pmcid = paper.get("pmcid")
    url = (f"https://doi.org/{doi}" if doi else
           f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else paper.get("url", ""))
    return {"itemType": "journalArticle", **meta, "url": url, "tags": tags, "collections": collections, "relations": {}}


def with_order(extra: str | None, code: str) -> str:
    """Sets the read-order line in an Extra field and leaves any other lines alone."""
    line = f"Read order: {code} ({LETTER_NAMES[code[0]]})"
    rest = [ln for ln in (extra or "").splitlines() if ln.strip() and not ORDER_LINE.match(ln)]
    return "\n".join([line, *rest])


def next_code(level: str | None, used: dict[str, int]) -> str:
    """The next free code at the end of a level. A paper with no level counts as specialized."""
    letter = LEVELS.get((level or "").strip().lower(), LEVELS["specialized"])[0]
    used[letter] = used.get(letter, 0) + 1
    return f"{letter}{used[letter]:02d}"


# ---- zotero ---------------------------------------------------------------------------------

class Library:
    def __init__(self, user: str, key: str):
        self.base = f"{ZOTERO}/users/{user}"
        self.h = {"Zotero-API-Key": key, "Zotero-API-Version": "3", **UA}

    def check_write(self) -> None:
        r = requests.get(f"{ZOTERO}/keys/current", headers=self.h, timeout=30)
        if r.status_code != 200:
            raise ImportFailure(f"Zotero rejected the API key ({r.status_code}). Check the ZOTERO_API_KEY secret.")
        if not ((r.json().get("access") or {}).get("user") or {}).get("write"):
            raise ImportFailure("The Zotero key is read-only. Turn on 'Allow write access' at "
                                "zotero.org/settings/keys, then re-run this workflow.")

    def _pages(self, path: str, **params):
        start = 0
        while True:
            r = requests.get(f"{self.base}{path}", headers=self.h, timeout=30,
                             params={"limit": 100, "start": start, **params})
            if r.status_code != 200:
                raise ImportFailure(f"Zotero read failed ({r.status_code}): {r.text[:160]}")
            rows = r.json()
            yield from rows
            if len(rows) < 100:
                return
            start += 100

    def collection(self, name: str) -> str:
        for c in self._pages("/collections"):
            if c["data"]["name"].strip().lower() == name.strip().lower():
                return c["key"]
        r = requests.post(f"{self.base}/collections", json=[{"name": name}], timeout=30,
                          headers={**self.h, "Zotero-Write-Token": uuid.uuid4().hex})
        made = r.json().get("successful", {}) if r.status_code == 200 else {}
        if "0" not in made:
            raise ImportFailure(f'Could not create the "{name}" collection ({r.status_code}): {r.text[:160]}')
        print(f'Created the "{name}" collection.')
        return made["0"]["key"]

    def known(self) -> tuple[set[str], set[str]]:
        dois, titles = set(), set()
        for it in self._pages("/items/top"):
            d = it.get("data", {})
            if d.get("DOI"):
                dois.add(norm_doi(d["DOI"]))
            if d.get("title"):
                titles.add(norm_title(d["title"]))
        return dois, titles

    def add_scout_items_to(self, collection: str) -> tuple[int, list[str]]:
        """Adds earlier imports to a collection. Changes only that membership, and keeps every other one."""
        added, errors = 0, []
        for it in list(self._pages("/items/top", tag="paper-scout")):
            current = it["data"].get("collections", [])
            if collection in current:
                continue
            r = requests.patch(f"{self.base}/items/{it['key']}", json={"collections": current + [collection]},
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code in (200, 204):
                added += 1
            else:
                errors.append(f'{it["data"].get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        return added, errors

    def apply_order(self, order: list[dict]) -> tuple[int, list[str]]:
        """Writes read order onto earlier imports. Papers are matched by DOI, or by title when there is no DOI."""
        by_doi = {norm_doi(o["doi"]): o["code"] for o in order if o.get("doi")}
        by_title = {norm_title(o["title"]): o["code"] for o in order}
        written, matched, errors = 0, set(), []
        for it in list(self._pages("/items/top", tag="paper-scout")):
            d = it["data"]
            code = by_doi.get(norm_doi(d.get("DOI"))) or by_title.get(norm_title(d.get("title")))
            if not code:
                continue
            matched.add(code)
            extra = with_order(d.get("extra"), code)
            if extra == d.get("extra"):
                continue
            r = requests.patch(f"{self.base}/items/{it['key']}", json={"extra": extra},
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code in (200, 204):
                written += 1
            else:
                errors.append(f'{d.get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        missing = [o["code"] for o in order if o["code"] not in matched]
        if missing:
            errors.append("no library item found for " + ", ".join(missing))
        return written, errors

    def used_codes(self) -> dict[str, int]:
        used: dict[str, int] = {}
        for it in self._pages("/items/top"):
            m = ORDER_LINE.search(it["data"].get("extra") or "")
            if m:
                used[m[1].upper()] = max(used.get(m[1].upper(), 0), int(m[2]))
        return used

    def create(self, items: list[dict]) -> list[str]:
        """Creates items, returns a failure message per item that did not save."""
        errors = []
        for i in range(0, len(items), BATCH):
            chunk = items[i:i + BATCH]
            r = requests.post(f"{self.base}/items", json=chunk, timeout=60,
                              headers={**self.h, "Zotero-Write-Token": uuid.uuid4().hex})
            if r.status_code != 200:
                errors.append(f"batch rejected ({r.status_code}): {r.text[:160]}")
                continue
            for pos, f in (r.json().get("failed") or {}).items():
                errors.append(f'{chunk[int(pos)]["title"][:60]}: {f.get("message", "failed")}')
        return errors


# ---- run ------------------------------------------------------------------------------------

def run() -> int:
    user, key = os.getenv("ZOTERO_USER_ID"), os.getenv("ZOTERO_API_KEY")
    if not user or not key:
        raise ImportFailure("Add ZOTERO_USER_ID and ZOTERO_API_KEY as GitHub Actions secrets, then re-run this workflow.")
    pending = sorted((ROOT / "queue").glob("*.json"))
    marker = ROOT / BACKFILL_MARKER
    order_file, order_marker = ROOT / ORDER_FILE, ROOT / ORDER_MARKER
    order_due = order_file.exists() and not order_marker.exists()
    if not pending and marker.exists() and not order_due:
        print("Queue is empty.")
        return 0
    lib = Library(user, key)
    lib.check_write()
    to_read = lib.collection(os.getenv("ZOTERO_COLLECTION") or "To Read")
    project = lib.collection(PROJECT)
    colls = [to_read, project]
    failed_any = False
    if not marker.exists():
        moved, errors = lib.add_scout_items_to(project)
        if errors:
            failed_any = True
            print("Could not add every earlier paper:\n  " + "\n  ".join(errors))
        else:
            marker.write_text(f"Added {moved} earlier papers to {PROJECT}.\n")
            print(f"Added {moved} earlier papers to {PROJECT}.")
    if order_due:
        written, errors = lib.apply_order(json.loads(order_file.read_text()))
        if errors:
            failed_any = True
            print("Could not set the whole read order:\n  " + "\n  ".join(errors))
        else:
            order_marker.write_text(f"Set the read order on {written} papers.\n")
            print(f"Set the read order on {written} papers.")
    dois, titles = lib.known()
    used = lib.used_codes()
    log = []
    (ROOT / "done").mkdir(exist_ok=True)
    for path in pending:
        papers = json.loads(path.read_text()).get("papers", [])
        items, outcomes = [], []
        for p in papers:
            item = build_item(p, colls)
            doi, title = norm_doi(item.get("DOI")), norm_title(item["title"])
            if (doi and doi in dois) or title in titles:
                outcomes.append(("skipped: already in library", item))
                continue
            if doi:
                dois.add(doi)
            titles.add(title)
            item["extra"] = with_order(item.get("extra"), next_code(p.get("level"), used))
            items.append(item)
            outcomes.append(("needs-check" if {"tag": "needs-check"} in item["tags"] else "added", item))
        errors = lib.create(items) if items else []
        if errors:
            failed_any = True
            used = lib.used_codes()  # some may have saved: never hand out the same code twice
            print(f"{path.name} kept in the queue:\n  " + "\n  ".join(errors))
            continue
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log += [{"date": stamp, "outcome": o, "title": i["title"], "doi": norm_doi(i.get("DOI")), "file": path.name,
                 **({"order": i["extra"].split()[2]} if o != "skipped: already in library" else {})}
                for o, i in outcomes]
        path.rename(ROOT / "done" / path.name)
    if log:
        with (ROOT / "imported.jsonl").open("a") as f:
            f.writelines(json.dumps(row) + "\n" for row in log)
    lines = [f"- **{r['outcome']}**: {r['title'][:90]}" for r in log]
    report = "\n".join(lines) or "Nothing imported."
    print(report)
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as f:
            f.write(f"### Papers imported to Zotero\n{report}\n")
    return 1 if failed_any else 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except ImportFailure as e:
        print(f"::error::{e}")
        sys.exit(1)
