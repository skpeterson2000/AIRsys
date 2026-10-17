# AIRsys

AIRsys draws compressed-air systems the way KiCad draws circuits. You place
pneumatic symbols from a library, join their ports with lines, and number
the parts. It then checks the drawing for open ports and loose lines, and
gives you a bill of materials and a netlist. It runs as a small server, and
the editor is a page in any browser.

## Running it

Python 3.11 or later, standard library only. Nothing to install.

    ./airsys.py                      # then open http://localhost:8091/
    ./airsys.py --projects ~/air     # keep drawings somewhere else
    ./airsys.py --host 0.0.0.0       # let other machines on the network in

Drawings are saved as `<name>.airsys.json` in `projects/`, one file each,
so they can be copied, backed up and kept in git. The drawing before each
save is kept beside it as `.bak`. **Open → Examples** has a finished
drawing to look at first.

## What it does

- **A library of 32 symbols in the shapes of ISO 1219-1**: supply,
  compressor, receiver, filter, regulator, lubricator, service unit;
  3/2, 5/2 and 5/3 valves with solenoid, push button, roller, air pilot and
  spring actuators; shut-off, check, throttle, one-way flow control, relief
  and shuttle valves; single- and double-acting cylinders, air motor; gauge
  and pressure switch; silencer, exhaust, coupling and plug. Port numbers
  follow ISO 5599 (1 supply, 2 and 4 working, 3 and 5 exhaust, 12 and 14
  pilot).
- **Drawing as in KiCad**: a 100 mil grid. A places a part, W draws a line,
  R rotates, X mirrors, M or a drag moves a part, and its lines stay
  attached and square. L adds a net label, T a note, E edits, Ctrl+D
  duplicates, and Ctrl+Z undoes. Clicking a port's open circle starts a
  line from it. Lines are working, pilot or exhaust lines (solid, long
  dashes, short dashes).
- **Connections are shown as you draw**: a dot where lines join, a small
  circle on a port nothing is connected to, a square on a line end that
  joins nothing.
- **Check** (the KiCad ERC, for air) lists:
  - **errors**: duplicate or missing numbers, and a supply piped straight
    to an exhaust port
  - **warnings**: ports nothing is connected to, and lines that end on
    nothing
  - **notes**: exhaust ports left open to vent

  Click an entry to go to it.
- **Numbering**: new parts take the next free number for their letter
  (ISO 1219-2: A actuator, M motor, P compressor, S sensor, V valve, Z
  other). **Renumber** numbers everything again, top to bottom.
- **Output**: a bill of materials as CSV, with any fields you add (part
  number, supplier, port size…); a netlist as text; the sheet as SVG; and
  printing. Every drawing has a frame with zones and a title block, on
  A4, A3, Letter or Tabloid.

## Tests

    for t in tests/test_*.py; do python3 "$t" >/dev/null || echo "FAIL $t"; done

`test_geometry_js.py` needs Node.js, and `test_editor_browser.py` needs
Chromium or Chrome. Each fails and says so if what it needs is missing.

## Not done yet

- More than one sheet per drawing, and hierarchical sheets.
- Electrical control circuits beside the pneumatic one: the solenoids have
  no coil connections yet.
- Copy and paste between drawings. Ctrl+D duplicates within one.
- A symbol editor. Symbols are written in `airsys/library.py`.
- Simulation: AIRsys draws and checks a circuit, it does not run one.
