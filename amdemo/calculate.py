"""One build-time calculation implementation. No browser arithmetic."""
import json
import math
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

GROUPS = ("TX", "POLE")
HEALTH_BANDS = ("very good", "good", "fair", "poor", "very poor", "insufficient evidence")
RISK_BANDS = ("low", "moderate", "elevated", "high", "unscored")
DATE_KINDS = ("recorded", "estimated", "missing", "invalid")


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def validate_model(model):
    for group in GROUPS:
        weights = model["weights"][group]
        if set(weights) != {"age", "condition", "measurement"} or any(not math.isfinite(v) or v < 0 for v in weights.values()) or not math.isclose(math.fsum(weights.values()), 1, abs_tol=1e-10):
            raise ValueError("Weights must be finite, nonnegative, and sum to one")
        if not math.isfinite(model["lives"][group]) or model["lives"][group] <= 0:
            raise ValueError("Illustrative lives must be positive")
    if not 0 < model["minimum_evidence"] <= 1 or model["discount_rate"] < 0 or model["annual_budget_cad"] <= 0:
        raise ValueError("Invalid evidence, discount or budget assumption")
    if model["horizon_years"] != 5 or model["deterioration_rates"] != [1, 2, 3]:
        raise ValueError("This fixture supports five years and rates 1, 2, 3")
    if sorted(model["health_band_minima"], reverse=True) != model["health_band_minima"] or len(model["health_band_minima"]) != 4:
        raise ValueError("Health band minima must be four descending values")


def parsed_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None


def date_kind(row, model):
    if not row["install_date"]:
        return "missing"
    installed = parsed_date(row["install_date"])
    if installed is None or installed < date.fromisoformat(model["earliest_install_date"]) or installed > date.fromisoformat(model["snapshot"]) or row["install_date_status"] not in ("recorded", "estimated"):
        return "invalid"
    return row["install_date_status"]


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def validity(row, model, costs):
    snapshot = date.fromisoformat(model["snapshot"])
    inspected = parsed_date(row["inspection_date"])
    grade = row["condition_grade"]
    lo, hi = model["measurement_limits"][row["asset_group"]]
    return {"asset_id": bool(row["asset_id"].strip()),
            "subtype": any(c["asset_group"] == row["asset_group"] and c["subtype"] == row["subtype"] for c in costs),
            "install_date": date_kind(row, model) in ("recorded", "estimated"),
            "inspection_date": inspected is not None and inspected <= snapshot,
            "condition_grade": isinstance(grade, int) and not isinstance(grade, bool) and 1 <= grade <= 5,
            "measurement": finite_number(row["measurement"]) and lo <= row["measurement"] <= hi,
            "customers_served": isinstance(row["customers_served"], int) and row["customers_served"] > 0}


def dispositions(rows):
    # Exact duplicates precede conflicts. A conflicting group of retained rows is held.
    seen, decisions, representatives = {}, {}, defaultdict(list)
    for row in sorted(rows, key=lambda r: r["source_row_id"]):
        signature = canonical({k: v for k, v in row.items() if k != "source_row_id"})
        if signature in seen:
            decisions[row["source_row_id"]] = {"disposition": "excluded", "reasons": ["exact_duplicate"], "duplicate_of": seen[signature]}
        else:
            seen[signature] = row["source_row_id"]
            representatives[row["asset_id"]].append(row)
    for asset_id, copies in representatives.items():
        disposition = "held" if not asset_id.strip() or len(copies) > 1 else "accepted"
        reasons = (["missing_identity"] if not asset_id.strip() else ["conflicting_identity"]) if disposition == "held" else []
        for row in copies:
            decisions[row["source_row_id"]] = {"disposition": disposition, "reasons": reasons, "duplicate_of": None}
    return decisions


def cost_lookup(row, costs, snapshot):
    matches = [c for c in costs if c["asset_group"] == row["asset_group"] and c["subtype"] == row["subtype"] and c["effective_date"] <= snapshot]
    return max(matches, key=lambda c: c["effective_date"])["installed_unit_cost_cad"] if matches else None


def clamp(value):
    return min(100, max(0, value))


def health_band(hi, model):
    if hi is None:
        return "insufficient evidence"
    for threshold, label in zip(model["health_band_minima"], HEALTH_BANDS):
        if hi >= threshold:
            return label
    return "very poor"


def likelihood(hi, model):
    band = health_band(hi, model)
    return None if hi is None else HEALTH_BANDS.index(band) + 1


def consequence(customers, model):
    return 1 + sum(customers > boundary for boundary in model["consequence_cut_points"])


def risk_band(risk, model):
    if risk is None:
        return "unscored"
    for threshold, label in zip(model["risk_band_minima"], ("high", "elevated", "moderate")):
        if risk >= threshold:
            return label
    return "low"


