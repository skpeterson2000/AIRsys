"""The symbol library: pneumatic symbols in the shapes of ISO 1219-1.

Every symbol is drawn about its own origin in schematic units of 0.01 inch
(10 mil), and every port sits on the 10-unit grid (100 mil, as KiCad draws),
so a wire snapped to the grid lands exactly on a port. y grows downward, as
it does on the page.

A symbol is plain data, served to the editor as JSON:

    id, name, group     what it is and where the library lists it
    prefix              the letter its reference designator starts with,
                        after ISO 1219-2: A actuator, M motor, P compressor,
                        S sensor or instrument, V valve, Z everything else
    ports               name, position and kind; port names follow ISO 5599
                        (1 supply, 2 and 4 working, 3 and 5 exhaust,
                        12 and 14 pilot)
    g                   the drawing, as primitives (line, poly, rect,
                        circle, path, text)
    box                 the bounding box, worked out here
    ref_at              where the reference designator goes; the value
                        goes 10 units below it
    virtual             a supply or exhaust mark: not a part to buy, so it
                        has no number and stays off the bill of materials
    global_net          every copy with the same value is the same net, as
                        KiCad's power symbols are

Port kinds: "out" (a source of air), "supply" (port 1), "work",
"exhaust" (3 and 5: it vents if left open) and "pilot".
"""

import math

GRID = 10


# --- primitives ---

def line(*xy, dash=None):
    d = {"t": "line", "p": [round(v, 2) for v in xy]}
    if dash:
        d["dash"] = dash
    return d


def poly(*xy, fill=False):
    return {"t": "poly", "p": [round(v, 2) for v in xy], "fill": fill}


def rect(x, y, w, h, rx=0, dash=None, fill=False):
    d = {"t": "rect", "x": x, "y": y, "w": w, "h": h}
    if rx:
        d["rx"] = rx
    if dash:
        d["dash"] = dash
    if fill:
        d["fill"] = True
    return d


def circle(x, y, r, fill=False):
    return {"t": "circle", "x": x, "y": y, "r": r, "fill": fill}


def path(d, fill=False):
    return {"t": "path", "d": d, "fill": fill}


def text(x, y, s, size=7, anchor="start"):
    return {"t": "text", "x": x, "y": y, "s": s, "size": size, "anchor": anchor}


def spring(x0, y0, x1, y1, n=3, amp=4):
    """A zigzag from (x0, y0) to (x1, y1), n full waves."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    nx, ny = -dy / length, dx / length
    pts = [x0, y0]
    for i in range(1, 2 * n + 1):
        t = (i - 0.5) / (2 * n)
        s = amp if i % 2 else -amp
        pts += [x0 + dx * t + nx * s, y0 + dy * t + ny * s]
    pts += [x1, y1]
    return line(*pts)


def arrow(x0, y0, x1, y1, head=5.0, half=2.5):
    """A line ending in a filled head whose tip is at (x1, y1)."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    bx, by = x1 - ux * head, y1 - uy * head
    return [line(x0, y0, bx, by),
            poly(x1, y1, bx - uy * half, by + ux * half, bx + uy * half, by - ux * half,
                 fill=True)]


def flow(x0, y0, x1, y1):
    """A flow path across a valve square, kept clear of its edges."""
    dx, dy = x1 - x0, y1 - y0
    return arrow(x0 + dx * 0.08, y0 + dy * 0.08, x1 - dx * 0.1, y1 - dy * 0.1)


def adjustable(cx, cy, size=22):
    """The slanted arrow that marks a setting as adjustable."""
    h = size / 2
    return arrow(cx - h, cy + h, cx + h, cy - h, head=4, half=2)


def blocked(x, edge):
    """A blocked port: the T drawn inside a valve square. edge is -1 for the
    top of a square at y = -15, +1 for the bottom at y = 15."""
    y0 = 15 * edge
    y1 = 9 * edge
    return [line(x, y0, x, y1), line(x - 4, y1, x + 4, y1)]


def exhaust_mark(x, y, down=1):
    """The hollow triangle of a port venting to atmosphere."""
    return poly(x - 4, y, x + 4, y, x, y + 6 * down)


def port(n, x, y, kind):
    assert x % GRID == 0 and y % GRID == 0, (n, x, y)
    return {"n": n, "x": x, "y": y, "kind": kind}


def stubs(spec):
    """Port lines from a valve's squares to the grid, with ISO 5599 numbers.
    spec is (name, x, edge, kind); edge -1 is the top, +1 the bottom."""
    g, ports = [], []
    for name, x, edge, kind in spec:
        g.append(line(x, 15 * edge, x, 30 * edge))
        g.append(text(x + 2.5, 27 if edge > 0 else -20, name, 6))
        ports.append(port(name, x, 30 * edge, kind))
    return g, ports


