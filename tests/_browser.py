"""The smallest devtools client that will load a page and run a script in it.

For tests that need a real browser: whether the editor's script runs, and
what it does when a person clicks, nothing short of a JavaScript engine can
say. Pure Python - the websocket handshake, masked client frames and a few
devtools calls - so the tests need nothing installed beyond the browser.

    from _browser import evaluate
    value = evaluate("http://127.0.0.1:8091/", "typeof AirEditor")

Nothing here waits for ever. A page that stops answering fails the test
after ANSWER_S with a line that says so, rather than hanging it.
"""

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request

ANSWER_S = 60.0     # the longest the browser may be silent before the test fails


class PageSilent(RuntimeError):
    """The browser stopped answering: the test fails rather than hangs."""


class _LaunchFlake(Exception):
    """Chromium did not come up this time; the launch is worth retrying."""


def available():
    """A Chromium-family browser that actually runs, or None. Ubuntu can have
    a chromium-browser that only prints "install the snap", so each one is
    asked for its version before it is trusted."""
    for name in ("chromium", "google-chrome-stable", "google-chrome", "chrome",
                 "chromium-browser"):
        path = shutil.which(name)
        if not path:
            continue
        try:
            if subprocess.run([path, "--version"], capture_output=True,
                              timeout=20).returncode == 0:
                return path
        except Exception:
            pass
    if os.name == "nt":
        # Edge is Chromium and is on every Windows machine. Not asked for its
        # version: on Windows that opens a tab in the person's browser.
        for env, tail in (("ProgramFiles(x86)", r"Microsoft\Edge\Application\msedge.exe"),
                          ("ProgramFiles", r"Microsoft\Edge\Application\msedge.exe"),
                          ("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
                          ("LocalAppData", r"Google\Chrome\Application\chrome.exe")):
            base = os.environ.get(env)
            if base and os.path.isfile(os.path.join(base, tail)):
                return os.path.join(base, tail)
    return None


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def evaluate(url, js, width=1024, height=600, settle=1.0, out=None):
    """Load url in a headless Chromium, wait for it to load and then settle
    seconds more, and return the value of js (a promise is awaited). out
    writes a PNG of the page as well."""
    chromium = available()
    if not chromium:
        raise RuntimeError("no Chromium or Chrome on this machine")
    last = None
    for _ in range(3):          # a cold Chromium sometimes dies at launch
        try:
            return _run(chromium, url, js, width, height, settle, out, _free_port())
        except _LaunchFlake as e:
            last = e
            time.sleep(0.5)
    raise SystemExit(str(last))


def _run(chromium, url, js, w, h, settle, out, port):
    profile = tempfile.mkdtemp(prefix="airsys-browser-")
    proc = subprocess.Popen(
        [chromium, "--headless=new", "--disable-gpu", "--no-sandbox", "--disable-dev-shm-usage",
         "--remote-debugging-port=%d" % port, "--user-data-dir=" + profile, "--no-first-run",
         "--window-size=%d,%d" % (w, h), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(200):
            try:
                targets = json.load(urllib.request.urlopen("http://127.0.0.1:%d/json" % port))
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise _LaunchFlake("Chromium never answered on its debugging port")
        path = page["webSocketDebuggerUrl"].split(":%d" % port, 1)[1]
        s = socket.create_connection(("127.0.0.1", port))
        s.settimeout(ANSWER_S)
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(("GET %s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
                   "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n" % (path, port, key)).encode())
        buf = b""

        def fill():
            nonlocal buf
            try:
                chunk = s.recv(65536)
            except socket.timeout:
                raise PageSilent("the browser said nothing for %.0f s (%s)" % (ANSWER_S, url)) from None
            if not chunk:
                raise PageSilent("the browser closed the connection (%s)" % url)
            buf += chunk

        while b"\r\n\r\n" not in buf:
            fill()
        buf = buf.split(b"\r\n\r\n", 1)[1]

        def send(obj):
            data = json.dumps(obj).encode()
            mask = os.urandom(4)
            n = len(data)
            if n < 126:
                head = bytes([0x81, 0x80 | n])
            elif n < 65536:
                head = bytes([0x81, 0x80 | 126]) + struct.pack(">H", n)
            else:
                head = bytes([0x81, 0x80 | 127]) + struct.pack(">Q", n)
            s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

        def recv():
            nonlocal buf
            while len(buf) < 2:
                fill()
            n, off = buf[1] & 0x7F, 2
            if n == 126:
                while len(buf) < 4:
                    fill()
                n, off = struct.unpack(">H", buf[2:4])[0], 4
            elif n == 127:
                while len(buf) < 10:
                    fill()
                n, off = struct.unpack(">Q", buf[2:10])[0], 10
            while len(buf) < off + n:
                fill()
            payload, buf = buf[off:off + n], buf[off + n:]
            return json.loads(payload)

        dialogs = [0]

        def call(ident, method, **params):
            send({"id": ident, "method": method, "params": params})
            while True:
                msg = recv()
                # alert(), confirm() or prompt() with nobody to answer: answer
                # Cancel at once, or headless Chromium can take the page down
                if msg.get("method") == "Page.javascriptDialogOpening":
                    dialogs[0] += 1
                    send({"id": 9000 + dialogs[0], "method": "Page.handleJavaScriptDialog",
                          "params": {"accept": False}})
                    continue
                if msg.get("method") == "Inspector.targetCrashed":
                    raise RuntimeError("the page crashed under the test")
                if msg.get("id") == ident:
                    return msg.get("result", msg)

        call(1, "Page.enable")
        call(2, "Emulation.setDeviceMetricsOverride", width=w, height=h,
             deviceScaleFactor=1, mobile=False)
        call(3, "Page.navigate", url=url)
        waited = 0.0
        while waited < 15.0:
            ready = call(4, "Runtime.evaluate", returnByValue=True, expression="document.readyState")
            if (ready.get("result") or {}).get("value") == "complete":
                break
            time.sleep(0.1)
            waited += 0.1
        time.sleep(settle)
        value = None
        if js:
            got = call(5, "Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
            value = (got.get("result") or {}).get("value")
            if got.get("exceptionDetails"):
                value = "EXCEPTION " + str(got["exceptionDetails"].get("text"))
        if out:
            shot = call(6, "Page.captureScreenshot", format="png")
            with open(out, "wb") as f:
                f.write(base64.b64decode(shot["data"]))
        return value
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
