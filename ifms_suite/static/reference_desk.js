"use strict";

// Local reference data never writes bill amounts or deductions implicitly.
const referenceState={categories:[],documents:[],slabs:[],rates:[],documentEdit:null,slabEdit:null,windows:[],pickerVersion:0};
const referenceStorageKey='ifms-reference-panels-v1';
const referenceSafe = v=>escapeHTML(v??'');
const referenceReason = action=>`${action} by operator in the reference library`;
const referenceRun = async (button,work)=>{const form=button?.closest('form');if(button)button.disabled=true;if(form)form.inert=true;try{return await work();}catch(error){notify(error.message);}finally{if(button)button.disabled=false;if(form)form.inert=false;}};
const referenceButton = (action,id,label,kind='')=>`<button type="button" class="action" data-reference-action="${action}" data-id="${Number(id)}" data-kind="${kind}">${label}</button>`;

function renderManagedRates(rates) {
  referenceState.rates=rates;
  $('ratesTable').innerHTML=`<div class="scroll"><table><thead><tr>${['Allowance / basis','Effective dates','Rate','Order / category','Actions'].map(s=>`<th>${s}</th>`).join('')}</tr></thead><tbody>${rates.map(r=>`<tr draggable="true" data-pin-kind="rate" data-pin-id="${Number(r.id)}"><td>${referenceSafe(r.allowance)}<br>${referenceSafe(r.basis||'basic')}</td><td>${referenceSafe(r.effective_from)}${r.effective_to?'<br>through '+referenceSafe(r.effective_to):''}</td><td>${referenceSafe(r.rate)}</td><td>${referenceSafe(r.category||'General')}<br>${referenceSafe(r.order_date||'')}<br>${referenceSafe(r.reference)}<br>${referenceSafe(r.verification||'manual')}</td><td>${referenceButton('edit-rate',r.id,'Edit')}${referenceButton('pin',r.id,'Pin','rate')}${referenceButton('archive-rate',r.id,'Archive')}${referenceButton('audit-rate',r.id,'History')}</td></tr>`).join('')}</tbody></table></div>`;
}
$('rateForm').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{
  const data=Object.fromEntries(new FormData(e.target));const id=Number(data.rate_id);delete data.rate_id;data.revision=Number(data.revision);
  await post('rates'+(id?'/'+id:''),data);$('rateForm').reset();$('rateEditorTitle').textContent='Add a dated allowance rate';await refresh();notify('Dated rate saved. Bill entries will be checked against its effective date when calculated or exported.');
});};
$('rateEditorNew').onclick=()=>{$('rateForm').reset();$('rateEditorTitle').textContent='Add a dated allowance rate';};
$('loadArchivedRates').onclick=e=>referenceRun(e.target,async()=>{
  const rows=await api('rates/archived');
  $('archivedRatesTable').innerHTML=rows.map(r=>`<div class="reference-card">${referenceSafe(r.allowance)} · ${referenceSafe(r.effective_from)} · ${referenceSafe(r.rate)} · ${referenceSafe(r.archive_reason)}${referenceButton('restore-rate',r.id,'Restore')}${referenceButton('audit-rate',r.id,'History')}</div>`).join('')||'No archived rates.';
});

