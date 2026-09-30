# Method

Read this before you quote a number from this repo. It says what is measured, how, and where the
sample is thin.

## The question

AI search answers cite web pages. Some of those pages later die, move or change. This repo
re-checks the same set of cited URLs every month and records what happened, so the decay can be
quoted with a date and a sample size.

## Where the URLs come from

Seeds come from published lists of AI answers and their sources, plus any you add with
`python -m citation_rot add`. The first seed source is the Search Arena dataset from LMArena
(version 1, 7,000 comparisons, collected 18 March to 13 April 2025), read on 30 September 2026
from <https://huggingface.co/datasets/lmarena-ai/search-arena-v1-7k>. Its prompts are CC-BY-4.0
and its model outputs fall under the providers' terms, so this repo keeps only the cited URL, the
date of the answer and the engine family. It never stores prompts or answer text.

What "cited" means depends on the engine, and the seed file records it in the `via` field:

- OpenAI search models return links inside the answer text (`inline`).
- Perplexity and Gemini models return a list of retrieved sources with the answer
  (`search_results`). Some of those may not appear in the answer text.

The models in the dataset are API versions of search-enabled models (for example
`api-gpt-4o-search`, `ppl-sonar-pro`, `gemini-2.5-pro-grounding`), not the consumer products.
"Engine family" means openai, perplexity or google, nothing finer.

Dropped at harvest time, and never stored: links on social and login-walled hosts (LinkedIn,
Facebook, Instagram, X, TikTok, Telegram, The Org and similar), personal profile and author pages
(`/profile/`, `/author/`, `/people/`, `@handle` pages and the like), redirect tokens, addresses with
credentials or email addresses, non-public hostnames, and host names with sensitive words. The
filter is a path and host list, so a few personal pages will still get through. The drop counts
are in `seeds/search-arena-v1-7k.meta.json`.

## The panel

Re-checking all seeds every month would be slow and impolite, so a panel is drawn once and then
frozen in `data/panel.jsonl`. The same URLs are checked every month, because decay only means
something for a fixed set.

- Random sample, fixed seed, so the draw can be reproduced from the seeds.
- At most 25 URLs per host, so YouTube and Wikipedia do not fill the panel.
- Equal quotas per engine family. One engine returns far more URLs than the others, so a plain
  sample would tell you almost nothing about the rest. The headline figure is therefore not
  proportional to citation volume. Quote the per-engine rows, with their sample sizes.
- New URLs join only as a new, labelled cohort (`panel --extend`). Old cohorts are never
  reshuffled.

The panel is small next to studies that check millions of URLs. It is a repeatable sample, not a
census. The 95% intervals in the report are Wilson score intervals and assume the panel is a
random sample of the seeds. They do not cover the bias in where the seeds came from.

## The check

For each URL, once a month, from one machine:

1. Fetch `robots.txt` for the host (cached for the run). Follow RFC 9309: a 4xx means allowed, a
   5xx or redirect loop means not allowed. A URL that robots.txt disallows is not fetched.
2. Wait at least 2 seconds since the last request to that host, longer if the host sets a
   `Crawl-delay`.
3. GET the URL with the user agent `citation-rot/<version> (+https://github.com/rishsadh/citation-rot; ...)`.
   Follow up to 5 redirects by hand, checking robots.txt on every hop. Read at most 256 KB.
4. Retry once after 3 seconds if the host did not answer or returned a 5xx (not for DNS failures).
5. Classify the result into exactly one of these:

| Status | Meaning |
|---|---|
| live | 2xx, and the final URL is the same page (scheme, `www`, trailing slash, fragment and tracking parameters are ignored) |
| moved | 2xx, but the redirect chain ended on a different page. `to_home` marks a redirect to a site's home page, which is often a dead page in disguise |
| soft-404 | 2xx, but the title or first heading says the page is missing, or a very short page says so |
| dead | 404 or 410 |
| unreachable | DNS failure, refused or reset connection, timeout, TLS failure, or a redirect loop |
| server-error | 5xx after the retry |
| blocked | 401, 402, 403, 405, 406, 407, 429, 451, 999, or robots.txt says no. These are what paywalls and bot filters answer a script, so we could not look and the page is not judged |
| other | a TLS failure (for example a certificate this client cannot verify), a local socket error, any other 4xx, or an unusable redirect. Not judged: these say as much about the client as about the page |

