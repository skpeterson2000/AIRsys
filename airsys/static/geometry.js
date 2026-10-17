/* Where things are and what touches what: the same rules as schematic.py,
   which the editor needs live, to draw junction dots, open-port circles and
   loose wire ends while you draw. tests/test_geometry_js.py runs both on
   the same drawings and checks they agree. */

(function (root) {
  "use strict";
  const TOL = 0.01;

  function transform(x, y, part) {
    if (part.mirror) x = -x;
    const r = (((part.rot || 0) % 4) + 4) % 4;
    for (let i = 0; i < r; i++) { const t = x; x = -y; y = t; }
    return [x + part.x, y + part.y];
  }

  function portsOf(part, sym) {
    return sym.ports.map(p => {
      const xy = transform(p.x, p.y, part);
      return { n: p.n, kind: p.kind, x: xy[0], y: xy[1] };
    });
  }

  /* The symbol's box on the sheet: [x0, y0, x1, y1]. */
  function boxOf(part, sym) {
    const b = sym.box;
    const corners = [transform(b[0], b[1], part), transform(b[2], b[3], part)];
    return [Math.min(corners[0][0], corners[1][0]), Math.min(corners[0][1], corners[1][1]),
            Math.max(corners[0][0], corners[1][0]), Math.max(corners[0][1], corners[1][1])];
  }

  function same(a, b) {
    return Math.abs(a[0] - b[0]) <= TOL && Math.abs(a[1] - b[1]) <= TOL;
  }

  function onSegment(p, a, b) {
    if (same(p, a) || same(p, b)) return true;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len = Math.hypot(dx, dy);
    if (len <= TOL) return false;
    const cross = dx * (p[1] - a[1]) - dy * (p[0] - a[0]);
    if (Math.abs(cross) / len > TOL) return false;
    const t = (dx * (p[0] - a[0]) + dy * (p[1] - a[1])) / (len * len);
    return t >= -TOL / len && t <= 1 + TOL / len;
  }

  function onWire(p, pts) {
    for (let i = 0; i < pts.length - 1; i++) if (onSegment(p, pts[i], pts[i + 1])) return true;
    return false;
  }

  /* Distance from p to the nearest segment of a polyline. */
  function distToWire(p, pts) {
    let best = Infinity;
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      const dx = b[0] - a[0], dy = b[1] - a[1];
      const l2 = dx * dx + dy * dy;
      let t = l2 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2 : 0;
      t = Math.max(0, Math.min(1, t));
      best = Math.min(best, Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy));
    }
    return best;
  }

  function allPorts(doc, symbols) {
    const out = [];
    for (const part of doc.parts) {
      const sym = symbols[part.sym];
      if (!sym) continue;
      for (const p of portsOf(part, sym)) out.push({ part, sym, n: p.n, kind: p.kind, xy: [p.x, p.y] });
    }
    return out;
  }

  /* Dots: a wire ending at a point counts one, a wire running through it
     two, a port one; three or more is a junction. */
  function junctions(doc, symbols) {
    const ports = allPorts(doc, symbols).map(p => p.xy);
    const found = [];
    for (const w of doc.wires) {
      for (const pt of [w.pts[0], w.pts[w.pts.length - 1]]) {
        if (found.some(f => same(f, pt))) continue;
        let degree = ports.filter(q => same(q, pt)).length;
        for (const v of doc.wires) {
          const pts = v.pts;
          if (same(pt, pts[0]) || same(pt, pts[pts.length - 1])) degree += 1;
          else if (onWire(pt, pts)) degree += 2;
        }
        if (degree >= 3) found.push([pt[0], pt[1]]);
      }
    }
    found.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    return found;
  }

  /* Ports nothing touches, and wire ends that join nothing: the editor
     marks both, as KiCad marks an open pin and a dangling wire. */
  function loose(doc, symbols) {
    const ports = allPorts(doc, symbols);
    const labels = doc.labels.map(l => [l.x, l.y]);
    const openPorts = [];
    for (const p of ports) {
      const hit = doc.wires.some(w => onWire(p.xy, w.pts))
        || ports.some(q => q.part !== p.part && same(q.xy, p.xy))
        || labels.some(l => same(l, p.xy));
      if (!hit) openPorts.push({ partId: p.part.id, n: p.n, kind: p.kind, xy: p.xy });
    }
    const openEnds = [];
    for (const w of doc.wires) {
      for (const end of [w.pts[0], w.pts[w.pts.length - 1]]) {
        const hit = doc.wires.some(v => v !== w && onWire(end, v.pts))
          || ports.some(q => same(q.xy, end))
          || labels.some(l => same(l, end));
        if (!hit) openEnds.push([end[0], end[1]]);
      }
    }
    return { openPorts, openEnds };
  }

  /* Make every segment horizontal or vertical, adding an elbow where one is
     not, and drop points that sit in a straight run. */
  function tidy(pts) {
    const out = [pts[0].slice()];
    for (let i = 1; i < pts.length; i++) {
      const a = out[out.length - 1], b = pts[i];
      if (Math.abs(a[0] - b[0]) > TOL && Math.abs(a[1] - b[1]) > TOL) out.push([b[0], a[1]]);
      out.push(b.slice());
    }
    const clean = [];
    for (const p of out) {
      if (clean.length && same(clean[clean.length - 1], p)) continue;
      if (clean.length >= 2) {
        const a = clean[clean.length - 2], b = clean[clean.length - 1];
        const straight = (Math.abs(a[0] - b[0]) <= TOL && Math.abs(b[0] - p[0]) <= TOL)
          || (Math.abs(a[1] - b[1]) <= TOL && Math.abs(b[1] - p[1]) <= TOL);
        const back = (p[0] - b[0]) * (b[0] - a[0]) + (p[1] - b[1]) * (b[1] - a[1]) < 0;
        if (straight && !back) { clean[clean.length - 1] = p; continue; }
      }
      clean.push(p);
    }
    return clean;
  }

  const api = { TOL, transform, portsOf, boxOf, same, onSegment, onWire, distToWire,
                allPorts, junctions, loose, tidy };
  root.AirGeom = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
