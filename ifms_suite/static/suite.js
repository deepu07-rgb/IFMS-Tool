"use strict";
const $ = (id) => document.getElementById(id);
const escapeHTML = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const modules = [
  ["dashboard", "Dashboard"],
  ["employees", "Employee & Groups"],
  ["outer", "Outer Sheet Analyzer"],
  ["inner", "Inner Sheet Analyzer"],
  ["ga55", "GA 55 / OCR"],
  ["arrears", "Arrear / Due–Drawn"],
  ["rates", "Rates & Allowances"],
  ["schedules", "Schedules & Comparison"],
  ["reports", "Reports & Backup"],
];
let savedRules = [];
let refreshVersion = 0;
const renderedHTML = new Map();
let cachedRates = [];
let importRecords = [],
  groupRecords = [],
  reviewState = null;
$("navigation").innerHTML = modules
  .map(([k, n]) => `<button data-module="${k}">${n}</button>`)
  .join("");
$("navigation").onclick = (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  const k = b.dataset.module;
  if (k === "inner") openLegacy("upload");
  else if (k === "schedules") openLegacy("schedules");
  else if (k === "outer" || k === "ga55") {
    openModule("imports");
    $("importForm").elements.kind.value = k === "outer" ? "outer" : "ga55";
  } else openModule(k);
};
function notify(text) {
  $("message").textContent = text;
  $("message").style.display = "block";
}
async function api(path, options = {}) {
  const r = await fetch("/suite/api/" + path, options);
  const p = await r.json();
  if (!r.ok) {
    throw Error(
      p.error ||
        p.errors?.map((x) => x.employee_code + ": " + x.error).join("\n") ||
        "Request failed",
    );
  }
  return p;
}
const post = (path, p) =>
  api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(p),
  });
