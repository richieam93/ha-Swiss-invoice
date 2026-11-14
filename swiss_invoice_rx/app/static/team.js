(() => {
  'use strict';
  const selector = document.querySelector('#team-role');
  const help = document.querySelector('#team-role-help');
  if (!selector || !help) return;
  const own = document.querySelector('#team-own-company');
  const companyFields = document.querySelector('#team-assign-fields');
  const submit = document.querySelector('#team-create-submit');
  function updateOwnMode() {
    if (!own || !companyFields) return;
    const isolated = own.checked;
    companyFields.hidden = isolated;
    companyFields.querySelectorAll('input, select').forEach(field => { field.disabled = isolated; });
    if (submit) submit.textContent = isolated ? 'Benutzer für eigene Einrichtung erstellen' : 'Benutzer erstellen / zuordnen';
  }
  if (own) { own.addEventListener('change', updateOwnMode); updateOwnMode(); }
  const explanations = {
    admin: 'Geschäftsleitung darf Rechnungen, Kunden, Artikel, Zahlungen, Vorlagen, Firmeneinstellungen und Benutzer dieses Geschäfts verwalten. Kein Zugriff auf andere Geschäfte oder Gesamtbackups.',
    editor: 'Mitarbeiter darf Rechnungen, Kunden, Artikel und Zahlungen bearbeiten. Firmeneinstellungen und Benutzerverwaltung sind geschützt.',
    viewer: 'Leser darf Informationen und Rechnungen ansehen, aber nichts verändern.'
  };
  selector.addEventListener('change', () => { help.textContent = explanations[selector.value] || ''; });
})();