def score(row, model, valid=None):
    # Missing or future inspection dates cannot substantiate a condition finding.
    valid = valid or validity(row, model, [])
    kind = date_kind(row, model)
    age = ((date.fromisoformat(model["snapshot"]) - date.fromisoformat(row["install_date"])).days / model["age_divisor"]) if valid["install_date"] else None
    scores = {"age": clamp(100 * age / model["lives"][row["asset_group"]]) if age is not None else None,
              "condition": 25 * (row["condition_grade"] - 1) if valid["condition_grade"] and valid["inspection_date"] else None,
              "measurement": None}
    if valid["measurement"]:
        scores["measurement"] = clamp(2 * (row["measurement"] - 80)) if row["asset_group"] == "TX" else clamp(100 * (100 - row["measurement"]) / 40)
    weights = model["weights"][row["asset_group"]]
    # Built-in float sum changed in Python 3.12; use one algorithm on all versions.
    coverage = math.fsum(weights[factor] for factor, value in scores.items() if value is not None)
    hi = (100 - math.fsum(weights[factor] * value for factor, value in scores.items() if value is not None) / coverage
          if coverage + 1e-12 >= model["minimum_evidence"] and coverage > 0 and scores["condition"] is not None else None)
    factors = [{"factor": factor, "raw": {"age": age, "condition": row["condition_grade"], "measurement": row["measurement"]}[factor],
                "score": value, "weight": weights[factor], "available_weight": weights[factor] / coverage if value is not None and coverage else None,
                "contribution": weights[factor] * value / coverage if value is not None and coverage else None}
               for factor, value in scores.items()]
    return {"date_kind": kind, "age": age, "health": hi, "health_band": health_band(hi, model),
            "evidence_weight": coverage, "uses_estimated_age": kind == "estimated" and hi is not None,
            "factors": factors}


def percent(numerator, denominator):
    return 100 * numerator / denominator if denominator else None


def age_category(derived):
    kind = derived["date_kind"]
    if kind != "recorded":
        return {"estimated": "estimated date", "missing": "unknown date", "invalid": "invalid date"}[kind]
    return f"{int(derived['age'] // 10) * 10}–{int(derived['age'] // 10) * 10 + 9} years"


def projected_health(initial, year, replaced_year, rate, model):
    # Beginning of year observation, after intervention; year 1 starts at HI0.
    return model["replacement_health"] if replaced_year is not None and year >= replaced_year else max(0, initial - rate * (year - 1))


