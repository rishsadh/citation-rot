"""Command line: harvest, add, panel, check, report, diff, url."""
import argparse
import json
import sys
from collections import Counter
from datetime import date

from . import harvest as hv
from . import panel as pn
from . import report as rp
from . import store
from .fetch import HostLimiter, Robots, check_url
from .urls import canonical_key, clean_url, excluded_reason, host_of


def cmd_harvest(a):
    def prog(o, t):
        if o % 1000 == 0 or o >= t:
            print(f"read {o}/{t} rows", file=sys.stderr)
    seeds, stats = hv.harvest(sleep=a.sleep, limit=a.limit, progress=prog)
    out = store.seeds_dir() / f"{hv.SOURCE_NAME}.jsonl"
    store.write_jsonl(out, seeds)
    meta = {"source": hv.SOURCE_NAME, "dataset": hv.SOURCE_URL, "dataset_revision": hv.revision(),
            "read_on": date.today().isoformat(), **stats,
            "licence_note": "Prompts CC-BY-4.0; model outputs under provider terms. Only cited URLs, answer date and engine family are kept."}
    store.write_json(store.seeds_dir() / f"{hv.SOURCE_NAME}.meta.json", meta)
    print(json.dumps(meta, indent=2))


def cmd_add(a):
    urls = list(a.urls)
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as f:
            urls += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    path = store.seeds_dir() / "manual.jsonl"
    have = {s["key"]: s for s in store.read_jsonl(path)}
    added = 0
    for raw in urls:
        u = clean_url(raw)
        why = "not a web URL" if u is None else excluded_reason(u)
        if why:
            print(f"skipped {raw}: {why}", file=sys.stderr)
            continue
        k = canonical_key(u)
        if k in have:
            continue
        have[k] = {"url": u, "key": k, "host": host_of(u), "first_cited": a.cited_on, "last_cited": a.cited_on,
                   "engines": [a.engine] if a.engine else [], "times_cited": 1, "source": a.source or "manual",
                   "source_url": a.source_url}
        added += 1
    store.write_jsonl(path, [have[k] for k in sorted(have)])
    print(f"added {added} seeds to {path}")


