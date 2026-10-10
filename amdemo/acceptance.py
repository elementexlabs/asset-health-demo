"""Bounded, independently checked output contracts for this fixture."""
import csv
import io
from collections import Counter
from datetime import date
from .calculate import canonical


def check(name, failures, actual, expected):
    return {"name": name, "status": "FAIL" if failures else "PASS", "actual": actual,
            "expected": expected, "failures": failures, "threshold": "Demo thresholds, not utility acceptance"}


def reconciliation(results):
    raw, derived = results["raw"], results["derived"]
    failures = []
    source_counts = Counter(r["source_row_id"] for r in raw)
    output_counts = Counter(d["source_row_id"] for d in derived)
    if source_counts != output_counts or any(n != 1 for n in source_counts.values()):
        failures.append("source_row_id coverage is not exactly one")
    counts = Counter(d["disposition"] for d in derived)
    if set(counts) - {"accepted", "held", "excluded"}:
        failures.append("unknown disposition")
    for d in derived:
        if d["disposition"] in ("held", "excluded") and not d["reasons"]:
            failures.append(d["source_row_id"] + ": missing disposition reason")
    if (len(raw), counts["accepted"], counts["held"], counts["excluded"]) != (1015, 990, 15, 10):
        failures.append("fixture counts differ from README")
    return check("1 Reconciliation", failures,
                 f"{len(raw)} source = {counts['accepted']} accepted + {counts['held']} held + {counts['excluded']} excluded; {len(failures)} violations",
                 "1015 = 990 + 15 + 10; zero unexplained rows")


def crv(results, cost_csv):
    # Independent string-key lookup from the CSV, with no production cost function.
    table = list(csv.DictReader(io.StringIO(cost_csv)))
    raw = {r["source_row_id"]: r for r in results["raw"]}
    totals, unvalued = Counter(), Counter()
    failures = []
    for d in results["derived"]:
        r = raw[d["source_row_id"]]
        value = None
        if d["disposition"] == "accepted" and r["status"] == "in_service":
            matches = sorted([c for c in table if c["asset_group"] == r["asset_group"] and c["subtype"] == str(r["subtype"]) and c["effective_date"] <= results["model"]["snapshot"]], key=lambda c: c["effective_date"])
            value = int(matches[-1]["installed_unit_cost_cad"]) if matches else None
            if value is None:
                unvalued[r["asset_group"]] += 1
            else:
                totals[r["asset_group"]] += value
        if d["crv"] != value:
            failures.append(d["source_row_id"] + ": wrong valuation or null")
    for item in results["inventory"]:
        if item["crv_total"] != totals[item["group"]] or len(item["unvalued_ids"]) != unvalued[item["group"]] or item["crv_label"] != ("Partial CRV" if unvalued[item["group"]] else "CRV"):
            failures.append(item["group"] + ": wrong partial total, coverage or label")
    return check("2 Independent CRV", failures, f"{len(raw)} rows checked; {len(failures)} mismatches", "zero dollar differences; every unmatched asset remains null; partial labels visible")


