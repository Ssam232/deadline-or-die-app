"""Runs the importer against a local fake of Zotero, Crossref and Europe PMC."""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Fake:
    def __init__(self):
        self.write = True
        self.collections, self.items, self.tokens = [], [], set()
        self.reject_titles = set()
        self.reject_patch = set()
        self.reject_put = False
        self.crossref = {"10.1/good": {"title": ["Good <i>paper</i>"], "DOI": "10.1/GOOD",
                                       "author": [{"family": "Koch", "given": "L"}], "container-title": ["J Test"],
                                       "issued": {"date-parts": [[2020, 3]]}, "abstract": "<jats:p>Abs</jats:p>"},
                         "10.1/wrong": {"title": ["Something else entirely about plants"], "DOI": "10.1/wrong"}}
        self.epmc = {"PMCID:PMC1": {"title": "Paper from PMC.", "doi": "10.1/pmc", "pubYear": "2019",
                                    "authorList": {"author": [{"lastName": "Britton", "firstName": "S"}]},
                                    "journalInfo": {"journal": {"title": "J PMC"}, "volume": "5"}}}


fake = None


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/keys/current":
            return self.send(200, {"access": {"user": {"library": True, "write": fake.write}}})
        if u.path.startswith("/works/"):
            m = fake.crossref.get(u.path[len("/works/"):])
            return self.send(200, {"message": m}) if m else self.send(404, {})
        if u.path == "/search":
            h = fake.epmc.get(q["query"][0])
            return self.send(200, {"resultList": {"result": [h] if h else []}})
        if u.path.endswith("/collections"):
            return self.send(200, fake.collections)
        if "/items/" in u.path and not u.path.endswith("/top"):
            row = next((i for i in fake.items if i["key"] == u.path.rsplit("/", 1)[1]), None)
            return self.send(200, row) if row else self.send(404, {})
        if u.path.endswith("/items/top"):
            ck = u.path.split("/collections/")[1].split("/")[0] if "/collections/" in u.path else None
            rows = [i for i in fake.items if not ck or ck in i["data"]["collections"]]
            if "tag" in q:
                rows = [i for i in rows if {"tag": q["tag"][0]} in i["data"]["tags"]]
            start = int(q.get("start", ["0"])[0])
            return self.send(200, rows[start:start + int(q.get("limit", ["100"])[0])])
        self.send(404, {})

    def do_PUT(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        row = next(c for c in fake.collections if c["key"] == self.path.rsplit("/", 1)[1])
        if body.get("version") != row["version"] or fake.reject_put:
            return self.send(412, {})
        row["data"].update({"name": body["name"], "parentCollection": body["parentCollection"]})
        row["version"] += 1
        self.send_response(204)
        self.end_headers()

    def do_PATCH(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        key = self.path.rsplit("/", 1)[1]
        row = next(i for i in fake.items if i["key"] == key)
        if key in fake.reject_patch:
            return self.send(412, {})
        if self.headers.get("If-Unmodified-Since-Version") != str(row["version"]):
            return self.send(412, {})
        row["data"].update(body)
        row["version"] += 1
        self.send_response(204)
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        token = self.headers.get("Zotero-Write-Token")
        if token in fake.tokens:
            return self.send(412, {})
        if self.path.endswith("/collections"):
            fake.tokens.add(token)
            key = f"COLL{len(fake.collections)}"
            row = {"key": key, "version": 1, "data": {"name": body[0]["name"],
                                                      "parentCollection": body[0].get("parentCollection", False)}}
            fake.collections.append(row)
            return self.send(200, {"successful": {"0": row}, "failed": {}})
        ok, bad = {}, {}
        for n, it in enumerate(body):
            if it["title"] in fake.reject_titles:
                bad[str(n)] = {"code": 400, "message": "rejected"}
            else:
                row = {"key": f"ITEM{len(fake.items)}", "version": 1, "data": it}
                fake.items.append(row)
                ok[str(n)] = row
        if not bad:
            fake.tokens.add(token)
        self.send(200, {"successful": ok, "failed": bad})


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.srv.server_port}"
        for v in ("ZOTERO_API_BASE", "CROSSREF_BASE", "EPMC_BASE"):
            os.environ[v] = base
        os.environ.update(ZOTERO_USER_ID="1", ZOTERO_API_KEY="k")
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1"
        cls.base = base

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        global fake
        fake = Fake()
        self.root = Path(tempfile.mkdtemp())
        (self.root / "queue").mkdir()
        os.environ["QUEUE_ROOT"] = str(self.root)
        sys.modules.pop("import_papers", None)
        import import_papers
        self.m = import_papers
        self.m.MAX_NEW_PER_RUN = 99  # only the run-limit tests use the real cap

    def tearDown(self):
        shutil.rmtree(self.root)

    def queue(self, papers, name="2026-11-04.json"):
        (self.root / "queue" / name).write_text(json.dumps({"papers": papers}))

    def test_adds_paper_to_new_to_read_collection_and_moves_file(self):
        self.queue([{"doi": "10.1/good", "title": "Good paper", "tags": ["q1"]}])
        self.assertEqual(self.m.run(), 0)
        d = fake.items[0]["data"]
        self.assertEqual(d["title"], "Good paper")
        self.assertEqual(d["DOI"], "10.1/good")
        self.assertEqual(d["date"], "2020-03")
        self.assertEqual(d["collections"], ["COLL0", "COLL1"])
        self.assertEqual([c["data"]["name"] for c in fake.collections], ["To Read", "LCR HCR CVxR", "Read", "Dropped", "Inbox"])
        self.assertIn({"tag": "subject:q1"}, d["tags"])
        self.assertIn({"tag": "year:2020"}, d["tags"])
        self.assertFalse(list((self.root / "queue").glob("*.json")))
        self.assertTrue((self.root / "done" / "2026-11-04.json").exists())

    def test_resolves_pmcid_through_europe_pmc(self):
        self.queue([{"pmcid": "PMC1", "title": "Paper from PMC", "tags": []}])
        self.assertEqual(self.m.run(), 0)
        d = fake.items[0]["data"]
        self.assertEqual((d["DOI"], d["publicationTitle"]), ("10.1/pmc", "J PMC"))
        self.assertEqual(d["creators"][0]["lastName"], "Britton")

    def test_wrong_doi_is_flagged_and_its_metadata_not_used(self):
        self.queue([{"doi": "10.1/wrong", "title": "High-fat diet and the rat diaphragm"}])
        self.assertEqual(self.m.run(), 0)
        d = fake.items[0]["data"]
        self.assertEqual(d["title"], "High-fat diet and the rat diaphragm")
        self.assertEqual(d["DOI"], "")
        self.assertIn({"tag": "needs-check"}, d["tags"])

    def test_unresolvable_paper_is_flagged_not_dropped(self):
        self.queue([{"doi": "10.1/missing", "title": "Unknown paper"}])
        self.assertEqual(self.m.run(), 0)
        self.assertIn({"tag": "needs-check"}, fake.items[0]["data"]["tags"])

    def test_skips_papers_already_in_library_and_leaves_them_alone(self):
        fake.items.append({"key": "OLD", "version": 7, "data": {"title": "Old", "DOI": "https://doi.org/10.1/GOOD",
                                                                "collections": [], "tags": [{"tag": "read"}]}})
        before = json.dumps(fake.items[0])
        self.queue([{"doi": "10.1/good", "title": "Good paper"}])
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(len(fake.items), 1)
        self.assertEqual(json.dumps(fake.items[0]), before)

    def test_duplicates_across_queue_files_import_once(self):
        self.queue([{"doi": "10.1/good", "title": "Good paper"}], "a.json")
        self.queue([{"doi": "10.1/good", "title": "Good paper"}], "b.json")
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(len(fake.items), 1)

    def test_read_only_key_stops_before_writing_and_keeps_queue(self):
        fake.write = False
        self.queue([{"doi": "10.1/good", "title": "Good paper"}])
        with self.assertRaisesRegex(self.m.ImportFailure, "read-only"):
            self.m.run()
        self.assertEqual(fake.items, [])
        self.assertTrue((self.root / "queue" / "2026-11-04.json").exists())

    def test_failed_item_keeps_file_and_retry_does_not_duplicate(self):
        fake.reject_titles = {"Unknown paper"}
        self.queue([{"doi": "10.1/good", "title": "Good paper"}, {"doi": "10.1/none", "title": "Unknown paper"}])
        self.assertEqual(self.m.run(), 1)
        self.assertTrue((self.root / "queue" / "2026-11-04.json").exists())
        fake.reject_titles = set()
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(sorted(i["data"]["title"] for i in fake.items), ["Good paper", "Unknown paper"])

    def test_batch_where_every_item_failed_is_retried_not_lost(self):
        fake.reject_titles = {"Unknown paper"}
        self.queue([{"doi": "10.1/none", "title": "Unknown paper"}])
        self.assertEqual(self.m.run(), 1)
        fake.reject_titles = set()
        self.assertEqual(self.m.run(), 0)
        self.assertEqual([i["data"]["title"] for i in fake.items], ["Unknown paper"])

    def scout_item(self, key="OLD1", colls=("TOREAD",), tags=("paper-scout",)):
        fake.items.append({"key": key, "version": 3, "data": {"title": f"Paper {key}", "collections": list(colls),
                                                              "tags": [{"tag": t} for t in tags]}})

    def test_earlier_imports_join_the_project_collection_and_keep_the_others(self):
        self.scout_item()
        self.scout_item("MINE", colls=("OTHER",), tags=("my-own",))
        self.assertEqual(self.m.run(), 0)
        project = next(c["key"] for c in fake.collections if c["data"]["name"] == "LCR HCR CVxR")
        self.assertEqual(fake.items[0]["data"]["collections"], ["TOREAD", project])
        self.assertEqual(fake.items[1]["data"]["collections"], ["OTHER"])
        self.assertIn("Added 1", (self.root / self.m.BACKFILL_MARKER).read_text())

    def test_backfill_runs_once_so_a_later_removal_sticks(self):
        self.scout_item()
        self.m.run()
        fake.items[0]["data"]["collections"] = ["TOREAD"]
        self.queue([{"doi": "10.1/good", "title": "Good paper"}])
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(fake.items[0]["data"]["collections"], ["TOREAD"])

    def test_failed_backfill_is_reported_and_retried(self):
        self.scout_item()
        fake.reject_patch = {"OLD1"}
        self.assertEqual(self.m.run(), 1)
        self.assertFalse((self.root / self.m.BACKFILL_MARKER).exists())
        fake.reject_patch = set()
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(len(fake.items[0]["data"]["collections"]), 2)

    def order_file(self, entries):
        (self.root / self.m.ORDER_FILE).write_text(json.dumps(entries))

    def test_read_order_is_written_once_and_keeps_other_extra_lines(self):
        self.scout_item()
        fake.items[0]["data"].update({"DOI": "10.1/x", "extra": "My own note"})
        self.scout_item("OLD2")
        self.scout_item("MINE", tags=("my-own",))
        self.order_file([{"code": "A01", "doi": "10.1/X", "title": "Different title"},
                         {"code": "D01", "title": "Paper OLD2"}])
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(fake.items[0]["data"]["extra"], "Read order: A01 (Foundational)\nMy own note")
        self.assertEqual(fake.items[1]["data"]["extra"], "Read order: D01 (Niche)")
        self.assertNotIn("extra", fake.items[2]["data"])
        fake.items[0]["data"]["extra"] = "Read order: B09 (Core)"  # a later hand edit keeps its level, and is not
        self.assertEqual(self.m.run(), 0)                          # overwritten by reading-order.json again
        self.assertEqual(fake.items[0]["data"]["extra"], "Read order: B01 (Core)")  # only renumbered without the gap

    def test_unmatched_read_order_is_an_error_and_retried(self):
        self.order_file([{"code": "A01", "title": "Nowhere"}])
        self.assertEqual(self.m.run(), 1)
        self.assertFalse((self.root / self.m.ORDER_MARKER).exists())

    def ordered_item(self, key, code, title=None, extra_lines=""):
        self.scout_item(key)
        fake.items[-1]["data"].update({"title": title or f"Paper {key}", "extra": f"Read order: {code} ({self.m.LETTER_NAMES[code[0]]}){extra_lines}"})

    def codes(self):
        return {i["data"]["title"]: (i["data"].get("extra") or "").split("\n")[0].replace("Read order: ", "").split(" ")[0]
                for i in fake.items}

    def test_new_paper_goes_to_the_end_of_its_level_without_a_place(self):
        self.ordered_item("B1", "B01")
        self.ordered_item("B2", "B02")
        self.queue([{"doi": "10.1/good", "title": "Good paper", "level": "core"},
                    {"doi": "10.1/none", "title": "No level given"},
                    {"doi": "10.1/none2", "title": "Foundational one", "level": "Foundational"}])
        self.assertEqual(self.m.run(), 0)
        c = self.codes()
        self.assertEqual((c["Good paper"], c["No level given"], c["Foundational one"]), ("B03", "C01", "A01"))
        self.assertEqual((c["Paper B1"], c["Paper B2"]), ("B01", "B02"))

    def test_new_paper_slots_in_and_later_papers_move_down(self):
        self.ordered_item("A1", "A01")
        self.ordered_item("B1", "B01")
        self.ordered_item("B2", "B02", extra_lines="\nMy note")
        self.ordered_item("B3", "B03")
        self.ordered_item("C1", "C01")
        (self.root / self.m.BACKFILL_MARKER).write_text("done")  # so only read-order writes change versions
        self.queue([{"doi": "10.1/good", "title": "Good paper", "before": "paper b2", "level": "niche"}])
        self.assertEqual(self.m.run(), 0)
        c = self.codes()
        self.assertEqual([c[f"Paper {k}"] for k in ("A1", "B1", "B2", "B3", "C1")], ["A01", "B01", "B03", "B04", "C01"])
        self.assertEqual(c["Good paper"], "B02")  # the place wins over the level
        moved = next(i for i in fake.items if i["key"] == "B2")["data"]["extra"]
        self.assertEqual(moved, "Read order: B03 (Core)\nMy note")
        saved = json.loads((self.root / "reading-order.json").read_text())
        self.assertEqual([r["code"] for r in saved], ["A01", "B01", "B02", "B03", "B04", "C01"])
        self.assertEqual(saved[2]["title"], "Good paper")
        self.assertEqual(sum(1 for i in fake.items if i["version"] > 3), 2)  # only the two that moved were written

    # ---- daily tidy: renumbering, ranks, placements ----

    def to_read_key(self):
        fake.collections.append({"key": "TR", "version": 1, "data": {"name": "To Read", "parentCollection": False}})
        for k in (self.m.BACKFILL_MARKER, self.m.FOLDERS_MARKER, self.m.ORDER_MARKER):
            (self.root / k).write_text("done")
        return "TR"

    def paper(self, key, extra=None, status=None, added="2026-01-01", colls=("TR",)):
        d = {"title": f"Paper {key}", "itemType": "journalArticle", "collections": list(colls), "dateAdded": added,
             "tags": [{"tag": status}] if status else []}
        if extra is not None:
            d["extra"] = extra
        fake.items.append({"key": key, "version": 3, "data": d})

    def extra(self, key):
        return next(i for i in fake.items if i["key"] == key)["data"].get("extra")

    def test_ranks_put_reading_first_then_read_order_then_unordered_and_skip_read(self):
        self.to_read_key()
        self.paper("B1", "Read order: B01 (Core)")
        self.paper("A1", "Read order: A01 (Foundational)\nMy note")
        self.paper("C1", "Read order: C01 (Specialized)", status="reading")
        self.paper("R1", "Read order: A02 (Foundational)\nReading rank: 1", status="read")
        self.paper("N2", added="2026-03-01")
        self.paper("N1", added="2026-02-01")
        self.paper("ELSE", "Read order: D01 (Niche)", colls=("OTHER",))
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(self.extra("C1"), "Read order: C01 (Specialized)\nReading rank: 1")
        self.assertEqual(self.extra("A1"), "Read order: A01 (Foundational)\nReading rank: 2\nMy note")
        self.assertEqual(self.extra("B1"), "Read order: B01 (Core)\nReading rank: 3")
        self.assertEqual((self.extra("N1"), self.extra("N2")), ("Reading rank: 4", "Reading rank: 5"))
        self.assertEqual(self.extra("R1"), "Read order: A02 (Foundational)")  # read papers lose their rank
        self.assertEqual(self.extra("ELSE"), "Read order: D01 (Niche)")  # not in To Read, so no rank
        unranked = json.loads((self.root / "unranked.json").read_text())
        self.assertEqual([u["key"] for u in unranked], ["N1", "N2"])
        versions = {i["key"]: i["version"] for i in fake.items}
        self.assertEqual(self.m.run(), 0)  # a second run with nothing new writes nothing
        self.assertEqual({i["key"]: i["version"] for i in fake.items}, versions)

    def test_marking_a_paper_read_moves_the_others_up(self):
        self.to_read_key()
        self.paper("A1", "Read order: A01 (Foundational)")
        self.paper("A2", "Read order: A02 (Foundational)")
        self.m.run()
        fake.items[0]["data"]["tags"] = [{"tag": "read"}]
        self.m.run()
        self.assertEqual((self.extra("A1"), self.extra("A2")),
                         ("Read order: A01 (Foundational)", "Read order: A02 (Foundational)\nReading rank: 1"))

    def test_gaps_and_repeats_are_renumbered_and_leftovers_cleaned(self):
        self.to_read_key()
        self.paper("X", "Read order: B03\n (Core)", added="2026-01-02")
        self.paper("Y", "Read order: B03 (Core)", added="2026-01-01")
        self.paper("Z", "Read order: B07 (Core)")
        self.m.run()
        self.assertEqual([self.extra(k).split("\n")[0] for k in ("Y", "X", "Z")],
                         ["Read order: B01 (Core)", "Read order: B02 (Core)", "Read order: B03 (Core)"])
        self.assertEqual(self.extra("X").count("(Core)"), 1)

    def test_placement_gives_an_existing_paper_its_place(self):
        self.to_read_key()
        self.paper("B1", "Read order: B01 (Core)")
        self.paper("B2", "Read order: B02 (Core)")
        self.paper("NEW", "My note")
        self.paper("WRONG")
        (self.root / "placements").mkdir()
        (self.root / "placements" / "2026-11-07.json").write_text(json.dumps({"papers": [
            {"key": "NEW", "title": "Paper NEW", "level": "core", "before": "Paper B2"}]}))
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(self.extra("NEW"), "Read order: B02 (Core)\nReading rank: 2\nMy note")
        self.assertEqual(self.extra("B2"), "Read order: B03 (Core)\nReading rank: 3")
        self.assertTrue((self.root / "done" / "placed-2026-11-07.json").exists())
        self.assertEqual([u["key"] for u in json.loads((self.root / "unranked.json").read_text())], ["WRONG"])

    def test_manual_papers_already_read_get_tags_but_no_order(self):
        self.to_read_key()
        self.paper("B1", "Read order: B01 (Core)")
        self.paper("OLD", status="read", colls=("RD",))
        self.paper("TAGGED", status="read", colls=("RD",))
        for k, extra in (("OLD", []), ("TAGGED", [{"tag": "question:Q1 What are HCR/LCR rats?"}])):
            next(i for i in fake.items if i["key"] == k)["data"]["tags"] += [{"tag": "manual entry"}, *extra]
        self.assertEqual(self.m.run(), 0)
        listed = json.loads((self.root / "unranked.json").read_text())
        self.assertEqual([(u["key"], u["status"]) for u in listed], [("OLD", "read")])
        (self.root / "placements").mkdir()
        (self.root / "placements" / "t.json").write_text(json.dumps({"papers": [
            {"key": "OLD", "title": "Paper OLD", "level": "core", "tags": ["diet-muscle"], "species": "rat", "type": "study"}]}))
        self.assertEqual(self.m.run(), 0)
        tags = {t["tag"] for t in next(i for i in fake.items if i["key"] == "OLD")["data"]["tags"]}
        self.assertTrue({"question:Q3 How does diet change muscle?", "species:rat", "type:study", "read"} <= tags)
        self.assertIsNone(self.extra("OLD"))  # read: never given an order
        self.assertEqual(self.extra("B1"), "Read order: B01 (Core)\nReading rank: 1")
        self.assertEqual(json.loads((self.root / "unranked.json").read_text()), [])

    def test_placement_with_a_title_that_does_not_match_is_kept(self):
        self.to_read_key()
        self.paper("NEW")
        (self.root / "placements").mkdir()
        (self.root / "placements" / "p.json").write_text(json.dumps({"papers": [
            {"key": "NEW", "title": "A completely different study of plants", "level": "core"}]}))
        self.assertEqual(self.m.run(), 1)
        self.assertTrue((self.root / "placements" / "p.json").exists())
        self.assertEqual(self.extra("NEW"), "Reading rank: 1")

    def test_two_papers_in_one_run_keep_their_places(self):
        self.ordered_item("B1", "B01")
        self.ordered_item("B2", "B02")
        self.queue([{"doi": "10.1/good", "title": "Good paper", "before": "Paper B1"},
                    {"doi": "10.1/none", "title": "Second", "before": "Paper B2"}])
        self.assertEqual(self.m.run(), 0)
        c = self.codes()
        self.assertEqual((c["Good paper"], c["Paper B1"], c["Second"], c["Paper B2"]), ("B01", "B02", "B03", "B04"))

    def test_unknown_place_falls_back_to_the_level(self):
        self.ordered_item("B1", "B01")
        self.queue([{"doi": "10.1/good", "title": "Good paper", "before": "Not a real title", "level": "core"}])
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(self.codes()["Good paper"], "B02")

    def test_run_limit_adds_two_and_keeps_the_rest_for_next_run(self):
        self.m.MAX_NEW_PER_RUN = 2
        self.queue([{"doi": "10.1/a", "title": "One"}, {"doi": "10.1/b", "title": "Two"}, {"doi": "10.1/c", "title": "Three"}])
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(sorted(i["data"]["title"] for i in fake.items), ["One", "Two"])
        left = json.loads((self.root / "queue" / "2026-11-04.json").read_text())["papers"]
        self.assertEqual([p["title"] for p in left], ["Three"])
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(len(fake.items), 3)
        self.assertFalse(list((self.root / "queue").glob("*.json")))

    def test_duplicates_do_not_use_up_the_run_limit(self):
        self.m.MAX_NEW_PER_RUN = 1
        self.ordered_item("OLD", "A01", title="Already here")
        self.queue([{"doi": "10.1/none", "title": "Already here"}, {"doi": "10.1/good", "title": "Good paper"}])
        self.assertEqual(self.m.run(), 0)
        self.assertIn("Good paper", self.codes())

    def test_failed_move_keeps_the_file_and_the_retry_fixes_the_order(self):
        self.ordered_item("B1", "B01")
        self.queue([{"doi": "10.1/good", "title": "Good paper", "before": "Paper B1"}])
        fake.reject_patch = {"B1"}
        self.assertEqual(self.m.run(), 1)
        self.assertTrue((self.root / "queue" / "2026-11-04.json").exists())
        fake.reject_patch = set()
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(sorted(self.codes().values()), ["B01", "B02"])
        self.assertEqual(sum(i["data"]["title"] == "Good paper" for i in fake.items), 1)

    def test_app_lists_papers_in_read_order_and_tracks_status(self):
        app = os.getenv("APP_CHECKOUT")
        if not app:
            self.skipTest("set APP_CHECKOUT to a checkout of main")
        self.queue([{"doi": "10.1/none", "title": "Later", "level": "niche"},
                    {"doi": "10.1/good", "title": "Good paper", "level": "foundational"},
                    {"kind": "webpage", "title": "A protocol", "url": "https://x.org", "level": "core"}])
        self.m.run()
        fake.items.append({"key": "OWN", "version": 1, "data": {"itemType": "journalArticle", "title": "Own", "creators": [],
                           "tags": [{"tag": "keep"}], "collections": [fake.collections[0]["key"]]}})
        sys.path.insert(0, app)
        sys.modules.pop("zotero", None)
        import zotero as Z
        Z.API = self.base
        rl = Z.reading_list("1", "k", "To Read")
        self.assertEqual([p["order"] for p in rl], ["A01", "B01", "D01", ""])
        self.assertEqual([p["level"] for p in rl], ["Foundational", "Core", "Niche", None])
        Z.set_status("1", "k", rl[0]["key"], "reading")
        Z.set_status("1", "k", rl[0]["key"], "dropped")
        Z.set_status("1", "k", "OWN", "read")
        own = next(i for i in fake.items if i["key"] == "OWN")
        self.assertEqual(own["data"]["tags"], [{"tag": "keep"}, {"tag": "read"}])
        first = next(i for i in fake.items if i["key"] == rl[0]["key"])
        self.assertNotIn({"tag": "reading"}, first["data"]["tags"])
        self.assertIn({"tag": "paper-scout"}, first["data"]["tags"])
        self.assertEqual([p["title"] for p in Z.to_read("1", "k", "To Read")], ["A protocol", "Later"])
        Z.set_status("1", "k", rl[0]["key"], "unread")
        self.assertEqual(Z.to_read("1", "k", "To Read")[0]["title"], "Good paper")

    def folder(self, name):
        return next(c for c in fake.collections if c["data"]["name"] == name)

    def test_folders_nest_and_papers_already_read_or_dropped_move(self):
        fake.collections.append({"key": "TR", "version": 4, "data": {"name": "To Read", "parentCollection": False}})
        fake.collections.append({"key": "MINE", "version": 1, "data": {"name": "Read", "parentCollection": False}})
        self.scout_item("A", colls=("TR",), tags=("paper-scout", "read"))
        self.scout_item("B", colls=("TR", "OTHER"), tags=("paper-scout", "dropped"))
        self.scout_item("C", colls=("TR",), tags=("paper-scout", "reading"))
        self.assertEqual(self.m.run(), 0)
        project = self.folder("LCR HCR CVxR")["key"]
        self.assertEqual(self.folder("To Read")["data"]["parentCollection"], project)
        read = next(c for c in fake.collections if c["data"]["name"] == "Read" and c["key"] != "MINE")
        self.assertEqual(read["data"]["parentCollection"], project)
        self.assertFalse(next(c for c in fake.collections if c["key"] == "MINE")["data"]["parentCollection"])
        dropped = self.folder("Dropped")
        self.assertEqual(dropped["data"]["parentCollection"], project)
        a, b, c = fake.items[:3]
        self.assertNotIn("TR", a["data"]["collections"])
        self.assertIn(read["key"], a["data"]["collections"])
        self.assertIn(project, a["data"]["collections"])
        self.assertIn("OTHER", b["data"]["collections"])
        self.assertIn(dropped["key"], b["data"]["collections"])
        self.assertIn("TR", c["data"]["collections"])
        n = len(fake.collections)
        os.unlink(self.root / self.m.FOLDERS_MARKER)
        self.assertEqual(self.m.run(), 0)  # safe to run again
        self.assertEqual(len(fake.collections), n)

    def test_failed_folder_move_is_reported_and_retried(self):
        fake.collections.append({"key": "TR", "version": 4, "data": {"name": "To Read", "parentCollection": False}})
        fake.reject_put = True
        self.assertEqual(self.m.run(), 1)
        self.assertFalse((self.root / self.m.FOLDERS_MARKER).exists())
        fake.reject_put = False
        self.assertEqual(self.m.run(), 0)
        self.assertTrue((self.root / self.m.FOLDERS_MARKER).exists())

    def test_app_moves_papers_between_folders_and_still_lists_them_all(self):
        app = os.getenv("APP_CHECKOUT")
        if not app:
            self.skipTest("set APP_CHECKOUT to a checkout of main")
        self.queue([{"doi": "10.1/good", "title": "Good paper", "level": "core"},
                    {"doi": "10.1/none", "title": "Other", "level": "niche"}])
        self.assertEqual(self.m.run(), 0)
        sys.path.insert(0, app)
        sys.modules.pop("zotero", None)
        import zotero as Z
        Z.API = self.base
        tr, rd, dr = (self.folder(n)["key"] for n in ("To Read", "Read", "Dropped"))
        project = self.folder("LCR HCR CVxR")["key"]
        item = next(i for i in fake.items if i["data"]["title"] == "Good paper")
        for status, where in (("reading", tr), ("read", rd), ("dropped", dr), ("unread", tr)):
            Z.set_status("1", "k", item["key"], status)
            self.assertEqual(set(item["data"]["collections"]), {where, project}, status)
            self.assertEqual(Z.reading_list("1", "k")[0]["status"], status)
            self.assertEqual(len(Z.reading_list("1", "k")), 2)
        Z.set_status("1", "k", item["key"], "read")
        self.assertEqual([p["title"] for p in Z.to_read("1", "k")], ["Other"])

    def test_new_paper_gets_labelled_tags_and_bad_values_are_left_off(self):
        self.queue([{"doi": "10.1/good", "title": "Good paper", "tags": ["diet-muscle"], "species": "Rat",
                     "sex": "unclear", "type": "study"}])
        self.assertEqual(self.m.run(), 0)
        tags = {t["tag"] for t in fake.items[0]["data"]["tags"]}
        self.assertEqual(tags, {"question:Q3 How does diet change muscle?", "subject:Diet and muscle", "year:2020",
                                "species:rat", "type:study", "paper-scout"})

    def test_earlier_papers_are_tagged_once_keeping_status_and_own_tags(self):
        self.scout_item(tags=("paper-scout", "diet-muscle", "read", "my-own"))
        fake.items[0]["data"].update({"DOI": "10.1/x", "date": "2016-11-17"})
        (self.root / self.m.FACTS_FILE).write_text(json.dumps(
            [{"doi": "10.1/X", "title": "Paper OLD1", "tags": ["diet-muscle"], "species": "rat", "sex": "male", "type": "study"}]))
        self.assertEqual(self.m.run(), 0)
        tags = {t["tag"] for t in fake.items[0]["data"]["tags"]}
        self.assertEqual(tags, {"question:Q3 How does diet change muscle?", "subject:Diet and muscle", "year:2016",
                                "species:rat", "sex:male", "type:study", "paper-scout", "read", "my-own"})
        fake.items[0]["data"]["tags"].append({"tag": "species:mouse"})  # a later hand edit is left alone
        self.assertEqual(self.m.run(), 0)
        self.assertIn({"tag": "species:mouse"}, fake.items[0]["data"]["tags"])

    def test_missing_paper_in_facts_is_an_error_and_retried(self):
        (self.root / self.m.FACTS_FILE).write_text(json.dumps([{"title": "Nowhere", "tags": ["diet-muscle"]}]))
        self.assertEqual(self.m.run(), 1)
        self.assertFalse((self.root / self.m.FACTS_MARKER).exists())

    def test_app_reads_the_labelled_tags(self):
        app = os.getenv("APP_CHECKOUT")
        if not app:
            self.skipTest("set APP_CHECKOUT to a checkout of main")
        self.queue([{"doi": "10.1/good", "title": "Good paper", "tags": ["diet-muscle"], "species": "rat", "type": "study"}])
        self.m.run()
        sys.path.insert(0, app)
        sys.modules.pop("zotero", None)
        import zotero as Z
        Z.API = self.base
        p = Z.reading_list("1", "k")[0]
        self.assertEqual(p["facets"], {"question": ["Q3 How does diet change muscle?"], "subject": ["Diet and muscle"],
                                       "species": ["rat"], "sex": [], "type": ["study"], "source": []})
        self.assertEqual(p["year"], "2020")
        self.assertFalse(p["needs_check"])

    def test_app_renumber_bumps_the_level_and_closes_the_gap(self):
        app = os.getenv("APP_CHECKOUT")
        if not app:
            self.skipTest("set APP_CHECKOUT to a checkout of main")
        sys.path.insert(0, app)
        sys.modules.pop("zotero", None)
        import zotero as Z
        ps = [{"key": k, "order": o} for k, o in (("a", "A01"), ("b", "A02"), ("c", "B01"), ("d", "B02"), ("n", ""))]
        self.assertEqual(Z.renumber(ps, "n", "A", 2), {"n": "A02", "b": "A03"})
        self.assertEqual(Z.renumber(ps, "c", "A", 1), {"c": "A01", "a": "A02", "b": "A03", "d": "B01"})
        self.assertEqual(Z.renumber(ps, "n", "D", 9), {"n": "D01"})
        self.assertEqual(Z._facets([{"tag": "manual entry"}])["source"], ["Manual entry"])

    def test_questions_go_on_earlier_papers_once_and_touch_nothing_else(self):
        self.scout_item(tags=("paper-scout", "subject:Diet and muscle", "species:mouse", "year:2016", "read", "my-own"))
        fake.items[0]["data"]["DOI"] = "10.1/x"
        (self.root / self.m.QUESTIONS_FILE).write_text(json.dumps(
            [{"doi": "10.1/X", "title": "Paper OLD1", "tags": ["diet-muscle", "strip-testing"]}]))
        self.assertEqual(self.m.run(), 0)
        tags = {t["tag"] for t in fake.items[0]["data"]["tags"]}
        self.assertEqual(tags, {"question:Q3 How does diet change muscle?", "question:Q7 How are muscle strips tested?",
                                "subject:Diet and muscle", "subject:Muscle strip testing", "species:mouse", "year:2016",
                                "paper-scout", "read", "my-own"})
        fake.items[0]["data"]["tags"] = [{"tag": "paper-scout"}, {"tag": "question:Q1 What are HCR/LCR rats?"}]  # a later hand edit stays
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(fake.items[0]["data"]["tags"], [{"tag": "paper-scout"}, {"tag": "question:Q1 What are HCR/LCR rats?"}])

    def test_inbox_papers_move_to_to_read_and_hand_added_papers_get_tagged_then_placed(self):
        self.assertEqual(self.m.run(), 0)  # sets up the folders, Inbox included
        names = {c["data"]["name"]: c["key"] for c in fake.collections}
        tr, proj, inbox, read = names["To Read"], names["LCR HCR CVxR"], names["Inbox"], names["Read"]
        fake.items += [
            {"key": "MINE", "version": 1, "data": {"itemType": "journalArticle", "title": "Paper I found", "date": "2021",
                                                   "extra": "", "tags": [{"tag": "keep"}], "collections": [inbox]}},
            {"key": "OLDR", "version": 1, "data": {"itemType": "journalArticle", "title": "Read long ago", "date": "2015",
                                                   "extra": "", "tags": [{"tag": "read"}], "collections": [read]}},
            {"key": "ELSE", "version": 1, "data": {"itemType": "journalArticle", "title": "Other project", "date": "2015",
                                                   "extra": "", "tags": [], "collections": []}}]
        self.assertEqual(self.m.run(), 0)
        by = {i["key"]: i["data"] for i in fake.items}
        self.assertEqual(set(by["MINE"]["collections"]), {tr, proj})
        self.assertEqual(by["MINE"]["tags"], [{"tag": "keep"}, {"tag": "manual entry"}])
        self.assertIn({"tag": "manual entry"}, by["OLDR"]["tags"])
        self.assertEqual(by["ELSE"]["tags"], [])
        todo = json.loads((self.root / "unranked.json").read_text())
        self.assertEqual([(u["key"], u["order"], u["questions"]) for u in todo], [("MINE", "", False), ("OLDR", "", False)])
        (self.root / "placements").mkdir(exist_ok=True)
        (self.root / "placements" / "p.json").write_text(json.dumps({"papers": [
            {"key": "MINE", "title": "Paper I found", "level": "core", "tags": ["diet-muscle"]},
            {"key": "OLDR", "title": "Read long ago", "tags": ["hcr-lcr"]}]}))
        self.assertEqual(self.m.run(), 0)
        d = next(i["data"] for i in fake.items if i["key"] == "MINE")
        self.assertTrue(d["extra"].startswith("Read order: B01"))
        self.assertIn({"tag": "question:Q3 How does diet change muscle?"}, d["tags"])
        self.assertIn({"tag": "manual entry"}, d["tags"])
        self.assertEqual(json.loads((self.root / "unranked.json").read_text()), [])
        self.assertEqual(by["OLDR"]["extra"], "")  # read: tagged, never ordered
        self.assertIn({"tag": "question:Q1 What are HCR/LCR rats?"}, by["OLDR"]["tags"])
        # a hand-ordered paper with no question still comes up, for tags only
        d["tags"] = [{"tag": "manual entry"}]
        self.assertEqual(self.m.run(), 0)
        self.assertEqual([(u["key"], u["order"]) for u in json.loads((self.root / "unranked.json").read_text())], [("MINE", "B01")])

    def test_every_question_code_has_a_short_numbered_tag(self):
        self.assertEqual(set(self.m.QUESTIONS), set(self.m.SUBJECTS))
        self.assertEqual(sorted(v[:2] for v in self.m.QUESTIONS.values()), [f"Q{i}" for i in range(1, 8)])

    def test_webpage_entry(self):
        self.queue([{"kind": "webpage", "title": "Protocol", "url": "https://x.org/p.pdf", "source": "TREAT-NMD"}])
        self.assertEqual(self.m.run(), 0)
        d = fake.items[0]["data"]
        self.assertEqual((d["itemType"], d["url"]), ("webpage", "https://x.org/p.pdf"))
        self.assertNotIn("DOI", d)

    def test_missing_secrets_gives_clear_error(self):
        os.environ.pop("ZOTERO_API_KEY")
        try:
            with self.assertRaisesRegex(self.m.ImportFailure, "secrets"):
                self.m.run()
        finally:
            os.environ["ZOTERO_API_KEY"] = "k"

    def test_the_apps_own_reader_sees_the_imported_paper(self):
        app = os.getenv("APP_CHECKOUT")
        if not app:
            self.skipTest("set APP_CHECKOUT to a checkout of main")
        self.queue([{"doi": "10.1/good", "title": "Good paper"}])
        self.m.run()
        sys.path.insert(0, app)
        import zotero as Z
        Z.API = self.base
        papers = Z.to_read("1", "k", "To Read")
        self.assertEqual(papers[0]["title"], "Good paper")
        self.assertEqual(papers[0]["url"], "https://doi.org/10.1/good")
        self.assertEqual((papers[0]["who"], papers[0]["year"]), ("Koch", "2020"))


if __name__ == "__main__":
    unittest.main()
