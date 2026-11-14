(() => {
  'use strict';
  const form = document.querySelector('#onboard-form');
  if (!form) return;
  const steps = Array.from(form.querySelectorAll('.onboard-step'));
  const previous = document.querySelector('#onboard-back');
  const next = document.querySelector('#onboard-next');
  const finish = document.querySelector('#onboard-finish');
  const progress = document.querySelector('#onboard-progress');
  const bar = document.querySelector('#onboard-progress-bar');
  const vat = document.querySelector('#onboard-tax');
  const vatBox = document.querySelector('#onboard-tax-box');
  const vatDetails = document.querySelector('#onboard-tax-details');
  const logoInput = document.querySelector('#onboard-logo');
  const logoPreview = document.querySelector('#onboard-logo-preview');
  let current = 0;
  let logoUrl = null;
  function privateSelected() { return form.querySelector('input[name="business_type"]:checked')?.value === 'private'; }
  function updateTax() {
    const isPrivate = privateSelected();
    if (vat) { vat.checked = isPrivate ? false : vat.checked; vat.disabled = isPrivate; }
    if (vatBox) vatBox.classList.toggle('is-private', isPrivate);
    if (vatDetails) vatDetails.hidden = !(vat && vat.checked);
  }
  function render() {
    steps.forEach((step, ix) => { step.hidden = ix !== current; });
    previous.hidden = current === 0;
    next.hidden = current === steps.length - 1;
    finish.hidden = current !== steps.length - 1;
    if (progress) progress.textContent = `Schritt ${current + 1} von ${steps.length}`;
    if (bar) bar.style.width = `${(current + 1) * 100 / steps.length}%`;
    updateTax();
  }
  function checkStep() {
    const password = form.querySelector('[name="password_new"]');
    const confirm = form.querySelector('[name="password_confirm"]');
    if (current === 2 && password && confirm) {
      confirm.setCustomValidity(password.value !== confirm.value ? 'Die Passwörter stimmen nicht überein.' : '');
    }
    for (const input of steps[current].querySelectorAll('input, select')) {
      if (!input.checkValidity()) { input.reportValidity(); return false; }
    }
    return true;
  }
  next?.addEventListener('click', () => { if (checkStep() && current < steps.length - 1) { current++; render(); } });
  previous?.addEventListener('click', () => { if (current > 0) { current--; render(); } });
  form.querySelectorAll('input[name="business_type"]').forEach(input => input.addEventListener('change', updateTax));
  vat?.addEventListener('change', updateTax);
  form.querySelector('[name="password_confirm"]')?.addEventListener('input', event => event.target.setCustomValidity(''));
  form.querySelector('[name="password_new"]')?.addEventListener('input', () => form.querySelector('[name="password_confirm"]')?.setCustomValidity(''));
  form.addEventListener('submit', event => {
    for (let ix = 0; ix < steps.length; ix++) {
      for (const input of steps[ix].querySelectorAll('input, select')) {
        if (!input.checkValidity()) { event.preventDefault(); current = ix; render(); input.reportValidity(); return; }
      }
    }
  });
  logoInput?.addEventListener('change', () => {
    if (logoUrl) URL.revokeObjectURL(logoUrl);
    logoUrl = null;
    const file = logoInput.files?.[0];
    if (!file) { logoPreview.innerHTML = '<span>Geschäftslogo</span>'; return; }
    if (file.size > 5 * 1024 * 1024) { window.alert('Maximal 5 MB erlaubt'); logoInput.value = ''; return; }
    logoUrl = URL.createObjectURL(file);
    const img = document.createElement('img');
    img.src = logoUrl; img.alt = 'Vorschau des Logos';
    logoPreview.replaceChildren(img);
  });
  render();
})();
