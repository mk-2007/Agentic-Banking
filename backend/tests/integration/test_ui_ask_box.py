"""Browser test: a signed-in user can type in "Ask the bank" and gets a reply (regression: a key handler
returned false and cancelled every keystroke). Skipped when Playwright or Chrome is missing."""

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[3]
PORT = "8766"


@pytest.fixture
def server():
    env = dict(os.environ, NEXA_API_TOKENS="tc:ayesha:customer:cust_010,te:ana:fraud_analyst")
    cmd = [sys.executable, str(ROOT / "scripts" / "run_api.py"), "--port", PORT, "--no-monitor"]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    yield f"http://127.0.0.1:{PORT}/"
    proc.kill()


@pytest.mark.parametrize("token", ["tc", "te"])
def test_user_can_type_and_ask(server: str, token: str) -> None:
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(channel="chrome")
        except Exception:
            pytest.skip("Chrome is not available")
        page = browser.new_page()
        page.goto(server)
        page.fill("#token", token)
        page.click("#connect")
        page.get_by_role("button", name="Ask the bank").click()
        box = page.locator(".ask input")
        box.click()
        page.keyboard.type("how do I report a stolen card?")
        assert box.input_value() == "how do I report a stolen card?"
        page.keyboard.press("Enter")
        page.wait_for_selector(".passage, .stage p.mute, #stage p.mute")
        assert page.locator("#msg").inner_text() == ""
        browser.close()
