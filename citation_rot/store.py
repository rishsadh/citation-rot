"""Files on disk. Everything is plain JSONL or CSV so a month's data diffs cleanly in git."""
import json
import os
import pathlib
from datetime import datetime, timezone


def root():
    """The working tree that holds seeds/, data/ and reports/. Run from the repo root, or set CITATION_ROT_HOME."""
    return pathlib.Path(os.environ.get("CITATION_ROT_HOME") or os.getcwd())


def month_now():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def read_jsonl(path):
    path = pathlib.Path(path)
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl(f, row):
    f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    f.flush()


def write_json(path, obj):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def seeds_dir():
    return root() / "seeds"


def panel_path():
    return root() / "data" / "panel.jsonl"


def run_path(month):
    return root() / "data" / "runs" / f"{month}.jsonl"


def load_seeds(directory=None):
    """All seed files merged by canonical key. Earliest first_cited wins; engines are unioned."""
    merged = {}
    for p in sorted(pathlib.Path(directory or seeds_dir()).glob("*.jsonl")):
        for s in read_jsonl(p):
            cur = merged.get(s["key"])
            if cur is None:
                merged[s["key"]] = dict(s)
                continue
            cur["first_cited"] = min(cur.get("first_cited") or "9999", s.get("first_cited") or "9999")
            cur["engines"] = sorted(set(cur.get("engines", [])) | set(s.get("engines", [])))
    return [merged[k] for k in sorted(merged)]


def load_run(month):
    """Returns (header, records) for a month's run, or (None, [])."""
    rows = read_jsonl(run_path(month))
    if not rows:
        return None, []
    return (rows[0] if rows[0].get("type") == "run" else None), [r for r in rows if r.get("type") != "run"]


def list_runs():
    d = root() / "data" / "runs"
    return sorted(p.stem for p in d.glob("*.jsonl")) if d.exists() else []


def previous_month(month, months=None):
    months = months if months is not None else list_runs()
    earlier = [m for m in months if m < month]
    return earlier[-1] if earlier else None
