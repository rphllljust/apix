/**
 * Google Apps Script para sincronização Moodle <-> Google Sheets
 * Funções básicas: ping, read_records, append_records, ensure_headers
 */

// Configuração
const SPREADSHEET_ID = PropertiesService.getUserProperties().getProperty('SPREADSHEET_ID') || '1Q2nm_MDUIynHmbYsSEWC9m0voEEdc_atRbUlrLkvCBM';
const WEBHOOK_TOKEN = PropertiesService.getUserProperties().getProperty('WEBHOOK_TOKEN') || '';

/**
 * Handler para GET (teste)
 */
function doGet(e) {
  try {
    const action = e.parameter.action || '';
    const spreadsheet_id = e.parameter.spreadsheet_id || SPREADSHEET_ID;

    if (action === 'ping') {
      return sendJsonResponse({ ok: true, result: true });
    }

    return sendJsonResponse({ ok: false, error: 'Use POST para esta ação' }, 400);
  } catch(error) {
    return sendJsonResponse({ ok: false, error: error.toString() }, 500);
  }
}

/**
 * Handler principal do Web App
 */
function doPost(e) {
  try {
    const requestBody = JSON.parse(e.postData.contents);

    // Validar token se configurado
    if (WEBHOOK_TOKEN && requestBody.token !== WEBHOOK_TOKEN) {
      return sendJsonResponse({ ok: false, error: 'Token inválido' }, 401);
    }

    const action = requestBody.action || '';
    const spreadsheet_id = requestBody.spreadsheet_id || SPREADSHEET_ID;

    // Rotear para a ação apropriada
    switch(action) {
      case 'ping':
        return sendJsonResponse({ ok: true, result: true });

      case 'read_records':
        return handleReadRecords(spreadsheet_id, requestBody.sheet_name);

      case 'append_records':
        return handleAppendRecords(spreadsheet_id, requestBody.sheet_name, requestBody.records);

      case 'ensure_headers':
        return handleEnsureHeaders(spreadsheet_id, requestBody.sheet_name, requestBody.required_headers);

      case 'clear_sheet':
        return handleClearSheet(spreadsheet_id, requestBody.sheet_name);

      default:
        return sendJsonResponse({ ok: false, error: `Ação desconhecida: ${action}` }, 400);
    }
  } catch(error) {
    return sendJsonResponse({ ok: false, error: error.toString() }, 500);
  }
}

/**
 * Lê registros de uma planilha
 */
function handleReadRecords(spreadsheetId, sheetName) {
  try {
    const ss = SpreadsheetApp.openById(spreadsheetId);
    const sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      return sendJsonResponse({ ok: false, error: `Planilha '${sheetName}' não encontrada` }, 404);
    }

    const data = sheet.getDataRange().getValues();
    if (data.length === 0) {
      return sendJsonResponse({ ok: true, result: [] });
    }

    const headers = data[0];
    const records = [];

    for (let i = 1; i < data.length; i++) {
      const record = {};
      for (let j = 0; j < headers.length; j++) {
        record[headers[j]] = data[i][j] || '';
      }
      records.push(record);
    }

    return sendJsonResponse({ ok: true, result: records });
  } catch(error) {
    return sendJsonResponse({ ok: false, error: error.toString() }, 500);
  }
}

/**
 * Adiciona registros a uma planilha
 */
function handleAppendRecords(spreadsheetId, sheetName, records) {
  try {
    const ss = SpreadsheetApp.openById(spreadsheetId);
    let sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    }

    if (!records || records.length === 0) {
      return sendJsonResponse({ ok: true, result: { appended: 0 } });
    }

    // Pegar headers atuais
    const data = sheet.getDataRange().getValues();
    let headers = data.length > 0 ? data[0] : [];

    // Expandir headers se necessário
    const recordKeys = new Set();
    records.forEach(r => Object.keys(r).forEach(k => recordKeys.add(k)));
    const newHeaders = Array.from(recordKeys);

    headers = [...new Set([...headers, ...newHeaders])];

    // Preparar rows para adicionar
    const rowsToAdd = records.map(record => {
      return headers.map(h => record[h] || '');
    });

    // Atualizar headers se mudaram
    if (data.length === 0 || !arraysEqual(headers, data[0])) {
      if (data.length > 0) {
        sheet.deleteRows(1, 1);
      }
      sheet.insertRows(1, 1);
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
    }

    // Adicionar registros
    const lastRow = sheet.getLastRow();
    const nextRow = lastRow + 1;
    sheet.getRange(nextRow, 1, rowsToAdd.length, headers.length).setValues(rowsToAdd);

    return sendJsonResponse({ ok: true, result: { appended: records.length } });
  } catch(error) {
    return sendJsonResponse({ ok: false, error: error.toString() }, 500);
  }
}

/**
 * Garante que os headers existem
 */
function handleEnsureHeaders(spreadsheetId, sheetName, requiredHeaders) {
  try {
    const ss = SpreadsheetApp.openById(spreadsheetId);
    let sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      sheet = ss.insertSheet(sheetName);
    }

    const data = sheet.getDataRange().getValues();
    const existingHeaders = data.length > 0 ? data[0] : [];

    // Mesclar headers
    const merged = Array.from(new Set([...existingHeaders, ...requiredHeaders]));

    // Atualizar se mudou
    if (!arraysEqual(existingHeaders, merged)) {
      if (data.length > 0) {
        sheet.deleteRows(1, 1);
      }
      sheet.insertRows(1, 1);
      sheet.getRange(1, 1, 1, merged.length).setValues([merged]);
    }

    return sendJsonResponse({ ok: true, result: merged });
  } catch(error) {
    return sendJsonResponse({ ok: false, error: error.toString() }, 500);
  }
}

/**
 * Limpa uma planilha
 */
function handleClearSheet(spreadsheetId, sheetName) {
  try {
    const ss = SpreadsheetApp.openById(spreadsheetId);
    const sheet = ss.getSheetByName(sheetName);

    if (!sheet) {
      return sendJsonResponse({ ok: false, error: `Planilha '${sheetName}' não encontrada` }, 404);
    }

    sheet.clear();
    return sendJsonResponse({ ok: true, result: true });
  } catch(error) {
    return sendJsonResponse({ ok: false, error: error.toString() }, 500);
  }
}

/**
 * Envia resposta em JSON
 */
function sendJsonResponse(data, statusCode = 200) {
  const output = ContentService.createTextOutput(JSON.stringify(data));
  output.setMimeType(ContentService.MimeType.JSON);
  return output;
}

/**
 * Compara dois arrays
 */
function arraysEqual(a, b) {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

/**
 * Função para testar localmente
 */
function testPing() {
  const result = doPost({
    postData: {
      contents: JSON.stringify({ action: 'ping' })
    }
  });
  Logger.log(result.getContent());
}
