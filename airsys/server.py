"""The web side: the editor page, the symbol library, and the projects.

Standard library only. Projects are files in one directory, one
<name>.airsys.json each, so they can be copied, backed up and put under
version control like any other drawing. A save goes to a temporary file
that then replaces the old one, so a crash mid-save never leaves half a
drawing, and the drawing before it is kept as <name>.airsys.json.bak.
"""

import json
import logging
import mimetypes
import os
import re
import shutil
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import __version__, library, schematic

log = logging.getLogger("airsys.server")

HERE = Path(__file__).resolve().parent
STATIC = HERE / "static"
EXAMPLES = HERE / "examples"
SUFFIX = ".airsys.json"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$")
MAX_BODY = 5 * 1024 * 1024


def valid_name(name):
    return bool(NAME.match(name)) and not name.endswith(".")


def stamp(path):
    """What the editor sends back on save, so a save cannot quietly overwrite
    a change made in another window since this one opened the drawing."""
    return str(path.stat().st_mtime_ns)


class AirServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, projects):
        super().__init__(address, Handler)
        self.projects = Path(projects)
        self.projects.mkdir(parents=True, exist_ok=True)

    def listing(self, folder):
        out = []
        for f in sorted(folder.glob("*" + SUFFIX), key=lambda f: f.name.lower()):
            st = f.stat()
            out.append({"name": f.name[:-len(SUFFIX)], "modified": st.st_mtime,
                        "size": st.st_size})
        return out

    def save(self, name, doc, base):
        target = self.projects / (name + SUFFIX)
        if base is not None and target.exists() and stamp(target) != base:
            return None
        data = json.dumps(doc, indent=1, ensure_ascii=False).encode("utf-8") + b"\n"
        fd, tmp = tempfile.mkstemp(prefix=".save-", dir=self.projects)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if target.exists():
                shutil.copy2(target, target.with_name(target.name + ".bak"))
            os.replace(tmp, target)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        log.info("saved %s (%d parts, %d lines)", target.name, len(doc["parts"]),
                 len(doc["wires"]))
        return stamp(target)


class Handler(BaseHTTPRequestHandler):
    server_version = "AIRsys/" + __version__

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.address_string(), fmt % args)

    # --- routing ---

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/library":
            return self._json(dict(library.as_json(), sheets=schematic.SHEETS))
        if path == "/api/new":
            return self._json(schematic.new_document())
        if path == "/api/projects":
            return self._json({"projects": self.server.listing(self.server.projects),
                               "examples": self.server.listing(EXAMPLES)})
        for prefix, folder in (("/api/projects/", self.server.projects),
                               ("/api/examples/", EXAMPLES)):
            if path.startswith(prefix):
                return self._open(folder, unquote(path[len(prefix):]))
        if path == "/":
            path = "/index.html"
        return self._static(path)

    def do_PUT(self):
        path = self.path.split("?", 1)[0]
        if not path.startswith("/api/projects/"):
            return self._fail(404, "nothing to save here")
        name = unquote(path[len("/api/projects/"):])
        if not valid_name(name):
            return self._fail(400, "a name is letters, numbers, spaces, dots, dashes "
                              "and underscores, up to 64")
        doc = self._body()
        if doc is None:
            return
        problem = schematic.validate(doc)
        if problem:
            return self._fail(400, "not saved: " + problem)
        force = "force=1" in self.path.partition("?")[2].split("&")
        base = None if force else self.headers.get("X-AIRsys-Base")
        new = self.server.save(name, doc, base or None)
        if new is None:
            return self._fail(409, "%s was changed in another window since this one "
                              "opened it" % name)
        return self._json({"saved": name, "base": new})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/api/check":
            return self._fail(404, "no such action")
        doc = self._body()
        if doc is None:
            return
        problem = schematic.validate(doc)
        if problem:
            return self._fail(400, problem)
        result = schematic.analyze(doc, library.BY_ID)
        result["bom_csv"] = schematic.bom_csv(result["bom"])
        result["netlist"] = schematic.netlist_text(doc, result["nets"])
        return self._json(result)

    # --- helpers ---

    def _open(self, folder, name):
        if not valid_name(name):
            return self._fail(404, "no such drawing")
        target = folder / (name + SUFFIX)
        if not target.is_file():
            return self._fail(404, "no drawing called %s" % name)
        try:
            doc = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            log.warning("could not read %s: %s", target, e)
            return self._fail(500, "%s could not be read: %s" % (name, e))
        problem = schematic.validate(doc)
        if problem:
            log.warning("%s is not a usable drawing: %s", target, problem)
            return self._fail(500, "%s is damaged: %s" % (name, problem))
        return self._json({"name": name, "doc": doc, "base": stamp(target)})

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._fail(411, "no length")
            return None
        if n > MAX_BODY:
            self._fail(413, "drawing is larger than 5 MB")
            return None
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except ValueError:
            self._fail(400, "not JSON")
            return None

    def _json(self, obj, code=200):
        body = json.dumps(obj, separators=(",", ":")).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, code, msg):
        self._json({"error": msg}, code)

    def _static(self, path):
        target = (STATIC / unquote(path).lstrip("/")).resolve()
        if not target.is_relative_to(STATIC) or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
