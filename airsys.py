#!/usr/bin/env python3
"""AIRsys: draw compressed-air systems the way KiCad draws circuits.

    ./airsys.py                     editor at http://localhost:8091/
    ./airsys.py --projects DIR      keep drawings in DIR (default ./projects)
    ./airsys.py --host 0.0.0.0      let other machines on the network in
"""

import argparse
import logging
import sys
from pathlib import Path

from airsys import server

HERE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser(description="pneumatic schematic editor")
    ap.add_argument("--host", default="127.0.0.1",
                    help="address to listen on (default 127.0.0.1, this machine only)")
    ap.add_argument("--port", type=int, default=8091)
    ap.add_argument("--projects", type=Path, default=HERE / "projects",
                    help="where drawings are kept")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("airsys")

    httpd = server.AirServer((args.host, args.port), args.projects)
    shown = "localhost" if args.host in ("0.0.0.0", "127.0.0.1") else args.host
    log.info("editor at http://%s:%d/, drawings in %s", shown, args.port,
             httpd.projects.resolve())
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