# --- actuators, drawn at the end x = xe of a valve; side -1 left, +1 right ---

def actuator(kind, xe, side, y=0, pilot_name=None):
    s = side
    if kind == "solenoid":
        x0, x1 = sorted((xe, xe + 10 * s))
        return [rect(x0, y - 6, 10, 12), line(x0, y + 6, x1, y - 6)], []
    if kind == "spring":
        return [spring(xe, y, xe + 12 * s, y, n=3, amp=5)], []
    if kind == "button":
        xb = xe + 6 * s
        sweep = 1 if s > 0 else 0
        return [line(xe, y, xb, y), line(xb, y - 6, xb, y + 6),
                path("M%g,%g A6,6 0 0 %d %g,%g" % (xb, y - 6, sweep, xb, y + 6))], []
    if kind == "roller":
        return [line(xe, y, xe + 8 * s, y), circle(xe + 12 * s, y, 4)], []
    if kind == "pilot":
        xb = xe + 8 * s
        xp = xe + 20 * s
        return ([poly(xe, y, xb, y - 5, xb, y + 5), line(xb, y, xp, y, dash="pilot"),
                 text(xp + (2 if s > 0 else -2), y - 3, pilot_name, 6,
                      "start" if s > 0 else "end")],
                [port(pilot_name, xp, y, "pilot")])
    raise ValueError(kind)


def _act(spec, xe, side, pilot_name):
    """One actuator, or several stacked, as ISO draws them."""
    kinds = spec.split("+")
    if len(kinds) == 1:
        return actuator(kinds[0], xe, side, 0, pilot_name)
    g, ports = [], []
    for kind, y in zip(kinds, (-8, 8)):
        gg, pp = actuator(kind, xe, side, y, pilot_name)
        g += gg
        ports += pp
    return g, ports


# --- the symbols ---

def _valve32(sid, name, left, right="spring"):
    g = [rect(-30, -15, 30, 30), rect(0, -15, 30, 30)]
    # unactuated (right square, where the ports are): 2 exhausts to 3, 1 blocked
    g += flow(10, -15, 20, 15) + blocked(10, 1)
    # actuated (left square): 1 to 2, 3 blocked
    g += flow(-20, 15, -20, -15) + blocked(-10, 1)
    sg, ports = stubs([("2", 10, -1, "work"), ("1", 10, 1, "supply"),
                       ("3", 20, 1, "exhaust")])
    g += sg
    for spec, xe, side, pn in ((left, -30, -1, "12"), (right, 30, 1, "10")):
        ag, ap = _act(spec, xe, side, pn)
        g += ag
        ports += ap
    return dict(id=sid, name=name, group="Directional valves", prefix="V",
                ports=ports, g=g, ref_at=[-30, -30])


def _valve52(sid, name, left, right):
    g = [rect(-40, -15, 40, 30), rect(0, -15, 40, 30)]
    # unactuated: 1 to 2, 4 to 5, 3 blocked
    g += flow(20, 15, 30, -15) + flow(10, -15, 10, 15) + blocked(30, 1)
    # actuated by 14: 1 to 4, 2 to 3, 5 blocked
    g += flow(-20, 15, -30, -15) + flow(-10, -15, -10, 15) + blocked(-30, 1)
    sg, ports = stubs([("4", 10, -1, "work"), ("2", 30, -1, "work"),
                       ("5", 10, 1, "exhaust"), ("1", 20, 1, "supply"),
                       ("3", 30, 1, "exhaust")])
    g += sg
    for spec, xe, side, pn in ((left, -40, -1, "14"), (right, 40, 1, "12")):
        ag, ap = _act(spec, xe, side, pn)
        g += ag
        ports += ap
    return dict(id=sid, name=name, group="Directional valves", prefix="V",
                ports=ports, g=g, ref_at=[-40, -30])


