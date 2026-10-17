"""What joins what, and what the check says about it.

The connection rules are KiCad's: a wire's end on another wire joins them,
wires that only cross do not, a port joins a wire through or ending on it,
labels with the same text join, and supplies with the same value join. The
check must find what would be wrong on the bench: an open port blowing
air, a line that goes nowhere, two parts with one number, and a supply
piped straight to an exhaust.
"""

import json
from pathlib import Path

from _check import check, finish

from airsys import library, schematic

S = library.BY_ID
HERE = Path(__file__).resolve().parent.parent


def doc(parts=(), wires=(), labels=()):
    d = schematic.new_document()
    for i, (sym, ref, x, y, *rest) in enumerate(parts):
        rot = rest[0] if rest else 0
        d["parts"].append({"id": "p%d" % i, "sym": sym, "ref": ref, "value": "",
                           "x": x, "y": y, "rot": rot, "mirror": False, "fields": {}})
    for i, pts in enumerate(wires):
        d["wires"].append({"id": "w%d" % i, "pts": [list(p) for p in pts], "kind": "work"})
    for i, (x, y, text) in enumerate(labels):
        d["labels"].append({"id": "l%d" % i, "x": x, "y": y, "text": text, "rot": 0})
    return d


def messages(result, level=None):
    return [e["msg"] for e in result["erc"] if level is None or e["level"] == level]


# --- placing ports ---
part = {"x": 100, "y": 200, "rot": 0, "mirror": False}
check("a port lands where the symbol puts it", schematic.transform(10, -30, part), (110, 170))
check("a quarter turn clockwise", schematic.transform(10, -30, dict(part, rot=1)), (130, 210))
check("a half turn", schematic.transform(10, -30, dict(part, rot=2)), (90, 230))
check("mirrored, then turned", schematic.transform(10, -30, dict(part, rot=1, mirror=True)),
      (130, 190))

# --- what joins ---
# two filters in a row, joined by a wire from 1's outlet to 2's inlet
d = doc(parts=[("filter", "Z1", 0, 0), ("filter", "Z2", 100, 0)],
        wires=[[(20, 0), (80, 0)]])
r = schematic.analyze(d, S)
check("a wire port to port makes one net",
      [n["members"] for n in r["nets"] if "Z1:2" in n["members"]], [["Z1:2", "Z2:1"]])

# a T: a wire ends on the middle of another
d = doc(parts=[("filter", "Z1", 0, 0), ("filter", "Z2", 100, 0), ("gauge", "S1", 50, 60)],
        wires=[[(20, 0), (80, 0)], [(50, 0), (50, 80)]])
r = schematic.analyze(d, S)
check("a wire ending on another wire's middle joins it",
      [n["members"] for n in r["nets"] if "S1:1" in n["members"]], [["S1:1", "Z1:2", "Z2:1"]])
check("and gets a junction dot", r["junctions"], [[50, 0]])

# crossing without a dot
d = doc(parts=[("filter", "Z1", 0, 0), ("filter", "Z2", 100, 0),
               ("gauge", "S1", 50, 60), ("gauge", "S2", 50, -100)],
        wires=[[(20, 0), (80, 0)], [(50, -80), (50, 80)]])
r = schematic.analyze(d, S)
check("wires that only cross do not join",
      sorted(n["members"] for n in r["nets"] if "S1:1" in n["members"]), [["S1:1", "S2:1"]])
check("and get no dot", r["junctions"], [])

# a label joins two wires that do not touch
d = doc(parts=[("filter", "Z1", 0, 0), ("filter", "Z2", 300, 0)],
        wires=[[(20, 0), (60, 0)], [(220, 0), (280, 0)]],
        labels=[(60, 0, "MAIN"), (220, 0, "MAIN")])
r = schematic.analyze(d, S)
check("labels with the same text are one net, named by the label",
      [(n["name"], n["members"]) for n in r["nets"] if n["name"] == "MAIN"],
      [("MAIN", ["Z1:2", "Z2:1"])])
check("a labelled wire end is not a loose end",
      [m for m in messages(r) if "line ends" in m], [])

# two supplies of the same value are one net
d = doc(parts=[("supply", "#S1", 0, 20), ("supply", "#S2", 200, 20),
               ("gauge", "S1", 0, -40), ("gauge", "S2", 200, -40)],
        wires=[[(0, 0), (0, -20)], [(200, 0), (200, -20)]])
for p in d["parts"][:2]:
    p["value"] = "6 bar"
r = schematic.analyze(d, S)
check("supplies with one value are one net, named by it",
      [(n["name"], n["members"]) for n in r["nets"]], [("6 bar", ["S1:1", "S2:1"])])