function table(rows, columns) {
  return `<div class="scroll"><table><thead><tr>${columns.map((k) => `<th>${escapeHTML(k.replaceAll("_", " "))}</th>`).join("")}</tr></thead><tbody>${rows.map((r) => `<tr>${columns.map((k) => `<td>${escapeHTML(r[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
}
function openModule(id) {
  document
    .querySelectorAll("main section")
    .forEach((s) => s.classList.toggle("active", s.id === id));
  document
    .querySelectorAll("nav button")
    .forEach((b) => b.classList.toggle("active", b.dataset.module === id));
  refresh().catch((e) => notify(e.message));
}
function openLegacy(tab) {
  openModule("legacy");
  $("legacyFrame").src = "/analyzer#" + tab;
}
function addSegment(s = {}) {
  const tr = document.createElement("tr");
  for (const k of [
    "start",
    "end",
    "basic",
    "due_rate",
    "drawn_rate",
    "prior_settlement",
    "due_da_rate",
    "drawn_da_rate",
    "settlement_ids",
  ]) {
    const td = document.createElement("td"),
      i = document.createElement("input");
    i.dataset.key = k;
    i.type = ["start", "end"].includes(k)
      ? "date"
      : k === "settlement_ids"
        ? "text"
        : "number";
    i.step = "0.0001";
    i.required = !k.includes("da_rate") && k !== "settlement_ids";
    i.style.width = ["start", "end"].includes(k) ? "145px" : "100px";
    i.value = s[k] ?? (k === "prior_settlement" ? "0" : "");
    td.append(i);
    tr.append(td);
  }
  const td = document.createElement("td"),
    b = document.createElement("button");
  b.type = "button";
  b.textContent = "Remove";
  b.onclick = () => tr.remove();
  td.append(b);
  tr.append(td);
  $("segments").append(tr);
  updateSegmentControls();
}
addSegment({ start: "2025-01-01", end: "2025-03-31" });
function addDeduction() {
  const div = document.createElement("div");
  div.className = "deduction";
  div.innerHTML =
    '<label>Name<input data-key="name" placeholder="GPF / Tax" required></label><label>Method<select data-key="mode"><option value="fixed">Fixed amount</option><option value="percent">% of positive gross arrear</option></select></label><label>Value<input data-key="value" type="number" step="0.01" min="0" required></label>';
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = "Remove";
  b.onclick = () => div.remove();
  div.append(b);
  $("deductionRows").append(div);
}
function deductions() {
  return [...document.querySelectorAll(".deduction")].map((r) =>
    Object.fromEntries(
      [...r.querySelectorAll("[data-key]")].map((i) => [
        i.dataset.key,
        i.value,
      ]),
    ),
  );
}
for (const [form, path] of [
  ["employeeForm", "employees"],
  ["rateForm", "rates"],
  ["ruleForm", "rules"],
]) {
  $(form).onsubmit = async (e) => {
    e.preventDefault();
    try {
      await post(path, Object.fromEntries(new FormData(e.target)));
      notify("Saved");
      await refresh();
    } catch (x) {
      notify(x.message);
    }
  };
}
$("payHistoryForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const p = Object.fromEntries(new FormData(e.target));
    p.reviewed = e.target.elements.reviewed.checked;
    p.eligible = p.eligible === "true";
    await post("pay_history", p);
    notify("Dated pay event saved");
    await refresh();
  } catch (x) {
    notify(x.message);
  }
};
function updateSegmentControls() {
  const history = $("claimSource").value === "history",
    basis = $("claimBasis").value;
  document.querySelectorAll("#segments input").forEach((i) => {
    const key = i.dataset.key,
      unused =
        (key === "basic" && ["fixed", "daily"].includes(basis)) ||
        (key.includes("da_rate") && basis !== "basic_da");
    i.disabled = history || unused;
    i.required =
      !i.disabled &&
      key !== "settlement_ids" &&
      (!key.includes("da_rate") ||
        key === "due_da_rate" ||
        $("drawnMode").value !== "actual");
  });
}
$("claimSource").onchange = updateSegmentControls;
$("claimBasis").onchange = updateSegmentControls;
$("drawnMode").onchange = updateSegmentControls;
$("claimForm").elements.allowance.onchange = () => {
  const rule = savedRules.find(
    (r) =>
      r.name.toUpperCase() ===
      $("claimForm").elements.allowance.value.trim().toUpperCase(),
  );
  if (rule) {
    $("claimBasis").value = rule.basis;
    $("claimProration").value = rule.proration || "calendar";
    $("claimRounding").value = rule.rounding || "paise";
    $("claimRoundingScope").value = rule.rounding_scope || "segment";
  }
  updateSegmentControls();
  renderRateReference();
};
$("claimForm").elements.category.onchange = renderRateReference;
$("claimForm").elements.start.onchange = renderRateReference;
$("claimForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const p = Object.fromEntries(new FormData(e.target));
    p.deductions = deductions();
    p.uniform_drawn_reviewed = e.target.elements.uniform_drawn_reviewed.checked;
    if (p.source === "manual") {
      p.segments = [...$("segments").rows].map((tr) => {
        const s = Object.fromEntries(
          [...tr.querySelectorAll("input")].map((i) => [
            i.dataset.key,
            i.value,
          ]),
        );
        s.settlement_ids = (s.settlement_ids || "")
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean)
          .map(Number);
        s.basis = $("claimBasis").value;
        s.proration = $("claimProration").value;
        s.rounding = $("claimRounding").value;
        s.rounding_scope = $("claimRoundingScope").value;
        if (["fixed", "daily"].includes(s.basis)) {
          s.due_amount = s.due_rate;
          s.drawn_amount = s.drawn_rate;
        }
        if ($("drawnMode").value === "actual") {
          s.drawn_amount = s.drawn_rate;
          s.drawn_basis = "period";
        }
        return s;
      });
    }
    const r = await post("claims", p);
    $("calculation").innerHTML =
      `<div class="card"><h2>Draft #${r.id} · gross INR ${escapeHTML(r.calculation.total)}</h2>${table(r.calculation.rows, ["start", "end", "days", "due", "drawn", "prior_settlement", "difference"])}<h3>Deductions ${escapeHTML(r.calculation.total_deductions)} · Cash payable ${escapeHTML(r.calculation.net_payable)}</h3>${table(r.calculation.deductions, ["name", "amount"])}<a class="action" href="/suite/api/claims/${r.id}/excel">Excel</a><a class="action" href="/suite/api/claims/${r.id}/pdf">PDF</a></div>`;
    notify("Draft saved; review the source references before finalizing");
    await refresh();
  } catch (x) {
    notify(x.message);
  }
};
$("batchForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const p = Object.fromEntries(new FormData(e.target));
    p.employees = p.employees
      .split(",")
      .map((x) => x.trim())
      .filter(Boolean);
    const r = await post("batch", p);
    $("batchResult").innerHTML =
      r.saved +
      ' drafts prepared <a class="action" href="/suite/api/batch_export?ids=' +
      r.claims.map((c) => c.id).join(",") +
      '">Download PDF / Excel pack</a>';
    await refresh();
  } catch (x) {
    $("batchResult").textContent = x.message;
    notify("Batch not saved. Resolve the listed exceptions.");
  }
};
$("importForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api("imports", {
      method: "POST",
      body: new FormData(e.target),
    });
    notify(
      r.duplicate
        ? "This document is already imported"
        : "Document retained for review",
    );
    await refresh();
  } catch (x) {
    notify(x.message);
  }
};
function input(label, key, value, type = "text") {
  return `<label>${escapeHTML(label)}<input data-field="${escapeHTML(key)}" type="${type}" value="${escapeHTML(value)}" ${type === "number" ? 'step="0.01"' : ""}></label>`;
}
async function loadAnalyzerPayments() {
  try {
    const code = prompt("Employee code from the inner sheet");
    if (!code) return;
    const payments = await api(
      "analyzer_candidates?employee_code=" + encodeURIComponent(code),
    );
    if (!payments.length)
      throw Error("No imported inner-sheet rows found for this employee");
    reviewState = { id: null, payments };
    renderPaymentReview();
    $("reviewEmployee").value = code;
    $("reviewReference").value = "Reviewed inner-sheet source rows";
  } catch (e) {
    notify(e.message);
  }
}
function manualPayment() {
  reviewState = {
    id: null,
    payments: [
      {
        bill_no: "",
        pay_month: "",
        bill_type: "Regular Salary",
        allowances: { Basic: "", DA: "", HRA: "" },
        deductions: {},
      },
    ],
  };
  renderPaymentReview();
}
function reviewDocument(id) {
  const r = importRecords.find((x) => x.id === id);
  if (!r) return;
  reviewState = {
    id,
    payments: structuredClone(
      r.payload.ga55?.payments || [
        {
          bill_no: "",
          pay_month: "",
          bill_type: "Regular Salary",
          allowances: { Basic: "", DA: "", HRA: "" },
          deductions: {},
        },
      ],
    ),
  };
  renderPaymentReview();
}
function renderPaymentReview() {
  const state = reviewState;
  let html =
    '<div class="card"><h2>Review payment history</h2><p>Compare each candidate with its source. Enter amounts actually paid. For arrear bills, allocate the original entitlement period; the payment month is separate.</p><form id="reviewPayments"><label>Employee code<input id="reviewEmployee" list="employeeOptions"></label><label>Source reference<input id="reviewReference" required placeholder="Bill / source checked"></label>';
  state.payments.forEach((p, i) => {
    html += `<details class="payment-editor" data-index="${i}" ${i === 0 ? "open" : ""}><summary>${escapeHTML(p.pay_month)} · ${escapeHTML(p.bill_type)} · ${escapeHTML(p.bill_no)}</summary>${input("Employee code (or use common code above)", "employee_code", p.employee_code || "")}${input("Bill number", "bill_no", p.bill_no)}${input("Payment month", "pay_month", p.pay_month, "month")}${input("Bill type", "bill_type", p.bill_type)}${paymentCategoryInputs(p)}${input("Entitlement from (arrear)", "period_start", p.entitlement_period?.start || "", "date")}${input("Entitlement through", "period_end", p.entitlement_period?.end || "", "date")}${input("Printed gross", "printed_gross", p.printed_gross ?? "", "number")}${input("Printed deduction total", "printed_deductions", p.printed_deductions ?? "", "number")}${input("Printed net", "printed_net", p.printed_net ?? "", "number")}<h4>Allowances</h4><div class="allowances">${Object.entries(
      p.allowances || {},
    )
      .map(([k, v]) => input(k, k, v, "number"))
      .join(
        "",
      )}</div><h4>Deductions</h4><div class="deductions">${Object.entries(
      p.deductions || {},
    )
      .map(([k, v]) => deductionInput(k, v, p.deduction_effects?.[k] !== false))
      .join(
        "",
      )}</div><button type="button" class="action" data-add-head="${i}">Add allowance / deduction</button><p class="muted">${escapeHTML((p.issues || []).join(" · "))}</p></details>`;
  });
  html +=
    '<label><span>I checked identity, amounts and dates against the source</span><input type="checkbox" id="reviewChecked" required></label><button class="action">Approve payment history</button></form></div>';
  if (state.id)
    html = `<div class="grid"><div>${html}</div><div><iframe title="Original source" src="/suite/api/imports/${state.id}/source"></iframe></div></div>`;
  $("paymentReview").innerHTML = html;
  $("paymentReview").scrollIntoView({ behavior: "smooth" });
  $("paymentReview")
    .querySelectorAll("[data-add-head]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          const name = prompt("Allowance / deduction name");
          if (!name?.trim()) return;
          const kind = confirm(
            "Is this an allowance? Choose Cancel for a deduction.",
          )
            ? "allowances"
            : "deductions";
          const container = b
            .closest(".payment-editor")
            .querySelector("." + kind);
          container.insertAdjacentHTML(
            "beforeend",
            kind === "deductions"
              ? deductionInput(name.trim(), "", true)
              : input(name.trim(), name.trim(), "", "number"),
          );
        }),
    );
  document.querySelectorAll('.payment-editor [data-field="bill_type"]').forEach(
    (input) =>
      (input.onchange = () => {
        const editor = input.closest(".payment-editor"),
          kind = classifyBill(input.value);
        editor.querySelector('[data-field="payment_class"]').value = kind;
        editor.querySelector('[data-field="entitlement_type"]').value =
          kind === "leave_encashment" ? "leave_encashment" : "salary";
      }),
  );
  $("reviewPayments").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const code = $("reviewEmployee").value.trim(),
        reference = $("reviewReference").value;
      const payments = [...document.querySelectorAll(".payment-editor")].map(
        (el) => {
          const source = state.payments[Number(el.dataset.index)] || {};
          const p = {
            allowances: {},
            deductions: {},
            source_file: source.source_file,
            source_employee_row_id: source.source_employee_row_id,
            source_page: source.source_page,
          };
          for (const kind of ["allowances", "deductions"])
            el.querySelectorAll("." + kind + " input[data-field]").forEach(
              (i) => {
                if (i.value !== "") p[kind][i.dataset.field] = i.value;
              },
            );
          const read = (k) => el.querySelector(`[data-field="${k}"]`).value;
          p.employee_code = read("employee_code").trim() || code;
          if (!p.employee_code)
            throw Error("Confirm the employee code for every payment");
          p.deduction_effects = {};
          el.querySelectorAll("[data-effect]").forEach(
            (i) => (p.deduction_effects[i.dataset.effect] = i.checked),
          );
          for (const key of [
            "printed_gross",
            "printed_deductions",
            "printed_net",
          ]) {
            const v = read(key);
            if (v !== "") p[key] = v;
          }
          p.bill_no = read("bill_no");
          p.bill_type = read("bill_type");
          p.payment_class = read("payment_class");
          p.entitlement_type = read("entitlement_type");
          p.pay_month = read("pay_month");
          const a = read("period_start"),
            b = read("period_end");
          if (a || b) {
            if (!a || !b) throw Error("Both entitlement dates are required");
            p.entitlement_period = { start: a, end: b };
          }
          return p;
        },
      );
      if (state.id) {
        await post(`imports/${state.id}/review`, {
          employee_code: code,
          reviewed: $("reviewChecked").checked,
          payments,
        });
      } else {
        await post("payments/review_batch", {
          payments,
          employee_code: code,
          reviewed: true,
          reference,
        });
      }
      notify("Reviewed payment history saved");
      $("paymentReview").innerHTML = "";
      await refresh();
    } catch (x) {
      notify(x.message);
    }
  };
}
$("importsList").onclick = async (e) => {
  const b = e.target.closest("[data-review-import],[data-ocr]");
  if (!b) return;
  if (b.dataset.reviewImport) {
    const id = Number(b.dataset.reviewImport),
      r = importRecords.find((x) => x.id === id);
    if (r?.payload.kind === "due_drawn") reviewStatement(id);
    else reviewDocument(id);
    return;
  }
  try {
    b.disabled = true;
    notify("Local OCR is processing pages. Review will follow.");
    await post(`imports/${b.dataset.ocr}/ocr`, {
      language: $("ocrLanguage").value,
    });
    await refresh();
    notify(
      "OCR finished; compare candidates with the original before approving",
    );
  } catch (x) {
    notify(x.message);
  } finally {
    b.disabled = false;
  }
};
$("claimsList").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  if (f.dataset.settlement) {
    try {
      const p = Object.fromEntries(new FormData(f));
      p.reviewed = f.elements.reviewed.checked;
      if (!p.payment_id) delete p.payment_id;
      await post(`claims/${f.dataset.settlement}/settlement`, p);
      notify("Actual full settlement linked to statement");
      await refresh();
    } catch (x) {
      notify(x.message);
    }
    return;
  }
  if (!f.dataset.claim) return;
  try {
    const p = Object.fromEntries(new FormData(f));
    p.reviewed = f.elements.reviewed.checked;
    await post(`claims/${f.dataset.claim}/finalize`, p);
    notify("Statement finalized; calculation snapshot is retained");
    await refresh();
  } catch (x) {
    notify(x.message);
  }
};
$("groupReviews").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    const selections = {};
    f.querySelectorAll('input[type="radio"]:checked').forEach(
      (i) => (selections[i.name] = Number(i.value)),
    );
    await post(`group_imports/${f.dataset.group}/review`, {
      reviewed: f.elements.reviewed.checked,
      replace_current: f.elements.replace_current.checked,
      selections,
    });
    notify("Group profiles approved");
    await refresh();
  } catch (x) {
    notify(x.message);
  }
};
async function refresh() {
  const version = ++refreshVersion;
  const [employees, rates, claims, imports, groups, rules] = await Promise.all(
    ["employees", "rates", "claims", "imports", "group_imports", "rules"].map(
      (k) => api(k),
    ),
  );
  if (version !== refreshVersion) return;
  savedRules = rules;
  cachedRates = rates;
  importRecords = imports;
  groupRecords = groups;
  $("summary").textContent =
    `${employees.length} library employees · ${claims.length} statements · ${imports.length} documents`;
  $("employeeOptions").innerHTML = employees
    .map(
      (e) =>
        `<option value="${escapeHTML(e.employee_code)}">${escapeHTML(e.name)}</option>`,
    )
    .join("");
  $("employeesTable").innerHTML = table(employees, [
    "employee_code",
    "name",
    "group",
  ]);
  $("allowances").innerHTML = [
    ...new Set([
      "DA",
      "HRA",
      "HDA",
      "CCA",
      ...rules.map((r) => r.name),
      ...rates.map((r) => r.allowance),
    ]),
  ]
    .map((n) => `<option>${escapeHTML(n)}</option>`)
    .join("");
  $("rulesTable").innerHTML = table(rules, [
    "name",
    "basis",
    "proration",
    "rounding",
    "reference",
  ]);
  $("ratesTable").innerHTML = table(rates, [
    "allowance",
    "category",
    "effective_from",
    "rate",
    "order_date",
    "reference",
    "verification",
  ]);
  renderRateReference();
  $("importsList").innerHTML = imports
    .map(
      (i) =>
        `<div class="card"><h2>${escapeHTML(i.filename)}</h2><p>${escapeHTML(i.status)} · ${escapeHTML(i.payload.notice || "Review source before using amounts")}</p><a class="action" target="_blank" rel="noopener" href="/suite/api/imports/${i.id}/source">View source</a><a class="action" href="/suite/api/imports/${i.id}/pdf">PDF export</a><a class="action" href="/suite/api/imports/${i.id}/excel">Excel export</a>${i.status !== "reviewed" ? `<button class="action" data-review-import="${i.id}">${i.payload.kind === "due_drawn" ? "Check / recalculate statement" : "Review / enter payments"}</button>${i.payload.scan_pages?.length ? `<button class="action" data-ocr="${i.id}">Run local OCR</button>` : ""}` : ""}${i.payload.extracted ? outerSummary(i.payload.extracted) : ""}<p>${i.payload.ga55?.payments.length ?? 0} candidate payment entries</p><details><summary>Source text (${i.payload.pages.length} pages)</summary>${i.payload.pages.map((t, n) => `<h3>Page ${n + 1}</h3><pre>${escapeHTML(t || "No selectable text")}</pre>`).join("")}</details></div>`,
    )
    .join("");
  renderPersistent(
    "claimsList",
    claims
      .map(
        (c) =>
          `<div class="card"><h2>#${c.id} ${escapeHTML(c.payload.employee_code)} · ${escapeHTML(c.payload.allowance)}</h2><p>${escapeHTML(c.payload.start)} — ${escapeHTML(c.payload.end)} · ${escapeHTML(c.status)} · gross INR ${escapeHTML(c.calculation.total)} · cash INR ${escapeHTML(c.calculation.net_payable ?? c.calculation.total)}</p><a class="action" href="/suite/api/claims/${c.id}/excel">Excel</a><a class="action" href="/suite/api/claims/${c.id}/pdf">PDF</a>${c.status === "draft" ? `<form data-claim="${c.id}"><label>Rate / order reference<input name="rule_reference" required></label><label>Drawn-payment references<input name="drawn_reference" required></label><label><span>Inputs & rules checked</span><input name="reviewed" type="checkbox" required></label><button class="action">Finalize reviewed statement</button></form>` : c.status === "finalized" ? `<form data-settlement="${c.id}"><h3>Link actual full settlement</h3><p>Confirm payment or GPF credit against the external bill / GA55. This permits later rate revisions to deduct this settled arrear.</p><label>Existing reviewed payment ID (if already imported)<input name="payment_id" type="number"></label><label>Otherwise, actual arrear bill number<input name="bill_no"></label><label>Actual payment / credit month<input name="pay_month" type="month"></label><label>GA55 / external reference<input name="reference" required></label><label><span>Full amount paid or credited; source checked</span><input name="reviewed" type="checkbox" required></label><button class="action">Record settlement</button></form>` : ""}</div>`,
      )
      .join(""),
  );
  renderPersistent(
    "groupReviews",
    groups
      .filter((g) => !g.reviewed)
      .map((g) => {
        const grouped = {};
        g.payload.records.forEach((r, i) => {
          const code = r.employeeCode || r.employee_code || "";
          (grouped[code] ??= []).push([r, i]);
        });
        return `<form data-group="${g.id}"><h4>Snapshot #${g.id}</h4>${Object.entries(
          grouped,
        )
          .map(
            ([code, rows]) =>
              `<fieldset><legend>${escapeHTML(code || "MISSING CODE — correct the source import")}</legend>${rows.map(([r, i]) => `<label><span>${escapeHTML(r.employeeName || r.name)} · ${escapeHTML(r.groupName || r.group || "")}</span><input name="${escapeHTML(code)}" type="radio" value="${i}" ${rows.length === 1 ? "checked" : ""}></label>`).join("")}</fieldset>`,
          )
          .join(
            "",
          )}<label><span>Replace differing current profiles; retain previous versions</span><input name="replace_current" type="checkbox"></label><label><span>Identity & source rows checked</span><input name="reviewed" type="checkbox" required></label><button class="action">Approve selected profiles</button></form>`;
      })
      .join(""),
  );
}
refresh().catch((e) => notify(e.message));
function reviewStatement(id, sheet) {
  const record = importRecords.find((r) => r.id === id);
  const candidates = record.payload.statement_rows || [];
  const sheets = [...new Set(candidates.map((r) => r.source_sheet || "PDF"))];
  if (!candidates.length) {
    notify(
      "No supported table was recognized. Use OCR for a scan, or enter reviewed periods in the arrear maker. No amounts have been guessed.",
    );
    return;
  }
  sheet = sheet || sheets[0];
  const rows = candidates.filter((r) => (r.source_sheet || "PDF") === sheet);
  let html = `<div class="card"><h2>Check & recalculate due–drawn</h2><label>Source worksheet<select id="statementSheet">${sheets.map((s) => `<option ${s === sheet ? "selected" : ""}>${escapeHTML(s)}</option>`).join("")}</select></label><form id="statementForm"><label>Employee code<input name="employee_code" list="employeeOptions" required></label><label>Component<select name="allowance"><option>DA</option><option>HRA</option><option>BASIC</option></select></label><label>Entitlement<select name="entitlement_type"><option value="salary">Regular salary arrear</option><option value="leave_encashment">Leave encashment / surrender</option></select></label><label>Method<select name="method"><option value="rates">Recalculate from reviewed rate library</option><option value="uploaded">Use corrected uploaded due amounts</option></select></label><label>HRA category<select name="category"><option value="">General / DA</option><option>Y</option><option>Z</option></select></label><p>Enter the actual covered dates. If the uploaded amounts already represent those partial dates, tick the option below to avoid prorating twice.</p><label><span>Uploaded amounts already cover the selected dates</span><input name="period_amounts" type="checkbox"></label><div class="scroll"><table><thead><tr><th>Use</th><th>Month / source row</th><th>From</th><th>Through</th><th>Due basic</th><th>Due DA</th><th>Due HRA</th><th>Drawn basic</th><th>Drawn DA</th><th>Drawn HRA</th><th>Source checks</th></tr></thead><tbody>${rows
    .map((r, i) => {
      const [y, m] = r.month.split("-").map(Number);
      const end = r.month + "-" + new Date(y, m, 0).getDate();
      return `<tr class="statement-row" data-index="${i}"><td><input type="checkbox" data-use checked></td><td>${escapeHTML(r.month)} / ${escapeHTML(r.source_row)}</td><td><input type="date" data-key="start" value="${r.month}-01"></td><td><input type="date" data-key="end" value="${end}"></td>${["due", "drawn"].flatMap((kind) => ["Basic", "DA", "HRA"].map((k) => `<td><input type="number" step="0.01" data-kind="${kind}" data-head="${k}" value="${escapeHTML(r[kind][k])}" style="width:100px"></td>`)).join("")}<td>${escapeHTML((r.issues || []).join("; ") || "Source arithmetic matches")}<br>Printed difference ${escapeHTML(r.printed_difference ?? "not read")}; calculated ${escapeHTML(r.calculated_difference)}</td></tr>`;
    })
    .join(
      "",
    )}</tbody></table></div><label><span>Identity, figures, dates and applicable orders checked</span><input type="checkbox" name="reviewed" required></label><button class="action">Create revised statement draft</button></form></div>`;
  if (record.payload.file_kind !== "xlsx")
    html = `<div class="grid"><div>${html}</div><iframe title="Original statement" src="/suite/api/imports/${id}/source"></iframe></div>`;
  $("paymentReview").innerHTML = html;
  $("paymentReview").scrollIntoView({ behavior: "smooth" });
  $("statementSheet").onchange = (e) => reviewStatement(id, e.target.value);
  $("statementForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const p = Object.fromEntries(new FormData(e.target));
      p.import_id = id;
      p.source_sheet = sheet;
      p.reviewed = e.target.elements.reviewed.checked;
      p.amounts_cover_selected_period =
        e.target.elements.period_amounts.checked;
      p.rows = [...document.querySelectorAll(".statement-row")]
        .filter((el) => el.querySelector("[data-use]").checked)
        .map((el) => {
          const r = structuredClone(rows[Number(el.dataset.index)]);
          for (const k of ["start", "end"])
            r[k] = el.querySelector(`[data-key="${k}"]`).value;
          el.querySelectorAll("[data-kind]").forEach(
            (i) => (r[i.dataset.kind][i.dataset.head] = i.value),
          );
          return r;
        });
      const result = await post("statement_claim", p);
      notify(
        "Revised draft #" +
          result.id +
          " created; gross difference INR " +
          result.calculation.total,
      );
      openModule("reports");
    } catch (x) {
      notify(x.message);
    }
  };
}