def cmd_panel(a):
    # Filter again at draw time, so a seed file harvested under older rules cannot put a URL
    # that the privacy filter now refuses into a new cohort.
    # Seeds on local hosts only exist in the test suite, which serves pages from 127.0.0.1.
    seeds = [s for s in store.load_seeds() if excluded_reason(s["url"]) in (None, "not a public hostname")]
    existing = store.read_jsonl(store.panel_path())
    if existing and not a.extend:
        sys.exit("A panel already exists and is frozen. Use --extend to add a new cohort to it.")
    cohort = a.cohort or store.month_now()
    new = pn.build(seeds, a.size, a.per_host, a.seed, cohort, [p["key"] for p in existing], stratify=not a.no_stratify)
    store.write_jsonl(store.panel_path(), existing + new)
    meta_path = store.panel_path().with_name("panel.meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {"cohorts": []}
    meta["cohorts"].append({"cohort": cohort, "size": len(new), "per_host": a.per_host, "seed": a.seed,
                            "stratified_by_engine": not a.no_stratify, "seeds_available": len(seeds),
                            "by_engine": dict(Counter(pn.stratum(p) for p in new))})
    store.write_json(meta_path, meta)
    print(f"panel: {len(existing)} existing + {len(new)} new = {len(existing) + len(new)} URLs from {len(seeds)} seeds")


def cmd_check(a):
    from .run import run
    month = a.month or store.month_now()
    panel = store.read_jsonl(store.panel_path())
    if not panel:
        sys.exit("No panel. Run `panel` first.")
    path = store.run_path(month)
    if path.exists() and not a.resume:
        sys.exit(f"{path} exists. A month's run is a snapshot; use --resume to finish an interrupted one.")
    recs = run(panel, month, path, workers=a.workers, delay=a.delay, timeout=a.timeout, resume=a.resume, limit=a.limit)
    print(f"wrote {len(recs)} records to {path}")


def _summaries():
    """Summary for every run, each compared with the run before it."""
    months = store.list_runs()
    out, prev_recs, prev_m = [], None, None
    for m in months:
        hd, recs = store.load_run(m)
        s = rp.summarize(recs, prev_recs, prev_m)
        out.append((m, s, hd))
        prev_recs, prev_m = recs, m
    return out


def cmd_report(a):
    allrun = _summaries()
    if not allrun:
        sys.exit("No runs yet. Run `check` first.")
    month = a.month or allrun[-1][0]
    hit = [x for x in allrun if x[0] == month]
    if not hit:
        sys.exit(f"No run for {month}. Runs: {', '.join(m for m, _, _ in allrun)}")
    _, s, hd = hit[0]
    root = store.root()
    (root / "reports").mkdir(exist_ok=True)
    (root / "reports" / f"{month}.md").write_text(rp.markdown(month, s, hd), encoding="utf-8", newline="\n")
    store.write_json(root / "data" / "summary" / f"{month}.json", s)
    (root / "data" / "history.csv").write_text(rp.history_csv([(m, x) for m, x, _ in allrun]), encoding="utf-8", newline="\n")
    print(rp.headline(month, s))


def cmd_diff(a):
    _, x = store.load_run(a.older)
    _, y = store.load_run(a.newer)
    if not x or not y:
        sys.exit("Both months need a run.")
    t = rp.transitions(y, x)
    print(f"{a.older} -> {a.newer}: {t['compared']} URLs in both")
    for k, v in t["moves"].items():
        print(f"  {k}: {v}")
    print(f"  live in both: {t['live_both']}, text changed: {len(t['changed'])}")
    for c in t["changed"][:a.top]:
        print(f"    {c['distance']:>2} bits  {c['url']}")


def cmd_url(a):
    lim = HostLimiter(a.delay)
    rob = Robots(lim)
    for raw in a.urls:
        u = clean_url(raw)
        if not u:
            print(f"{raw}: not a web URL")
            continue
        r = check_url(u, lim, rob)
        extra = f" -> {r['final_url']}" if r.get("final_url") and r["final_url"] != u else ""
        print(f"{r['status']:<13} {r.get('reason', '')}{extra}  {u}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="citation-rot", description="Monthly re-check of URLs cited in published AI citation studies.")
    sub = p.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="collect seed URLs from the Search Arena dataset")
    h.add_argument("--sleep", type=float, default=1.0, help="seconds between API pages")
    h.add_argument("--limit", type=int, help="stop after this many rows (testing)")
    h.set_defaults(fn=cmd_harvest)

    ad = sub.add_parser("add", help="add your own seed URLs, with where they were cited")
    ad.add_argument("urls", nargs="*")
    ad.add_argument("--from-file")
    ad.add_argument("--source", help="where they were cited, e.g. a study name")
    ad.add_argument("--source-url")
    ad.add_argument("--cited-on", help="YYYY-MM-DD the answer or study was published")
    ad.add_argument("--engine", help="openai, perplexity, google, ...")
    ad.set_defaults(fn=cmd_add)

    pa = sub.add_parser("panel", help="freeze the set of URLs re-checked every month")
    pa.add_argument("--size", type=int, default=2000)
    pa.add_argument("--per-host", type=int, default=25)
    pa.add_argument("--seed", type=int, default=1)
    pa.add_argument("--cohort")
    pa.add_argument("--extend", action="store_true")
    pa.add_argument("--no-stratify", action="store_true", help="plain random sample instead of equal quotas per engine family")
    pa.set_defaults(fn=cmd_panel)

    c = sub.add_parser("check", help="re-check every panel URL and write data/runs/YYYY-MM.jsonl")
    c.add_argument("--month")
    c.add_argument("--workers", type=int, default=8)
    c.add_argument("--delay", type=float, default=2.0, help="seconds between requests to one host")
    c.add_argument("--timeout", type=float, default=15)
    c.add_argument("--resume", action="store_true")
    c.add_argument("--limit", type=int)
    c.set_defaults(fn=cmd_check)

    r = sub.add_parser("report", help="write reports/YYYY-MM.md and data/history.csv, print the headline")
    r.add_argument("--month")
    r.set_defaults(fn=cmd_report)

    d = sub.add_parser("diff", help="what changed between two monthly runs")
    d.add_argument("older")
    d.add_argument("newer")
    d.add_argument("--top", type=int, default=10)
    d.set_defaults(fn=cmd_diff)

    u = sub.add_parser("url", help="check one or more URLs once, without touching the panel")
    u.add_argument("urls", nargs="+")
    u.add_argument("--delay", type=float, default=2.0)
    u.set_defaults(fn=cmd_url)

    a = p.parse_args(argv)
    a.fn(a)
