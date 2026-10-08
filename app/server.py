"""Tiny local HTTP server so the player can stream and seek meeting audio."""
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote

from . import store

ROUTE = re.compile(r"/audio/([\w-]+)/([\w.-]+)")
RANGE = re.compile(r"bytes=(\d*)-(\d*)")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        route = ROUTE.fullmatch(unquote(self.path.split("?")[0]))
        try:
            path = store.folder(route.group(1)) / route.group(2)
            size = path.stat().st_size
            if not path.is_file():
                raise OSError
        except (AttributeError, ValueError, OSError):
            self.send_error(404)
            return
        start, end = 0, size - 1
        wanted = RANGE.fullmatch(self.headers.get("Range", ""))
        if wanted and (wanted.group(1) or wanted.group(2)):
            if wanted.group(1):
                start = int(wanted.group(1))
                end = min(int(wanted.group(2)), size - 1) if wanted.group(2) else size - 1
            else:
                start = max(0, size - int(wanted.group(2)))
            if start > end:
                self.send_error(416)
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                left = end - start + 1
                while left > 0:
                    block = handle.read(min(65536, left))
                    if not block:
                        break
                    self.wfile.write(block)
                    left -= len(block)
        except OSError:
            pass

    def log_message(self, *args):
        pass


def start():
    """Start serving on a free localhost port and return that port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server.server_address[1]
