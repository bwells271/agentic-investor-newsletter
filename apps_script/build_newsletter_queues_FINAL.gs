/**
 * build_newsletter_queues.gs
 *
 * Same job as v1, rewritten around the Sheets REST API instead of SpreadsheetApp.
 *
 * v1 was slow for one reason: SpreadsheetApp.openById() loads the whole document
 * model, and the master sheet is ~28 MB because Full Text holds entire articles.
 * Opening it can take minutes before any row is read.
 *
 * This version never opens the master as a document. It pulls ranges over the
 * REST API, which reads cells directly:
 *
 *   call 1  four filter columns (Pitch Date, Total Score, Special Situation?,
 *           Date Ingested) across all rows
 *   call 2  one batchGet carrying two ranges per winning row, skipping column E
 *
 * Two reads total instead of a hundred, and Full Text is never transferred.
 *
 * SETUP: enable the advanced service first, or every run dies with
 * "ReferenceError: Sheets is not defined".
 *   Editor sidebar -> Services -> + -> Google Sheets API -> Add
 *
 * READ-ONLY against the master sheet. Output goes to a separate spreadsheet.
 */

// ── Config ───────────────────────────────────────────────────────────────────

var MASTER_ID = '1K2qhuVaSp-G0iCEplsqVVD0-oTykM-meMhL1bkg5Yxc';
var MASTER_TAB = 'Sheet1';

// Destination created by the first run. Keep this filled in so later runs reuse
// the same file instead of creating a new one each time.
var DEST_ID = '1-lNEktaNdLHFuDAMxM3q_rB6o6oRpFn6X5tWnjaW4V8';

var DAYS = 7;
var LIMIT = 50;

// One-off backfill switch.
//
// Only two rows currently carry a date, because the Pitch Date and Date Ingested
// columns were added recently. Widening DAYS does not help: an undated row fails
// the date test no matter how far back the window reaches. Set this to true to
// skip the date test entirely and rank the whole sheet by Total Score, which is
// how you get a realistic 50-row queue to test against.
//
// Set it back to false before installing the weekly trigger. A backfill must
// never go out as a weekly issue.
var IGNORE_DATES = false;

// Output layout. Column E (Full Text) is absent on purpose.
// Each entry is [heading, 0-based index into the assembled row].
var OUTPUT = [
  ['Company Name',       0],   // A
  ['Ticker',             1],   // B
  ['Link',               2],   // C
  ['Pitch Date',         3],   // D
  ['Brief Summary',      4],   // F
  ['Total Score',        5],   // Q
  ['Total Evaluation',   6],   // R
  ['Special Situation?', 7],   // S
  ['No-Brainer?',        8],   // T
  ['Notes',              9],   // U
  ['Date Ingested',     10],   // V
  ['_pitch_id',         11]    // W
];

// ── Entry point ──────────────────────────────────────────────────────────────

