"""The panel: the fixed set of URLs re-checked every month.

A decay rate only means something if the same URLs are checked each time, so the panel is
frozen when it is built and only ever extended with a new, labelled cohort.

The sample is stratified by engine family with equal quotas, because one engine returns far more
URLs than the others and a plain random sample would say almost nothing about the rest. The
headline figure is therefore not proportional to how many URLs each engine cites. Quote the
per-engine rows.
"""
import random
from collections import Counter, defaultdict


def stratum(seed):
    e = seed.get("engines") or []
    return e[0] if len(e) == 1 else ("multi" if e else "unknown")


def build(seeds, size, per_host=25, seed=1, cohort=None, exclude_keys=(), stratify=True):
    """Deterministic random sample of seeds, at most `per_host` per host, equal quotas per stratum.

    The same seeds and arguments always give the same panel, so the sample can be audited.
    Quota a stratum cannot fill is given to the others.
    """
    skip = set(exclude_keys)
    pool = sorted((s for s in seeds if s["key"] not in skip), key=lambda s: s["key"])
    rng = random.Random(seed)
    rng.shuffle(pool)
    groups = defaultdict(list)
    for s in pool:
        groups[stratum(s) if stratify else "all"].append(s)
    per, taken = Counter(), {g: [] for g in groups}
    cursor = {g: 0 for g in groups}

    def take(g, n):
        got = 0
        while got < n and cursor[g] < len(groups[g]):
            s = groups[g][cursor[g]]
            cursor[g] += 1
            if per[s["host"]] >= per_host:
                continue
            per[s["host"]] += 1
            taken[g].append(s)
            got += 1
        return got

    names = sorted(groups)
    quota = size // len(names) if names else 0
    short = size - quota * len(names)
    for g in names:
        short += quota - take(g, quota)
    while short > 0:  # hand unused quota to strata that still have URLs
        gave = 0
        for g in names:
            if short <= 0:
                break
            got = take(g, 1)
            short -= got
            gave += got
        if not gave:
            break
    out = []
    for g in names:
        for s in taken[g]:
            out.append({"url": s["url"], "key": s["key"], "host": s["host"], "engines": s.get("engines", []),
                        "first_cited": s.get("first_cited"), "source": s.get("source"), "cohort": cohort})
    rng2 = random.Random(seed + 1)
    rng2.shuffle(out)
    return out
