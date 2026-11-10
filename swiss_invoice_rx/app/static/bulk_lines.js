'use strict';
/* Reine, lokal ausgefuehrte Excel-/CSV-Zeilenpruefung. Keine Netzwerkzugriffe. */
(function () {
  function cells(line, separator) {
    const values = [];
    let current = '', quoted = false;
    for (let i = 0; i < line.length; i++) {
      const c = line[i];
      if (c === '"') {
        if (quoted && line[i + 1] === '"') { current += '"'; i++; }
        else quoted = !quoted;
      } else if (c === separator && !quoted) { values.push(current.trim()); current = ''; }
      else current += c;
    }
    if (quoted) throw new Error('Ein Textfeld hat ein nicht geschlossenes Anfuehrungszeichen.');
    values.push(current.trim());
    return values;
  }
  function number(value, name, row, decimals, max, allowNegative) {
    let v = String(value).trim().replace(/[\u00a0\u202f'’\s]/g, '');
    if (v.includes('.') && v.includes(',')) {
      const comma = v.lastIndexOf(',') > v.lastIndexOf('.');
      v = comma ? v.replaceAll('.', '').replace(',', '.') : v.replaceAll(',', '');
    } else v = v.replace(',', '.');
    if (!new RegExp('^' + (allowNegative ? '-?' : '') + '\\d+(?:\\.\\d{1,' + decimals + '})?$').test(v))
      throw new Error('Zeile ' + row + ': ' + name + ' ist keine gueltige Zahl (max. ' + decimals + ' Nachkommastellen).');
    const n = Number(v);
    if (!Number.isFinite(n) || Math.abs(n) > max || (allowNegative ? n === 0 : n < 0))
      throw new Error('Zeile ' + row + ': ' + name + ' liegt ausserhalb des gueltigen Bereichs.');
    return String(n);
  }
  function parse(source, kind, defaultTax) {
    if (typeof source !== 'string' || !source.trim()) throw new Error('Bitte zuerst Excel-Zeilen einfuegen.');
    if (source.length > 25000) throw new Error('Zu viele Daten: maximal 25.000 Zeichen.');
    const sep = source.includes('\t') ? '\t' : ';';
    const input = source.replace(/\r\n?/g, '\n').split('\n');
    const result = [];
    for (let i = 0; i < input.length; i++) {
      if (!input[i].trim()) continue;
      const parts = cells(input[i], sep);
      if (i === 0 && /^(beschreibung|artikel|leistung)$/i.test(parts[0]) && /^menge$/i.test(parts[1] || '')) continue;
      if (parts.length < 3 || parts.length > 6)
        throw new Error('Zeile ' + (i + 1) + ': Bitte 3 bis 6 Spalten (Beschreibung, Menge, [Einheit], Preis, [MWST], [Rabatt]) verwenden.');
      const description = parts[0].trim();
      if (!description || description.length > 1000)
        throw new Error('Zeile ' + (i + 1) + ': Beschreibung fehlt oder ist laenger als 1.000 Zeichen.');
      const hasUnit = parts.length >= 4;
      const unit = hasUnit ? parts[2] || 'Stk.' : 'Stk.';
      if (unit.length > 20) throw new Error('Zeile ' + (i + 1) + ': Einheit ist zu lang.');
      const qty = number(parts[1], 'Menge', i + 1, 3, 1000000, kind === 'credit');
      if (kind !== 'credit' && Number(qty) <= 0)
        throw new Error('Zeile ' + (i + 1) + ': Menge muss positiv sein.');
      const price = number(parts[hasUnit ? 3 : 2], 'Preis', i + 1, 2, 999999999, false);
      const tax = number(parts[4] || defaultTax || '0', 'MWST', i + 1, 2, 100, false);
      const discount = number(parts[5] || '0', 'Rabatt', i + 1, 2, 100, false);
      result.push({ description, qty, unit, price, tax, discount });
      if (result.length > 150) throw new Error('Maximal 150 Positionen pro Rechnung.');
    }
    if (!result.length) throw new Error('Keine gueltigen Positionen gefunden.');
    return result;
  }
  const api = {parse, cells};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof window !== 'undefined') window.HelveticBulk = api;
})();
