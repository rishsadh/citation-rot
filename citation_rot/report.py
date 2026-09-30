"""Turn a month's records into numbers and a readable report."""
import csv
import io
from collections import Counter, defaultdict

from .fetch import CLASSES
from .simhash import distance
from .stats import pct, rate_cell, wilson

CHANGE_BITS = 10  # simhash distance (of 64 bits) at which a live page counts as "changed"
GONE = ("dead", "soft-404")
NOT_LIVE = ("moved", "soft-404", "dead", "unreachable", "server-error")
UNRESOLVED = ("blocked", "other")


def tally(recs):
    c = Counter(r["status"] for r in recs)
    return {k: c.get(k, 0) for k in CLASSES}


def rates(counts):
    """Headline rates. Blocked and other are excluded from the denominator: we could not tell."""
    n = sum(counts.values())
    resolved = n - sum(counts[k] for k in UNRESOLVED)
    not_live = sum(counts[k] for k in NOT_LIVE)
    gone = sum(counts[k] for k in GONE)
    return {"n": n, "resolved": resolved, "not_live": not_live, "gone": gone,
            "unresolved": n - resolved, "live": counts["live"]}


def _group(recs, keyfn):
    g = defaultdict(list)
    for r in recs:
        for k in keyfn(r):
            g[k].append(r)
    return g


def _row(recs):
    c = tally(recs)
    return {"counts": c, **rates(c)}


def transitions(recs, prev):
    """Compare this month with the last, URL by URL. Only URLs present in both are compared."""
    before = {r["key"]: r for r in prev}
    moves, changed, compared, live_both = Counter(), [], 0, 0
    for r in recs:
        p = before.get(r["key"])
        if not p:
            continue
        compared += 1
        if p["status"] != r["status"]:
            moves[(p["status"], r["status"])] += 1
        if p["status"] == "live" and r["status"] == "live":
            live_both += 1
            if p.get("simhash") and r.get("simhash"):
                d = distance(int(p["simhash"], 16), int(r["simhash"], 16))
                if d >= CHANGE_BITS:
                    changed.append({"url": r["url"], "distance": d, "title_before": p.get("title"), "title_after": r.get("title")})
    return {"compared": compared, "live_both": live_both, "moves": {f"{a} -> {b}": n for (a, b), n in sorted(moves.items())},
            "changed": sorted(changed, key=lambda x: -x["distance"])}


def summarize(recs, prev=None, prev_month=None):
    s = {"n": len(recs), **_row(recs)}
    s["by_engine"] = {e: _row(v) for e, v in sorted(_group(recs, lambda r: r.get("engines") or ["unknown"]).items())}
    s["by_cited_month"] = {m: _row(v) for m, v in sorted(_group(recs, lambda r: [(r.get("first_cited") or "unknown")[:7]]).items())}
    hosts = _group(recs, lambda r: [r["host"]])
    top = sorted(hosts.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:15]
    s["top_hosts"] = {h: _row(v) for h, v in top}
    s["reasons"] = {st: dict(Counter(r.get("reason", "") for r in recs if r["status"] == st).most_common(8))
                    for st in ("blocked", "unreachable", "other", "server-error")}
    s["moved_to_home"] = sum(1 for r in recs if r.get("to_home"))
    s["retried"] = sum(1 for r in recs if r.get("retried"))
    s["prev_month"] = prev_month
    s["vs_prev"] = transitions(recs, prev) if prev else None
    return s


