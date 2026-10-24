"""Small local ThinkLens server. Python standard library only."""
import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
import ai_engine

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 3_000_000
MAX_TEXT = 12_000


class ImportErrorMessage(ValueError):
    pass


def public_target(url):
    try:
        parts = urlsplit(url)
        if parts.scheme not in ("https", "http") or not parts.hostname:
            raise ValueError()
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            raise ValueError()
        if any(ord(c) < 33 for c in url) or len(url) > 4096:
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii")
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except (ValueError, UnicodeError):
        raise ImportErrorMessage("Enter a public http:// or https:// article URL without login details or a custom port.")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ImportErrorMessage("That website could not be found. Check the link and try again.")
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ImportErrorMessage("Use a public website URL. Local and private network addresses cannot be imported.")
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))
    return parts, host, port, addresses[0][4][0], normalized


def fetch_page(url):
    deadline = time.monotonic() + 24
    for _ in range(5):
        parts, host, port, address, url = public_target(url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ImportErrorMessage("The website took too long to respond. Try pasting the article text instead.")
        timeout = min(8, remaining)
        connection = (http.client.HTTPSConnection(host, port, timeout=timeout, context=ssl.create_default_context())
                      if parts.scheme == "https" else http.client.HTTPConnection(host, port, timeout=timeout))
        # Pin the validated public IP while retaining hostname verification and SNI for HTTPS.
        connection._create_connection = lambda *args, **kwargs: socket.create_connection((address, port), timeout)
        try:
            target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            connection.request("GET", target, headers={
                "User-Agent": "ThinkLens-Demo/1.0 (reader-requested article import)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.5",
                "Accept-Encoding": "identity",
            })
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ImportErrorMessage("The website returned an incomplete redirect.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ImportErrorMessage(f"The website did not allow this import (HTTP {response.status}). Open the article and paste its text instead.")
            kind = response.getheader("Content-Type", "").split(";")[0].strip().lower()
            if kind not in ("text/html", "application/xhtml+xml", "text/plain"):
                raise ImportErrorMessage("This link is not a readable web article. PDF, image, and video links are not supported.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ImportErrorMessage("This website uses an unsupported response format. Paste the article text instead.")
            chunks, size = [], 0
            while size <= MAX_BYTES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ImportErrorMessage("The article download timed out. Try pasting the text instead.")
                if connection.sock:
                    connection.sock.settimeout(min(8, remaining))
                chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size > MAX_BYTES:
                raise ImportErrorMessage("This page is too large to import. Paste an excerpt instead.")
            encoding = response.headers.get_content_charset() or "utf-8"
            try:
                content = b"".join(chunks).decode(encoding, errors="replace")
            except LookupError:
                content = b"".join(chunks).decode("utf-8", errors="replace")
            return content, kind, url
        finally:
            connection.close()
    raise ImportErrorMessage("This link redirects too many times. Try the final article URL.")


class ArticleParser(HTMLParser):
    """Extract visible paragraph text, preferring article/main elements."""
    SKIP = {"script", "style", "nav", "footer", "header", "aside", "form", "button", "noscript", "svg", "template"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
    BLOCK = {"p", "h1", "h2", "h3", "li", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []
        self.pending = []
        self.pending_scope = "body"
        self.title_parts = []
        self.og_title = ""

    def scope(self):
        tags = [tag for tag, _ in self.stack]
        return "article" if "article" in tags else "main" if "main" in tags else "body"

    def flush(self):
        text = re.sub(r"\s+", " ", "".join(self.pending)).strip()
        if text:
            self.blocks.append((self.pending_scope, text))
        self.pending = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property") == "og:title":
            self.og_title = attrs.get("content", "")
        skipped = any(skip for _, skip in self.stack) or tag in self.SKIP or "hidden" in attrs or attrs.get("aria-hidden") == "true"
        if tag in self.BLOCK and not skipped:
            self.flush()
            self.pending_scope = self.scope()
        if tag == "br" and not skipped:
            self.pending.append(" ")
        if tag not in self.VOID:
            self.stack.append((tag, skipped))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self.BLOCK and not any(skip for _, skip in self.stack):
            self.flush()
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if any(skip for _, skip in self.stack):
            return
        tags = [tag for tag, _ in self.stack]
        if "title" in tags:
            self.title_parts.append(data)
        if any(tag in self.BLOCK for tag in tags):
            if not self.pending:
                self.pending_scope = self.scope()
            self.pending.append(data)

    def result(self):
        self.flush()
        # A short article region may be only a teaser; extraction never bypasses access controls.
        scope = next((s for s in ("article", "main", "body") if sum(len(t) for k, t in self.blocks if k == s) >= 160), "body")
        texts = [t for k, t in self.blocks if k == scope]
        return re.sub(r"\s+", " ", self.og_title or "".join(self.title_parts)).strip()[:300], "\n\n".join(texts)


def import_article(url):
    content, kind, final_url = fetch_page(url)
    if kind == "text/plain":
        title, text = "Imported text", content.strip()
    else:
        parser = ArticleParser()
        parser.feed(content)
        title, text = parser.result()
    if len(text) < 160:
        raise ImportErrorMessage("Not enough readable article text was found. This page may require JavaScript, a subscription, or sign-in. Paste its text instead.")
    # Match browser textarea/JavaScript UTF-16 length, including emoji.
    truncated = len(text.encode("utf-16-le")) // 2 > MAX_TEXT
    if truncated:
        text = text.encode("utf-16-le")[:MAX_TEXT * 2].decode("utf-16-le", errors="ignore")
        # Prefer a word boundary so the excerpt does not end in the middle of a word.
        text = text.rsplit(" ", 1)[0]
    return {"title": title or "Imported article", "url": final_url, "text": text, "truncated": truncated}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Do not log URLs or submitted material.

    def send_data(self, status, content, kind="application/json; charset=utf-8"):
        data = json.dumps(content, ensure_ascii=False).encode() if isinstance(content, dict) else content
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765"):
            return self.send_data(403, {"error": "Use the local ThinkLens address."})
        if urlsplit(self.path).path in ("/", "/ThinkLens.html"):
            return self.send_data(200, (ROOT / "ThinkLens.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/config":
            return self.send_data(200, ai_engine.connection_status())
        self.send_data(404, {"error": "Not found"})

    def do_POST(self):
        if self.headers.get("Host") not in ("127.0.0.1:8765", "localhost:8765"):
            return self.send_data(403, {"error": "Use the local ThinkLens address."})
        if self.headers.get("Origin") not in ("http://127.0.0.1:8765", "http://localhost:8765"):
            return self.send_data(403, {"error": "Use the local ThinkLens page for imports and analysis."})
        if self.path not in ("/api/import", "/api/analyze"):
            return self.send_data(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= (100000 if self.path == "/api/analyze" else 8192):
                raise ImportErrorMessage("The request is too large or missing.")
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                raise ImportErrorMessage("Send a JSON article import request.")
            self.connection.settimeout(10)
            request = json.loads(self.rfile.read(length))
            if self.path == "/api/analyze":
                if not isinstance(request, dict):
                    raise ImportErrorMessage("Enter text to analyze.")
                return self.send_data(200, ai_engine.analyze(request.get("text")))
            if not isinstance(request, dict) or not isinstance(request.get("url"), str):
                raise ImportErrorMessage("Enter an article URL.")
            self.send_data(200, import_article(request["url"].strip()))
        except ai_engine.AIError as exc:
            self.send_data(exc.status, {"error": str(exc)})
        except ImportErrorMessage as exc:
            self.send_data(400, {"error": str(exc)})
        except (socket.timeout, TimeoutError):
            self.send_data(504, {"error": "The website took too long to respond. Paste the article text instead."})
        except (OSError, http.client.HTTPException, UnicodeError):
            self.send_data(502, {"error": "The website could not be reached securely. Check the link or paste its article text."})
        except (ValueError, TypeError):
            self.send_data(400, {"error": "The import request was invalid. Check the article URL."})


if __name__ == "__main__":
    print("ThinkLens: http://127.0.0.1:8765/ThinkLens.html", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