async function loadDocumentCategories() {
  referenceState.categories=await api('library/categories');
  for(const select of document.querySelectorAll('select.document-category')){
    const previous=select.value,empty=select.closest('#documentSearch')?'All categories':'Uncategorized';
    select.innerHTML=`<option value="">${empty}</option>`+referenceState.categories.map(c=>`<option value="${Number(c.id)}">${referenceSafe(c.name)}</option>`).join('');
    select.value=previous;
  }
}
async function loadDocumentLibrary(){
  await loadDocumentCategories();
  const data=Object.fromEntries(new FormData($('documentSearch')));data.include_archived=$('documentSearch').elements.include_archived.checked?'true':'false';
  referenceState.documents=await api('library/documents?'+new URLSearchParams(data));
  $('documentLibraryResults').innerHTML=referenceState.documents.map(referenceDocumentCard).join('')||'<p>No documents match this search.</p>';
}
function referenceDocumentCard(d){
  const category=referenceState.categories.find(c=>c.id===d.category_id)?.name||'Uncategorized';
  return `<article class="reference-card" draggable="true" data-pin-kind="document" data-pin-id="${Number(d.id)}"><h3>${referenceSafe(d.title)}</h3><p>${referenceSafe(category)} · ${referenceSafe(d.file_kind.toUpperCase())}${d.archived?' · ARCHIVED':''}<br>${referenceSafe(d.order_number||'')} · ${referenceSafe(d.order_date||'')}<br>${referenceSafe(d.tags||'')}</p><p>${referenceSafe(d.text_search_note||'')}</p>${referenceButton('pin',d.id,'Pin beside work','document')}${referenceButton('edit-document',d.id,'Edit')}${referenceButton(d.archived?'restore-document':'archive-document',d.id,d.archived?'Restore':'Archive')}</article>`;
}
$('documentSearch').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),loadDocumentLibrary);};
$('documentCategoryForm').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{await post('library/categories',Object.fromEntries(new FormData(e.target)));e.target.reset();await loadDocumentCategories();notify('Category created.');});};
$('documentCategoryRename').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{
  const id=Number(e.target.elements.id.value),old=referenceState.categories.find(c=>c.id===id);if(!old)throw Error('Select a category.');
  await post('library/categories/'+id,{name:e.target.elements.name.value,revision:old.revision});await loadDocumentLibrary();notify('Category renamed.');
});};
function resetDocumentEditor(){referenceState.documentEdit=null;$('documentEditor').reset();$('documentEditor').elements.file.disabled=false;$('documentEditorTitle').textContent='Add an order or typed rule';}
$('documentEditorNew').onclick=resetDocumentEditor;
$('documentEditor').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{
  const form=e.target,editing=referenceState.documentEdit;
  const data=new FormData(form);if(!form.elements.file.files.length)data.delete('file');
  let saved;
  if(editing){const p=Object.fromEntries(data);p.category_id=p.category_id?Number(p.category_id):null;p.revision=editing.revision;saved=await post('library/documents/'+editing.id,p);}
  else if(form.elements.file.files.length)saved=await api('library/documents',{method:'POST',body:data});
  else {const p=Object.fromEntries(data);p.category_id=p.category_id?Number(p.category_id):null;saved=await post('library/documents',p);}
  resetDocumentEditor();await loadDocumentLibrary();notify(`Document #${saved.id} saved. Search it or pin it beside your bill.`);
});};

