/* Presentation only: navigation, lookup and CSV downloads. */
"use strict";
const embedded = JSON.parse(document.getElementById("embedded-data").textContent);
const buttons = Array.from(document.querySelectorAll('[role="tab"]'));
function showTab(id, focus = false) {
  buttons.forEach(button => {
    const selected = button.dataset.tab === id;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
    document.getElementById(button.getAttribute("aria-controls")).hidden = !selected;
    if (selected && focus) button.focus();
  });
}
buttons.forEach((button, index) => {
  button.addEventListener("click", () => { location.hash = button.dataset.tab; });
  button.addEventListener("keydown", event => {
    let next;
    if (event.key === "ArrowRight") next = buttons[index + 1] || buttons[0];
    if (event.key === "ArrowLeft") next = buttons[index - 1] || buttons[buttons.length - 1];
    if (event.key === "Home") next = buttons[0];
    if (event.key === "End") next = buttons[buttons.length - 1];
    if (next) { event.preventDefault(); location.hash = next.dataset.tab; next.focus(); }
  });
});
function restoreTab() {
  const id = location.hash.slice(1);
  showTab(buttons.some(button => button.dataset.tab === id) ? id : "quality");
}
addEventListener("hashchange", restoreTab);
restoreTab();
const picker = document.getElementById("asset-picker");
function displayAsset() {
  const d = embedded.data.derived.find(row => row.source_row_id === picker.value);
  const r = embedded.data.raw.find(row => row.source_row_id === picker.value);
  const out = document.getElementById("asset-detail");
  out.replaceChildren();
  const text = (tag, content) => { const el = document.createElement(tag); el.textContent = content; out.append(el); };
  const format = value => value === null ? "Unavailable (null)" : new Intl.NumberFormat("en-CA", {maximumFractionDigits: 3}).format(value);
  text("h3", `${d.asset_id || "Blank identity"} · ${d.source_row_id}`);
  text("p", `${d.disposition}; ${d.date_kind} date ${r.install_date || "missing"}; inspection ${r.inspection_date || "missing"}. HI ${format(d.health)}; ${d.health_band}; evidence weight ${format(d.evidence_weight)}. CRV ${d.crv === null ? "Unvalued (null)" : "CAD " + format(d.crv)}.`);
  text("p", `Warnings: ${d.warnings.join(", ") || "None"}. ${d.uses_estimated_age ? "Uses estimated age." : ""} Plan exclusions: ${d.plan_exclusions.join(", ") || "None"}. Disposition reasons: ${d.reasons.join(", ") || "None"}.`);
  const table = document.createElement("table");
  const header = table.createTHead().insertRow();
  ["Factor", "Raw value / age years", "Deterioration score", "Fixed weight", "Available weight share", "Deterioration contribution"].forEach(value => { const th = document.createElement("th"); th.scope = "col"; th.textContent = value; header.append(th); });
  const body = table.createTBody();
  d.factors.forEach(factor => { const row = body.insertRow(); [factor.factor, format(factor.raw), format(factor.score), String(factor.weight), format(factor.available_weight), format(factor.contribution)].forEach(value => { row.insertCell().textContent = value; }); });
  const wrap = document.createElement("div"); wrap.className = "table-wrap"; wrap.append(table); out.append(wrap);
  text("p", `Ordinal likelihood ${d.likelihood ?? "unscored"}; consequence ${d.consequence ?? "unscored"}; scenario R ${d.risk ?? "unscored"}; ${d.risk_band}. These are ordinal scores, not probabilities or dollars.`);
}
picker.addEventListener("change", displayAsset);
displayAsset();
const cell = value => '"' + String(value ?? "").replaceAll('"', '""') + '"';
document.querySelectorAll("[data-export]").forEach(link => {
  link.addEventListener("click", event => {
    event.preventDefault();
    const table = embedded.exports[link.dataset.export];
    const lines = [table.fields.map(cell).join(","), ...(table.rows || embedded.data[table.source]).map(row => table.fields.map(field => { const value = field === "synthetic_notice" ? embedded.notice : field === "model_version" ? embedded.data.model.version : field === "seed" ? embedded.data.model.seed : row[field]; return cell(typeof value === "object" && value !== null ? JSON.stringify(value) : value); }).join(","))];
    const blob = new Blob([lines.join("\n") + "\n"], {type:"text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = "synthetic-" + link.dataset.export + ".csv";
    download.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
});
