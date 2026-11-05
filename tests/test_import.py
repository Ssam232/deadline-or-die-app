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
            row = {"key": key, "data": {"name": body[0]["name"]}}
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
        self.assertEqual([c["data"]["name"] for c in fake.collections], ["To Read", "LCR HCR CVxR"])
        self.assertIn({"tag": "q1"}, d["tags"])
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
        fake.items[0]["data"]["extra"] = "Read order: B09 (Core)"  # a later hand edit is left alone
        self.assertEqual(self.m.run(), 0)
        self.assertEqual(fake.items[0]["data"]["extra"], "Read order: B09 (Core)")

    def test_unmatched_read_order_is_an_error_and_retried(self):
        self.order_file([{"code": "A01", "title": "Nowhere"}])
        self.assertEqual(self.m.run(), 1)
        self.assertFalse((self.root / self.m.ORDER_MARKER).exists())

    def ordered_item(self, key, code, title=None, extra_lines=""):
        self.scout_item(key)
        fake.items[-1]["data"].update({"title": title or f"Paper {key}", "extra": f"Read order: {code} (x){extra_lines}"})

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
