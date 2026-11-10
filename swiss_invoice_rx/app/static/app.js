const SWISS_BASE = document.querySelector('meta[name="swiss-invoice-base"]')?.getAttribute('content') || '';
'use strict';
(() => {
  document.querySelector('#company-switch')?.addEventListener('change', e => e.target.form.submit());
  document.querySelectorAll('[data-confirm]').forEach(el => el.addEventListener('click', e => {
    if (!confirm(el.dataset.confirm)) e.preventDefault();
  }));
})();

// Swiss-invoice-RX 1.9: globale Suchpalette, lokal und pro Geschaeft.
(() => {
  const dialog = document.querySelector('#global-search-dialog');
  if (!dialog) return;
  const input = dialog.querySelector('#quick-search-input');
  const results = dialog.querySelector('#quick-search-content');
  const openButtons = document.querySelectorAll('[data-open-global-search]');
  const groupNames = {invoices:'Rechnungen & Belege',customers:'Kunden',items:'Artikel'};
  let timer, active = -1, requestSerial = 0;
  const options = () => [...results.querySelectorAll('.quick-search-hit')];
  function selectNext(step) {
    const links = options();
    if (!links.length) return;
    active = (active + step + links.length) % links.length;
    links.forEach((a,i) => a.classList.toggle('is-selected',i===active));
    links[active].scrollIntoView({block:'nearest'});
  }
  function showMessage(message) { results.replaceChildren(); const p = document.createElement('p'); p.textContent=message; results.append(p); active = -1; }
  function appendHit(group,hit) {
    const a = document.createElement('a'); a.className='quick-search-hit'; a.href=hit.url.startsWith('/') ? SWISS_BASE + hit.url : hit.url;
    const wrap = document.createElement('span');
    const title = document.createElement('strong');title.textContent=hit.title;
    const subtitle=document.createElement('small');subtitle.textContent=hit.subtitle;
    wrap.append(title,subtitle);
    const arrow=document.createElement('span');arrow.textContent='→';arrow.setAttribute('aria-hidden','true');
    a.append(wrap,arrow); group.append(a);
  }
  async function load(q) {
    const serial = ++requestSerial;
    if (q.length<2) {showMessage('Mindestens 2 Zeichen eingeben.');return;}
    showMessage('Suche läuft …');
    try {
      const resp=await fetch(SWISS_BASE + '/api/search?q='+encodeURIComponent(q),{headers:{Accept:'application/json'}});
      if (!resp.ok || !resp.headers.get('content-type')?.includes('json')) throw Error('Suche nicht verfügbar; bitte neu anmelden.');
      const data=await resp.json();
      if (serial!==requestSerial) return;
      results.replaceChildren();active=-1;let any=false;
      for (const [key,label] of Object.entries(groupNames)) {
        const hits = data.groups?.[key] ?? [];
        if (!hits.length) continue;
        any=true;
        const group=document.createElement('section');group.className='quick-search-group';
        const heading=document.createElement('h3');heading.textContent=label;group.append(heading);
        hits.forEach(hit=>appendHit(group,hit)); results.append(group);
      }
      if (!any) showMessage('Keine Treffer. Mit Enter die erweiterte Suche öffnen.');
      const more=document.createElement('a');more.href=SWISS_BASE + '/search?q='+encodeURIComponent(q);
      more.className='quick-search-more';more.textContent='Alle Suchergebnisse anzeigen →';results.append(more);
    } catch(err) { if (serial===requestSerial) showMessage(err.message || 'Suche nicht möglich'); }
  }
  function openSearch() {
    if (!dialog.open) dialog.showModal();
    input.focus(); input.select(); load(input.value.trim());
  }
  openButtons.forEach(b=>b.addEventListener('click',openSearch));
  dialog.querySelector('[data-close-global-search]').addEventListener('click',()=>dialog.close());
  dialog.addEventListener('click',event=>{if (event.target===dialog) dialog.close();});
  dialog.addEventListener('keydown',event=>{ if(event.key==='Escape'){event.preventDefault();dialog.close();} });
  input.addEventListener('input',()=>{clearTimeout(timer); const text=input.value.trim(); const serial=++requestSerial; timer=setTimeout(()=>{if(serial===requestSerial)load(text);},150);});
  input.addEventListener('keydown',event=>{
    if (event.key==='ArrowDown'||event.key==='ArrowUp') {event.preventDefault();selectNext(event.key==='ArrowDown'?1:-1);}
    if (event.key==='Enter' && active>=0) {event.preventDefault(); window.location.assign(options()[active].href);}
  });
  document.addEventListener('keydown',event=>{
    if ((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k') {event.preventDefault();openSearch();}
    if (event.key==='/'&&!dialog.open&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName)) {event.preventDefault();openSearch();}
  });

})();

// Swiss-invoice-RX 1.9: Archiv-Auswahl ohne Datenmutation.
(() => {
  const form=document.querySelector('#archive-bulk-form');if(!form)return;
  const selectAll=form.querySelector('#archive-select-all');
  const checkboxes=[...form.querySelectorAll('.archive-select')];
  const count=form.querySelector('#archive-count');const button=form.querySelector('#archive-download');
  const selected=()=>checkboxes.filter(b=>b.checked);
  function update(){
    const n=selected().length; count.textContent=n+' / 25 Belege ausgewählt';
    button.disabled=n===0||n>25;selectAll.checked=checkboxes.length>0&&n===checkboxes.length;
    selectAll.indeterminate=n>0&&n<checkboxes.length;
    count.classList.toggle('archive-limit',n>25);
  }
  selectAll.addEventListener('change',()=>{
    checkboxes.forEach((b,i)=>{b.checked=selectAll.checked&&i<25;});update();
    if(selectAll.checked&&checkboxes.length>25)count.textContent='Erste 25 Belege ausgewählt (Maximalgrenze).';
  });
  checkboxes.forEach(b=>b.addEventListener('change',()=>{
    if(selected().length>25){b.checked=false;count.textContent='Maximal 25 Belege pro ZIP. Bitte Auswahl verkleinern.';return;}
    update();
  }));
  form.addEventListener('submit',e=>{if(selected().length<1||selected().length>25)e.preventDefault();});
  update();
})();

// Swiss-invoice-RX 1.9: vollstaendige mobile Navigation mit Geschaeftswechsel.
(() => {
  const toggle=document.querySelector('#mobile-menu-toggle');
  const sidebar=document.querySelector('#main-sidebar');
  const backdrop=document.querySelector('#sidebar-overlay');
  if (!toggle||!sidebar||!backdrop) return;
  function show(open){
    sidebar.classList.toggle('is-open',open);
    backdrop.hidden=!open;
    backdrop.classList.toggle('is-visible',open);
    toggle.setAttribute('aria-expanded',String(open));
    toggle.setAttribute('aria-label',open?'Menü schliessen':'Menü öffnen');
    document.body.classList.toggle('menu-open',open);
    if(open) sidebar.querySelector('.work-switch select')?.focus();
    else toggle.focus();
  }
  toggle.addEventListener('click',()=>show(!sidebar.classList.contains('is-open')));
  backdrop.addEventListener('click',()=>show(false));
  sidebar.querySelectorAll('nav a').forEach(a=>a.addEventListener('click',()=>show(false)));
  document.addEventListener('keydown',e=>{
    if(e.key==='Escape'&&sidebar.classList.contains('is-open')){e.preventDefault();show(false);}
  });
  window.matchMedia('(min-width:871px)').addEventListener?.('change',e=>{
    if(e.matches&&sidebar.classList.contains('is-open'))show(false);
  });
})();

// 2.1: aktive Seite, aufklappbare Bereiche und die letzten Menu-Einstellungen.
(() => {
  const sidebar = document.querySelector('#main-sidebar');
  if (!sidebar) return;
  const fullPath = window.location.pathname;
  const path = SWISS_BASE && fullPath.startsWith(SWISS_BASE + '/') ? fullPath.slice(SWISS_BASE.length) : fullPath;
  const params = new URLSearchParams(window.location.search);
  const kind = sidebar.dataset.documentKind || params.get('kind') || 'invoice';
  const target = (() => {
    if (path === '/dashboard') return 'dashboard';
    if (path === '/search') return 'search';
    if (path === '/invoices' || path.startsWith('/invoices/')) return kind === 'quote' ? 'quotes' : kind === 'credit' ? 'credits' : 'invoices';
    if (path.startsWith('/recurring')) return 'recurring';
    if (path.startsWith('/customers')) return 'customers';
    if (path.startsWith('/items') || path.startsWith('/stock')) return 'items';
    if (path.startsWith('/receivables')) return 'receivables';
    if (path.startsWith('/bank')) return 'bank';
    if (path.startsWith('/archive')) return 'archive';
    if (path.startsWith('/reports')) return 'reports';
    if (path.startsWith('/templates/designer')) return 'designer';
    if (path.startsWith('/templates')) return 'templates';
    if (path.startsWith('/qr-test')) return 'qr-test';
    if (path.startsWith('/settings')) return 'settings';
    if (path.startsWith('/team')) return 'team';
    if (path.startsWith('/activity')) return 'activity';
    if (path.startsWith('/backup')) return 'backup';
    if (path.startsWith('/systemcheck')) return 'systemcheck';
    if (path.startsWith('/help')) return 'help';
    return '';
  })();
  sidebar.querySelectorAll('.nav-link').forEach(link => {
    const selected = link.dataset.navKey === target;
    link.classList.toggle('is-active', selected);
    if (selected) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });

  const groups = Array.from(sidebar.querySelectorAll('details.nav-group'));
  const activeLink = Array.from(sidebar.querySelectorAll('.nav-link')).find(link => link.dataset.navKey === target);
  const storageKey = 'helvetic-sidebar-v21-' + (sidebar.dataset.userId || 'default');
  let previous = {};
  try { previous = JSON.parse(localStorage.getItem(storageKey) || '{}'); }
  catch (_) { previous = {}; }
  if (previous && typeof previous === 'object' && !Array.isArray(previous)) {
    groups.forEach(group => {
      const remembered = previous[group.dataset.navGroup];
      if (typeof remembered === 'boolean') group.open = remembered;
    });
  }
  // Die aktuelle Seite ist immer sichtbar, auch wenn der Bereich zuvor geschlossen wurde.
  const activeGroup = activeLink?.closest('details.nav-group');
  if (activeGroup) activeGroup.open = true;
  groups.forEach(group => {
    const summary = group.querySelector('summary');
    if (activeGroup === group) summary.setAttribute('aria-label', summary.textContent.trim() + ', aktueller Bereich');
    group.addEventListener('toggle', () => {
      try {
        const state = JSON.parse(localStorage.getItem(storageKey) || '{}');
        state[group.dataset.navGroup] = group.open;
        localStorage.setItem(storageKey, JSON.stringify(state));
      } catch (_) { /* private Browsermodi koennen lokale Einstellungen blockieren */ }
    });
  });
})();