def history_csv(rows):
    """rows: list of (month, summary). One line per month."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["month", "urls", *CLASSES, "not_live_rate", "gone_rate", "changed_of_live"])
    for month, s in rows:
        c = s["counts"]
        ch = ""
        vp = s.get("vs_prev")
        if vp and vp["live_both"]:
            ch = f"{len(vp['changed']) / vp['live_both']:.4f}"
        w.writerow([month, s["n"], *[c[k] for k in CLASSES],
                    f"{s['not_live'] / s['resolved']:.4f}" if s["resolved"] else "",
                    f"{s['gone'] / s['resolved']:.4f}" if s["resolved"] else "", ch])
    return out.getvalue()


def headline(month, s):
    """The short text shown in the terminal and the README image."""
    c = s["counts"]
    lines = [f"citation-rot {month}: {s['n']} cited URLs re-checked",
             "",
             f"  live            {c['live']:>5}  {pct(c['live'] / s['n']):>6}",
             f"  moved           {c['moved']:>5}  {pct(c['moved'] / s['n']):>6}   ({s['moved_to_home']} to a home page)",
             f"  soft-404        {c['soft-404']:>5}  {pct(c['soft-404'] / s['n']):>6}",
             f"  dead (404/410)  {c['dead']:>5}  {pct(c['dead'] / s['n']):>6}",
             f"  unreachable     {c['unreachable']:>5}  {pct(c['unreachable'] / s['n']):>6}",
             f"  server error    {c['server-error']:>5}  {pct(c['server-error'] / s['n']):>6}",
             f"  blocked         {c['blocked']:>5}  {pct(c['blocked'] / s['n']):>6}   (not counted: robots.txt, 403, 429)",
             f"  other           {c['other']:>5}  {pct(c['other'] / s['n']):>6}   (not counted: TLS failures, odd codes)",
             ""]
    if s["resolved"]:
        lines += [f"  not live, of the {s['resolved']} we could tell: {rate_cell(s['not_live'], s['resolved'])}",
                  f"  gone (404, 410, soft 404):       {rate_cell(s['gone'], s['resolved'])}"]
    vp = s.get("vs_prev")
    if vp:
        lines += ["", f"  since {s['prev_month']}: {sum(vp['moves'].values())} URLs changed status, "
                      f"{len(vp['changed'])} of {vp['live_both']} live pages changed text"]
    else:
        lines += ["", "  first run: this is the baseline, so no change data yet"]
    return "\n".join(lines)


def _table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join(str(x) for x in r) + " |" for r in rows]
    return "\n".join(out)


def _group_table(title, groups, min_n=1):
    rows = []
    for k, g in groups.items():
        if g["n"] < min_n:
            continue
        c = g["counts"]
        rows.append([k, g["n"], c["live"], c["moved"], c["soft-404"] + c["dead"], c["unreachable"] + c["server-error"],
                     c["blocked"] + c["other"], rate_cell(g["not_live"], g["resolved"])])
    return _table([title, "URLs", "live", "moved", "gone", "unreachable or 5xx", "blocked or other", "not live, of those we could tell (95% interval)"], rows)


def markdown(month, s, header=None):
    hd = header or {}
    out = [f"# Citation rot, {month}", "", "```text", headline(month, s), "```", "",
           f"Panel size {s['n']}. Checked with `{hd.get('user_agent', 'citation-rot')}`, "
           f"{hd.get('delay_s', 2)} seconds between requests to one host, robots.txt honoured. "
           "Rates exclude blocked and other, because those pages could not be judged. Read `METHOD.md` before quoting a number.", "",
           "## By engine family", "",
           "A URL cited by several engine families is counted under each, so these rows add up to more than the panel.", "",
           _group_table("engine", s["by_engine"]), "", "## By month first cited", "",
           _group_table("first cited", s["by_cited_month"]), "", "## Busiest hosts in the panel", "",
           _group_table("host", s["top_hosts"]), ""]
    for st, title in (("blocked", "Why pages were blocked"), ("unreachable", "Why pages were unreachable"),
                      ("other", "Why pages were not judged (other)")):
        r = s["reasons"].get(st)
        if r:
            out += [f"## {title}", ""] + [f"- {k or '(no reason)'}: {v}" for k, v in r.items()] + [""]
    vp = s.get("vs_prev")
    if vp:
        out += [f"## Change since {s['prev_month']}", "", f"{vp['compared']} URLs were in both runs.", ""]
        if vp["moves"]:
            out += [_table(["status change", "URLs"], [[k, v] for k, v in vp["moves"].items()]), ""]
        else:
            out += ["No URL changed status.", ""]
        out += [f"Live in both runs: {vp['live_both']}. Text changed by {CHANGE_BITS} or more of 64 simhash bits: {len(vp['changed'])}.", ""]
        if vp["changed"]:
            out += [_table(["URL", "bits", "title before", "title after"],
                           [[c["url"], c["distance"], (c["title_before"] or "")[:60], (c["title_after"] or "")[:60]] for c in vp["changed"][:25]]), ""]
    else:
        out += ["## Change since last month", "", "This is the first run. It is the baseline: the next run can say which pages died, moved or changed since.", ""]
    return "\n".join(out)
