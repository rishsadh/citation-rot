import contextlib
import io
import os
import pathlib
import tempfile
import unittest

from citation_rot import report, store
from citation_rot.cli import main
from citation_rot.run import interleave, run
from tests.helpers import serve


def item(base, path, host="h", engines=("openai",), cited="2025-03-18"):
    u = base + path
    return {"url": u, "key": u.split("//")[1], "host": host, "engines": list(engines), "first_cited": cited, "cohort": "t"}


class RunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["CITATION_ROT_HOME"] = self.tmp.name
        self.addCleanup(os.environ.pop, "CITATION_ROT_HOME", None)
        self.panel = [item(self.base, p) for p in ("/ok", "/gone", "/moved", "/soft", "/forbidden", "/pdf")]

    def test_interleave_spreads_hosts(self):
        items = [{"host": "a", "k": i} for i in range(3)] + [{"host": "b", "k": 9}]
        self.assertEqual([i["host"] for i in interleave(items)], ["a", "b", "a", "a"])

    def test_run_writes_header_and_one_record_per_url(self):
        path = store.run_path("2026-10")
        quiet = lambda m: None
        recs = run(self.panel, "2026-10", path, workers=3, delay=0, timeout=5, log=quiet)
        self.assertEqual({r["url"].rsplit("/", 1)[1]: r["status"] for r in recs},
                         {"ok": "live", "gone": "dead", "moved": "moved", "soft": "soft-404", "forbidden": "blocked", "pdf": "live"})
        header, again = store.load_run("2026-10")
        self.assertEqual(header["panel_size"], 6)
        self.assertEqual(len(again), 6)
        self.assertEqual([r["key"] for r in again], [p["key"] for p in self.panel])

    def test_resume_skips_finished_urls(self):
        path = store.run_path("2026-10")
        quiet = lambda m: None
        run(self.panel, "2026-10", path, workers=2, delay=0, timeout=5, limit=2, log=quiet)
        self.assertEqual(len(store.load_run("2026-10")[1]), 2)
        run(self.panel, "2026-10", path, workers=2, delay=0, timeout=5, resume=True, log=quiet)
        recs = store.load_run("2026-10")[1]
        self.assertEqual(len(recs), 6)
        self.assertEqual(len({r["key"] for r in recs}), 6)

    def test_report_and_change_detection_across_two_months(self):
        quiet = lambda m: None
        run(self.panel, "2026-10", store.run_path("2026-10"), workers=3, delay=0, timeout=5, log=quiet)
        _, oct_recs = store.load_run("2026-10")
        nov = []
        for r in oct_recs:
            r = dict(r)
            if r["url"].endswith("/ok"):
                r["simhash"] = f"{int(r['simhash'], 16) ^ 0xFFFFFFFFFFFF:016x}"  # 48 bits differ: text changed
            if r["url"].endswith("/moved"):
                r["status"] = "dead"  # moved last month, dead now
            nov.append(r)
        s = report.summarize(nov, oct_recs, "2026-10")
        vp = s["vs_prev"]
        self.assertEqual(vp["compared"], 6)
        self.assertEqual(vp["moves"], {"moved -> dead": 1})
        self.assertEqual(len(vp["changed"]), 1)
        self.assertTrue(vp["changed"][0]["url"].endswith("/ok"))
        first = report.summarize(oct_recs)
        self.assertIsNone(first["vs_prev"])
        self.assertIn("baseline", report.headline("2026-10", first))
        self.assertIn("since 2026-10", report.headline("2026-11", s))

    def test_rates_exclude_blocked(self):
        quiet = lambda m: None
        recs = run(self.panel, "2026-10", store.run_path("2026-10"), workers=3, delay=0, timeout=5, log=quiet)
        s = report.summarize(recs)
        self.assertEqual(s["n"], 6)
        self.assertEqual(s["resolved"], 5)  # the 403 is not judged
        self.assertEqual(s["not_live"], 3)  # moved, soft-404, dead
        self.assertEqual(s["gone"], 2)
        self.assertEqual(s["moved_to_home"], 0)

    def test_history_csv(self):
        quiet = lambda m: None
        recs = run(self.panel, "2026-10", store.run_path("2026-10"), workers=3, delay=0, timeout=5, log=quiet)
        csv_text = report.history_csv([("2026-10", report.summarize(recs))])
        lines = csv_text.strip().splitlines()
        self.assertTrue(lines[0].startswith("month,urls,live,moved"))
        self.assertTrue(lines[1].startswith("2026-10,6,"))


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["CITATION_ROT_HOME"] = self.tmp.name
        self.addCleanup(os.environ.pop, "CITATION_ROT_HOME", None)

    def call(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(list(argv))
        return out.getvalue()

    def test_add_panel_freeze_and_extend(self):
        self.call("add", "https://a.example.org/1?utm_source=x", "https://a.example.org/1", "https://www.linkedin.com/in/x",
                  "https://b.example.org/2", "--source", "Some study", "--cited-on", "2026-09-01", "--engine", "openai")
        seeds = store.load_seeds()
        self.assertEqual(len(seeds), 2)  # duplicate merged, linkedin skipped
        self.assertEqual(seeds[0]["source"], "Some study")
        self.assertIn("0 existing + 2 new = 2 URLs", self.call("panel", "--size", "5", "--cohort", "2026-10"))
        with self.assertRaises(SystemExit):
            self.call("panel", "--size", "5")
        self.call("add", "https://c.example.org/3", "--source", "Other study")
        out = self.call("panel", "--extend", "--size", "5", "--cohort", "2026-11")
        self.assertIn("2 existing + 1 new", out)
        cohorts = [p["cohort"] for p in store.read_jsonl(store.panel_path())]
        self.assertEqual(cohorts, ["2026-10", "2026-10", "2026-11"])

    def test_check_refuses_to_overwrite_a_month(self):
        self.call("add", "https://a.example.org/1")
        self.call("panel")
        store.run_path("2026-10").parent.mkdir(parents=True)
        store.run_path("2026-10").write_text("{}\n")
        with self.assertRaises(SystemExit):
            self.call("check", "--month", "2026-10")

    def test_url_command_and_full_cycle_on_local_server(self):
        srv, base = serve()
        self.addCleanup(srv.shutdown)
        # `add` refuses local addresses on purpose, so write the seeds the way `harvest` would.
        store.write_jsonl(store.seeds_dir() / "t.jsonl", [
            {"url": base + p, "key": base.split("//")[1] + p, "host": "127.0.0.1", "engines": ["google"], "first_cited": "2025-04-01", "source": "t"}
            for p in ("/ok", "/gone")])
        self.call("panel", "--cohort", "2026-10")
        self.call("check", "--month", "2026-10", "--delay", "0", "--timeout", "5")
        out = self.call("report", "--month", "2026-10")
        self.assertIn("2 cited URLs re-checked", out)
        root = pathlib.Path(self.tmp.name)
        self.assertTrue((root / "reports" / "2026-10.md").exists())
        self.assertTrue((root / "data" / "history.csv").exists())
        md = (root / "reports" / "2026-10.md").read_text(encoding="utf-8")
        self.assertIn("## By engine family", md)
        self.assertIn("baseline", md)
        self.assertIn("dead", self.call("url", base + "/gone", "--delay", "0"))


if __name__ == "__main__":
    unittest.main()
