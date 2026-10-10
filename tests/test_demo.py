import builtins
import copy
import hashlib
import json
from collections import Counter
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
import unittest
from unittest.mock import patch
from amdemo import acceptance
from amdemo.calculate import (calculate, canonical, cost_lookup, date_kind, dispositions,
                              health_band, likelihood, consequence, risk_band, score,
                              percent, present_value, projected_health, validate_model)
from amdemo.generate import generate, unit_costs, csv_bytes, COST_FIELDS

ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = json.loads((ROOT / "config/model.json").read_text())
        # Hand-worked unit fixtures use the documented starting configuration.
        # The build separately validates and verifies the user's current model.
        cls.model["weights"] = {"TX": {"age": .3, "condition": .5, "measurement": .2}, "POLE": {"age": .2, "condition": .3, "measurement": .5}}
        cls.rows, cls.manifest = generate(cls.model)
        cls.costs = unit_costs()
        cls.cost_csv = csv_bytes(cls.costs, COST_FIELDS).decode()
        cls.results = calculate(cls.rows, cls.costs, cls.model)

    def fixture(self, **overrides):
        return {"source_row_id": "R0001", "asset_id": "TX0001", "asset_group": "TX", "subtype": "50", "status": "in_service", "area": "A1", "customers_served": 5, "install_date": self.model["snapshot"], "install_date_status": "recorded", "inspection_date": self.model["snapshot"], "condition_grade": 1, "measurement": 80, **overrides}

    def test_01_seed_repeatability(self):
        self.assertEqual(canonical(generate(self.model)), canonical(generate(self.model)))

    def test_02_generator_counts(self):
        self.assertEqual(len(self.rows), 1015)
        self.assertEqual(Counter(r["asset_group"] for r in self.rows if int(r["source_row_id"][1:]) <= 1000), {"TX": 300, "POLE": 700})
        self.assertEqual(len({r["source_row_id"] for r in self.rows}), 1015)

    def test_03_exact_defect_counts(self):
        expected = {"missing_install": 80, "estimated_install": 80, "placeholder_install": 10, "future_install": 5, "missing_inspection": 60, "impossible_measurement": 10, "unmatched_subtype": 10, "missing_identity": 5, "exact_duplicate": 10, "conflicting_identity": 5}
        self.assertEqual(Counter(m["kind"] for m in self.manifest), expected)
        mapped = {r["source_row_id"]: r for r in self.rows}
        detected = Counter()
        for d in self.results["derived"]:
            r = mapped[d["source_row_id"]]
            if d["date_kind"] == "missing": detected["missing_install"] += 1
            if d["date_kind"] == "estimated": detected["estimated_install"] += 1
            if r["install_date"] == "1900-01-01": detected["placeholder_install"] += 1
            if r["install_date"] > self.model["snapshot"]: detected["future_install"] += 1
            if not r["inspection_date"]: detected["missing_inspection"] += 1
            if not d["field_validity"]["measurement"]: detected["impossible_measurement"] += 1
            if not d["field_validity"]["subtype"]: detected["unmatched_subtype"] += 1
            if not r["asset_id"]: detected["missing_identity"] += 1
            if d["disposition"] == "excluded": detected["exact_duplicate"] += 1
        detected["conflicting_identity"] = sum("conflicting_identity" in d["reasons"] for d in self.results["derived"]) // 2
        self.assertEqual(detected, expected)

    def test_04_reconciliation(self):
        self.assertEqual(acceptance.reconciliation(self.results)["status"], "PASS")

    def test_05_duplicate_precedence(self):
        rows = [self.fixture(source_row_id="R0001"), self.fixture(source_row_id="R0002"), self.fixture(source_row_id="R0003", measurement=90)]
        choices = dispositions(rows)
        self.assertEqual(choices["R0002"]["disposition"], "excluded")
        self.assertEqual(choices["R0001"]["disposition"], "held")
        self.assertEqual(choices["R0003"]["disposition"], "held")

    def test_06_missing_identity(self):
        self.assertEqual(dispositions([self.fixture(asset_id="")])["R0001"]["reasons"], ["missing_identity"])

    def test_07_empty_denominator(self):
        self.assertIsNone(percent(0, 0))

    def test_08_date_boundaries(self):
        for installed, expected in [("1900-01-01", "invalid"), ("1899-12-31", "invalid"), ("1900-01-02", "recorded"), ("1970-01-01", "recorded"), ("2026-03-31", "recorded"), ("2026-04-01", "invalid"), ("bad", "invalid"), ("", "missing")]:
            self.assertEqual(date_kind(self.fixture(install_date=installed), self.model), expected)

    def test_09_future_inspection(self):
        self.assertIsNone(score(self.fixture(inspection_date="2026-04-01"), self.model)["health"])

    def test_10_missing_inspection(self):
        self.assertIsNone(score(self.fixture(inspection_date=""), self.model)["health"])

    def test_11_stale_flag_keeps_evidence(self):
        result = calculate([self.fixture(inspection_date="2010-01-01")], self.costs, self.model)["derived"][0]
        self.assertIn("stale_inspection_flag_only", result["warnings"])
        self.assertIsNotNone(result["health"])

    def test_12_hand_health_best(self):
        self.assertEqual(score(self.fixture(), self.model)["health"], 100)

    def test_13_hand_health_pole(self):
        result = score(self.fixture(asset_group="POLE", subtype="standard", condition_grade=3, measurement=80), self.model)
        self.assertEqual(result["health"], 60)  # 100 - (.3*50 + .5*50)

    def test_14_evidence_exact_threshold(self):
        result = score(self.fixture(install_date="", install_date_status="missing", condition_grade=3, measurement=100), self.model)
        self.assertAlmostEqual(result["health"], 100 - (25 + 8) / .7)
        self.assertAlmostEqual(result["evidence_weight"], .7)
        self.assertIsNone(result["factors"][0]["score"])

    def test_15_evidence_below_threshold(self):
        result = score(self.fixture(asset_group="POLE", subtype="standard", install_date="", install_date_status="missing", measurement=140), self.model)
        self.assertIsNone(result["health"])
        self.assertEqual(result["health_band"], "insufficient evidence")

    def test_16_bad_grade(self):
        for value in (0, 6, 1.5, None):
            self.assertIsNone(score(self.fixture(condition_grade=value), self.model)["health"])

    def test_17_measurement_boundaries(self):
        for group, subtype, inside, outside in [("TX", "50", 200, 200.01), ("POLE", "standard", 100, 100.01)]:
            self.assertIsNotNone(score(self.fixture(asset_group=group, subtype=subtype, measurement=inside), self.model)["factors"][2]["score"])
            self.assertIsNone(score(self.fixture(asset_group=group, subtype=subtype, measurement=outside), self.model)["factors"][2]["score"])

    def test_18_weights_validation(self):
        for weights in ({"age": -.1, "condition": .9, "measurement": .2}, {"age": .3, "condition": .4, "measurement": .2}):
            model = copy.deepcopy(self.model)
            model["weights"]["TX"] = weights
            with self.assertRaises(ValueError): validate_model(model)

    def test_19_health_band_edges(self):
        for value, expected in [(80, "very good"), (79.999, "good"), (60, "good"), (59.999, "fair"), (40, "fair"), (39.999, "poor"), (20, "poor"), (19.999, "very poor"), (None, "insufficient evidence")]:
            self.assertEqual(health_band(value, self.model), expected)

    def test_20_cost_lookup_effective_date(self):
        self.assertEqual(cost_lookup(self.fixture(), self.costs, self.model["snapshot"]), 12000)
        self.assertIsNone(cost_lookup(self.fixture(), self.costs, "2025-12-31"))
        self.assertIsNone(cost_lookup(self.fixture(subtype="UNMATCHED"), self.costs, self.model["snapshot"]))

    def test_21_independent_crv(self):
        self.assertEqual(acceptance.crv(self.results, self.cost_csv)["status"], "PASS")

    def test_22_estimates_and_age_bins(self):
        self.assertEqual(acceptance.uncertainty(self.results)["status"], "PASS")
        for d in self.results["derived"]:
            if d["in_inventory"] and d["date_kind"] == "estimated":
                self.assertEqual(d["age_category"], "estimated date")

    def test_23_risk_edges(self):
        for customers, expected in [(10, 1), (11, 2), (50, 2), (51, 3), (150, 3), (151, 4), (400, 4), (401, 5)]:
            self.assertEqual(consequence(customers, self.model), expected)
        self.assertEqual(risk_band(15, self.model), "high")
        self.assertEqual(risk_band(14, self.model), "elevated")
        self.assertIsNone(likelihood(None, self.model))

    def test_24_budget_limit_and_no_repeat_buys(self):
        for plan in self.results["plans"]:
            bought = []
            for year in plan["annual"]:
                self.assertLessEqual(year["spend"], 300000)
                self.assertEqual(year["spend"] + year["underspend"], 300000)
                bought += year["replaced_ids"]
            self.assertEqual(len(bought), len(set(bought)))

    def test_25_whole_asset_stop(self):
        model = copy.deepcopy(self.model)
        model["annual_budget_cad"] = 10000
        rows = [self.fixture(source_row_id="R0001", asset_id="TX0001", subtype="100", install_date="1960-01-01", condition_grade=5, customers_served=30), self.fixture(source_row_id="R0002", asset_id="TX0002", subtype="25", customers_served=1)]
        plans = calculate(rows, self.costs, model)["plans"]
        self.assertTrue(all(a["spend"] == 0 for p in plans for a in p["annual"]))

    def test_26_shared_plan_cohort(self):
        pool = set(self.results["plan_eligible_ids"])
        self.assertTrue(pool)
        self.assertTrue(all(not d["plan_exclusions"] for d in self.results["derived"] if d["asset_id"] in pool and d["in_inventory"]))
        self.assertEqual(sum(d["in_inventory"] and d["asset_id"] in pool for d in self.results["derived"]), len(pool))
        for p in self.results["plans"]:
            self.assertTrue(all(a["cohort_count"] == len(pool) for a in p["annual"]))
            self.assertTrue(all(asset in pool for a in p["annual"] for asset in a["replaced_ids"]))

    def test_27_intervention_timing(self):
        self.assertEqual(projected_health(50, 1, 3, 2, self.model), 50)
        self.assertEqual(projected_health(50, 2, 3, 2, self.model), 48)
        self.assertEqual(projected_health(50, 3, 3, 2, self.model), 95)
        self.assertEqual(projected_health(50, 5, 3, 3, self.model), 95)

    def test_28_hand_pv(self):
        self.assertEqual(present_value([100, 100], .1), "190.91")
        self.assertEqual(present_value([100, 100], 0), "200.00")

    def test_29_tamper_reconciliation(self):
        data = copy.deepcopy(self.results)
        next(d for d in data["derived"] if d["disposition"] == "held")["reasons"] = []
        self.assertEqual(acceptance.reconciliation(data)["status"], "FAIL")

    def test_30_tamper_crv(self):
        data = copy.deepcopy(self.results)
        next(d for d in data["derived"] if d["crv"] is not None)["crv"] += 1
        self.assertEqual(acceptance.crv(data, self.cost_csv)["status"], "FAIL")

    def test_31_tamper_uncertainty(self):
        data = copy.deepcopy(self.results)
        next(d for d in data["derived"] if d["uses_estimated_age"])["uses_estimated_age"] = False
        self.assertEqual(acceptance.uncertainty(data)["status"], "FAIL")

    def test_32_tamper_repeatability(self):
        data = copy.deepcopy(self.results)
        data["inventory"][0]["crv_total"] += 1
        self.assertEqual(acceptance.repeatability(canonical(self.results), canonical(data))["status"], "FAIL")

    def test_33_static_html_contract(self):
        from amdemo.__main__ import package
        from amdemo.render import BANNER
        html_bytes = package()[-1]["index.html"]
        self.assertLess(len(html_bytes), 2000000)
        class Parser(HTMLParser):
            def __init__(self):
                super().__init__(); self.banners = []; self.in_banner = False; self.urls = []
            def handle_starttag(self, tag, attrs):
                attributes = dict(attrs)
                if attributes.get("class") == "banner": self.in_banner = True
                self.urls += [v for k, v in attrs if k in ("src", "href") and v and "http" in v.lower()]
            def handle_data(self, data):
                if self.in_banner: self.banners.append(data)
            def handle_endtag(self, tag):
                if tag == "div": self.in_banner = False
        parser = Parser(); parser.feed(html_bytes.decode())
        self.assertEqual(parser.banners, [BANNER] * 6)
        self.assertEqual(parser.urls, [])

    def test_34_two_fresh_processes(self):
        from amdemo.__main__ import fresh_fingerprints
        self.assertEqual(fresh_fingerprints(), fresh_fingerprints())

    def test_35_configured_weights(self):
        model = copy.deepcopy(self.model)
        model["weights"]["POLE"] = {"age": .3, "condition": .4, "measurement": .3}
        row = self.fixture(asset_group="POLE", subtype="standard", condition_grade=3, measurement=80)
        self.assertEqual(score(row, model)["health"], 65)

    def test_36_no_plain_float_sum(self):
        from amdemo.__main__ import package
        integer_or_decimal_sum = builtins.sum

        def reject_float_sum(values, start=0):
            values = list(values)
            if isinstance(start, float) or any(isinstance(value, float) for value in values):
                raise AssertionError("Use math.fsum for float totals")
            return integer_or_decimal_sum(values, start)

        # Exercise every health row, hand fixture and rendered table on either runtime.
        # Even a correctly compensated built-in sum must fail this contract.
        with patch("builtins.sum", side_effect=reject_float_sum):
            results = package()[0]
        self.assertTrue(all(check["status"] == "PASS" for check in results["acceptance"]))


if __name__ == "__main__":
    unittest.main()
