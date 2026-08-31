#!/usr/bin/env python3
"""Served-app browser E2E for the authenticated local PayTwin workspace.

This test starts FastAPI on an isolated SQLite database, seeds a scoped local
workspace, then drives Chrome through the Chrome DevTools Protocol. It proves
the browser receives the served application (not ``file://``), authenticates
without retaining the key in its URL, and completes the two judge-facing flows:
the operational forecast and Reliability Lab's defect → correction proof.
"""
from __future__ import annotations

import json
import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from websockets.sync.client import connect


REPO = pathlib.Path(__file__).resolve().parents[1]
CHROME_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
)


def find_chrome() -> str:
    for candidate in CHROME_CANDIDATES:
        if pathlib.Path(candidate).exists():
            return candidate
    raise RuntimeError("Chrome not found")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def fetch_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=2) as response:  # nosec B310: local only
        return json.loads(response.read().decode())


def wait_for(description: str, condition: Callable[[], bool], timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if condition():
                print(f"PASS {description}")
                return
        except Exception as exc:  # browser/server may still be starting
            last_error = exc
        time.sleep(0.15)
    detail = f" ({last_error})" if last_error else ""
    raise AssertionError(f"timeout: {description}{detail}")


class Cdp:
    """Tiny request/response CDP client; avoids adding a browser-test runtime."""

    def __init__(self, websocket_url: str):
        self.ws = connect(websocket_url, open_timeout=10)
        self.message_id = 0

    def close(self) -> None:
        self.ws.close()

    def evaluate(self, expression: str) -> Any:
        self.message_id += 1
        message_id = self.message_id
        self.ws.send(json.dumps({
            "id": message_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        }))
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            message = json.loads(self.ws.recv(timeout=2))
            if message.get("id") != message_id:
                continue
            result = message.get("result", {}).get("result", {})
            if "exceptionDetails" in message.get("result", {}):
                raise RuntimeError(message["result"]["exceptionDetails"].get("text", "browser error"))
            if result.get("subtype") == "error":
                raise RuntimeError(result.get("description", "browser evaluation failed"))
            return result.get("value")
        raise TimeoutError("CDP evaluation timed out")


def seed_workspace(database_url: str) -> str:
    os.environ["PAYTWIN_DATABASE_URL"] = database_url
    os.environ["PAYTWIN_ENV"] = "development"
    os.environ["PAYTWIN_LLM_PROVIDER"] = "none"
    from paytwin_sim.demo import make_db, seed_world

    db = make_db()
    try:
        seeded = seed_world(db)
        return seeded["keys"]["risk_admin"]
    finally:
        db.close()


def start_server(port: int, database_url: str) -> subprocess.Popen[str]:
    environment = os.environ | {
        "PAYTWIN_DATABASE_URL": database_url,
        "PAYTWIN_ENV": "development",
        "PAYTWIN_LLM_PROVIDER": "none",
    }
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "paytwin_api.main:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=REPO, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )


def stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def main() -> int:
    server: subprocess.Popen[str] | None = None
    browser: subprocess.Popen[str] | None = None
    cdp: Cdp | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="paytwin-served-e2e-") as directory:
            temp = pathlib.Path(directory)
            database_url = f"sqlite:///{temp / 'workspace.db'}"
            api_key = seed_workspace(database_url)
            app_port, debug_port = free_port(), free_port()
            server = start_server(app_port, database_url)
            wait_for("FastAPI readiness", lambda: fetch_json(
                f"http://127.0.0.1:{app_port}/api/ready")["status"] == "ready")

            local_url = f"http://127.0.0.1:{app_port}/#key={urllib.parse.quote(api_key, safe='')}"
            browser = subprocess.Popen([
                find_chrome(), "--headless=new", "--disable-gpu", "--no-first-run",
                "--mute-audio", "--remote-allow-origins=*",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={temp / 'chrome-profile'}", local_url,
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_for("Chrome DevTools connection", lambda: bool(fetch_json(
                f"http://127.0.0.1:{debug_port}/json/list")))
            pages = fetch_json(f"http://127.0.0.1:{debug_port}/json/list")
            page = next(item for item in pages if item.get("type") == "page")
            cdp = Cdp(page["webSocketDebuggerUrl"])

            wait_for("served workspace hydration", lambda: cdp.evaluate(
                "window.__PTW_LIVE === true && !!document.querySelector('.app')"))
            wait_for("credential scrubbed from browser URL", lambda: cdp.evaluate(
                "location.search === '' && !/^#key=/.test(location.hash)"))

            cdp.evaluate("document.querySelector('[data-p=\"reliability\"]').click(); true")
            wait_for("Reliability Lab served", lambda: cdp.evaluate(
                "!!document.querySelector('.reliability-proof')"))
            cdp.evaluate("document.querySelector('[data-act=\"relproof\"][data-stage=\"detect\"]').click(); true")
            wait_for("known defect blocks release", lambda: cdp.evaluate(
                "document.body.innerText.includes('Duplicate fulfilment control caught') && document.body.innerText.includes('CRITICAL CONTROL FAILURE')"))
            wait_for("corrected handler becomes actionable", lambda: cdp.evaluate(
                "document.querySelector('[data-act=\"relproof\"][data-stage=\"verify\"]').disabled === false"))
            cdp.evaluate("document.querySelector('[data-act=\"relproof\"][data-stage=\"verify\"]').click(); true")
            wait_for("corrected handler verifies", lambda: cdp.evaluate(
                "document.body.innerText.includes('Correction verified') && document.body.innerText.includes('ONE FULFILMENT VERIFIED')"))

            initial_scroll = cdp.evaluate(
                "const page = document.querySelector('article.page'); page.scrollTop = 500; page.scrollTop")
            if not isinstance(initial_scroll, (int, float)) or initial_scroll < 100:
                raise AssertionError("Reliability Lab did not become scrollable")
            # The connected workspace refreshes every five seconds. A refresh must
            # update data in-place: it must neither return an operator to the top
            # nor remount the page (which visibly flickers every card).
            cdp.evaluate(
                "window.__paytwinPageRef = document.querySelector('article.page'); "
                "window.__paytwinScrollProbe = null; "
                "setTimeout(() => { window.__paytwinScrollProbe = document.querySelector('article.page').scrollTop; }, 5500); true")
            wait_for("scroll probe after live refresh", lambda: cdp.evaluate(
                "window.__paytwinScrollProbe !== null"), timeout=8)
            preserved_scroll = cdp.evaluate("window.__paytwinScrollProbe")
            if not isinstance(preserved_scroll, (int, float)) or preserved_scroll < 100:
                raise AssertionError("live refresh reset the document scroll position")
            print("PASS scroll position survives live refresh")
            if not cdp.evaluate(
                    "window.__paytwinPageRef === document.querySelector('article.page')"):
                raise AssertionError("live refresh remounted the page instead of updating in place")
            print("PASS live refresh updates in place")

            cdp.evaluate("document.querySelector('[data-p=\"overview\"]').click(); true")
            wait_for("Command Center restored", lambda: cdp.evaluate(
                "document.querySelector('.page h1').innerText.includes('Organization view')"))
            cdp.evaluate("document.querySelector('[data-act=\"launchFlow\"]').click(); true")
            wait_for("operational flow opens Twin Lab", lambda: cdp.evaluate(
                "document.querySelector('.page h1').innerText.includes('Scenario Lab')"))
            wait_for("served forecast completes", lambda: cdp.evaluate(
                "document.body.innerText.includes('Pre-incident scenario forecast')"), timeout=20)

            cdp.evaluate("document.querySelector('[data-act=\"theme\"]').click(); true")
            wait_for("light theme has high-contrast text", lambda: cdp.evaluate(
                "document.documentElement.dataset.theme === 'light' && getComputedStyle(document.body).color === 'rgb(17, 24, 39)'"))
            wait_for("no user-facing demo label", lambda: cdp.evaluate(
                "!/\\bdemo\\b/i.test(document.querySelector('#app').innerText)"))
        print("ALL SERVED BROWSER E2E CHECKS PASSED")
        return 0
    finally:
        if cdp is not None:
            cdp.close()
        stop(browser)
        stop(server)


if __name__ == "__main__":
    raise SystemExit(main())
