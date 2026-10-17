"""The editor works in a real browser: place, draw, drag, undo, check.

Driven the way a person drives it, with pointer and key events on the
sheet: pick a 3/2 valve from the library and click it down, place a
cylinder, click the valve's open port to start a line and click the
cylinder's port to end it, drag the valve and see the line follow and stay
square, undo the drag, rotate, and run the check. A page whose script
throws partway would leave the drawing short, and these checks would say
where. Needs Chromium or Chrome; fails, rather than skips, without one.
"""

import json
import tempfile
import threading

from _check import check, finish

import _browser
from airsys import server

if not _browser.available():
    print("FAIL no Chromium or Chrome on PATH: this test needs a real browser")
    raise SystemExit(1)

httpd = server.AirServer(("127.0.0.1", 0), tempfile.mkdtemp(prefix="airsys-browser-"))
threading.Thread(target=httpd.serve_forever, daemon=True).start()
URL = "http://127.0.0.1:%d/" % httpd.server_address[1]

SCRIPT = r"""
(async () => {
  const E = window.AirEditor, svg = document.getElementById("canvas");
  const wait = ms => new Promise(r => setTimeout(r, ms));
  for (let i = 0; i < 100 && !E.doc; i++) await wait(50);
  const out = {};
  const ev = (type, x, y, extra) => {
    const [cx, cy] = E.toScreen(x, y);
    svg.dispatchEvent(new PointerEvent(type, Object.assign(
      {clientX: cx, clientY: cy, button: 0, buttons: 1, bubbles: true, pointerId: 1}, extra || {})));
  };
  const click = (x, y) => { ev("pointerdown", x, y); ev("pointerup", x, y); };
  const key = (k, extra) => document.dispatchEvent(new KeyboardEvent("keydown",
    Object.assign({key: k, bubbles: true}, extra || {})));
  const part = ref => E.doc.parts.find(p => p.ref === ref);

  document.querySelector('[data-sym="valve32_solenoid"]').click();
  ev("pointermove", 300, 300);
  click(300, 300);
  document.querySelector('[data-sym="cylinder_single"]').click();
  click(300, 150);
  key("Escape");
  out.placed = E.doc.parts.map(p => [p.ref, p.sym, p.x, p.y]);

  // the valve's port 2 is at (310, 270), the cylinder's cap port at (270, 170)
  click(310, 270);
  click(270, 170);
  out.wires = E.doc.wires.map(w => w.pts);

  // drag the valve 50 to the right: the line's end follows, the run stays square
  ev("pointerdown", 300, 300); ev("pointermove", 350, 300); ev("pointerup", 350, 300);
  out.afterDrag = [part("V1").x, E.doc.wires[0].pts];
  key("z", {ctrlKey: true});
  out.afterUndo = [part("V1").x, E.doc.wires[0].pts];
  key("y", {ctrlKey: true});
  out.afterRedo = part("V1").x;

  // select the cylinder and turn it
  click(300, 150);
  key("r");
  out.rot = part("A1").rot;
  key("z", {ctrlKey: true});

  // a sheet drawn with nothing joined to the valve's 1 and 3: the check says so
  document.getElementById("b-check").click();
  for (let i = 0; i < 60 && document.getElementById("erc").hidden; i++) await wait(50);
  out.erc = [...document.querySelectorAll("#erc-list li")].map(li => li.textContent);
  out.svg = E.exportSVG().slice(0, 200);
  out.title = document.title;
  return JSON.stringify(out);
})()
"""

raw = _browser.evaluate(URL, SCRIPT, width=1300, height=850, settle=1.0)
try:
    got = json.loads(raw)
except (TypeError, ValueError):
    print("FAIL the page did not answer: %r" % raw)
    raise SystemExit(1)

check("a valve and a cylinder are placed where clicked, numbered",
      got["placed"], [["V1", "valve32_solenoid", 300, 300], ["A1", "cylinder_single", 300, 150]])
check("clicking an open port draws a square line to the next port",
      got["wires"], [[[310, 270], [270, 270], [270, 170]]])
check("dragging the valve brings the line with it, still square",
      got["afterDrag"], [350, [[360, 270], [270, 270], [270, 170]]])
check("undo puts both back", got["afterUndo"], [300, [[310, 270], [270, 270], [270, 170]]])
check("redo does it again", got["afterRedo"], 350)
check("R turns the selected part", got["rot"], 1)
check("the check finds the valve's open supply port",
      any("V1 port 1 is not connected" in e for e in got["erc"]), True)
check("the check finds there is no supply", any("no air supply" in e for e in got["erc"]), True)
check("the sheet exports as SVG", got["svg"].startswith('<?xml version="1.0" encoding="UTF-8"?>\n<svg'),
      True)
check("the window title shows unsaved changes", got["title"].startswith("* untitled"), True)

httpd.shutdown()
finish()