# --- the check ---
d = doc(parts=[("valve32_solenoid", "V1", 0, 0)])
r = schematic.analyze(d, S)
check("an open working port is a warning", "V1 port 2 is not connected" in messages(r, "warning"),
      True)
check("an open exhaust port is a note, because it vents on purpose",
      any(m.startswith("V1 port 3 is open") for m in messages(r, "note")), True)
check("a sheet with no supply says so",
      "there is no air supply or compressor on the sheet" in messages(r, "warning"), True)

d = doc(parts=[("filter", "Z1", 0, 0), ("filter", "Z1", 100, 0), ("gauge", "S?", 0, 100)])
r = schematic.analyze(d, S)
check("one number on two parts is an error", "Z1 is used twice" in messages(r, "error"), True)
check("an unnumbered part is an error",
      "Pressure gauge has no reference number" in messages(r, "error"), True)

d = doc(parts=[("supply", "#S1", 0, 0), ("valve32_solenoid", "V1", 0, 0)],
        wires=[[(0, -20), (20, -20), (20, 30)]])
r = schematic.analyze(d, S)
check("a supply piped to an exhaust port is an error",
      "the supply runs straight to exhaust port V1:3" in messages(r, "error"), True)

d = doc(parts=[("filter", "Z1", 0, 0)], wires=[[(20, 0), (60, 0)]])
r = schematic.analyze(d, S)
check("a line that ends on nothing is found, where it ends",
      [(e["msg"], e["at"]) for e in r["erc"] if "line ends" in e["msg"]],
      [("a line ends without joining anything", [60, 0])])

d = doc(parts=[("nonesuch", "X1", 0, 0)])
check("an unknown symbol is an error, not a crash",
      messages(schematic.analyze(d, S), "error"), ["X1: no symbol 'nonesuch' in the library"])

# --- bill of materials and netlist ---
d = doc(parts=[("silencer", "Z3", 0, 0), ("silencer", "Z2", 50, 0), ("silencer", "Z10", 100, 0),
               ("supply", "#S1", 0, 100), ("gauge", "S1", 200, 0)])
d["parts"][0]["value"] = d["parts"][1]["value"] = d["parts"][2]["value"] = "G1/8"
d["parts"][4]["fields"] = {"Part number": "PG-63"}
rows = schematic.bom(d, S)
check("like parts are one row, numbers in natural order",
      [(r["qty"], r["refs"], r["value"]) for r in rows],
      [(1, ["S1"], ""), (3, ["Z2", "Z3", "Z10"], "G1/8")])
check("the supply is not a part to buy", any("#S1" in r["refs"] for r in rows), False)
csv_text = schematic.bom_csv(rows)
check("the CSV has a column per field", csv_text.splitlines()[0],
      "Qty,References,Part,Value,Part number")
check("the CSV quotes a list of references", csv_text.splitlines()[2],
      '3,"Z2, Z3, Z10",Silencer,G1/8,')

# --- documents from outside ---
good = schematic.new_document()
check("a new document is valid", schematic.validate(good), None)
check("something else's JSON is refused", schematic.validate({"parts": []}),
      "not an AIRsys schematic")
check("a newer format is refused, not misread",
      schematic.validate(dict(good, version=99)), "made by a newer AIRsys (format version 99)")
bad = json.loads(json.dumps(good))
bad["wires"] = [{"id": "w1", "pts": [[0, 0]], "kind": "work"}]
check("a one-point wire is refused", schematic.validate(bad), "wire w1 has bad points")
bad["wires"] = [{"id": "a", "pts": [[0, 0], [10, 0]]}, {"id": "a", "pts": [[0, 0], [10, 0]]}]
check("a repeated id is refused", schematic.validate(bad), "id a is used twice")
bad["wires"] = [{"id": "w1", "pts": [[0, 0], [float("nan"), 0]]}]
check("a point that is not a number is refused", schematic.validate(bad), "wire w1 has bad points")

# --- the shipped example is clean ---
ex = json.loads((HERE / "airsys" / "examples" / "Door cylinder.airsys.json").read_text())
check("the example is valid", schematic.validate(ex), None)
r = schematic.analyze(ex, S)
check("the example passes the check with nothing to say", r["erc"], [])
check("the example's main line is named by its label",
      [n["members"] for n in r["nets"] if n["name"] == "MAIN"], [["V2:1", "Z1:2"]])
text = schematic.netlist_text(ex, r["nets"])
check("the netlist names the drawing", text.splitlines()[1], "# title: Door cylinder, single solenoid")

finish()
