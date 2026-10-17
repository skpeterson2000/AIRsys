"""The editor's live dots and open-port marks agree with the check.

The editor works out junctions, open ports and loose line ends in
JavaScript as you draw (static/geometry.js), and the check works them out
in Python (schematic.py). If the two disagreed, the sheet would show a
port as joined that the check calls open, or the other way about. This
runs both on the same drawings and compares. It needs node; without it,
it says so and fails, rather than passing having checked nothing.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

from _check import check, finish

from airsys import library, schematic

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
if not NODE:
    print("FAIL node is not on PATH: install Node.js to run this test")
    sys.exit(1)

RUNNER = """
const G = require(process.argv[1]);
let input = "";
process.stdin.on("data", c => input += c);
process.stdin.on("end", () => {
  const {doc, symbols} = JSON.parse(input);
  const lo = G.loose(doc, symbols);
  console.log(JSON.stringify({
    junctions: G.junctions(doc, symbols),
    openPorts: lo.openPorts.map(p => p.xy),
    openEnds: lo.openEnds,
  }));
});
"""


def js(doc):
    out = subprocess.run([NODE, "-e", RUNNER, str(ROOT / "airsys" / "static" / "geometry.js")],
                         input=json.dumps({"doc": doc, "symbols": library.BY_ID}),
                         capture_output=True, text=True, timeout=60)
    if out.returncode:
        raise SystemExit(out.stderr)
    return json.loads(out.stdout)


def py(doc):
    r = schematic.analyze(doc, library.BY_ID)
    ports = [e["at"] for e in r["erc"] if "not connected" in e["msg"] or " is open " in e["msg"]]
    ends = [e["at"] for e in r["erc"] if "line ends" in e["msg"]]
    return {"junctions": r["junctions"], "openPorts": ports, "openEnds": ends}


def norm(result):
    return {k: sorted([round(a, 2), round(b, 2)] for a, b in v) for k, v in result.items()}


def doc(parts=(), wires=(), labels=()):
    d = schematic.new_document()
    for i, (sym, x, y, rot, mirror) in enumerate(parts):
        d["parts"].append({"id": "p%d" % i, "sym": sym, "ref": "X%d" % i, "value": "",
                           "x": x, "y": y, "rot": rot, "mirror": mirror, "fields": {}})
    for i, pts in enumerate(wires):
        d["wires"].append({"id": "w%d" % i, "pts": [list(p) for p in pts], "kind": "work"})
    for i, (x, y, t) in enumerate(labels):
        d["labels"].append({"id": "l%d" % i, "x": x, "y": y, "text": t, "rot": 0})
    return d


cases = {
    "the shipped example": json.loads(
        (ROOT / "airsys" / "examples" / "Door cylinder.airsys.json").read_text()),
    "a T and a crossing": doc(
        parts=[("filter", 0, 0, 0, False), ("filter", 100, 0, 0, False),
               ("gauge", 50, 60, 0, False), ("gauge", 150, -100, 0, False)],
        wires=[[(20, 0), (80, 0)], [(50, 0), (50, 80)], [(150, -80), (150, 50)],
               [(120, 20), (200, 20)]]),
    "turned and mirrored valves, one loose line": doc(
        parts=[("valve52_solenoid", 200, 200, 1, False), ("valve32_pilot", 400, 200, 3, True),
               ("silencer", 400, 400, 2, False)],
        wires=[[(230, 210), (300, 210), (300, 300)]]),
    "a wire running through a port, ports touching, labels": doc(
        parts=[("gauge", 0, 0, 0, False), ("silencer", 100, 40, 0, False),
               ("plug", 100, 20, 0, False), ("filter", 300, 0, 0, False)],
        wires=[[(-40, 20), (60, 20)], [(280, 0), (240, 0)]],
        labels=[(-40, 20, "A"), (240, 0, "A")]),
}
for name, d in cases.items():
    a, b = norm(js(d)), norm(py(d))
    for key in ("junctions", "openPorts", "openEnds"):
        check("%s: %s agree" % (name, key), a[key], b[key])

finish()