def present_value(spends, discount):
    value = sum(Decimal(spend) / ((Decimal(1) + Decimal(str(discount))) ** (year - 1)) for year, spend in enumerate(spends, 1))
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate(rows, costs, model):
    validate_model(model)
    decisions = dispositions(rows)
    derived = []
    for row in rows:
        valid = validity(row, model, costs)
        result = {"source_row_id": row["source_row_id"], "asset_id": row["asset_id"], "asset_group": row["asset_group"], **decisions[row["source_row_id"]], "field_validity": valid, **score(row, model, valid)}
        warnings = [f"missing_{field}" if row[field] in ("", None) else f"invalid_{field}" for field, ok in valid.items() if not ok]
        if result["date_kind"] == "estimated":
            warnings.append("estimated_install_date")
        inspected = parsed_date(row["inspection_date"])
        if valid["inspection_date"] and (date.fromisoformat(model["snapshot"]) - inspected).days / model["age_divisor"] > model["stale_inspection_years"]:
            warnings.append("stale_inspection_flag_only")
        if row["asset_group"] == "TX" and valid["measurement"] and row["measurement"] > 130:
            warnings.append("high_loading_warning_only")
        result["warnings"] = warnings
        result["in_inventory"] = result["disposition"] == "accepted" and row["status"] == "in_service"
        result["crv"] = cost_lookup(row, costs, model["snapshot"]) if result["in_inventory"] else None
        if not result["in_inventory"]:
            result.update(health=None, health_band="insufficient evidence", uses_estimated_age=False)
        result["likelihood"] = likelihood(result["health"], model)
        result["consequence"] = consequence(row["customers_served"], model) if valid["customers_served"] else None
        result["risk"] = result["likelihood"] * result["consequence"] if result["likelihood"] is not None and result["consequence"] is not None else None
        result["risk_band"] = risk_band(result["risk"], model)
        # The same cohort supports both orders; no ranking an unknown or estimated age.
        result["plan_exclusions"] = ([result["disposition"]] if not result["in_inventory"] else []) + (["insufficient_health"] if result["health"] is None else []) + (["unvalued"] if result["crv"] is None else []) + ([f"{result['date_kind']}_age"] if result["date_kind"] != "recorded" else []) + (["unscored_risk"] if result["risk"] is None else [])
        result["age_category"] = age_category(result) if result["in_inventory"] else "outside inventory"
        derived.append(result)
    quality, inventory, health, ages, uncertainty = [], [], [], [], []
    for group in GROUPS:
        raw_group = [r for r in rows if r["asset_group"] == group]
        group_rows = [d for d in derived if d["asset_group"] == group]
        eligible = [d for d in group_rows if d["in_inventory"]]
        for field in ("asset_id", "subtype", "install_date", "inspection_date", "condition_grade", "measurement", "customers_served"):
            applicable = raw_group
            nonblank = [r["source_row_id"] for r in applicable if r[field] not in ("", None)]
            usable = [d["source_row_id"] for d in group_rows if d["field_validity"][field]]
            invalid = [d["source_row_id"] for d in group_rows if not d["field_validity"][field] and d["source_row_id"] in nonblank]
            estimated = [r["source_row_id"] for r in applicable if field == "install_date" and r["install_date_status"] == "estimated"]
            quality.append({"group": group, "field": field, "denominator": len(applicable), "present": len(nonblank), "usable": len(usable), "completeness": percent(len(nonblank), len(applicable)), "usability": percent(len(usable), len(applicable)), "missing_ids": [r["source_row_id"] for r in applicable if r["source_row_id"] not in nonblank], "invalid_ids": invalid, "estimated_ids": estimated})
        counts = Counter(d["disposition"] for d in group_rows)
        valued = [d for d in eligible if d["crv"] is not None]
        unvalued = [d for d in eligible if d["crv"] is None]
        inventory.append({"group": group, "source": len(group_rows), "accepted": counts["accepted"], "held": counts["held"], "excluded": counts["excluded"], "in_service": len(eligible), "valued": len(valued), "unvalued_ids": [d["source_row_id"] for d in unvalued], "unvalued_by_subtype": dict(Counter(next(r["subtype"] for r in raw_group if r["source_row_id"] == d["source_row_id"]) for d in unvalued)), "crv_total": sum(d["crv"] for d in valued), "crv_label": "Partial CRV" if unvalued else "CRV", "held_ids": [d["source_row_id"] for d in group_rows if d["disposition"] == "held"], "excluded_ids": [d["source_row_id"] for d in group_rows if d["disposition"] == "excluded"]})
        for band in HEALTH_BANDS:
            ids = [d["source_row_id"] for d in eligible if d["health_band"] == band]
            health.append({"group": group, "band": band, "count": len(ids), "denominator": len(eligible), "outside_inventory": len(group_rows) - len(eligible), "ids": ids})
        for category in [f"{i}–{i+9} years" for i in range(0, 70, 10)] + ["estimated date", "unknown date", "invalid date"]:
            ids = [d["source_row_id"] for d in eligible if d["age_category"] == category]
            ages.append({"group": group, "category": category, "count": len(ids), "denominator": len(eligible), "outside_inventory": len(group_rows) - len(eligible), "ids": ids})
        for kind in DATE_KINDS:
            ids = [d["source_row_id"] for d in group_rows if d["date_kind"] == kind]
            in_ids = [d["source_row_id"] for d in eligible if d["date_kind"] == kind]
            scored = [d["source_row_id"] for d in eligible if d["date_kind"] == kind and d["health"] is not None]
            plan_ids = [d["source_row_id"] for d in eligible if d["date_kind"] == kind and not d["plan_exclusions"]]
            uncertainty.append({"group": group, "kind": kind, "source_ids": ids, "inventory_ids": in_ids, "scored_ids": scored, "plan_eligible_ids": plan_ids})
    plan_pool = [d for d in derived if not d["plan_exclusions"]]
    plans = []
    for rate in model["deterioration_rates"]:
        for name in ("A", "B"):
            replaced, annual, spends = {}, [], []
            for year in range(1, model["horizon_years"] + 1):
                remaining = [d for d in plan_pool if d["asset_id"] not in replaced]
                def order(d):
                    if name == "A":
                        hi = projected_health(d["health"], year, None, rate, model)
                        return (-likelihood(hi, model) * d["consequence"], d["asset_id"])
                    return (-d["age"], d["asset_id"])
                remaining.sort(key=order)
                bought, spend = [], 0
                for d in remaining:
                    if spend + d["crv"] > model["annual_budget_cad"]:
                        break
                    bought.append(d["asset_id"])
                    spend += d["crv"]
                    replaced[d["asset_id"]] = year
                risk_counts = Counter()
                health_counts = Counter()
                high_ids = []
                for d in plan_pool:
                    hi = projected_health(d["health"], year, replaced.get(d["asset_id"]), rate, model)
                    risk = likelihood(hi, model) * d["consequence"]
                    risk_counts[risk_band(risk, model)] += 1
                    health_counts[health_band(hi, model)] += 1
                    if risk >= 15:
                        high_ids.append(d["asset_id"])
                spends.append(spend)
                annual.append({"year": year, "replaced_ids": bought, "spend": spend, "underspend": model["annual_budget_cad"] - spend, "cohort_count": len(plan_pool), "excluded_source_count": len(derived) - len(plan_pool), "health_counts": {b: health_counts[b] for b in HEALTH_BANDS}, "risk_counts": {b: risk_counts[b] for b in RISK_BANDS}, "risk_at_least_15_ids": high_ids})
            plans.append({"plan": name, "rate": rate, "annual": annual, "pv_cad": present_value(spends, model["discount_rate"]), "total_spend": sum(spends)})
    return {"model": model, "raw": rows, "costs": costs, "derived": derived, "quality": quality, "inventory": inventory, "health": health, "ages": ages, "uncertainty": uncertainty, "plans": plans, "plan_eligible_ids": [d["asset_id"] for d in plan_pool]}