function outerSummary(p) {
  return `<h3>Gross INR ${escapeHTML(p["Gross Amount"])} · deductions INR ${escapeHTML(p.Stated_Total_Deduction)} · net INR ${escapeHTML(p["Net Amount"])}</h3><p>${escapeHTML(p["Bill Name"])} · ${escapeHTML(p["Reference Number"])} · ${escapeHTML(p["Group Name"])}</p>${table(
    Object.entries(p.Allowances || {}).map(([head, amount]) => ({
      head,
      amount,
    })),
    ["head", "amount"],
  )}${table(
    Object.entries(p.Deductions || {}).map(([head, amount]) => ({
      head,
      amount,
    })),
    ["head", "amount"],
  )}<p>${escapeHTML((p.Confidence_Reasons || []).join(" · "))}</p>`;
}

$("previewRestore").onclick = async () => {
  try {
    const r = await api("restore/preview", {
      method: "POST",
      body: new FormData($("restoreForm")),
    });
    notify("Backup verified: " + r.files + " files, created " + r.created_at);
  } catch (e) {
    notify(e.message);
  }
};
$("restoreForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const r = await api("restore/stage", {
      method: "POST",
      body: new FormData(e.target),
    });
    notify(r.message);
  } catch (x) {
    notify(x.message);
  }
};

