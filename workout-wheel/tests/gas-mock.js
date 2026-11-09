// A tiny in-memory stand-in for the Google Apps Script services Code.gs uses,
// so the real backend code can be tested without Google.
import fs from 'node:fs';
import vm from 'node:vm';
import crypto from 'node:crypto';

export function loadBackend() {
  const sheets = new Map();
  const files = [];
  const props = {};

  const makeSheet = (name) => {
    const rows = [];          // 2D array of values
    let maxRows = 1000;
    const sh = {
      name,
      rows,
      getLastRow: () => rows.length,
      getMaxRows: () => maxRows,
      getMaxColumns: () => 26,
      insertRowsAfter: (_, n) => { maxRows += n; },
      setFrozenRows() {},
      getDataRange: () => sh.getRange(1, 1, Math.max(1, rows.length), Math.max(1, ...rows.map((r) => r.length))),
      getRange(r, c, nr = 1, nc = 1) {
        if (r + nr - 1 > maxRows) throw new Error('Range out of bounds');
        const range = {
          setNumberFormat: () => range,
          setFontWeight: () => range,
          getValues: () => Array.from({ length: nr }, (_, i) =>
            Array.from({ length: nc }, (_, j) => rows[r - 1 + i]?.[c - 1 + j] ?? '')),
          setValues(vals) {
            vals.forEach((row, i) => {
              while (rows.length < r + i) rows.push([]);
              row.forEach((v, j) => { rows[r - 1 + i][c - 1 + j] = v; });
            });
            return range;
          },
        };
        return range;
      },
    };
    return sh;
  };

  const ss = {
    getSheetByName: (n) => sheets.get(n) ?? null,
    insertSheet: (n) => { const s = makeSheet(n); sheets.set(n, s); return s; },
    deleteSheet: (s) => sheets.delete(s.name),
  };
  sheets.set('Sheet1', makeSheet('Sheet1'));

  const ctx = {
    SpreadsheetApp: { getActive: () => ss },
    LockService: { getScriptLock: () => ({ waitLock() {}, releaseLock() {} }) },
    Utilities: {
      getUuid: () => crypto.randomUUID(),
      base64Decode: (b) => [...Buffer.from(b, 'base64')],
      newBlob: (bytes, type, name) => ({ bytes, type, name }),
      formatDate: (d) => d.toISOString().slice(0, 10),
    },
    Session: { getScriptTimeZone: () => 'UTC' },
    PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => props[k] ?? null, setProperty: (k, v) => { props[k] = v; } }) },
    DriveApp: {
      Access: { ANYONE_WITH_LINK: 'link' }, Permission: { VIEW: 'view' },
      createFolder: () => ({ getId: () => 'folder1' }),
      getFolderById: () => ({
        createFile: (blob) => {
          const f = { id: `file${files.length + 1}`, blob, sharing: null };
          files.push(f);
          return { getId: () => f.id, setSharing: (a) => { f.sharing = a; } };
        },
      }),
    },
    ContentService: {
      MimeType: { JSON: 'json' },
      createTextOutput: (content) => ({ content, setMimeType() { return this; } }),
    },
    Logger: { log() {} },
  };
  vm.createContext(ctx);
  const code = fs.readFileSync(new URL('../google-sheets/Code.gs', import.meta.url), 'utf8');
  vm.runInContext(code, ctx);

  const post = (body) => JSON.parse(ctx.doPost({ postData: { contents: JSON.stringify(body) } }).content);
  return { ctx, sheets, files, post };
}
