"use strict";

// Human-entered literals are the calculation input. OCR and spreadsheet formulas
// never replace these figures. Saved drafts, revisions and ledger links live on the server.
const worksheetState = {schema:null, payload:null, id:null, revision:null, dirty:false, tab:'drawn', result:null, salaryRecords:null, localPdf:null};
const worksheetMeta = ['employee_code','employee_name','kind','rounding','template_id','include_hda'];
const worksheetHeads = ['BASIC','DA','HRA','HDA','CCA'];
const worksheetForm = $('worksheetSetup');
const worksheetDate = d => `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
const worksheetToday = new Date();
worksheetForm.elements.claim_start.value = worksheetDate(new Date(worksheetToday.getFullYear(),worksheetToday.getMonth(),1));
worksheetForm.elements.claim_end.value = worksheetDate(new Date(worksheetToday.getFullYear(),worksheetToday.getMonth()+1,0));

function worksheetCollect() {
  const p = worksheetState.payload || {rows:[]};
  for (const key of worksheetMeta) p[key] = key === 'include_hda' ? worksheetForm.elements[key].checked : worksheetForm.elements[key].value.trim();
  worksheetState.payload = p;
  return p;
}
function worksheetChanged() {
  worksheetState.dirty = true;
  worksheetState.result = null;
  $('worksheetSaveStatus').textContent = `${worksheetState.id ? 'Draft #'+worksheetState.id+' · revision '+worksheetState.revision : 'New draft'} · unsaved edits`;
  $('worksheetResult').textContent = 'Inputs changed. Choose Check and calculate to refresh the statement.';
  $('worksheetErrors').textContent = '';
  $('worksheetTables').querySelectorAll('.worksheet-invalid').forEach(e=>e.classList.remove('worksheet-invalid'));
}
function worksheetSet(payload, saved=null) {
  worksheetState.payload = structuredClone(payload);
  worksheetState.id = saved?.id ?? null;
  worksheetState.revision = saved?.revision ?? null;
  worksheetState.dirty = !saved;
  for (const key of worksheetMeta) {
    if (key === 'include_hda') worksheetForm.elements[key].checked = payload[key] === true;
    else worksheetForm.elements[key].value = payload[key] ?? '';
  }
  if (payload.rows?.length) {
    worksheetForm.elements.claim_start.value = payload.rows[0].start || '';
    worksheetForm.elements.claim_end.value = payload.rows.at(-1).end || '';
  }
  $('worksheetSaveStatus').textContent = saved ? `Draft #${saved.id} · revision ${saved.revision} · ${saved.audit_count} recorded revisions` : 'New draft · import or edits are not saved yet';
  worksheetRender();
  worksheetRenderResult(saved?.result || null);
}
async function loadWorksheetWorkspace() {
  if (!worksheetState.schema) worksheetState.schema = await api('worksheets/schema');
  const [drafts, employees, imports] = await Promise.all([api('worksheets'),api('employees'),api('imports')]);
  const current = $('worksheetSaved').value;
  $('worksheetSaved').innerHTML = '<option value="">Select a draft</option>' + drafts.map(d=>`<option value="${Number(d.id)}">#${Number(d.id)} · ${escapeHTML(d.employee_name || d.employee_code || 'Incomplete')} · ${escapeHTML(d.kind)} · ${Number(d.months)} months</option>`).join('');
  if (current) $('worksheetSaved').value = current;
  $('worksheetEmployees').innerHTML = employees.map(e=>`<option value="${escapeHTML(e.employee_code)}">${escapeHTML(e.name)}</option>`).join('');
  const source = $('worksheetSourceSelect').value;
  $('worksheetSourceSelect').innerHTML = '<option value="">Select original</option>' + imports.filter(i=>i.payload.file_kind==='pdf').map(i=>`<option value="${Number(i.id)}">${escapeHTML(i.filename)}</option>`).join('');
  if (source) $('worksheetSourceSelect').value = source;
  if (!worksheetState.payload) worksheetCollect();
  worksheetRender();
  worksheetUpdateTemplate();
}
function worksheetUpdateTemplate() {
  const q = new URLSearchParams({start:worksheetForm.elements.claim_start.value,end:worksheetForm.elements.claim_end.value});
  $('worksheetBlankTemplate').href = '/suite/api/worksheets/template?' + q;
}
function worksheetFields(tab) {
  const p = worksheetState.payload || worksheetCollect();
  if (tab === 'drawn') return ['start','end','presentation',...worksheetHeads.map(h=>'drawn_'+h),'bill_no','bill_date','tv_no','tv_date','salary_reference'];
  if (tab === 'entitlement') {
    const fields = p.kind === 'manual' ? worksheetHeads.map(h=>'due_'+h) : p.kind === 'hra' ? ['hra_rate'] : p.kind === 'da' ? ['da_rate'] : ['new_basic','da_rate','hra_rate'];
    if (['da','increment'].includes(p.kind) && p.include_hda) fields.push('hda_divisor');
    return [...fields,'order_reference'];
  }
  if (tab === 'prior') return [...worksheetHeads.map(h=>'prior_'+h),'history_reference','history_reviewed'];
  const fields = worksheetState.schema.templates[p.template_id]?.deduction_keys || [];
  const inactive = worksheetState.schema.columns.filter(c=>c.group==='deductions'&&!fields.includes(c.key.slice(4))&&p.rows.some(r=>r[c.key]!==''&&r[c.key]!=null&&Number(r[c.key])!==0)).map(c=>c.key);
  return [...fields.map(k=>'ded_'+k),...inactive,'deduction_reference','deductions_reviewed'];
}
function worksheetRender() {
  if (!worksheetState.schema) return;
  const p = worksheetState.payload;
  const schemas = new Map(worksheetState.schema.columns.map(c=>[c.key,c]));
  const tabs = ['drawn','entitlement','prior','deductions'];
  const options = worksheetState.schema.templates[p.template_id]?.deduction_keys || [];
  const helper = {
    drawn:'Actual full-month salary amounts. Use period for selected days, or whole_month to retain original pay for unaffected days. Saved ledger amounts stay linked until you choose manual values.',
    entitlement:'Enter the sanctioned rate or amount for each month. DA and HRA are percentages of basic. HDA uses (Basic + unrounded DA) / the approved divisor. Enter 0 for confirmed no HRA entitlement.',
    prior:'Enter only earlier payments NOT already included in drawn pay. Allocate each amount to the head and claim month it covers; payment month alone is not enough.',
    deductions:'Enter only extra deductions from this arrear. In the newer form, GPF/SIF already deducted are disclosed and are not subtracted again.'
  };
  $('worksheetTables').innerHTML = tabs.map(tab=>{
    const fields = worksheetFields(tab);
    const tools = tab==='entitlement' ? '<button class="action" type="button" data-ws-action="fill-entitlement">Fill blank entitlement cells from first month</button>' : tab==='prior' ? '<button class="action" type="button" data-ws-action="review-prior">After source check: mark blank earlier payments as 0</button>' : tab==='deductions' ? '<button class="action" type="button" data-ws-action="review-deductions">After source check: mark blank extra deductions as 0</button>' : '';
    return `<div data-ws-panel="${tab}" ${tab===worksheetState.tab?'':'hidden'}><p>${helper[tab]}</p>${tools}<div class="scroll"><table class="worksheet-table" data-ws-table="${tab}"><thead><tr><th>Month</th>${fields.map(k=>`<th>${escapeHTML(schemas.get(k)?.label||k)}</th>`).join('')}${tab==='drawn'?'<th>Source link</th>':''}</tr></thead><tbody>${p.rows.map((row,i)=>`<tr><th>${escapeHTML(row.month||'Missing month')}</th>${fields.map(k=>{
      const value = row[k] ?? '';
      const common = `data-row="${i}" data-key="${k}" aria-label="${escapeHTML((schemas.get(k)?.label||k)+' '+(row.month||i+1))}"`;
      if (k.endsWith('_reviewed')) return `<td><input ${common} type="checkbox" ${value===true?'checked':''}></td>`;
      if (k==='presentation') return `<td><select ${common}><option value="period" ${value==='period'?'selected':''}>Affected days only</option><option value="whole_month" ${value==='whole_month'?'selected':''}>Whole month</option></select></td>`;
      const linked = k.startsWith('drawn_') && row.ledger_payment_id;
      const isAmount = ['drawn_','prior_','due_','ded_'].some(s=>k.startsWith(s)) || ['new_basic','da_rate','hra_rate','hda_divisor'].includes(k);
      return `<td><input ${common} type="${['start','end'].includes(k)?'date':'text'}" ${isAmount?'inputmode="decimal"':''} value="${escapeHTML(value)}" ${linked?'readonly title="Linked to a saved salary; choose manual values to edit"':''}></td>`;
    }).join('')}${tab==='drawn'?`<td>${row.ledger_payment_id?`Ledger #${Number(row.ledger_payment_id)}<button type="button" data-ws-action="detach" data-row="${i}">Use edited/manual pay</button>`:'Manual / Excel entry'}</td>`:''}</tr>`).join('')}</tbody></table></div>${p.rows.length?'':'<p>Create monthly rows above, load a ledger or import a completed formula workbook.</p>'}</div>`;
  }).join('');
  worksheetSelectTab(worksheetState.tab);
  worksheetForm.elements.include_hda.closest('label').hidden = !['da','increment'].includes(p.kind);
}
function worksheetSelectTab(tab) {
  worksheetState.tab = tab;
  document.querySelectorAll('[data-ws-panel]').forEach(el=>el.hidden=el.dataset.wsPanel!==tab);
  $('worksheetTabs').querySelectorAll('button').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.sheet===tab)));
}
$('worksheetTabs').onclick = e=>{const b=e.target.closest('[data-sheet]');if(b)worksheetSelectTab(b.dataset.sheet);};
worksheetForm.oninput = e=>{
  if (e.target.name==='employee_code') {
    const chosen = [...$('worksheetEmployees').options].find(o=>o.value===e.target.value);
    if (chosen) worksheetForm.elements.employee_name.value=chosen.textContent;
  }
  worksheetCollect();worksheetChanged();worksheetUpdateTemplate();
};
worksheetForm.onchange = e=>{if(['kind','include_hda','template_id'].includes(e.target.name))worksheetRender();};
$('worksheetTables').oninput = e=>{
  const el=e.target.closest('[data-key]');if(!el)return;
  worksheetState.payload.rows[Number(el.dataset.row)][el.dataset.key] = el.type==='checkbox'?el.checked:el.value;
  worksheetChanged();
};
$('worksheetTables').onclick = e=>{
  const b=e.target.closest('[data-ws-action]');if(!b)return;
  const p=worksheetCollect();
  if (b.dataset.wsAction==='detach') {
    const row=p.rows[Number(b.dataset.row)];delete row.ledger_payment_id;delete row.ledger_snapshot;
    row.salary_reference=(row.salary_reference||'')+'; manually reviewed values (record corrections here)';
  } else if (b.dataset.wsAction==='fill-entitlement' && p.rows.length) {
    for (const row of p.rows.slice(1)) for (const key of worksheetFields('entitlement')) if ((row[key]==null||row[key]==='') && p.rows[0][key]!=null) row[key]=p.rows[0][key];
  } else if (b.dataset.wsAction==='review-prior') {
    for (const row of p.rows) {
      for (const head of worksheetHeads) if (row['prior_'+head]==null||row['prior_'+head]==='') row['prior_'+head]='0';
      row.history_reviewed=true;
      if (!row.history_reference) row.history_reference='Operator checked source payment history: only the earlier payments entered here need credit; no other payments found';
    }
  } else if (b.dataset.wsAction==='review-deductions') {
    for (const row of p.rows) {
      for (const key of worksheetState.schema.templates[p.template_id].deduction_keys) if (row['ded_'+key]==null||row['ded_'+key]==='') row['ded_'+key]='0';
      row.deductions_reviewed=true;
      if (!row.deduction_reference) row.deduction_reference='Operator checked additional deductions: only the amounts entered here apply';
    }
  }
  worksheetChanged();worksheetRender();
};
$('worksheetTables').onpaste = e=>{
  const target=e.target.closest('[data-key]');if(!target||target.readOnly)return;
  const text=e.clipboardData.getData('text/plain');if(!/[\t\n]/.test(text))return;
  const tab=target.closest('[data-ws-table]').dataset.wsTable;
  const fields=worksheetFields(tab), start=fields.indexOf(target.dataset.key), firstRow=Number(target.dataset.row);
  const matrix=text.replace(/\r/g,'').replace(/\n$/,'').split('\n').map(line=>line.split('\t'));
  if (firstRow+matrix.length>worksheetState.payload.rows.length||matrix.some(r=>start+r.length>fields.length)) {e.preventDefault();notify('Pasted cells exceed this table. Create the required monthly rows and paste only its visible input columns.');return;}
  if (matrix.some((r,i)=>worksheetState.payload.rows[firstRow+i].ledger_payment_id && r.some((_,j)=>fields[start+j].startsWith('drawn_')))) {e.preventDefault();notify('Choose Use edited/manual pay before replacing linked salary figures.');return;}
  e.preventDefault();
  matrix.forEach((values,i)=>values.forEach((v,j)=>{
    const key=fields[start+j];let value=v.trim();
    if (['start','end'].includes(key)&&/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(value)) {const [d,m,y]=value.split('/');value=`${y}-${m.padStart(2,'0')}-${d.padStart(2,'0')}`;}
    if (key.endsWith('_reviewed')) value=/^(yes|true)$/i.test(value);
    worksheetState.payload.rows[firstRow+i][key]=value;
  }));
  worksheetChanged();worksheetRender();
};
async function worksheetBusy(button, work) {button.disabled=true;try{return await work();}catch(error){notify(error.message);}finally{button.disabled=false;}}
$('worksheetGenerate').onclick = e=>worksheetBusy(e.target,async()=>{
  const p=worksheetCollect();const response=await post('worksheets/months',{start:worksheetForm.elements.claim_start.value,end:worksheetForm.elements.claim_end.value});
  const old=new Map(p.rows.map(r=>[r.month,r]));
  // Retain entered figures for existing months; regenerate dates only after the explicit action.
  p.rows=response.rows.map(r=>({...old.get(r.month),...r}));
  worksheetChanged();worksheetRender();
});
$('worksheetLoadLedger').onclick = e=>worksheetBusy(e.target,async()=>{
  const p=worksheetCollect();if(!p.employee_code)throw Error('Enter an employee code first.');
  const q=new URLSearchParams({employee_code:p.employee_code,start:worksheetForm.elements.claim_start.value,end:worksheetForm.elements.claim_end.value});
  const data=await api('worksheets/ledger-load?'+q);
  const old=new Map(p.rows.map(r=>[r.month,r]));
  p.rows=data.rows.map(row=>{
    const existing={...old.get(row.month)};
    for(const key of ['ledger_payment_id','ledger_snapshot',...worksheetHeads.map(h=>'drawn_'+h),'salary_reference','bill_no','bill_date','tv_no','tv_date'])delete existing[key];
    return {...existing,...row};
  });
  worksheetChanged();worksheetRender();notify('Ledger months loaded. Blank heads or months remain unresolved; earlier payments still need a separate check.');
});
function worksheetRenderResult(result) {
  worksheetState.result=result;
  $('worksheetTables').querySelectorAll('.worksheet-invalid').forEach(e=>e.classList.remove('worksheet-invalid'));
  if(!result){$('worksheetErrors').textContent='';$('worksheetResult').textContent='Choose Check and calculate after entering the monthly figures.';return;}
  $('worksheetErrors').innerHTML=result.errors.length?`<p><b>${result.errors.length} fields or checks need attention.</b></p><ul>${result.errors.slice(0,100).map((err,i)=>`<li><button type="button" data-ws-error="${i}">${err.row==null?'Employee / setup':escapeHTML(worksheetState.payload.rows[err.row]?.month||'Row '+(err.row+1))} · ${escapeHTML(err.field.replaceAll('_',' '))}: ${escapeHTML(err.message)}</button></li>`).join('')}</ul>`:'';
  for(const err of result.errors){
    const input=err.row==null?worksheetForm.elements[err.field]:[...$('worksheetTables').querySelectorAll('[data-key]')].find(e=>Number(e.dataset.row)===err.row&&e.dataset.key===err.field);
    if(input)input.classList.add('worksheet-invalid');
  }
  if(result.status!=='ready'){$('worksheetResult').textContent='Incomplete draft. Review the highlighted entries. Formula Excel can still be saved; PDF needs all required checks.';return;}
  const bill=result.bill,meta=result.metadata, keys=worksheetState.schema.templates[worksheetState.payload.template_id].deduction_keys;
  const labels=worksheetState.schema.templates[worksheetState.payload.template_id].deduction_labels;
  const number=v=>escapeHTML(v??'');
  const body=bill.rows.map(row=>{
    const detail=meta.supplied_form_rows[row.month];
    const due=row.components.map(c=>Number(c.due)),drawn=row.components.map(c=>Number(c.drawn)+Number(c.prior_settlement)),diff=row.components.map(c=>Number(c.difference));
    const amounts=[...due,due.reduce((a,b)=>a+b,0),...drawn,drawn.reduce((a,b)=>a+b,0),...diff,diff.reduce((a,b)=>a+b,0),...keys.map(k=>detail.deductions[k]),detail.total_deductions,diff.reduce((a,b)=>a+b,0)-Number(detail.total_deductions)];
    return `<tr><td>${escapeHTML(row.start)}<br>${escapeHTML(row.end)}</td><td>${escapeHTML(detail.bill_no||'')}<br>${escapeHTML(detail.bill_date||'')}</td><td>${escapeHTML(detail.tv_no||'')}<br>${escapeHTML(detail.tv_date||'')}</td>${amounts.map(n=>`<td>${number(n)}</td>`).join('')}</tr>`;
  }).join('');
  const t=bill.totals;
  $('worksheetResult').innerHTML=`<p><b>Calculation complete — draft for office verification.</b> Gross arrear ₹${number(t.difference)} · additional deductions ₹${number(t.total_deductions)} · net ${Number(t.net_payable)<0?'recovery':'payable'} ₹${number(t.net_payable)}</p><p>Already-drawn columns include allocated earlier payments of ₹${number(t.prior_settlement)}. Full salary deductions and unchanged heads outside this form are not additional deductions.</p><div class="scroll"><table class="worksheet-preview"><thead><tr><th rowspan="2">MONTH / PERIOD</th><th rowspan="2">BILL NO / DATE</th><th rowspan="2">TV NO / DATE</th><th colspan="6">PAY TO BE DRAWN</th><th colspan="6">PAY ALREADY DRAWN</th><th colspan="6">PAY DIFFERENCE DRAWN</th>${labels.map(l=>`<th rowspan="2">${escapeHTML(l)}</th>`).join('')}<th rowspan="2">TOTAL DEDUCTION</th><th rowspan="2">NET AMOUNT</th></tr><tr>${Array.from({length:3},()=>[...worksheetHeads,'TOTAL'].map(h=>`<th>${h}</th>`).join('')).join('')}</tr></thead><tbody>${body}</tbody></table></div><details><summary>Calculation references</summary>${result.audit.map(a=>`<p>${escapeHTML(a.month)}: ${a.days}/${a.month_days} days · ${escapeHTML(a.presentation)} · ${escapeHTML(a.heads.BASIC.salary_reference)} · ${escapeHTML(a.heads.BASIC.order_reference)} · ${escapeHTML(a.heads.BASIC.prior_reference)} · ${escapeHTML(a.deduction_reference)}</p>`).join('')}</details>`;
}
$('worksheetErrors').onclick = e=>{
  const b=e.target.closest('[data-ws-error]');if(!b)return;
  const err=worksheetState.result.errors[Number(b.dataset.wsError)];
  if(err.row==null){worksheetForm.elements[err.field]?.focus();return;}
  const key=err.field==='ledger_snapshot'?'salary_reference':err.field;
  const tab=['drawn','entitlement','prior','deductions'].find(t=>worksheetFields(t).includes(key));if(tab)worksheetSelectTab(tab);
  const input=[...$('worksheetTables').querySelectorAll('[data-key]')].find(el=>Number(el.dataset.row)===err.row&&el.dataset.key===key);input?.focus();
};
async function worksheetSave() {
  const payload=worksheetCollect();
  const path='worksheets'+(worksheetState.id?'/'+worksheetState.id:'');
  const data=await post(path,{payload,revision:worksheetState.revision});
  worksheetSet(data.payload,data);await loadWorksheetWorkspace();
  $('worksheetSaved').value=String(data.id);return data;
}
$('worksheetCalculate').onclick=e=>worksheetBusy(e.target,async()=>worksheetRenderResult(await post('worksheets/calculate',worksheetCollect())));
$('worksheetSave').onclick=e=>worksheetBusy(e.target,worksheetSave);
for(const [id,ext] of [['worksheetExcel','excel'],['worksheetPdf','pdf']])$(id).onclick=e=>worksheetBusy(e.target,async()=>{
  const data=await worksheetSave();
  if(ext==='pdf'&&data.result.status!=='ready')throw Error('Complete the highlighted fields and source checks before PDF export.');
  const response=await fetch(`/suite/api/worksheets/${data.id}/${ext}`);
  if(!response.ok){const err=await response.json();throw Error(err.error||'Export failed');}
  const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=`IFMS-Due-Drawn-${data.id}.${ext==='excel'?'xlsx':'pdf'}`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$('worksheetOpen').onclick=e=>worksheetBusy(e.target,async()=>{
  const id=Number($('worksheetSaved').value);if(!id)throw Error('Choose a saved draft.');
  const data=await api('worksheets/'+id);worksheetSet(data.payload,data);
});
$('worksheetNew').onclick=()=>{
  worksheetState.id=null;worksheetState.revision=null;worksheetCollect();worksheetState.payload.rows=[];
  worksheetChanged();worksheetRender();notify('Separate draft started. Previously saved drafts remain available above.');
};
$('worksheetImportForm').onsubmit=e=>{
  e.preventDefault();worksheetBusy(e.target.querySelector('button'),async()=>{
    const data=await api('worksheets/preview-import',{method:'POST',body:new FormData(e.target)});
    worksheetSet(data.payload);worksheetRenderResult(data.result);notify('Workbook inputs loaded and recalculated. Save to keep a new draft; imported formula totals were ignored.');
  });
};
$('worksheetLocalPdf').onchange=e=>{
  const file=e.target.files[0];if(!file)return;
  if(worksheetState.localPdf)URL.revokeObjectURL(worksheetState.localPdf);
  worksheetState.localPdf=URL.createObjectURL(file);$('worksheetSourceFrame').src=worksheetState.localPdf;$('worksheetSourceFrame').hidden=false;
};
$('worksheetSourceSelect').onchange=e=>{const id=Number(e.target.value);$('worksheetSourceFrame').hidden=!id;$('worksheetSourceFrame').src=id?`/suite/api/imports/${id}/source`:'about:blank';};
$('worksheetOcrReview').onclick=async()=>{const id=Number($('worksheetSourceSelect').value);if(!id){notify('Select an imported PDF to open its editable OCR review.');return;}try{if(worksheetState.dirty)await worksheetSave();await openBillCase(id);}catch(error){notify(error.message);}};
$('worksheetSalaryImport').onsubmit=e=>{
  e.preventDefault();worksheetBusy(e.target.querySelector('button'),async()=>{
    const data=await api('worksheets/salary-preview',{method:'POST',body:new FormData(e.target)});worksheetState.salaryRecords=data.records;
    const heads=[...worksheetHeads,'OTHER_ALLOWANCES'];
    $('worksheetSalaryPreview').innerHTML=`<p>${data.records.length} records loaded. ${data.errors.length} reconciliation issues.</p>${data.errors.map(err=>`<p>${Number(err.row)+1}: ${escapeHTML(err.message)}</p>`).join('')}<div class="scroll"><table><thead><tr><th>Employee</th><th>Month</th><th>Bill</th>${heads.map(h=>`<th>${h}</th>`).join('')}<th>Gross</th><th>Deductions</th><th>Net</th><th>Reference</th></tr></thead><tbody>${data.records.map(r=>`<tr><td>${escapeHTML(r.employee_code)}<br>${escapeHTML(r.employee_name)}</td><td>${escapeHTML(r.pay_month)}</td><td>${escapeHTML(r.bill_no)}</td>${heads.map(h=>`<td>${escapeHTML(r.allowances[h])}</td>`).join('')}<td>${escapeHTML(r.printed_gross)}</td><td>${escapeHTML(r.printed_deductions)}</td><td>${escapeHTML(r.printed_net)}</td><td>${escapeHTML(r.reference)}</td></tr>`).join('')}</tbody></table></div><label><input id="worksheetSalaryReviewed" type="checkbox">I checked these full-month salary figures, absent heads, deductions and printed totals against the original records</label><button class="action" type="button" id="worksheetSalarySave" ${data.errors.length?'disabled':''}>Save verified salaries to ledger</button>`;
    $('worksheetSalarySave').onclick=event=>worksheetBusy(event.target,async()=>{
      if(!$('worksheetSalaryReviewed').checked)throw Error('Check the original records and confirm the salary review first.');
      const saved=await post('worksheets/salary-save',{records:worksheetState.salaryRecords,reviewed:true});
      $('worksheetSalaryPreview').textContent=`${saved.saved} verified salary records saved. Load the employee ledger above to reuse them.`;
      await loadWorksheetWorkspace();
    });
  });
};
