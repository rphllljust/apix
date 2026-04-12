/**
 * Webhook bridge for Moodle <-> Sheets integration without Google Cloud.
 *
 * Deploy as Web App:
 * 1) Extensions -> Apps Script
 * 2) Deploy -> New deployment -> Web app
 * 3) Execute as: Me
 * 4) Who has access: Anyone with the link
 *
 * Optional Script Properties:
 * - APPS_SCRIPT_WEBHOOK_TOKEN: shared secret for requests
 * - SPREADSHEET_ID: spreadsheet id when script is standalone
 */

function doPost(e) {
  try {
    var body = _parseBody(e);
    _validateToken(body);
    var result = _executeAction(body);
    return _json({ ok: true, result: result });
  } catch (error) {
    return _json({
      ok: false,
      error: String(error && error.message ? error.message : error),
    });
  }
}

function _parseBody(e) {
  var raw = '';
  if (e && e.postData && typeof e.postData.contents === 'string') {
    raw = e.postData.contents;
  }
  if (!raw) {
    return {};
  }
  try {
    return JSON.parse(raw);
  } catch (error) {
    throw new Error('Invalid JSON payload.');
  }
}

function _json(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}

function _validateToken(body) {
  var expected = String(
    PropertiesService.getScriptProperties().getProperty('APPS_SCRIPT_WEBHOOK_TOKEN') || ''
  ).trim();
  if (!expected) {
    return;
  }
  var received = String((body && body.token) || '').trim();
  if (!received || received !== expected) {
    throw new Error('Unauthorized token.');
  }
}

function _executeAction(body) {
  var action = String((body && body.action) || '').trim();
  if (!action) {
    throw new Error('Missing action.');
  }

  switch (action) {
    case 'ping':
      return _actionPing(body);
    case 'ensure_headers':
      return _actionEnsureHeaders(body);
    case 'read_records':
      return _actionReadRecords(body, false);
    case 'read_records_with_row_number':
      return _actionReadRecords(body, true);
    case 'upsert_records':
      return _actionUpsertRecords(body);
    case 'overwrite_records':
      return _actionOverwriteRecords(body);
    case 'overwrite_table_with_subheader':
      return _actionOverwriteTableWithSubheader(body);
    case 'clear_rows':
      return _actionClearRows(body);
    case 'update_sync_status_rows':
      return _actionUpdateSyncStatusRows(body);
    case 'append_event':
      return _actionAppendEvent(body);
    case 'apply_alunos_layout':
      return _actionApplyAlunosLayout(body);
    default:
      throw new Error('Unsupported action: ' + action);
  }
}

function _openSpreadsheet(body) {
  var explicitId = String((body && body.spreadsheet_id) || '').trim();
  if (explicitId) {
    return SpreadsheetApp.openById(explicitId);
  }

  var configuredId = String(
    PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID') || ''
  ).trim();
  if (configuredId) {
    return SpreadsheetApp.openById(configuredId);
  }

  var active = SpreadsheetApp.getActiveSpreadsheet();
  if (active) {
    return active;
  }
  throw new Error('Spreadsheet not found. Provide spreadsheet_id or SPREADSHEET_ID property.');
}

function _requireSheet(spreadsheet, sheetName) {
  var name = String(sheetName || '').trim();
  if (!name) {
    throw new Error('Missing sheet_name.');
  }
  var sheet = spreadsheet.getSheetByName(name);
  if (!sheet) {
    sheet = spreadsheet.insertSheet(name);
  }
  return sheet;
}