function addSlabRow(row={lower:'',upper:null,kind:'fixed',value:''}){
  const tr=document.createElement('tr');tr.innerHTML=`<td><input data-slab="lower" inputmode="decimal" value="${referenceSafe(row.lower)}" aria-label="Salary lower inclusive" required></td><td><input data-slab="upper" inputmode="decimal" value="${referenceSafe(row.upper)}" aria-label="Salary upper exclusive"></td><td><select data-slab="kind" aria-label="Subscription method"><option value="fixed" ${row.kind==='fixed'?'selected':''}>Fixed amount</option><option value="percent" ${row.kind==='percent'?'selected':''}>Percentage of basis</option></select></td><td><input data-slab="value" inputmode="decimal" value="${referenceSafe(row.value)}" aria-label="Subscription amount or percentage" required></td><td><button type="button" data-remove-slab>Remove row</button></td>`;$('slabEditorRows').appendChild(tr);
}
$('slabEditorRows').onclick=e=>{if(e.target.closest('[data-remove-slab]'))e.target.closest('tr').remove();};
$('slabAddRow').onclick=()=>addSlabRow();
function resetSlabEditor(){referenceState.slabEdit=null;$('slabEditor').reset();$('slabEditorRows').innerHTML='';addSlabRow();$('slabEditorTitle').textContent='Add a salary slab schedule';}
$('slabEditorNew').onclick=resetSlabEditor;resetSlabEditor();
function referenceSlabTable(s){return `<p>${referenceSafe(s.scheme)} · ${referenceSafe(s.basis)} · category ${referenceSafe(s.category||'General')}<br>${referenceSafe(s.effective_from)} through ${referenceSafe(s.effective_to||'open-ended')}<br>${referenceSafe(s.reference)}</p><table><thead><tr><th>From included</th><th>Below excluded</th><th>Method</th><th>Value</th></tr></thead><tbody>${s.slabs.map(r=>`<tr><td>${referenceSafe(r.lower)}</td><td>${referenceSafe(r.upper??'No ceiling')}</td><td>${referenceSafe(r.kind)}</td><td>${referenceSafe(r.value)}</td></tr>`).join('')}</tbody></table><p class="muted">Full subscription reference only. Check actual deductions before calculating an additional arrear adjustment.</p>`;}
async function loadSlabLibrary(){
  const form=$('slabSearch');const data=Object.fromEntries(new FormData(form));data.include_archived=form.elements.include_archived.checked?'true':'false';
  const result=await api('slabs?'+new URLSearchParams(data));referenceState.slabs=result.slabs;
  $('slabLibraryResults').innerHTML=referenceState.slabs.map(s=>`<article class="reference-card" draggable="true" data-pin-kind="slab" data-pin-id="${Number(s.id)}"><h3>${referenceSafe(s.name)}${s.archived?' · ARCHIVED':''}</h3>${referenceSlabTable(s)}${referenceButton('pin',s.id,'Pin beside work','slab')}${referenceButton('edit-slab',s.id,'Edit')}${referenceButton(s.archived?'restore-slab':'archive-slab',s.id,s.archived?'Restore':'Archive')}</article>`).join('')||'<p>No schedules yet. Add only schedules supported by your applicable orders.</p>';
}
$('slabSearch').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),loadSlabLibrary);};
$('slabEditor').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{
  const p=Object.fromEntries(new FormData(e.target));p.effective_to=p.effective_to||null;p.slabs=[...$('slabEditorRows').querySelectorAll('tr')].map(tr=>{const r=Object.fromEntries([...tr.querySelectorAll('[data-slab]')].map(i=>[i.dataset.slab,i.value.trim()]));r.upper=r.upper===''?null:r.upper;return r;});
  const edit=referenceState.slabEdit;if(edit)p.revision=edit.revision;
  await post('slabs'+(edit?'/'+edit.id:''),p);resetSlabEditor();await loadSlabLibrary();notify('Salary slab schedule saved.');
});};
$('slabSuggestion').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{
  const q=new URLSearchParams(Object.fromEntries(new FormData(e.target)));const result=await api('slabs/suggest?'+q);
  $('slabSuggestionResult').innerHTML=result.status==='ok'?`<p><b>Suggested full ${referenceSafe(result.scheme)} subscription: ₹${referenceSafe(result.amount)}</b></p><p>${referenceSafe(result.reference)}</p><p>${referenceSafe(result.message)}</p>${referenceButton('pin',result.schedule.id,'Pin this schedule','slab')}`:`<p>${referenceSafe(result.status)}: ${referenceSafe(result.message)}</p>`;
});};

