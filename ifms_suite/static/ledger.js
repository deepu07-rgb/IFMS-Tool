"use strict";

// The ledger uses the reviewed payment history; it does not keep another copy
// of financial balances in the browser.
async function loadLedgerSources() {
  const sources = await api('imports');
  const options = sources.filter(s => s.payload.file_kind === 'pdf').map(s =>
    `<option value="${Number(s.id)}">${escapeHTML(s.filename)} · #${Number(s.id)}</option>`).join('');
  for (const formId of ['ledgerSourceForm', 'ledgerCaseForm']) {
    const select = $(formId).elements.import_id;
    const previous = select.value;
    select.innerHTML = options;
    if ([...select.options].some(o => o.value === previous)) select.value = previous;
  }
  const [master, saved] = await Promise.all([api('employees'), api('ledger/employees')]);
  const employees = [...new Map([...master, ...saved].map(e => [e.employee_code, e])).values()];
  $('ledgerEmployees').innerHTML = employees.map(e =>
    `<option value="${escapeHTML(e.employee_code)}">${escapeHTML(e.name)}</option>`).join('');
}

function ledgerPayment(payment) {
  const values = heads => Object.entries(heads || {}).map(([head, amount]) =>
    `<span>${escapeHTML(head)}: ${escapeHTML(amount)}</span>`).join(' · ');
  const source = payment.ledger_source;
  return `<details><summary>${escapeHTML(payment.bill_no)} · ${escapeHTML(payment.bill_type)} · ${escapeHTML(payment.ledger_status || 'reviewed')}</summary>
    <p>Allowances: ${values(payment.allowances) || 'Unresolved'}</p>
    <p>Deductions: ${values(payment.deductions) || 'Unresolved'}</p>
    <p>Printed gross ${escapeHTML(payment.printed_gross ?? 'unresolved')} · deductions ${escapeHTML(payment.printed_deductions ?? 'unresolved')} · net ${escapeHTML(payment.printed_net ?? 'unresolved')}</p>
    ${payment.ledger_issue ? `<p class="warning">${escapeHTML(payment.ledger_issue)}</p>` : ''}
    ${source ? `<a target="_blank" rel="noopener" href="/suite/api/imports/${Number(source.source_import)}/source">View original PDF</a>` : ''}
    <p>${escapeHTML(payment.reference || '')}</p></details>`;
}

async function loadEmployeeLedger(code) {
  const ledger = await api('ledger?employee_code=' + encodeURIComponent(code));
  $('ledgerRecords').innerHTML = `<h2>${escapeHTML(ledger.employee_code)}</h2><p>${Number(ledger.payment_count)} saved payment records</p>` +
    (ledger.months.map(month => `<div class="card"><h3>${escapeHTML(month.pay_month)} · ${escapeHTML(month.status)}</h3>
      ${(month.issues || []).map(i => `<p class="warning">${escapeHTML(typeof i === 'string' ? i : i.issue || i.message)}</p>`).join('')}
      <h4>Regular salary drawn</h4>${month.regular_salary.map(ledgerPayment).join('') || '<p>No regular salary established for this month.</p>'}
      <h4>Previous arrear / other payments</h4>${month.prior_credits.map(ledgerPayment).join('') || '<p>None saved. Check the source for any additional paid credits.</p>'}</div>`).join('') || '<p>No saved monthly records. Add verified source records below.</p>');
  return ledger;
}

$('ledgerEmployeeForm').onsubmit = async e => {
  e.preventDefault();
  try { await loadEmployeeLedger(e.target.elements.employee_code.value.trim()); }
  catch (error) { notify(error.message); }
};

$('ledgerSourceForm').onsubmit = async e => {
  e.preventDefault();
  const id = Number(e.target.elements.import_id.value);
  try {
    const data = await api(`imports/${id}/case_review`);
    const bills = data.facts.bills || [];
    $('ledgerSourceRecords').innerHTML = `<p><a href="/suite/api/imports/${id}/source" target="_blank" rel="noopener">View original PDF</a></p>
      <form id="saveSourceLedger"><div class="scroll"><table><thead><tr><th>Save</th><th>Employee</th><th>Pay month</th><th>Bill</th><th>Type</th><th>Printed gross</th><th>Printed deductions</th><th>Printed net</th><th>Source status</th></tr></thead><tbody>${bills.map((b,i) =>
        `<tr><td><input type="checkbox" name="bill_index" value="${i}" aria-label="Save bill ${escapeHTML(b.bill_no)}"></td><td>${escapeHTML(b.employee_code)}</td><td>${escapeHTML(b.pay_month)}</td><td>${escapeHTML(b.bill_no)}</td><td>${escapeHTML(b.bill_type)}</td><td>${escapeHTML(b.printed_gross ?? 'unresolved')}</td><td>${escapeHTML(b.printed_deductions ?? 'unresolved')}</td><td>${escapeHTML(b.printed_net ?? 'unresolved')}</td><td>${b.complete && b.deductions_complete && b.net_reconciled ? 'Reconciled candidate; verify original' : b.human_reviewed ? 'Source reviewed' : 'Source review required'}</td></tr>`).join('')}</tbody></table></div>
      <label>Original verification reference<input name="reference" required></label>
      <label><input type="checkbox" name="reviewed" required>I checked the selected bills’ identity, dates, signs, heads and totals against the original</label>
      <button class="action">Save selected records to ledger</button><button type="button" class="action" id="reviewLedgerSource">Resolve source fields</button></form>`;
    $('reviewLedgerSource').onclick = () => openBillCase(id).catch(x => notify(x.message));
    $('saveSourceLedger').onsubmit = async event => {
      event.preventDefault();
      const form = event.target;
      const selected = [...form.querySelectorAll('[name="bill_index"]:checked')].map(input => Number(input.value));
      const button = form.querySelector('button'); button.disabled = true;
      try {
        if (!selected.length) throw Error('Select at least one source bill.');
        const saved = await post(`imports/${id}/ledger`, {bill_indexes:selected, reviewed:form.elements.reviewed.checked, reference:form.elements.reference.value});
        const code = bills[selected[0]].employee_code;
        $('ledgerEmployeeForm').elements.employee_code.value = code;
        await loadEmployeeLedger(code);
        notify(`${saved.saved} source records saved. They will be reused for this employee’s arrear cases.`);
      } catch (error) { notify(error.message); }
      finally { button.disabled = false; }
    };
  } catch (error) { notify(error.message); }
};

$('ledgerCaseForm').onsubmit = async e => {
  e.preventDefault();
  try { await openBillCase(Number(e.target.elements.import_id.value)); }
  catch (error) { notify(error.message); }
};
