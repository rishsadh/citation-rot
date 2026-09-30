"""Run the monthly check over the panel."""
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import __version__, store
from .fetch import UA, HostLimiter, Robots, check_url


def interleave(items):
    """Round-robin by host so worker threads are not all waiting on one slow host."""
    by = defaultdict(list)
    for it in items:
        by[it["host"]].append(it)
    queues = [by[h] for h in sorted(by, key=lambda h: (-len(by[h]), h))]
    out = []
    while any(queues):
        for q in queues:
            if q:
                out.append(q.pop(0))
    return out


def run(panel, month, path, workers=8, delay=2.0, timeout=15, resume=False, limit=None, log=None):
    """Check every panel URL and write `path` (header line, then one record per URL)."""
    log = log or (lambda m: print(m, file=sys.stderr, flush=True))
    done = {}
    if resume:
        _, prev = store.load_run(month)
        done = {r["key"]: r for r in prev}
    todo = [p for p in panel if p["key"] not in done]
    if limit:
        todo = todo[:limit]
    header = {"type": "run", "month": month, "tool": f"citation-rot {__version__}", "user_agent": UA,
              "panel_size": len(panel), "delay_s": delay, "timeout_s": timeout, "workers": workers}
    limiter = HostLimiter(delay)
    robots = Robots(limiter, timeout)
    lock, n = threading.Lock(), 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if resume and path.exists() else "w", encoding="utf-8", newline="\n") as f:
        if not (resume and path.stat().st_size):
            store.append_jsonl(f, header)

        def work(item):
            rec = check_url(item["url"], limiter, robots, timeout)
            rec.update(key=item["key"], host=item["host"], engines=item.get("engines", []),
                       first_cited=item.get("first_cited"), cohort=item.get("cohort"))
            return rec

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(work, it) for it in interleave(todo)]
            for fut in as_completed(futs):
                rec = fut.result()
                with lock:
                    store.append_jsonl(f, rec)
                    n += 1
                    if n % 50 == 0 or n == len(todo):
                        log(f"checked {n}/{len(todo)}")
    _, recs = store.load_run(month)
    order = {p["key"]: i for i, p in enumerate(panel)}
    recs.sort(key=lambda r: order.get(r["key"], 1 << 30))
    store.write_jsonl(path, [header] + recs)
    return recs
