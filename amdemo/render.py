"""A local static report. Only presentation interactions execute in the browser."""
import hashlib
import html
import json
from pathlib import Path
from .calculate import canonical, GROUPS, HEALTH_BANDS, RISK_BANDS

BANNER = "Synthetic data, not a real utility. Method demonstration; ElementeX Labs has no utility clients."
TABS = [("quality", "Data quality"), ("inventory", "Inventory and CRV"), ("health", "Health index"), ("age", "Age profile"), ("plans", "Plans"), ("acceptance", "Acceptance tests")]
ASSUMPTIONS = "Weights, lives, unit costs and thresholds are invented demonstration values; not engineer-approved or calibrated."


def esc(value):
    return html.escape(str(value), quote=True)


def number(value):
    return "Unavailable" if value is None else f"{value:,.1f}"


def money(value):
    return "Unvalued (null)" if value is None else f"CAD {value:,.0f}"


def ids(label, values):
    return f'<details><summary>{esc(label)}: {len(values)}</summary><div class="ids">{esc(", ".join(values) or "None")}</div></details>'


def table(headers, rows, caption=""):
    return '<div class="table-wrap"><table>' + (f'<caption>{esc(caption)}</caption>' if caption else "") + '<thead><tr>' + ''.join(f'<th scope="col">{esc(h)}</th>' for h in headers) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{value}</td>' for value in row) + '</tr>' for row in rows) + '</tbody></table></div>'


def export_link(key, label):
    return f'<a class="download" href="#" data-export="{key}">{esc(label)} CSV</a>'


