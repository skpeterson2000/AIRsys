/* The schematic editor. The drawing is one JSON document (see schematic.py);
   every change goes through change(), which keeps the undo history, and
   everything on the sheet is redrawn from the document after it. */

(function () {
  "use strict";
  const G = window.AirGeom;
  const NS = "http://www.w3.org/2000/svg";
  const $ = s => document.querySelector(s);

  let LIB = null;            // {grid, symbols, sheets}
  let SYMS = {};             // symbol id -> symbol
  let GRID = 10;
  let doc = null;
  let project = { name: null, base: null, example: false };
  let savedSnap = "";
  let sel = new Set();
  let tool = "select";
  let placing = null;        // {sym, rot, mirror}
  let draft = null;          // {pts, posture} for the line being drawn
  let drag = null;
  let view = { x: 0, y: 0, s: 1 };   // world point at the top-left corner; s = pixels per unit
  let mouse = [0, 0];        // world, snapped
  let rawMouse = [0, 0];     // world, not snapped
  let spaceDown = false;
  let undoStack = [], redoStack = [];
  let ercResult = null;
  let ercFocus = null;
  let propsKey = null;

  const svg = $("#canvas");
  let world, sceneG, overlayG, gridPat, gridDot;

  // --- small helpers ---

  function el(tag, attrs, parent) {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(tag, attrs, s, parent) { const e = el(tag, attrs, parent); e.textContent = s; return e; }
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      if (k.startsWith("on")) e.addEventListener(k.slice(2), attrs[k]);
      else if (k === "value") e.value = attrs[k];
      else e.setAttribute(k, attrs[k]);
    }
    for (const kid of kids) e.append(kid);
    return e;
  }
  function pairs(a) { const s = []; for (let i = 0; i < a.length; i += 2) s.push(a[i] + "," + a[i + 1]); return s.join(" "); }
  function snap(p) { return [Math.round(p[0] / GRID) * GRID, Math.round(p[1] / GRID) * GRID]; }
  function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window */ } }
  function newId(prefix) {
    const used = new Set(allItems().map(i => i.obj.id));
    let id;
    do { id = prefix + Math.random().toString(36).slice(2, 9); } while (used.has(id));
    return id;
  }
  function natural(a, b) { return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" }); }
  function sheetSize() { return LIB.sheets[doc.sheet] || LIB.sheets.A4; }
  function hint(s) { $("#st-hint").textContent = s || ""; }

  async function api(method, url, body, headers) {
    const opts = { method, headers: Object.assign({}, headers || {}) };
    if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { data = { error: res.statusText }; }
    return { ok: res.ok, status: res.status, data };
  }

  // --- the document's items ---

  function allItems() {
    if (!doc) return [];
    return [].concat(
      doc.parts.map(o => ({ kind: "part", obj: o })),
      doc.wires.map(o => ({ kind: "wire", obj: o })),
      doc.labels.map(o => ({ kind: "label", obj: o })),
      doc.texts.map(o => ({ kind: "text", obj: o })));
  }
  function find(id) { return allItems().find(i => i.obj.id === id) || null; }
  function selected() { return [...sel].map(find).filter(Boolean); }

  // --- undo and dirty ---

  function snapshot() { return JSON.stringify(doc); }
  function change(fn) {
    const before = snapshot();
    fn();
    if (snapshot() !== before) committed(before);
    renderAll();
  }
  function committed(before) {
    undoStack.push(before);
    if (undoStack.length > 300) undoStack.shift();
    redoStack = [];
    ercResult = null;
    ercFocus = null;
    updateTitle();
  }
  function undo() {
    if (!undoStack.length) return;
    redoStack.push(snapshot());
    doc = JSON.parse(undoStack.pop());
    afterSwap();
  }
  function redo() {
    if (!redoStack.length) return;
    undoStack.push(snapshot());
    doc = JSON.parse(redoStack.pop());
    afterSwap();
  }
  function afterSwap() {
    sel = new Set([...sel].filter(id => find(id)));
    ercResult = null; ercFocus = null; propsKey = null;
    updateTitle();
    renderAll();
  }
  function dirty() { return doc && snapshot() !== savedSnap; }
  function updateTitle() {
    const name = project.name ? project.name + (project.example ? " (example)" : "") : "untitled";
    $("#docname").textContent = name + (dirty() ? " *" : "");
    document.title = (dirty() ? "* " : "") + name + " - AIRsys";
  }

  // --- view ---

  function capture(e) {
    try { svg.setPointerCapture(e.pointerId); } catch (err) { /* the pointer has already gone */ }
  }
  function toWorld(ev) {
    const r = svg.getBoundingClientRect();
    return [(ev.clientX - r.left) / view.s + view.x, (ev.clientY - r.top) / view.s + view.y];
  }
  function applyView() {
    world.setAttribute("transform", `translate(${-view.x * view.s},${-view.y * view.s}) scale(${view.s})`);
    const step = GRID * view.s < 6 ? GRID * 5 : GRID;
    gridPat.setAttribute("width", step);
    gridPat.setAttribute("height", step);
    gridPat.setAttribute("x", -step / 2);
    gridPat.setAttribute("y", -step / 2);
    gridDot.setAttribute("cx", step / 2);
    gridDot.setAttribute("cy", step / 2);
    gridDot.setAttribute("r", Math.min(1.2, 1 / view.s));
    $("#st-zoom").textContent = "zoom " + Math.round(view.s * 100) + "%";
  }
  function zoomAt(factor, sx, sy) {
    const r = svg.getBoundingClientRect();
    if (sx === undefined) { sx = r.width / 2; sy = r.height / 2; }
    const wx = sx / view.s + view.x, wy = sy / view.s + view.y;
    view.s = Math.max(0.15, Math.min(30, view.s * factor));
    view.x = wx - sx / view.s;
    view.y = wy - sy / view.s;
    applyView();
    renderOverlay();
  }
  function fit() {
    const r = svg.getBoundingClientRect();
    const [W, H] = sheetSize();
    view.s = Math.min(r.width / (W + 40), r.height / (H + 40)) || 1;
    view.x = -(r.width / view.s - W) / 2;
    view.y = -(r.height / view.s - H) / 2;
    applyView();
    renderOverlay();
  }
  function centerOn(p) {
    const r = svg.getBoundingClientRect();
    if (view.s < 2) view.s = 2;
    view.x = p[0] - r.width / 2 / view.s;
    view.y = p[1] - r.height / 2 / view.s;
    applyView();
  }

  // --- drawing symbols ---

  function partTransform(part) {
    return `translate(${part.x},${part.y}) rotate(${(part.rot || 0) * 90})${part.mirror ? " scale(-1,1)" : ""}`;
  }

  function drawPrim(g, p) {
    const stroke = "sym-stroke" + (p.dash ? " dash-pilot" : "");
    const cls = p.fill ? "sym-fill" : stroke;
    switch (p.t) {
      case "line": return el("polyline", { points: pairs(p.p), class: stroke }, g);
      case "poly": return el("polygon", { points: pairs(p.p), class: cls }, g);
      case "rect": return el("rect", { x: p.x, y: p.y, width: p.w, height: p.h, rx: p.rx || null, class: cls }, g);
      case "circle": return el("circle", { cx: p.x, cy: p.y, r: p.r, class: cls }, g);
      case "path": return el("path", { d: p.d, class: cls }, g);
    }
    return null;
  }

  /* The symbol's own text stays upright however the part is turned. */
  function drawSymTexts(g, sym, part) {
    const dir = G.transform(1, 0, Object.assign({}, part, { x: 0, y: 0 }));
    for (const p of sym.g) {
      if (p.t !== "text") continue;
      let anchor = p.anchor || "start";
      if (dir[0] < -0.5) anchor = anchor === "start" ? "end" : anchor === "end" ? "start" : anchor;
      if (anchor === "middle") {
        const [x, y] = G.transform(p.x, p.y - p.size * 0.35, part);
        txt("text", { x, y, class: "sym-text", "font-size": p.size, "text-anchor": "middle",
                      "dominant-baseline": "central" }, p.s, g);
      } else {
        const [x, y] = G.transform(p.x, p.y, part);
        txt("text", { x, y, class: "sym-text", "font-size": p.size, "text-anchor": anchor }, p.s, g);
      }
    }
  }

  function fieldPos(part, sym) {
    const [x, y] = G.transform(sym.ref_at[0], sym.ref_at[1], part);
    const o = part.ref_off || [0, 0];
    return [x + o[0], y + o[1]];
  }
  function fieldTexts(part, sym) {
    const [x, y] = fieldPos(part, sym);
    const out = [];
    if (sym.virtual) {
      if (part.value) out.push({ x, y, s: part.value, cls: "ref", size: 9 });
    } else {
      out.push({ x, y, s: part.ref || "?", cls: "ref", size: 9 });
      if (part.value) out.push({ x, y: y + 10, s: part.value, cls: "val", size: 8 });
    }
    return out;
  }

  function drawPart(c, part, ghost) {
    const sym = SYMS[part.sym];
    if (!sym) {
      el("rect", { x: part.x - 10, y: part.y - 10, width: 20, height: 20, class: "erc-focus" }, c);
      return;
    }
    const g = el("g", { class: "part" + (ghost ? " ghost" : ""), transform: partTransform(part) }, c);
    for (const p of sym.g) if (p.t !== "text") drawPrim(g, p);
    const tg = el("g", { class: "part" + (ghost ? " ghost" : "") }, c);
    drawSymTexts(tg, sym, part);
    for (const f of fieldTexts(part, sym)) txt("text", { x: f.x, y: f.y, class: f.cls }, f.s, tg);
  }

  function labelGeom(lb) {
    const end = lb.rot === 2;
    return { x: lb.x + (end ? -3 : 3), y: lb.y - 3, anchor: end ? "end" : "start" };
  }
  function drawLabel(c, lb) {
    const g = labelGeom(lb);
    el("rect", { x: lb.x - 1.5, y: lb.y - 1.5, width: 3, height: 3, class: "label-mark", fill: "none" }, c);
    txt("text", { x: g.x, y: g.y, class: "label", "text-anchor": g.anchor }, lb.text, c);
  }
  function drawNote(c, t) {
    const size = t.size || 10;
    const e = el("text", { x: t.x, y: t.y, class: "note", "font-size": size }, c);
    t.text.split("\n").forEach((line, i) => {
      txt("tspan", { x: t.x, dy: i ? size * 1.2 : 0 }, line || " ", e);
    });
  }

  // --- the sheet: frame, zones and title block ---

  function drawSheet(c, live) {
    const [W, H] = sheetSize();
    el("rect", { x: 0, y: 0, width: W, height: H, class: "paper" }, c);
    if (live) el("rect", { x: 0, y: 0, width: W, height: H, fill: "url(#gridpat)" }, c);
    el("rect", { x: 10, y: 10, width: W - 20, height: H - 20, class: "frame" }, c);
    el("rect", { x: 20, y: 20, width: W - 40, height: H - 40, class: "frame" }, c);
    const cols = Math.max(2, Math.round((W - 40) / 200)), rows = Math.max(2, Math.round((H - 40) / 200));
    const cw = (W - 40) / cols, rh = (H - 40) / rows;
    for (let i = 0; i < cols; i++) {
      const x = 20 + i * cw;
      if (i) { el("line", { x1: x, y1: 10, x2: x, y2: 20, class: "frame" }, c); el("line", { x1: x, y1: H - 20, x2: x, y2: H - 10, class: "frame" }, c); }
      txt("text", { x: x + cw / 2, y: 18, class: "frame-text", "text-anchor": "middle" }, String(i + 1), c);
      txt("text", { x: x + cw / 2, y: H - 12, class: "frame-text", "text-anchor": "middle" }, String(i + 1), c);
    }
    for (let i = 0; i < rows; i++) {
      const y = 20 + i * rh;
      if (i) { el("line", { x1: 10, y1: y, x2: 20, y2: y, class: "frame" }, c); el("line", { x1: W - 20, y1: y, x2: W - 10, y2: y, class: "frame" }, c); }
      const L = String.fromCharCode(65 + i);
      txt("text", { x: 15, y: y + rh / 2 + 3, class: "frame-text", "text-anchor": "middle" }, L, c);
      txt("text", { x: W - 15, y: y + rh / 2 + 3, class: "frame-text", "text-anchor": "middle" }, L, c);
    }
    const tb = doc.title_block, w = 380, hgt = 80, x0 = W - 20 - w, y0 = H - 20 - hgt;
    el("rect", { x: x0, y: y0, width: w, height: hgt, class: "frame" }, c);
    for (const y of [18, 48, 64]) el("line", { x1: x0, y1: y0 + y, x2: x0 + w, y2: y0 + y, class: "frame" }, c);
    el("line", { x1: x0 + 170, y1: y0 + 48, x2: x0 + 170, y2: y0 + 64, class: "frame" }, c);
    el("line", { x1: x0 + 290, y1: y0 + 48, x2: x0 + 290, y2: y0 + hgt, class: "frame" }, c);
    const cell = (x, y, label, value) => {
      const t = el("text", { x: x0 + x + 3, y: y0 + y }, c);
      txt("tspan", { class: "tb-small" }, label + "  ", t);
      txt("tspan", { class: "tb-val" }, value || "", t);
    };
    cell(0, 13, "Company", tb.company);
    txt("text", { x: x0 + 3, y: y0 + 26, class: "tb-small" }, "Title", c);
    txt("text", { x: x0 + 8, y: y0 + 43, class: "tb-big" }, tb.title || "", c);
    cell(0, 60, "Drawn by", tb.drawn_by);
    cell(170, 60, "Date", tb.date);
    cell(290, 60, "Rev", tb.rev);
    cell(0, 76, "", tb.comment);
    cell(290, 76, "Size " + doc.sheet, "");
    txt("text", { x: x0 + w - 3, y: y0 + 13, class: "tb-small", "text-anchor": "end" }, "AIRsys", c);
  }

  /* Everything that belongs to the drawing. live adds the grid, selection,
     open-port circles and loose-end squares, which do not print. */
  function drawScene(c, live) {
    drawSheet(c, live);
    if (live) {
      for (const it of selected()) {
        if (it.kind === "wire") el("polyline", { points: it.obj.pts.map(p => p.join(",")).join(" "), class: "halo" }, c);
      }
    }
    const wires = el("g", {}, c);
    for (const w of doc.wires) {
      el("polyline", { points: w.pts.map(p => p.join(",")).join(" "), class: "wire " + (w.kind || "work") }, wires);
    }
    const parts = el("g", {}, c);
    for (const p of doc.parts) drawPart(parts, p, false);
    const marks = el("g", {}, c);
    for (const j of G.junctions(doc, SYMS)) el("circle", { cx: j[0], cy: j[1], r: 2.4, class: "junction" }, marks);
    for (const lb of doc.labels) drawLabel(marks, lb);
    for (const t of doc.texts) drawNote(marks, t);
    if (!live) return;
    const lo = G.loose(doc, SYMS);
    for (const p of lo.openPorts) el("circle", { cx: p.xy[0], cy: p.xy[1], r: 2, class: "open-port" }, marks);
    for (const e of lo.openEnds) el("rect", { x: e[0] - 2, y: e[1] - 2, width: 4, height: 4, class: "open-end" }, marks);
    for (const it of selected()) {
      const b = itemBox(it);
      if (it.kind !== "wire") el("rect", { x: b[0] - 2, y: b[1] - 2, width: b[2] - b[0] + 4, height: b[3] - b[1] + 4, class: "selbox" }, marks);
    }
    const one = selected();
    if (one.length === 1 && one[0].kind === "wire") {
      for (const p of one[0].obj.pts) el("rect", { x: p[0] - 2.5, y: p[1] - 2.5, width: 5, height: 5, class: "handle" }, marks);
    }
    if (ercResult) {
      for (const e of ercResult.erc) {
        if (!e.at) continue;
        el("path", { d: `M${e.at[0]},${e.at[1]} l-4,-9 h8 z`, class: "erc-mark " + e.level }, marks);
      }
    }
    if (ercFocus) el("circle", { cx: ercFocus[0], cy: ercFocus[1], r: 12, class: "erc-focus" }, marks);
  }

  function renderAll() {
    sceneG.replaceChildren();
    drawScene(sceneG, true);
    renderOverlay();
    const key = [...sel].sort().join(",");
    if (key !== propsKey) { propsKey = key; showProps(); }
    $("#b-undo").disabled = !undoStack.length;
    $("#b-redo").disabled = !redoStack.length;
  }

  function renderOverlay() {
    overlayG.replaceChildren();
    const [x, y] = mouse;
    const arm = 8 / view.s;
    el("path", { d: `M${x - arm},${y} H${x + arm} M${x},${y - arm} V${y + arm}`, class: "cursor", "stroke-width": 1 / view.s }, overlayG);
    if (tool === "place" && placing) {
      drawPart(overlayG, { id: "_ghost", sym: placing.sym.id, x, y, rot: placing.rot, mirror: placing.mirror,
                           ref: placing.sym.prefix + "?", value: placing.sym.value }, true);
    }
    if (tool === "wire" && draft) {
      el("polyline", { points: draftPoints(mouse).map(p => p.join(",")).join(" "), class: "draft" }, overlayG);
    }
    if (drag && drag.type === "rubber") {
      const [a, b] = [drag.start, rawMouse];
      el("rect", { x: Math.min(a[0], b[0]), y: Math.min(a[1], b[1]), width: Math.abs(a[0] - b[0]),
                   height: Math.abs(a[1] - b[1]), class: "rubber", "stroke-width": 1 / view.s }, overlayG);
    }
    $("#st-pos").textContent = `x ${(x / 100).toFixed(2)} in  y ${(y / 100).toFixed(2)} in` +
      `  (${(x * 0.254).toFixed(1)}, ${(y * 0.254).toFixed(1)} mm)`;
  }

  // --- what is under the pointer ---

  function textBox(x, y, s, size, anchor) {
    const w = Math.max(4, s.length * size * 0.6);
    const x0 = anchor === "end" ? x - w : anchor === "middle" ? x - w / 2 : x;
    return [x0, y - size, x0 + w, y + size * 0.3];
  }
  function itemBox(it) {
    const o = it.obj;
    if (it.kind === "part") {
      const sym = SYMS[o.sym];
      return sym ? G.boxOf(o, sym) : [o.x - 10, o.y - 10, o.x + 10, o.y + 10];
    }
    if (it.kind === "wire") {
      const xs = o.pts.map(p => p[0]), ys = o.pts.map(p => p[1]);
      return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
    if (it.kind === "label") { const g = labelGeom(o); return textBox(g.x, g.y, o.text, 9, g.anchor); }
    const size = o.size || 10, lines = o.text.split("\n");
    const w = Math.max(...lines.map(l => l.length)) * size * 0.6;
    return [o.x, o.y - size, o.x + Math.max(w, 4), o.y + size * 1.2 * (lines.length - 1) + size * 0.3];
  }
  function inBox(p, b, pad) { return p[0] >= b[0] - pad && p[0] <= b[2] + pad && p[1] >= b[1] - pad && p[1] <= b[3] + pad; }

  function hitTest(p) {
    const tol = Math.max(1.5, 5 / view.s);
    const one = selected();
    if (one.length === 1 && one[0].kind === "wire") {
      const i = one[0].obj.pts.findIndex(q => Math.hypot(q[0] - p[0], q[1] - p[1]) <= tol);
      if (i >= 0) return { kind: "vertex", id: one[0].obj.id, index: i };
    }
    for (const op of G.loose(doc, SYMS).openPorts) {
      if (Math.hypot(op.xy[0] - p[0], op.xy[1] - p[1]) <= tol) return { kind: "port", xy: op.xy };
    }
    for (let i = doc.parts.length - 1; i >= 0; i--) {
      const part = doc.parts[i], sym = SYMS[part.sym];
      if (!sym) continue;
      for (const f of fieldTexts(part, sym)) {
        if (inBox(p, textBox(f.x, f.y, f.s, f.size, "start"), 0)) return { kind: "field", id: part.id };
      }
    }
    for (const it of allItems().reverse()) {
      if ((it.kind === "label" || it.kind === "text") && inBox(p, itemBox(it), 1)) return { kind: it.kind, id: it.obj.id };
    }
    for (let i = doc.wires.length - 1; i >= 0; i--) {
      if (G.distToWire(p, doc.wires[i].pts) <= tol) return { kind: "wire", id: doc.wires[i].id };
    }
    for (let i = doc.parts.length - 1; i >= 0; i--) {
      const it = { kind: "part", obj: doc.parts[i] };
      if (inBox(p, itemBox(it), 0)) return { kind: "part", id: it.obj.id };
    }
    return null;
  }

  function portAt(p) {
    return G.allPorts(doc, SYMS).find(q => G.same(q.xy, p)) || null;
  }

  // --- tools ---

  const HINTS = {
    select: "Click to select, drag to move, drag on empty sheet to select an area. Click an open port to draw a line from it.",
    wire: "Click to start and to bend; double-click, Esc, or click a port or line to finish. / bends the other way.",
    place: "Click to place. R rotates, X mirrors, Esc stops.",
    label: "Click on a line or port to label it. Lines with the same label are joined.",
    text: "Click where the note goes.",
  };

  function setTool(t) {
    if (tool === "wire" && t !== "wire") finishWire();
    tool = t;
    if (t !== "place") {
      placing = null;
      document.querySelectorAll(".libitem.on").forEach(b => b.classList.remove("on"));
    }
    document.querySelectorAll("#tools [data-tool]").forEach(b =>
      b.classList.toggle("on", b.dataset.tool === t));
    svg.classList.toggle("cross", t !== "select");
    hint(HINTS[t]);
    renderOverlay();
  }

  function startPlace(sym) {
    setTool("place");
    placing = { sym, rot: 0, mirror: false };
    document.querySelectorAll(".libitem").forEach(b => b.classList.toggle("on", b.dataset.sym === sym.id));
    hint(sym.name + ": " + HINTS.place);
    renderOverlay();
  }

  function nextRef(prefix, taken) {
    let n = 0;
    const re = new RegExp("^" + prefix.replace(/[^A-Za-z0-9]/g, "\\$&") + "(\\d+)$");
    for (const p of doc.parts) { const m = re.exec(p.ref || ""); if (m) n = Math.max(n, +m[1]); }
    for (const r of taken || []) { const m = re.exec(r); if (m) n = Math.max(n, +m[1]); }
    return prefix + (n + 1);
  }

  function placePart(p) {
    const sym = placing.sym;
    change(() => {
      const part = { id: newId("p"), sym: sym.id, ref: nextRef(sym.prefix), value: sym.value || "",
                     x: p[0], y: p[1], rot: placing.rot, mirror: placing.mirror, fields: {} };
      doc.parts.push(part);
      sel = new Set([part.id]);
    });
  }

  function draftPoints(p) {
    const pts = draft.pts.map(q => q.slice());
    const last = pts[pts.length - 1];
    if (!G.same(last, p)) {
      pts.push(draft.posture ? [last[0], p[1]] : [p[0], last[1]]);
      pts.push(p.slice());
    }
    return G.tidy(pts);
  }

  function endsOnSomething(p) {
    return !!portAt(p) || doc.wires.some(w => G.onWire(p, w.pts)) || doc.labels.some(l => G.same([l.x, l.y], p));
  }

  function wireClick(p) {
    if (!draft) {
      draft = { pts: [p.slice()], posture: 0 };
      renderOverlay();
      return;
    }
    const last = draft.pts[draft.pts.length - 1];
    if (G.same(last, p)) return;
    draft.pts = draftPoints(p);
    if (endsOnSomething(p)) finishWire();
    else renderOverlay();
  }

  function finishWire() {
    if (!draft) return;
    const pts = G.tidy(draft.pts);
    const thenSelect = draft.thenSelect;
    draft = null;
    if (thenSelect && tool === "wire") setTool("select");
    if (pts.length >= 2) {
      const kind = $("#wire-kind").value;
      change(() => doc.wires.push({ id: newId("w"), pts, kind }));
    } else {
      renderOverlay();
    }
  }

  function addLabel(p) {
    const s = prompt("Net label (every line with the same label is joined):", "");
    if (!s || !s.trim()) return;
    change(() => doc.labels.push({ id: newId("l"), x: p[0], y: p[1], text: s.trim().slice(0, 64), rot: 0 }));
  }

  function addNote(p) {
    const s = prompt("Note:", "");
    if (!s) return;
    change(() => doc.texts.push({ id: newId("t"), x: p[0], y: p[1], text: s, size: 10 }));
  }

  // --- moving things ---

  /* A line attached to a moving part follows it: its end moves, and the
     next corner moves with it so the run stays square. */
  function stretch(orig, moveStart, moveEnd, d) {
    const pts = orig.map(p => p.slice());
    if (moveStart && moveEnd) return pts.map(p => [p[0] + d[0], p[1] + d[1]]);
    const i = moveStart ? 0 : pts.length - 1;
    const j = moveStart ? 1 : pts.length - 2;
    const a = orig[i], b = orig[j];
    const horizontal = Math.abs(a[1] - b[1]) <= G.TOL;
    pts[i] = [a[0] + d[0], a[1] + d[1]];
    if (pts.length > 2) {
      if (horizontal) pts[j][1] += d[1];
      else pts[j][0] += d[0];
    } else {
      const elbow = horizontal ? [b[0], pts[i][1]] : [pts[i][0], b[1]];
      pts.splice(1, 0, elbow);
    }
    return G.tidy(pts);
  }

  function startMove(p, follow) {
    const items = selected().map(it => ({ it, orig: JSON.parse(JSON.stringify(it.obj)) }));
    const moving = new Set(items.map(i => i.it.obj.id));
    const ports = [];
    for (const { it } of items) {
      if (it.kind === "part" && SYMS[it.obj.sym]) for (const q of G.portsOf(it.obj, SYMS[it.obj.sym])) ports.push([q.x, q.y]);
      if (it.kind === "label") ports.push([it.obj.x, it.obj.y]);
    }
    const attached = [];
    for (const w of doc.wires) {
      if (moving.has(w.id)) continue;
      const s = ports.some(q => G.same(q, w.pts[0]));
      const e = ports.some(q => G.same(q, w.pts[w.pts.length - 1]));
      if (s || e) attached.push({ wire: w, orig: w.pts.map(q => q.slice()), s, e });
    }
    drag = { type: "move", start: p, before: snapshot(), items, attached, follow: !!follow, moved: false };
  }

  function applyMove(d) {
    for (const { it, orig } of drag.items) {
      const o = it.obj;
      if (it.kind === "wire") o.pts = orig.pts.map(q => [q[0] + d[0], q[1] + d[1]]);
      else { o.x = orig.x + d[0]; o.y = orig.y + d[1]; }
    }
    for (const a of drag.attached) a.wire.pts = stretch(a.orig, a.s, a.e, d);
  }

  function endDrag(cancel) {
    const d = drag;
    drag = null;
    svg.classList.remove("panning");
    if (!d) return;
    if (d.type === "move" || d.type === "vertex" || d.type === "field") {
      if (cancel) { doc = JSON.parse(d.before); renderAll(); return; }
      if (snapshot() !== d.before) committed(d.before);
    }
    if (d.type === "rubber") {
      const a = d.start, b = rawMouse;
      const box = [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
      const crossing = b[0] < a[0];   // right to left takes anything it touches, as in KiCad
      for (const it of allItems()) {
        const ib = itemBox(it);
        const inside = ib[0] >= box[0] && ib[2] <= box[2] && ib[1] >= box[1] && ib[3] <= box[3];
        const touch = ib[0] <= box[2] && ib[2] >= box[0] && ib[1] <= box[3] && ib[3] >= box[1];
        if (crossing ? touch : inside) sel.add(it.obj.id);
      }
    }
    renderAll();
  }

  // --- editing the selection ---

  function rotate90(p, c) { return [c[0] - (p[1] - c[1]), c[1] + (p[0] - c[0])]; }

  function selectionCenter(items) {
    const bs = items.map(itemBox);
    return snap([(Math.min(...bs.map(b => b[0])) + Math.max(...bs.map(b => b[2]))) / 2,
                 (Math.min(...bs.map(b => b[1])) + Math.max(...bs.map(b => b[3]))) / 2]);
  }

  function rotateSel() {
    if (tool === "place" && placing) { placing.rot = (placing.rot + 1) % 4; renderOverlay(); return; }
    const items = selected();
    if (!items.length) return;
    change(() => {
      if (items.length === 1 && items[0].kind === "part") { items[0].obj.rot = ((items[0].obj.rot || 0) + 1) % 4; return; }
      const c = selectionCenter(items);
      for (const it of items) {
        const o = it.obj;
        if (it.kind === "wire") o.pts = o.pts.map(p => rotate90(p, c));
        else { [o.x, o.y] = rotate90([o.x, o.y], c); }
        if (it.kind === "part") o.rot = ((o.rot || 0) + 1) % 4;
      }
    });
  }

  function mirrorSel() {
    if (tool === "place" && placing) { placing.mirror = !placing.mirror; renderOverlay(); return; }
    const items = selected();
    if (!items.length) return;
    const flip = o => { o.mirror = !o.mirror; o.rot = (4 - (o.rot || 0)) % 4; };
    change(() => {
      if (items.length === 1 && items[0].kind === "part") { flip(items[0].obj); return; }
      const cx = selectionCenter(items)[0];
      for (const it of items) {
        const o = it.obj;
        if (it.kind === "wire") o.pts = o.pts.map(p => [2 * cx - p[0], p[1]]);
        else o.x = 2 * cx - o.x;
        if (it.kind === "part") flip(o);
        if (it.kind === "label") o.rot = o.rot === 2 ? 0 : 2;
      }
    });
  }

  function deleteSel() {
    if (!sel.size) return;
    change(() => {
      for (const k of ["parts", "wires", "labels", "texts"]) doc[k] = doc[k].filter(o => !sel.has(o.id));
      sel.clear();
    });
  }

  function duplicateSel() {
    const items = selected();
    if (!items.length) return;
    change(() => {
      const fresh = new Set(), taken = [];
      for (const it of items) {
        const o = JSON.parse(JSON.stringify(it.obj));
        o.id = newId(it.kind[0]);
        if (it.kind === "wire") o.pts = o.pts.map(p => [p[0] + 20, p[1] + 20]);
        else { o.x += 20; o.y += 20; }
        if (it.kind === "part" && SYMS[o.sym]) { o.ref = nextRef(SYMS[o.sym].prefix, taken); taken.push(o.ref); }
        doc[{ part: "parts", wire: "wires", label: "labels", text: "texts" }[it.kind]].push(o);
        fresh.add(o.id);
      }
      sel = fresh;
    });
  }

  function renumber() {
    change(() => {
      const groups = {};
      for (const p of doc.parts) {
        const sym = SYMS[p.sym];
        if (sym) (groups[sym.prefix] = groups[sym.prefix] || []).push(p);
      }
      for (const prefix in groups) {
        groups[prefix].sort((a, b) => a.y - b.y || a.x - b.x)
          .forEach((p, i) => { p.ref = prefix + (i + 1); });
      }
    });
    hint("Numbered again, top to bottom and left to right, per letter.");
  }

  // --- the side panel: properties ---

  const FIELD_NAMES = ["Part number", "Supplier", "Port size", "Pressure", "Flow", "Note"];

  function input(value, onchange, attrs) {
    const e = h("input", Object.assign({ type: "text", value: value || "" }, attrs || {}));
    e.addEventListener("change", () => onchange(e.value));
    return e;
  }

  function showProps() {
    const box = $("#props");
    box.replaceChildren();
    const items = selected();
    if (!items.length) return sheetProps(box);
    if (items.length > 1) {
      box.append(h("h2", {}, items.length + " selected"));
      const wires = items.filter(i => i.kind === "wire");
      if (wires.length === items.length) box.append(wireKindPicker(wires));
      box.append(h("p", {}, "R rotates them together, X mirrors, Del deletes, Ctrl+D duplicates."));
      return;
    }
    const it = items[0], o = it.obj;
    if (it.kind === "part") return partProps(box, o);
    if (it.kind === "wire") {
      box.append(h("h2", {}, "Line"), wireKindPicker([it]),
        h("p", {}, `${o.pts.length - 1} segment${o.pts.length > 2 ? "s" : ""}. Drag a corner to reshape it.`));
      return;
    }
    if (it.kind === "label") {
      box.append(h("h2", {}, "Net label"), h("label", {}, "Name"),
        input(o.text, v => { if (v.trim()) change(() => { o.text = v.trim().slice(0, 64); }); }),
        h("p", {}, "Every line or port carrying this label is one net."));
      return;
    }
    const ta = h("textarea", { rows: 4 });
    ta.value = o.text;
    ta.addEventListener("change", () => change(() => { o.text = ta.value; }));
    box.append(h("h2", {}, "Note"), ta, h("label", {}, "Size"),
      input(String(o.size || 10), v => { const n = parseFloat(v); if (n > 2 && n < 200) change(() => { o.size = n; }); }));
  }

  function wireKindPicker(wires) {
    const s = h("select", {},
      h("option", { value: "work" }, "Working line"),
      h("option", { value: "pilot" }, "Pilot line"),
      h("option", { value: "exhaust" }, "Exhaust line"));
    s.value = wires[0].obj.kind || "work";
    s.addEventListener("change", () => change(() => { for (const w of wires) w.obj.kind = s.value; }));
    return h("div", {}, h("label", {}, "Carries"), s);
  }

  function partProps(box, o) {
    const sym = SYMS[o.sym];
    box.append(h("h2", {}, sym ? sym.name : "Unknown symbol " + o.sym));
    if (!sym) return;
    if (!sym.virtual) {
      box.append(h("label", {}, "Reference"),
        input(o.ref, v => change(() => { o.ref = v.trim().slice(0, 32); }), { id: "prop-ref" }));
    }
    box.append(h("label", {}, sym.global_net ? "Value (names the net: every supply with this value is joined)" : "Value"),
      input(o.value, v => change(() => { o.value = v.slice(0, 200); }), { id: sym.virtual ? "prop-ref" : "prop-value" }));
    const fields = o.fields || {};
    for (const k of Object.keys(fields)) {
      box.append(h("label", {}, k), h("div", { class: "row" },
        input(fields[k], v => change(() => { o.fields[k] = v.slice(0, 500); })),
        h("button", { class: "small", title: "Remove this field",
                      onclick: () => change(() => { delete o.fields[k]; propsKey = null; }) }, "×")));
    }
    if (!sym.virtual) {
      const add = h("select", {}, h("option", { value: "" }, "Add a field..."),
        ...FIELD_NAMES.filter(n => !(n in fields)).map(n => h("option", { value: n }, n)),
        h("option", { value: "*" }, "Other..."));
      add.addEventListener("change", () => {
        let name = add.value;
        if (name === "*") name = (prompt("Field name:") || "").trim().slice(0, 64);
        if (!name) { add.value = ""; return; }
        propsKey = null;
        change(() => { o.fields = o.fields || {}; if (!(name in o.fields)) o.fields[name] = ""; });
      });
      box.append(h("div", { style: "margin-top:8px" }, add));
    }
    box.append(h("div", { class: "row", style: "margin-top:8px" },
      h("button", { onclick: rotateSel }, "Rotate"), h("button", { onclick: mirrorSel }, "Mirror")),
      h("p", {}, `Ports: ${sym.ports.map(p => p.n).join(", ") || "none"}. Drag the number to move it.`));
  }

  function sheetProps(box) {
    const tb = doc.title_block;
    const size = h("select", {}, ...Object.keys(LIB.sheets).map(k => h("option", { value: k }, k + " landscape")));
    size.value = doc.sheet;
    size.addEventListener("change", () => { change(() => { doc.sheet = size.value; }); fit(); });
    box.append(h("h2", {}, "Sheet"), size);
    for (const [k, label] of [["title", "Title"], ["drawn_by", "Drawn by"], ["date", "Date"],
                              ["rev", "Revision"], ["company", "Company"], ["comment", "Comment"]]) {
      box.append(h("label", {}, label), input(tb[k], v => change(() => { tb[k] = v.slice(0, 500); })));
    }
    box.append(h("p", {}, `${doc.parts.length} parts, ${doc.wires.length} lines, ${doc.labels.length} labels.`));
  }

  // --- the side panel: library ---

  function thumb(sym) {
    const s = el("svg", {});
    const b = sym.box, pad = 3;
    s.setAttribute("viewBox", `${b[0] - pad} ${b[1] - pad} ${b[2] - b[0] + 2 * pad} ${b[3] - b[1] + 2 * pad}`);
    const g = el("g", { class: "part" }, s);
    for (const p of sym.g) if (p.t !== "text") drawPrim(g, p);
    return s;
  }

  function buildLibrary() {
    const list = $("#lib-list");
    const q = $("#lib-search").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    list.replaceChildren();
    let group = null, first = null;
    for (const sym of LIB.symbols) {
      const hay = (sym.name + " " + sym.id + " " + sym.group).toLowerCase();
      if (!q.every(w => hay.includes(w))) continue;
      if (sym.group !== group) { group = sym.group; list.append(h("h3", {}, group)); }
      const b = h("button", { class: "libitem", "data-sym": sym.id, title: sym.name, onclick: () => startPlace(sym) },
        thumb(sym), h("span", {}, sym.name));
      if (placing && placing.sym.id === sym.id) b.classList.add("on");
      list.append(b);
      first = first || sym;
    }
    return first;
  }

  // --- the check, and what it exports ---

  async function check() {
    const r = await api("POST", "/api/check", doc);
    if (!r.ok) { alert("The check could not run: " + r.data.error); return null; }
    return r.data;
  }

  async function runCheck() {
    const res = await check();
    if (!res) return;
    ercResult = res;
    const n = lv => res.erc.filter(e => e.level === lv).length;
    $("#erc").hidden = false;
    $("#erc-summary").textContent = res.erc.length
      ? `${n("error")} errors, ${n("warning")} warnings, ${n("note")} notes, in ${doc.parts.length} parts and ${res.nets.length} nets.`
      : `Nothing found, in ${doc.parts.length} parts and ${res.nets.length} nets.`;
    const ul = $("#erc-list");
    ul.replaceChildren();
    for (const e of res.erc) {
      const li = h("li", { class: e.level }, h("b", {}, e.level), e.msg);
      li.addEventListener("click", () => {
        if (e.at) { ercFocus = e.at; centerOn(e.at); }
        if (e.item && find(e.item)) sel = new Set([e.item]);
        renderAll();
      });
      ul.append(li);
    }
    renderAll();
  }

  function baseName() {
    return (project.name || doc.title_block.title || "untitled").replace(/[^A-Za-z0-9 _.-]/g, "_");
  }
  function download(name, text, type) {
    const a = h("a", { href: URL.createObjectURL(new Blob([text], { type })), download: name });
    document.body.append(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  const EXPORT_CSS = `
.paper{fill:#fff}.frame{fill:none;stroke:#7a2a2a;stroke-width:1}
.frame-text{fill:#7a2a2a;font:9px sans-serif}.tb-big{fill:#7a2a2a;font:600 16px sans-serif}
.tb-small{fill:#7a2a2a;font:8px sans-serif}.tb-val{fill:#111;font:11px sans-serif}
.part{color:#8b1a1a}.sym-stroke{fill:none;stroke:currentColor;stroke-width:1.2;stroke-linejoin:round;stroke-linecap:round}
.sym-fill{fill:currentColor;stroke:currentColor;stroke-width:1.2;stroke-linejoin:round}
.dash-pilot{stroke-dasharray:5 3}.sym-text{fill:currentColor;font-family:sans-serif}
.ref{fill:#8b1a1a;font:600 9px sans-serif}.val{fill:#8b1a1a;font:8px sans-serif}
.wire{fill:none;stroke:#0f6b3a;stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round}
.wire.pilot{stroke-dasharray:7 4}.wire.exhaust{stroke-dasharray:2 3}.junction{fill:#0f6b3a}
.label{fill:#1d4ed8;font:600 9px sans-serif}.label-mark{stroke:#1d4ed8;stroke-width:1}
.note{fill:#111;font-family:sans-serif}`;

  function exportSVG() {
    const [W, H] = sheetSize();
    const out = el("svg", { xmlns: NS, width: W / 100 + "in", height: H / 100 + "in", viewBox: `0 0 ${W} ${H}` });
    txt("title", {}, doc.title_block.title || baseName(), out);
    txt("style", {}, EXPORT_CSS, out);
    drawScene(out, false);
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + new XMLSerializer().serializeToString(out);
  }

  function printSheet() {
    const [W, H] = sheetSize();
    const win = window.open("", "_blank");
    if (!win) { alert("The browser blocked the print window. Allow pop-ups for this page, or use SVG."); return; }
    const svgText = exportSVG().replace(/^<\?xml[^>]*>\n/, "");
    win.document.write(`<!doctype html><html><head><title>${baseName()}</title><style>
      @page { size: ${W / 100}in ${H / 100}in; margin: 0 }
      html, body { margin: 0; background: #fff }
      svg { width: 100vw; height: auto; display: block }
      </style></head><body>${svgText}<script>onload = () => { print(); }<\/script></body></html>`);
    win.document.close();
  }

  // --- opening and saving ---

  async function newDoc() {
    if (dirty() && !confirm("Discard the changes to this drawing?")) return;
    const r = await api("GET", "/api/new");
    loadDoc(r.data, { name: null, base: null, example: false });
  }

  function loadDoc(d, proj) {
    doc = d;
    project = proj;
    savedSnap = snapshot();
    undoStack = []; redoStack = [];
    sel = new Set(); draft = null; drag = null; ercResult = null; ercFocus = null; propsKey = null;
    $("#erc").hidden = true;
    if (proj.name && !proj.example) lsSet("airsys.last", proj.name);
    updateTitle();
    fit();
    renderAll();
  }

  async function openDoc(kind, name, quiet) {
    const r = await api("GET", `/api/${kind}/${encodeURIComponent(name)}`);
    if (!r.ok) { if (!quiet) alert(r.data.error); return false; }
    loadDoc(r.data.doc, { name, base: r.data.base, example: kind === "examples" });
    return true;
  }

  async function showOpen() {
    const r = await api("GET", "/api/projects");
    if (!r.ok) { alert(r.data.error); return; }
    const list = $("#open-list");
    list.replaceChildren();
    const dlg = $("#open-dlg");
    const section = (title, items, kind) => {
      list.append(h("h3", {}, title));
      if (!items.length) list.append(h("p", {}, kind === "projects" ? "No drawings saved yet." : "None."));
      for (const it of items) {
        list.append(h("button", { type: "button", onclick: async () => {
          if (dirty() && !confirm("Discard the changes to this drawing?")) return;
          dlg.close();
          await openDoc(kind, it.name);
        } }, it.name, h("small", {}, new Date(it.modified * 1000).toLocaleString())));
      }
    };
    section("Your drawings", r.data.projects, "projects");
    section("Examples", r.data.examples, "examples");
    dlg.showModal();
  }

  async function save(asNew) {
    let name = project.name;
    let fresh = asNew || !name || project.example;
    if (fresh) {
      name = prompt("Save as:", name || doc.title_block.title || "untitled");
      if (!name) return;
      name = name.trim();
      const list = await api("GET", "/api/projects");
      if (list.ok && list.data.projects.some(p => p.name === name) &&
          !confirm(`There is already a drawing called ${name}. Replace it?`)) return;
    }
    const send = force => api("PUT", `/api/projects/${encodeURIComponent(name)}${force ? "?force=1" : ""}`, doc,
      !fresh && project.base ? { "X-AIRsys-Base": project.base } : {});
    let r = await send(fresh);
    if (r.status === 409) {
      if (!confirm(r.data.error + ". Save over it anyway?")) return;
      r = await send(true);
    }
    if (!r.ok) { alert(r.data.error); return; }
    project = { name, base: r.data.base, example: false };
    savedSnap = snapshot();
    lsSet("airsys.last", name);
    updateTitle();
    hint("Saved " + name + ".");
  }

  // --- pointer and keys ---

  svg.addEventListener("contextmenu", e => e.preventDefault());

  svg.addEventListener("pointerdown", e => {
    const raw = toWorld(e);
    rawMouse = raw;
    const p = snap(raw);
    mouse = p;
    if (e.button === 1 || (e.button === 0 && spaceDown)) {
      drag = { type: "pan", sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
      svg.classList.add("panning");
      capture(e);
      e.preventDefault();
      return;
    }
    if (e.button === 2) {
      if (drag && drag.follow) endDrag(true);
      else if (tool === "wire" && draft) finishWire();
      else if (tool !== "select") setTool("select");
      return;
    }
    if (e.button !== 0) return;
    if (drag && drag.follow) { endDrag(false); return; }
    if (tool === "place") return placePart(p);
    if (tool === "wire") return wireClick(p);
    if (tool === "label") return addLabel(p);
    if (tool === "text") return addNote(p);

    const hit = hitTest(raw);
    capture(e);
    if (hit && hit.kind === "port") {
      // a line from an open port; when it is done, back to selecting
      setTool("wire");
      wireClick(hit.xy);
      draft.thenSelect = true;
      return;
    }
    if (hit && hit.kind === "vertex") {
      const w = find(hit.id).obj;
      drag = { type: "vertex", wire: w, index: hit.index, orig: w.pts.map(q => q.slice()), start: p, before: snapshot() };
      return;
    }
    if (hit && hit.kind === "field") {
      const part = find(hit.id).obj;
      sel = new Set([part.id]);
      drag = { type: "field", part, orig: (part.ref_off || [0, 0]).slice(), start: p, before: snapshot() };
      renderAll();
      return;
    }
    if (hit) {
      if (e.shiftKey || e.ctrlKey) { sel.has(hit.id) ? sel.delete(hit.id) : sel.add(hit.id); renderAll(); return; }
      if (!sel.has(hit.id)) sel = new Set([hit.id]);
      startMove(p, false);
      renderAll();
      return;
    }
    if (!e.shiftKey && !e.ctrlKey) sel.clear();
    drag = { type: "rubber", start: raw };
    renderAll();
  });

  svg.addEventListener("pointermove", e => {
    const raw = toWorld(e);
    rawMouse = raw;
    mouse = snap(raw);
    if (!drag) {
      const port = G.allPorts(doc, SYMS).find(q => Math.hypot(q.xy[0] - raw[0], q.xy[1] - raw[1]) <= Math.max(1.5, 5 / view.s));
      if (port) hint(`${port.sym.virtual ? port.sym.name : (port.part.ref || "?")} port ${port.n} (${port.kind})`);
      else hint(placing && tool === "place" ? placing.sym.name + ": " + HINTS.place : HINTS[tool]);
      renderOverlay();
      return;
    }
    if (drag.type === "pan") {
      view.x = drag.vx - (e.clientX - drag.sx) / view.s;
      view.y = drag.vy - (e.clientY - drag.sy) / view.s;
      applyView();
      renderOverlay();
      return;
    }
    if (drag.type === "rubber") { renderOverlay(); return; }
    const d = [mouse[0] - drag.start[0], mouse[1] - drag.start[1]];
    if (drag.type === "move") applyMove(d);
    else if (drag.type === "vertex") {
      const pts = drag.orig.map(q => q.slice());
      pts[drag.index] = [pts[drag.index][0] + d[0], pts[drag.index][1] + d[1]];
      drag.wire.pts = pts;
    } else if (drag.type === "field") {
      drag.part.ref_off = [drag.orig[0] + d[0], drag.orig[1] + d[1]];
    }
    renderAll();
  });

  svg.addEventListener("pointerup", () => {
    if (!drag || drag.follow) return;
    if (drag.type === "vertex") drag.wire.pts = G.tidy(drag.wire.pts);
    endDrag(false);
  });

  svg.addEventListener("dblclick", e => {
    if (tool === "wire") { finishWire(); return; }
    if (tool !== "select") return;
    const hit = hitTest(toWorld(e));
    if (!hit) return;
    const it = find(hit.id);
    if (!it) return;
    if (it.kind === "label" || it.kind === "text") {
      const s = prompt(it.kind === "label" ? "Net label:" : "Note:", it.obj.text);
      if (s && s.trim()) change(() => { it.obj.text = it.kind === "label" ? s.trim().slice(0, 64) : s; });
    } else if (it.kind === "part") {
      const f = $("#prop-ref") || $("#prop-value");
      if (f) { f.focus(); f.select(); }
    }
  });

  svg.addEventListener("wheel", e => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    zoomAt(Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0015)), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });

  function typing(e) {
    const t = e.target;
    return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
  }

  document.addEventListener("keydown", e => {
    if (typing(e)) {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    const k = e.key, ctrl = e.ctrlKey || e.metaKey;
    if (ctrl) {
      const lk = k.toLowerCase();
      if (lk === "z" && !e.shiftKey) { undo(); e.preventDefault(); }
      else if (lk === "y" || (lk === "z" && e.shiftKey)) { redo(); e.preventDefault(); }
      else if (lk === "s") { save(e.shiftKey); e.preventDefault(); }
      else if (lk === "o") { showOpen(); e.preventDefault(); }
      else if (lk === "d") { duplicateSel(); e.preventDefault(); }
      else if (lk === "a") { sel = new Set(allItems().map(i => i.obj.id)); renderAll(); e.preventDefault(); }
      return;
    }
    if (k === " ") { spaceDown = true; svg.classList.add("pan"); e.preventDefault(); return; }
    if (k === "Escape") {
      if (drag && drag.follow) endDrag(true);
      else if (draft) finishWire();
      else if (tool !== "select") setTool("select");
      else { sel.clear(); renderAll(); }
      return;
    }
    if (k === "Backspace" && draft) {
      if (draft.pts.length > 1) draft.pts.pop(); else draft = null;
      renderOverlay();
      e.preventDefault();
      return;
    }
    if (k === "Delete" || k === "Backspace") { deleteSel(); e.preventDefault(); return; }
    if (k === "/" && draft) { draft.posture ^= 1; renderOverlay(); e.preventDefault(); return; }
    switch (k.toLowerCase()) {
      case "w": setTool("wire"); break;
      case "l": setTool("label"); break;
      case "t": setTool("text"); break;
      case "a": { const s = $("#lib-search"); s.focus(); s.select(); e.preventDefault(); break; }
      case "r": rotateSel(); break;
      case "x": mirrorSel(); break;
      case "m": if (sel.size && !drag) { startMove(mouse, true); hint("Moving: click to put it down, Esc to put it back."); } break;
      case "e": { const f = $("#prop-ref") || $("#prop-value"); if (f) { f.focus(); f.select(); e.preventDefault(); } break; }
      case "home": fit(); break;
      case "+": case "=": zoomAt(1.25); break;
      case "-": case "_": zoomAt(0.8); break;
      case "?": $("#help-dlg").showModal(); break;
    }
  });
  document.addEventListener("keyup", e => {
    if (e.key === " ") { spaceDown = false; svg.classList.remove("pan"); }
  });

  window.addEventListener("beforeunload", e => {
    if (dirty()) { e.preventDefault(); e.returnValue = ""; }
  });
  window.addEventListener("resize", () => { applyView(); renderOverlay(); });

  // --- buttons ---

  function wireButtons() {
    const on = (id, fn) => $(id).addEventListener("click", fn);
    on("#b-new", newDoc);
    on("#b-open", showOpen);
    on("#b-save", () => save(false));
    on("#b-saveas", () => save(true));
    on("#b-undo", undo);
    on("#b-redo", redo);
    on("#b-check", runCheck);
    on("#b-renumber", renumber);
    on("#b-bom", async () => { const r = await check(); if (r) download(baseName() + "-bom.csv", r.bom_csv, "text/csv"); });
    on("#b-netlist", async () => { const r = await check(); if (r) download(baseName() + ".net.txt", r.netlist, "text/plain"); });
    on("#b-svg", () => download(baseName() + ".svg", exportSVG(), "image/svg+xml"));
    on("#b-print", printSheet);
    on("#b-rotate", rotateSel);
    on("#b-mirror", mirrorSel);
    on("#b-delete", deleteSel);
    on("#b-fit", fit);
    on("#b-zin", () => zoomAt(1.25));
    on("#b-zout", () => zoomAt(0.8));
    on("#b-help", () => $("#help-dlg").showModal());
    on("#erc-close", () => { $("#erc").hidden = true; ercResult = null; ercFocus = null; renderAll(); });
    on("#b-theme", () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      lsSet("airsys.theme", root.dataset.theme);
    });
    document.querySelectorAll("#tools [data-tool]").forEach(b => b.addEventListener("click", () => setTool(b.dataset.tool)));
    const search = $("#lib-search");
    search.addEventListener("input", buildLibrary);
    search.addEventListener("keydown", e => {
      if (e.key === "Enter") { const first = buildLibrary(); if (first) { startPlace(first); search.blur(); } }
    });
  }

  // --- start ---

  async function boot() {
    const theme = lsGet("airsys.theme");
    if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
    svg.innerHTML = "";
    const defs = el("defs", {}, svg);
    gridPat = el("pattern", { id: "gridpat", patternUnits: "userSpaceOnUse", width: 10, height: 10 }, defs);
    gridDot = el("circle", { cx: 5, cy: 5, r: 0.8, class: "grid-dot" }, gridPat);
    el("rect", { x: 0, y: 0, width: "100%", height: "100%", class: "desk" }, svg);
    world = el("g", {}, svg);
    sceneG = el("g", {}, world);
    overlayG = el("g", {}, world);

    const lib = await api("GET", "/api/library");
    LIB = lib.data;
    GRID = LIB.grid;
    for (const s of LIB.symbols) SYMS[s.id] = s;
    buildLibrary();
    wireButtons();
    setTool("select");

    // #open=<name> or #example=<name> in the address opens that drawing
    const m = /^#(open|example)=(.+)$/.exec(location.hash);
    if (m && await openDoc(m[1] === "open" ? "projects" : "examples", decodeURIComponent(m[2]))) return;
    const last = lsGet("airsys.last");
    if (!(last && await openDoc("projects", last, true))) {
      const r = await api("GET", "/api/new");
      loadDoc(r.data, { name: null, base: null, example: false });
      hint("A new sheet. Pick a symbol on the right, or Open an example to see a finished drawing.");
    }
  }

  /* For the browser test, and for poking at a drawing from the console. */
  window.AirEditor = {
    get doc() { return doc; },
    get selection() { return [...sel]; },
    toScreen(x, y) {
      const r = svg.getBoundingClientRect();
      return [r.left + (x - view.x) * view.s, r.top + (y - view.y) * view.s];
    },
    renderAll, exportSVG, fit,
  };
  boot().catch(err => { console.error(err); hint("AIRsys could not start: " + err.message); });
})();
