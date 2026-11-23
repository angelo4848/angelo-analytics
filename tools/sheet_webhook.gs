/**
 * A. Analytics – recibe los picks del bot de tenis y los apunta en la pestaña "Scan 1.er set".
 *
 * Cómo ponerlo (una sola vez):
 *  1. Abre tu Google Sheet "A. Analytics" -> Extensiones -> Apps Script.
 *  2. Borra lo que haya, pega TODO este archivo y cambia la CLAVE de abajo por una tuya.
 *  3. Guardar -> Implementar -> Nueva implementación -> tipo "Aplicación web".
 *       Ejecutar como: Yo      ·      Quién tiene acceso: Cualquier usuario
 *  4. Autoriza, copia la URL que termina en /exec y ponla en bot_config.txt:
 *       SHEET_WEBHOOK=https://script.google.com/macros/s/.../exec
 *       SHEET_SECRET=la misma clave que pusiste aquí
 */
const CLAVE = 'cambia-esta-clave';
const TAB = 'Scan 1.er set';
const HEAD = ['Id', 'Fecha', 'Hora', 'Circuito', 'Torneo', 'Favorito', 'Rival', 'Prob. SofaScore', 'Prob. TNNS',
              'Cuota partido', 'Cuota 1.er set', 'Marcador al enviar', 'Pick', 'Resultado 1.er set', 'Acierto'];

function hoja_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(TAB);
  if (!sh) {
    sh = ss.insertSheet(TAB);
    sh.appendRow(HEAD);
    sh.getRange(1, 1, 1, HEAD.length).setFontWeight('bold').setBackground('#0b1f3a').setFontColor('#ffffff');
    sh.setFrozenRows(1);
    sh.getRange('A:A').setNumberFormat('@');
  }
  return sh;
}

function colorea_(sh, r, acierto) {
  const c = acierto === 'Ganado' ? '#c8f7c5' : acierto === 'Perdido' ? '#f7c5c5' : acierto === 'Anulado' ? '#eeeeee' : null;
  if (c) sh.getRange(r, HEAD.indexOf('Acierto') + 1).setBackground(c);
}

function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  if (d.secret !== CLAVE) return salida_({ ok: false, error: 'clave' });
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = hoja_();
    const vals = HEAD.map(h => (d.row && d.row[h] !== undefined) ? d.row[h] : '');
    const ids = sh.getRange(1, 1, sh.getLastRow(), 1).getValues().map(x => String(x[0]));
    const id = String(d.id || (d.row && d.row.Id) || '');
    let r = ids.indexOf(id) + 1;
    if (r < 2) {                     // fila nueva
      sh.appendRow(vals);
      r = sh.getLastRow();
    } else {                         // actualizar resultado
      sh.getRange(r, 1, 1, HEAD.length).setValues([vals]);
    }
    colorea_(sh, r, d.row && d.row['Acierto']);
    return salida_({ ok: true });
  } finally {
    lock.releaseLock();
  }
}

function salida_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