def render(results, root):
    exports = {}
    def add_export(key, records):
        fields = list(records[0]) if records else []
        aliases = {"raw": "raw", "quality": "quality", "inventory": "inventory", "costs": "costs", "age": "ages", "health": "derived", "health-bands": "health", "hand-checks": "hand_checks", "disposition-counts": "inventory", "plan-summary": "plans", "dispositions": "derived", "plan-eligibility": "derived", "acceptance": "acceptance", "uncertainty": "uncertainty"}
        exports[key] = {"fields": ["synthetic_notice", "model_version", "seed"] + fields}
        if key in aliases:
            exports[key]["source"] = aliases[key]
        else:
            exports[key]["rows"] = records
    model, raw, derived = results["model"], results["raw"], results["derived"]
    add_export("raw", raw)
    sections = []
    quality_rows = [[q["group"], esc(q["field"]), f'{q["present"]} / {q["denominator"]} ({number(q["completeness"])}%)', f'{q["usable"]} / {q["denominator"]} ({number(q["usability"])}%)', ids("Missing", q["missing_ids"]) + ids("Invalid", q["invalid_ids"]) + ids("Estimated", q["estimated_ids"])] for q in results["quality"]]
    disposition_rows = [[i["group"], f'{i["accepted"]} / {i["source"]}', f'{i["held"]} / {i["source"]}' + ids("Held IDs", i["held_ids"]), f'{i["excluded"]} / {i["source"]}' + ids("Excluded IDs", i["excluded_ids"])] for i in results["inventory"]]
    reason_rows = []
    for reason in ("missing_identity", "conflicting_identity", "exact_duplicate"):
        affected = [d["source_row_id"] for d in derived if reason in d["reasons"]]
        reason_rows.append([reason, f'{len(affected)} / {len(raw)} source rows', ids("Source row IDs", affected)])
    sections.append('<p>Source-level denominators include duplicates and held rows. Estimated dates count as present; usability counts valid values. Measurement is group-specific, so no not-applicable factor is counted as missing.</p>' + table(["Group", "Field", "Completeness", "Usability", "Exceptions and estimates"], quality_rows) + '<h2>Exclusive dispositions</h2>' + table(["Group", "Accepted", "Held outside inventory", "Excluded copies"], disposition_rows) + table(["Reason", "Count / source", "Rows"], reason_rows) + '<p class="small">Exact copies are excluded first; blank identities and remaining conflicting identities are held. Other defects remain field warnings. A stale inspection is flagged after 10 years and remains available. Valid loading above 130% is a warning; values outside 0–200% are unusable. These are invented demonstration thresholds, not engineering limits.</p>')
    add_export("quality", results["quality"])
    add_export("disposition-counts", results["inventory"])
    add_export("disposition-reasons", [{"reason": reason, "count": sum(reason in d["reasons"] for d in derived), "source_denominator": len(raw), "source_ids": [d["source_row_id"] for d in derived if reason in d["reasons"]]} for reason in ("missing_identity", "conflicting_identity", "exact_duplicate")])
    add_export("dispositions", [{k: d[k] for k in ("source_row_id", "asset_id", "asset_group", "disposition", "reasons", "warnings")} for d in derived])
    sections[0] += '<div class="actions">' + export_link("quality", "Quality") + export_link("disposition-counts", "Disposition counts") + export_link("disposition-reasons", "Reason counts") + export_link("dispositions", "Row dispositions") + export_link("raw", "Raw rows") + '</div>'
    inventory_rows = [[i["group"], f'{i["in_service"]} / {i["source"]}', f'{i["held"]} held; {i["excluded"]} copies', f'{i["valued"]} / {i["in_service"]} valued; all matched prices estimated', '<strong>' + i["crv_label"] + '</strong><br>' + money(i["crv_total"]), ids("Unvalued", i["unvalued_ids"]) + esc(i["unvalued_by_subtype"])] for i in results["inventory"]]
    cost_rows = [[c["asset_group"], esc(c["subtype"]), money(c["installed_unit_cost_cad"]), esc(c["effective_date"]), 'estimated=true<br>' + esc(c["source"])] for c in results["costs"]]
    sections.append('<p>Inventory counts accepted in-service assets only. CRV is the matched whole-dollar installed unit cost, with no adjustment. Missing matches remain null. Partial totals sum valued assets only.</p>' + table(["Group", "In-service / source", "Outside inventory", "Price coverage", "Planning estimate", "Unvalued subtype and rows"], inventory_rows) + '<h2>Invented unit cost table</h2><p>Installed like-for-like replacement including labour, excluding removal. No separate disposal cost. Every price is an <strong>invented demonstration assumption, not a quotation</strong>.</p>' + table(["Group", "Subtype", "Installed cost", "Effective date", "Provenance"], cost_rows) + '<p>No book value, insurance value or supplier pricing is demonstrated. All costs are invented demonstration values.</p>')
    add_export("inventory", results["inventory"])
    add_export("costs", results["costs"])
    sections[1] += '<div class="actions">' + export_link("inventory", "Inventory and CRV") + export_link("costs", "Unit costs") + '</div>'
    weights_rows = [[group, str(model["lives"][group]), str(model["weights"][group]["age"]), str(model["weights"][group]["condition"]), str(model["weights"][group]["measurement"])] for group in GROUPS]
    hand = results["hand_checks"]
    health_rows = [[h["group"], esc(h["band"]), f'{h["count"]} / {h["denominator"]}', str(h["outside_inventory"]), ids("Contributing rows", h["ids"])] for h in results["health"]]
    choices = []
    for d in derived:
        key = d["source_row_id"]
        choices.append(f'<option value="{key}">{esc(d["asset_id"] or "Blank ID")} · {key} · {d["disposition"]}</option>')

    sections.append('<p><strong>Condition grade 1 is best; 5 is worst.</strong> Higher HI means better synthetic condition. The generator deliberately makes grade and strength follow age; this is not validation. Different evidence bases can yield similar indices, so no group mean is reported.</p>' + '<h2>Hand-worked fixtures, outside fleet counts</h2>' + table(["Fixture", "Factor scores", "Expected HI", "Computed HI"], [[esc(h["description"]), esc(h["scores"]), esc(h["expected"]), esc(h["actual"])] for h in hand]) + '<h2>Visible fixed model</h2>' + table(["Group", "Invented life, years", "Age weight", "Condition weight", "Measurement weight"], weights_rows) + '<p class="small">HI = 100 − Σ(weight × available deterioration score) / Σ(available weight). Minimum evidence weight ' + str(model["minimum_evidence"]) + '; a valid condition grade supported by a valid inspection date is required. Missing factors are unavailable, never mean-filled. Weights sum to one; only available weights are renormalised.</p><details><summary>Exact factor scales, band boundaries and invented evidence rules</summary><p>' + esc(json.dumps({k: model[k] for k in ("scales", "health_band_minima", "minimum_evidence", "age_divisor", "earliest_install_date", "measurement_limits", "stale_inspection_years")}, indent=2)) + '</p><p>HI bands: ≥80 very good; ≥60 and &lt;80 good; ≥40 and &lt;60 fair; ≥20 and &lt;40 poor; &lt;20 very poor. Unavailable HI is insufficient evidence.</p></details>' + table(["Group", "Health band", "Count / inventory", "Outside inventory", "Rows"], health_rows) + '<h2>Asset detail</h2><label for="asset-picker">Look up an asset ID or source row</label><br><select id="asset-picker">' + ''.join(choices) + '</select><div id="asset-detail" class="detail"></div>')
    add_export("health", [{k: d[k] for k in ("source_row_id", "asset_id", "asset_group", "disposition", "date_kind", "health", "health_band", "uses_estimated_age", "evidence_weight", "factors", "warnings")} for d in derived])
    add_export("hand-checks", results["hand_checks"])
    add_export("health-bands", results["health"])
    add_export("weights", [{"group": group, "life_years": model["lives"][group], **model["weights"][group], "assumptions": ASSUMPTIONS} for group in GROUPS])
    sections[2] += '<div class="actions">' + export_link("health", "Health and factor detail") + export_link("health-bands", "Health bands") + export_link("hand-checks", "Hand checks") + export_link("weights", "Fixed model") + '</div>'
    ages_rows = [[a["group"], esc(a["category"]), f'{a["count"]} / {a["denominator"]}', str(a["outside_inventory"]), ids("Contributing rows", a["ids"])] for a in results["ages"]]
    reconciliation = "; ".join(f'{i["group"]}: {sum(a["count"] for a in results["ages"] if a["group"] == i["group"])} categories = {i["in_service"]} accepted in service; {i["held"]} held and {i["excluded"]} copies outside' for i in results["inventory"])
    sections.append('<p>Known synthetic dates use elapsed days / ' + str(model["age_divisor"]) + ' and half-open 10-year bins. Estimated, unknown and invalid dates stay in their own categories. Supplied dates are synthetic observations, not verified records.</p>' + table(["Group", "Age category", "Count / inventory", "Outside inventory", "Rows"], ages_rows) + '<p class="note"><strong>Reconciliation:</strong> ' + esc(reconciliation) + '</p>')
    add_export("age", results["ages"])
    sections[3] += '<div class="actions">' + export_link("age", "Age profile") + '</div>'
    plan_count = len(results["plan_eligible_ids"])
    sections.append('<p class="note"><strong>Plan A wins on its own measure by design.</strong> It orders assets by the same ordinal risk used to assess the scenario. This demonstrates mechanics, not a measured benefit or optimisation.</p><p>Both plans use the same ' + str(plan_count) + ' scored, valued assets with recorded valid ages; ' + str(len(raw) - plan_count) + ' source rows are outside the shared cohort. Estimated, missing and invalid ages are excluded from both orders. The remaining fleet is not projected. Plan A orders by descending year-specific R; Plan B by oldest known age. Ties use asset ID. Each asset can be replaced once.</p><p>Invented budget CAD 300,000 per year per plan; whole assets until the next will not fit. Underspend is not carried forward. Constant 2026 dollars; no escalation, maintenance, disposal or residual value. PV = Σ spend(t) / (1.03)^(t−1), beginning-of-year spending convention, rounded once half-up to cents. This is a replacement-spending comparison, not lifecycle economics.</p><p>Beginning-of-year observations after intervention. Unreplaced HI(t) = max(0, HI0 − rate × (t−1)). Replacement HI = 95, held fixed after replacement: <strong>scenario reset, not a test result</strong>. Condition and likelihood are not measured after intervention. The 1, 2 and 3 point annual rates are invented demonstration scenarios, not confidence intervals.</p><p>Risk R = ordinal likelihood × ordinal consequence. Likelihood: very good=1, good=2, fair=3, poor=4, very poor=5. Consequence uses invented customers-served cut points ≤10, ≤50, ≤150, ≤400, then &gt;400. Risk bands: 1–4 low, 5–9 moderate, 10–14 elevated, 15–25 high. <strong>R is never summed or averaged; it is not a probability or dollars.</strong></p>')
    spending, risks, projected = [], [], []
    for p in results["plans"]:
        for a in p["annual"]:
            spending.append([p["plan"], str(p["rate"]), str(a["year"]), money(a["spend"]), money(a["underspend"]), ids("Replacement IDs", a["replaced_ids"])])
            risks.append([p["plan"], str(p["rate"]), str(a["year"])] + [f'{a["risk_counts"][b]} / {plan_count}' for b in RISK_BANDS[:-1]] + [ids("R ≥ 15 asset IDs", a["risk_at_least_15_ids"]), str(a["excluded_source_count"])])
            projected.append([p["plan"], str(p["rate"]), str(a["year"])] + [f'{a["health_counts"][b]} / {plan_count}' for b in HEALTH_BANDS] + [str(a["excluded_source_count"])])
    sections[4] += '<h2>Five-year replacement spending</h2>' + table(["Plan", "Rate", "Total spending", "Present value"], [[p["plan"], str(p["rate"]), money(p["total_spend"]), 'CAD ' + f'{float(p["pv_cad"]):,.2f}'] for p in results["plans"]]) + table(["Plan", "Rate", "Year", "Spending", "Underspend", "Selected IDs"], spending) + '<h2>Ordinal risk frequencies, shared cohort only</h2>' + table(["Plan", "Rate", "Year", "Low", "Moderate", "Elevated", "High", "Count R ≥ 15", "Outside cohort"], risks) + '<h2>Projected health frequencies</h2>' + table(["Plan", "Rate", "Year"] + list(HEALTH_BANDS) + ["Outside cohort"], projected)
    add_export("plan-spending", [{"plan": p["plan"], "rate": p["rate"], "pv_cad": p["pv_cad"], **{k: a[k] for k in ("year", "spend", "underspend", "replaced_ids", "cohort_count", "excluded_source_count")}} for p in results["plans"] for a in p["annual"]])
    add_export("plan-summary", [{k: p[k] for k in ("plan", "rate", "total_spend", "pv_cad")} for p in results["plans"]])
    add_export("plan-risk", [{"plan": p["plan"], "rate": p["rate"], **{k: a[k] for k in ("year", "risk_counts", "risk_at_least_15_ids", "cohort_count", "excluded_source_count")}} for p in results["plans"] for a in p["annual"]])
    add_export("plan-health", [{"plan": p["plan"], "rate": p["rate"], **{k: a[k] for k in ("year", "health_counts", "cohort_count", "excluded_source_count")}} for p in results["plans"] for a in p["annual"]])
    add_export("plan-eligibility", [{k: d[k] for k in ("source_row_id", "asset_id", "asset_group", "date_kind", "warnings", "plan_exclusions")} for d in derived])
    excluded_details = ''.join(ids(reason, [d["source_row_id"] for d in derived if reason in d["plan_exclusions"]]) for reason in sorted({r for d in derived for r in d["plan_exclusions"]}))
    sections[4] += '<h2>Eligibility exclusions (reasons may overlap)</h2>' + excluded_details + '<div class="actions">' + ''.join(export_link(k, label) for k, label in [("plan-summary", "Plan totals and PV"), ("plan-spending", "Annual spending"), ("plan-risk", "Risk frequencies"), ("plan-health", "Projected health"), ("plan-eligibility", "Eligibility")]) + '</div>'
    checks_rows = [[esc(c["name"]), '<span class="' + c["status"].lower() + '">' + c["status"] + '</span>', esc(c["actual"]), esc(c["expected"]), esc("; ".join(c["failures"]) or "None")] for c in results["acceptance"]]
    trace_rows = [[u["group"], u["kind"], ids("Source", u["source_ids"]), ids("Inventory", u["inventory_ids"]), ids("Scored", u["scored_ids"]), ids("Plan eligible", u["plan_eligible_ids"])] for u in results["uncertainty"]]
    sections.append('<p><strong>Demo thresholds, not utility acceptance.</strong> These checks were computed at build time from raw rows. The page does not rerun calculations. A pass verifies this fixture and these rules only; it is not a reference or evidence of delivery capacity.</p>' + table(["Check", "Result", "Actual", "Expected", "Failing rows or reason"], checks_rows) + '<h2>Visible uncertainty across outputs</h2><p>Source counts include held and duplicate rows. Inventory, scored and plan counts use their explicitly narrower populations. Row details and CSV exports retain warning flags and factor availability.</p>' + table(["Group", "Date provenance", "Source rows", "Accepted in service", "Scored health", "Shared plan cohort"], trace_rows))
    add_export("acceptance", results["acceptance"])
    add_export("uncertainty", results["uncertainty"])
    sections[5] += '<div class="actions">' + export_link("acceptance", "Acceptance checks") + export_link("uncertainty", "Uncertainty trace") + '</div>'
    # Derived calculations are embedded once. Lookup cards are presentation strings only.
    embedded = {"data": results, "notice": BANNER, "exports": exports}
    body = ''.join(f'<section id="view-{key}" role="tabpanel" aria-labelledby="tab-{key}"' + ('' if i == 0 else ' hidden') + f'><div class="banner">{BANNER}</div><h1>{i+1}. {title}</h1><p class="muted small">{ASSUMPTIONS}</p>{content}</section>' for i, ((key, title), content) in enumerate(zip(TABS, sections)))
    navigation = ''.join(f'<button id="tab-{key}" role="tab" data-tab="{key}" aria-controls="view-{key}" aria-selected="{str(i == 0).lower()}" tabindex="{0 if i == 0 else -1}">{i+1} {title}</button>' for i, (key, title) in enumerate(TABS))
    payload = canonical(embedded).decode().replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    digest = hashlib.sha256(canonical(results) + b'\n').hexdigest()
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; connect-src \'none\'; img-src data:; base-uri \'none\'; form-action \'none\'"><title>ElementeX · Asset method demonstration</title><style>' + (root / 'web/style.css').read_text() + '</style></head><body><header><strong>ElementeX · Asset evidence</strong><p>Method demonstration · Snapshot 2026-03-31 · One synthetic fleet</p></header><nav role="tablist" aria-label="Demonstration views">' + navigation + '</nav><main>' + body + '</main><footer>Model ' + esc(model["version"]) + ' · Generator 1 · Seed ' + str(model["seed"]) + '<br>results.json SHA-256: <code>' + digest + '</code><br>No validated engineering model. No real utility, place, standard limit or published benchmark supplies these values.</footer><script type="application/json" id="embedded-data">' + payload + '</script><script>' + (root / 'web/app.js').read_text() + '</script></body></html>\n').encode('utf-8')
