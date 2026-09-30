"""Pull the title and visible text out of an HTML page, and spot soft 404s."""
import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript", "template", "svg", "nav", "footer", "header", "aside", "form", "iframe"}
_PHRASES = (r"page not found|not found|no longer available|has been removed|has been deleted|"
            r"doesn'?t exist|does not exist|page (is )?unavailable|content unavailable|nothing here|"
            r"we couldn'?t find|could not be found|couldn'?t be found")
_SOFT_404 = re.compile(r"(\b404\b|" + _PHRASES + ")", re.I)
_HEADING_404 = re.compile(r"(^\W*(error\W*)?404\b|\b404\b.{0,12}not found|" + _PHRASES + ")", re.I)


class _Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.h1, self.text = "", "", []
        self._skip = 0
        self._in = None

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self._skip += 1
        elif tag in ("title", "h1") and self._in is None:
            self._in = tag

    def handle_endtag(self, tag):
        if tag in _SKIP and self._skip:
            self._skip -= 1
        elif tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "title":
            self.title += data
        elif self._in == "h1" and len(self.h1) < 300:
            self.h1 += data
        if not self._skip:
            self.text.append(data)


def extract(html):
    """Return (title, h1, text) with whitespace collapsed."""
    p = _Extract()
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed markup: use what was parsed
        pass

    def clean(s):
        return re.sub(r"\s+", " ", s).strip()

    return clean(p.title), clean(p.h1), clean(" ".join(p.text))


def looks_like_404(title, h1, text):
    """A 200 page that says it is missing: the marker is in the title or H1, or the page is nearly empty."""
    if _HEADING_404.search(title) or _HEADING_404.search(h1):
        return True
    return len(text) < 400 and bool(_SOFT_404.search(text))