Rates use only the pages we could judge. `blocked` and `other` are reported but left out of the
denominator. A large blocked share (Reddit is one) means the dead rate there is unknown, not low.

Two headline rates:

- **Not live**: moved, soft-404, dead, unreachable and server-error, over judged pages. This is
  the broad reading and the closest match to how OtterlyAI grouped its results (below).
- **Gone**: dead and soft-404 over judged pages. This is the narrow reading: the server answered
  and the page was not there.

YouTube gets a second opinion. It serves a normal 200 page for a removed video, so a page check
calls every dead video live. For video URLs, `citation-rot` also asks YouTube's oEmbed endpoint
(allowed by its robots.txt): 404 or 400 means dead, 200 means live, 401 (private or restricted)
means blocked. No other site has a special probe yet, so other sites that answer 200 for gone
pages are counted as live.

A single check is a snapshot. A timeout today can be a live page tomorrow; the month-on-month
table shows which URLs flip back (`unreachable -> live`).

## What "changed" means

For text pages, the tool keeps a 64-bit simhash of the visible text (navigation, headers,
footers, sidebars, forms and scripts removed) plus the title and text length. It does not keep
the page. From the second month on, a page that is live in both runs counts as changed when the
simhash differs by 10 or more bits. That threshold is a judgement call, not a standard. Small
edits, rotating ads and dates usually stay under it. A rewritten article does not. PDFs and other
non-text files keep only their `ETag`, `Last-Modified` and `Content-Length` headers.

The first run (30 September 2026) is the baseline, so it has no change data. The change columns
appear in the report from the second run.

## Comparison with the OtterlyAI study

OtterlyAI published a one-off study on 24 July 2026: 20,092,769 URLs cited by seven AI search
engines over one month, of which 19.3% were not live
(<https://otterly.ai/blog/dead-citations-study/>, read 30 September 2026). Its URL data is not
published there, it was a single check of each URL, and it says the check covered roughly a
third of the corpus so far. Differences that matter when you compare numbers:

| | OtterlyAI | this repo |
|---|---|---|
| Sample | 20M+ URLs | 2,000 URLs, same ones every month |
| Checks | one snapshot | monthly, so decay and recovery are visible |
| Cited when | one month of 2026 | March to April 2025 (about 17 months before the first check) |
| Redirects | counted as not live | only counted as moved if the page differs |
| 403 and 429 | not described in the study [[CONFIRM: how blocked responses were counted]] | reported as blocked, left out of the rates |
| Data | not published | every record is in `data/runs/` |

So a figure here will not match theirs, and it should not be presented as a replication. The age
of the citations alone changes the rate.

## How noisy one check is

A single pass misjudges some pages. While building this, the panel was checked several times on
30 September 2026, with the same settings, and later passes disagreed with earlier ones on about
1% of URLs: 23 and 26 of 2,000 changed status between two pairs of passes, nearly all of them
blocked-then-live, live-then-blocked, or timeout-then-live. Those passes used an earlier draw of
the panel and are not kept in the repo. Read a month-on-month movement of one or two percent
as noise until the series is longer, and look at the per-URL `status change` table rather than the
headline rate.

## Known limits

- The seeds are one dataset, from crowdsourced prompts on one arena, in March and April 2025.
  They are skewed to what arena users asked about and to English.
- Search Arena is not a measurement of any engine's real citation behaviour today.
- Headless or bot-blocking sites answer a script differently from a person. `blocked` catches the
  obvious cases, but a site can also serve a bot a fake 200 or a soft-404 we do not recognise.
- Soft-404 detection is a short list of phrases in English. Pages that say it in another language
  are counted as live or moved.
- One vantage point, one network. Geo-blocked pages show as unreachable or blocked.
- Not every cited URL was live when it was first cited. Some may never have existed.
