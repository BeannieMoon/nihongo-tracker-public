/**
 * Audio Diary — Apps Script backend, bound to the "Audio Diary" Google Sheet.
 *
 * Granularity: Franchise → Group (optional, e.g. a game era or release year) → Series (product line) → CD (tab "Volumes": the unit you own, listen to,
 * date and rate; for LI-per-volume series one CD = one LI) → Tracks (real durations; type drama /
 * free talk / song / bonus, songs don't count toward listening time).
 *
 * The Sheet is the database: one tab per table, first row = column names, one row per record keyed
 * by `id`. The web page (Index.html) calls the functions below through google.script.run; the PC
 * scripts (tools/diary_api.py) call doPost with the API token from Script Properties.
 *
 * First time: run setup() once from the editor (it creates any missing tabs/columns and the token),
 * then Deploy > New deployment > Web app (Execute as: Me, Who has access: Only myself).
 */

const SCHEMA = {
  Series: ['id', 'franchise_id', 'group_id', 'title', 'title_en', 'kind', 'audience', 'age', 'tags', 'status', 'star',
    'rating', 'level', 'difficulty', 'release', 'label', 'store', 'parent_id', 'game', 'website', 'links',
    'cover', 'notes', 'notes_after', 'started', 'finished', 'owned', 'location', 'synopsis', 'contents', 'updated'],
  Volumes: ['id', 'series_id', 'no', 'title', 'li', 'cv', 'runtime_min', 'listened', 'started', 'finished',
    'time_min', 'time_source', 'star', 'rating', 'notes', 'file_path', 'dlsite', 'release', 'store', 'catalog_no', 'cover', 'updated'],
  Franchises: ['id', 'name', 'name_en', 'audience', 'games', 'links', 'notes', 'cover', 'cast_label', 'updated'],
  Groups: ['id', 'franchise_id', 'name', 'order', 'game', 'notes', 'updated'],
  Tracks: ['id', 'volume_id', 'no', 'title', 'duration_s', 'file_path', 'type', 'cast', 'listened', 'subtitle'],
  Dumper: ['id', 'type', 'target_id', 'payload_json', 'source', 'found_at', 'status'],
  Log: ['date', 'volume_id', 'minutes', 'source', 'nt_log_id'],
  Settings: ['key', 'value'],
};
const ID_PREFIX = { Series: 's', Volumes: 'v', Franchises: 'f', Groups: 'g', Tracks: 't', Dumper: 'd' };

// ---------- web page ----------

function doGet() {
  return HtmlService.createTemplateFromFile('Index').evaluate()
    .setTitle('Audio Diary')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// ---------- table helpers ----------

function sheet_(name) {
  const sh = SpreadsheetApp.getActive().getSheetByName(name);
  if (!sh) throw new Error('Missing tab ' + name + ' — run setup()');
  return sh;
}

function headers_(sh) {
  return sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0].map(String);
}

function readTab_(name) {
  const sh = sheet_(name);
  const last = sh.getLastRow();
  if (last < 2) return [];
  const head = headers_(sh);
  return sh.getRange(2, 1, last - 1, head.length).getValues()
    .map(r => Object.fromEntries(head.map((h, i) => [h, r[i] instanceof Date ? isoDate_(r[i]) : r[i]])))
    .filter(o => o[head[0]] !== '');
}

function isoDate_(d) {
  return Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}

function newId_(tab) {
  return (ID_PREFIX[tab] || 'x') + '_' + Utilities.getUuid().slice(0, 8);
}

/** Insert or update rows by id. Only the given fields change; `updated` is stamped. */
function upsertRows_(tab, rows) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    const sh = sheet_(tab);
    const head = headers_(sh);
    const last = sh.getLastRow();
    const ids = last > 1 ? sh.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0])) : [];
    const now = new Date().toISOString();
    const out = [];
    const appends = [];
    rows.forEach(row => {
      const obj = Object.assign({}, row);
      if (!obj.id && head[0] === 'id') obj.id = newId_(tab);
      if (head.includes('updated')) obj.updated = now;
      const at = ids.indexOf(String(obj.id));
      if (at >= 0) {
        const range = sh.getRange(at + 2, 1, 1, head.length);
        const current = range.getValues()[0];
        range.setValues([head.map((h, i) => (h in obj ? obj[h] : current[i]))]);
      } else {
        appends.push(head.map(h => (h in obj ? obj[h] : '')));
        ids.push(String(obj.id));
      }
      out.push(obj);
    });
    if (appends.length) sh.getRange(sh.getLastRow() + 1, 1, appends.length, head.length).setValues(appends);
    return out;
  } finally {
    lock.releaseLock();
  }
}

function deleteRow_(tab, id) {
  const sh = sheet_(tab);
  const last = sh.getLastRow();
  if (last < 2) return false;
  const ids = sh.getRange(2, 1, last - 1, 1).getValues().map(r => String(r[0]));
  const at = ids.indexOf(String(id));
  if (at < 0) return false;
  sh.deleteRow(at + 2);
  return true;
}

// ---------- called from the page ----------

function getAll() {
  return {
    franchises: readTab_('Franchises'),
    groups: readTab_('Groups'),
    series: readTab_('Series'),
    volumes: readTab_('Volumes'),
    dumper: readTab_('Dumper').filter(d => d.status === 'pending'),
    settings: Object.fromEntries(readTab_('Settings').map(s => [s.key, s.value])),
  };
}

function save(tab, row) {
  if (!SCHEMA[tab]) throw new Error('Unknown tab ' + tab);
  return upsertRows_(tab, [row])[0];
}

function saveMany(tab, rows) {
  if (!SCHEMA[tab]) throw new Error('Unknown tab ' + tab);
  return upsertRows_(tab, rows);
}