$("inspectEmployee").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const code = e.target.elements.employee_code.value;
    const [events, payments] = await Promise.all([
      api("pay_history?employee_code=" + encodeURIComponent(code)),
      api("payments?employee_code=" + encodeURIComponent(code)),
    ]);
    $("employeeHistory").innerHTML =
      "<h3>Approved pay timeline</h3>" +
      table(events, ["effective_from", "basic", "eligible", "reference"]) +
      "<h3>Reviewed payments</h3>" +
      payments
        .map(
          (p) =>
            `<details><summary>#${p.id} ${escapeHTML(p.pay_month)} · ${escapeHTML(p.bill_type)} · ${escapeHTML(p.bill_no)}</summary>${table(
              Object.entries(p.allowances || {}).map(([head, amount]) => ({
                head,
                amount,
              })),
              ["head", "amount"],
            )}<p>Entitlement period: ${escapeHTML(p.entitlement_period?.start || "not assigned")} — ${escapeHTML(p.entitlement_period?.end || "")}</p>${!p.entitlement_period && p.bill_type.toLowerCase() !== "regular salary" ? `<form data-allocation="${p.id}"><label>Entitlement from<input type="date" name="start" required></label><label>Through<input type="date" name="end" required></label><label>Sanction / source reference<input name="reference" required></label><label><span>Period checked against source</span><input name="reviewed" type="checkbox" required></label><button class="action">Assign arrear period</button></form>` : ""}${monthlyAllocationForm(p)}</details>`,
        )
        .join("");
  } catch (x) {
    notify(x.message);
  }
};
$("employeeHistory").onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  if (!f.dataset.allocation && !f.dataset.monthlyAllocation) return;
  try {
    const p = Object.fromEntries(new FormData(f));
    p.reviewed = f.elements.reviewed.checked;
    if (f.dataset.monthlyAllocation) {
      p.rows = [...f.querySelectorAll("tbody tr")].map((tr) =>
        Object.fromEntries(
          [...tr.querySelectorAll("input")].map((i) => [
            i.dataset.key,
            i.value,
          ]),
        ),
      );
      await post(
        `payments/${f.dataset.monthlyAllocation}/period_allocations`,
        p,
      );
    } else await post(`payments/${f.dataset.allocation}/allocate`, p);
    notify("Entitlement period saved");
    $("inspectEmployee").requestSubmit();
  } catch (x) {
    notify(x.message);
  }
};

