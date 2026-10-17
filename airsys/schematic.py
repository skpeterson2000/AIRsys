"""A schematic document, and what can be worked out from it: which ports are
joined (the nets), what is wrong with it (the electrical rules check, ERC,
which here checks air rather than electricity), the bill of materials, and
the netlist.

The document is JSON, saved as <name>.airsys.json:

    format, version     "airsys-schematic", 1
    sheet               "A4", "A3", "Letter" or "Tabloid", landscape
    title_block         title, drawn_by, date, rev, company, comment
    parts               id, sym, ref, value, x, y, rot (quarter turns
                        clockwise), mirror (flipped left to right before
                        turning), fields (name: text), ref_off
    wires               id, pts [[x, y], ...], kind: "work", "pilot" or
                        "exhaust" (solid, long dashes, short dashes)
    labels              id, x, y, text, rot: every label with the same text
                        is one net, as a KiCad net label is
    texts               id, x, y, text, size: notes on the sheet

What connects, which is the same rule the editor draws its dots by:

- a wire's end that lies anywhere on another wire joins the two;
  wires that only cross do not join
- a port joins any wire that passes through or ends on it, and any port
  at the same point
- a label joins the wire or port it sits on
- every supply symbol with the same value is one net
"""

import csv
import io
import math
import re

FORMAT = "airsys-schematic"
VERSION = 1
SHEETS = {"A4": (1170, 830), "A3": (1650, 1170), "Letter": (1100, 850),
          "Tabloid": (1700, 1100)}
WIRE_KINDS = ("work", "pilot", "exhaust")
TOL = 0.01


def new_document():
    return {
        "format": FORMAT, "version": VERSION, "sheet": "A4",
        "title_block": {"title": "", "drawn_by": "", "date": "", "rev": "",
                        "company": "", "comment": ""},
        "parts": [], "wires": [], "labels": [], "texts": [],
    }


# --- checking a document that came over the network ---

def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _str(v, most):
    return isinstance(v, str) and len(v) <= most


def validate(doc):
    """None when the document is well formed, else what is wrong with it.
    This is about shape, not sense: an unconnected port is the ERC's
    business, not a reason to refuse a save."""
    if not isinstance(doc, dict):
        return "not a JSON object"
    if doc.get("format") != FORMAT:
        return "not an AIRsys schematic"
    if not isinstance(doc.get("version"), int) or doc["version"] > VERSION:
        return "made by a newer AIRsys (format version %r)" % doc.get("version")
    if doc.get("sheet") not in SHEETS:
        return "unknown sheet size %r" % doc.get("sheet")
    tb = doc.get("title_block")
    if not isinstance(tb, dict) or not all(_str(v, 500) for v in tb.values()):
        return "bad title block"
    ids = set()

    def item_list(key):
        items = doc.get(key)
        if not isinstance(items, list):
            raise ValueError("%s is not a list" % key)
        for it in items:
            if not isinstance(it, dict) or not _str(it.get("id"), 64) or not it["id"]:
                raise ValueError("an entry in %s has no id" % key)
            if it["id"] in ids:
                raise ValueError("id %s is used twice" % it["id"])
            ids.add(it["id"])
        return items

    try:
        for p in item_list("parts"):
            if not (_str(p.get("sym"), 64) and _num(p.get("x")) and _num(p.get("y"))):
                raise ValueError("part %s has no symbol or position" % p["id"])
            if p.get("rot", 0) not in (0, 1, 2, 3) or not isinstance(p.get("mirror", False), bool):
                raise ValueError("part %s has a bad rotation" % p["id"])
            if not (_str(p.get("ref", ""), 32) and _str(p.get("value", ""), 200)):
                raise ValueError("part %s has a bad reference or value" % p["id"])
            fields = p.get("fields", {})
            if not isinstance(fields, dict) or not all(
                    _str(k, 64) and _str(v, 500) for k, v in fields.items()):
                raise ValueError("part %s has bad fields" % p["id"])
            off = p.get("ref_off")
            if off is not None and not (isinstance(off, list) and len(off) == 2
                                        and all(_num(v) for v in off)):
                raise ValueError("part %s has a bad reference position" % p["id"])
        for w in item_list("wires"):
            pts = w.get("pts")
            if not (isinstance(pts, list) and len(pts) >= 2 and all(
                    isinstance(q, list) and len(q) == 2 and _num(q[0]) and _num(q[1])
                    for q in pts)):
                raise ValueError("wire %s has bad points" % w["id"])
            if w.get("kind", "work") not in WIRE_KINDS:
                raise ValueError("wire %s has an unknown kind" % w["id"])
        for lb in item_list("labels"):
            if not (_num(lb.get("x")) and _num(lb.get("y"))
                    and _str(lb.get("text"), 64) and lb["text"].strip()):
                raise ValueError("label %s is empty or misplaced" % lb["id"])
        for t in item_list("texts"):
            if not (_num(t.get("x")) and _num(t.get("y")) and _str(t.get("text"), 4000)):
                raise ValueError("text %s is bad" % t["id"])
    except ValueError as e:
        return str(e)
    return None


# --- geometry ---

