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
    from paytwin_sim.demo import make_db, run_flagship, seed_history, seed_world

    db = make_db()
    try:
        seeded = seed_world(db)
        # Exercise the UI against the same coherent money story used in the
        # local showcase: a detected incident, bounded action, matched-control
        # batch, one blocked action, and one automatic rollback.  A bare world
        # hides these pages behind empty-state placeholders and cannot validate
        # the end-to-end product path.
        seed_history(db, seeded["org_id"], seed=42, hours=1.5, only=("mgro",))
        run_flagship(db, seeded["org_id"], seed=42)
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
    tempdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        tempdir = tempfile.TemporaryDirectory(prefix="paytwin-served-e2e-")
        directory = tempdir.name
        if tempdir is not None:  # keeps the isolated browser/server block scoped
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
            cdp.evaluate("location.reload(); true")
            wait_for("workspace session survives a browser refresh", lambda: cdp.evaluate(
                "window.__PTW_LIVE === true && window.__paytwinHasAuth === true && !!document.querySelector('.app')"))
            if cdp.evaluate("document.cookie.includes('paytwin_workspace')"):
                raise AssertionError("workspace session cookie must be HttpOnly")
            print("PASS workspace session is refresh-stable and HttpOnly")

            cdp.evaluate("document.querySelector('[data-p=\"integrations\"]').click(); true")
            wait_for("local payment lifecycle renders", lambda: cdp.evaluate(
                "!!document.querySelector('[data-act=\"localOrder\"]')"))
            cdp.evaluate("document.querySelector('[data-act=\"localOrder\"]').click(); true")
            wait_for("local order enables payment capture", lambda: cdp.evaluate(
                "!!S.localRzp.order && !document.querySelector('[data-act=\"localCapture\"]').disabled"))
            cdp.evaluate("document.querySelector('[data-act=\"localCapture\"]').click(); true")
            wait_for("local capture enables Checkout verification", lambda: cdp.evaluate(
                "!!S.localRzp.payment && !document.querySelector('[data-act=\"localVerify\"]').disabled"))
            cdp.evaluate("document.querySelector('[data-act=\"localVerify\"]').click(); true")
            wait_for("Checkout verification enables fulfilment", lambda: cdp.evaluate(
                "S.localRzp.verified === true && !document.querySelector('[data-act=\"localFulfil\"]').disabled"))
            cdp.evaluate("document.querySelector('[data-act=\"localFulfil\"]').click(); true")
            wait_for("one fulfilment is recorded", lambda: cdp.evaluate(
                "S.localRzp.fulfilled === true && document.body.innerText.includes('Fulfilment recorded exactly once')"))
            if not cdp.evaluate("document.querySelector('[data-act=\"localCapture\"]').disabled && document.querySelector('[data-act=\"localVerify\"]').disabled && document.querySelector('[data-act=\"localFulfil\"]').disabled"):
                raise AssertionError("local payment lifecycle kept a completed control actionable")
            if cdp.evaluate("document.querySelector('.toastwrap').innerText.includes('This control needs a connected local workspace API')"):
                raise AssertionError("local payment lifecycle displayed the stale connection prompt")
            print("PASS local order → capture → verify → fulfilment flow")

            cdp.evaluate("document.querySelector('[data-p=\"reliability\"]').click(); true")
            wait_for("Reliability Lab served", lambda: cdp.evaluate(
                "!!document.querySelector('.reliability-proof')"))
            cdp.evaluate("document.querySelector('[data-act=\"relproof\"][data-stage=\"detect\"]').click(); true")
            wait_for("known defect blocks release", lambda: cdp.evaluate(
                "document.body.innerText.includes('Duplicate fulfilment control caught') && document.body.innerText.includes('FIXTURE BLOCKED')"))
            wait_for("corrected handler becomes actionable", lambda: cdp.evaluate(
                "document.querySelector('[data-act=\"relproof\"][data-stage=\"verify\"]').disabled === false"))
            cdp.evaluate("document.querySelector('[data-act=\"relproof\"][data-stage=\"verify\"]').click(); true")
            wait_for("corrected handler verifies", lambda: cdp.evaluate(
                "document.body.innerText.includes('Correction verified') && document.body.innerText.includes('ONE FULFILMENT VERIFIED')"))
            cdp.evaluate("document.querySelector('[data-act=\"relwh\"][data-k=\"bad_signature\"]').click(); true")
            wait_for("forged signature is rejected in Webhook Lab", lambda: cdp.evaluate(
                "!!S.rel.lastFault && S.rel.lastFault.fault === 'bad_signature' && document.body.innerText.includes('Forged signature rejected')"))
            print("PASS Webhook Lab forged-signature control")

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

            # A connected workspace must never route an opportunity card to the
            # old generic "connect the API" placeholder. The checkout-recovery
            # opportunity now opens its real cohort surface.
            cdp.evaluate(
                "Array.from(document.querySelectorAll('.card')).find(x => x.innerText.includes('Links for 2-failure carts')).querySelector('[data-act=\"nav\"]').click(); true")
            wait_for("checkout recovery opportunity opens its live view", lambda: cdp.evaluate(
                "document.querySelector('.page h1').innerText.includes('Checkout funnel')"))
            cdp.evaluate("document.querySelector('[data-p=\"policies\"]').click(); true")
            wait_for("policy replay control renders", lambda: cdp.evaluate(
                "!!document.querySelector('[data-act=\"policyReplay\"]')"))
            cdp.evaluate("document.querySelector('[data-act=\"polview\"]').click(); true")
            wait_for("policy modal renders the typed API rules", lambda: cdp.evaluate(
                "document.body.innerText.includes('rules:') && !document.body.innerText.includes('(typed rules from API)')"))
            cdp.evaluate("document.querySelector('[data-act=\"ovclose\"]').click(); true")
            cdp.evaluate("document.querySelector('[data-act=\"policyReplay\"]').click(); true")
            wait_for("connected policy replay responds", lambda: cdp.evaluate(
                "document.querySelector('.toastwrap').innerText.trim().length > 0"))
            replay_message = cdp.evaluate("document.querySelector('.toastwrap').innerText")
            if "Historical replay complete" not in replay_message:
                raise AssertionError(f"connected policy replay failed: {replay_message}")
            if "Connect the local workspace API" in replay_message:
                raise AssertionError("connected policy replay displayed a stale connection prompt")
            print("PASS connected controls use the workspace API, not the stale connection prompt")

            cdp.evaluate("document.querySelector('[data-p=\"overview\"]').click(); true")
            wait_for("Command Center restored after control check", lambda: cdp.evaluate(
                "document.querySelector('.page h1').innerText.includes('Organization view')"))
            cdp.evaluate("document.querySelector('[data-act=\"verifyAudit\"]').click(); true")
            wait_for("connected audit verification responds", lambda: cdp.evaluate(
                "document.querySelector('.toastwrap').innerText.trim().length > 0"))
            audit_message = cdp.evaluate("document.querySelector('.toastwrap').innerText")
            if "Audit chain verified" not in audit_message:
                raise AssertionError(f"connected audit verification failed: {audit_message}")
            print("PASS audit verification uses the connected workspace API")
            cdp.evaluate("document.querySelector('[data-act=\"launchFlow\"]').click(); true")
            wait_for("operational flow opens Twin Lab", lambda: cdp.evaluate(
                "document.querySelector('.page h1').innerText.includes('Scenario Lab')"))
            wait_for("served forecast completes", lambda: cdp.evaluate(
                "document.body.innerText.includes('Pre-incident scenario forecast')"), timeout=20)
            cdp.evaluate("document.querySelector('[data-act=\"surgeInject\"]').click(); true")
            wait_for("scenario injection advances the operational flow", lambda: cdp.evaluate(
                "S.flowStep >= 2"), timeout=25)
            wait_for("scenario injection reports verified events", lambda: cdp.evaluate(
                "document.querySelector('.toastwrap').innerText.includes('Scenario events introduced')"), timeout=10)
            injection_message = cdp.evaluate("document.querySelector('.toastwrap').innerText")
            if "connected local workspace API" in injection_message:
                raise AssertionError("scenario injection displayed a stale connection prompt")
            print("PASS connected scenario injection uses the workspace API")

            cdp.evaluate("document.querySelector('[data-p=\"experiments\"]').click(); true")
            wait_for("recovery money-proof screen renders", lambda: cdp.evaluate(
                "document.body.innerText.includes('Net incremental GMV') && "
                "document.body.innerText.includes('Why not a payment optimizer alone?')"))
            cdp.evaluate("document.querySelector('[data-act=\"batchReport\"]').click(); true")
            wait_for("downloadable recovery report opens with money proof", lambda: cdp.evaluate(
                "document.body.innerText.includes('Recovery Batch Report') && document.body.innerText.includes('net incremental GMV') && document.body.innerText.includes('stopping events') && document.body.innerText.includes('audit references')"))
            cdp.evaluate("document.querySelector('[data-recovery-report] [data-act=\"ovclose\"]').click(); true")

            cdp.evaluate("S.inc = 0; document.querySelector('[data-p=\"commander\"]').click(); true")
            wait_for("Commander renders an empty live evidence context", lambda: cdp.evaluate(
                "document.body.innerText.includes('Choose a question to retrieve current, cited workspace evidence.')"))
            cdp.evaluate("document.querySelector('[data-q=\"Why this action?\"]').click(); true")
            wait_for("Commander receives its live tool trace", lambda: cdp.evaluate(
                "Array.isArray(S.cmdTrace) && S.cmdTrace.length > 0"))
            if not cdp.evaluate(
                    "(() => { const chat = document.querySelector('#chatbox'); const trace = document.querySelector('#trace'); const selected = (INC[S.inc] || INC[0] || {}).id || ''; return !!chat && !!trace && !!selected && chat.innerText.includes(selected) && trace.innerText.includes(selected); })()"):
                raise AssertionError("Commander response or trace did not retain the selected incident")
            print("PASS Commander keeps its selected incident in the answer")
            cdp.evaluate("document.querySelector('[data-q=\"How much was recovered?\"]').click(); true")
            wait_for("Commander reports recovery money proof instead of a payment count", lambda: cdp.evaluate(
                "(() => { const chat = document.querySelector('#chatbox'); return !!chat && chat.innerText.includes('net incremental GMV'); })()"))

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
        if tempdir is not None:
            tempdir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