def _valve53(sid, name, left, right):
    g = [rect(-60, -15, 40, 30), rect(-20, -15, 40, 30), rect(20, -15, 40, 30)]
    # center: every port blocked
    for x, edge in ((-10, -1), (10, -1), (-10, 1), (0, 1), (10, 1)):
        g += blocked(x, edge)
    # left square (14): 1 to 4, 2 to 3, 5 blocked
    g += flow(-40, 15, -50, -15) + flow(-30, -15, -30, 15) + blocked(-50, 1)
    # right square (12): 1 to 2, 4 to 5, 3 blocked
    g += flow(40, 15, 50, -15) + flow(30, -15, 30, 15) + blocked(50, 1)
    sg, ports = stubs([("4", -10, -1, "work"), ("2", 10, -1, "work"),
                       ("5", -10, 1, "exhaust"), ("1", 0, 1, "supply"),
                       ("3", 10, 1, "exhaust")])
    g += sg
    for spec, xe, side, pn in ((left, -60, -1, "14"), (right, 60, 1, "12")):
        ag, ap = _act(spec, xe, side, pn)
        g += ag
        ports += ap
    return dict(id=sid, name=name, group="Directional valves", prefix="V",
                ports=ports, g=g, ref_at=[-60, -30])


def _diamond():
    return poly(0, -15, 15, 0, 0, 15, -15, 0)


def _inline_ports():
    return ([line(-20, 0, -15, 0), line(15, 0, 20, 0)],
            [port("1", -20, 0, "supply"), port("2", 20, 0, "work")])


def _check(cx, cy, free_right=True):
    """A ball check valve on a horizontal line: the V seat on the side the
    air comes from, the ball beyond it."""
    s = 1 if free_right else -1
    ax = cx - 6 * s
    return [line(ax, cy, cx + 2 * s, cy - 7), line(ax, cy, cx + 2 * s, cy + 7),
            circle(cx + 3 * s, cy, 4)]