def transform(x, y, part):
    """A point in a symbol's own frame, placed on the sheet: flipped if the
    part is mirrored, then turned a quarter clockwise per rot."""
    if part.get("mirror"):
        x = -x
    for _ in range(part.get("rot", 0) % 4):
        x, y = -y, x
    return (x + part["x"], y + part["y"])


def ports_of(part, sym):
    """[(name, kind, (x, y))] where the part's ports are on the sheet."""
    return [(p["n"], p["kind"], transform(p["x"], p["y"], part)) for p in sym["ports"]]


def same(a, b):
    return abs(a[0] - b[0]) <= TOL and abs(a[1] - b[1]) <= TOL


def on_segment(p, a, b):
    if same(p, a) or same(p, b):
        return True
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length <= TOL:
        return False
    cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0])
    if abs(cross) / length > TOL:
        return False
    t = (dx * (p[0] - a[0]) + dy * (p[1] - a[1])) / (length * length)
    return -TOL / length <= t <= 1 + TOL / length


def on_wire(p, pts):
    return any(on_segment(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def junctions(doc, symbols):
    """Where three or more things meet, the points that get a dot. A wire
    ending at a point counts one, a wire running through it counts two, a
    port counts one. A wire end on another wire's middle always makes a dot."""
    ports = []
    for p in doc["parts"]:
        sym = symbols.get(p["sym"])
        if sym:
            ports += [xy for _, _, xy in ports_of(p, sym)]
    ends = []
    for w in doc["wires"]:
        ends += [tuple(w["pts"][0]), tuple(w["pts"][-1])]
    found = []
    for pt in ends:
        if any(same(pt, f) for f in found):
            continue
        degree = sum(1 for q in ports if same(q, pt))
        for w in doc["wires"]:
            pts = w["pts"]
            if same(pt, pts[0]) or same(pt, pts[-1]):
                degree += 1
            elif on_wire(pt, pts):
                degree += 2
        if degree >= 3:
            found.append(pt)
    return sorted(found)


# --- connectivity ---

class _Union:
    def __init__(self):
        self.up = {}

    def add(self, k):
        self.up.setdefault(k, k)

    def find(self, k):
        while self.up[k] != k:
            self.up[k] = self.up[self.up[k]]
            k = self.up[k]
        return k

    def join(self, a, b):
        self.up[self.find(a)] = self.find(b)


def natural(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _issue(level, msg, at=None, item=None):
    d = {"level": level, "msg": msg}
    if at is not None:
        d["at"] = [round(at[0], 2), round(at[1], 2)]
    if item is not None:
        d["item"] = item
    return d


def analyze(doc, symbols):
    """Nets, rule check, junctions and bill of materials for a document.
    symbols is a dict of symbol id to symbol."""
    uf = _Union()
    erc = []
    ports = []      # (key, part, sym, name, kind, xy)
    for p in doc["parts"]:
        sym = symbols.get(p["sym"])
        if sym is None:
            erc.append(_issue("error", "%s: no symbol %r in the library"
                              % (p.get("ref") or p["id"], p["sym"]), (p["x"], p["y"]), p["id"]))
            continue
        for name, kind, xy in ports_of(p, sym):
            key = ("port", p["id"], name)
            uf.add(key)
            ports.append((key, p, sym, name, kind, xy))
            if sym["global_net"]:
                gkey = ("global", p.get("value") or sym["value"] or sym["name"])
                uf.add(gkey)
                uf.join(key, gkey)
    wires = doc["wires"]
    for w in wires:
        uf.add(("wire", w["id"]))

    touches = {}    # count of things each key touches, to find what goes nowhere

    def touch(a, b):
        uf.join(a, b)
        touches[a] = touches.get(a, 0) + 1
        touches[b] = touches.get(b, 0) + 1

    # wire ends on other wires
    end_hits = {}
    for w in wires:
        for i, end in ((0, w["pts"][0]), (1, w["pts"][-1])):
            for v in wires:
                if v is not w and on_wire(end, v["pts"]):
                    uf.join(("wire", w["id"]), ("wire", v["id"]))
                    end_hits[(w["id"], i)] = True
    # ports on wires, and ports on ports
    for key, p, sym, name, kind, xy in ports:
        for w in wires:
            if on_wire(xy, w["pts"]):
                touch(key, ("wire", w["id"]))
                for i, end in ((0, w["pts"][0]), (1, w["pts"][-1])):
                    if same(end, xy):
                        end_hits[(w["id"], i)] = True
        for key2, p2, _, _, _, xy2 in ports:
            if key2 != key and p2 is not p and same(xy, xy2):
                touch(key, key2)
    # labels
    for lb in doc["labels"]:
        lkey = ("label", lb["text"].strip())
        uf.add(lkey)
        at = (lb["x"], lb["y"])
        hit = False
        for w in wires:
            if on_wire(at, w["pts"]):
                uf.join(lkey, ("wire", w["id"]))
                hit = True
                for i, end in ((0, w["pts"][0]), (1, w["pts"][-1])):
                    if same(end, at):
                        end_hits[(w["id"], i)] = True
        for key, _, _, _, _, xy in ports:
            if same(xy, at):
                touch(key, lkey)
                hit = True
        if not hit:
            erc.append(_issue("warning", "label %s is not on a line or a port"
                              % lb["text"], at, lb["id"]))

    groups = {}
    for k in uf.up:
        groups.setdefault(uf.find(k), []).append(k)

    def ref_of(p, sym):
        return p.get("ref") or ("#" + sym["prefix"].lstrip("#"))

    nets = []
    port_net = {}
    for keys in groups.values():
        members = [pt for pt in ports if pt[0] in set(keys)]
        if not members:
            continue
        names = sorted({k[1] for k in keys if k[0] in ("global", "label")}, key=natural)
        listed = sorted(("%s:%s" % (ref_of(p, s), n) for _, p, s, n, _, _ in members
                         if not s["virtual"]), key=natural)
        if names:
            name = names[0]
            if len(names) > 1:
                at = members[0][5]
                erc.append(_issue("warning", "one net has two names: %s"
                                  % ", ".join(names), at))
        elif listed:
            name = "Net-(%s)" % listed[0]
        else:
            name = "Net-(%s)" % ("%s:%s" % (ref_of(members[0][1], members[0][2]),
                                            members[0][3]))
        net = {"name": name, "members": listed}
        nets.append(net)
        for m in members:
            port_net[m[0]] = net
        kinds = {m[4] for m in members}
        if "out" in kinds and "exhaust" in kinds:
            vents = sorted("%s:%s" % (ref_of(p, s), n) for _, p, s, n, k, _ in members
                           if k == "exhaust")
            erc.append(_issue("error", "the supply runs straight to exhaust port %s"
                              % ", ".join(vents), members[0][5]))
    nets.sort(key=lambda n: natural(n["name"]))

    # references
    seen = {}
    for p in doc["parts"]:
        sym = symbols.get(p["sym"])
        if sym is None or sym["virtual"]:
            continue
        ref = (p.get("ref") or "").strip()
        if not ref or ref.endswith("?"):
            erc.append(_issue("error", "%s has no reference number" % sym["name"],
                              (p["x"], p["y"]), p["id"]))
        elif ref in seen:
            erc.append(_issue("error", "%s is used twice" % ref, (p["x"], p["y"]), p["id"]))
        else:
            seen[ref] = p
    # unconnected ports
    for key, p, sym, name, kind, xy in ports:
        if touches.get(key):
            continue
        who = "%s port %s" % (ref_of(p, sym), name) if not sym["virtual"] else sym["name"]
        if kind == "exhaust":
            erc.append(_issue("note", "%s is open and vents to atmosphere; a silencer "
                              "or an exhaust mark says that is meant" % who, xy, p["id"]))
        else:
            erc.append(_issue("warning", "%s is not connected" % who, xy, p["id"]))
    # wire ends that go nowhere
    for w in wires:
        for i, end in ((0, w["pts"][0]), (1, w["pts"][-1])):
            if not end_hits.get((w["id"], i)):
                erc.append(_issue("warning", "a line ends without joining anything",
                                  end, w["id"]))
    if doc["parts"] and not any(
            k == "out" for _, _, _, _, k, _ in ports):
        erc.append(_issue("warning", "there is no air supply or compressor on the sheet"))

    order = {"error": 0, "warning": 1, "note": 2}
    erc.sort(key=lambda e: order[e["level"]])
    return {"nets": nets, "erc": erc, "junctions": [list(j) for j in junctions(doc, symbols)],
            "bom": bom(doc, symbols)}


# --- bill of materials and netlist ---

def bom(doc, symbols):
    """One row per kind of part: the same symbol, value and fields."""
    rows = {}
    for p in doc["parts"]:
        sym = symbols.get(p["sym"])
        if sym is None or sym["virtual"]:
            continue
        fields = tuple(sorted((k, v) for k, v in (p.get("fields") or {}).items() if v))
        key = (p["sym"], p.get("value", ""), fields)
        row = rows.setdefault(key, {"qty": 0, "refs": [], "part": sym["name"],
                                    "value": p.get("value", ""), "fields": dict(fields)})
        row["qty"] += 1
        row["refs"].append(p.get("ref") or "?")
    out = list(rows.values())
    for r in out:
        r["refs"].sort(key=natural)
    out.sort(key=lambda r: natural(r["refs"][0]))
    return out


def bom_csv(rows):
    names = sorted({k for r in rows for k in r["fields"]}, key=str.lower)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Qty", "References", "Part", "Value"] + names)
    for r in rows:
        w.writerow([r["qty"], ", ".join(r["refs"]), r["part"], r["value"]]
                   + [r["fields"].get(n, "") for n in names])
    return buf.getvalue()


def netlist_text(doc, nets):
    tb = doc.get("title_block", {})
    lines = ["# AIRsys netlist", "# title: %s" % (tb.get("title") or "(untitled)"),
             "# rev: %s" % (tb.get("rev") or "-"), ""]
    for n in nets:
        lines.append("net %s" % n["name"])
        lines += ["  %s" % m for m in n["members"]]
        lines.append("")
    return "\n".join(lines)