// One delegated handler covers cards refreshed by search, library updates or archived lists.
document.addEventListener('click',e=>{
  const button=e.target.closest('[data-reference-action]');if(!button)return;
  referenceRun(button,async()=>{
    const id=Number(button.dataset.id),action=button.dataset.referenceAction;
    if(action==='pin'){await pinReference(button.dataset.kind,id);$('referencePicker').hidden=true;return;}
    if(action==='edit-rate'){
      const r=referenceState.rates.find(r=>r.id===id);if(!r)throw Error('Reload the rates library.');
      const form=$('rateForm');form.reset();for(const [k,v] of Object.entries(r))if(form.elements[k])form.elements[k].value=v??'';
      form.elements.rate_id.value=id;form.elements.revision.value=r.revision||1;form.elements.override_reason.value='';$('rateEditorTitle').textContent=`Edit rate #${id} · amendment reason required`;form.scrollIntoView({behavior:'smooth'});return;
    }
    if(action==='archive-rate'||action==='restore-rate'){
      const archived=action==='archive-rate',items=archived?referenceState.rates:await api('rates/archived'),r=items.find(r=>r.id===id);
      if(!r)throw Error('Reload the rate list.');await post(`rates/${id}/archive`,{revision:r.revision||1,archived,reason:referenceReason(archived?'Archived':'Restored')});await refresh();if(!archived)$('loadArchivedRates').click();notify('Rate '+(archived?'archived':'restored')+'. Saved bills will be checked against active rates.');return;
    }
    if(action==='audit-rate'){
      const audit=await api(`rates/${id}/audit`);const panel=document.createElement('div');panel.className='reference-card';panel.innerHTML='<h3>Rate history</h3>'+audit.map(a=>`<p>${referenceSafe(a.created_at)} · ${referenceSafe(a.reason)}<br>Previous: ${referenceSafe(a.previous?.rate??'New')} → ${referenceSafe(a.current?.rate)}${a.current.archived?' · archived':''}</p>`).join('');button.parentElement.appendChild(panel);return;
    }
    if(action==='edit-document'){
      const d=await api('library/documents/'+id);referenceState.documentEdit=d;const form=$('documentEditor');form.reset();for(const [k,v] of Object.entries(d))if(form.elements[k]&&k!=='file')form.elements[k].value=v??'';
      form.elements.file.disabled=true;$('documentEditorTitle').textContent=`Edit document #${id} · original file preserved`;form.scrollIntoView({behavior:'smooth'});return;
    }
    if(action==='archive-document'||action==='restore-document'){
      const d=await api('library/documents/'+id),archived=action==='archive-document';await post(`library/documents/${id}/archive`,{revision:d.revision,archived,reason:referenceReason(archived?'Archived':'Restored')});await loadDocumentLibrary();return;
    }
    if(action==='edit-slab'){
      const s=await api('slabs/'+id);referenceState.slabEdit=s;const form=$('slabEditor');form.reset();for(const [k,v] of Object.entries(s))if(form.elements[k])form.elements[k].value=v??'';
      $('slabEditorRows').innerHTML='';s.slabs.forEach(addSlabRow);$('slabEditorTitle').textContent=`Edit schedule #${id}`;form.scrollIntoView({behavior:'smooth'});return;
    }
    if(action==='archive-slab'||action==='restore-slab'){
      const s=await api('slabs/'+id),archived=action==='archive-slab';await post(`slabs/${id}/archive`,{revision:s.revision,archived,reason:referenceReason(archived?'Archived':'Restored')});await loadSlabLibrary();
    }
  });
});

