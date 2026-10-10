"""Commissioning evidence using an installed headless shell, standard library only.

The browser communicates through private process pipes; no server or browser
attachment. Profile cleanup is the caller's responsibility: move it to Trash.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import subprocess
import time


class Pipe:
    def __init__(self, process):
        self.process = process
        self.sequence = 0
        self.buffer = b""
        self.events = []

    def call(self, method, params=None, session=None):
        self.sequence += 1
        packet = {"id": self.sequence, "method": method, "params": params or {}}
        if session:
            packet["sessionId"] = session
        self.process.stdin.write(json.dumps(packet).encode() + b"\0")
        self.process.stdin.flush()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if b"\0" not in self.buffer:
                ready, _, _ = select.select([self.process.stdout], [], [], max(0, deadline - time.monotonic()))
                if not ready:
                    continue
                data = os.read(self.process.stdout.fileno(), 65536)
                if not data:
                    raise RuntimeError("Headless debugging pipe closed")
                self.buffer += data
            while b"\0" in self.buffer:
                message, self.buffer = self.buffer.split(b"\0", 1)
                if not message:
                    continue
                response = json.loads(message)
                if response.get("id") == self.sequence:
                    if "error" in response:
                        raise RuntimeError(response["error"])
                    return response.get("result", {})
                if "method" in response:
                    self.events.append(response)
        raise TimeoutError(method)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--page", type=Path, required=True)
    parser.add_argument("--shots", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    args = parser.parse_args()
    args.profile.mkdir(parents=True, exist_ok=False)
    (args.profile / "Default").mkdir()
    (args.profile / "Default/Preferences").write_text(json.dumps({"profile": {"default_content_setting_values": {"automatic_downloads": 1}}}))
    args.shots.mkdir(parents=True, exist_ok=True)
    downloads = args.profile / "downloads"
    downloads.mkdir()
    log = args.profile / "browser-stderr.log"
    flags = ["--headless", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
             "--disable-component-update", "--disable-default-apps", "--disable-extensions", "--disable-sync",
             "--disable-features=MediaRouter,OptimizationHints", "--no-proxy-server", "--hide-scrollbars",
             "--force-device-scale-factor=1", f"--user-data-dir={args.profile}"]
    with log.open("wb") as errors:
        # The shell duplicates only this process's pipes into the required descriptors.
        process = subprocess.Popen(["/bin/sh", "-c", 'exec 3<&0 4>&1; exec "$@" --remote-debugging-pipe', "headless", str(args.binary), *flags], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
        assertions = []
        shots = []
        try:
            pipe = Pipe(process)
            version = pipe.call("Browser.getVersion")
            target = pipe.call("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
            call = lambda method, params=None: pipe.call(method, params, session)
            def evaluate(expression):
                response = call("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True, "userGesture": True})
                if "exceptionDetails" in response:
                    raise RuntimeError(response["exceptionDetails"])
                return response["result"].get("value")
            def require(expression, description):
                if evaluate(expression) is not True:
                    raise AssertionError(description)
                assertions.append(description)
            call("Page.enable")
            call("Runtime.enable")
            call("Network.enable")
            pipe.call("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(downloads), "eventsEnabled": True})
            call("Emulation.setDeviceMetricsOverride", {"width": 1440, "height": 1050, "deviceScaleFactor": 1, "mobile": False})
            call("Page.navigate", {"url": args.page.resolve().as_uri()})
            for _ in range(100):
                if evaluate("document.readyState === 'complete' && typeof embedded !== 'undefined'"):
                    break
                time.sleep(.02)
            require("document.querySelectorAll('[role=tab]').length === 6", "Six tabs rendered")
            require("document.querySelectorAll('.banner').length === 6", "Six exact view banners")
            require("embedded.data.acceptance.every(check => check.status === 'PASS')", "Four displayed acceptance passes")
            for index, tab in enumerate(("quality", "inventory", "health", "age", "plans", "acceptance"), 1):
                evaluate(f"document.getElementById('tab-{tab}').click()")
                require(f"document.querySelectorAll('[role=tabpanel]:not([hidden])').length === 1 && !document.getElementById('view-{tab}').hidden", f"Tab {index} activation")
                require(f"document.getElementById('view-{tab}').querySelector('.banner').textContent === embedded.notice", f"Tab {index} exact notice")
                filename = args.shots / f"{index:02d}-{tab}.png"
                if filename.exists():
                    raise FileExistsError(filename)
                image = call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False, "fromSurface": True})
                filename.write_bytes(base64.b64decode(image["data"]))
                shots.append(str(filename))
            require("embedded.data.hand_checks.every(check => check.actual === check.expected)", "Three displayed hand checks agree")
            evaluate("location.hash='health'; picker.value=embedded.data.derived.find(row => row.uses_estimated_age).source_row_id; picker.dispatchEvent(new Event('change'))")
            require("document.getElementById('asset-detail').textContent.includes('Uses estimated age.')", "Estimated-age lookup flag visible")
            evaluate("picker.value=embedded.data.derived.find(row => row.in_inventory && row.crv === null).source_row_id; picker.dispatchEvent(new Event('change'))")
            require("document.getElementById('asset-detail').textContent.includes('Unvalued (null)')", "Unvalued lookup remains null")
            evaluate("document.querySelector('[data-export=raw]').click()")
            for _ in range(100):
                if (downloads / "synthetic-raw.csv").exists():
                    break
                time.sleep(.02)
            exported = (downloads / "synthetic-raw.csv").read_text()
            if exported.count("Synthetic data, not a real utility.") != 1015:
                raise AssertionError("Raw CSV provenance")
            assertions.append("Raw CSV includes 1015 synthetic row notices")
            # Every displayed download must resolve to a quoted CSV with a notice.
            for key in evaluate("Object.keys(embedded.exports)"):
                time.sleep(.4)
                evaluate("document.querySelector('[data-export=" + key + "]').click()")
                filename = downloads / f"synthetic-{key}.csv"
                for _ in range(100):
                    if filename.exists():
                        break
                    time.sleep(.02)
                if not filename.exists():
                    raise AssertionError({"missing_download": key, "events": [e for e in pipe.events if e["method"].startswith("Browser.download")], "script_errors": [e for e in pipe.events if e["method"] == "Runtime.exceptionThrown"]})
                if "synthetic_notice" not in filename.read_text().splitlines()[0]:
                    raise AssertionError(key + " export lacks notice column")
                assertions.append(key + " CSV downloaded")
            call("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
            require("document.documentElement.scrollWidth <= 390", "Narrow viewport contains horizontal scrolling within tables")
            failures = [e for e in pipe.events if e["method"] == "Runtime.exceptionThrown"]
            requests = [e["params"]["request"]["url"] for e in pipe.events if e["method"] == "Network.requestWillBeSent"]
            external = [url for url in requests if not url.startswith(("file:", "blob:", "data:"))]
            if failures or external:
                raise AssertionError({"exceptions": failures, "external_requests": external})
            assertions.append("Zero external requests and zero browser script exceptions")
            receipt = {"status": "PASS", "browser": version["product"], "binary": str(args.binary), "page": str(args.page), "page_sha256": hashlib.sha256(args.page.read_bytes()).hexdigest(), "transport": "private process debugging pipes", "profile": str(args.profile), "assertion_count": len(assertions), "assertions": assertions, "observed_requests": requests, "external_requests": external, "screenshots": shots}
            (args.shots / "verification.json").write_text(json.dumps(receipt, indent=2) + "\n")
            print(json.dumps(receipt, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
