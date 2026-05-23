/*
 * Tiny CSV parser used by PartyImportDialog.
 *
 * Why hand-rolled: the project doesn't bundle papaparse and pulling it
 * in for a single dialog is overkill. The grammar we support is the
 * RFC-4180 happy path:
 *
 *   - Comma delimiter.
 *   - Optional double-quoted fields.
 *   - `""` inside a quoted field encodes a literal `"`.
 *   - `\n` or `\r\n` row terminators. `\r` alone is treated as a row
 *     terminator too — Excel-on-Mac legacy file quirk.
 *
 * Out of scope (will throw / silently misparse):
 *   - Alternative delimiters (semicolon, tab) — operators are told to
 *     export from Vyapar / Excel as standard CSV.
 *   - Embedded BOM is stripped from the first character only.
 *
 * The header row is always required. Rows with fewer cells than the
 * header are right-padded with empty strings; rows with more cells
 * have their tail dropped (with a console warning during dev). That's
 * forgiving enough for hand-edited CSVs.
 */

export interface ParsedCsv {
  headers: string[];
  /** One object per data row, keyed by header. */
  rows: Array<Record<string, string>>;
}

export function parseCsv(text: string): ParsedCsv {
  // Strip UTF-8 BOM if present.
  let src = text;
  if (src.charCodeAt(0) === 0xfeff) src = src.slice(1);

  const records = tokenize(src);
  if (records.length === 0) {
    return { headers: [], rows: [] };
  }

  const headers = records[0].map((h) => h.trim());
  const rows: Array<Record<string, string>> = [];

  for (let i = 1; i < records.length; i++) {
    const r = records[i];
    // Skip wholly-empty rows (common trailing-newline artifact).
    if (r.length === 1 && r[0] === '') continue;
    if (r.length === 0) continue;
    const obj: Record<string, string> = {};
    for (let j = 0; j < headers.length; j++) {
      obj[headers[j]] = r[j] ?? '';
    }
    rows.push(obj);
  }

  return { headers, rows };
}

/**
 * Walk the source character-by-character into a list of records, each
 * a list of fields. The state machine has two states: in-quotes and
 * not-in-quotes. `""` inside quotes emits a literal `"`. A bare quote
 * at field-start opens quotes; a quote in unquoted mode is treated as
 * literal data (Excel does this too).
 */
function tokenize(src: string): string[][] {
  const records: string[][] = [];
  let field = '';
  let row: string[] = [];
  let inQuotes = false;
  let i = 0;

  while (i < src.length) {
    const c = src[i];

    if (inQuotes) {
      if (c === '"') {
        if (src[i + 1] === '"') {
          field += '"';
          i += 2;
          continue;
        }
        inQuotes = false;
        i++;
        continue;
      }
      field += c;
      i++;
      continue;
    }

    if (c === '"' && field === '') {
      inQuotes = true;
      i++;
      continue;
    }
    if (c === ',') {
      row.push(field);
      field = '';
      i++;
      continue;
    }
    if (c === '\r') {
      // Treat \r\n and bare \r as one row terminator.
      row.push(field);
      records.push(row);
      row = [];
      field = '';
      i++;
      if (src[i] === '\n') i++;
      continue;
    }
    if (c === '\n') {
      row.push(field);
      records.push(row);
      row = [];
      field = '';
      i++;
      continue;
    }
    field += c;
    i++;
  }

  // Final field (no trailing newline case).
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    records.push(row);
  }

  return records;
}
