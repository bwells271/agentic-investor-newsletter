/**
 * build_newsletter_queues.gs
 *
 * Runs on Google's servers on a weekly trigger. Reads the master evaluated-pitches
 * sheet and writes two slim queue tabs that a Claude cloud routine can read whole
 * through the Google Drive connector.
 *
 * Why this exists: the master sheet is ~28 MB because Full Text holds entire
 * articles (~16 KB per row). The Drive connector caps out around 1.6 MB, so a
 * direct read returns only the first ~100 rows. Dropping Full Text and keeping
 * one week of pitches brings each queue to roughly 150 KB, well inside the limit.
 *
 * READ-ONLY against the master sheet. This script opens it, reads cells, and
 * never writes to it. Output goes to a separate spreadsheet this script owns.
 */

// ── Config ───────────────────────────────────────────────────────────────────

var MASTER_ID = '1K2qhuVaSp-G0iCEplsqVVD0-oTykM-meMhL1bkg5Yxc';
var MASTER_TAB = 'Sheet1';

// Leave blank on first run: the script creates the destination and logs its URL.
// Paste that ID back here afterwards so later runs reuse the same file.
var DEST_ID = '';

var DAYS = 7;      // how far back to look
var LIMIT = 50;    // max rows per queue

// Column numbers in the master sheet (1-indexed).
var COL = {
  companyName: 1,   // A
  ticker: 2,        // B
  link: 3,          // C
  pitchDate: 4,     // D
  fullText: 5,      // E  <- deliberately never read
  briefSummary: 6,  // F
  totalScore: 17,   // Q
  totalEval: 18,    // R
  specialSit: 19,   // S
  noBrainer: 20,    // T
  notes: 21,        // U
  dateIngested: 22, // V
  pitchId: 23       // W
};

// What lands in each queue tab, in order. Full Text is absent on purpose.
var OUTPUT_COLS = [
  ['Company Name',    COL.companyName],
  ['Ticker',          COL.ticker],
  ['Link',            COL.link],
  ['Pitch Date',      COL.pitchDate],
  ['Date Ingested',   COL.dateIngested],
  ['Brief Summary',   COL.briefSummary],
  ['Total Evaluation', COL.totalEval],
  ['Notes',           COL.notes],
  ['Special Situation?', COL.specialSit],
  ['Total Score',     COL.totalScore],
  ['_pitch_id',       COL.pitchId]
];

// ── Entry point ──────────────────────────────────────────────────────────────

function buildNewsletterQueues() {
  var master = SpreadsheetApp.openById(MASTER_ID).getSheetByName(MASTER_TAB);
  if (!master) throw new Error('Master tab not found: ' + MASTER_TAB);

  var lastRow = master.getLastRow();
  if (lastRow < 2) throw new Error('Master sheet looks empty.');
  var n = lastRow - 1; // excluding the header

  // Read only the four narrow columns needed to decide which rows qualify.
  // Reading whole rows here would pull Full Text and blow the memory limit.
  var pitchDates = flatten(master.getRange(2, COL.pitchDate,    n, 1).getDisplayValues());
  var ingested   = flatten(master.getRange(2, COL.dateIngested, n, 1).getDisplayValues());
  var scores     = flatten(master.getRange(2, COL.totalScore,   n, 1).getDisplayValues());
  var special    = flatten(master.getRange(2, COL.specialSit,   n, 1).getDisplayValues());

  var cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - DAYS);
  cutoff.setHours(0, 0, 0, 0);

  var candidates = [];
  for (var i = 0; i < n; i++) {
    // Date Ingested wins; Pitch Date is the fallback. Undated rows are skipped
    // so the pre-August-2026 backlog is never republished.
    var when = parseDate(ingested[i]) || parseDate(pitchDates[i]);
    if (!when || when < cutoff) continue;

    var score = parseFloat(scores[i]);
    if (isNaN(score)) score = -1;

    candidates.push({
      row: i + 2,
      score: score,
      isSpecial: /^y(es)?$/i.test(String(special[i]).trim())
    });
  }

  candidates.sort(function (a, b) { return b.score - a.score; });

  var specials = candidates.filter(function (c) { return c.isSpecial; }).slice(0, LIMIT);
  var pitches  = candidates.slice(0, LIMIT);

  var dest = openDestination();
  writeQueue(dest, 'Special Situations Queue', master, specials);
  writeQueue(dest, 'Stock Pitches Queue',      master, pitches);
  writeStatus(dest, candidates.length, specials.length, pitches.length);

  Logger.log('Destination: ' + dest.getUrl());
  Logger.log('Destination ID: ' + dest.getId());
  Logger.log('In window: ' + candidates.length +
             ' | specials: ' + specials.length +
             ' | pitches: ' + pitches.length);
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function flatten(values) {
  return values.map(function (r) { return r[0]; });
}

/** Accepts YYYY-MM-DD and common US formats. Returns null for 'n.a.' and junk. */
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

function writeQueue(dest, tabName, master, picks) {
  var sheet = dest.getSheetByName(tabName);
  if (!sheet) {
    sheet = dest.insertSheet(tabName);
  } else {
    sheet.clear();
  }

  var header = OUTPUT_COLS.map(function (c) { return c[0]; });
  var rows = [header];

  // One getRange call per selected row. At 50 rows this is cheap, and it avoids
  // pulling Full Text for the thousands of rows we are not using.
  picks.forEach(function (p) {
    var whole = master.getRange(p.row, 1, 1, COL.pitchId).getDisplayValues()[0];
    rows.push(OUTPUT_COLS.map(function (c) {
      var v = whole[c[1] - 1];
      return v == null ? '' : String(v);
    }));
  });

  sheet.getRange(1, 1, rows.length, header.length).setValues(rows);
  sheet.setFrozenRows(1);
}

function writeStatus(dest, inWindow, nSpecial, nPitches) {
  var name = 'Status';
  var sheet = dest.getSheetByName(name) || dest.insertSheet(name);
  sheet.clear();
  sheet.getRange(1, 1, 5, 2).setValues([
    ['Last refreshed', new Date().toISOString()],
    ['Window (days)', DAYS],
    ['Pitches in window', inWindow],
    ['Special Situations queued', nSpecial],
    ['Stock Pitches queued', nPitches]
  ]);
}

/** Run once to install the weekly trigger. Fires Mondays around 4am. */
function installWeeklyTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'buildNewsletterQueues') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('buildNewsletterQueues')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(4)
    .create();
  Logger.log('Weekly trigger installed: Mondays ~4am.');
}
