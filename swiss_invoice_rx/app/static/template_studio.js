const SWISS_BASE = document.querySelector('meta[name="swiss-invoice-base"]')?.getAttribute('content') || '';
'use strict';
(() => {
  const form = document.getElementById('template-studio');
  const paper = document.getElementById('invoice-preview');
  if (!form || !paper) return;
  const $ = id => document.getElementById(id);
  const state = $('studio-state');
  let changed = false;
  function render() {
    const color = $('tpl-color').value;
    const style = $('tpl-style').value;
    paper.dataset.style = style;
    paper.dataset.density = $('tpl-density').value;
    paper.dataset.header = $('tpl-header').value;
    paper.dataset.table = $('tpl-table').value;
    paper.style.setProperty('--studio-body-size', (Number($('tpl-body').value)+1)+'px');
    const logoWidth=Math.max(30,Number($('tpl-logo-size').value)||110);
    paper.style.setProperty('--studio-logo-width', (logoWidth*1.08)+'px');
    const previewLogo=$('studio-logo');
    if(previewLogo){
      previewLogo.style.width=(logoWidth*1.08)+'px';
      previewLogo.style.height=(Math.max(5,Number($('tpl-logo-height').value)||19)*2.6)+'px';
      previewLogo.style.maxWidth='none';previewLogo.style.maxHeight='none';
      previewLogo.style.objectFit=$('tpl-logo-fit').value;
      previewLogo.style.transform='translate('+((Number($('tpl-logo-x').value)||0)-15)*2.6+'px,'+((Number($('tpl-logo-y').value)||0)-16)*2.6+'px)';
    }
    paper.style.setProperty('--studio-accent', style === 'modern' ? color : '#25354a');
    const kind = $('tpl-preview-kind').value;
    $('preview-title').textContent = kind === 'invoice' ? ($('tpl-title').value.trim() || 'Rechnung') :
      (kind === 'quote' ? 'Offerte' : 'Gutschrift');
    $('preview-title').style.fontSize = (Number($('tpl-size').value) * 0.9) + 'px';
    $('preview-footer').textContent = $('tpl-footer').value || 'Vielen Dank fuer Ihren Auftrag.';
    $('preview-notes').textContent = $('tpl-default-notes').value || 'Vielen Dank fuer Ihren Auftrag.';
    $('preview-customer-email').hidden = !$('tpl-customer-email').checked;
    $('preview-service').hidden = !$('tpl-service').checked;
    // This sample has one tax rate. With several rates the PDF always itemizes each.
    const rate = Number(paper.dataset.taxRate) || 0;
    const currency = paper.dataset.currency || 'CHF';
    const format = number => (Math.round((number + Number.EPSILON) * 100)/100).toFixed(2);
    const tax = Math.round((295 * rate / 100 + Number.EPSILON) * 100)/100;
    $('preview-subtotal').textContent = currency+' 295.00';
    $('preview-tax').firstChild.textContent = ($('tpl-tax').checked ? 'MWST ' : 'MWST gesamt (')+rate+' %'+($('tpl-tax').checked ? ' ' : ') ');
    $('preview-tax-amount').textContent = currency+' '+format(tax);
    $('preview-grand-total').textContent = currency+' '+format(295+tax);
    $('preview-terms').hidden = !$('tpl-terms').checked || kind !== 'invoice';
    $('preview-pages').hidden = !$('tpl-pages').checked;
    const logo = $('studio-logo');
    if (logo) logo.hidden = !$('tpl-logo').checked;
    $('studio-wordmark').hidden = Boolean(logo && $('tpl-logo').checked);
  }
  function markDirty() {
    changed = true;
    state.textContent = 'Noch nicht gespeichert';
    state.classList.add('is-dirty');
    render();
  }
  form.addEventListener('input', markDirty);
  form.addEventListener('change', markDirty);
  // Choosing another preview type does not modify the design itself.
  $('tpl-preview-kind').addEventListener('change', render);
  const presets = {
    business: { 'tpl-style':'modern','tpl-color':'#2563eb','tpl-header':'standard',
      'tpl-density':'normal','tpl-table':'lines','tpl-body':'9','tpl-size':'26' },
    elegant: { 'tpl-style':'modern','tpl-color':'#0f766e','tpl-header':'mirrored',
      'tpl-density':'spacious','tpl-table':'zebra','tpl-body':'10','tpl-size':'30' },
    simple: { 'tpl-style':'minimal','tpl-color':'#334155','tpl-header':'standard',
      'tpl-density':'compact','tpl-table':'clean','tpl-body':'9','tpl-size':'22' }
  };
  form.querySelectorAll('[data-preset]').forEach(btn => btn.addEventListener('click', () => {
    Object.entries(presets[btn.dataset.preset] || {}).forEach(([id,value]) => { $(id).value = value; });
    markDirty();
  }));
  document.querySelectorAll('form[action$="/templates/activate"]').forEach(item => item.addEventListener('submit', event => {
    if (changed && !window.confirm('Ungespeicherte Aenderungen verwerfen und Vorlage wechseln?')) {
      event.preventDefault();
    }
  }));
  document.querySelectorAll('form[data-confirm]').forEach(item => item.addEventListener('submit', event => {
    if (!window.confirm(item.dataset.confirm)) event.preventDefault();
  }));
  form.querySelectorAll('[data-accent]').forEach(btn => {
    btn.addEventListener('click', () => {
      $('tpl-color').value = btn.dataset.accent;
      markDirty();
    });
  });
  $('studio-undo').addEventListener('click', () => {
    form.reset();
    changed = false;
    state.textContent = 'Gespeichert';
    state.classList.remove('is-dirty');
    render();
  });
  form.addEventListener('submit', event => {
    if (event.submitter?.id === 'studio-save-as' && !$('tpl-name').value.trim()) {
      event.preventDefault();
      $('tpl-name').focus();
      state.textContent = 'Bitte einen Vorlagennamen eingeben';
      state.classList.add('is-dirty');
      return;
    }
    if (event.submitter?.id === 'studio-save') {
      changed = false;
    }
  });
  render();
})();
