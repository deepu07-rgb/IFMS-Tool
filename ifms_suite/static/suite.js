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
  ["salary_ledger", "Salary Ledger"],
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
    $("documentFilterForm").reset();
    $("documentKindFilter").value = k === "outer" ? "outer" : "ga55";
    document.querySelector('#imports h1').textContent = k === 'outer' ? 'Outer Sheet Analyzer' : 'GA55 / OCR';
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
  if (id === 'salary_ledger' && typeof loadLedgerSources === 'function') {
    loadLedgerSources().catch(e => notify(e.message));
  }
}
function openLegacy(tab) {
  openModule("legacy");
  $("legacyTitle").textContent = ({schedules:"Schedules & Comparison",backup:"Backup & Restore",exportcenter:"Export Centre"})[tab] || "Inner Sheet Analyzer";
  const module = tab === "schedules" ? "schedules" : ["backup","exportcenter"].includes(tab) ? "reports" : "inner";
  document.querySelectorAll("#navigation button").forEach(b=>b.classList.toggle("active",b.dataset.module===module));
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
function renderAutomaticHra(result, id) {
$("automaticHraResults").innerHTML = `<h2>HRA source reconciliation</h2><p>${escapeHTML(result.notice)}</p>${result.blockers.map(x => `<p class="warning">${escapeHTML(x)}</p>`).join("")}${result.claims.map(c => `<p>${c.human_assisted ? "Human-assisted draft" : "Machine-generated draft"} #${c.id} · ${escapeHTML(c.employee_code)} · HRA INR ${escapeHTML(c.calculation.total)} <a href="/suite/api/claims/${c.id}/pdf">PDF</a> <a href="/suite/api/claims/${c.id}/excel">Excel</a></p>`).join("")}<details><summary>Extracted facts and source evidence</summary><pre>${escapeHTML(JSON.stringify(result.facts, null, 2))}</pre></details>`;
  $("automaticHraResults").innerHTML += (result.review_requests || []).map(r => `<form data-rate-review="${escapeHTML(r.request_id)}" data-import="${Number(id)}" data-version="${escapeHTML(r.facts_version)}"><h3>Check one source field</h3><p>${escapeHTML(r.employee_code)} · effective ${escapeHTML(r.effective_from)} · original page ${r.page}</p><img src="/suite/api/imports/${Number(id)}/fact_review/${escapeHTML(r.request_id)}/image" alt="Original sanction row" style="max-width:100%"><label>HRA percentage in this row<input name="rate" type="number" min="0.01" max="100" step="0.01" required></label><label>Source reference<input name="reference" value="Original PDF page ${r.page}" required></label><label><span>I checked this field against the original</span><input name="reviewed" type="checkbox" required></label><button class="action">Confirm this field and build draft</button><p>This confirmation is recorded as human review, not automatic recognition.</p></form>`).join("");
}
$("automaticHraResults").onsubmit = async e => {
  e.preventDefault();
  const form=e.target;
  if (!form.dataset.rateReview) return;
  const button=form.querySelector('button'); button.disabled=true;
  try {
    const result=await post(`imports/${form.dataset.import}/fact_review`,{request_id:form.dataset.rateReview,facts_version:form.dataset.version,rate:form.elements.rate.value,reference:form.elements.reference.value,reviewed:form.elements.reviewed.checked});
    await refresh();renderAutomaticHra(result,form.dataset.import);
    notify(result.claims.length ? "Draft built with the recorded human field confirmation" : "Other source facts still need review");
  } catch(x) {notify(x.message);} finally {button.disabled=false;}
};
$("importsList").onclick = async (e) => {
  const b = e.target.closest("[data-review-import],[data-ocr],[data-automatic-hra],[data-evidence]");
  if (!b) return;
  if (b.dataset.evidence) {
    b.disabled = true;
    try { renderEvidence(await api(`imports/${b.dataset.evidence}/evidence`), b.dataset.evidence); }
    catch (x) { notify(x.message); } finally { b.disabled=false; }
    return;
  }
  if (b.dataset.automaticHra) {
    b.disabled = true;
    notify("Reading printed salary and sanction records locally. This can take a few minutes.");
    try {
      const result = await post(`imports/${b.dataset.automaticHra}/automatic_hra`, {});
      await refresh();
      renderAutomaticHra(result, b.dataset.automaticHra);
      notify(result.claims.length ? "Machine draft saved; verify evidence and deductions before final approval" : "Draft blocked: source facts need review. No figures were guessed.");
    } catch (x) { notify(x.message); }
    finally { b.disabled = false; }
    return;
  }
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
      if (f.elements.machine_facts_reviewed) p.machine_facts_reviewed = f.elements.machine_facts_reviewed.checked;
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
      if (f.elements.machine_facts_reviewed) p.machine_facts_reviewed = f.elements.machine_facts_reviewed.checked;
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
  const [employees, rates, claims, imports, groups, rules, completeBills] = await Promise.all(
    ["employees", "rates", "claims", "imports", "group_imports", "rules", "bills"].map(
      (k) => api(k),
    ),
  );
  if (version !== refreshVersion) return;
  savedRules = rules;
  cachedRates = rates;
  importRecords = imports;
  groupRecords = groups;
  $("summary").textContent =
    `${employees.length} library employees · ${claims.length} component statements · ${completeBills.length} consolidated bills · ${imports.length} documents`;
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
    .filter(i => !$("documentKindFilter").value || i.payload.kind === $("documentKindFilter").value)
    .map(
      (i) =>
        `<div class="card"><h2>${escapeHTML(i.filename)}</h2><p>${escapeHTML(i.status)} · ${escapeHTML(i.payload.notice || "Review source before using amounts")}</p><a class="action" target="_blank" rel="noopener" href="/suite/api/imports/${i.id}/source">View source</a><a class="action" href="/suite/api/imports/${i.id}/pdf">Original PDF</a><a class="action" href="/suite/api/imports/${i.id}/excel">Full Excel</a>${i.status !== "reviewed" ? `<button class="action" data-review-import="${i.id}">${i.payload.kind === "due_drawn" ? "Check / recalculate statement" : "Review / enter payments"}</button>${i.payload.scan_pages?.length ? `<button class="action" data-ocr="${i.id}">Run local OCR</button>` : ""}` : ""}${i.payload.file_kind === "pdf" ? `<button class="action" data-complete-bill="${i.id}">Prepare complete bill</button>` : ""}${i.payload.file_kind === "pdf" && i.status !== "reviewed" ? `<button class="action" data-evidence="${i.id}">Review unresolved source fields</button>` : ""}${i.payload.file_kind === "pdf" ? `<button class="action" data-automatic-hra="${i.id}">Build HRA draft from PDF</button>` : ""}${i.payload.extracted ? outerSummary(i.payload.extracted) : ""}<p>${i.payload.ga55?.payments.length ?? 0} candidate payment entries</p><details><summary>Source text (${i.payload.pages.length} pages)</summary>${i.payload.pages.map((t, n) => `<h3>Page ${n + 1}</h3><pre>${escapeHTML(t || "No selectable text")}</pre>`).join("")}</details></div>`,
    )
    .join("");
  renderPersistent(
    "claimsList",
    claims
      .map(
        (c) =>
          `<div class="card"><h2>#${c.id} ${escapeHTML(c.payload.employee_code)} · ${escapeHTML(c.payload.allowance)}</h2>${c.payload.machine_generated ? `<p>${c.payload.machine_evidence?.order?.human_reviewed ? "Human-assisted source draft" : "Machine-generated source draft"} · check eligibility and deductions before final approval</p>` : ""}<p>${escapeHTML(c.payload.start)} — ${escapeHTML(c.payload.end)} · ${escapeHTML(c.status)} · gross INR ${escapeHTML(c.calculation.total)} · cash INR ${escapeHTML(c.calculation.net_payable ?? c.calculation.total)}</p><a class="action" href="/suite/api/claims/${c.id}/excel">Excel</a><a class="action" href="/suite/api/claims/${c.id}/pdf">PDF</a>${c.status === "draft" ? `<form data-claim="${c.id}"><label>Rate / order reference<input name="rule_reference" required></label><label>Drawn-payment references<input name="drawn_reference" required></label>${c.payload.machine_generated ? `<label><span>Machine-extracted identity, dates, amounts, eligibility and deductions checked</span><input name="machine_facts_reviewed" type="checkbox" required></label>` : ""}<label><span>Inputs & rules checked</span><input name="reviewed" type="checkbox" required></label><button class="action">Finalize reviewed statement</button></form>` : c.status === "finalized" ? `<form data-settlement="${c.id}"><h3>Link actual full settlement</h3><p>Confirm payment or GPF credit against the external bill / GA55. This permits later rate revisions to deduct this settled arrear.</p><label>Existing reviewed payment ID (if already imported)<input name="payment_id" type="number"></label><label>Otherwise, actual arrear bill number<input name="bill_no"></label><label>Actual payment / credit month<input name="pay_month" type="month"></label><label>GA55 / external reference<input name="reference" required></label><label><span>Full amount paid or credited; source checked</span><input name="reviewed" type="checkbox" required></label><button class="action">Record settlement</button></form>` : ""}</div>`,
      )
      .join(""),
  );
  loadDocumentRecords().catch(e=>notify(e.message));
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
  const statementHeads = [...new Set(rows.flatMap(r => [...Object.keys(r.due || {}), ...Object.keys(r.drawn || {})]))];
  let html = `<div class="card"><h2>Check & recalculate due–drawn</h2><label>Source worksheet<select id="statementSheet">${sheets.map((s) => `<option ${s === sheet ? "selected" : ""}>${escapeHTML(s)}</option>`).join("")}</select></label><form id="statementForm"><label>Employee code<input name="employee_code" list="employeeOptions" required></label><label>Component<select name="allowance"><option>DA</option><option>HRA</option><option>BASIC</option></select></label><label>Entitlement<select name="entitlement_type"><option value="salary">Regular salary arrear</option><option value="leave_encashment">Leave encashment / surrender</option></select></label><label>Method<select name="method"><option value="rates">Recalculate from reviewed rate library</option><option value="uploaded">Use corrected uploaded due amounts</option></select></label><label>HRA category<select name="category"><option value="">General / DA</option><option>Y</option><option>Z</option></select></label><p>Enter the actual covered dates. If the uploaded amounts already represent those partial dates, tick the option below to avoid prorating twice.</p><label><span>Uploaded amounts already cover the selected dates</span><input name="period_amounts" type="checkbox"></label><div class="scroll"><table><thead><tr><th>Use</th><th>Month / source row</th><th>From</th><th>Through</th>${["due", "drawn"].flatMap(kind => statementHeads.map(head => `<th>${escapeHTML(kind)} ${escapeHTML(head)}</th>`)).join("")}<th>Source checks</th></tr></thead><tbody>${rows
    .map((r, i) => {
      const [y, m] = r.month.split("-").map(Number);
      const end = r.month + "-" + new Date(y, m, 0).getDate();
      return `<tr class="statement-row" data-index="${i}"><td><input type="checkbox" data-use checked></td><td>${escapeHTML(r.month)} / ${escapeHTML(r.source_row)}</td><td><input type="date" data-key="start" value="${r.month}-01"></td><td><input type="date" data-key="end" value="${end}"></td>${["due", "drawn"].flatMap((kind) => statementHeads.map((k) => `<td><input type="number" step="0.01" data-kind="${kind}" data-head="${k}" value="${escapeHTML(r[kind]?.[k] ?? "")}" style="width:100px"></td>`)).join("")}<td>${escapeHTML((r.issues || []).join("; ") || "Source arithmetic matches")}<br>Printed difference ${escapeHTML(r.printed_difference ?? "not read")}; calculated ${escapeHTML(r.calculated_difference)}</td></tr>`;
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
            )}<p>Entitlement period: ${escapeHTML(p.entitlement_period?.start || "not assigned")} — ${escapeHTML(p.entitlement_period?.end || "")}</p>${!p.entitlement_period && p.bill_type.toLowerCase() !== "regular salary" ? `<form data-allocation="${p.id}"><label>Entitlement from<input type="date" name="start" required></label><label>Through<input type="date" name="end" required></label><label>Sanction / source reference<input name="reference" required></label><label><span>Period checked against source</span><input name="reviewed" type="checkbox" required></label><button class="action">Assign arrear period</button></form>` : ""}${monthlyAllocationForm(p)}${p.payment_class === "regular_salary" ? `<button class="action" data-increment-payment="${p.id}">Use for increment check</button>` : ""}</details>`,
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
      if (f.elements.machine_facts_reviewed) p.machine_facts_reviewed = f.elements.machine_facts_reviewed.checked;
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

$("employeeHistory").onclick = async (e) => {
  const button = e.target.closest("[data-increment-payment]");
  if (!button) return;
  try {
    const code = $("inspectEmployee").elements.employee_code.value;
    const payments = await api(
      "payments?employee_code=" + encodeURIComponent(code),
    );
    const payment = payments.find(
      (p) => p.id === Number(button.dataset.incrementPayment),
    );
    const f = $("incrementForm"),
      heads = Object.fromEntries(
        Object.entries(payment.allowances).map(([k, v]) => [
          k.toUpperCase(),
          v,
        ]),
      );
    f.elements.employee_code.value = code;
    f.elements.month.value = payment.pay_month;
    for (const head of ["BASIC", "DA", "HRA", "HDA"])
      f.elements["drawn_" + head].value = heads[head] ?? "";
    f.elements.unchanged_total.value = Object.entries(heads)
      .filter(([k]) => !["BASIC", "DA", "HRA", "HDA"].includes(k))
      .reduce((total, [k, v]) => total + Number(v), 0)
      .toFixed(2);
    f.elements.printed_drawn_gross.value = payment.printed_gross || "";
    f.elements.drawn_reference.value =
      payment.bill_no + " / " + payment.reference;
    f.elements.category.value = "";
    f.elements.hra_eligibility_reference.value = "";
    f.elements.new_basic.value = "";
    f.elements.effective_from.value = "";
    f.elements.reviewed.checked = false;
    openModule("arrears");
    f.scrollIntoView({ behavior: "smooth" });
  } catch (error) {
    notify(error.message);
  }
};
$("incrementForm").onsubmit = async (e) => {
  e.preventDefault();
  try {
    const f = e.target,
      p = Object.fromEntries(new FormData(f));
    const [year, month] = p.month.split("-").map(Number);
    p.start = p.month + "-01";
    p.end = p.month + "-" + new Date(Date.UTC(year, month, 0)).getUTCDate();
    p.reviewed = f.elements.reviewed.checked;
      if (f.elements.machine_facts_reviewed) p.machine_facts_reviewed = f.elements.machine_facts_reviewed.checked;
    p.hra_eligible = p.category !== "NONE";
    p.drawn = {};
    for (const head of ["BASIC", "DA", "HRA", "HDA"])
      p.drawn[head] = p["drawn_" + head];
    p.hda_rule = {
      numerator: p.hda_numerator,
      denominator: p.hda_denominator,
      reference: p.hda_reference,
    };
    p.unchanged_allowances = {
      "Other unchanged allowances": p.unchanged_total,
    };
    const result = await post("increment_check", p);
    $("incrementResult").innerHTML =
      `<h3>Increment difference INR ${escapeHTML(result.total)}</h3>${table(result.components, ["head", "due", "drawn", "difference", "formula", "reference"])}<p>Selected-head subtotal: due ${escapeHTML(result.selected_due)}, drawn ${escapeHTML(result.selected_drawn)}. Including unchanged allowances: due ${escapeHTML(result.full_due_gross)}, drawn ${escapeHTML(result.full_drawn_gross)}.</p><p>${escapeHTML(result.warnings.join("; "))}</p><a class="action" href="/suite/api/batch_export?ids=${result.claim_ids.join(",")}">Download PDF/Excel component pack</a><p>Drafts saved in Reports for review and finalization.</p>`;
    notify(
      "Increment checked using the dated library; review component drafts",
    );
    await refresh();
  } catch (error) {
    notify(error.message);
  }
};

function renderEvidence(result, id) {
  const target = $("paymentReview");
  target.innerHTML = `<h2>Review unresolved bill fields</h2><p>Confirm only fields you can verify in the original. Other source issues may still block preparation.</p>${result.requests.map((r,n)=>`<details><summary>${escapeHTML(r.pay_month || "Month unresolved")} · ${escapeHTML(r.field)} · ${escapeHTML(r.value ?? "Not read")}</summary><a target="_blank" rel="noopener" href="/suite/api/imports/${Number(id)}/source#page=${Number(r.source_pages[0])}">Open original page ${Number(r.source_pages[0])}</a><form data-evidence-index="${n}"><label>Verified ${escapeHTML(r.field)}<input name="value" required value="${escapeHTML(r.value ?? "")}"></label><label>Source reference<input name="reference" required value="Original page ${Number(r.source_pages[0])}"></label><label><input type="checkbox" name="reviewed" required>I checked this field against the original</label><button class="action">Save this field</button></form></details>`).join("") || "<p>No supported unresolved bill fields. Check remaining order, page or payment issues.</p>"}`;
  target.onsubmit = async e => {
    const form = e.target.closest("[data-evidence-index]");
    if (!form) return;
    e.preventDefault();
    const r=result.requests[Number(form.dataset.evidenceIndex)];
    const button=form.querySelector("button"); button.disabled=true;
    try {
      const updated=await post(`imports/${id}/evidence`, {request_id:r.request_id, field:r.field, source_sha256:r.source_sha256, facts_version:r.facts_version, value:form.elements.value.value, reference:form.elements.reference.value, reviewed:form.elements.reviewed.checked});
      await refresh(); renderEvidence(updated,id); notify("Field confirmation saved; remaining evidence still needs checking");
    } catch(x) {notify(x.message); button.disabled=false;}
  };
  target.scrollIntoView({behavior:"smooth"});
}

// Complete source case workflow; pay figures are taken from saved evidence.
const billWorkspace = document.createElement('div');
billWorkspace.id = 'billWorkspace';
$('arrears').prepend(billWorkspace);
function componentEditor(name, values, effects = {}) {
  return `<fieldset data-components="${name}"><legend>${escapeHTML(name)}</legend>${Object.entries(values || {}).map(([head,value])=>`<div class="component-pair"><input aria-label="Component name" data-component-head value="${escapeHTML(head)}"><input aria-label="Source amount" data-component-amount type="number" step="0.01" value="${escapeHTML(value)}">${(effects[head] ?? effects[head.toUpperCase()]) === false ? '<small>Non-accounting; excluded from printed net</small>' : ''}</div>`).join('')}<button type="button" data-add-component>Add component</button></fieldset>`;
}
function readComponents(form, name) {
  const values={};
  form.querySelectorAll(`[data-components="${name}"] .component-pair`).forEach(row=>{
    const head=row.querySelector('[data-component-head]').value.trim();
    const amount=row.querySelector('[data-component-amount]').value;
    if(head) {if(Object.hasOwn(values,head))throw Error('Duplicate component '+head); values[head]=amount;}
  });
  return values;
}
async function openBillCase(id) {
  notify('Loading saved source evidence and order decisions');
  const [result, employees]=await Promise.all([api(`imports/${id}/case_review`),api('ledger/employees')]);
  result.ledger_employees=employees;
  renderBillCase(id,result); openModule('arrears'); notify('Source evidence loaded. Review unresolved fields before preparing the bill.');
}
function renderBillCase(id,result) {
  const codes=[...new Set([...(result.facts.bills||[]),...(result.facts.orders||[]),...(result.facts.pay_orders||[]),...(result.ledger_employees||[])].map(b=>b.employee_code).filter(Boolean))];
  billWorkspace.innerHTML=`<div class="card"><h2>Complete bill from source case #${Number(id)}</h2><p>Review unresolved evidence, select the claim dates, then prepare one monthly statement. Saved decisions are reused.</p><a href="/suite/api/imports/${Number(id)}/source" target="_blank" rel="noopener">View original PDF</a>
  ${(result.requests||[]).map((r,i)=>`<details><summary>Order review · page ${r.source_pages.join(', ')} · ${escapeHTML(r.kind || 'type unresolved')}</summary><p>Use the entitlement date in the employee's sanction row. Confirm the source employee and terms.</p><form data-order-index="${i}"><label>Order kind<select name="kind"><option value="increment" ${r.kind==='increment'?'selected':''}>Increment / sanctioned revised basic</option><option value="hra" ${r.kind==='hra'?'selected':''}>HRA</option><option value="da" ${r.kind==='da'?'selected':''}>DA</option></select></label><label>Employee<select name="employee_code">${codes.map(c=>`<option ${c===r.employee_code?'selected':''}>${escapeHTML(c)}</option>`).join('')}</select></label><label>Effective from<input type="date" name="effective_from" value="${escapeHTML(r.candidate.effective_from||'')}" required></label><label>Effective through (if limited)<input type="date" name="effective_to" value="${escapeHTML(r.candidate.effective_to||'')}"></label><label>Sanctioned new basic (increment)<input name="basic_amount" type="number" step="0.01" value="${escapeHTML(r.candidate.basic_amount||'')}"></label><label>Sanctioned percentage (HRA/DA)<input name="rate" type="number" step="0.01" value="${escapeHTML(r.candidate.rate||'')}"></label><label>HRA eligibility<select name="hra_eligible"><option value="">Check separately</option><option value="true">Payable</option><option value="false">Not payable</option></select></label><label>HDA numerator (if applicable)<input name="hda_numerator" type="number" step="0.0001"></label><label>HDA denominator<input name="hda_denominator" type="number" step="0.0001"></label><label>HDA governing reference<input name="hda_reference"></label><label>Order / source reference<input name="reference" required></label><label><input type="checkbox" name="entire_page_reviewed">I checked the entire source page and its employee-specific terms</label><label><input type="checkbox" name="reviewed" required>I checked these fields against the original</label><button class="action">Save order decision</button></form></details>`).join('')}
  ${(result.unsupported_pages||[]).map(page=>`<details><summary>Unclassified source page ${Number(page)}</summary><p>Only use this if the page is a comparison due–drawn. Orders and payment records must be reviewed in their own workflow.</p><form data-reference-page="${Number(page)}"><label>Reference<input name="reference" required></label><label><input name="reviewed" type="checkbox" required>I checked that this page contains only the comparison statement and no additional sanction or payment evidence</label><button class="action">Classify comparison page</button></form></details>`).join('')}
  ${(result.bill_requests||[]).map((r,i)=>{const b=r.record;return `<details><summary>${b.complete?'Check source bill':'Resolve source bill'} · ${escapeHTML(b.pay_month)} · ${escapeHTML(b.bill_no)} · pages ${r.source_pages.join(', ')}</summary><form data-source-bill-index="${i}">${['employee_code','pay_month','bill_no','bill_type','printed_gross','printed_deductions','printed_net'].map(k=>`<label>${escapeHTML(k.replaceAll('_',' '))}<input name="${k}" value="${escapeHTML(b[k]??'')}" required></label>`).join('')}<label>Actual drawn coverage from (partial source only)<input name="covered_start" type="date" value="${escapeHTML(b.covered_dates?.start||'')}"></label><label>Actual drawn coverage through<input name="covered_end" type="date" value="${escapeHTML(b.covered_dates?.end||'')}"></label><label>Monthly basic from source (required for partial HRA/DA)<input name="monthly_basic" type="number" step="0.01" value="${escapeHTML(b.monthly_basic||'')}"></label><label>Prior arrear entitlement from<input name="entitlement_start" type="date" value="${escapeHTML(b.entitlement_period?.start||'')}"></label><label>Prior arrear entitlement through<input name="entitlement_end" type="date" value="${escapeHTML(b.entitlement_period?.end||'')}"></label><fieldset data-allocation-editor><legend>Prior arrear monthly allocations (head, from, through, paid amount)</legend>${Object.entries(b.allocations_by_head||{}).flatMap(([head,parts])=>parts.map(part=>allocationEditor(head,part))).join('')}<button type="button" data-add-allocation>Add allocation</button></fieldset>${componentEditor('allowances',b.allowances)}${componentEditor('deductions',b.deductions,b.deduction_effects)}<label>Original bill reference<input name="reference" required></label><label><input name="reviewed" type="checkbox" required>I checked identity, all heads, signs and printed totals against the original bill</label><button class="action">Save reconciled source bill</button></form></details>`;}).join('')}
  <h3>Read a ruled reference statement</h3><form id="statementGridForm"><label>Original page<input name="page" type="number" min="1" value="1" required></label><button class="action">Read individual table cells</button></form><div id="statementGridResult"></div><h3>Prepare consolidated statement</h3><form id="completeBillForm"><label>Employee<select name="employee_code">${codes.map(c=>`<option>${escapeHTML(c)}</option>`).join('')}</select></label><label>Arrear kind<select name="kind"><option value="increment">Increment / sanctioned revised basic</option><option value="hra">HRA</option><option value="da">DA</option></select></label><label>From<input name="start" type="date" required></label><label>Through<input name="end" type="date" required></label><label>HRA category<select name="category"><option value="Y">Y</option><option value="Z">Z</option><option value="">General / not applicable</option></select></label><label>Proration rule<select name="proration"><option value="calendar">Calendar days</option><option value="thirty">Thirty-day rule</option></select></label><label>Rounding<select name="rounding"><option value="rupee">Whole rupee</option><option value="paise">Paise</option></select></label><input type="hidden" name="rounding_scope" value="month"><label>Additional arrear deduction name<input name="extra_deduction_name" value="GPF adjustment"></label><label>Additional arrear deduction amount (0 if none)<input name="extra_deduction_amount" type="number" step="0.01" min="0" value="0"></label><label>Deduction review reference<input name="deduction_reference"></label><label><input type="checkbox" name="deductions_reviewed">I checked additional arrear deductions, including a zero adjustment</label><button class="action">Prepare complete bill</button></form><div id="completeBillResult"></div></div>`;
  billWorkspace.onclick=e=>{const allocation=e.target.closest('[data-add-allocation]');if(allocation)allocation.insertAdjacentHTML('beforebegin',allocationEditor('',{}));const add=e.target.closest('[data-add-component]');if(add)add.insertAdjacentHTML('beforebegin','<div class="component-pair"><input aria-label="Component name" data-component-head><input aria-label="Source amount" type="number" step="0.01" data-component-amount></div>');};
  billWorkspace.onsubmit=async e=>{
    e.preventDefault();const form=e.target;const button=form.querySelector('button[type="submit"],button.action');if(button)button.disabled=true;
    try {
      let payload=Object.fromEntries(new FormData(form));
      if(form.dataset.orderIndex!==undefined){const r=result.requests[Number(form.dataset.orderIndex)];payload={...payload,request_id:r.request_id,facts_version:r.facts_version,source_sha256:r.source_sha256,reviewed:form.elements.reviewed.checked,entire_page_reviewed:form.elements.entire_page_reviewed.checked};if(payload.hra_eligible==='')delete payload.hra_eligible;else payload.hra_eligible=payload.hra_eligible==='true';if(payload.hda_numerator||payload.hda_denominator)payload.hda_rule={numerator:payload.hda_numerator,denominator:payload.hda_denominator,reference:payload.hda_reference};delete payload.hda_numerator;delete payload.hda_denominator;delete payload.hda_reference;if(!payload.effective_to)delete payload.effective_to;await post(`imports/${id}/case_review`,payload);}
      else if(form.dataset.referencePage!==undefined){await post(`imports/${id}/case_review`,{type:'reference_page',page:Number(form.dataset.referencePage),reference:payload.reference,reviewed:form.elements.reviewed.checked});}
      else if(form.dataset.sourceBillIndex!==undefined){const r=result.bill_requests[Number(form.dataset.sourceBillIndex)];const record={...r.record,...payload,allowances:readComponents(form,'allowances'),deductions:readComponents(form,'deductions')};if(payload.covered_start||payload.covered_end)record.covered_dates={start:payload.covered_start,end:payload.covered_end};if(payload.entitlement_start||payload.entitlement_end)record.entitlement_period={start:payload.entitlement_start,end:payload.entitlement_end};const allocations={};form.querySelectorAll('[data-allocation-row]').forEach(el=>{const head=el.querySelector('[data-allocation-head]').value.trim();if(head)(allocations[head]??=[]).push({start:el.querySelector('[data-allocation-start]').value,end:el.querySelector('[data-allocation-end]').value,amount:el.querySelector('[data-allocation-amount]').value});});if(Object.keys(allocations).length)record.allocations_by_head=allocations;await post(`imports/${id}/case_review`,{type:'source_bill',request_id:r.request_id,record,reference:payload.reference,reviewed:form.elements.reviewed.checked});}
      else if(form.id==='statementGridForm'){const grid=await post(`imports/${id}/statement_grid`,{page:Number(payload.page)});renderStatementGrid(id,grid);return;}
      else if(form.id==='completeBillForm'){
        payload.deductions_reviewed=form.elements.deductions_reviewed.checked;
        if(Number(payload.extra_deduction_amount)!==0)payload.extra_deductions=[{name:payload.extra_deduction_name,mode:'fixed',value:payload.extra_deduction_amount,reference:payload.deduction_reference}];
        delete payload.extra_deduction_name;delete payload.extra_deduction_amount;
        const bill=await post(`imports/${id}/bill_prepare`,payload);await loadCompleteBills();
        $('completeBillResult').innerHTML=`<h3>${bill.status==='ready'?'Consolidated draft prepared':'Source checks still required'}</h3>${(bill.blockers||[]).map(b=>`<p class="warning">${escapeHTML(b.month||'')} ${escapeHTML(b.message)}</p>`).join('')}${(bill.rows||[]).map(row=>`<h4>${escapeHTML(row.month)}</h4>${table(row.components,['head','due','drawn','prior_settlement','difference'])}`).join('')}${bill.reference_comparison?`<p class="warning">Reference comparison: ${escapeHTML(({reference_not_read:'Statement not read automatically; compare the original manually.',candidate_discrepancies:'Read cells differ from the source calculation; verify the original.',candidate_matches:'Read cells match; confirm source comparison before approval.',reference_review_required:'Reference figures remain unresolved; check the original.'})[bill.reference_comparison.status]||bill.reference_comparison.status)}</p>${table(bill.reference_comparison.discrepancies||[],['month','side','head','reference','source_calculation'])}`:''}<p>Gross arrear: ${escapeHTML(bill.totals?.difference??'unresolved')} · Net: ${escapeHTML(bill.deductions_confirmed ? bill.totals?.net_payable : 'provisional; confirm deductions')}</p>${bill.bill_id?billFormDownloads(bill.bill_id,bill.status==='ready'):''}`;notify(bill.status==='ready'?'Consolidated draft prepared; verify deductions and source comparison.':'Provisional calculation saved; resolve the listed source checks before approval.');return;
      }
      await refresh();await openBillCase(id);notify('Source decision saved; dependent checks updated');
    }catch(x){notify(x.message);}finally{if(button)button.disabled=false;}
  };
}
$('importsList').addEventListener('click', e=>{const button=e.target.closest('[data-complete-bill]');if(button)openBillCase(Number(button.dataset.completeBill)).catch(x=>notify(x.message));});

function allocationEditor(head,part) {
 return `<div data-allocation-row><input aria-label="Paid head" data-allocation-head value="${escapeHTML(head)}"><input aria-label="Covered from" type="date" data-allocation-start value="${escapeHTML(part.start||'')}"><input aria-label="Covered through" type="date" data-allocation-end value="${escapeHTML(part.end||'')}"><input aria-label="Amount paid" type="number" step="0.01" data-allocation-amount value="${escapeHTML(part.amount||'')}"></div>`;
}
function billFormDownloads(id, ready) {
 if(!ready)return '<p class="warning">Office-form export is unavailable until the source calculation is complete. Verified provisional rows remain visible above.</p>';
 return `<fieldset data-bill-downloads="${Number(id)}"><legend>Supplied due–drawn format</legend><label>Form variant<select data-bill-template><option value="jodhpur_classic">Supplied form — GPF / SI / CM Corona / income tax</option><option value="jodhpur_gpf_arrear">Supplied form — GPF arrear columns</option></select></label><a class="action" data-form-pdf href="/suite/api/bills/${Number(id)}/pdf?template=jodhpur_classic">PDF</a><a class="action" data-form-excel href="/suite/api/bills/${Number(id)}/excel?template=jodhpur_classic">Excel</a></fieldset>`;
}
document.addEventListener('change', e=>{
 const select=e.target.closest('[data-bill-template]');if(!select)return;
 const group=select.closest('[data-bill-downloads]');
 for(const kind of ['pdf','excel'])group.querySelector(`[data-form-${kind}]`).href=`/suite/api/bills/${Number(group.dataset.billDownloads)}/${kind}?template=${encodeURIComponent(select.value)}`;
});
const completeBillHistory=document.createElement('div');completeBillHistory.id='completeBillHistory';$('reports').prepend(completeBillHistory);
async function loadCompleteBills() {
 const bills=await api('bills');
 completeBillHistory.innerHTML='<h2>Consolidated due–drawn bills</h2>'+bills.map(b=>`<div class="card"><h3>Bill #${b.id} · ${escapeHTML(b.payload.selection.employee_code)} · ${escapeHTML(b.status)}</h3><p>${escapeHTML(b.payload.selection.start)} through ${escapeHTML(b.payload.selection.end)} · gross arrear ${escapeHTML(b.result.totals.difference)}</p>${billFormDownloads(b.id,b.result.status==='ready')}${b.status==='draft'?`<form data-final-complete-bill="${b.id}"><label>Source and deduction reference<input name="reference" required></label><label><input name="reviewed" type="checkbox" required>I checked source figures, rules, dates and prior payments</label><label><input name="deductions_reviewed" type="checkbox" required>I checked the additional arrear deductions shown in this statement, including any zero adjustment</label>${b.result.reference_comparison?`<label><input name="comparison_reviewed" type="checkbox" required>I checked the reference due–drawn against the original, including discrepancies or unreadable cells</label>`:""}<button class="action">Finalize reviewed bill</button></form>`:''}</div>`).join('');
}
completeBillHistory.onsubmit=async e=>{const form=e.target.closest('[data-final-complete-bill]');if(!form)return;e.preventDefault();try{await post(`bills/${form.dataset.finalCompleteBill}/finalize`,{reference:form.elements.reference.value,reviewed:form.elements.reviewed.checked,deductions_reviewed:form.elements.deductions_reviewed.checked,comparison_reviewed:form.elements.comparison_reviewed?.checked===true});await loadCompleteBills();notify('Reviewed complete bill finalized');}catch(x){notify(x.message);}};
loadCompleteBills().catch(x=>notify(x.message));

function renderStatementGrid(id,grid) {
 const target=$('statementGridResult');
 const rows=grid.editable_rows||grid.table_rows||[];
 const columns=rows.reduce((n,r)=>Math.max(n,r.length),0);
 const cells=new Map((grid.cells||[]).map(c=>[`${c.row}:${c.column}`,c]));
 const corrected=new Set((grid.corrected_cells||[]).map(c=>`${c.row}:${c.column}`));
 const marginRegions=grid.editable_margin_regions||grid.source_margin_regions||[];
 const marginPanel=marginRegions.length?`<div data-margin-panel><h3>Source margin handwriting · column unresolved</h3><p>These observed source regions lie outside the resolved table columns. Transcriptions remain separate annotations and never become mapped financial values.</p><form id="gridMarginCorrections"><div class="scroll" style="max-height:45vh;overflow:auto"><table><thead><tr><th>Source region</th><th>Transcription annotation</th><th>Raw candidates</th></tr></thead><tbody>${marginRegions.map((region,index)=>`<tr><th>${escapeHTML(region.region_id)} · physical row ${region.row+1}</th><td><input data-grid-margin="${index}" aria-label="Margin transcription ${escapeHTML(region.region_id)}" value="${escapeHTML(region.editable_text??region.text??'')}"><small>${region.origin==='human'?'Human transcription annotation':'Unassigned source region · review required'}</small></td><td>${(region.candidates||[]).map((candidate,candidateIndex)=>`<button type="button" data-margin-candidate data-margin-region="${index}" data-candidate-index="${candidateIndex}">Use ${escapeHTML(candidate.text??'')}</button>`).join('')||'No machine reading'}</td></tr>`).join('')}</tbody></table></div><label>Original margin review reference<input name="reference" required></label><label><input name="reviewed" type="checkbox" required>I checked my changed margin transcriptions against the original; their table columns remain unresolved</label><button class="action">Save margin transcription annotations</button></form></div>`:'';

 const options='<option value="">Not used</option>'+Array.from({length:columns},(_,i)=>`<option value="${i}">Column ${i+1}</option>`).join('');
 const binding={page:grid.source_page,source_sha256:grid.source_sha256,grid_revision:grid.grid_revision,correction_revision:grid.correction_revision};
 const collect=(onlyChanged=false)=>Array.from(target.querySelectorAll('[data-grid-cell]'),input=>({row:Number(input.dataset.row),column:Number(input.dataset.column),text:input.value})).filter(cell=>!onlyChanged||cell.text!==String(rows[cell.row]?.[cell.column]??''));
 target.innerHTML=`<p class="warning">${escapeHTML(grid.notice||'Raw OCR suggestions need checking against the source. Confidence is not measured accuracy.')}</p><p>${(grid.cells||[]).reduce((sum,c)=>sum+(c.candidates||[]).filter(candidate=>candidate.text).length,0)} raw OCR suggestions; ${(grid.cells||[]).filter(c=>c.status==='recognized').length} unambiguous machine cells; ${(grid.semantic_rows||[]).length} reference comparison rows. Every detected cell below is editable, including uncertain suggestions and blanks. Saving corrections preserves the original machine results.</p><div style="display:flex;flex-wrap:wrap;gap:1rem;align-items:flex-start"><div style="flex:1 1 340px;min-width:0"><p>Original page ${grid.source_page} · <a href="/suite/api/imports/${id}/source#page=${grid.source_page}" target="_blank" rel="noopener">Open original PDF</a></p><img id="gridSourceImage" src="/suite/api/imports/${id}/statement_grid/${grid.source_page}/image" alt="Original statement page ${grid.source_page}; compare each editable cell with this source" style="width:100%;max-height:650px;object-fit:contain;object-position:top"><p id="gridCropLabel">Focus a cell to magnify its source region.</p><canvas id="gridCellCrop" style="max-width:100%;border:1px solid #aaa" aria-label="Magnified original source cell"></canvas></div><div style="flex:2 1 480px;min-width:0"><form id="gridCellCorrections"><div class="scroll" data-grid-scroll style="max-height:58vh;overflow:auto"><table><thead style="position:sticky;top:0;background:white;z-index:1"><tr><th>Physical row</th>${Array.from({length:columns},(_,i)=>`<th>Column ${i+1}</th>`).join('')}</tr></thead><tbody>${rows.map((row,r)=>`<tr><th>${r+1}</th>${row.map((value,c)=>{const cell=cells.get(`${r}:${c}`);const candidates=(cell?.candidates||[]).map(x=>x.text).filter(Boolean).join(' | ');return `<td><input data-grid-cell data-row="${r}" data-column="${c}" aria-label="Row ${r+1}, column ${c+1}" value="${escapeHTML(value??'')}" style="min-width:8rem"><small>${corrected.has(`${r}:${c}`)?'Human reviewed':escapeHTML(cell?.status||'Machine table cell')}${candidates?` · Raw: ${escapeHTML(candidates)}`:''}</small>${(cell?.candidates||[]).map((candidate,index)=>`<button type="button" data-grid-candidate data-row="${r}" data-column="${c}" data-candidate-index="${index}" aria-label="Use raw candidate ${escapeHTML(candidate.text??'')} for row ${r+1}, column ${c+1}">Use ${escapeHTML(candidate.text??'')}</button>`).join('')}</td>`;}).join('')}</tr>`).join('')}</tbody></table></div><label>Source review reference<input name="reference" required placeholder="Page / original record checked"></label><label><input name="reviewed" type="checkbox" required>I checked my changed cell entries against the original; blanks remain unreadable or empty</label><button class="action">Save reviewed cell entries</button></form></div></div>${marginPanel}${columns?`<details><summary>Map reviewed cells to reference comparison rows</summary><p>These rows are only a reference comparison. They do not establish entitlement, pay rates or financial proof. Totals are never used to infer missing cells.</p><form id="gridColumnMapping"><label>Month column<select name="month">${options}</select></label>${['due','drawn'].map(group=>`<fieldset><legend>${group}</legend>${['Basic','DA','HRA','HDA','CCA','Total'].map(head=>`<label>${head}<select name="${group}.${head}">${options}</select></label>`).join('')}</fieldset>`).join('')}<label>Source header and cell review reference<input name="reference" required></label><label><input type="checkbox" name="reviewed" required>I checked every cell entry and this mapping against the original printed headings</label><button class="action">Save cells and apply checked mapping</button></form></details>`:''}<p>${escapeHTML((grid.issues||[]).join('; '))}</p><div id="gridSemanticRows">${(grid.semantic_rows||[]).map(r=>`<p>${escapeHTML(r.month)}: ${escapeHTML((r.issues||[]).join('; '))}</p>`).join('')}</div><details><summary>Cell correction audit (${(grid.correction_audit||[]).length} saves)</summary>${(grid.correction_audit||[]).map(event=>`<p>${escapeHTML(event.recorded_at)} · ${escapeHTML(event.reference)} · revision ${event.revision}</p><ul>${event.changes.map(c=>`<li>${c.region_id?`Source margin ${escapeHTML(c.region_id)}`:`Row ${c.row+1}, column ${c.column+1}`}: ${escapeHTML(c.before??'Blank')} → ${escapeHTML(c.after||'Blank')}</li>`).join('')}</ul>`).join('')}</details>`;
 const image=$('gridSourceImage');
 const showSourceRegion=(polygon,label)=>{
  $('gridCropLabel').textContent=label+(polygon?'':' · source region unavailable; inspect the full page');
  const canvas=$('gridCellCrop'),context=canvas.getContext('2d');
  context.clearRect(0,0,canvas.width,canvas.height);
  if(!polygon||!image.complete||!image.naturalWidth)return;
  const xs=polygon.map(p=>p[0]),ys=polygon.map(p=>p[1]);
  const x=Math.max(0,Math.floor(Math.min(...xs))),y=Math.max(0,Math.floor(Math.min(...ys)));
  const width=Math.min(image.naturalWidth-x,Math.ceil(Math.max(...xs))-x),height=Math.min(image.naturalHeight-y,Math.ceil(Math.max(...ys))-y);
  if(width<=0||height<=0)return;
  canvas.width=width;canvas.height=height;
  context.drawImage(image,x,y,width,height,0,0,width,height);
 };
 const showCrop=input=>{const r=Number(input.dataset.row),c=Number(input.dataset.column);showSourceRegion(cells.get(`${r}:${c}`)?.source_polygon,`Original row ${r+1}, column ${c+1}`);};
 target.querySelectorAll('[data-grid-margin]').forEach(input=>input.addEventListener('focus',()=>{const region=marginRegions[Number(input.dataset.gridMargin)];if(region)showSourceRegion(region.source_polygon,`Original source margin ${region.region_id} · column unresolved`);}));
 target.querySelectorAll('[data-margin-candidate]').forEach(button=>button.addEventListener('click',()=>{const index=Number(button.dataset.marginRegion),candidate=marginRegions[index]?.candidates?.[Number(button.dataset.candidateIndex)],input=target.querySelector(`[data-grid-margin="${index}"]`);if(input&&candidate&&typeof candidate.text==='string'){input.value=candidate.text;input.focus();}}));
 const marginForm=$('gridMarginCorrections');
 if(marginForm)marginForm.onsubmit=async e=>{e.preventDefault();e.stopPropagation();try{const margin_corrections=Array.from(target.querySelectorAll('[data-grid-margin]'),input=>({region:marginRegions[Number(input.dataset.gridMargin)],text:input.value})).filter(item=>item.region&&item.text!==String(item.region.editable_text??item.region.text??'')).map(item=>({region_id:item.region.region_id,text:item.text}));if(!margin_corrections.length)throw Error('Change a source margin transcription before saving.');const result=await post(`imports/${id}/statement_grid`,{...binding,margin_corrections,reviewed:marginForm.elements.reviewed.checked,reference:marginForm.elements.reference.value});renderStatementGrid(id,result);notify('Reviewed margin annotations saved; column assignment remains unresolved');}catch(x){notify(x.message);}};
 target.querySelectorAll('[data-grid-cell]').forEach(input=>input.addEventListener('focus',()=>showCrop(input)));
 target.querySelectorAll('[data-grid-candidate]').forEach(button=>button.addEventListener('click',()=>{const r=Number(button.dataset.row),c=Number(button.dataset.column),candidate=cells.get(`${r}:${c}`)?.candidates?.[Number(button.dataset.candidateIndex)];const input=target.querySelector(`[data-grid-cell][data-row="${r}"][data-column="${c}"]`);if(input&&candidate&&typeof candidate.text==='string'){input.value=candidate.text;input.focus();}}));
 image.onload=()=>{const input=target.querySelector('[data-grid-cell]');if(input)showCrop(input);};
 const correctionForm=$('gridCellCorrections');
 correctionForm.onsubmit=async e=>{e.preventDefault();e.stopPropagation();try{const corrections=collect(true);if(!corrections.length)throw Error('Change a cell entry before saving corrections. Use the checked mapping form to review all entries.');const result=await post(`imports/${id}/statement_grid`,{...binding,corrections,reviewed:correctionForm.elements.reviewed.checked,reference:correctionForm.elements.reference.value});renderStatementGrid(id,result);notify('Reviewed entries saved; original OCR preserved');}catch(x){notify(x.message);}};
 const form=$('gridColumnMapping');if(form)form.onsubmit=async e=>{e.preventDefault();e.stopPropagation();try{const values=Object.fromEntries(new FormData(form));if(values.month==='')throw Error('Choose the source month column');const mapping={month_column:Number(values.month),groups:{due:{},drawn:{}}};for(const group of ['due','drawn'])for(const head of ['Basic','DA','HRA','HDA','CCA','Total'])if(values[group+'.'+head]!=='')mapping.groups[group][head]=Number(values[group+'.'+head]);const result=await post(`imports/${id}/statement_grid`,{...binding,corrections:collect(),mapping,reviewed:form.elements.reviewed.checked,reference:values.reference});renderStatementGrid(id,result);}catch(x){notify(x.message);}};
}

let documentRecordsRequest=0;
async function loadDocumentRecords() {
 const version=++documentRecordsRequest;
 const query=new URLSearchParams(new FormData($('documentFilterForm')));
 const data=await api('document_records?'+query);
 if(version!==documentRecordsRequest)return;
 const selected=$('documentAmountField').value;
 $('documentAmountField').innerHTML=data.amount_fields.map(field=>`<option value="${escapeHTML(field)}">${escapeHTML(field.replace(':',': '))}</option>`).join('');
 if(data.amount_fields.includes(selected))$('documentAmountField').value=selected;
 $('documentRecords').innerHTML=`<p><b>${data.count} matching records</b></p>`+table(data.records,['document','employee_code','pay_month','bill_type','bill_no','gross','net']);
 $('filteredDocumentPdf').href='/suite/api/document_records/pdf?'+query;
 $('filteredDocumentExcel').href='/suite/api/document_records/excel?'+query;
}
$('documentFilterForm').onsubmit=e=>{e.preventDefault();loadDocumentRecords().catch(x=>notify(x.message));};
$('clearDocumentFilters').onclick=()=>{$('documentFilterForm').reset();refresh().catch(x=>notify(x.message));};
$('documentKindFilter').onchange=()=>refresh().catch(x=>notify(x.message));
