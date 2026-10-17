"""The shared check() the test scripts use. Each test prints its checks in
order and exits non-zero if any failed: run one with python3 tests/test_x.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + label + ("" if ok else "  got %r, want %r" % (got, want)))
    if not ok:
        FAILS.append(label)


def finish():
    if FAILS:
        print("\n%d check(s) failed" % len(FAILS))
        sys.exit(1)
    print("\nall checks passed")