function deductionInput(head, amount, affectsNet) {
  return `<div>${input(head, head, amount, "number")}<label><span>Affects net pay</span><input type="checkbox" data-effect="${escapeHTML(head)}" ${affectsNet ? "checked" : ""}></label></div>`;
}

function renderRateReference() {
  const form = $("claimForm"),
    allowance = form.elements.allowance.value.trim().toUpperCase(),
    category = form.elements.category.value;
  const rates = cachedRates
    .filter(
      (r) =>
        r.allowance.toUpperCase() === allowance &&
        (r.category || "") === category,
    )
    .sort((a, b) => a.effective_from.localeCompare(b.effective_from));
  if (!rates.length) {
    $("rateReference").textContent =
      "No matching rate. Choose the applicable category or add a manual rate with its source.";
    return;
  }
  const eligible = rates.filter(
    (r) => r.effective_from <= form.elements.start.value,
  );
  const preferred = eligible.at(-1) || rates[0];
  $("rateReference").innerHTML =
    '<label>Effective date / rate / order date<select id="rateChoice">' +
    rates
      .map(
        (r, i) =>
          `<option value="${i}" ${r === preferred ? "selected" : ""}>${escapeHTML(r.effective_from)} · ${escapeHTML(r.rate)} · order ${escapeHTML(r.order_date || "not supplied")}</option>`,
      )
      .join("") +
    '</select></label><div id="rateDetails"></div>';
  function details() {
    const r = rates[Number($("rateChoice").value)];
    $("rateDetails").innerHTML =
      `<p><b>${escapeHTML(r.allowance)} ${escapeHTML(r.category || "")}</b><br>Effective: ${escapeHTML(r.effective_from)}<br>Order: ${escapeHTML(r.order_date || "not supplied")}<br>${escapeHTML(r.reference)}<br>${r.verification === "official_source_checked" ? "Official source checked" : "Manual rate — verify applicability"}</p>${r.source_file ? `<a class="action" target="_blank" rel="noopener" href="/suite/api/reference/${encodeURIComponent(r.source_file)}">Read bundled order</a>` : ""}<p class="muted">${escapeHTML(r.notes || "")} ${r.cash_from ? "Cash commencement: " + escapeHTML(r.cash_from) : ""}</p>`;
  }
  $("rateChoice").onchange = details;
  details();
}

