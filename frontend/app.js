"use strict";

const CATEGORIES = [
  "Travel", "Materials", "Software", "Professional Services",
  "Utilities", "Equipment", "Uncategorised",
];

let arFilter = "";
let apAnomaliesOnly = "";
let spendChart = null;
let arChart = null;

const fmt = (n) => "£" + Number(n).toLocaleString("en-GB", { minimumFractionDigits: 2 });

// Escape values that originate from invoices / parsed supplier PDFs before they
// go into innerHTML, so a crafted vendor or client name can't inject markup.
function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

function toast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.className = isError ? "error" : "";
  setTimeout(() => el.classList.add("hidden"), 4000);
}

// ---- AR invoices -----------------------------------------------------------

async function loadInvoices() {
  const query = arFilter ? `?status=${arFilter}` : "";
  const invoices = await api(`/invoices${query}`);
  const tbody = document.getElementById("invoice-rows");
  tbody.innerHTML = "";
  document.getElementById("invoice-empty").classList.toggle("hidden", invoices.length > 0);

  for (const inv of invoices) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>INV-${String(inv.id).padStart(5, "0")}</td>
      <td>${esc(inv.client_name)}</td>
      <td class="muted">${esc(inv.description)}</td>
      <td>${fmt(inv.amount)}</td>
      <td>${inv.due_date}</td>
      <td><span class="badge badge-${inv.status}">${inv.status}</span></td>
      <td>${inv.reminder_count || ""}</td>
      <td class="actions"></td>`;
    const actions = tr.querySelector(".actions");
    if (inv.status === "DRAFT") {
      actions.appendChild(actionButton("Send", "btn-accept", () => sendInvoice(inv.id)));
    } else if (inv.status === "SENT" || inv.status === "OVERDUE") {
      actions.appendChild(actionButton("Mark paid", "btn-ghost", () => markPaid(inv.id)));
    }
    tbody.appendChild(tr);
  }
  return invoices;
}

function actionButton(label, cls, handler) {
  const btn = document.createElement("button");
  btn.textContent = label;
  btn.className = `btn ${cls}`;
  btn.addEventListener("click", handler);
  return btn;
}

async function sendInvoice(id) {
  try {
    await api(`/invoices/${id}/send`, { method: "POST" });
    toast(`Invoice ${id} sent`);
    refresh();
  } catch (err) {
    toast(err.message, true);
  }
}

async function markPaid(id) {
  try {
    await api(`/invoices/${id}/paid`, { method: "PATCH" });
    toast(`Invoice ${id} marked paid`);
    refresh();
  } catch (err) {
    toast(err.message, true);
  }
}

// ---- AP expenses -----------------------------------------------------------

async function loadExpenses() {
  const query = apAnomaliesOnly ? "?anomalies_only=true" : "";
  const expenses = await api(`/expenses${query}`);
  const tbody = document.getElementById("expense-rows");
  tbody.innerHTML = "";
  document.getElementById("expense-empty").classList.toggle("hidden", expenses.length > 0);

  for (const exp of expenses) {
    const tr = document.createElement("tr");
    if (exp.anomaly_flag) tr.classList.add("flagged");
    tr.innerHTML = `
      <td>${exp.vendor ? esc(exp.vendor) : "<span class='muted'>unknown</span>"}</td>
      <td class="muted">${exp.invoice_number ? esc(exp.invoice_number) : "–"}</td>
      <td>${exp.invoice_date || "–"}</td>
      <td>${exp.amount != null ? fmt(exp.amount) : "–"}</td>
      <td class="muted">${exp.vat_amount != null ? fmt(exp.vat_amount) : "–"}</td>
      <td class="category-cell"></td>
      <td class="flag-cell">${exp.anomaly_flag ? `<span class="flag">${esc(exp.anomaly_flag)}</span>` : ""}</td>
      <td class="actions"></td>`;

    const select = document.createElement("select");
    for (const cat of CATEGORIES) {
      const opt = document.createElement("option");
      opt.value = cat;
      opt.textContent = cat;
      opt.selected = cat === exp.category;
      select.appendChild(opt);
    }
    if (!CATEGORIES.includes(exp.category)) {
      const opt = document.createElement("option");
      opt.value = exp.category;
      opt.textContent = exp.category;
      opt.selected = true;
      select.appendChild(opt);
    }
    select.addEventListener("change", () => overrideCategory(exp.id, select.value));
    tr.querySelector(".category-cell").appendChild(select);

    if (exp.anomaly_flag) {
      tr.querySelector(".actions")
        .appendChild(actionButton("Clear flag", "btn-ghost", () => clearAnomaly(exp.id)));
    }
    tbody.appendChild(tr);
  }
}

async function overrideCategory(id, category) {
  try {
    await api(`/expenses/${id}/category`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ category }),
    });
    toast("Category updated");
    refreshCharts();
  } catch (err) {
    toast(err.message, true);
  }
}

async function clearAnomaly(id) {
  try {
    await api(`/expenses/${id}/clear-anomaly`, { method: "PATCH" });
    toast("Anomaly flag cleared");
    refresh();
  } catch (err) {
    toast(err.message, true);
  }
}

// ---- Charts + cards --------------------------------------------------------

const CHART_COLOURS = ["#14b8a6", "#60a5fa", "#fbbf24", "#f472b6", "#a78bfa", "#34d399", "#94a3b8"];

async function refreshCharts() {
  const [summary, invoices] = await Promise.all([api("/expenses/summary"), api("/invoices")]);

  document.getElementById("card-spend").textContent = fmt(summary.total_spend);
  document.getElementById("card-anomalies").textContent = summary.anomaly_count;

  const outstanding = invoices
    .filter((i) => i.status === "SENT" || i.status === "OVERDUE")
    .reduce((sum, i) => sum + i.amount, 0);
  document.getElementById("card-outstanding").textContent = fmt(outstanding);
  document.getElementById("card-overdue").textContent =
    invoices.filter((i) => i.status === "OVERDUE").length;

  const datasets = Object.entries(summary.by_category).map(([category, series], idx) => ({
    label: category,
    data: series,
    backgroundColor: CHART_COLOURS[idx % CHART_COLOURS.length],
  }));
  if (spendChart) spendChart.destroy();
  spendChart = new Chart(document.getElementById("spend-chart"), {
    type: "bar",
    data: { labels: summary.months, datasets },
    options: {
      responsive: true,
      scales: {
        x: { stacked: true, grid: { color: "#334155" }, ticks: { color: "#94a3b8" } },
        y: { stacked: true, grid: { color: "#334155" }, ticks: { color: "#94a3b8" } },
      },
      plugins: { legend: { labels: { color: "#e2e8f0" } } },
    },
  });

  const statuses = ["DRAFT", "SENT", "OVERDUE", "PAID"];
  const counts = statuses.map((s) => invoices.filter((i) => i.status === s).length);
  if (arChart) arChart.destroy();
  arChart = new Chart(document.getElementById("ar-chart"), {
    type: "doughnut",
    data: {
      labels: statuses,
      datasets: [{ data: counts, backgroundColor: ["#475569", "#0d9488", "#b45309", "#15803d"] }],
    },
    options: { responsive: true, plugins: { legend: { labels: { color: "#e2e8f0" } } } },
  });
}

// ---- Wiring ----------------------------------------------------------------

function bindFilters(containerId, datasetKey, apply) {
  const container = document.getElementById(containerId);
  container.addEventListener("click", (event) => {
    const btn = event.target.closest(".filter");
    if (!btn) return;
    container.querySelectorAll(".filter").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    apply(btn.dataset[datasetKey]);
  });
}

async function refresh() {
  await Promise.all([loadInvoices(), loadExpenses(), refreshCharts()]);
}

bindFilters("ar-filters", "status", (value) => { arFilter = value; loadInvoices(); });
bindFilters("ap-filters", "anomalies", (value) => { apAnomaliesOnly = value; loadExpenses(); });

document.getElementById("report-btn").addEventListener("click", async () => {
  try {
    const result = await api("/reports/monthly", { method: "POST" });
    toast(`Report generated: ${result.pdf_path}`);
  } catch (err) {
    toast(err.message, true);
  }
});

refresh();
setInterval(refresh, 30000);