function buildNewsletterQueues() {
  var started = new Date();

  // One call for the four columns that decide which rows qualify.
  var filters = Sheets.Spreadsheets.Values.batchGet(MASTER_ID, {
    ranges: [
      MASTER_TAB + '!D2:D',   // Pitch Date
      MASTER_TAB + '!Q2:Q',   // Total Score
      MASTER_TAB + '!S2:S',   // Special Situation?
      MASTER_TAB + '!V2:V'    // Date Ingested
    ],
    majorDimension: 'COLUMNS',
    valueRenderOption: 'FORMATTED_VALUE'
  }).valueRanges;

  var pitchDates = col(filters[0]);
  var scores     = col(filters[1]);
  var special    = col(filters[2]);
  var ingested   = col(filters[3]);

  var n = Math.max(pitchDates.length, scores.length, special.length, ingested.length);
  Logger.log('Rows scanned: ' + n + ' (' + secs(started) + 's elapsed)');

  var cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - DAYS);
  cutoff.setHours(0, 0, 0, 0);
  var windowEnd = new Date();
  windowEnd.setHours(0, 0, 0, 0);

  var candidates = [];
  for (var i = 0; i < n; i++) {
    // Date Ingested wins, Pitch Date is the fallback, undated rows are skipped
    // so the pre-August-2026 backlog is never republished.
    var when = parseDate(ingested[i]) || parseDate(pitchDates[i]);
    if (!IGNORE_DATES && (!when || when < cutoff)) continue;

    var score = parseFloat(scores[i]);
    candidates.push({
      row: i + 2,
      score: isNaN(score) ? -1 : score,
      isSpecial: /^y(es)?$/i.test(String(special[i] || '').trim())
    });
  }

  candidates.sort(function (a, b) { return b.score - a.score; });

  var allSpecials = candidates.filter(function (c) { return c.isSpecial; });
  var specials = allSpecials.slice(0, LIMIT);
  var pitches  = candidates.slice(0, LIMIT);

  Logger.log((IGNORE_DATES ? 'BACKFILL (dates ignored): ' : 'In window: ') + candidates.length +
             ' | specials: ' + specials.length +
             ' | pitches: ' + pitches.length);

  // Fetch both queues' rows in a single batchGet.
  var wanted = dedupeRows(specials.concat(pitches));
  var rowData = fetchRows(wanted);

  var dest = openDestination();
  writeQueue(dest, 'Special Situations Queue', specials, rowData);
  writeQueue(dest, 'Stock Pitches Queue',      pitches,  rowData);
  writeStatus(dest, {
    scanned: n,
    inWindow: candidates.length,
    specialsAvailable: allSpecials.length,
    specialsQueued: specials.length,
    pitchesQueued: pitches.length,
    cutoff: cutoff,
    windowEnd: windowEnd,
    elapsed: secs(started)
  });

  Logger.log('Destination: ' + dest.getUrl());
  Logger.log('Destination ID: ' + dest.getId());
  Logger.log('Done in ' + secs(started) + 's');
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function col(valueRange) {
  var v = valueRange && valueRange.values;
  return (v && v[0]) ? v[0] : [];
}

function secs(started) {
  return Math.round((new Date() - started) / 100) / 10;
}

function dedupeRows(picks) {
  var seen = {}, out = [];
  picks.forEach(function (p) {
    if (!seen[p.row]) { seen[p.row] = true; out.push(p.row); }
  });
  return out;
}

/**
 * Two ranges per row (A:D and F:W) so column E is never transferred.
 * Returns {rowNumber: [12 values in OUTPUT order]}.
 */
function fetchRows(rows) {
  var out = {};
  if (!rows.length) return out;

  var ranges = [];
  rows.forEach(function (r) {
    ranges.push(MASTER_TAB + '!A' + r + ':D' + r);
    ranges.push(MASTER_TAB + '!F' + r + ':W' + r);
  });

  // batchGet caps out well above this, but chunk anyway so an unusually busy
  // week cannot blow the request size.
  var CHUNK = 100;
  for (var start = 0; start < ranges.length; start += CHUNK) {
    var slice = ranges.slice(start, start + CHUNK);
    var res = Sheets.Spreadsheets.Values.batchGet(MASTER_ID, {
      ranges: slice,
      majorDimension: 'ROWS',
      valueRenderOption: 'FORMATTED_VALUE'
    }).valueRanges;

    for (var j = 0; j < res.length; j += 2) {
      var rowNum = rows[(start + j) / 2];
      var ad = firstRow(res[j]);      // A,B,C,D
      var fw = firstRow(res[j + 1]);  // F..W  (F,G..P,Q,R,S,T,U,V,W)

      out[rowNum] = [
        pick(ad, 0),   // A Company Name
        pick(ad, 1),   // B Ticker
        pick(ad, 2),   // C Link
        pick(ad, 3),   // D Pitch Date
        pick(fw, 0),   // F Brief Summary
        pick(fw, 11),  // Q Total Score
        pick(fw, 12),  // R Total Evaluation
        pick(fw, 13),  // S Special Situation?
        pick(fw, 14),  // T No-Brainer?
        pick(fw, 15),  // U Notes
        pick(fw, 16),  // V Date Ingested
        pick(fw, 17)   // W _pitch_id
      ];
    }
  }
  return out;
}