function renderPersistent(id, html) {
  const node = $(id);
  if (renderedHTML.get(id) === html) return;
  const key = (f) =>
    f.dataset.claim
      ? "claim:" + f.dataset.claim
      : f.dataset.settlement
        ? "settlement:" + f.dataset.settlement
        : f.dataset.group
          ? "group:" + f.dataset.group
          : null;
  const edits = new Map(
    [...node.querySelectorAll("form")]
      .filter((f) => key(f))
      .map((f) => [
        key(f),
        [...f.elements]
          .filter((i) => i.name)
          .map((i) => ({
            name: i.name,
            type: i.type,
            value: i.value,
            checked: i.checked,
          })),
      ]),
  );
  node.innerHTML = html;
  renderedHTML.set(id, html);
  node.querySelectorAll("form").forEach((f) => {
    for (const old of edits.get(key(f)) || []) {
      const choices = [...f.elements].filter(
        (i) => i.name === old.name && i.type === old.type,
      );
      const input =
        old.type === "radio"
          ? choices.find((i) => i.value === old.value)
          : choices[0];
      if (!input) continue;
      if (old.type === "checkbox" || old.type === "radio")
        input.checked = old.checked;
      else input.value = old.value;
    }
  });
}

function classifyBill(value) {
  const text = value.toLowerCase().trim();
  if (text.includes("arrear") || ["da", "hra", "hda", "cca"].includes(text))
    return "allowance_arrear";
  if (text.includes("surrender") || text.includes("encashment"))
    return "leave_encashment";
  if (text.includes("bonus")) return "bonus";
  if (text.includes("regular") && text.includes("salary"))
    return "regular_salary";
  return "other";
}
function paymentCategoryInputs(p) {
  const kind = p.payment_class || classifyBill(p.bill_type || "");
  const scope =
    p.entitlement_type ||
    (kind === "leave_encashment" ? "leave_encashment" : "salary");
  return `<label>Payment category<select data-field="payment_class">${[
    ["regular_salary", "Regular salary"],
    ["allowance_arrear", "Allowance arrear"],
    ["leave_encashment", "Surrender / leave encashment"],
    ["bonus", "Bonus"],
    ["other", "Other — requires separate review"],
  ]
    .map(
      ([v, n]) =>
        `<option value="${v}" ${v === kind ? "selected" : ""}>${n}</option>`,
    )
    .join(
      "",
    )}</select></label><label>Entitlement<select data-field="entitlement_type"><option value="salary" ${scope === "salary" ? "selected" : ""}>Salary</option><option value="leave_encashment" ${scope === "leave_encashment" ? "selected" : ""}>Leave encashment</option></select></label>`;
}
$("importAnalyzerProfiles").onclick = async () => {
  try {
    const r = await post("group_import/analyzer", {});
    notify(r.rows + " extracted employee rows staged for profile review");
    await refresh();
  } catch (e) {
    notify(e.message);
  }
};

