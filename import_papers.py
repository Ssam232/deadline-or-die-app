"""
Moves papers from queue/*.json into Zotero. The collections are arranged as:

    LCR HCR CVxR     every paper the search has sent, the permanent record
      To Read        what's ahead, which Deadline or Die reads
      Read           moved here when marked Read in Deadline or Die
      Dropped        moved here when marked Dropped in Deadline or Die

An item in two collections is one item in Zotero, not a duplicate.
Runs in GitHub Actions, where the Zotero key lives as a secret.

Rules:
  - Metadata comes from Crossref or Europe PMC, never from the queue file alone, and is checked
    against the queued title. A failed lookup or a title mismatch still adds the paper, using what
    the queue supplied, but tags it "needs-check" and leaves the DOI off.
  - A paper already in the library is skipped. Existing items are never edited or deleted, apart
    from one-time steps on earlier imports (tag "paper-scout"): adding them to "LCR HCR CVxR", and
    writing the read order from reading-order.json.
  - Read order lives in the item's Extra field as "Read order: B07 (Core)", so sorting by Extra in
    Zotero and the list in Deadline or Die agree.
  - A new paper goes before the title in its "before" field, or at the end of its "level" if there is
    none. Papers after it in that level move down one, which changes only their read-order line.
  - reading-order.json is rewritten from Zotero after each import, so the next search sees the real order.
  - Papers get Zotero tags such as "question:Q3 How does diet change muscle?", "subject:Diet and muscle",
    "year:2016", "species:rat", "sex:male" and "type:study". A paper's "tags" set its questions and subjects. The year comes from the paper's metadata; a detail not stated in the queue is left off.
  - At most MAX_NEW_PER_RUN papers are added per run. Any extras stay in the queue for the next run.
  - A queue file moves to done/ only once every paper in it has been handled.
  - Papers you add yourself: anything left in the "Inbox" folder under LCR HCR CVxR moves to To Read (Sunday pass only,
    so Deadline or Die's questionnaire gets them first), and every paper
    in the project's folders that the search didn't add (no "paper-scout" tag) is tagged "manual entry".
  - placements/*.json place papers that are already in Zotero, such as ones added by hand. Each entry names the
    item's Zotero key, its title, an optional level and "before" title (placed like a new import, only if it has
    no order yet), and optional question "tags" (added; existing tags stay). The file then moves to done/.
  - search-topics.json lists the extra search topics you add in Deadline or Die (kept as subfolders of "Search topics" in Zotero), for the Sunday search.
  - Every run (Sunday afternoon before the weekly search, and after every push) also keeps the order tidy: each level is renumbered 1, 2, 3...
    without gaps or repeats, and every paper still to read in "To Read" gets an absolute
    "Reading rank: N" line. Papers marked reading come first, then the rest in read order, then any
    without an order, oldest first. Read and dropped papers lose their rank. unranked.json lists the
    papers to read that still have no read order, and every manual entry with no question tag (read ones too, which
    get tags but never an order), for the Sunday search to place and tag by title.
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
FOLDERS_MARKER = "folders.done"
FACTS_FILE = "paper-facts.json"
FACTS_MARKER = "paper-facts.done"
SUBJECTS = {"hcr-lcr": "HCR and LCR rats", "remodeling": "Heart and diaphragm remodeling", "diet-muscle": "Diet and muscle",
            "exercise-obese-muscle": "Exercise and obese muscle", "genetics-exercise": "Genetics and exercise",
            "heart-diaphragm": "Heart and diaphragm failure", "strip-testing": "Muscle strip testing"}
QUESTIONS = {"hcr-lcr": "Q1 What are HCR/LCR rats?", "remodeling": "Q2 What causes remodeling?",
             "diet-muscle": "Q3 How does diet change muscle?", "exercise-obese-muscle": "Q4 How does exercise change obese muscle?",
             "genetics-exercise": "Q5 How do genes and exercise interact?",
             "heart-diaphragm": "Q6 Why does heart + diaphragm failure matter?", "strip-testing": "Q7 How are muscle strips tested?"}
QUESTIONS_FILE = "paper-questions.json"
QUESTIONS_MARKER = "paper-questions.done"
ALLOWED = {"species": {"rat", "mouse", "human"}, "sex": {"male", "female", "both"},
           "type": {"review", "study", "methods"}}
FACT_PREFIXES = ("question:", "subject:", "year:", "species:", "sex:", "type:")
STATUS_FOLDERS = {"read": "Read", "dropped": "Dropped"}
ORDER_FILE = "reading-order.json"
ORDER_MARKER = "reading-order.done"
LEVELS = {"foundational": ("A", "Foundational"), "core": ("B", "Core"),
          "specialized": ("C", "Specialized"), "niche": ("D", "Niche")}
LETTER_NAMES = {letter: name for letter, name in LEVELS.values()}
MAX_NEW_PER_RUN = 5
ORDER_LINE = re.compile(r"^Read order:\s*([A-D])(\d+).*$", re.M | re.I)
RANK_LINE = re.compile(r"^Reading rank:.*$", re.I)
LEFTOVER = re.compile(r"^\s*\((Foundational|Core|Specialized|Niche)\)\s*$", re.I)  # left by an older order editor
UNRANKED_FILE = "unranked.json"
TOPICS_FILE = "search-topics.json"
TOPICS_FOLDER = "Search topics"  # under the project; each subfolder's name is one topic. Deadline or Die manages them.
INBOX = "Inbox"
MANUAL_TAG = "manual entry"
STATUS_TAGS = ("read", "reading", "dropped")
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
    tags = fact_tags(paper, paper.get("date")) + [{"tag": "paper-scout"}]
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
    tags = fact_tags(paper, meta["date"]) + [t for t in tags if not t["tag"].startswith(FACT_PREFIXES)]
    doi = meta["DOI"]
    pmcid = paper.get("pmcid")
    url = (f"https://doi.org/{doi}" if doi else
           f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/" if pmcid else paper.get("url", ""))
    return {"itemType": "journalArticle", **meta, "url": url, "tags": tags, "collections": collections, "relations": {}}


def fact_tags(paper: dict, date: str | None) -> list[dict]:
    """The labelled tags for a paper: its subjects, year, and any species, sex and type that were stated."""
    names = [f"question:{QUESTIONS[t]}" for t in paper.get("tags", []) if t in QUESTIONS]
    names += [f"subject:{SUBJECTS.get(t, t)}" for t in paper.get("tags", [])]
    year = (date or "")[:4]
    if year.isdigit():
        names.append(f"year:{year}")
    for facet, allowed in ALLOWED.items():
        value = (paper.get(facet) or "").strip().lower()
        if value in allowed:
            names.append(f"{facet}:{value}")
    return [{"tag": n} for n in names]


def with_order(extra: str | None, code: str) -> str:
    """Sets the read-order line in an Extra field and leaves any other lines alone."""
    line = f"Read order: {code} ({LETTER_NAMES[code[0]]})"
    rest = [ln for ln in (extra or "").splitlines() if ln.strip() and not ORDER_LINE.match(ln) and not LEFTOVER.match(ln)]
    return "\n".join([line, *rest])


def with_rank(extra: str | None, rank: int | None) -> str:
    """Sets (or, for None, removes) the "Reading rank: N" line, just under the read-order line."""
    lines = [ln for ln in (extra or "").splitlines() if ln.strip() and not RANK_LINE.match(ln)]
    if rank:
        lines.insert(1 if lines and ORDER_LINE.match(lines[0]) else 0, f"Reading rank: {rank}")
    return "\n".join(lines)


def status_of(tags: list[dict]) -> str:
    names = {t.get("tag") for t in tags or []}
    return next((s for s in STATUS_TAGS if s in names), "unread")


def tidy(items: list[dict], to_read: str) -> tuple[dict[str, str], list[dict]]:
    """Works out what every item's Extra should say. Returns {item key: new Extra} for the items that change,
    and the papers still to read that have no read order or no question tag (with their order, if any).

    Each level is renumbered without gaps or repeats, keeping its order (ties go to the paper added first).
    Ranks cover the papers in To Read marked unread or reading: reading first, then by read order, then the
    ones with no order, oldest first.
    """
    codes, groups = {}, {}
    for it in items:
        m = ORDER_LINE.search(it["data"].get("extra") or "")
        if m:
            groups.setdefault(m[1].upper(), []).append((int(m[2]), it["data"].get("dateAdded") or "", it["key"]))
    for letter, group in groups.items():
        for n, (_, _, key) in enumerate(sorted(group), 1):
            codes[key] = f"{letter}{n:02d}"
    ahead = [it for it in items if to_read in it["data"].get("collections", [])
             and status_of(it["data"].get("tags")) in ("unread", "reading")]
    ahead.sort(key=lambda it: (status_of(it["data"].get("tags")) != "reading", codes.get(it["key"], "~"),
                               it["data"].get("dateAdded") or ""))
    ranks = {it["key"]: n for n, it in enumerate(ahead, 1)}
    changes = {}
    for it in items:
        old = it["data"].get("extra") or ""
        new = with_order(old, codes[it["key"]]) if it["key"] in codes else old
        new = with_rank(new, ranks.get(it["key"]))
        if new != old:
            changes[it["key"]] = new
    def no_question(it):  # only papers you added by hand: the search always tags its own
        tags = {t.get("tag", "") for t in it["data"].get("tags", [])}
        return MANUAL_TAG in tags and not any(t.startswith("question:") for t in tags)
    ahead_keys = {it["key"] for it in ahead}
    todo = [it for it in ahead if it["key"] not in codes or no_question(it)]
    todo += [it for it in items if it["key"] not in ahead_keys and no_question(it)]  # read or dropped: tags only
    unranked = [{"key": it["key"], "title": it["data"].get("title", ""), "added": (it["data"].get("dateAdded") or "")[:10],
                 "status": status_of(it["data"].get("tags")) if it["key"] in ahead_keys or status_of(it["data"].get("tags")) != "unread" else "not in To Read",
                 "order": codes.get(it["key"], ""), "questions": not no_question(it)} for it in todo]
    return changes, unranked

def place(rows: list[dict], new: list[tuple[dict, dict]]) -> list[tuple[dict, str]]:
    """Fits new papers into the read order and numbers each level 1, 2, 3...

    rows is the current order, new is (queue entry, Zotero item) pairs. Sets each new item's Extra and returns
    the (existing row, new code) pairs that have to change.
    """
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["code"][0], []).append(row)
    for paper, item in new:
        entry = {"item": item}
        anchor = norm_title(paper.get("before"))
        spot = next(((letter, i) for letter, g in groups.items() for i, r in enumerate(g)
                     if anchor and norm_title(r.get("title")) == anchor), None)
        if spot:
            groups[spot[0]].insert(spot[1], entry)
        else:
            if anchor:
                print(f'  "{paper["before"][:60]}" is not in the read order, so using the level instead.')
            letter = LEVELS.get((paper.get("level") or "").strip().lower(), LEVELS["specialized"])[0]
            groups.setdefault(letter, []).append(entry)
    changes = []
    for letter, group in groups.items():
        for n, entry in enumerate(group, 1):
            code = f"{letter}{n:02d}"
            if "item" in entry:
                entry["item"]["extra"] = with_order(entry["item"].get("extra"), code)
            elif entry["code"] != code:
                changes.append((entry, code))
    return changes


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

    def arrange_folders(self, project: str, to_read: str) -> tuple[int, list[str]]:
        """Puts To Read under the project collection, adds Read and Dropped beside it, and moves papers that are
        already marked read or dropped. Changes only collections, and is safe to run again."""
        errors = []
        cols = list(self._pages("/collections"))
        row = next(c for c in cols if c["key"] == to_read)
        if row["data"].get("parentCollection") != project:
            r = requests.put(f"{self.base}/collections/{to_read}", headers=self.h, timeout=30,
                             json={"key": to_read, "version": row["version"], "name": row["data"]["name"],
                                   "parentCollection": project})
            if r.status_code not in (200, 204):
                return 0, [f"could not move To Read ({r.status_code}): {r.text[:120]}"]
        keys = {}
        for tag, name in STATUS_FOLDERS.items():
            found = next((c["key"] for c in cols if c["data"]["name"].strip().lower() == name.lower()
                          and c["data"].get("parentCollection") == project), None)
            if not found:
                r = requests.post(f"{self.base}/collections", json=[{"name": name, "parentCollection": project}],
                                  headers={**self.h, "Zotero-Write-Token": uuid.uuid4().hex}, timeout=30)
                made = r.json().get("successful", {}) if r.status_code == 200 else {}
                if "0" not in made:
                    return 0, [f'could not create "{name}" ({r.status_code}): {r.text[:120]}']
                found = made["0"]["key"]
            keys[tag] = found
        moved = 0
        for it in list(self._pages(f"/collections/{to_read}/items/top")):
            tags = {t.get("tag") for t in it["data"].get("tags", [])}
            tag = next((t for t in STATUS_FOLDERS if t in tags), None)
            if not tag:
                continue
            colls = [c for c in it["data"].get("collections", []) if c != to_read] + [keys[tag]]
            r = requests.patch(f"{self.base}/items/{it['key']}", json={"collections": list(dict.fromkeys(colls))},
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code in (200, 204):
                moved += 1
            else:
                errors.append(f'{it["data"].get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        return moved, errors

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

    def apply_facts(self, facts: list[dict]) -> tuple[int, list[str]]:
        """Adds labelled tags to earlier imports. Replaces their old topic codes and keeps every other tag."""
        by_doi = {norm_doi(f["doi"]): f for f in facts if f.get("doi")}
        by_title = {norm_title(f["title"]): f for f in facts}
        written, matched, errors = 0, set(), []
        for it in list(self._pages("/items/top", tag="paper-scout")):
            d = it["data"]
            fact = by_doi.get(norm_doi(d.get("DOI"))) or by_title.get(norm_title(d.get("title")))
            if not fact:
                continue
            matched.add(fact["title"])
            keep = [t for t in d.get("tags", []) if not t.get("tag", "").startswith(FACT_PREFIXES)
                    and t.get("tag") not in SUBJECTS]
            tags = fact_tags(fact, d.get("date")) + keep
            r = requests.patch(f"{self.base}/items/{it['key']}", json={"tags": tags},
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code in (200, 204):
                written += 1
            else:
                errors.append(f'{d.get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        missing = [f["title"][:60] for f in facts if f["title"] not in matched]
        if missing:
            errors.append("no library item found for: " + "; ".join(missing))
        return written, errors

    def apply_questions(self, papers: list[dict]) -> tuple[int, list[str]]:
        """Sets the question and subject tags on earlier imports. Every other tag stays as it is."""
        by_doi = {norm_doi(f["doi"]): f for f in papers if f.get("doi")}
        by_title = {norm_title(f["title"]): f for f in papers}
        written, matched, errors = 0, set(), []
        for it in list(self._pages("/items/top", tag="paper-scout")):
            d = it["data"]
            fact = by_doi.get(norm_doi(d.get("DOI"))) or by_title.get(norm_title(d.get("title")))
            if not fact:
                continue
            matched.add(fact["title"])
            keep = [t for t in d.get("tags", []) if not t.get("tag", "").startswith(("question:", "subject:"))]
            tags = [t for t in fact_tags(fact, None)] + keep
            r = requests.patch(f"{self.base}/items/{it['key']}", json={"tags": tags},
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code in (200, 204):
                written += 1
            else:
                errors.append(f'{d.get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        missing = [f["title"][:60] for f in papers if f["title"] not in matched]
        if missing:
            errors.append("no library item found for: " + "; ".join(missing))
        return written, errors

    def ordered(self) -> list[dict]:
        """Every item with a read-order line, in order."""
        rows = []
        for it in self._pages("/items/top"):
            d = it["data"]
            m = ORDER_LINE.search(d.get("extra") or "")
            if m:
                rows.append({"key": it["key"], "version": it["version"], "extra": d.get("extra"),
                             "code": f"{m[1].upper()}{int(m[2]):02d}", "num": int(m[2]),
                             "title": d.get("title", ""), "doi": norm_doi(d.get("DOI"))})
        rows.sort(key=lambda r: (r["code"][0], r["num"]))
        return rows

    def papers(self) -> list[dict]:
        """Every top-level item that is a paper, not a note or attachment."""
        return [it for it in self._pages("/items/top") if it["data"].get("itemType") not in ("note", "attachment", "annotation")]

    def patch_extra(self, item: dict, extra: str) -> str | None:
        r = requests.patch(f"{self.base}/items/{item['key']}", json={"extra": extra},
                           headers={**self.h, "If-Unmodified-Since-Version": str(item["version"])}, timeout=30)
        return None if r.status_code in (200, 204) else f'{item["data"].get("title", "?")[:60]}: {r.status_code} {r.text[:100]}'

    def place_existing(self, papers: list[dict]) -> tuple[int, list[str]]:
        """Gives a read order and question tags to papers already in Zotero, named by key, such as ones you added
        by hand. A paper that already has an order keeps it and only gets the tags. Existing tags all stay."""
        by_key = {it["key"]: it for it in self.papers()}
        pairs, targets, errors = [], [], []
        for p in papers:
            it = by_key.get(p.get("key", ""))
            if not it or not same_title(it["data"].get("title"), p.get("title")):
                errors.append(f'no item {p.get("key")} titled "{(p.get("title") or "")[:60]}"')
                continue
            entry = {"extra": it["data"].get("extra")}
            if p.get("level") and not ORDER_LINE.search(it["data"].get("extra") or "") \
                    and status_of(it["data"].get("tags")) in ("unread", "reading"):  # read or dropped: tags only
                pairs.append((p, entry))
            targets.append((it, entry, p))
        changes = place(self.ordered(), pairs)
        for it, entry, p in targets:
            d = it["data"]
            have = {t.get("tag") for t in d.get("tags", [])}
            extra_tags = [t for t in fact_tags(p, d.get("date")) if t["tag"] not in have]
            body = {**({"extra": entry["extra"]} if entry["extra"] != d.get("extra") else {}),
                    **({"tags": d.get("tags", []) + extra_tags} if extra_tags else {})}
            if not body:
                continue
            r = requests.patch(f"{self.base}/items/{it['key']}", json=body,
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code not in (200, 204):
                errors.append(f'{d.get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        if not errors:
            errors += self.write_codes(changes)
        return len(targets), errors

    def back_to_inbox(self, project: str, to_read: str, keys: list[str]) -> list[str]:
        """Puts papers back in the Inbox (out of To Read), so Deadline or Die's questionnaire can file them."""
        cols = list(self._pages("/collections"))
        inbox = next((c["key"] for c in cols if c["data"].get("parentCollection") == project
                      and c["data"]["name"].strip().lower() == INBOX.lower()), None)
        if not inbox:
            return ["no Inbox folder"]
        by_key = {it["key"]: it for it in self.papers()}
        errors = []
        for k in keys:
            it = by_key.get(k)
            if not it:
                errors.append(f"no item {k}")
                continue
            colls = [c for c in it["data"].get("collections", []) if c != to_read] + [inbox]
            tags = [t for t in it["data"].get("tags", []) if t.get("tag") != MANUAL_TAG]  # the questionnaire adds it back
            r = requests.patch(f"{self.base}/items/{k}", json={"collections": list(dict.fromkeys(colls)), "tags": tags},
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code not in (200, 204):
                errors.append(f"{k}: {r.status_code} {r.text[:100]}")
        return errors

    def _topics_folder(self, project: str, create: bool) -> tuple[str | None, list[dict]]:
        """The "Search topics" folder under the project, and its subfolders (one per topic)."""
        cols = list(self._pages("/collections"))
        folder = next((c["key"] for c in cols if c["data"].get("parentCollection") == project
                       and c["data"]["name"].strip().lower() == TOPICS_FOLDER.lower()), None)
        if not folder and create:
            r = requests.post(f"{self.base}/collections", json=[{"name": TOPICS_FOLDER, "parentCollection": project}],
                              headers={**self.h, "Zotero-Write-Token": uuid.uuid4().hex}, timeout=30)
            made = r.json().get("successful", {}) if r.status_code == 200 else {}
            folder = made.get("0", {}).get("key")
        kids = [c for c in cols if folder and c["data"].get("parentCollection") == folder]
        return folder, kids

    def search_topics(self, project: str) -> list[str]:
        """Extra topics for the Sunday search: the subfolders of "Search topics", which Deadline or Die manages."""
        _, kids = self._topics_folder(project, create=False)
        return sorted((c["data"]["name"].strip() for c in kids), key=str.casefold)

    def add_topics(self, project: str, new: list[str]) -> tuple[list[str], str | None]:
        """Adds topics as subfolders of "Search topics" (made if missing). Returns (all topics, error or None)."""
        folder, kids = self._topics_folder(project, create=True)
        if not folder:
            return [], f'could not create "{TOPICS_FOLDER}"'
        have = [c["data"]["name"].strip() for c in kids]
        add = [t.strip() for t in new if t.strip() and t.strip().casefold() not in {h.casefold() for h in have}]
        if add:
            r = requests.post(f"{self.base}/collections", json=[{"name": t, "parentCollection": folder} for t in add],
                              headers={**self.h, "Zotero-Write-Token": uuid.uuid4().hex}, timeout=30)
            if r.status_code != 200 or r.json().get("failed"):
                return have, f"{r.status_code} {r.text[:100]}"
        return sorted(have + add, key=str.casefold), None

    def sweep_manual(self, project: str, to_read: str, file_inbox: bool = True) -> tuple[int, int, list[str]]:
        """Papers you add yourself. Anything in the Inbox folder (under the project, made if missing) moves to To Read,
        and every paper in the project's folders that the search didn't add gets the tag "manual entry".
        Returns (moved out of the Inbox, newly tagged, errors)."""
        cols = list(self._pages("/collections"))
        inbox = next((c["key"] for c in cols if c["data"].get("parentCollection") == project
                      and c["data"]["name"].strip().lower() == INBOX.lower()), None)
        if not inbox:
            r = requests.post(f"{self.base}/collections", json=[{"name": INBOX, "parentCollection": project}],
                              headers={**self.h, "Zotero-Write-Token": uuid.uuid4().hex}, timeout=30)
            made = r.json().get("successful", {}) if r.status_code == 200 else {}
            if "0" not in made:
                return 0, 0, [f'could not create "{INBOX}" ({r.status_code}): {r.text[:120]}']
            inbox = made["0"]["key"]
        mine = {project, inbox} | {c["key"] for c in cols if c["data"].get("parentCollection") == project}
        moved = tagged = 0
        errors, waiting = [], []
        for it in self.papers():
            d = it["data"]
            colls = d.get("collections", [])
            if not mine & set(colls):
                continue
            names = {t.get("tag") for t in d.get("tags", [])}
            body = {}
            if inbox in colls and not file_inbox:
                waiting.append(d.get("title", "?")[:70])
                continue  # left for the questionnaire in Deadline or Die until the Sunday pass
            if inbox in colls:
                body["collections"] = list(dict.fromkeys([c for c in colls if c != inbox] + [to_read, project]))
            if "paper-scout" not in names and MANUAL_TAG not in names:
                body["tags"] = d.get("tags", []) + [{"tag": MANUAL_TAG}]
            if not body:
                continue
            r = requests.patch(f"{self.base}/items/{it['key']}", json=body,
                               headers={**self.h, "If-Unmodified-Since-Version": str(it["version"])}, timeout=30)
            if r.status_code in (200, 204):
                moved += "collections" in body
                tagged += "tags" in body
            else:
                errors.append(f'{d.get("title", "?")[:60]}: {r.status_code} {r.text[:100]}')
        if waiting:
            print(f"{len(waiting)} paper(s) waiting in the Inbox for Deadline or Die: " + "; ".join(waiting))
        return moved, tagged, errors

    def write_codes(self, changes: list[tuple[dict, str]]) -> list[str]:
        errors = []
        for row, code in changes:
            r = requests.patch(f"{self.base}/items/{row['key']}", json={"extra": with_order(row["extra"], code)},
                               headers={**self.h, "If-Unmodified-Since-Version": str(row["version"])}, timeout=30)
            if r.status_code not in (200, 204):
                errors.append(f'{row["title"][:60]}: {r.status_code} {r.text[:100]}')
        return errors

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
    folders_marker = ROOT / FOLDERS_MARKER
    facts_file, facts_marker = ROOT / FACTS_FILE, ROOT / FACTS_MARKER
    facts_due = facts_file.exists() and not facts_marker.exists()
    questions_file, questions_marker = ROOT / QUESTIONS_FILE, ROOT / QUESTIONS_MARKER
    questions_due = questions_file.exists() and not questions_marker.exists()
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
    if not folders_marker.exists():
        moved, errors = lib.arrange_folders(project, to_read)
        if errors:
            failed_any = True
            print("Could not finish arranging the folders:\n  " + "\n  ".join(errors))
        else:
            folders_marker.write_text(f"Arranged To Read, Read and Dropped under {PROJECT}. Moved {moved} papers.\n")
            print(f"Arranged the folders and moved {moved} papers.")
    if facts_due:
        written, errors = lib.apply_facts(json.loads(facts_file.read_text()))
        if errors:
            failed_any = True
            print("Could not tag every earlier paper:\n  " + "\n  ".join(errors))
        else:
            facts_marker.write_text(f"Tagged {written} earlier papers.\n")
            print(f"Tagged {written} earlier papers.")
    if questions_due:
        written, errors = lib.apply_questions(json.loads(questions_file.read_text()))
        if errors:
            failed_any = True
            print("Could not add every question tag:\n  " + "\n  ".join(errors))
        else:
            questions_marker.write_text(f"Added question tags to {written} earlier papers.\n")
            print(f"Added question tags to {written} earlier papers.")
    if order_due:
        written, errors = lib.apply_order(json.loads(order_file.read_text()))
        if errors:
            failed_any = True
            print("Could not set the whole read order:\n  " + "\n  ".join(errors))
        else:
            order_marker.write_text(f"Set the read order on {written} papers.\n")
            print(f"Set the read order on {written} papers.")
    back = ROOT / "to-inbox.json"
    if back.exists():
        errors = lib.back_to_inbox(project, to_read, json.loads(back.read_text()).get("keys", []))
        if errors:
            failed_any = True
            print("Could not put every paper back in the Inbox:\n  " + "\n  ".join(errors))
        else:
            (ROOT / "done").mkdir(exist_ok=True)
            back.rename(ROOT / "done" / f"to-inbox-{datetime.now(timezone.utc):%Y-%m-%d}.json")
            print("Put papers back in the Inbox.")
    # The Inbox is filed only by the Sunday pass (or a manual run), so a push never beats the app's questionnaire.
    file_inbox = os.getenv("GITHUB_EVENT_NAME", "schedule") in ("schedule", "workflow_dispatch")
    moved, tagged, errors = lib.sweep_manual(project, to_read, file_inbox)
    if errors:
        failed_any = True
        print("Could not file every paper you added:\n  " + "\n  ".join(errors))
    if moved or tagged:
        print(f"Moved {moved} paper(s) out of the Inbox and tagged {tagged} as manual entries.")
    dois, titles = lib.known()
    log = []
    room = MAX_NEW_PER_RUN
    (ROOT / "done").mkdir(exist_ok=True)
    for path in pending:
        if room <= 0:
            break
        queued = json.loads(path.read_text())
        papers = queued.get("papers", [])
        items, pairs, outcomes = [], [], []
        taken = 0
        for p in papers:
            if len(items) >= room:
                break
            taken += 1
            item = build_item(p, colls)
            doi, title = norm_doi(item.get("DOI")), norm_title(item["title"])
            if (doi and doi in dois) or title in titles:
                outcomes.append(("skipped: already in library", item))
                continue
            if doi:
                dois.add(doi)
            titles.add(title)
            items.append(item)
            pairs.append((p, item))
            outcomes.append(("needs-check" if {"tag": "needs-check"} in item["tags"] else "added", item))
        changes = place(lib.ordered(), pairs)
        errors = lib.create(items) if items else []
        if not errors:
            errors = lib.write_codes(changes)
        if errors:
            failed_any = True
            print(f"{path.name} kept in the queue:\n  " + "\n  ".join(errors))
            continue
        room -= len(items)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log += [{"date": stamp, "outcome": o, "title": i["title"], "doi": norm_doi(i.get("DOI")), "file": path.name,
                 **({"order": i["extra"].split()[2]} if o != "skipped: already in library" else {})}
                for o, i in outcomes]
        if taken < len(papers):
            queued["papers"] = papers[taken:]
            path.write_text(json.dumps(queued, indent=1, ensure_ascii=False) + "\n")
            print(f"Run limit reached: {len(papers) - taken} paper(s) stay in {path.name} for the next run.")
        else:
            path.rename(ROOT / "done" / path.name)
    for path in sorted((ROOT / "placements").glob("*.json")):
        wanted = json.loads(path.read_text()).get("papers", [])
        placed, errors = lib.place_existing(wanted)
        if errors:
            failed_any = True
            print(f"{path.name} kept, as some papers could not be placed:\n  " + "\n  ".join(errors))
            continue
        path.rename(ROOT / "done" / f"placed-{path.name}")
        print(f"Placed {placed} paper(s) from {path.name} in the read order.")
    items = lib.papers()
    changes, unranked = tidy(items, to_read)
    by_key = {it["key"]: it for it in items}
    errors = [e for k, extra in changes.items() if (e := lib.patch_extra(by_key[k], extra))]
    if errors:
        failed_any = True
        print("Could not update every rank:\n  " + "\n  ".join(errors))
    print(f"Updated the order or rank on {len(changes) - len(errors)} paper(s). {len(unranked)} paper(s) to read have no order.")
    add, topics = ROOT / "add-topics.json", None
    if add.exists():
        topics, err = lib.add_topics(project, json.loads(add.read_text()).get("topics", []))
        if err:
            topics = None
            failed_any = True
            print(f"Could not add the search topics: {err}")
        else:
            (ROOT / "done").mkdir(exist_ok=True)
            add.rename(ROOT / "done" / f"add-topics-{datetime.now(timezone.utc):%Y-%m-%d}.json")
    topics = topics if topics is not None else lib.search_topics(project)  # just saved: Zotero can list it a moment late
    print(f"{len(topics)} extra search topic(s).")
    (ROOT / TOPICS_FILE).write_text(json.dumps(topics, indent=1, ensure_ascii=False) + "\n")
    (ROOT / UNRANKED_FILE).write_text(json.dumps(unranked, indent=1, ensure_ascii=False) + "\n")
    current = [{"code": r["code"], "doi": r["doi"], "title": r["title"]} for r in lib.ordered()]
    (ROOT / ORDER_FILE).write_text(json.dumps(current, indent=1, ensure_ascii=False) + "\n")
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
