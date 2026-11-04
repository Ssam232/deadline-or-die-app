"""
Moves papers from queue/*.json into the Zotero "To Read" collection.

Deadline or Die already reads that collection, so a paper imported here shows up in the app
with no change to the app itself. Runs in GitHub Actions, where the Zotero key lives as a secret.

Rules:
  - Metadata comes from Crossref or Europe PMC, never from the queue file alone, and is checked
    against the queued title. A failed lookup or a title mismatch still adds the paper, using what
    the queue supplied, but tags it "needs-check" and leaves the DOI off.
  - A paper already in the library is skipped. Existing items are never edited or deleted.
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


def build_item(paper: dict, collection: str) -> dict:
    tags = [{"tag": t} for t in paper.get("tags", [])] + [{"tag": "paper-scout"}]
    if paper.get("kind") == "webpage":
        return {"itemType": "webpage", "title": paper["title"], "url": paper.get("url", ""), "creators": [],
                "websiteTitle": paper.get("source", ""), "date": paper.get("date", ""),
                "tags": tags, "collections": [collection], "relations": {}}
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
    return {"itemType": "journalArticle", **meta, "url": url, "tags": tags, "collections": [collection], "relations": {}}


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

    def _pages(self, path: str):
        start = 0
        while True:
            r = requests.get(f"{self.base}{path}", headers=self.h, params={"limit": 100, "start": start}, timeout=30)
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
    if not pending:
        print("Queue is empty.")
        return 0
    lib = Library(user, key)
    lib.check_write()
    coll = lib.collection(os.getenv("ZOTERO_COLLECTION") or "To Read")
    dois, titles = lib.known()
    log, failed_any = [], False
    (ROOT / "done").mkdir(exist_ok=True)
    for path in pending:
        papers = json.loads(path.read_text()).get("papers", [])
        items, outcomes = [], []
        for p in papers:
            item = build_item(p, coll)
            doi, title = norm_doi(item.get("DOI")), norm_title(item["title"])
            if (doi and doi in dois) or title in titles:
                outcomes.append(("skipped: already in library", item))
                continue
            if doi:
                dois.add(doi)
            titles.add(title)
            items.append(item)
            outcomes.append(("needs-check" if {"tag": "needs-check"} in item["tags"] else "added", item))
        errors = lib.create(items) if items else []
        if errors:
            failed_any = True
            print(f"{path.name} kept in the queue:\n  " + "\n  ".join(errors))
            continue
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log += [{"date": stamp, "outcome": o, "title": i["title"], "doi": norm_doi(i.get("DOI")), "file": path.name}
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
