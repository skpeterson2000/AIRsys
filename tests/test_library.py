"""Every symbol in the library can be wired to and drawn.

A port off the 10-unit grid is a port a snapped wire can never reach, so
it would show as open for ever; two ports with one name would make one of
them unreachable in the netlist. The editor draws only the primitive types
it knows, so an unknown one would be a symbol with a piece missing.
"""

from _check import check, finish

from airsys import library

KINDS = {"out", "supply", "work", "exhaust", "pilot"}
PRIMS = {"line", "poly", "rect", "circle", "path", "text"}
PREFIXES = {"A", "M", "P", "S", "V", "Z"}

ids = [s["id"] for s in library.SYMBOLS]
check("symbol ids are unique", len(ids), len(set(ids)))
check("there are symbols in every group the editor lists",
      sorted({s["group"] for s in library.SYMBOLS}),
      sorted(["Supply", "Air treatment", "Directional valves", "Flow and pressure",
              "Actuators", "Instruments", "Connections"]))

bad_grid, bad_names, bad_kinds, bad_prims, bad_prefix, outside = [], [], [], [], [], []
for s in library.SYMBOLS:
    names = [p["n"] for p in s["ports"]]
    if len(names) != len(set(names)):
        bad_names.append(s["id"])
    for p in s["ports"]:
        if p["x"] % library.GRID or p["y"] % library.GRID:
            bad_grid.append("%s:%s" % (s["id"], p["n"]))
        if p["kind"] not in KINDS:
            bad_kinds.append("%s:%s" % (s["id"], p["n"]))
        b = s["box"]
        if not (b[0] <= p["x"] <= b[2] and b[1] <= p["y"] <= b[3]):
            outside.append("%s:%s" % (s["id"], p["n"]))
    for g in s["g"]:
        if g["t"] not in PRIMS:
            bad_prims.append("%s:%s" % (s["id"], g["t"]))
    if s["virtual"]:
        if not s["prefix"].startswith("#"):
            bad_prefix.append(s["id"])
    elif s["prefix"] not in PREFIXES:
        bad_prefix.append(s["id"])

check("every port is on the grid", bad_grid, [])
check("no symbol has two ports with one name", bad_names, [])
check("every port has a kind the check knows", bad_kinds, [])
check("every drawing primitive is one the editor draws", bad_prims, [])
check("prefixes follow ISO 1219-2 letters; supply and exhaust marks start with #",
      bad_prefix, [])
check("every port is inside its symbol's box", outside, [])

v = library.BY_ID["valve52_solenoid"]
check("a 5/2 valve has ISO 5599 port numbers",
      sorted(p["n"] for p in v["ports"]), ["1", "2", "3", "4", "5"])
check("a 5/2 valve's exhausts are exhaust ports",
      sorted(p["n"] for p in v["ports"] if p["kind"] == "exhaust"), ["3", "5"])
check("a double pilot 5/2 has pilot ports 12 and 14",
      sorted(p["n"] for p in library.BY_ID["valve52_double_pilot"]["ports"]
             if p["kind"] == "pilot"), ["12", "14"])
check("the supply joins every supply of the same value",
      library.BY_ID["supply"]["global_net"], True)
check("the supply is not on the bill of materials", library.BY_ID["supply"]["virtual"], True)

finish()
