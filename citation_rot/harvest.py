"""Collect seed URLs from a published dataset of AI search answers.

Source: Search Arena (LMArena), CC-BY-4.0 for prompts. We read only the cited URLs and the
date and engine family of the answer. Prompts and answer text are never stored.
"""
import json
import time
import urllib.request
from collections import Counter

from .urls import canonical_key, clean_url, excluded_reason, extract_links, host_of

DATASET = "lmarena-ai/search-arena-v1-7k"
SOURCE_NAME = "search-arena-v1-7k"
SOURCE_URL = "https://huggingface.co/datasets/lmarena-ai/search-arena-v1-7k"
ROWS_API = "https://datasets-server.huggingface.co/rows?dataset={ds}&config=default&split=test&offset={off}&length={n}"


def engine_of(model):
    m = (model or "").lower()
    if m.startswith("api-gpt") or "gpt" in m:
        return "openai"
    if m.startswith("ppl-") or "sonar" in m or "perplexity" in m:
        return "perplexity"
    if "gemini" in m:
        return "google"
    return m.split("-")[0] or "unknown"


def extract_row(row):
    """Yield (url, engine, model, via, cited_on) for each source URL in one comparison row (both sides)."""
    date = (row.get("timestamp") or "")[:10]
    for side in ("a", "b"):
        model = row.get(f"model_{side}")
        eng = engine_of(model)
        content = ""
        for m in row.get(f"messages_{side}") or []:
            if m.get("role") == "assistant":
                content = m.get("content") or ""
        found = {}
        for u in extract_links(content):
            found[u] = "inline"
        meta = row.get(f"system_{side}_metadata") or {}
        for step in meta.get("web_search_trace") or []:
            for r in step.get("search_results") or []:
                if r.get("url"):
                    found.setdefault(r["url"], "search_results")
        for u, via in found.items():
            yield u, eng, model, via, date


def fetch_page(offset, n=100, dataset=DATASET, retries=4):
    url = ROWS_API.format(ds=dataset, off=offset, n=n)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "citation-rot (research; +https://github.com/rishsadh/citation-rot)"})
            with urllib.request.urlopen(req, timeout=90) as r:
                d = json.load(r)
            return [x["row"] for x in d["rows"]], d["num_rows_total"]
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(10 * (attempt + 1))


def revision(dataset=DATASET):
    """The dataset's git revision on Hugging Face, so a harvest can be reproduced. None if unreachable."""
    try:
        req = urllib.request.Request(f"https://huggingface.co/api/datasets/{dataset}", headers={"User-Agent": "citation-rot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r).get("sha")
    except Exception:
        return None


def harvest(fetch=fetch_page, sleep=1.0, limit=None, progress=None):
    """Return (seed_records, stats). `fetch(offset)` returns (rows, total)."""
    seeds, dropped, refs = {}, Counter(), 0
    offset, total = 0, None
    while total is None or offset < total:
        rows, total = fetch(offset)
        if not rows:
            break
        for row in rows:
            for raw, eng, model, via, date in extract_row(row):
                refs += 1
                u = clean_url(raw)
                if u is None:
                    dropped["not a web URL"] += 1
                    continue
                why = excluded_reason(u)
                if why:
                    dropped[why] += 1
                    continue
                k = canonical_key(u)
                s = seeds.get(k)
                if s is None:
                    s = seeds[k] = {"url": u, "key": k, "host": host_of(u), "first_cited": date or None,
                                    "last_cited": date or None, "engines": set(), "models": set(), "via": set(),
                                    "times_cited": 0, "source": SOURCE_NAME}
                s["times_cited"] += 1
                s["engines"].add(eng)
                s["models"].add(model)
                s["via"].add(via)
                if date:
                    s["first_cited"] = min(s["first_cited"] or date, date)
                    s["last_cited"] = max(s["last_cited"] or date, date)
        offset += len(rows)
        if progress:
            progress(offset, total)
        if limit and offset >= limit:
            break
        time.sleep(sleep)
    out = []
    for k in sorted(seeds):
        s = seeds[k]
        s["engines"], s["models"], s["via"] = sorted(s["engines"]), sorted(s["models"]), sorted(s["via"])
        out.append(s)
    stats = {"rows_read": offset, "references": refs, "unique_urls": len(out), "dropped": dict(dropped)}
    return out, stats
