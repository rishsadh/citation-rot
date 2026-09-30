import unittest

from citation_rot import harvest, panel
from citation_rot.page import extract, looks_like_404
from citation_rot.simhash import distance, simhash
from citation_rot.stats import wilson
from citation_rot.urls import (canonical_key, clean_url, excluded_reason, extract_links, is_home, same_page)


class UrlTests(unittest.TestCase):
    def test_clean_strips_tracking_and_fragment(self):
        self.assertEqual(clean_url("https://Example.com/a?utm_source=openai&id=3#top"), "https://example.com/a?id=3")
        self.assertEqual(clean_url("https://example.com/a?utm_source=openai"), "https://example.com/a")

    def test_clean_rejects_non_web(self):
        self.assertIsNone(clean_url("ftp://example.com/x"))
        self.assertIsNone(clean_url("mailto:a@b.com"))

    def test_canonical_key_ignores_scheme_www_slash(self):
        self.assertTrue(same_page("http://www.example.com/a/", "https://example.com/a"))
        self.assertFalse(same_page("https://example.com/a", "https://example.com/b"))
        self.assertFalse(same_page("https://example.com/a?id=1", "https://example.com/a?id=2"))

    def test_canonical_key_decodes_paths(self):
        self.assertEqual(canonical_key("https://x.org/caf%C3%A9"), canonical_key("https://x.org/café"))

    def test_is_home(self):
        self.assertTrue(is_home("https://example.com/"))
        self.assertFalse(is_home("https://example.com/a"))

    def test_extract_links_markdown_and_bare(self):
        t = "See ([theorg.com](https://theorg.com/x?utm_source=openai)) and https://b.org/y."
        self.assertEqual(extract_links(t), ["https://theorg.com/x?utm_source=openai", "https://b.org/y."])

    def test_exclusions(self):
        for u in ("https://www.linkedin.com/in/someone", "https://t.me/s/channel", "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                  "http://192.168.0.1/x", "https://user:pw@example.com/", "https://example.com/?e=a.b@c.com", "https://somesexsite.com/"):
            self.assertIsNotNone(excluded_reason(u), u)
        self.assertIsNone(excluded_reason("https://en.wikipedia.org/wiki/Link_rot"))

    def test_personal_profile_pages_are_dropped(self):
        for u in ("https://www.blogger.com/profile/05010167771182635595", "https://spie.org/profile/Andrea.Scaudo-4374951",
                  "https://www.famousbirthdays.com/people/someone.html", "https://mastodon.social/@someone",
                  "https://medium.com/@someone", "https://example.org/author/jane-doe/",
                  "https://en.wikipedia.org/wiki/User:Someone", "https://blueskystarterpack.com/starter-packs/x"):
            self.assertIsNotNone(excluded_reason(u), u)
        for u in ("https://github.com/someuser", "https://www.worldcubeassociation.org/persons/2021ABCD01",
                  "https://www.amazon.com/stores/Some-Name/author/B000000000",
                  "https://forum.example.de/user-post-list/361-someone/"):
            self.assertIsNotNone(excluded_reason(u), u)
        # an article by a named author is an ordinary page and stays
        self.assertIsNone(excluded_reason("https://medium.com/@someone/how-to-check-links-abc123"))
        self.assertIsNone(excluded_reason("https://example.org/blog/2025/link-rot"))
        self.assertIsNone(excluded_reason("https://github.com/owner/repo"))
        self.assertIsNone(excluded_reason("https://github.com/features"))

    def test_login_bot_check_and_token_urls_are_dropped(self):
        for u in ("https://sso.passport.yandex.ru/push?uuid=abc&retpath=https%3A%2F%2Fexample.org%2F",
                  "https://www.google.com/sorry/index?continue=https%3A%2F%2Fwww.google.com%2F&q=EhAm",
                  "https://example.org/report?token=abc123", "https://example.org/a?X-Amz-Signature=abc",
                  "https://example.org/login?next=/a", "https://accounts.example.org/o/authorize/"):
            self.assertIsNotNone(excluded_reason(u), u)
        # an ordinary query string and a page that merely has "login" in its slug stay
        self.assertIsNone(excluded_reason("https://example.org/watch?v=abc&t=10"))
        self.assertIsNone(excluded_reason("https://example.org/blog/how-to-log-in-to-x"))
        self.assertIsNone(excluded_reason("https://www.google.com/search?q=link+rot"))


class PageTests(unittest.TestCase):
    def test_extract_title_h1_text(self):
        t, h, x = extract("<title> Hi  there </title><script>var a=1</script><h1>Head</h1><p>Body text</p>")
        self.assertEqual((t, h), ("Hi there", "Head"))
        self.assertIn("Body text", x)
        self.assertNotIn("var a", x)

    def test_soft_404_needs_title_or_short_page(self):
        self.assertTrue(looks_like_404("Page Not Found | Acme", "", "x" * 2000))
        self.assertTrue(looks_like_404("Acme", "", "Sorry, that page could not be found."))
        self.assertFalse(looks_like_404("Guide to 404 errors", "", "x" * 2000))
        self.assertTrue(looks_like_404("404 | Acme", "", "x" * 2000))
        self.assertFalse(looks_like_404("Acme guide", "Acme guide", "A long article. " * 100 + " page not found in some sentence"))


class SimhashTests(unittest.TestCase):
    base = "the quick brown fox jumps over the lazy dog and keeps running through the field " * 10

    def test_same_text_same_hash(self):
        self.assertEqual(simhash(self.base), simhash(self.base))

    def test_small_edit_is_close_big_edit_is_far(self):
        small = self.base + " one extra sentence here"
        other = "completely unrelated words about tax law and river boats in the north " * 12
        self.assertLess(distance(simhash(self.base), simhash(small)), 10)
        self.assertGreaterEqual(distance(simhash(self.base), simhash(other)), 10)

    def test_empty(self):
        self.assertEqual(simhash(""), 0)


class StatsTests(unittest.TestCase):
    def test_wilson_known_values(self):
        lo, hi = wilson(5, 10)
        self.assertAlmostEqual(lo, 0.2366, places=3)
        self.assertAlmostEqual(hi, 0.7634, places=3)
        lo, hi = wilson(0, 10)
        self.assertEqual(lo, 0.0)
        self.assertAlmostEqual(hi, 0.2775, places=3)
        self.assertEqual(wilson(0, 0), (0.0, 0.0))


ROW = {
    "timestamp": "2025-03-18T17:28:58.245000", "model_a": "api-gpt-4o-search", "model_b": "ppl-sonar",
    "messages_a": [{"role": "user", "content": "private prompt"},
                   {"role": "assistant", "content": "Answer ([theorg.com](https://theorg.com/o?utm_source=openai)) [x](https://b.org/p?utm_source=openai)"}],
    "messages_b": [{"role": "assistant", "content": "No links."}],
    "system_a_metadata": {"web_search_trace": [{"search_results": [{"url": "https://b.org/p"}]}]},
    "system_b_metadata": {"web_search_trace": [{"search_results": [{"url": "https://c.org/q"}, {"url": "https://b.org/p"}]}]},
}


class HarvestTests(unittest.TestCase):
    def test_engine_family(self):
        self.assertEqual(harvest.engine_of("gemini-2.5-pro-grounding"), "google")
        self.assertEqual(harvest.engine_of("ppl-sonar-pro"), "perplexity")
        self.assertEqual(harvest.engine_of("api-gpt-4o-search-high"), "openai")

    def test_extract_row_reads_both_sides_and_marks_how(self):
        got = {(u.split("?")[0], e, via) for u, e, _, via, _ in harvest.extract_row(ROW)}
        self.assertIn(("https://b.org/p", "openai", "inline"), got)
        self.assertIn(("https://c.org/q", "perplexity", "search_results"), got)

    def test_harvest_merges_drops_and_never_keeps_the_prompt(self):
        pages = {0: ([ROW], 2), 1: ([ROW], 2)}
        seeds, stats = harvest.harvest(fetch=lambda off: pages[off], sleep=0)
        by = {s["host"]: s for s in seeds}
        self.assertNotIn("theorg.com", by)  # excluded host
        self.assertEqual(sorted(by["b.org"]["engines"]), ["openai", "perplexity"])
        self.assertEqual(by["b.org"]["first_cited"], "2025-03-18")
        self.assertEqual(stats["rows_read"], 2)
        self.assertIn("excluded host (personal profile, login wall or redirect token)", stats["dropped"])
        self.assertNotIn("private prompt", str(seeds))


class PanelTests(unittest.TestCase):
    seeds = [{"url": f"https://h{i % 4}.org/{i}", "key": f"h{i % 4}.org/{i}", "host": f"h{i % 4}.org", "engines": ["openai"],
              "first_cited": "2025-03-18", "source": "t"} for i in range(40)]

    def test_deterministic(self):
        a = panel.build(self.seeds, 20, 25, seed=7)
        b = panel.build(list(reversed(self.seeds)), 20, 25, seed=7)
        self.assertEqual([x["key"] for x in a], [x["key"] for x in b])

    def test_seed_changes_sample(self):
        a = panel.build(self.seeds, 10, 25, seed=1)
        b = panel.build(self.seeds, 10, 25, seed=2)
        self.assertNotEqual([x["key"] for x in a], [x["key"] for x in b])

    def test_per_host_cap(self):
        p = panel.build(self.seeds, 40, per_host=3, seed=1)
        self.assertEqual(len(p), 12)
        from collections import Counter
        self.assertLessEqual(max(Counter(x["host"] for x in p).values()), 3)

    def test_extend_excludes_existing(self):
        first = panel.build(self.seeds, 10, 25, seed=1)
        more = panel.build(self.seeds, 10, 25, seed=1, exclude_keys=[x["key"] for x in first])
        self.assertFalse({x["key"] for x in first} & {x["key"] for x in more})


if __name__ == "__main__":
    unittest.main()


class ProbeTests(unittest.TestCase):
    def test_youtube_ids(self):
        from citation_rot.probes import youtube_id
        self.assertEqual(youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&pp=abc"), "dQw4w9WgXcQ")
        self.assertEqual(youtube_id("https://youtu.be/dQw4w9WgXcQ?t=3"), "dQw4w9WgXcQ")
        self.assertEqual(youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertIsNone(youtube_id("https://www.youtube.com/@somechannel"))
        self.assertIsNone(youtube_id("https://www.youtube.com/playlist?list=PL123"))
        self.assertIsNone(youtube_id("https://www.youtube.com/watch?v=short"))
        self.assertIsNone(youtube_id("https://example.com/watch?v=dQw4w9WgXcQ"))

    def test_youtube_verdicts(self):
        from citation_rot.probes import youtube_verdict
        self.assertEqual(youtube_verdict(200)[0], "live")
        self.assertEqual(youtube_verdict(404)[0], "dead")
        self.assertEqual(youtube_verdict(400)[0], "dead")
        self.assertEqual(youtube_verdict(401)[0], "blocked")
        self.assertIsNone(youtube_verdict(503)[0])