def build():
    syms = []

    # supply
    syms.append(dict(
        id="supply", name="Air supply", group="Supply", prefix="#S",
        virtual=True, global_net=True, value="Supply",
        g=[circle(0, 0, 8), poly(0, -5, -4, 3, 4, 3), line(0, -8, 0, -20)],
        ports=[port("1", 0, -20, "out")], ref_at=[11, 3]))
    syms.append(dict(
        id="compressor", name="Compressor", group="Supply", prefix="P",
        g=[circle(0, 0, 15), poly(0, -14, -5, -5, 5, -5), line(0, -15, 0, -30),
           line(-15, -2, -25, -2), line(-15, 2, -25, 2)],
        ports=[port("2", 0, -30, "out")], ref_at=[19, -10]))
    syms.append(dict(
        id="motor", name="Electric motor", group="Supply", prefix="M",
        g=[circle(0, 0, 15), text(0, 5, "M", 14, "middle"),
           line(15, -2, 25, -2), line(15, 2, 25, 2)],
        ports=[], ref_at=[-15, -30]))
    syms.append(dict(
        id="receiver", name="Air receiver (tank)", group="Supply", prefix="Z",
        g=[rect(-20, -10, 40, 20, rx=8), line(-30, 0, -20, 0), line(20, 0, 30, 0)],
        ports=[port("1", -30, 0, "supply"), port("2", 30, 0, "work")],
        ref_at=[-20, -24]))

    # air treatment
    ig, ip = _inline_ports()
    syms.append(dict(
        id="filter", name="Filter", group="Air treatment", prefix="Z",
        g=[_diamond(), line(0, -15, 0, 15, dash="pilot")] + ig,
        ports=ip, ref_at=[-15, -28]))
    syms.append(dict(
        id="filter_separator", name="Filter, water separator, manual drain",
        group="Air treatment", prefix="Z",
        g=[_diamond(), line(0, -15, 0, 15, dash="pilot"), line(-8, 7, 8, 7),
           line(0, 15, 0, 20), exhaust_mark(0, 20)] + ig,
        ports=ip, ref_at=[-15, -28]))
    syms.append(dict(
        id="lubricator", name="Lubricator", group="Air treatment", prefix="Z",
        g=[_diamond(), line(0, -6, 0, 15), poly(-3, -10, 3, -10, 0, -6, fill=True)] + ig,
        ports=ip, ref_at=[-15, -28]))
    syms.append(dict(
        id="regulator", name="Pressure regulator", group="Air treatment", prefix="V",
        g=[rect(-15, -15, 30, 30)] + arrow(0, 12, 0, -12)
          + [line(0, 15, 0, 30), line(0, -15, 0, -30),
             line(0, -22, -25, -22, -25, 0, -15, 0, dash="pilot"),
             spring(15, 0, 30, 0, n=3, amp=5)] + adjustable(22, 0)
          + [text(3, 27, "1", 6), text(3, -20, "2", 6)],
        ports=[port("1", 0, 30, "supply"), port("2", 0, -30, "work")],
        ref_at=[36, -8]))
    syms.append(dict(
        id="frl", name="Service unit (filter, regulator, gauge)",
        group="Air treatment", prefix="Z",
        g=[rect(-20, -12, 40, 24), poly(-8, -7, -1, 0, -8, 7, -15, 0),
           line(-8, -7, -8, 7, dash="pilot")] + arrow(8, 8, 8, -8)
          + adjustable(8, 0, 14)
          + [line(8, -12, 8, -13), circle(8, -18, 5), line(-30, 0, -20, 0),
             line(20, 0, 30, 0)],
        ports=[port("1", -30, 0, "supply"), port("2", 30, 0, "work")],
        ref_at=[-20, 26]))

    # directional valves
    syms.append(_valve32("valve32_solenoid", "3/2 valve, solenoid, spring return",
                         "solenoid"))
    syms.append(_valve32("valve32_button", "3/2 valve, push button, spring return",
                         "button"))
    syms.append(_valve32("valve32_roller", "3/2 valve, roller lever, spring return",
                         "roller"))
    syms.append(_valve32("valve32_pilot", "3/2 valve, air pilot, spring return",
                         "pilot"))
    syms.append(_valve52("valve52_solenoid", "5/2 valve, solenoid, spring return",
                         "solenoid", "spring"))
    syms.append(_valve52("valve52_double_solenoid", "5/2 valve, double solenoid",
                         "solenoid", "solenoid"))
    syms.append(_valve52("valve52_double_pilot", "5/2 valve, double air pilot",
                         "pilot", "pilot"))
    syms.append(_valve53("valve53_closed", "5/3 valve, closed center, solenoids, "
                         "spring centered", "solenoid+spring", "solenoid+spring"))

    # flow and pressure
    syms.append(dict(
        id="ball_valve", name="Shut-off valve, manual", group="Flow and pressure",
        prefix="V",
        g=[poly(-10, -6, -10, 6, 0, 0), poly(10, -6, 10, 6, 0, 0),
           line(-20, 0, -10, 0), line(10, 0, 20, 0), line(0, 0, 0, -10),
           line(-5, -10, 5, -10)],
        ports=[port("1", -20, 0, "supply"), port("2", 20, 0, "work")],
        ref_at=[-15, -24]))
    syms.append(dict(
        id="check_valve", name="Check valve", group="Flow and pressure", prefix="V",
        g=[line(-20, 0, -6, 0)] + _check(0, 0) + [line(7, 0, 20, 0)],
        ports=[port("1", -20, 0, "supply"), port("2", 20, 0, "work")],
        ref_at=[-15, -18]))
    syms.append(dict(
        id="throttle", name="Throttle valve, adjustable", group="Flow and pressure",
        prefix="V",
        g=[line(-20, 0, 20, 0), path("M-7,-7 Q0,0 7,-7"), path("M-7,7 Q0,0 7,7")]
          + adjustable(0, 0, 20),
        ports=[port("1", -20, 0, "supply"), port("2", 20, 0, "work")],
        ref_at=[-15, -18]))
    syms.append(dict(
        id="flow_control", name="One-way flow control valve",
        group="Flow and pressure", prefix="V",
        g=[line(-30, 0, 30, 0), path("M-7,-7 Q0,0 7,-7"), path("M-7,7 Q0,0 7,7")]
          + adjustable(0, 0, 18)
          + [line(-20, 0, -20, 16, -9, 16), line(9, 16, 20, 16, 20, 0)]
          + _check(0, 16, free_right=False)
          + [rect(-25, -13, 50, 38, dash="pilot")],
        ports=[port("1", -30, 0, "supply"), port("2", 30, 0, "work")],
        ref_at=[-25, -28]))
    syms.append(dict(
        id="relief_valve", name="Pressure relief valve", group="Flow and pressure",
        prefix="V",
        g=[rect(-15, -15, 30, 30)] + arrow(5, 12, 5, -12)
          + [line(0, 15, 0, 30), line(0, -15, 0, -20), exhaust_mark(0, -20, -1),
             line(0, 22, 25, 22, 25, 0, 15, 0, dash="pilot"),
             spring(-15, 0, -30, 0, n=3, amp=5)] + adjustable(-22, 0),
        ports=[port("1", 0, 30, "supply")], ref_at=[30, -10]))
    syms.append(dict(
        id="shuttle_valve", name="Shuttle valve (OR)", group="Flow and pressure",
        prefix="V",
        g=[rect(-20, -8, 40, 16), line(-30, 0, -20, 0), line(20, 0, 30, 0),
           line(0, -8, 0, -20), circle(0, 0, 4),
           line(-12, -6, -16, 0, -12, 6), line(12, -6, 16, 0, 12, 6)],
        ports=[port("1a", -30, 0, "supply"), port("1b", 30, 0, "supply"),
               port("2", 0, -20, "work")],
        ref_at=[-20, 22]))

    # actuators
    syms.append(dict(
        id="cylinder_double", name="Cylinder, double acting", group="Actuators",
        prefix="A",
        g=[rect(-40, -10, 80, 20), rect(-27, -10, 4, 20, fill=True),
           rect(-23, -2, 83, 4), line(-30, 10, -30, 20), line(30, 10, 30, 20)],
        ports=[port("cap", -30, 20, "work"), port("rod", 30, 20, "work")],
        ref_at=[-40, -24]))
    syms.append(dict(
        id="cylinder_single", name="Cylinder, single acting, spring return",
        group="Actuators", prefix="A",
        g=[rect(-40, -10, 80, 20), rect(-27, -10, 4, 20, fill=True),
           rect(-23, -2, 83, 4), spring(-23, 0, 40, 0, n=5, amp=7),
           line(-30, 10, -30, 20)],
        ports=[port("cap", -30, 20, "work")], ref_at=[-40, -24]))
    syms.append(dict(
        id="air_motor", name="Air motor, one direction", group="Actuators",
        prefix="A",
        g=[circle(0, 0, 15), poly(0, -6, -5, -14, 5, -14), line(0, -15, 0, -30),
           line(0, 15, 0, 30), line(15, -2, 25, -2), line(15, 2, 25, 2)],
        ports=[port("1", 0, -30, "supply"), port("2", 0, 30, "exhaust")],
        ref_at=[19, -18]))

    # instruments
    syms.append(dict(
        id="gauge", name="Pressure gauge", group="Instruments", prefix="S",
        g=[circle(0, 0, 10), line(0, 10, 0, 20)] + arrow(-6, 6, 6, -6, head=4, half=2),
        ports=[port("1", 0, 20, "work")], ref_at=[14, -2]))
    syms.append(dict(
        id="pressure_switch", name="Pressure switch", group="Instruments",
        prefix="S",
        g=[rect(-15, -10, 30, 20), line(-11, 4, -4, 4), line(-4, 4, 7, -4),
           line(6, 4, 11, 4), line(0, 10, 0, 20, dash="pilot")],
        ports=[port("1", 0, 20, "pilot")], ref_at=[19, -2]))

    # connections
    syms.append(dict(
        id="silencer", name="Silencer", group="Connections", prefix="Z",
        g=[line(0, -20, 0, -8), rect(-6, -8, 12, 16), line(-6, -2, 6, -2),
           line(-6, 4, 6, 4)],
        ports=[port("1", 0, -20, "work")], ref_at=[10, -2]))
    syms.append(dict(
        id="exhaust", name="Exhaust to atmosphere", group="Connections", prefix="#E",
        virtual=True, value="",
        g=[line(0, -10, 0, 0), exhaust_mark(0, 0)],
        ports=[port("1", 0, -10, "work")], ref_at=[8, 4]))
    syms.append(dict(
        id="coupling", name="Quick coupling, connected", group="Connections",
        prefix="Z",
        g=[line(-20, 0, -3, 0), line(3, 0, 20, 0), line(-8, -5, -3, 0, -8, 5),
           line(8, -5, 3, 0, 8, 5)],
        ports=[port("1", -20, 0, "supply"), port("2", 20, 0, "work")],
        ref_at=[-12, -18]))
    syms.append(dict(
        id="plug", name="Plug (blanked port)", group="Connections", prefix="Z",
        g=[line(0, 0, 0, 6), line(-5, 6, 5, 6)],
        ports=[port("1", 0, 0, "work")], ref_at=[8, 8]))

    for s in syms:
        s.setdefault("virtual", False)
        s.setdefault("global_net", False)
        s.setdefault("value", "")
        s["box"] = bounds(s)
    return syms


def bounds(sym):
    """The symbol's bounding box [x0, y0, x1, y1], from everything with
    coordinates. Curves stay inside the points around them."""
    xs, ys = [], []
    for p in sym["ports"]:
        xs.append(p["x"])
        ys.append(p["y"])
    for g in sym["g"]:
        t = g["t"]
        if t in ("line", "poly"):
            xs += g["p"][0::2]
            ys += g["p"][1::2]
        elif t == "rect":
            xs += [g["x"], g["x"] + g["w"]]
            ys += [g["y"], g["y"] + g["h"]]
        elif t == "circle":
            xs += [g["x"] - g["r"], g["x"] + g["r"]]
            ys += [g["y"] - g["r"], g["y"] + g["r"]]
    return [min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2]


SYMBOLS = build()
BY_ID = {s["id"]: s for s in SYMBOLS}


def as_json():
    return {"grid": GRID, "symbols": SYMBOLS}