function persistReferencePanels(){
  try{localStorage.setItem(referenceStorageKey,JSON.stringify(referenceState.windows.map(w=>({kind:w.kind,id:w.id,...referenceGeometry(w.element)}))));}catch(_){/* Disk/privacy mode does not affect live panels. */}
}
function referenceGeometry(el){return {x:el.offsetLeft,y:el.offsetTop,width:el.offsetWidth,height:el.offsetHeight};}
function clampReference(el,geometry={}){
  const vw=window.innerWidth,vh=window.innerHeight,w=Math.min(Math.max(Number(geometry.width)||430,Math.min(260,vw-16)),vw-16),h=Math.min(Math.max(Number(geometry.height)||Math.min(520,vh*.6),150),vh-16);
  el.style.width=w+'px';el.style.height=h+'px';el.style.left=Math.min(Math.max(Number(geometry.x)||8,8),Math.max(8,vw-w-8))+'px';el.style.top=Math.min(Math.max(Number(geometry.y)||80,8),Math.max(8,vh-h-8))+'px';
}
async function referenceContent(kind,id){
  if(kind==='document'){
    const d=await api('library/documents/'+id);
    return {title:d.title,html:`${d.archived?'<p><b>ARCHIVED REFERENCE</b></p>':''}<p class="reference-metadata">${referenceSafe(d.order_number)} · ${referenceSafe(d.order_date)} · effective ${referenceSafe(d.effective_from)}${d.effective_to?' to '+referenceSafe(d.effective_to):''}<br>${referenceSafe(d.tags)}<br>${referenceSafe(d.notes)}</p>${d.file_kind!=='text'?`<a href="/suite/api/library/documents/${id}/content" target="_blank" rel="noopener">Open / download original ${referenceSafe(d.file_name)}</a>`:''}${d.file_kind==='pdf'?`<iframe src="/suite/api/library/documents/${id}/content" title="Original ${referenceSafe(d.title)}"></iframe>`:`<pre>${referenceSafe([d.body,d.extracted_text].filter(Boolean).join('\n\n'))}</pre>`}${d.file_kind==='pdf'&&d.body?`<pre>${referenceSafe(d.body)}</pre>`:''}`};
  }
  if(kind==='slab'){const s=await api('slabs/'+id);return {title:s.name,html:(s.archived?'<p><b>ARCHIVED REFERENCE</b></p>':'')+referenceSlabTable(s)};}
  if(kind==='rate'){
    const rates=[...await api('rates'),...await api('rates/archived')];const r=rates.find(r=>r.id===id);if(!r)throw Error('Rate not found');
    return {title:r.allowance+' · '+r.effective_from,html:`${r.archived?'<p><b>ARCHIVED REFERENCE</b></p>':''}<h2>${referenceSafe(r.rate)} ${['basic','basic_da'].includes(r.basis||'basic')?'%':''}</h2><p>Basis: ${referenceSafe(r.basis||'basic')} · category ${referenceSafe(r.category||'General')}<br>Effective ${referenceSafe(r.effective_from)} through ${referenceSafe(r.effective_to||'open-ended')}<br>Order ${referenceSafe(r.order_date)}<br>${referenceSafe(r.reference)}<br>${referenceSafe(r.verification)}</p><p>${referenceSafe(r.notes)}</p>`};
  }
  throw Error('Unsupported reference type');
}
async function pinReference(kind,id,geometry=null){
  if(!['document','slab','rate'].includes(kind)||!Number.isSafeInteger(id)||id<1)throw Error('Invalid reference');
  const existing=referenceState.windows.find(w=>w.kind===kind&&w.id===id);if(existing){existing.element.querySelector('button').focus();return;}
  if(referenceState.windows.length>=6)throw Error('Up to six references can remain pinned. Close one before adding another.');
  const data=await referenceContent(kind,id),el=document.createElement('div');el.className='reference-window';el.dataset.referenceKind=kind;el.dataset.referenceId=id;el.setAttribute('aria-label',data.title);
  el.innerHTML=`<div class="reference-window-header"><strong>${referenceSafe(data.title)}</strong><button type="button" data-refresh-reference aria-label="Refresh reference">Refresh</button><button type="button" data-close-reference aria-label="Close pinned reference">Close</button></div><div class="reference-window-body">${data.html}</div>`;
  const record={kind,id,element:el};referenceState.windows.push(record);$('referenceWindows').appendChild(el);
  clampReference(el,geometry||{x:Math.max(8,innerWidth-450-referenceState.windows.length*14),y:80+referenceState.windows.length*24});
  el.querySelector('[data-close-reference]').onclick=()=>{referenceState.windows=referenceState.windows.filter(w=>w!==record);record.observer.disconnect();el.remove();persistReferencePanels();};
  el.querySelector('[data-refresh-reference]').onclick=event=>referenceRun(event.target,async()=>{const current=await referenceContent(kind,id);el.querySelector('strong').textContent=current.title;el.querySelector('.reference-window-body').innerHTML=current.html;});
  const handle=el.querySelector('.reference-window-header');let drag=null;
  // Keep pointer coordinates separate from panel coordinates so dragging has no jump.
  handle.onpointerdown=e=>{if(e.target.closest('button'))return;drag={pointer:e.pointerId,pointerX:e.clientX,pointerY:e.clientY,...referenceGeometry(el)};handle.setPointerCapture(e.pointerId);el.classList.add('dragging');};
  handle.onpointermove=e=>{if(drag)clampReference(el,{...drag,x:drag.x+e.clientX-drag.pointerX,y:drag.y+e.clientY-drag.pointerY});};
  const end=()=>{drag=null;el.classList.remove('dragging');persistReferencePanels();};handle.onpointerup=end;handle.onpointercancel=end;
  let saveTimer;record.observer=new ResizeObserver(()=>{clearTimeout(saveTimer);saveTimer=setTimeout(()=>{const g=referenceGeometry(el);if(g.x+g.width>innerWidth||g.y+g.height>innerHeight)clampReference(el,g);persistReferencePanels();},150);});record.observer.observe(el);
  persistReferencePanels();
}
window.addEventListener('resize',()=>{for(const w of referenceState.windows)clampReference(w.element,referenceGeometry(w.element));persistReferencePanels();});
document.addEventListener('dragstart',e=>{const card=e.target.closest('[data-pin-kind]');if(card){e.dataTransfer.setData('application/x-ifms-reference',JSON.stringify({kind:card.dataset.pinKind,id:Number(card.dataset.pinId)}));e.dataTransfer.effectAllowed='copy';}});
document.addEventListener('dragover',e=>{if([...e.dataTransfer.types].includes('application/x-ifms-reference')){e.preventDefault();document.querySelector('main').classList.add('reference-drop-target');}});
document.addEventListener('drop',e=>{document.querySelector('main').classList.remove('reference-drop-target');const text=e.dataTransfer.getData('application/x-ifms-reference');if(!text)return;e.preventDefault();try{const item=JSON.parse(text);pinReference(item.kind,item.id,{x:e.clientX,y:e.clientY}).catch(x=>notify(x.message));}catch(_){notify('Invalid reference card.');}});
document.addEventListener('dragend',()=>document.querySelector('main').classList.remove('reference-drop-target'));
$('referenceDeskToggle').onclick=()=>{$('referencePicker').hidden=!$('referencePicker').hidden;if(!$('referencePicker').hidden)$('referenceQuickSearch').elements.q.focus();};
$('referencePickerClose').onclick=()=>{$('referencePicker').hidden=true;};
$('referenceQuickSearch').onsubmit=e=>{e.preventDefault();referenceRun(e.target.querySelector('button'),async()=>{
  const q=e.target.elements.q.value.trim(),version=++referenceState.pickerVersion;
  const [docs,slabs,rates]=await Promise.all([api('library/documents?q='+encodeURIComponent(q)),api('slabs'),api('rates')]);if(version!==referenceState.pickerVersion)return;
  const includes=s=>s.toLowerCase().includes(q.toLowerCase());const matches=[...docs.map(d=>({kind:'document',id:d.id,title:d.title})),...slabs.slabs.filter(s=>!s.archived&&includes([s.name,s.scheme,s.reference].join(' '))).map(s=>({kind:'slab',id:s.id,title:s.name})),...rates.filter(r=>includes([r.allowance,r.category,r.reference].join(' '))).map(r=>({kind:'rate',id:r.id,title:r.allowance+' '+r.rate+' · '+r.effective_from}))];
  $('referenceQuickResults').innerHTML=matches.map(m=>`<p>${referenceSafe(m.title)} ${referenceButton('pin',m.id,'Pin',m.kind)}</p>`).join('')||'No matching references.';
});};
(async()=>{try{const saved=JSON.parse(localStorage.getItem(referenceStorageKey)||'[]');if(Array.isArray(saved))for(const item of saved.slice(0,6))try{await pinReference(item.kind,Number(item.id),item);}catch(_){/* A removed/stale library reference is not a financial input. */}}catch(_){}})();
