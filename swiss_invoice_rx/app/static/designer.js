const SWISS_BASE = document.querySelector('meta[name="swiss-invoice-base"]')?.getAttribute('content') || '';
/* Swiss-invoice-RX 1.8: genuine pointer/keyboard A4 editor. No external JS. */
(() => {
  'use strict';
  const root = document.getElementById('layout-designer');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const paper = $('designer-paper'), layer = $('designer-layer'), form = $('designer-save-form');
  const taxEnabled = root.dataset.taxRegistered === '1';
  const LABELS = {logo:'Firmenlogo',sender:'Absender',recipient:'Empfänger',title:'Rechnungstitel',number:'Rechnungsnummer',dates:'Datumsangaben',subject:'Betreff',table:'Positionstabelle',totals:taxEnabled?'Total und MWST':'Total',notes:'Bemerkungen',terms:'Zahlungsbedingungen',footer:'Fusszeile',uid:taxEnabled?'UID / MWST':'UID',text:'Eigener Text',line:'Linie',box:'Farbfläche',image:'Eigenes Bild'};
  const REQUIRED = new Set(['sender','recipient','title','number','dates','table','totals']);
  const MULTIPLE = new Set(['text','image','box','line']);
  const minimum = {sender:[39,22],recipient:[39,22],title:[32,12],number:[26,8],dates:[40,22],table:[135,23],totals:[80,25]};
  const palette = {logo:[15,15,50,20],sender:[120,15,74,32],recipient:[15,56,80,30],title:[15,99,80,16],number:[15,119,70,9],dates:[126,104,70,28],subject:[15,135,110,10],table:[15,155,180,42],totals:[112,209,83,30],notes:[15,242,125,10],terms:[15,255,135,8],footer:[15,288,180,7],uid:[15,147,80,8],text:[35,83,80,14],image:[85,24,55,29],box:[15,91,180,5],line:[15,94,180,3]};
  const initial = JSON.parse($('designer-initial').textContent);
  let blocks = structuredClone(initial.blocks), selected = null, history = [], future = [], dirty = false, dragging = null;
  const clamp=(v,min,max)=>Math.min(Math.max(v,min),max);
  const snap=v=>$('designer-snap').checked ? Math.round(v/5)*5 : Math.round(v*2)/2;
  const byId=id=>blocks.find(b=>b.id===id);
  const num=v=>Number.isFinite(Number(v))?Number(v):0;
  function checkpoint() {
    history.push(JSON.stringify(blocks));if(history.length>80)history.shift();future=[];
  }
  function markDirty() {
    dirty=true;
    // Ganzseitige Bilder und randlose Logos duerfen absichtlich hinter anderen Feldern liegen.
    const first=blocks.filter(b=>!['box','line'].includes(b.kind) &&
      !(['logo','image'].includes(b.kind) && (b.x<0 || b.y<0 || b.w>=180 || b.h>=200)));
    let collision=null;
    for(let i=0;i<first.length&&!collision;i++)for(let j=i+1;j<first.length;j++){
      const a=first[i],b=first[j];
      const w=Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x);
      const h=Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y);
      if(w>2&&h>2&&w*h>35){collision=[LABELS[a.kind],LABELS[b.kind]];break;}
    }
    $('designer-status').textContent=collision
      ? 'Achtung: '+collision.join(' und ')+' überlappen sich. Bitte PDF-Muster prüfen.'
      : 'Änderungen noch nicht gespeichert';
    $('designer-status').classList.add('dirty');
  }
  function setClean() {dirty=false;$('designer-status').textContent='Layout gespeichert';$('designer-status').classList.remove('dirty');}
  function bounds(b){
    const min=minimum[b.kind]||[3,2];
    if(['logo','image'].includes(b.kind)){
      b.w=clamp(Math.round(b.w*10)/10,min[0],300);
      b.h=clamp(Math.round(b.h*10)/10,min[1],330);
      b.x=clamp(Math.round(b.x*10)/10,Math.max(-30,5-b.w),205);
      b.y=clamp(Math.round(b.y*10)/10,Math.max(-30,5-b.h),292);
    }else{
      b.w=clamp(Math.round(b.w*10)/10,min[0],208);
      b.h=clamp(Math.round(b.h*10)/10,min[1],295);
      b.x=clamp(Math.round(b.x*10)/10,1,209-b.w);
      b.y=clamp(Math.round(b.y*10)/10,1,Math.min(296-b.h,b.kind==='table'?241:296));
    }
  }
  function entryText(b) {
    const co=root.dataset.company || 'Mein Geschäft';
    const texts={logo:'Logo – noch keines hinterlegt',sender:co+'\n'+root.dataset.address+'\ninfo@beispiel.ch',recipient:'Musterkunde AG\nMusterstrasse 8\n8000 Zürich',title:root.dataset.title||'Rechnung',number:'Nr. RE-2026-00001',dates:'Datum: 08.11.2026\nFällig: 08.12.2026\nLeistung: 08.11.2026',subject:'Projekt / Betreff',uid:taxEnabled?'UID / MWST: CHE-000.000.000':'UID: CHE-000.000.000',notes:root.dataset.notes||'Besten Dank für Ihren Auftrag.',terms:root.dataset.terms||'Zahlbar innert 30 Tagen.',footer:root.dataset.footer||'Vielen Dank für Ihren Auftrag.',text:b.text||'Doppelklicken und rechts eigenen Text eingeben'};
    let val=texts[b.kind]||'';
    if(b.kind==='text')val=val.replaceAll('{kunde}','Musterkunde AG').replaceAll('{nummer}','RE-2026-00001').replaceAll('{firma}',co).replaceAll('{datum}','08.11.2026').replaceAll('{faellig}','08.12.2026').replaceAll('{betrag}','318.90').replaceAll('{waehrung}','CHF');
    return val;
  }
  function contentFor(b, host){
    if(b.kind==='logo' && root.dataset.logo==='1'){
      const img=document.createElement('img');img.alt='Firmenlogo';img.src=SWISS_BASE + '/media/logo';img.style.objectFit=b.fit||'contain';host.append(img);
    } else if(b.kind==='image' && /^[a-f0-9]{32}\.jpg$/.test(b.asset||'')){
      const img=document.createElement('img');img.alt='Eigenes Bild';img.src=SWISS_BASE + '/templates/designer/image/'+b.asset;img.style.objectFit=b.fit||'contain';host.append(img);
    } else if(b.kind==='table'){
      // Static example: dynamic invoice lines are generated by the PDF renderer.
      host.innerHTML='<table class="designer-mini-table"><thead><tr><th>Beschreibung</th><th>Menge</th><th>Preis</th><th>Total</th></tr></thead><tbody><tr><td>Beratung</td><td>2 Std.</td><td>125.00</td><td>250.00</td></tr><tr><td>Projektpauschale</td><td>1 Stk.</td><td>45.00</td><td>45.00</td></tr></tbody></table>';
    } else if(b.kind==='totals'){
      host.innerHTML=taxEnabled
        ? '<div class="designer-mini-total"><span>Zwischensumme</span><b>295.00 CHF</b></div><div class="designer-mini-total"><span>MWST 8.1 %</span><b>23.90 CHF</b></div><div class="designer-mini-total"><span>TOTAL</span><b>318.90 CHF</b></div>'
        : '<div class="designer-mini-total"><span>Zwischensumme</span><b>295.00 CHF</b></div><div class="designer-mini-total"><span>TOTAL</span><b>295.00 CHF</b></div>'; 
    } else if(!['line','box','image'].includes(b.kind)){host.textContent=entryText(b);}
  }
  function place(node,b){
    node.style.left=b.x/210*100+'%';node.style.top=b.y/297*100+'%';
    node.style.width=b.w/210*100+'%';node.style.height=b.h/297*100+'%';
    node.style.setProperty('--node-color',b.color);node.style.setProperty('--pageAccent',b.color);
    node.style.textAlign=b.align;
    const inner=node.querySelector('.designer-node-content');
    inner.style.fontSize=Math.max(8,b.size*1.30)+'px';
    inner.style.color=b.color;
    if(b.kind==='title')inner.style.fontWeight='800';
    node.classList.toggle('selected',b.id===selected);
    node.classList.toggle('locked',!!b.locked);
    node.setAttribute('aria-label',LABELS[b.kind]+', X '+b.x+' mm, Y '+b.y+' mm');
  }
  function element(b) {
    const el=document.createElement('div');el.className='designer-node kind-'+b.kind;
    el.dataset.id=b.id;el.tabIndex=0;el.setAttribute('role','button');
    const inner=document.createElement('div');inner.className='designer-node-content';contentFor(b,inner);
    const label=document.createElement('span');label.className='designer-kind-label';label.textContent=LABELS[b.kind];
    const handle=document.createElement('span');handle.className='designer-resize';handle.title='Grösse ändern';
    el.append(inner,label,handle);place(el,b);return el;
  }
  function render() {
    layer.replaceChildren(...blocks.map(element));renderList();renderInspector();
    $('designer-count').textContent=blocks.length+'/35';
    $('designer-layout-json').value=JSON.stringify({version:1,blocks});
  }
  function renderList() {
    const list=$('designer-block-list');list.replaceChildren();
    blocks.forEach(b=>{
      const btn=document.createElement('button');btn.type='button';btn.dataset.id=b.id;
      btn.setAttribute('role','option');btn.setAttribute('aria-selected',String(selected===b.id));
      const ico=document.createElement('span');ico.className='kind-bullet';ico.textContent=b.locked?'⊠':'◇';
      const name=document.createElement('span');name.textContent=LABELS[b.kind];btn.append(ico,name);list.append(btn);
    });
  }
  function renderInspector(){
    const b=byId(selected);const panel=$('designer-property-fields');
    panel.hidden=!b;$('designer-selection-hint').hidden=!!b;
    if(!b)return;
    $('designer-selected-kind').textContent=LABELS[b.kind]+(b.locked?' · Gesperrt':'');
    for(const prop of ['x','y','w','h','size','color','align'])$('d-'+prop).value=b[prop];
    $('d-text-block').hidden=b.kind!=='text';$('d-image-block').hidden=b.kind!=='image';
    const picture=['logo','image'].includes(b.kind);
    $('d-image-settings').hidden=!picture;
    $('d-fit').value=b.fit||'contain';
    for(const id of ['x','y','w','h']){
      const field=$('d-'+id);
      field.min=picture?(id==='x'||id==='y'?-30:id==='w'?3:2):1;
      field.max=picture?(id==='x'?205:id==='y'?292:id==='w'?300:330):(id==='x'?209:id==='y'?296:id==='w'?208:295);
    }
    if(b.kind==='text')$('d-text').value=b.text;
    $('d-delete').disabled=REQUIRED.has(b.kind);
    $('d-lock').textContent=b.locked?'Entsperren':'Sperren';
  }
  function select(id){selected=id;renderList();renderInspector();
    layer.querySelectorAll('.designer-node').forEach(n=>{const b=byId(n.dataset.id);if(b)place(n,b);});
  }
  function add(kind){
    if(!palette[kind]||blocks.length>=35){$('designer-status').textContent='Maximal 35 Elemente erlaubt.';return;}
    if(!MULTIPLE.has(kind)){
      const existing=blocks.find(b=>b.kind===kind);
      if(existing){select(existing.id);return;}
    }
    checkpoint();
    const p=palette[kind];const b={id:'b'+Math.random().toString(36).slice(2,12),kind,x:p[0],y:p[1],w:p[2],h:p[3],size:kind==='title'?24:9,color:kind==='box'?'#dbeafe':(['title','table','totals'].includes(kind)?'#2563eb':'#14233c'),align:'left',text:kind==='text'?'Vielen Dank für Ihren Auftrag!':'',asset:'',fit:'contain',locked:false};
    blocks.push(b);selected=b.id;render();markDirty();
  }
  function remove(){const b=byId(selected);if(!b||REQUIRED.has(b.kind))return;checkpoint();blocks=blocks.filter(n=>n.id!==selected);selected=null;render();markDirty();}
  function duplicate(){const b=byId(selected);if(!b||blocks.length>=35)return;
    if(!MULTIPLE.has(b.kind)){$('designer-status').textContent='Dieses Pflicht-/Standardfeld ist nur einmal erlaubt.';return;}
    checkpoint();const copy=structuredClone(b);copy.id='b'+Math.random().toString(36).slice(2,12);copy.x+=5;copy.y+=5;bounds(copy);
    blocks.push(copy);selected=copy.id;render();markDirty();
  }
  function undo(){if(!history.length)return;future.push(JSON.stringify(blocks));blocks=JSON.parse(history.pop());selected=byId(selected)?selected:null;render();markDirty();}
  function redo(){if(!future.length)return;history.push(JSON.stringify(blocks));blocks=JSON.parse(future.pop());selected=byId(selected)?selected:null;render();markDirty();}
  $('designer-tools').addEventListener('click',e=>{const btn=e.target.closest('[data-add]');if(btn)add(btn.dataset.add);});
  $('designer-block-list').addEventListener('click',e=>{const btn=e.target.closest('[data-id]');if(btn)select(btn.dataset.id);});
  $('designer-undo').addEventListener('click',undo);$('designer-redo').addEventListener('click',redo);
  $('d-delete').addEventListener('click',remove);$('d-duplicate').addEventListener('click',duplicate);
  $('d-lock').addEventListener('click',()=>{const b=byId(selected);if(!b)return;checkpoint();b.locked=!b.locked;render();markDirty();});
  for(const prop of ['x','y','w','h','size','color','align']){
    $('d-'+prop).addEventListener('change',e=>{
      const b=byId(selected);if(!b)return;
      checkpoint();
      b[prop]=['color','align'].includes(prop)?e.target.value:num(e.target.value);
      if(prop==='size')b.size=clamp(Math.round(b.size),7,36);
      if(['x','y','w','h'].includes(prop))bounds(b);
      render();markDirty();
    });
  }
  $('d-fit').addEventListener('change',e=>{
    const b=byId(selected);if(!b||!['logo','image'].includes(b.kind))return;
    checkpoint();b.fit=e.target.value;render();markDirty();
  });
  $('d-full-width').addEventListener('click',()=>{
    const b=byId(selected);if(!b||!['logo','image'].includes(b.kind))return;
    checkpoint();Object.assign(b,{x:-3,w:216,fit:'cover'});bounds(b);render();markDirty();
  });
  $('d-full-page').addEventListener('click',()=>{
    const b=byId(selected);if(!b||!['logo','image'].includes(b.kind))return;
    checkpoint();Object.assign(b,{x:-3,y:-3,w:216,h:303,fit:'cover'});bounds(b);render();markDirty();
  });
  $('d-text').addEventListener('change',e=>{const b=byId(selected);if(!b||b.kind!=='text')return;checkpoint();b.text=e.target.value.slice(0,600);render();markDirty();});
  function pointerStart(e){
    if(e.button!==0)return;
    const el=e.target.closest('.designer-node');if(!el)return;
    const b=byId(el.dataset.id);if(!b)return;
    select(b.id);if(b.locked)return;
    e.preventDefault();
    const sizing=!!e.target.closest('.designer-resize');
    dragging={id:b.id,px:e.clientX,py:e.clientY,original:{...b},resize:sizing,moved:false};
    el.setPointerCapture(e.pointerId);
  }
  function pointerMove(e){
    if(!dragging)return;
    const b=byId(dragging.id);if(!b)return;
    const rect=paper.getBoundingClientRect();
    const dx=(e.clientX-dragging.px)*210/rect.width;
    const dy=(e.clientY-dragging.py)*297/rect.height;
    if(Math.abs(dx)+Math.abs(dy)<.18&&!dragging.moved)return;
    dragging.moved=true;
    if(dragging.resize){b.w=snap(dragging.original.w+dx);b.h=snap(dragging.original.h+dy);}
    else{b.x=snap(dragging.original.x+dx);b.y=snap(dragging.original.y+dy);}
    bounds(b);
    const el=layer.querySelector(`[data-id="${b.id}"]`);if(el)place(el,b);
    for(const prop of ['x','y','w','h'])$('d-'+prop).value=b[prop];
  }
  function pointerEnd(e){
    if(!dragging)return;
    if(dragging.moved){history.push(JSON.stringify(blocks.map(b=>b.id===dragging.id?dragging.original:b)));if(history.length>80)history.shift();future=[];markDirty();renderList();}
    dragging=null;
  }
  layer.addEventListener('pointerdown',pointerStart);
  layer.addEventListener('pointermove',pointerMove);
  layer.addEventListener('pointerup',pointerEnd);
  layer.addEventListener('pointercancel',pointerEnd);
  layer.addEventListener('dblclick',e=>{const n=e.target.closest('.designer-node');if(n&&byId(n.dataset.id)?.kind==='text'){$('d-text').focus();}});
  document.addEventListener('keydown',e=>{
    const textField=['INPUT','TEXTAREA','SELECT'].includes(e.target.tagName);
    if((e.ctrlKey||e.metaKey)&&!textField && e.key.toLowerCase()==='z'){e.preventDefault();e.shiftKey?redo():undo();return;}
    if((e.ctrlKey||e.metaKey)&&!textField&&e.key.toLowerCase()==='y'){e.preventDefault();redo();return;}
    if(textField)return;
    const b=byId(selected);if(!b)return;
    if(e.key==='Delete'){e.preventDefault();remove();return;}
    const moves={ArrowLeft:['x',-1],ArrowRight:['x',1],ArrowUp:['y',-1],ArrowDown:['y',1]};
    if(!moves[e.key]||b.locked)return;
    e.preventDefault();checkpoint();const [prop,sgn]=moves[e.key];b[prop]+=sgn*(e.shiftKey?5:1);bounds(b);render();markDirty();
  });
  $('d-upload').addEventListener('click',async()=>{
    const b=byId(selected),file=$('d-file').files?.[0];if(!b||b.kind!=='image')return;
    const status=$('d-upload-status');if(!file){status.textContent='Bitte zuerst eine Bilddatei auswählen.';return;}
    if(file.size>4*1024*1024){status.textContent='Bild ist zu gross (max. 4 MB).';return;}
    status.textContent='Bild wird geprüft und gespeichert ...';
    const payload=new FormData();payload.append('_csrf',$('designer-csrf').value);payload.append('image',file);
    try{
      const response=await fetch(SWISS_BASE + '/templates/designer/image',{method:'POST',body:payload});
      if(!response.ok)throw Error('Upload fehlgeschlagen (HTTP '+response.status+').');
      const data=await response.json();if(!/^[a-f0-9]{32}\.jpg$/.test(data.asset))throw Error('Ungültige Bildantwort.');
      checkpoint();b.asset=data.asset;render();markDirty();status.textContent='Bild hochgeladen. Bitte Vorlage speichern.';
    }catch(err){status.textContent=err.message||'Upload fehlgeschlagen.';}
  });
  form.addEventListener('submit',e=>{
    const saveAs=e.submitter?.id==='designer-save-as';
    if(saveAs&&!$('designer-template-name').value.trim()){
      e.preventDefault();$('designer-template-name').focus();$('designer-status').textContent='Bitte zuerst einen Vorlagennamen eingeben.';return;
    }
    $('designer-layout-json').value=JSON.stringify({version:1,blocks});
    if(e.submitter?.id!=='designer-pdf-preview')setClean();
  });
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  // An unsaved draft can be inspected without enabling the layout. Server previews force visual mode.
  render();
})();
