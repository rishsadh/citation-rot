"""Host-specific checks for sites that answer 200 for a page that is gone.

YouTube is the most common host in cited URLs and it serves a normal 200 page for a removed or
private video, so a plain status check calls every dead video live. YouTube's public oEmbed
endpoint answers 404 for a video that is not there. robots.txt allows /oembed.
"""
import re
from urllib.parse import parse_qs, quote, urlsplit

_YT_HOSTS = {"www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com", "www.youtube-nocookie.com"}
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def youtube_id(url):
    """The 11 character video id in a YouTube video URL, or None (channels, playlists and searches are not videos)."""
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    vid = None
    if host == "youtu.be":
        vid = p.path.lstrip("/").split("/")[0]
    elif host in _YT_HOSTS:
        if p.path == "/watch":
            vid = (parse_qs(p.query).get("v") or [None])[0]
        else:
            m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", p.path)
            vid = m.group(2) if m else None
    return vid if vid and _ID.match(vid) else None


def oembed_url(vid):
    return "https://www.youtube.com/oembed?format=json&url=" + quote(f"https://www.youtube.com/watch?v={vid}", safe="")


def youtube_verdict(code):
    """Map an oEmbed status to (status, reason). status None means: keep the page check's answer."""
    if code == 200:
        return "live", "YouTube oEmbed 200"
    if code in (400, 404):
        return "dead", f"YouTube oEmbed {code}: video removed, or never existed"
    if code == 401:
        return "blocked", "YouTube oEmbed 401: private, restricted or embedding disabled, so not judged"
    return None, f"YouTube oEmbed {code}"
