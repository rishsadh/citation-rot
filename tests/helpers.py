"""A tiny local web server that behaves like the different ways a cited page can fail."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = "<html><head><title>{t}</title></head><body><nav>menu</nav><h1>{t}</h1><p>{body}</p></body></html>"
LONG = "This is a real article with enough words to be a page. " * 12


class Handler(BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *a):
        pass

    def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        Handler.hits.append(path)
        page = lambda t, b=LONG: PAGE.format(t=t, body=b).encode()
        if path == "/robots.txt":
            return self._send(200, b"User-agent: *\nDisallow: /private\n", "text/plain")
        if path == "/ok":
            return self._send(200, page("A good article"), headers={"ETag": '"v1"'})
        if path == "/ok-changed":
            return self._send(200, page("A good article", "Completely different words about other topics entirely. " * 14))
        if path == "/":
            return self._send(200, page("Home"))
        if path == "/gone":
            return self._send(404, page("Not Found"))
        if path == "/gone410":
            return self._send(410, b"gone")
        if path == "/moved":
            return self._send(301, headers={"Location": "/ok"})
        if path == "/tohome":
            return self._send(301, headers={"Location": "/"})
        if path == "/slash":
            return self._send(301, headers={"Location": "/slash/"})
        if path == "/slash/":
            return self._send(200, page("Slash page"))
        if path == "/soft":
            return self._send(200, page("Page not found", "Sorry."))
        if path == "/forbidden":
            return self._send(403, b"no")
        if path == "/ratelimited":
            return self._send(429, b"slow down")
        if path == "/err":
            return self._send(500, b"boom")
        if path == "/teapot":
            return self._send(418, b"tea")
        if path == "/loop":
            return self._send(302, headers={"Location": "/loop2"})
        if path == "/loop2":
            return self._send(302, headers={"Location": "/loop"})
        if path == "/slow":
            time.sleep(2)
            return self._send(200, page("Slow"))
        if path == "/private/secret":
            return self._send(200, page("Secret page"))
        if path == "/pdf":
            return self._send(200, b"%PDF-1.4 fake", "application/pdf", {"Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT"})
        self._send(404, page("Not Found"))


def serve():
    Handler.hits = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"