function monthlyAllocationForm(p) {
  if (p.payment_class !== "allowance_arrear" || !p.entitlement_period)
    return "";
  const heads = Object.keys(p.allowances).filter(
    (h) => !p.allocations_by_head?.[h],
  );
  const saved = Object.entries(p.allocations_by_head || {})
    .map(
      ([head, parts]) =>
        `<h4>Saved ${escapeHTML(head)} allocations</h4>${table(parts, ["start", "end", "amount"])}`,
    )
    .join("");
  if (!heads.length) return saved;
  const rows = [];
  let cursor = p.entitlement_period.start;
  while (cursor <= p.entitlement_period.end && rows.length < 1200) {
    const [y, m] = cursor.split("-").map(Number),
      last = new Date(Date.UTC(y, m, 0)).getUTCDate();
    const monthEnd = `${y}-${String(m).padStart(2, "0")}-${last}`;
    const end =
      monthEnd < p.entitlement_period.end ? monthEnd : p.entitlement_period.end;
    rows.push(
      `<tr><td><input data-key="start" type="date" value="${cursor}" required></td><td><input data-key="end" type="date" value="${end}" required></td><td><input data-key="amount" type="number" step="0.01" required></td></tr>`,
    );
    const next = new Date(end + "T00:00:00Z");
    next.setUTCDate(next.getUTCDate() + 1);
    cursor = next.toISOString().slice(0, 10);
  }
  return (
    saved +
    `<form data-monthly-allocation="${p.id}"><h4>Review monthly arrear amounts</h4><label>Allowance<select name="head">${heads.map((h) => `<option>${escapeHTML(h)}</option>`).join("")}</select></label><p>Enter the amounts in the original monthly statement. Dates and total must reconcile with this bill. Saved allocations cannot be overwritten.</p><div class="scroll"><table><thead><tr><th>From</th><th>Through</th><th>Actual arrear paid</th></tr></thead><tbody>${rows.join("")}</tbody></table></div><label>Source reference<input name="reference" required></label><label><span>Monthly amounts checked</span><input name="reviewed" type="checkbox" required></label><button class="action">Save reviewed monthly amounts</button></form>`
  );
}
