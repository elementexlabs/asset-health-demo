"""Deterministic coverage fixture; its relationship to age is imposed."""
import csv
import io
import math
import random
from datetime import date

FIELDS = ["source_row_id", "asset_id", "asset_group", "subtype", "status", "area",
          "customers_served", "install_date", "install_date_status", "inspection_date",
          "condition_grade", "measurement"]
COST_FIELDS = ["asset_group", "subtype", "installed_unit_cost_cad", "basis", "effective_date", "source", "estimated"]
DECADES = [(1960, .08), (1970, .17), (1980, .20), (1990, .15), (2000, .15), (2010, .15), (2020, .10)]


def csv_bytes(rows, fields):
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def unit_costs():
    return [{"asset_group": group, "subtype": subtype, "installed_unit_cost_cad": value,
             "basis": "installed like-for-like replacement including labour, excluding removal",
             "effective_date": "2026-01-01",
             "source": "invented demonstration assumption, not a quotation", "estimated": True}
            for group, subtype, value in [("TX", "25", 8000), ("TX", "50", 12000),
                                           ("TX", "100", 20000), ("POLE", "standard", 4000),
                                           ("POLE", "heavy", 6000)]]


def generate(model):
    rng = random.Random(model["seed"])
    # Every draw uses random(); no implementation-dependent helper sampling.
    def uniform_int(lo, hi):
        return lo + int(rng.random() * (hi - lo + 1))

    def normal(sd):
        u = max(rng.random(), 2 ** -53)
        return sd * math.sqrt(-2 * math.log(u)) * math.cos(2 * math.pi * rng.random())

    def triangle(lo, mode, hi):
        u = rng.random()
        if u < (mode - lo) / (hi - lo):
            return lo + math.sqrt(u * (hi - lo) * (mode - lo))
        return hi - math.sqrt((1 - u) * (hi - lo) * (hi - mode))

    def install_date():
        u, weights = rng.random(), []
        for decade, weight in DECADES:
            weights.append(weight)
            if u < math.fsum(weights):
                break
        # The current decade ends at the snapshot. Never seed future baseline dates.
        year = uniform_int(decade, min(decade + 9, 2026))
        last_month = 3 if year == 2026 else 12
        month = uniform_int(1, last_month)
        return date(year, month, uniform_int(1, 28))

    snapshot = date.fromisoformat(model["snapshot"])
    area_customers = {f"A{i}": uniform_int(20, 800) for i in range(1, 7)}
    assets = [(f"POLE{i:04}", "POLE") for i in range(1, 701)] + [(f"TX{i:04}", "TX") for i in range(1, 301)]
    rows = []
    for index, (asset_id, group) in enumerate(sorted(assets), 1):
        subtype_draw = rng.random()
        subtype = (["25", "50", "100"][int(subtype_draw * 3)] if group == "TX"
                   else ("standard" if subtype_draw < .8 else "heavy"))
        installed = install_date()
        age = (snapshot - installed).days / model["age_divisor"]
        grade = min(5, max(1, int(math.floor(math.fsum((1, 3 * min(age / model["lives"][group], 1.3), normal(.8), .5))))))
        measurement = (triangle(20, 65, 150) if group == "TX" else
                       min(100, max(30, math.fsum((100, -30 * age / model["lives"][group], normal(8))))))
        area = f"A{uniform_int(1, 6)}"
        customers = uniform_int(1, 30) if group == "TX" else area_customers[area]
        inspection_days = int(rng.random() * (12 * model["age_divisor"] + 1))
        from datetime import timedelta
        inspected = snapshot - timedelta(days=inspection_days)
        rows.append(dict(zip(FIELDS, [f"R{index:04}", asset_id, group, subtype, "in_service", area,
                                     customers, installed.isoformat(), "recorded", inspected.isoformat(),
                                     grade, round(measurement, 4)])))
    # Seeded sets: disjoint so planted counts remain directly auditable.
    order = sorted(range(len(rows)), key=lambda i: (rng.random(), i))
    manifest, cursor = [], 0
    for kind, count in [("missing_install", 80), ("estimated_install", 80), ("placeholder_install", 10),
                        ("future_install", 5), ("missing_inspection", 60), ("impossible_measurement", 10),
                        ("unmatched_subtype", 10), ("missing_identity", 5), ("exact_duplicate", 10),
                        ("conflicting_identity", 5)]:
        for index in order[cursor:cursor + count]:
            row = rows[index]
            extra = None
            if kind == "missing_install":
                row.update(install_date="", install_date_status="missing")
            elif kind == "estimated_install":
                row.update(install_date=row["install_date"][:4] + "-07-01", install_date_status="estimated")
                if row["install_date"] > model["snapshot"]:
                    row["install_date"] = "2025-07-01"
            elif kind == "placeholder_install":
                row["install_date"] = "1900-01-01"
            elif kind == "future_install":
                row["install_date"] = "2027-01-01"
            elif kind == "missing_inspection":
                row["inspection_date"] = ""
            elif kind == "impossible_measurement":
                row["measurement"] = 250 if row["asset_group"] == "TX" else 140
            elif kind == "unmatched_subtype":
                row["subtype"] = "UNMATCHED"
            elif kind == "missing_identity":
                row["asset_id"] = ""
            else:
                extra = dict(row)
                extra["source_row_id"] = f"R{len(rows) + 1:04}"
                if kind == "conflicting_identity":
                    delta = -.1 if row["asset_group"] == "POLE" and row["measurement"] > 99.9 else .1
                    extra["measurement"] = round(float(row["measurement"]) + delta, 4)
                rows.append(extra)
            manifest.append({"kind": kind, "source_row_id": row["source_row_id"],
                             "appended_row_id": extra["source_row_id"] if extra else ""})
        cursor += count
    return sorted(rows, key=lambda r: r["source_row_id"]), manifest
