"""Generate, check, verify fresh processes, publish locally, and open the report."""
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest
import webbrowser
from . import acceptance
from .calculate import calculate, canonical, score
from .generate import generate, unit_costs, csv_bytes, FIELDS, COST_FIELDS
from .render import render

ROOT = Path(__file__).resolve().parents[1]


def package():
    model = json.loads((ROOT / "config/model.json").read_text())
    rows, manifest = generate(model)
    costs = unit_costs()
    results = calculate(rows, costs, model)
    cases = [
        ("TX: zero age, grade 1, loading 80", {"asset_group": "TX", "install_date": model["snapshot"], "condition_grade": 1, "measurement": 80}, 100),
        ("Pole: zero age, grade 3, strength 80", {"asset_group": "POLE", "install_date": model["snapshot"], "condition_grade": 3, "measurement": 80}, 100 - 50 * math.fsum((model["weights"]["POLE"]["condition"], model["weights"]["POLE"]["measurement"]))),
        ("TX: missing age, grade 3, loading 100", {"asset_group": "TX", "install_date": "", "condition_grade": 3, "measurement": 100}, None)]
    results["hand_checks"] = []
    for description, overrides, expected in cases:
        row = {"source_row_id": "HAND", "asset_id": "HAND", "asset_group": "TX", "subtype": "50", "status": "in_service", "area": "A1", "customers_served": 5, "install_date": model["snapshot"], "install_date_status": "recorded", "inspection_date": model["snapshot"], "condition_grade": 1, "measurement": 80, **overrides}
        if not row["install_date"]:
            row["install_date_status"] = "missing"
        computed = score(row, model)
        if description.startswith("TX: missing"):
            w = model["weights"]["TX"]
            available = math.fsum((w["condition"], w["measurement"]))
            expected = (100 - math.fsum((50 * w["condition"], 40 * w["measurement"])) / available) if available > 0 and available + 1e-12 >= model["minimum_evidence"] else None
        display = lambda value: "null (insufficient evidence)" if value is None else f"{value:.3f}"
        results["hand_checks"].append({"description": description, "scores": ", ".join(f'{f["factor"]}={f["score"]}' for f in computed["factors"]), "expected": display(expected), "actual": display(computed["health"])})
        if (computed["health"] is None) != (expected is None) or (expected is not None and abs(computed["health"] - expected) > 1e-9):
            raise ValueError("Hand-worked fixture does not match")
    costs_bytes = csv_bytes(costs, COST_FIELDS)
    results["acceptance"] = acceptance.preliminary_checks(results, costs_bytes.decode())
    # Stable report slot; nothing is written until two independent processes verify it.
    results["acceptance"].append(acceptance.repeatability("verified", "verified"))
    json_bytes = canonical(results) + b"\n"
    html_bytes = render(results, ROOT)
    artifacts = {"results.json": json_bytes, "index.html": html_bytes}
    return results, rows, manifest, costs_bytes, artifacts


def fingerprints(artifacts):
    return {name: hashlib.sha256(value).hexdigest() for name, value in artifacts.items()}


def fresh_fingerprints():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", AMDEMO_NO_OPEN="1")
    result = subprocess.run([sys.executable, "-m", "amdemo", "--fingerprint"], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def main():
    if sys.argv[1:] == ["--fingerprint"]:
        print(json.dumps(fingerprints(package()[-1]), sort_keys=True))
        return
    if sys.argv[1:]:
        raise SystemExit("Run python3 -m amdemo without arguments")
    results, rows, manifest, costs, artifacts = package()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    if not outcome.wasSuccessful():
        raise SystemExit(1)
    one, two = fresh_fingerprints(), fresh_fingerprints()
    verified = acceptance.repeatability(one, two)
    if verified["status"] != "PASS" or one != fingerprints(artifacts):
        raise SystemExit("FAIL: independent process artifacts differ")
    results["acceptance"][-1] = verified
    if any(check["status"] != "PASS" for check in results["acceptance"]):
        raise SystemExit("FAIL: acceptance checks")
    # The verified report must be exactly the candidate compared above.
    assert canonical(results) + b"\n" == artifacts["results.json"]
    (ROOT / "data/synthetic").mkdir(parents=True, exist_ok=True)
    (ROOT / "dist").mkdir(exist_ok=True)
    (ROOT / "data/synthetic/assets.csv").write_bytes(csv_bytes(rows, FIELDS))
    (ROOT / "data/synthetic/unit_costs.csv").write_bytes(costs)
    (ROOT / "data/synthetic/defects.json").write_bytes(canonical(manifest) + b"\n")
    for name, data in artifacts.items():
        (ROOT / "dist" / name).write_bytes(data)
    print(f"PASS: {outcome.testsRun} automated tests; 4/4 acceptance checks; two independent builds verified")
    print(f"index.html: {len(artifacts['index.html'])} bytes")
    for name, digest in one.items():
        print(f"SHA-256 {name}: {digest}")
    if os.environ.get("AMDEMO_NO_OPEN") != "1":
        webbrowser.open((ROOT / "dist/index.html").as_uri())


if __name__ == "__main__":
    main()
