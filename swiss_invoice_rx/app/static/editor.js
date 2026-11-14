const SWISS_BASE = document.querySelector('meta[name="swiss-invoice-base"]')?.getAttribute('content') || '';
'use strict';
(() => {
  const form = document.getElementById('invoice-form');
  if (!form) return;
  const tbody = document.getElementById('invoice-rows');
  const items = JSON.parse(form.dataset.items || '[]');
  const customers = JSON.parse(form.dataset.customers || '[]');
  let editing = form.dataset.editing === '1';
  const kind = form.dataset.kind;
  const taxEnabled = form.dataset.taxRegistered === '1';
  const numberField = document.getElementById('invoice-number');
  const suggested = numberField.placeholder || '';
  const due = document.getElementById('due-date');
  const customer = document.getElementById('customer-select');
  const newCustomer = document.getElementById('new-customer');
  const newCustomerName = document.getElementById('new-customer-name');
  const customerFilter = document.getElementById('customer-filter');
  const customerSummary = document.getElementById('customer-summary');
  function renderCustomerSummary() {
    const selected = customers.find(c => String(c.id) === customer.value);
    if (!selected) {
      customerSummary.textContent = 'Bitte einen Kunden auswaehlen oder direkt neu erfassen.';
      return;
    }
    customerSummary.textContent = [selected.name, [selected.street,selected.building].filter(Boolean).join(' '),
      [selected.zip,selected.city].filter(Boolean).join(' '),selected.country||'CH'].filter(Boolean).join(' | ');
  }
  customerFilter?.addEventListener('input', () => {
    const query = customerFilter.value.toLocaleLowerCase('de-CH').trim();
    for (const opt of customer.options) {
      if (!opt.value) continue;
      const c=customers.find(entry => String(entry.id)===opt.value);
      opt.hidden = Boolean(query) && !(String(opt.textContent).toLocaleLowerCase('de-CH').includes(query) ||
        String(c?.number || '').toLocaleLowerCase('de-CH').includes(query)) && opt.value !== customer.value;
    }
    const matches=[...customer.options].filter(x => x.value && !x.hidden).length;
    if (query && matches===0) customerSummary.textContent='Kein Treffer. Neue Kundendaten unten erfassen.';
    else renderCustomerSummary();
  });
  const toggleCustomer = document.getElementById('toggle-customer');
  const status = document.getElementById('editor-feedback');
  const saveStatus = document.getElementById('editor-autosave');
  let autosaveTimer=null, autosavePromise=null, autosaveVersion=0;
  let changed = false;
  let sending = false;
  let lastRemoved = null;
  const undoButton = document.getElementById('undo-row');
  const search = document.getElementById('item-search');
  const searchResults = document.getElementById('item-search-results');
  const numberStatus = document.getElementById('number-availability');
  const previewButton = document.getElementById('preview-invoice-pdf');
  let numberRequestId = 0;
  let numberTimer;
  const money = value => {
    const v = Math.round((value + Number.EPSILON) * 100) / 100;
    return v.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  };
  const byName = (tr, key) => tr.querySelector(`[name="${key}[]"]`);
  function chooseUnit(select, unit) {
    if (![...select.options].some(option => option.value === String(unit))) {
      const option = document.createElement('option');option.value=String(unit);
      option.textContent=String(unit);select.add(option);
    }
    select.value=String(unit);
  }
  const getDate = dateText => {
    if (!/^\d{4}-\d\d-\d\d$/.test(dateText || '')) return null;
    const d = new Date(dateText + 'T12:00:00');
    return Number.isNaN(d.getTime()) ? null : d;
  };
  function feedback(message, isError = false) {
    status.textContent = message;
    status.className = isError ? 'small-help editor-error' : 'small-help';
  }
  function markChanged() {
    changed = true;autosaveVersion++;
    feedback('Änderungen werden automatisch gesichert.');
    persistLocalDraft();
    scheduleAutosave();
  }
  function setText(selector, text) { const target = document.querySelector(selector); if (target) target.textContent = text; }
  function showStock(tr) {
    const item = items.find(a => String(a.id) === byName(tr, 'item_id').value);
    const hint = tr.querySelector('.stock-hint');
    hint.textContent = item && item.track_stock ? `Lager: ${item.stock} ${item.kind === 'service' ? '' : 'Stk.'}` : '';
  }
  function currentCustomer() {
    if (!newCustomer.hidden && newCustomerName.value.trim()) return newCustomerName.value.trim();
    return customers.find(c => String(c.id) === customer.value)?.name || 'Bitte Kunde waehlen';
  }
  function checkQrReadiness() {
    const box = document.getElementById('qr-ready');
    const label = box.querySelector('span:nth-child(2)');
    box.classList.remove('is-good','is-warning');
    if (kind !== 'invoice') {
      label.textContent = 'Bei Offerten und Gutschriften wird kein QR-Zahlteil angehaengt.';
      return;
    }
    if (form.dataset.hasIban !== '1') {
      label.textContent = 'Noch keine IBAN hinterlegt. Die Rechnung wird ohne QR-Zahlteil erstellt.';
      box.classList.add('is-warning');return;
    }
    if (form.dataset.companyAddress !== '1') {
      label.textContent = 'Firmenadresse ist fuer den Swiss QR-Code noch unvollstaendig.';
      box.classList.add('is-warning');return;
    }
    const c = customers.find(x => String(x.id) === customer.value);
    const customerReady = !newCustomer.hidden ?
      !!(newCustomerName.value && newCustomer.querySelector('[name="new_customer_zip"]').value &&
         newCustomer.querySelector('[name="new_customer_city"]').value &&
         newCustomer.querySelector('[name="new_customer_country"]').value) :
      !!(c && c.zip && c.city && c.country);
    if (!customerReady) {
      label.textContent = 'Fuer den QR-Zahlteil bitte einen Kunden mit PLZ, Ort und Land waehlen.';
      box.classList.add('is-warning');return;
    }
    label.textContent = 'IBAN und Adressen vorhanden. Vollstaendige QR-Pruefung beim PDF-Export.';
    box.classList.add('is-good');
  }
  function recalc() {
    let subtotal = 0, gross = 0, afterPosition = 0;
    const buckets = new Map();
    const discount = Math.max(0, Math.min(100, parseFloat(document.getElementById('global-discount').value) || 0));
    const previewRows = document.getElementById('live-preview-rows');
    previewRows.replaceChildren();
    let rowCount = 0;
    tbody.querySelectorAll('.editor-line').forEach((tr,index) => {
      const qty = parseFloat(byName(tr,'qty').value) || 0;
      const price = parseFloat(byName(tr,'price').value) || 0;
      const lineDiscount = parseFloat(byName(tr,'discount').value) || 0;
      const rate = taxEnabled ? (parseFloat(byName(tr,'tax_rate').value) || 0) : 0;
      const mode = taxEnabled ? byName(tr,'tax_mode').value : 'taxable';
      const lineGross = Math.round((qty * price + Number.EPSILON) * 100) / 100;
      const afterLine = Math.round((qty * price * (1-lineDiscount/100) + Number.EPSILON) * 100) / 100;
      const net = Math.round((qty * price * (1-lineDiscount/100) * (1-discount/100) + Number.EPSILON) * 100) / 100;
      gross += lineGross;afterPosition += afterLine;subtotal += net;
      if (taxEnabled) {
        const key = mode === 'taxable' ? `tax:${rate}` : `other:${mode}`;
        buckets.set(key, (buckets.get(key)||0) + net);
      }
      tr.querySelector('.line-total').textContent = money(afterLine);
      tr.querySelector('.line-index').textContent = `Position ${index+1}`;
      tr.querySelector('.line-kind').textContent = byName(tr,'item_id').value ? 'Aus Artikelkatalog' : 'Freie Position';
      const taxText = mode === 'exempt' ? 'Steuerbefreit' : mode === 'excluded' ? 'Von MWST ausgenommen' : `${rate}% MWST`;
      tr.querySelector('.line-tax-summary').textContent = `${lineDiscount}% Rabatt${taxEnabled ? ' · '+taxText : ''}`;
      const desc = byName(tr,'description').value.trim();
      if (desc) {
        rowCount++;
        if (rowCount <= 8) {
          const row = document.createElement('tr');
          const cell1 = document.createElement('td');cell1.textContent = desc;
          const cell2 = document.createElement('td');cell2.textContent = byName(tr,'qty').value+' '+byName(tr,'unit').value;
          const cell3 = document.createElement('td');cell3.className = 'num';cell3.textContent = money(afterLine);
          row.append(cell1,cell2,cell3);previewRows.appendChild(row);
        }
      }
      showStock(tr);
    });
    if (rowCount > 8) {
      const tr = document.createElement('tr');const td = document.createElement('td');td.colSpan=3;
      td.textContent = `... und ${rowCount-8} weitere Position(en)`;tr.appendChild(td);previewRows.appendChild(tr);
    }
    let tax = 0;
    const breakdown = document.getElementById('tax-buckets-live');
    breakdown.replaceChildren();
    buckets.forEach((net,key) => {
      const value=key.startsWith('tax:') ? Math.round((net*parseFloat(key.slice(4))/100 + Number.EPSILON)*100)/100 : 0;
      tax += value;
      const row=document.createElement('div');row.className='tax-preview-row';
      const label=key==='other:exempt' ? 'Befreit' : key==='other:excluded' ? 'Ausgenommen' : 'MWST '+key.slice(4)+'%';
      row.textContent=label+' - Basis '+money(net)+' / Steuer '+money(value);breakdown.appendChild(row);
    });
    const total = subtotal + tax;
    const currency = document.getElementById('invoice-currency').value;
    const grossRounded = Math.round(gross*100)/100, afterRounded=Math.round(afterPosition*100)/100;
    const subRounded=Math.round(subtotal*100)/100;
    const lineReduction=Math.round((grossRounded-afterRounded)*100)/100;
    const globalReduction=Math.round((afterRounded-subRounded)*100)/100;
    for (const [id,amount] of [['gross-live-row',lineReduction||globalReduction],['line-discount-live-row',lineReduction],['global-discount-live-row',globalReduction]]) {
      const row=document.getElementById(id);if(row)row.hidden=!amount;
    }
    setText('#gross-live',money(grossRounded));
    setText('#line-discount-live',(lineReduction>0?'- ':'+ ')+money(Math.abs(lineReduction)));
    setText('#global-discount-live',(globalReduction>0?'- ':'+ ')+money(Math.abs(globalReduction)));
    setText('#subtotal-live',money(subtotal));setText('#tax-live',money(tax));
    setText('#total-live',money(total));setText('#live-preview-total',money(total));
    document.querySelectorAll('.editor-currency').forEach(el => el.textContent = currency);
    setText('#live-invoice-number',numberField.value.trim() || suggested || 'Automatisch');
    setText('#live-invoice-date',document.getElementById('invoice-date').value);
    setText('#live-customer',currentCustomer());setText('#live-due','Faellig: '+due.value);
    setText('#live-notes',document.getElementById('invoice-notes').value);
    setText('#live-subject',document.getElementById('invoice-subject').value);
    const count = tbody.querySelectorAll('.editor-line').length;
    setText('#row-count',`${rowCount} ausgefuellt · ${count} ${count === 1 ? 'Zeile' : 'Zeilen'}`);
    checkQrReadiness();
  }
  function addRow(type='normal', focus=true, silent=false) {
    const previous = tbody.querySelector('.editor-line:last-child');
    if (!previous) return;
    const tr = previous.cloneNode(true);
    tr.querySelectorAll('input').forEach(el => {
      el.value = el.name === 'qty[]' ? (kind === 'credit' ? '-1' : '1') :
                 el.name === 'price[]' || el.name === 'discount[]' ? '0' : '';
    });
    tr.querySelectorAll('select').forEach(el => {
      if (el.name === 'unit[]') chooseUnit(el,type === 'service' ? 'Std.' : type === 'text' ? '-' : 'Stk.');
      if (el.name === 'item_id[]') el.value = '';
      if (el.name === 'tax_rate[]') el.value = taxEnabled ? (form.dataset.defaultTax || '0') : '0';
      if (el.name === 'tax_mode[]') el.value = 'taxable';
    });
    if (!taxEnabled) {byName(tr,'tax_rate').value='0';byName(tr,'tax_mode').value='taxable';}
    if (type === 'text') {chooseUnit(byName(tr,'unit'),'-');byName(tr,'price').value = '0';}
    tr.querySelector('.stock-hint').textContent = '';
    tr.querySelector('.hi-line-advanced').open = false;
    tbody.appendChild(tr);
    if (!silent) {markChanged();recalc();}
    if (focus) byName(tr,'description').focus();
    return tr;
  }
  function applyItem(tr,item) {
    byName(tr,'item_id').value=String(item.id);
    byName(tr,'description').value=item.name+(item.description?' - '+item.description:'');
    byName(tr,'price').value=item.price;
    const select=byName(tr,'tax_rate');
    if (taxEnabled && select.tagName==='SELECT' && ![...select.options].some(opt => opt.value===String(item.tax_rate))) {
      const opt=document.createElement('option');opt.value=String(item.tax_rate);opt.textContent=String(item.tax_rate);select.add(opt);
    }
    select.value=taxEnabled ? String(item.tax_rate) : '0';
    byName(tr,'tax_mode').value=taxEnabled ? (item.tax_mode||'taxable') : 'taxable';
    byName(tr,'qty').value=kind==='credit'?'-1':'1';
    chooseUnit(byName(tr,'unit'),item.kind==='service'?'Std.':'Stk.');
    markChanged();recalc();
  }
  function isBlankRow(row) {
    return !byName(row,'description').value.trim() && !byName(row,'item_id').value &&
      !(Number(byName(row,'price').value) || 0) && !(Number(byName(row,'discount').value) || 0) &&
      (Number(byName(row,'qty').value) === 1 || (kind === 'credit' && Number(byName(row,'qty').value) === -1));
  }
  function addFoundItem(item) {
    const empty=[...tbody.querySelectorAll('.editor-line')].find(isBlankRow);
    const tr=empty || addRow('normal',false,true);
    applyItem(tr,item);search.value='';searchResults.hidden=true;searchResults.replaceChildren();
    byName(tr,'qty').focus();
    feedback(item.name+' zur Rechnung hinzugefuegt.');
  }
  // Schnellerfassung: Alle bestehenden Rechnungspositionen werden bei der
  // Artikelanlage unveraendert beibehalten. Neues Produkt sofort auswahlen.
  const quickDialog=document.getElementById('new-item-dialog');
  const quickForm=document.getElementById('new-item-form');
  const quickError=document.getElementById('quick-item-error');
  document.getElementById('new-item-button').addEventListener('click',()=>{
    quickError.hidden=true;quickError.textContent='';
    quickDialog.showModal();quickForm.elements.namedItem('name').focus();
  });
  function closeQuickDialog(){if(quickDialog.open)quickDialog.close();}
  document.getElementById('cancel-new-item').addEventListener('click',closeQuickDialog);
  document.getElementById('close-item-dialog').addEventListener('click',closeQuickDialog);
  quickForm.addEventListener('submit',async(event)=>{
    event.preventDefault();
    quickError.hidden=true;
    if(!quickForm.reportValidity())return;
    const submit=document.getElementById('save-new-item');submit.disabled=true;
    const oldLabel=submit.textContent;submit.textContent='Artikel wird gespeichert …';
    try{
      const payload=new FormData(quickForm);
      payload.set('_csrf',form.querySelector('[name="_csrf"]').value);
      const response=await fetch(SWISS_BASE+'/api/items/quick-create',{
        method:'POST',body:payload,credentials:'same-origin'});
      const result=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(result.detail||'Artikel konnte nicht gespeichert werden.');
      const item=result.item;
      if(!item||!Number.isInteger(Number(item.id)))throw new Error('Ungueltige Serverantwort.');
      items.push(item);
      for(const picker of tbody.querySelectorAll('.item-picker')){
        const option=document.createElement('option');option.value=String(item.id);
        option.textContent=(item.sku||item.name)+' - '+item.name;picker.appendChild(option);
      }
      addFoundItem(item);quickForm.reset();closeQuickDialog();
      feedback('Artikel '+item.name+' erstellt und zur Rechnung hinzugefügt.');
    }catch(err){quickError.textContent=err.message||'Unbekannter Fehler';quickError.hidden=false;}
    finally{submit.disabled=false;submit.textContent=oldLabel;}
  });
  function renderSearch() {
    const query=search.value.trim().toLocaleLowerCase('de-CH');
    searchResults.replaceChildren();
    if (!query) {searchResults.hidden=true;return;}
    const found=items.filter(item => [item.name,item.sku,item.category,item.description]
      .some(value=>String(value||'').toLocaleLowerCase('de-CH').includes(query))).slice(0,9);
    if (!found.length) {
      const note=document.createElement('p');note.className='small-help';note.textContent='Kein Treffer. Eine freie Position kann ergänzt werden.';
      searchResults.appendChild(note);
    }
    found.forEach(item => {
      const button=document.createElement('button');button.type='button';button.className='product-result';
      button.setAttribute('role','option');
      const info=document.createElement('span');const title=document.createElement('strong');
      title.textContent=item.name;const sku=document.createElement('small');
      sku.textContent=(item.sku||'Ohne Artikelnummer')+(item.kind==='service'?' · Dienstleistung':' · Artikel');
      info.append(title,sku);
      const price=document.createElement('b');price.textContent=money(Number(item.price)||0)+' '+document.getElementById('invoice-currency').value;
      button.append(info,price);button.addEventListener('click',()=>addFoundItem(item));searchResults.appendChild(button);
    });
    searchResults.hidden=false;
  }
  search.addEventListener('input',renderSearch);
  search.addEventListener('keydown',event => {
    if (event.key==='Escape') {search.value='';renderSearch();}
    if (event.key==='Enter' && !searchResults.hidden) {
      const first=searchResults.querySelector('button');if (first) {event.preventDefault();first.click();}
    }
  });
  document.getElementById('invoice-currency').addEventListener('change',renderSearch);

  function checkNumber() {
    const value=numberField.value.trim();
    const requestId=++numberRequestId;
    clearTimeout(numberTimer);
    if (!value) {numberStatus.textContent='Automatische Nummer beim Speichern.';numberStatus.className='small-help';return;}
    if (!/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$/.test(value)) {
      numberStatus.textContent='Bitte nur Buchstaben, Zahlen, Leerzeichen, Punkt, _ oder - verwenden.';
      numberStatus.className='small-help number-unavailable';return;
    }
    numberStatus.textContent='Pruefe Nummer ...';
    numberTimer=setTimeout(async () => {
      const id=form.querySelector('[name="id"]').value||'0';
      try {
        const url=SWISS_BASE + '/api/invoices/check-number?number='+encodeURIComponent(value)+'&exclude_id='+encodeURIComponent(id);
        const response=await fetch(url,{credentials:'same-origin'});
        if (requestId!==numberRequestId)return;
        if (!response.ok)throw new Error('Pruefung momentan nicht erreichbar');
        const result=await response.json();
        numberStatus.textContent=result.message;
        numberStatus.className=result.available?'small-help number-available':'small-help number-unavailable';
      } catch(error) {if(requestId===numberRequestId) {numberStatus.textContent='Pruefung erst beim Speichern moeglich.';numberStatus.className='small-help';}}
    },260);
  }
  numberField.addEventListener('input',checkNumber);
  numberField.addEventListener('blur',checkNumber);
  checkNumber();
  const copySelectValues = (from,to) => {
    const source = from.querySelectorAll('select'); const target = to.querySelectorAll('select');
    source.forEach((el,index) => {target[index].value = el.value;});
  };
  document.getElementById('add-row').addEventListener('click',() => addRow());
  document.getElementById('add-row-bottom').addEventListener('click',() => addRow());
  document.getElementById('add-service').addEventListener('click',() => addRow('service'));
  document.getElementById('add-text').addEventListener('click',() => addRow('text'));
  tbody.addEventListener('click',event => {
    const button = event.target.closest('button');if(!button)return;
    const tr = button.closest('.editor-line');if(!tr)return;
    if (button.classList.contains('remove-row')) {
      if (tbody.querySelectorAll('.editor-line').length <= 1) {feedback('Mindestens eine Position muss stehen bleiben.',true);return;}
      lastRemoved={row:tr,next:tr.nextElementSibling};
      tr.remove();undoButton.hidden=false;
    } else if (button.classList.contains('row-copy')) {
      const clone=tr.cloneNode(true);copySelectValues(tr,clone);
      // A copied position keeps its tax values, but stays visually compact.
      clone.querySelector('.hi-line-advanced').open=false;
      tr.after(clone);
    } else if (button.classList.contains('row-up') && tr.previousElementSibling) {
      tr.previousElementSibling.before(tr);
    } else if (button.classList.contains('row-down') && tr.nextElementSibling) {
      tr.nextElementSibling.after(tr);
    } else return;
    markChanged();recalc();
  });
  document.getElementById('clean-empty-rows')?.addEventListener('click', () => {
    const rows=[...tbody.querySelectorAll('.editor-line')];
    const blanks=rows.filter(isBlankRow);
    // Leave one input card so there is always a place to type.
    const remove=blanks.length===rows.length ? blanks.slice(1) : blanks;
    for (const row of remove) row.remove();
    if (!remove.length) {feedback('Keine leeren Positionen zum Entfernen.');return;}
    lastRemoved=null;undoButton.hidden=true;
    markChanged();recalc();
    feedback(`${remove.length} leere ${remove.length===1?'Position':'Positionen'} entfernt.`);
  });
  undoButton.addEventListener('click',() => {
    if (!lastRemoved)return;
    const restored=lastRemoved.row;
    if (lastRemoved.next && lastRemoved.next.parentElement===tbody)tbody.insertBefore(restored,lastRemoved.next);
    else tbody.appendChild(restored);
    lastRemoved=null;undoButton.hidden=true;
    markChanged();recalc();byName(restored,'description').focus();
  });
  tbody.addEventListener('change',event => {
    if (event.target.classList.contains('item-picker')) {
      const tr=event.target.closest('.editor-line');const item=items.find(a => String(a.id)===event.target.value);
      if (item)applyItem(tr,item);
    }
    markChanged();recalc();
  });
  tbody.addEventListener('input',()=>{markChanged();recalc();});
  toggleCustomer.addEventListener('click',() => {
    newCustomer.hidden = !newCustomer.hidden;
    toggleCustomer.setAttribute('aria-expanded', String(!newCustomer.hidden));
    toggleCustomer.textContent = newCustomer.hidden ? '+ Kunde direkt erfassen' : 'Kundenerfassung schliessen';
    if (!newCustomer.hidden) {customer.value='';newCustomerName.focus();}
    else newCustomerName.value='';
    renderCustomerSummary();renderDueHint();markChanged();recalc();
  });
  customer.addEventListener('change',() => {
    if (customer.value && !newCustomer.hidden) {newCustomer.hidden=true;toggleCustomer.textContent='+ Kunde direkt erfassen';toggleCustomer.setAttribute('aria-expanded','false');newCustomerName.value='';}
    renderCustomerSummary();renderDueHint();markChanged();recalc();
  });
  document.querySelectorAll('[data-due-days]').forEach(button => button.addEventListener('click',() => {
    const start=getDate(document.getElementById('invoice-date').value);
    if (!start) {feedback('Bitte zuerst ein gueltiges Belegdatum waehlen.',true);return;}
    start.setDate(start.getDate()+Number(button.dataset.dueDays));
    const yy=start.getFullYear(), mm=String(start.getMonth()+1).padStart(2,'0'), dd=String(start.getDate()).padStart(2,'0');
    due.value=`${yy}-${mm}-${dd}`;markChanged();recalc();
  }));
  const customerDueInfo = document.getElementById('customer-due-info');
  function renderDueHint() {
    const selected=customers.find(c => String(c.id)===customer.value);
    const days=Number(selected?.payment_days || 0);
    const fallback=Number(form.dataset.defaultDue || 30);
    customerDueInfo.textContent=days>0
      ? `${selected.name}: ${days} Tage ab Belegdatum. Zum Uebernehmen klicken.`
      : `Firmenstandard: ${fallback} Tage ab Belegdatum.`;
  }
  document.getElementById('apply-customer-due')?.addEventListener('click',() => {
    const selected=customers.find(c => String(c.id)===customer.value);
    const days=Number(selected?.payment_days || 0) || Number(form.dataset.defaultDue || 30);
    const start=getDate(document.getElementById('invoice-date').value);
    if (!start) {feedback('Bitte zuerst ein gueltiges Belegdatum waehlen.',true);return;}
    start.setDate(start.getDate()+days);
    due.value=`${start.getFullYear()}-${String(start.getMonth()+1).padStart(2,'0')}-${String(start.getDate()).padStart(2,'0')}`;
    markChanged();recalc();feedback(`Zahlungsziel von ${days} Tagen uebernommen.`);
  });
  customer.addEventListener('change',renderDueHint);

  const bulkInput=document.getElementById('bulk-lines-input');
  const bulkCheck=document.getElementById('bulk-check');
  const bulkAdd=document.getElementById('bulk-add');
  const bulkUndo=document.getElementById('bulk-undo');
  const bulkResult=document.getElementById('bulk-result');
  let bulkRows=null,bulkSource='',lastBulk=null;
  function showBulk(message,bad=false) {
    bulkResult.textContent=message;
    bulkResult.className=bad?'small-help mt-2 bulk-bad':'small-help mt-2 bulk-good';
  }
  bulkInput?.addEventListener('input',() => {
    bulkRows=null;bulkSource='';bulkAdd.disabled=true;
    bulkResult.textContent='Text geaendert. Bitte die Zeilen erneut pruefen.';
    bulkResult.className='small-help mt-2';
  });
  bulkCheck?.addEventListener('click',() => {
    try {
      const rows=window.HelveticBulk.parse(bulkInput.value,kind,form.dataset.defaultTax||'0');
      if (form.dataset.taxRegistered !== '1' && rows.some(r=>Number(r.tax)!==0))
        throw new Error('Das Geschaeft ist nicht MWST-pflichtig. Bitte Steuersatz 0 verwenden.');
      const filled=[...tbody.querySelectorAll('.editor-line')].filter(r=>byName(r,'description').value.trim()).length;
      if (rows.length + filled > 150) throw new Error('Rechnung darf maximal 150 beschriebene Positionen enthalten.');
      bulkRows=rows;bulkSource=bulkInput.value;bulkAdd.disabled=false;
      showBulk(`${rows.length} Position(en) geprueft. Vorschau: ${rows.slice(0,3).map(r=>r.description+' ('+r.qty+' x '+r.price+')').join(' | ')}. Mit Uebernehmen einfuegen.`);
    } catch (error) {bulkRows=null;bulkAdd.disabled=true;showBulk(error.message,true);}
  });
  bulkAdd?.addEventListener('click',() => {
    if (!bulkRows || bulkSource!==bulkInput.value) {showBulk('Bitte zuerst die aktuellen Zeilen pruefen.',true);return;}
    const available=[...tbody.querySelectorAll('.editor-line')].filter(isBlankRow);
    const inserted=[],reused=[],appended=[];
    for (const row of bulkRows) {
      const originalBlank=available.shift();
      const tr=originalBlank || addRow('normal',false,true);
      if (originalBlank) {
        const snapshot=tr.cloneNode(true);copySelectValues(tr,snapshot);
        reused.push({current:tr,original:snapshot});
      } else appended.push(tr);
      byName(tr,'item_id').value='';
      byName(tr,'description').value=row.description;
      byName(tr,'qty').value=row.qty;
      chooseUnit(byName(tr,'unit'),row.unit);
      byName(tr,'price').value=row.price;
      byName(tr,'discount').value=row.discount;
      byName(tr,'tax_mode').value='taxable';
      const tax=byName(tr,'tax_rate');
      if (taxEnabled && tax.tagName==='SELECT' && ![...tax.options].some(option=>option.value===row.tax)) {
        const option=document.createElement('option');option.value=row.tax;option.textContent=row.tax+' %';tax.add(option);
      }
      tax.value=taxEnabled ? row.tax : '0';
      inserted.push(tr);
    }
    lastBulk={inserted,reused,appended};
    bulkRows=null;bulkSource='';bulkAdd.disabled=true;bulkUndo.hidden=false;
    bulkInput.value='';markChanged();recalc();
    showBulk(`${inserted.length} Position(en) eingefuegt. Bitte Gesamtbetrag und Rabatte prüfen.`);
  });
  bulkUndo?.addEventListener('click',() => {
    if (!lastBulk)return;
    const {reused,appended}=lastBulk;
    for (const {current,original} of reused) {
      if (current.parentElement===tbody)tbody.replaceChild(original,current);
    }
    for (const tr of appended) if (tr.parentElement===tbody) tr.remove();
    if (!tbody.children.length) addRow('normal',false,true);
    lastBulk=null;bulkUndo.hidden=true;markChanged();recalc();
    showBulk('Letzter Excel-Import rueckgaengig gemacht. Andere Positionen bleiben bestehen.');
  });

  document.getElementById('use-suggested-number')?.addEventListener('click',() => {
    numberField.value=suggested;markChanged();recalc();
  });
  form.addEventListener('input',event => {
    if (event.target.closest('#invoice-rows') || event.target.closest('#bulk-import-panel') || event.target === customerFilter)return;
    markChanged();recalc();
  });
  form.addEventListener('change',event => {
    if (event.target.closest('#invoice-rows') || event.target.closest('#bulk-import-panel') || event.target===customer)return;
    markChanged();recalc();
  });
  // Autosave: unvollstaendige Eingaben verschluesseln wir nicht im Browser;
  // sie bleiben im lokalen Browserprofil. Vollstaendige Entwuerfe werden
  // nach kurzer Eingabepause auch serverseitig gespeichert.
  const draftKey=()=>['swissrx','editor','v2',form.dataset.userId,form.dataset.companyId,
                      kind,form.querySelector('[name="id"]').value||'new'].join(':');
  function snapshotDraft(){
    const pairs=[...new FormData(form).entries()].filter(([key,val])=>
      key!=='_csrf' && key!=='id' && typeof val==='string');
    return {saved:Date.now(),customerOpen:!newCustomer.hidden,pairs};
  }
  function persistLocalDraft(){
    try{localStorage.setItem(draftKey(),JSON.stringify(snapshotDraft()));}
    catch(e){saveStatus.textContent='Lokale Zwischenspeicherung nicht verfügbar.';saveStatus.classList.add('error');}
  }
  function clearLocalDraft(key){
    try{localStorage.removeItem(key||draftKey());}catch(e){}
  }
  function restoreLocalDraft(){
    let stored;
    try{stored=JSON.parse(localStorage.getItem(draftKey())||'null');}catch(e){return;}
    if(!stored||!Array.isArray(stored.pairs))return;
    if(Date.now()-Number(stored.saved)>7*24*3600*1000){clearLocalDraft();return;}
    const values=new Map();
    for(const entry of stored.pairs){
      if(!Array.isArray(entry)||entry.length!==2||typeof entry[0]!=='string'||typeof entry[1]!=='string')continue;
      if(!values.has(entry[0]))values.set(entry[0],[]);
      values.get(entry[0]).push(entry[1]);
    }
    const descriptions=values.get('description[]')||[];
    if(descriptions.length>150)return;
    while(tbody.querySelectorAll('.editor-line').length<descriptions.length)addRow('normal',false,true);
    // No form controls get replaced: selected client, CSRF and account remain trusted.
    for(const [name,list] of values){
      const elements=[...form.querySelectorAll('[name]')].filter(el=>el.name===name);
      if(name==='kind'||name==='_csrf'||name==='id')continue;
      for(let i=0;i<Math.min(elements.length,list.length);i++){
        const el=elements[i];
        if(el.type==='file')continue;
        if(el.type==='checkbox'||el.type==='radio')el.checked=list.includes(el.value);
        else{
          if(el.tagName==='SELECT' && ![...el.options].some(o=>o.value===list[i]) && (name==='tax_rate[]'||name==='unit[]')){
            const opt=document.createElement('option');opt.value=list[i];opt.textContent=list[i]+(name==='tax_rate[]'?' %':'');el.add(opt);
          }
          el.value=(!taxEnabled && name==='tax_rate[]') ? '0' : (!taxEnabled && name==='tax_mode[]') ? 'taxable' : list[i];
        }
      }
    }
    newCustomer.hidden=!stored.customerOpen;
    toggleCustomer.setAttribute('aria-expanded',String(stored.customerOpen));
    toggleCustomer.textContent=stored.customerOpen?'Kundenerfassung schliessen':'+ Kunde direkt erfassen';
    changed=true;autosaveVersion++;
    saveStatus.textContent='Lokale Eingaben wiederhergestellt. Automatisches Speichern aktiv.';
    renderCustomerSummary();renderDueHint();recalc();scheduleAutosave();
  }
  function serverReady(){
    const hasCustomer=(!newCustomer.hidden && newCustomerName.value.trim()) ||
      (newCustomer.hidden && customer.value);
    const hasLine=[...tbody.querySelectorAll('[name="description[]"]')].some(e=>e.value.trim());
    const validNumber=!numberField.value.trim() || /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$/.test(numberField.value.trim());
    const dates=['invoice-date','due-date'].every(id=>Boolean(getDate(document.getElementById(id).value)));
    return hasCustomer&&hasLine&&dates&&validNumber&&form.checkValidity();
  }
  function scheduleAutosave(){
    clearTimeout(autosaveTimer);
    if(!changed||sending)return;
    if(!serverReady()){
      saveStatus.textContent='Zwischengespeichert im Browser – Kundenangaben und Position ergänzen.';
      saveStatus.classList.remove('error');return;
    }
    saveStatus.textContent='Änderungen erkannt – Autospeichern …';
    autosaveTimer=setTimeout(()=>{void autosaveDraft();},1500);
  }
  async function autosaveDraft(){
    clearTimeout(autosaveTimer);
    if(!changed||sending||!serverReady())return;
    if(autosavePromise)return autosavePromise;
    const revision=autosaveVersion;
    const oldKey=draftKey();
    const payload=new FormData(form);
    saveStatus.textContent='Entwurf wird automatisch gespeichert …';
    autosavePromise=(async()=>{
      const response=await fetch(SWISS_BASE+'/api/invoices/autosave',{
        method:'POST',body:payload,credentials:'same-origin'});
      const result=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(result.detail||'Autospeichern fehlgeschlagen.');
      const originalId=form.querySelector('[name="id"]').value;
      form.querySelector('[name="id"]').value=String(result.id);
      numberField.value=result.number;
      numberField.required=true;
      editing=true;
      if(!originalId){
        history.replaceState(null,'',SWISS_BASE+'/invoices/'+result.id+'/edit');
      }
      if(!newCustomer.hidden && Number(result.customer_id)>0 &&
          ![...customer.options].some(o=>o.value===String(result.customer_id))){
        const option=document.createElement('option');option.value=String(result.customer_id);
        option.textContent=newCustomerName.value.trim()||'Neuer Kunde';customer.add(option);
        customers.push({id:result.customer_id,name:option.textContent,zip:'',city:'',country:'CH'});
      }
      if(!newCustomer.hidden && result.customer_id){
        customer.value=String(result.customer_id);
        newCustomer.hidden=true;newCustomerName.value='';
        toggleCustomer.setAttribute('aria-expanded','false');
        toggleCustomer.textContent='+ Kunde direkt erfassen';
      }
      clearLocalDraft(oldKey);
      if(revision===autosaveVersion){
        changed=false;
        clearLocalDraft();
        feedback('');
        saveStatus.textContent='Automatisch gespeichert um '+result.saved_at+' · Entwurf';
        saveStatus.classList.remove('error');
      }else{
        persistLocalDraft();scheduleAutosave();
      }
      renderCustomerSummary();recalc();
    })().catch(error=>{
      saveStatus.textContent='Autospeichern nicht möglich: '+(error.message||'Netzwerkfehler')+'. Eingaben bleiben im Browser erhalten.';
      saveStatus.classList.add('error');
    }).finally(()=>{autosavePromise=null;});
    return autosavePromise;
  }
  // Bei durchgehendem Tippen auch ohne Eingabepause regelmaessig sichern.
  setInterval(()=>{if(changed&&!autosavePromise&&serverReady()&&!sending)void autosaveDraft();},20000);
  form.addEventListener('submit',event => {
    const preview=event.submitter===previewButton;
    if(!preview && autosavePromise){
      event.preventDefault();
      const button=event.submitter||document.getElementById('save-invoice');
      autosavePromise.then(()=>form.requestSubmit(button));
      return;
    }
    clearTimeout(autosaveTimer);
    const number=numberField.value.trim();
    if ((number && !/^[A-Za-z0-9][A-Za-z0-9 ._-]{0,39}$/.test(number)) || (editing && !number)) {
      event.preventDefault();feedback('Bitte eine gueltige Belegnummer ohne Sonderzeichen eingeben.',true);numberField.focus();return;
    }
    if (newCustomer.hidden && !customer.value) {
      event.preventDefault();feedback('Bitte einen Kunden auswaehlen oder direkt neu erfassen.',true);customer.focus();return;
    }
    if (!newCustomer.hidden && !newCustomerName.value.trim()) {
      event.preventDefault();feedback('Bitte einen Namen fuer den neuen Kunden erfassen.',true);newCustomerName.focus();return;
    }
    if (![...tbody.querySelectorAll('[name="description[]"]')].some(el => el.value.trim())) {
      event.preventDefault();feedback('Mindestens eine Position braucht eine Beschreibung.',true);return;
    }
    if (preview) {feedback('Nicht gespeicherte PDF-Vorschau wird in einem neuen Tab geoeffnet.');return;}
    sending=true;const button=document.getElementById('save-invoice');button.disabled=true;button.textContent='Entwurf wird gespeichert ...';
  });
  window.addEventListener('beforeunload',event => {if(changed && !sending){event.preventDefault();event.returnValue='';}});
  window.addEventListener('pagehide',()=>{if(sending)clearLocalDraft();});
  document.addEventListener('keydown',event => {
    if ((event.ctrlKey||event.metaKey) && event.key.toLowerCase()==='s') {
      event.preventDefault();form.requestSubmit(document.getElementById('save-invoice'));
    }
    if ((event.ctrlKey||event.metaKey) && event.key==='Enter') {
      event.preventDefault();form.requestSubmit(previewButton);
    }
  });
  if (newCustomerName.value.trim()) {newCustomer.hidden=false;toggleCustomer.setAttribute('aria-expanded','true');toggleCustomer.textContent='Kundenerfassung schliessen';}
  renderCustomerSummary();
  renderDueHint();
  recalc();
  restoreLocalDraft();
})();