function _normalizeCell(value) {
  if (value === null || value === undefined) {
    return '';
  }
  if (Object.prototype.toString.call(value) === '[object Date]') {
    return Utilities.formatDate(value, 'UTC', "yyyy-MM-dd'T'HH:mm:ss'Z'");
  }
  if (typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

function _trimTrailingEmpty(list) {
  var copy = list.slice();
  while (copy.length > 0 && String(copy[copy.length - 1] || '').trim() === '') {
    copy.pop();
  }
  return copy;
}

function _readHeaders(sheet) {
  var lastCol = sheet.getLastColumn();
  if (lastCol < 1) {
    return [];
  }
  var headers = sheet.getRange(1, 1, 1, lastCol).getValues()[0];
  headers = headers.map(function (item) { return String(item || '').trim(); });
  return _trimTrailingEmpty(headers);
}

function _ensureHeaderRow(sheet, requiredHeaders) {
  var wanted = Array.isArray(requiredHeaders) ? requiredHeaders : [];
  wanted = wanted
    .map(function (item) { return String(item || '').trim(); })
    .filter(function (item) { return item !== ''; });

  var existing = _readHeaders(sheet);
  if (existing.length === 0) {
    if (wanted.length === 0) {
      return [];
    }
    _ensureGridSize(sheet, 1, wanted.length);
    sheet.getRange(1, 1, 1, wanted.length).setValues([wanted]);
    return wanted;
  }

  var merged = existing.slice();
  wanted.forEach(function (header) {
    if (merged.indexOf(header) === -1) {
      merged.push(header);
    }
  });

  if (merged.length !== existing.length) {
    _ensureGridSize(sheet, 1, merged.length);
    sheet.getRange(1, 1, 1, merged.length).setValues([merged]);
  }
  return merged;
}

function _collectHeadersFromRecords(records) {
  var headers = [];
  (records || []).forEach(function (record) {
    if (!record || typeof record !== 'object') {
      return;
    }
    Object.keys(record).forEach(function (key) {
      if (headers.indexOf(key) === -1) {
        headers.push(key);
      }
    });
  });
  return headers;
}

function _buildRowValues(headers, record) {
  return headers.map(function (header) {
    return _normalizeCell(record ? record[header] : '');
  });
}

function _toObjectRow(headers, rowValues, includeRowNumber, rowNumber) {
  var item = {};
  if (includeRowNumber) {
    item._row_number = rowNumber;
  }
  headers.forEach(function (header, index) {
    item[header] = _normalizeCell(rowValues[index]);
  });
  return item;
}

function _isMeaningfulRow(values) {
  return values.some(function (cell) {
    return String(cell || '').trim() !== '';
  });
}

function _ensureGridSize(sheet, minRows, minCols) {
  var targetRows = Math.max(1, Number(minRows || 1));
  var targetCols = Math.max(1, Number(minCols || 1));
  if (sheet.getMaxRows() < targetRows) {
    sheet.insertRowsAfter(sheet.getMaxRows(), targetRows - sheet.getMaxRows());
  }
  if (sheet.getMaxColumns() < targetCols) {
    sheet.insertColumnsAfter(sheet.getMaxColumns(), targetCols - sheet.getMaxColumns());
  }
}

function _keyForRecord(record, keyFields) {
  if (!Array.isArray(keyFields) || keyFields.length === 0) {
    return '';
  }
  var values = [];
  for (var i = 0; i < keyFields.length; i += 1) {
    var key = String(keyFields[i] || '').trim();
    var value = _normalizeCell(record ? record[key] : '').trim();
    if (!value) {
      return '';
    }
    values.push(value);
  }
  return values.join('||');
}

function _actionPing(body) {
  var spreadsheet = _openSpreadsheet(body);
  return {
    ok: true,
    title: spreadsheet.getName(),
  };
}

function _actionEnsureHeaders(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  return _ensureHeaderRow(sheet, body.required_headers || []);
}

function _actionReadRecords(body, includeRowNumber) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var headers = _readHeaders(sheet);
  if (headers.length === 0) {
    return [];
  }
  var lastRow = sheet.getLastRow();
  if (lastRow <= 1) {
    return [];
  }
  var values = sheet.getRange(2, 1, lastRow - 1, headers.length).getValues();
  var rows = [];
  values.forEach(function (rowValues, index) {
    if (!_isMeaningfulRow(rowValues)) {
      return;
    }
    rows.push(_toObjectRow(headers, rowValues, includeRowNumber, index + 2));
  });
  return rows;
}

function _actionUpsertRecords(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var records = Array.isArray(body.records) ? body.records : [];
  var keyFields = Array.isArray(body.key_fields) ? body.key_fields : [];
  if (records.length === 0) {
    return { inserted: 0, updated: 0 };
  }

  var incomingHeaders = _collectHeadersFromRecords(records);
  var headers = _ensureHeaderRow(sheet, incomingHeaders);
  var lastRow = sheet.getLastRow();
  var currentRows = [];
  if (lastRow > 1) {
    currentRows = sheet.getRange(2, 1, lastRow - 1, headers.length).getValues();
  }

  var indexByKey = {};
  currentRows.forEach(function (rowValues, idx) {
    var rowObject = _toObjectRow(headers, rowValues, false, idx + 2);
    var key = _keyForRecord(rowObject, keyFields);
    if (key) {
      indexByKey[key] = idx + 2;
    }
  });

  var updates = [];
  var appends = [];
  var inserted = 0;
  var updated = 0;

  records.forEach(function (record) {
    var rowValues = _buildRowValues(headers, record);
    var key = _keyForRecord(record, keyFields);
    if (key && Object.prototype.hasOwnProperty.call(indexByKey, key)) {
      updates.push({ row_number: indexByKey[key], values: rowValues });
      updated += 1;
    } else {
      appends.push(rowValues);
      inserted += 1;
    }
  });

  updates.forEach(function (item) {
    _ensureGridSize(sheet, item.row_number, headers.length);
    sheet.getRange(item.row_number, 1, 1, headers.length).setValues([item.values]);
  });

  if (appends.length > 0) {
    var startRow = sheet.getLastRow() + 1;
    _ensureGridSize(sheet, startRow + appends.length - 1, headers.length);
    sheet.getRange(startRow, 1, appends.length, headers.length).setValues(appends);
  }

  return { inserted: inserted, updated: updated };
}

function _actionOverwriteRecords(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var records = Array.isArray(body.records) ? body.records : [];
  var headersInput = Array.isArray(body.headers) ? body.headers : [];
  sheet.clearContents();
  if (records.length === 0) {
    return 0;
  }

  var allHeaders = _collectHeadersFromRecords(records);
  var headers = [];
  headersInput.forEach(function (header) {
    var h = String(header || '').trim();
    if (h && headers.indexOf(h) === -1) {
      headers.push(h);
    }
  });
  allHeaders.forEach(function (header) {
    if (headers.indexOf(header) === -1) {
      headers.push(header);
    }
  });

  var rows = records.map(function (record) {
    return _buildRowValues(headers, record);
  });
  var payload = [headers].concat(rows);
  _ensureGridSize(sheet, payload.length, headers.length);
  sheet.getRange(1, 1, payload.length, headers.length).setValues(payload);
  return rows.length;
}

function _actionOverwriteTableWithSubheader(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var headers = Array.isArray(body.headers) ? body.headers.map(_normalizeCell) : [];
  var subheader = Array.isArray(body.subheader) ? body.subheader.map(_normalizeCell) : [];
  var rows = Array.isArray(body.rows) ? body.rows : [];

  sheet.clearContents();
  if (headers.length === 0) {
    return 0;
  }

  var normalizedRows = rows.map(function (row) {
    var values = Array.isArray(row) ? row : [];
    return values.map(_normalizeCell);
  });
  var payload = [headers, subheader].concat(normalizedRows);
  _ensureGridSize(sheet, payload.length, headers.length);
  sheet.getRange(1, 1, payload.length, headers.length).setValues(payload);
  sheet.setFrozenRows(2);
  return normalizedRows.length;
}

function _actionClearRows(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var rowNumbers = Array.isArray(body.row_numbers) ? body.row_numbers : [];
  if (rowNumbers.length === 0) {
    return true;
  }
  var headers = _readHeaders(sheet);
  if (headers.length === 0) {
    return true;
  }
  var blank = new Array(headers.length).fill('');
  var seen = {};
  rowNumbers.forEach(function (value) {
    var rowNumber = Number(value || 0);
    if (!rowNumber || rowNumber < 2 || seen[rowNumber]) {
      return;
    }
    seen[rowNumber] = true;
    _ensureGridSize(sheet, rowNumber, headers.length);
    sheet.getRange(rowNumber, 1, 1, headers.length).setValues([blank]);
  });
  return true;
}

function _actionUpdateSyncStatusRows(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var updates = Array.isArray(body.updates) ? body.updates : [];
  if (updates.length === 0) {
    return true;
  }

  var statusHeader = String(body.status_header || 'Status Sync');
  var errorHeader = String(body.error_header || 'Erro');
  var headers = _ensureHeaderRow(sheet, [statusHeader, errorHeader]);
  var statusCol = headers.indexOf(statusHeader) + 1;
  var errorCol = headers.indexOf(errorHeader) + 1;

  updates.forEach(function (item) {
    var row = Number(item && item.row_number ? item.row_number : 0);
    if (!row || row < 2) {
      return;
    }
    _ensureGridSize(sheet, row, Math.max(statusCol, errorCol));
    sheet.getRange(row, statusCol).setValue(_normalizeCell(item.status));
    sheet.getRange(row, errorCol).setValue(_normalizeCell(item.error));
  });
  return true;
}

function _actionAppendEvent(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var payload = (body && typeof body.payload === 'object' && body.payload) ? body.payload : {};
  var payloadHeaders = Object.keys(payload);
  var headers = _ensureHeaderRow(sheet, payloadHeaders);
  var rowValues = _buildRowValues(headers, payload);
  var nextRow = sheet.getLastRow() + 1;
  if (nextRow < 2) {
    nextRow = 2;
  }
  _ensureGridSize(sheet, nextRow, headers.length);
  sheet.getRange(nextRow, 1, 1, headers.length).setValues([rowValues]);
  return true;
}

function _actionApplyAlunosLayout(body) {
  var spreadsheet = _openSpreadsheet(body);
  var sheet = _requireSheet(spreadsheet, body.sheet_name);
  var headerCount = Math.max(1, Number(body.header_count || 1));
  _ensureGridSize(sheet, 1, headerCount);
  sheet.setFrozenRows(1);
  sheet
    .getRange(1, 1, 1, headerCount)
    .setBackground('#1a3c5e')
    .setFontColor('#ffffff')
    .setFontWeight('bold');
  return true;
}
