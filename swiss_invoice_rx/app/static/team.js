(() => {
  'use strict';
  const selector = document.querySelector('#team-role');
  const help = document.querySelector('#team-role-help');
  if (!selector || !help) return;
  const explanations = {
    admin: 'Geschäftsleitung darf Rechnungen, Kunden, Artikel, Zahlungen, Vorlagen, Firmeneinstellungen und Benutzer dieses Geschäfts verwalten. Kein Zugriff auf andere Geschäfte oder Gesamtbackups.',
    editor: 'Mitarbeiter darf Rechnungen, Kunden, Artikel und Zahlungen bearbeiten. Firmeneinstellungen und Benutzerverwaltung sind geschützt.',
    viewer: 'Leser darf Informationen und Rechnungen ansehen, aber nichts verändern.'
  };
  selector.addEventListener('change', () => { help.textContent = explanations[selector.value] || ''; });
})();