def uncertainty(results):
    failures = []
    rows = {r["source_row_id"]: r for r in results["raw"]}
    model = results["model"]
    expected_kinds = {}
    for d in results["derived"]:
        r = rows[d["source_row_id"]]
        if not r["install_date"]:
            kind = "missing"
        else:
            try:
                installed = date.fromisoformat(r["install_date"])
                valid_date = model["earliest_install_date"] <= installed.isoformat() <= model["snapshot"]
            except ValueError:
                valid_date = False
            kind = r["install_date_status"] if valid_date and r["install_date_status"] in ("recorded", "estimated") else "invalid"
        expected_kinds[d["source_row_id"]] = kind
        if d["date_kind"] != kind:
            failures.append(d["source_row_id"] + ": lost date provenance")
        age_factor = next(f for f in d["factors"] if f["factor"] == "age")
        if kind in ("missing", "invalid") and (age_factor["score"] is not None or d["age"] is not None):
            failures.append(d["source_row_id"] + ": unavailable age used")
        if kind == "estimated" and d["in_inventory"] and d["health"] is not None and not d["uses_estimated_age"]:
            failures.append(d["source_row_id"] + ": estimate flag hidden")
        if kind != "recorded" and d["in_inventory"] and d["age_category"].endswith("years"):
            failures.append(d["source_row_id"] + ": uncertain date in known bin")
        if kind != "recorded" and not d["plan_exclusions"]:
            failures.append(d["source_row_id"] + ": uncertain date in shared plan cohort")
        measurement = next(f for f in d["factors"] if f["factor"] == "measurement")
        lo, hi = model["measurement_limits"][r["asset_group"]]
        if (not isinstance(r["measurement"], (int, float)) or not lo <= r["measurement"] <= hi) and measurement["score"] is not None:
            failures.append(d["source_row_id"] + ": invalid measure used")
        condition = next(f for f in d["factors"] if f["factor"] == "condition")
        if (not r["inspection_date"] or r["inspection_date"] > model["snapshot"]) and condition["score"] is not None:
            failures.append(d["source_row_id"] + ": absent or future inspection used")
        for field, valid in d["field_validity"].items():
            if not valid and not any(w.endswith(field) for w in d["warnings"]):
                failures.append(d["source_row_id"] + ": warning hidden for " + field)
    for trace in results["uncertainty"]:
        group, kind = trace["group"], trace["kind"]
        source = [d for d in results["derived"] if d["asset_group"] == group and expected_kinds[d["source_row_id"]] == kind]
        in_inventory = [d for d in source if d["in_inventory"]]
        expected = {"source_ids": [d["source_row_id"] for d in source], "inventory_ids": [d["source_row_id"] for d in in_inventory], "scored_ids": [d["source_row_id"] for d in in_inventory if d["health"] is not None], "plan_eligible_ids": [d["source_row_id"] for d in in_inventory if not d["plan_exclusions"]]}
        if any(trace[key] != value for key, value in expected.items()):
            failures.append(group + "/" + kind + ": mismatched trace")
        if kind != "recorded":
            category = {"estimated": "estimated date", "missing": "unknown date", "invalid": "invalid date"}[kind]
            age_ids = next(a["ids"] for a in results["ages"] if a["group"] == group and a["category"] == category)
            if age_ids != expected["inventory_ids"]:
                failures.append(group + "/" + kind + ": age view mismatch")
        quality = next(q for q in results["quality"] if q["group"] == group and q["field"] == "install_date")
        if kind in ("missing", "invalid", "estimated") and quality[{"missing": "missing_ids", "invalid": "invalid_ids", "estimated": "estimated_ids"}[kind]] != expected["source_ids"]:
            failures.append(group + "/" + kind + ": quality view mismatch")
    for group in ("TX", "POLE"):
        inventory = next(i for i in results["inventory"] if i["group"] == group)
        if sum(a["count"] for a in results["ages"] if a["group"] == group) != inventory["in_service"]:
            failures.append(group + ": age total does not reconcile")
        if sum(h["count"] for h in results["health"] if h["group"] == group) != inventory["in_service"]:
            failures.append(group + ": health total does not reconcile")
    return check("3 Visible uncertainty", failures, f"{len(rows)} row traces checked; {len(failures)} lost flags", "zero lost flags across quality, inventory, health, age and plan outputs; row detail and CSV retain provenance")


def repeatability(first, second):
    failures = [] if first == second else ["independent artifact fingerprints differ"]
    return check("4 Repeatability", failures, "2 / 2 independent process fingerprints match" if not failures else "process fingerprints differ", "identical SHA-256 for results.json and index.html in two fresh processes")


def preliminary_checks(results, cost_csv):
    return [reconciliation(results), crv(results, cost_csv), uncertainty(results)]
