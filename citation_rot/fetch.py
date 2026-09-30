"""Polite fetching: robots.txt, per-host delay, manual redirects, and classification."""
import http.client
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from . import __version__
from .page import extract, looks_like_404
from .simhash import simhash
from .urls import host_of, is_home, same_page

UA = f"citation-rot/{__version__} (+https://github.com/rishsadh/citation-rot; link-status research; honours robots.txt)"
MAX_BYTES = 262144
MAX_HOPS = 5
BLOCKED_CODES = {401, 403, 407, 429, 451, 999}
REDIRECTS = (301, 302, 303, 307, 308)

# Every outcome is exactly one of these.
CLASSES = ("live", "moved", "soft-404", "dead", "unreachable", "server-error", "blocked", "other")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def http_get(url, timeout=15, max_bytes=MAX_BYTES):
    """One GET with no redirect following. Returns (code, headers, body_bytes, error_reason)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.8,*/*;q=0.5",
        "Accept-Encoding": "identity", "Accept-Language": "en"})
    try:
        r = urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout)
        body = r.read(max_bytes)
        return r.status, r.headers, body, None
    except urllib.error.HTTPError as e:
        try:
            body = e.read(max_bytes)
        except Exception:
            body = b""
        return e.code, e.headers, body, None
    except urllib.error.URLError as e:
        return None, None, b"", reason_of(e.reason)
    except (socket.timeout, TimeoutError):
        return None, None, b"", "timeout"
    except ssl.SSLError as e:
        return None, None, b"", f"tls: {e.reason or e}"
    except (http.client.HTTPException, ConnectionError, OSError, ValueError) as e:
        return None, None, b"", type(e).__name__


def reason_of(reason):
    if isinstance(reason, socket.gaierror):
        return "dns"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(reason, ssl.SSLError):
        return f"tls: {getattr(reason, 'reason', None) or reason}"
    if isinstance(reason, ConnectionRefusedError):
        return "connection-refused"
    if isinstance(reason, ConnectionResetError):
        return "connection-reset"
    s = str(reason)
    if "CERTIFICATE" in s.upper():
        return "tls: certificate"
    if "getaddrinfo" in s or "Name or service" in s:
        return "dns"
    return s[:80] or "network-error"


class HostLimiter:
    """At most one request per host every `delay` seconds, across threads."""

    def __init__(self, delay=2.0):
        self.delay = delay
        self._next = {}
        self._lock = threading.Lock()

    def wait(self, host, delay=None):
        d = self.delay if delay is None else max(self.delay, delay)
        with self._lock:
            now = time.monotonic()
            at = max(now, self._next.get(host, 0.0))
            self._next[host] = at + d
        if at > now:
            time.sleep(at - now)


class Robots:
    """Cached robots.txt per scheme and host, following RFC 9309: 4xx means allowed, 5xx means not allowed."""

    def __init__(self, limiter, timeout=15):
        self.limiter, self.timeout = limiter, timeout
        self._cache = {}
        self._lock = threading.Lock()

    def _load(self, scheme, netloc):
        url = f"{scheme}://{netloc}/robots.txt"
        for _ in range(MAX_HOPS + 1):
            self.limiter.wait(urlsplit(url).netloc.lower())
            code, headers, body, err = http_get(url, self.timeout, 524288)
            if err:
                return ("error", err, None)
            if code in REDIRECTS and headers.get("Location"):
                url = urljoin(url, headers["Location"])
                continue
            if code and 200 <= code < 300:
                rp = RobotFileParser()
                rp.parse(body.decode("utf-8", "replace").splitlines())
                return ("ok", None, rp)
            if code and 400 <= code < 500:
                return ("allow-all", None, None)
            return ("unavailable", f"robots.txt returned {code}", None)
        return ("unavailable", "robots.txt redirect loop", None)

    def check(self, url):
        """Returns (verdict, detail, crawl_delay). verdict: allowed | disallowed | unavailable | error."""
        p = urlsplit(url)
        k = (p.scheme, p.netloc.lower())
        with self._lock:
            ent = self._cache.get(k)
            if ent is None:
                ent = self._cache[k] = {"lock": threading.Lock(), "val": None}
        with ent["lock"]:
            if ent["val"] is None:
                ent["val"] = self._load(*k)
        kind, detail, rp = ent["val"]
        if kind == "error":
            return "error", detail, None
        if kind == "unavailable":
            return "unavailable", detail, None
        if kind == "allow-all":
            return "allowed", None, None
        delay = rp.crawl_delay(UA) or rp.crawl_delay("*")
        ok = rp.can_fetch(UA, url)
        return ("allowed" if ok else "disallowed"), None, (min(float(delay), 30.0) if delay else None)


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def check_url(url, limiter, robots, timeout=15, retry=True):
    """Check one cited URL. Always returns a record whose `status` is in CLASSES."""
    t0 = time.monotonic()
    rec = {"url": url, "checked_at": _now(), "hops": []}
    try:
        _check(url, limiter, robots, timeout, rec)
        if retry and rec["status"] in ("unreachable", "server-error") and rec.get("reason") != "dns":
            time.sleep(3)
            first = rec["status"]
            rec = {"url": url, "checked_at": _now(), "hops": [], "retried": True}
            _check(url, limiter, robots, timeout, rec)
            rec["first_attempt"] = first
    except Exception as e:  # never let one URL kill a run
        rec.update(status="other", reason=f"checker error: {type(e).__name__}")
    rec["elapsed_ms"] = int((time.monotonic() - t0) * 1000)
    return rec


def _check(url, limiter, robots, timeout, rec):
    cur = url
    seen = {url}
    for hop in range(MAX_HOPS + 1):
        host = host_of(cur)
        verdict, detail, crawl_delay = robots.check(cur)
        if verdict == "disallowed":
            rec.update(status="blocked", reason="robots.txt disallows", final_url=cur)
            return
        if verdict == "unavailable":
            rec.update(status="blocked", reason=detail, final_url=cur)
            return
        if verdict == "error":
            rec.update(status="unreachable", reason=detail, final_url=cur)
            return
        limiter.wait(host, crawl_delay)
        code, headers, body, err = http_get(cur, timeout)
        if err:
            rec.update(status="unreachable", reason=err, final_url=cur)
            return
        rec["hops"].append(code)
        rec["code"] = code
        if code in REDIRECTS and headers.get("Location"):
            nxt = urljoin(cur, headers["Location"])
            if nxt in seen or hop == MAX_HOPS:
                rec.update(status="unreachable", reason="redirect loop" if nxt in seen else "too many redirects",
                           final_url=nxt)
                return
            if urlsplit(nxt).scheme not in ("http", "https"):
                rec.update(status="other", reason="redirect to non-http URL", final_url=nxt)
                return
            seen.add(nxt)
            cur = nxt
            continue
        rec["final_url"] = cur
        _classify_final(url, cur, code, headers, body, rec)
        return


def _classify_final(orig, final, code, headers, body, rec):
    ctype = (headers.get("Content-Type") or "").split(";")[0].strip().lower() if headers else ""
    rec["content_type"] = ctype
    if code in (404, 410):
        rec.update(status="dead", reason=f"HTTP {code}")
    elif code in BLOCKED_CODES:
        rec.update(status="blocked", reason=f"HTTP {code}")
    elif code >= 500:
        rec.update(status="server-error", reason=f"HTTP {code}")
    elif 400 <= code < 500:
        rec.update(status="other", reason=f"HTTP {code}")
    elif 200 <= code < 300:
        _classify_ok(orig, final, headers, body, ctype, rec)
    else:
        rec.update(status="other", reason=f"HTTP {code}")


def _charset(headers):
    m = re.search(r"charset=([\w-]+)", (headers.get("Content-Type") or "") if headers else "", re.I)
    return m.group(1) if m else "utf-8"


def _classify_ok(orig, final, headers, body, ctype, rec):
    if headers:
        for k, name in (("ETag", "etag"), ("Last-Modified", "last_modified"), ("Content-Length", "content_length")):
            if headers.get(k):
                rec[name] = headers[k]
    if ctype in ("text/html", "application/xhtml+xml", "text/plain", ""):
        try:
            html = body.decode(_charset(headers), "replace")
        except LookupError:
            html = body.decode("utf-8", "replace")
        if ctype == "text/plain":
            title, h1, text = "", "", " ".join(html.split())
        else:
            title, h1, text = extract(html)
        rec.update(title=title[:200], text_len=len(text), simhash=f"{simhash(text):016x}" if text else None)
        if looks_like_404(title, h1, text):
            rec.update(status="soft-404", reason="HTTP 200 page says it is missing")
            return
    if not same_page(orig, final):
        rec.update(status="moved", reason="redirected to a different page")
        if is_home(final) and not is_home(orig):
            rec["to_home"] = True
    else:
        rec.update(status="live", reason="ok")