function firstRow(valueRange) {
  var v = valueRange && valueRange.values;
  return (v && v[0]) ? v[0] : [];
}

function pick(arr, i) {
  return (arr[i] == null) ? '' : String(arr[i]);
}

function parseDate(raw) {
  var s = String(raw == null ? '' : raw).trim();
  if (!s || /^n\.?a\.?$/i.test(s) || s === '-') return null;

  var iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return new Date(+iso[1], +iso[2] - 1, +iso[3]);

  var parsed = new Date(s);
  return isNaN(parsed.getTime()) ? null : parsed;
}

function openDestination() {
  if (DEST_ID) return SpreadsheetApp.openById(DEST_ID);
  var created = SpreadsheetApp.create('Agentic Investor — Newsletter Queues');
  Logger.log('Created destination. Paste this into DEST_ID: ' + created.getId());
  return created;
}

function writeQueue(dest, tabName, picks, rowData) {
  var sheet = dest.getSheetByName(tabName);
  if (!sheet) { sheet = dest.insertSheet(tabName); } else { sheet.clear(); }

  var header = OUTPUT.map(function (c) { return c[0]; });
  var rows = [header];

  picks.forEach(function (p) {
    var vals = rowData[p.row];
    if (!vals) return;
    rows.push(OUTPUT.map(function (c) { return vals[c[1]]; }));
  });

  sheet.getRange(1, 1, rows.length, header.length).setValues(rows);
  sheet.setFrozenRows(1);
}

function writeStatus(dest, info) {
  var sheet = dest.getSheetByName('Status') || dest.insertSheet('Status');
  sheet.clear();

  // Window Start and Window End are read by the newsletter renderer, which
  // titles each issue with the period it covers. Without them it can only print
  // the day it ran, which tells the reader nothing about what is inside.
  //
  // The overflow rows matter for a different reason: a week with more than
  // LIMIT qualifying pitches loses the remainder for good, because next week's
  // window has already moved past them. Silent truncation would look identical
  // to a quiet week, so it is written down.
  var fmt = function (d) {
    return Utilities.formatDate(d, Session.getScriptTimeZone() || 'America/New_York', 'yyyy-MM-dd');
  };
  var na = IGNORE_DATES ? 'n/a (backfill)' : null;

  sheet.getRange(1, 1, 12, 2).setValues([
    ['Last refreshed', new Date().toISOString()],
    ['Mode', IGNORE_DATES ? 'BACKFILL - dates ignored' : 'Normal - last ' + DAYS + ' days'],
    ['Window Start', na || fmt(info.cutoff)],
    ['Window End', na || fmt(info.windowEnd)],
    ['Window (days)', na || DAYS],
    ['Rows scanned', info.scanned],
    ['Pitches in window', info.inWindow],
    ['Special Situations queued', info.specialsQueued],
    ['Special Situations available', info.specialsAvailable],
    ['Stock Pitches queued', info.pitchesQueued],
    ['Overflow dropped', overflowNote(info)],
    ['Run seconds', info.elapsed]
  ]);
  sheet.setColumnWidth(1, 220);
}

/** Human-readable note about anything the LIMIT cut off. */
function overflowNote(info) {
  var lostSpecial = Math.max(0, info.specialsAvailable - info.specialsQueued);
  var lostPitches = Math.max(0, info.inWindow - info.pitchesQueued);
  if (!lostSpecial && !lostPitches) return 'none';
  return 'specials ' + lostSpecial + ', pitches ' + lostPitches +
         ' (raise LIMIT above ' + LIMIT + ' to keep them)';
}

/** Run once to install the weekly trigger. Fires Mondays around 4am. */
function installWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'buildNewsletterQueues') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('buildNewsletterQueues')
    .timeBased().onWeekDay(ScriptApp.WeekDay.MONDAY).atHour(4).create();
  Logger.log('Weekly trigger installed: Mondays ~4am.');
}
