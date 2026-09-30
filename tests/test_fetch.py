import unittest

from citation_rot.fetch import HostLimiter, Robots, check_url
from tests.helpers import Handler, serve


class FetchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.base = serve()
        cls.lim = HostLimiter(0)
        cls.rob = Robots(cls.lim, timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def chk(self, path, **kw):
        return check_url(self.base + path, self.lim, self.rob, timeout=kw.pop("timeout", 5), retry=False)

    def test_live(self):
        r = self.chk("/ok")
        self.assertEqual(r["status"], "live")
        self.assertEqual(r["title"], "A good article")
        self.assertEqual(r["etag"], '"v1"')
        self.assertTrue(r["simhash"])

    def test_nav_text_is_not_page_text(self):
        self.assertNotIn("menu", str(self.chk("/ok")["text_len"]))  # sanity: field is a number
        from citation_rot.page import extract
        self.assertNotIn("menu", extract("<nav>menu</nav><p>body</p>")[2])

    def test_dead_404_and_410(self):
        self.assertEqual(self.chk("/gone")["status"], "dead")
        self.assertEqual(self.chk("/gone410")["status"], "dead")
        self.assertEqual(self.chk("/nonexistent")["code"], 404)

    def test_moved_follows_redirect_and_records_target(self):
        r = self.chk("/moved")
        self.assertEqual(r["status"], "moved")
        self.assertTrue(r["final_url"].endswith("/ok"))
        self.assertEqual(r["hops"], [301, 200])

    def test_moved_to_home_is_flagged(self):
        r = self.chk("/tohome")
        self.assertEqual(r["status"], "moved")
        self.assertTrue(r["to_home"])

    def test_trailing_slash_redirect_is_still_live(self):
        self.assertEqual(self.chk("/slash")["status"], "live")

    def test_soft_404(self):
        self.assertEqual(self.chk("/soft")["status"], "soft-404")

    def test_blocked_is_not_dead(self):
        self.assertEqual(self.chk("/forbidden")["status"], "blocked")
        self.assertEqual(self.chk("/ratelimited")["status"], "blocked")

    def test_server_error_and_other(self):
        self.assertEqual(self.chk("/err")["status"], "server-error")
        self.assertEqual(self.chk("/teapot")["status"], "other")

    def test_redirect_loop_is_unreachable(self):
        r = self.chk("/loop")
        self.assertEqual(r["status"], "unreachable")
        self.assertIn("loop", r["reason"])

    def test_timeout_is_unreachable(self):
        r = self.chk("/slow", timeout=0.5)
        self.assertEqual(r["status"], "unreachable")
        self.assertEqual(r["reason"], "timeout")

    def test_connection_refused_is_unreachable(self):
        r = check_url("http://127.0.0.1:9/x", self.lim, Robots(self.lim, 2), timeout=2, retry=False)
        self.assertEqual(r["status"], "unreachable")

    def test_robots_disallow_is_respected_and_page_not_fetched(self):
        before = len([h for h in Handler.hits if h == "/private/secret"])
        r = self.chk("/private/secret")
        self.assertEqual(r["status"], "blocked")
        self.assertIn("robots", r["reason"])
        self.assertEqual(len([h for h in Handler.hits if h == "/private/secret"]), before)

    def test_pdf_keeps_header_signals_but_no_text(self):
        r = self.chk("/pdf")
        self.assertEqual(r["status"], "live")
        self.assertEqual(r["content_type"], "application/pdf")
        self.assertIn("last_modified", r)
        self.assertNotIn("simhash", r)

    def test_robots_fetched_once_per_host(self):
        Handler.hits.clear()
        rob = Robots(self.lim, 5)
        for _ in range(3):
            check_url(self.base + "/ok", self.lim, rob, timeout=5, retry=False)
        self.assertEqual(Handler.hits.count("/robots.txt"), 1)

    def test_host_limiter_spaces_requests(self):
        import time
        lim = HostLimiter(0.2)
        t = time.monotonic()
        for _ in range(3):
            lim.wait("a.example")
        self.assertGreaterEqual(time.monotonic() - t, 0.39)
        t = time.monotonic()
        lim.wait("b.example")
        self.assertLess(time.monotonic() - t, 0.1)


if __name__ == "__main__":
    unittest.main()