function remove(tab, id) {
  if (tab === 'Series') readTab_('Volumes').filter(v => v.series_id === id).forEach(v => deleteRow_('Volumes', v.id));
  return deleteRow_(tab, id);
}

function getTracks(volumeId) {
  return readTab_('Tracks').filter(t => t.volume_id === volumeId);
}

/**
 * Accept a Dumper proposal. payload_json is {tab, row} or {series, volumes:[...]}. Proposals only
 * fill fields that are empty, so nothing you typed is overwritten.
 */
function acceptDump(id) {
  const dump = readTab_('Dumper').find(d => d.id === id);
  if (!dump) throw new Error('No dumper item ' + id);
  const p = JSON.parse(dump.payload_json);
  // New rows go in whole; for existing ones only the empty fields are filled.
  const fillEmpty = (tab, rows) => {
    if (!rows.length) return [];
    const have = Object.fromEntries(readTab_(tab).map(r => [r.id, r]));
    return upsertRows_(tab, rows.map(row => {
      const existing = row.id && have[row.id];
      if (!existing) return row;
      const patch = { id: row.id };
      Object.keys(row).forEach(k => { if (existing[k] === '' || existing[k] === null) patch[k] = row[k]; });
      return patch;
    }));
  };
  if (p.series) {
    const s = fillEmpty('Series', [p.series])[0];
    fillEmpty('Volumes', (p.volumes || []).map(v => Object.assign({ series_id: s.id }, v)));
    fillEmpty('Tracks', p.tracks || []);
  } else if (p.tab && p.row) {
    fillEmpty(p.tab, [p.row]);
  }
  upsertRows_('Dumper', [{ id: id, status: 'accepted' }]);
  return true;
}

function discardDump(id) {
  upsertRows_('Dumper', [{ id: id, status: 'discarded' }]);
  return true;
}

/** Listened volumes as a new Sheet in Drive, in the old tracker's column order. Returns its URL. */
function exportListened() {
  const series = Object.fromEntries(readTab_('Series').map(s => [s.id, s]));
  const head = ['Name', 'Level', 'Start date', 'Finished date', 'Difficulty', 'Notes', 'Notes after finishing',
    'Source', 'Time (min)', 'Series', 'Type', 'Voice Actors', 'DB link', 'Audience', 'Age', 'Rating', 'Star'];
  const rows = readTab_('Volumes').filter(v => v.listened === true || v.listened === 'TRUE').map(v => {
    const s = series[v.series_id] || {};
    return [v.title || s.title, s.level, v.started || s.started, v.finished || s.finished, s.difficulty,
      v.notes || s.notes, s.notes_after, s.website, v.time_min || v.runtime_min, s.title, s.kind, v.cv,
      s.links, s.audience, s.age, v.rating || s.rating, v.star || s.star ? '★' : ''];
  });
  const ss = SpreadsheetApp.create('Audio Diary — listened export ' + isoDate_(new Date()));
  ss.getSheets()[0].getRange(1, 1, rows.length + 1, head.length).setValues([head].concat(rows));
  return ss.getUrl();
}

// ---------- called from the PC scripts ----------

function doPost(e) {
  const req = JSON.parse(e.postData.contents);
  const token = PropertiesService.getScriptProperties().getProperty('API_TOKEN');
  if (!token || req.token !== token) return json_({ ok: false, error: 'bad token' });
  try {
    switch (req.action) {
      case 'read':
        return json_({ ok: true, data: Object.fromEntries((req.tabs || Object.keys(SCHEMA)).map(t => [t, readTab_(t)])) });
      case 'readRaw': // any tab by name, e.g. "Old tracker"
        return json_({ ok: true, data: sheet_(req.tab).getDataRange().getValues() });
      case 'upsert':
        return json_({ ok: true, data: upsertRows_(req.tab, req.rows) });
      case 'uploadCover': // {name, base64} -> Drive folder "Audio Diary covers", returns an image URL
        return json_({ ok: true, data: uploadCover_(req.name, req.base64) });
      case 'dump':
        return json_({ ok: true, data: upsertRows_('Dumper', req.items.map(it => ({
          type: it.type, target_id: it.target_id || '', payload_json: JSON.stringify(it.payload),
          source: it.source || '', found_at: new Date().toISOString(), status: 'pending' }))) });
      default:
        return json_({ ok: false, error: 'unknown action ' + req.action });
    }
  } catch (err) {
    return json_({ ok: false, error: String(err) });
  }
}

function uploadCover_(name, b64) {
  const folders = DriveApp.getFoldersByName('Audio Diary covers');
  const folder = folders.hasNext() ? folders.next() : DriveApp.createFolder('Audio Diary covers');
  const existing = folder.getFilesByName(name);
  const file = existing.hasNext() ? existing.next()
    : folder.createFile(Utilities.newBlob(Utilities.base64Decode(b64), 'image/jpeg', name));
  return 'https://drive.google.com/thumbnail?id=' + file.getId() + '&sz=w600';
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

// ---------- one-time setup ----------

function setup() {
  const ss = SpreadsheetApp.getActive();
  Object.entries(SCHEMA).forEach(([name, cols]) => {
    const sh = ss.getSheetByName(name) || ss.insertSheet(name);
    const have = sh.getLastColumn() ? headers_(sh) : [];
    const missing = cols.filter(c => !have.includes(c));
    if (missing.length) sh.getRange(1, have.length + 1, 1, missing.length).setValues([missing]);
    sh.setFrozenRows(1);
  });
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('API_TOKEN')) props.setProperty('API_TOKEN', Utilities.getUuid().replace(/-/g, ''));
  Logger.log('API token for tools/diary_api.py: ' + props.getProperty('API_TOKEN'));
}
