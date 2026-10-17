# AIRsys design notes

The reasoning behind the decisions. When this file and the code disagree,
the code is right and this file has a bug.

## A server and a page

A standard-library HTTP server and a page in the browser. A page gives a
drawing surface (SVG) with zoom, text and printing for free, and it runs
on any machine the server is reachable from. The server holds the files and does the checking, so the rules live
in Python, where they are tested.

There is nothing to install. No JavaScript build step, no framework, and no
library from a CDN, because a workshop machine may have no internet.

## Units and the grid

Schematic units are 0.01 inch (10 mil). The grid is 10 units (100 mil),
KiCad's schematic grid. Every symbol port is on the grid, and
`test_library.py` fails if one is not, because a port off the grid can
never be reached by a snapped line and would show as open for ever.

Sheets are landscape: A4 is 1170 × 830 units, A3 1650 × 1170, Letter
1100 × 850 and Tabloid 1700 × 1100.

## Symbols

Drawn by hand in `library.py` to the shapes of ISO 1219-1, as primitives
(lines, polygons, rectangles, circles, paths and text) about the symbol's
own origin. They are not traced from the standard. A few are simplified:

- the service unit is one box holding a filter diamond, a regulator arrow
  and a gauge, not the full detailed symbol
- the lubricator's drop is a small filled triangle
- the silencer is a box with two bars
- the air supply is a circle holding a hollow triangle

Valve squares are 30 units (3/2) or 40 units (5/2, 5/3) wide. The ports are
drawn on the square for the unactuated position, the one next to the
spring, as ISO draws them. Each port is numbered to ISO 5599.

A symbol's text (port numbers, the M of a motor) is turned with the part
but drawn upright, as KiCad draws pin numbers. The reference designator
and value go at the symbol's `ref_at`. You can drag them; the drag is kept
as an offset (`ref_off`), so turning the part still moves them with it.

## What joins what

KiCad's rules, in `schematic.py` and again in `static/geometry.js`:

- a line's end that lies anywhere on another line joins them; lines that
  only cross do not
- a port joins a line that ends on it or runs through it, and any other
  part's port at the same point
- a label joins whatever it sits on, and every label with the same text
  is one net
- every supply symbol with the same value is one net, as KiCad's power
  symbols are, so "6 bar" in two corners of the sheet is one supply

A dot is drawn where three or more things meet: a line ending there counts
one, a line running through counts two, a port counts one. That rule is
KiCad's too.

The browser needs these rules live, to draw dots and open-port circles as
you draw, and the server needs them for the check. So they are written
twice, and `test_geometry_js.py` runs both on the same drawings and fails
if they disagree.

## The check

KiCad's ERC, for air. Its levels mean what would happen on the bench:

- **error**: the circuit cannot be built as drawn, or blows air. Two parts
  with one number, a part with no number, a supply piped straight to an
  exhaust port, a symbol missing from the library.
- **warning**: probably a mistake. A port nothing is connected to (it
  would blow air, or the air would go nowhere), a line that ends on
  nothing, a label on nothing, a net with two names, a sheet with no
  supply.
- **note**: fine if meant. An open exhaust port (3 or 5) vents, which is
  what it is for. A silencer or the exhaust mark on it says it is meant,
  and the note goes away.

## Moving keeps lines attached

When a part moves, every line ending on one of its ports moves its end
with it. The corner next to that end moves too, so the first run stays
horizontal or vertical. A two-point line gets an elbow. Then `tidy()` puts
in any elbow still needed and takes out points in a straight run. This is
KiCad's drag (G), and AIRsys does it on every move, because a move that
tears lines off ports is almost never what is meant.

## Files

One drawing, one JSON file, `<name>.airsys.json`, written to a temporary
file and moved into place, so a crash mid-save never leaves half a
drawing. The previous version is copied to `.bak` first.

Each save sends back the file's modification time, and the next save sends
it again. If the file changed in between (another window saved it), the
save is refused with a 409, and the page asks before saving over it. Two
windows on one drawing cannot quietly undo each other's work.

The format carries a version number. A drawing from a newer AIRsys is
refused, not misread.

## The page

- Every change goes through `change()`, which keeps a snapshot for undo
  (300 deep) and redraws the sheet from the document. Drawings are small
  enough that redrawing everything is simpler, and fast enough.
- Text a person typed (references, values, labels, notes) reaches the
  page only as `textContent`, never as markup.
- Colors are KiCad's habit: symbols red-brown, lines green, labels blue.
  There are light and dark themes. Export and print are always on white.
- The address `#example=<name>` or `#open=<name>` opens a drawing, so a
  drawing can be bookmarked.
