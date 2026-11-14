'use strict';
(() => {
  const form=document.getElementById('settings-form');
  if (!form) return;
  const year=form.dataset.year;
  const kinds={invoice:['number_prefix','next_invoice'],quote:['quote_prefix','next_quote'],credit:['credit_prefix','next_credit']};
  function updateNumbers() {
    const padding=Math.max(3,Math.min(9,Number(form.elements.number_padding.value)||5));
    Object.entries(kinds).forEach(([kind,fields]) => {
      const prefix=form.elements[fields[0]].value.trim().toUpperCase()||'?';
      const counter=Math.max(1,Number(form.elements[fields[1]].value)||1);
      const element=form.querySelector(`[data-num-preview="${kind}"]`);
      if(element)element.textContent=`${prefix}-${year}-${String(counter).padStart(padding,'0')}`;
    });
  }
  ['number_prefix','quote_prefix','credit_prefix','next_invoice','next_quote','next_credit','number_padding'].forEach(name => {
    form.elements[name]?.addEventListener('input',updateNumbers);
    form.elements[name]?.addEventListener('change',updateNumbers);
  });
})();

// MWST nur für registrierte Unternehmen aktivieren; die übrigen Daten bleiben editierbar.
(() => {
  const toggle=document.getElementById('settings-tax-toggle');
  const panel=document.getElementById('settings-default-tax');
  if(!toggle||!panel)return;
  const apply=()=>{panel.hidden=!toggle.checked;};
  toggle.addEventListener('change',apply);apply();
})();
