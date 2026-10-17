"""Drawings are saved whole, opened as saved, and never lost by a stale window.

The server runs on a loopback port with its projects in a temporary
directory. A save from a window that opened the drawing before another
window saved it must be refused, not quietly win; a name that could leave
the projects directory must be refused; a damaged request must not write
anything.
"""

import json
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

from _check import check, finish

from airsys import schematic, server

tmp = Path(tempfile.mkdtemp(prefix="airsys-test-"))
httpd = server.AirServer(("127.0.0.1", 0), tmp)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]


def call(method, path, body=None, headers=None):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req) as res:
            raw = res.read()
            is_json = res.headers.get_content_type() == "application/json"
            return res.status, (json.loads(raw) if is_json else raw)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw


code, lib = call("GET", "/api/library")
check("the library is served with the sheet sizes", (code, "A4" in lib["sheets"]), (200, True))
code, page = call("GET", "/")
check("the editor page is served", (code, b"editor.js" in page), (200, True))
code, _ = call("GET", "/../server.py")
check("nothing outside the page's files is served", code, 404)

code, listing = call("GET", "/api/projects")
check("the example is listed", [e["name"] for e in listing["examples"]], ["Door cylinder"])
check("no drawings yet", listing["projects"], [])

d = schematic.new_document()
d["title_block"]["title"] = "Shop air"
d["parts"].append({"id": "p1", "sym": "filter", "ref": "Z1", "value": "", "x": 100, "y": 100,
                   "rot": 0, "mirror": False, "fields": {"Supplier": "Acme"}})
code, saved = call("PUT", "/api/projects/Shop%20air", d)
check("a save is accepted", (code, saved["saved"]), (200, "Shop air"))
check("it is a file in the projects directory", (tmp / "Shop air.airsys.json").is_file(), True)
code, opened = call("GET", "/api/projects/Shop%20air")
check("it opens as it was saved", opened["doc"], d)
base = opened["base"]

d2 = json.loads(json.dumps(d))
d2["title_block"]["rev"] = "B"
code, r = call("PUT", "/api/projects/Shop%20air", d2, {"X-AIRsys-Base": base})
check("a save from the window that opened it goes through", code, 200)
check("the drawing before it is kept", (tmp / "Shop air.airsys.json.bak").is_file(), True)
d3 = json.loads(json.dumps(d))
d3["title_block"]["rev"] = "C"
code, r = call("PUT", "/api/projects/Shop%20air", d3, {"X-AIRsys-Base": base})
check("a save from a window that is behind is refused", code, 409)
code, opened = call("GET", "/api/projects/Shop%20air")
check("and the newer drawing is still there", opened["doc"]["title_block"]["rev"], "B")
code, r = call("PUT", "/api/projects/Shop%20air?force=1", d3, {"X-AIRsys-Base": base})
check("saving over it on purpose works", code, 200)

code, r = call("PUT", "/api/projects/..%2Fescape", d)
check("a name that leaves the directory is refused", code, 400)
check("and nothing is written outside", (tmp.parent / "escape.airsys.json").exists(), False)
code, r = call("PUT", "/api/projects/broken", b"{not json", {"Content-Type": "application/json"})
check("a request that is not JSON is refused", code, 400)
code, r = call("PUT", "/api/projects/broken", {"format": "something else"})
check("a document that is not a drawing is refused, saying why",
      (code, r["error"]), (400, "not saved: not an AIRsys schematic"))
check("and nothing is written", (tmp / "broken.airsys.json").exists(), False)
check("no half-written files are left behind", sorted(p.name for p in tmp.iterdir()),
      ["Shop air.airsys.json", "Shop air.airsys.json.bak"])

code, r = call("POST", "/api/check", d)
check("the check runs", code, 200)
check("and brings the BOM as CSV", r["bom_csv"].splitlines()[0], "Qty,References,Part,Value,Supplier")
check("and the netlist", r["netlist"].splitlines()[1], "# title: Shop air")

code, ex = call("GET", "/api/examples/Door%20cylinder")
check("the example opens", (code, ex["doc"]["format"]), (200, "airsys-schematic"))
code, r = call("GET", "/api/projects/nothing-here")
check("a drawing that is not there is a 404 that says so",
      (code, r["error"]), (404, "no drawing called nothing-here"))

(tmp / "damaged.airsys.json").write_text("{\"format\": \"airsys-schematic\"")
code, r = call("GET", "/api/projects/damaged")
check("a damaged file is reported, not served", code, 500)

httpd.shutdown()
finish()
