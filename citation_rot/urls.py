"""URL handling: extraction, cleaning, equivalence keys and the seed privacy filter."""
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit, unquote

TRACKING_PARAMS = {"gclid", "fbclid", "msclkid", "mc_cid", "mc_eid", "ref_src", "igshid", "yclid"}
_LINK_RE = re.compile(r"\]\((https?://[^)\s]+)\)")
_BARE_RE = re.compile(r"https?://[^\s<>()\[\]\"']+")

# Hosts whose cited pages are usually about a private person, a login wall or a redirect token.
# Seeds on these hosts are dropped at harvest time and never stored.
EXCLUDED_HOST_SUFFIXES = (
    "linkedin.com", "facebook.com", "fb.com", "instagram.com", "x.com", "twitter.com", "tiktok.com",
    "vk.com", "t.me", "telegram.me", "threads.net", "snapchat.com", "theorg.com",
    "vertexaisearch.cloud.google.com", "famousbirthdays.com", "bsky.app", "bsky.social", "blueskystarterpack.com",
    "about.me", "linktr.ee", "beacons.ai", "gravatar.com",
)
# Pages whose first two path segments name a person's profile or author page. Dropped and never stored.
_PROFILE_SEGMENTS = {"profile", "profiles", "people", "person", "author", "authors", "user", "users", "member",
                     "members", "u", "in", "athlete", "athletes", "pub", "whois"}
_SENSITIVE_HOST_WORDS = ("porn", "xxx", "sex", "adult", "nude", "escort", "hentai", "onlyfans")


def is_tracking_param(name):
    n = name.lower()
    return n.startswith("utm_") or n in TRACKING_PARAMS


def clean_url(url):
    """Strip whitespace, trailing punctuation, fragment and tracking parameters. Returns None if unusable."""
    url = url.strip().rstrip(".,;:!?'\"")
    try:
        p = urlsplit(url)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.hostname:
        return None
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not is_tracking_param(k)]
    netloc = p.netloc
    return urlunsplit((p.scheme.lower(), netloc.lower() if "@" not in netloc else netloc, p.path or "/", urlencode(q), ""))


def host_of(url):
    return (urlsplit(url).hostname or "").lower()


def base_host(host):
    return host[4:] if host.startswith("www.") else host


def canonical_key(url):
    """Equivalence key: two URLs with the same key count as the same page (scheme, www, port,
    trailing slash, fragment and tracking parameters are ignored)."""
    p = urlsplit(url)
    host = base_host((p.hostname or "").lower())
    path = unquote(p.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    q = sorted((k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not is_tracking_param(k))
    return host + path + ("?" + urlencode(q) if q else "")


def same_page(a, b):
    return canonical_key(a) == canonical_key(b)


def is_home(url):
    p = urlsplit(url)
    return (p.path in ("", "/")) and not p.query


def extract_links(text):
    """URLs in markdown links first, then bare URLs, in order, without duplicates."""
    out, seen = [], set()
    for m in list(_LINK_RE.finditer(text or "")) + list(_BARE_RE.finditer(text or "")):
        u = m.group(1) if m.lastindex else m.group(0)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def excluded_reason(url):
    """Why a URL must not be stored as a seed, or None."""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if not host or "." not in host or host.replace(".", "").isdigit() or ":" in host:
        return "not a public hostname"
    if p.username or p.password or "@" in p.netloc:
        return "credentials in URL"
    for s in EXCLUDED_HOST_SUFFIXES:
        if host == s or host.endswith("." + s):
            return "excluded host (personal profile, login wall or redirect token)"
    segs = [s for s in unquote(p.path).lower().split("/") if s]
    if any(s in _PROFILE_SEGMENTS for s in segs[:2]) or (segs and segs[0].startswith("@") and len(segs) == 1):
        return "personal profile or author page"
    if re.search(r"/wiki/(user|user_talk|special):", unquote(p.path).lower()):
        return "personal profile or author page"
    if any(w in host for w in _SENSITIVE_HOST_WORDS):
        return "sensitive host name"
    if re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", unquote(p.path + "?" + p.query)):
        return "email address in URL"
    return None
