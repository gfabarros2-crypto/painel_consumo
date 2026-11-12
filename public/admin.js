const $ = (id) => document.getElementById(id);
let rows = [];
let importId = '';
let localPdfUrl = '';
let publishedKeys = new Set();
let authHeader = '';

function adminFetch(url, options = {}) {
  return fetch(url, { ...options, headers: { ...options.headers, Authorization: authHeader } });
}

function setAuthenticated(allowed) {
  $('admin-login').hidden = allowed;
  $('admin-workflow').hidden = !allowed;
}

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const user = $('login-user').value.trim();
  const password = $('login-password').value;
  if (user.includes(':')) return notice('login-message', 'O usuário não pode conter dois-pontos.', 'error');
  const bytes = new TextEncoder().encode(`${user}:${password}`);
  authHeader = `Basic ${btoa(Array.from(bytes, (byte) => String.fromCharCode(byte)).join(''))}`;
  notice('login-message', 'Verificando acesso…');
  try {
    const response = await adminFetch('api/admin/records', { cache: 'no-store' });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.error || (response.status === 401 ? 'Usuário ou senha incorretos.' : 'Não foi possível entrar.'));
    }
    const payload = await response.json();
    publishedKeys = new Set((payload.records || []).map((row) => `${row.resource}:${row.period}`));
    $('login-form').reset();
    notice('login-message', '');
    setAuthenticated(true);
    $('admin-resource').focus();
  } catch (error) {
    authHeader = '';
    notice('login-message', error.message, 'error');
  }
});

$('logout').addEventListener('click', () => {
  authHeader = '';
  rows = [];
  importId = '';
  setAuthenticated(false);
  $('login-user').focus();
});

function showAdminTab(name) {
  for (const item of ['update', 'guide']) {
    const selected = item === name;
    const tab = $(`admin-tab-${item}`);
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
    tab.classList.toggle('active', selected);
    $(`admin-${item}-panel`).hidden = !selected;
  }
  $(`admin-tab-${name}`).focus();
}

for (const name of ['update', 'guide']) {
  $(`admin-tab-${name}`).addEventListener('click', () => showAdminTab(name));
  $(`admin-tab-${name}`).addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    showAdminTab(event.key === 'ArrowLeft' || event.key === 'Home' ? 'update' : 'guide');
  });
}
$('start-update').addEventListener('click', () => showAdminTab('update'));

function notice(id, message, kind = '') {
  const box = $(id);
  box.hidden = !message;
  box.className = `admin-alert ${kind}`;
  box.textContent = message;
}

async function loadPublished() {
  try {
    const response = await adminFetch('api/admin/records', { cache: 'no-store' });
    if (!response.ok) return;
    const payload = await response.json();
    if (payload.demo) $('demo-banner').hidden = false;
    publishedKeys = new Set((payload.records || []).map((row) => `${row.resource}:${row.period}`));
  } catch { /* A revisão ainda funciona sem a prévia de duplicidade. */ }
}

function rawNumber(value) {
  const clean = String(value ?? '').trim();
  if (!clean) return null;
  const normalized = clean.includes(',') ? clean.replaceAll('.', '').replace(',', '.') : clean;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : NaN;
}

function createField(label, key, value, options = {}) {
  const wrapper = document.createElement('label');
  wrapper.className = 'field';
  wrapper.textContent = label;
  const input = document.createElement('input');
  input.dataset.field = key;
  input.value = value ?? '';
  input.type = options.type || 'text';
  if ((options.required || options.highlightMissing) && (value === null || value === undefined || value === '')) input.classList.add('needs-input');
  if (options.inputmode) input.inputMode = options.inputmode;
  if (options.placeholder) input.placeholder = options.placeholder;
  if (options.required) input.required = true;
  wrapper.append(input);
  return wrapper;
}

function renderRows() {
  const container = $('review-rows');
  container.replaceChildren();
  rows.forEach((row, index) => {
    const article = document.createElement('article');
    article.className = 'review-row';
    article.dataset.index = index;
    const heading = document.createElement('h3');
    heading.textContent = `Registro ${index + 1}${row.needs_review ? ' · leitura incompleta' : ''}${publishedKeys.has(`${row.resource}:${row.period}`) ? ' · substituirá mês publicado' : ''}`;
    article.append(heading);
    const primary = document.createElement('div');
    primary.className = 'review-grid';
    primary.append(
      createField('Competência (AAAA-MM)', 'period', row.period, { required: true, placeholder: '2026-09' }),
      createField(`Consumo (${row.resource === 'water' ? 'm³' : 'kWh'})`, 'consumption', row.consumption, { highlightMissing: true, inputmode: 'decimal' }),
      createField('Total faturado (R$)', 'total_brl', row.total_brl, { highlightMissing: true, inputmode: 'decimal' }),
    );
    article.append(primary);
    const absence = document.createElement('div');
    absence.className = 'absence-checks';
    for (const [field, text] of [
      ['consumption_missing_confirmed', 'Conferi: o consumo não está informado no PDF'],
      ['total_missing_confirmed', 'Conferi: o valor faturado não está informado no PDF'],
    ]) {
      const label = document.createElement('label');
      label.className = 'checkbox';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.dataset.field = field;
      input.checked = row[field] === true;
      const valueField = field === 'consumption_missing_confirmed' ? 'consumption' : 'total_brl';
      const valueInput = primary.querySelector(`[data-field="${valueField}"]`);
      label.hidden = valueInput.value.trim() !== '';
      valueInput.addEventListener('input', () => {
        label.hidden = valueInput.value.trim() !== '';
        if (label.hidden) input.checked = false;
      });
      label.append(input, document.createTextNode(text));
      absence.append(label);
    }
    article.append(absence);
    if (row.resource === 'water') {
      const more = document.createElement('div');
      more.className = 'review-grid more';
      more.style.marginTop = '13px';
      more.append(
        createField('Valor da água (R$), se discriminado', 'water_brl', row.water_brl, { inputmode: 'decimal' }),
        createField('Valor do esgoto (R$), se discriminado', 'sewage_brl', row.sewage_brl, { inputmode: 'decimal' }),
      );
      article.append(more);
    }
    const links = document.createElement('div');
    links.className = 'review-grid more';
    links.style.marginTop = '13px';
    links.append(
      createField('Link HTTPS da planilha publicada (opcional)', 'source_url', row.source_url, { type: 'url', placeholder: 'https://…' }),
      createField('Link HTTPS do comprovante aprovado (opcional)', 'receipt_url', row.receipt_url, { type: 'url', placeholder: 'https://…' }),
    );
    article.append(links);
    const check = document.createElement('label');
    check.className = 'checkbox';
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.dataset.field = 'receipt_approved';
    checkbox.checked = row.receipt_approved === true;
    check.append(checkbox, document.createTextNode('Comprovante aprovado para divulgação pública'));
    article.append(check);
    const actions = document.createElement('div');
    actions.className = 'row-actions';
    const remove = document.createElement('button');
    remove.className = 'text-button';
    remove.type = 'button';
    remove.textContent = 'Remover desta publicação';
    remove.addEventListener('click', () => {
      rows = collectRows(false).filter((_, position) => position !== index);
      renderRows();
    });
    actions.append(remove);
    article.append(actions);
    container.append(article);
  });
  $('review-section').hidden = !rows.length;
}

function collectRows(validate = true) {
  const collected = [...document.querySelectorAll('.review-row')].map((article) => {
    const row = { resource: rows[Number(article.dataset.index)].resource };
    article.querySelectorAll('[data-field]').forEach((input) => {
      row[input.dataset.field] = input.type === 'checkbox' ? input.checked : input.value.trim();
    });
    ['consumption', 'total_brl', 'water_brl', 'sewage_brl'].forEach((field) => { row[field] = rawNumber(row[field]); });
    return row;
  });
  if (validate) {
    for (const row of collected) {
      if (!/^20\d{2}-(0[1-9]|1[0-2])$/.test(row.period)) throw new Error('Corrija a competência. Use AAAA-MM.');
      if (Number.isNaN(row.consumption) || Number.isNaN(row.total_brl)) throw new Error(`Corrija os números de ${row.period}.`);
      if (row.consumption === null && row.total_brl === null) throw new Error(`Informe consumo ou total faturado de ${row.period}.`);
      if (row.consumption === null && !row.consumption_missing_confirmed) throw new Error(`Confirme a ausência do consumo em ${row.period} ou corrija o campo.`);
      if (row.total_brl === null && !row.total_missing_confirmed) throw new Error(`Confirme a ausência do faturamento em ${row.period} ou corrija o campo.`);
      if (Number.isNaN(row.water_brl) || Number.isNaN(row.sewage_brl)) throw new Error(`Corrija os valores de água/esgoto de ${row.period}.`);
      if (row.receipt_approved && !row.receipt_url) throw new Error(`Informe o comprovante aprovado de ${row.period}.`);
    }
  }
  return collected;
}

function addRow() {
  $('publish').disabled = false;
  if (rows.length) rows = collectRows(false);
  rows.push({ resource: $('admin-resource').value, period: '', consumption: null, total_brl: null, water_brl: null, sewage_brl: null, source_url: $('bulk-source-url').value.trim(), receipt_url: '', receipt_approved: false, consumption_missing_confirmed: false, total_missing_confirmed: false });
  renderRows();
  $('review-section').scrollIntoView({ behavior: 'smooth' });
}

$('upload-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('document').files[0];
  if (!file) return notice('upload-message', 'Selecione um PDF para leitura.', 'error');
  if (file.size > 4 * 1024 * 1024) return notice('upload-message', 'O PDF deve ter no máximo 4 MB.', 'error');
  notice('upload-message', 'Lendo o documento…');
  const body = new FormData();
  body.append('resource', $('admin-resource').value);
  body.append('document', file);
  try {
    const response = await adminFetch('api/admin/preview', { method: 'POST', headers: { 'X-Requested-With': 'EmpeturPainel' }, body });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Falha na leitura do PDF.');
    importId = result.import_id;
    rows = (result.rows || []).map((row) => ({ ...row, source_url: $('bulk-source-url').value.trim() }));
    if (localPdfUrl) URL.revokeObjectURL(localPdfUrl);
    localPdfUrl = URL.createObjectURL(file);
    $('local-pdf').href = localPdfUrl;
    $('local-pdf').hidden = false;
    renderRows();
    notice('upload-message', result.warnings.length ? result.warnings.join(' ') : `${rows.length} mês(es) identificado(s). Revise cada valor antes de publicar.`, result.warnings.length ? '' : 'success');
  } catch (error) {
    notice('upload-message', error.message, 'error');
  }
});

$('add-manual').addEventListener('click', addRow);
$('add-another').addEventListener('click', addRow);
$('confirm-missing').addEventListener('click', () => {
  rows = collectRows(false).map((row) => ({
    ...row,
    consumption_missing_confirmed: row.consumption === null,
    total_missing_confirmed: row.total_brl === null,
  }));
  renderRows();
  notice('review-message', 'Campos vazios marcados como ausentes da fonte. Confira o PDF antes de publicar.');
});
$('publish').addEventListener('click', async () => {
  try {
    const reviewed = collectRows();
    if (!reviewed.length) throw new Error('Inclua pelo menos um mês.');
    notice('review-message', 'Publicando os meses revisados…');
    const response = await adminFetch('api/admin/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'EmpeturPainel' },
      body: JSON.stringify({ import_id: importId, rows: reviewed }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Não foi possível publicar.');
    notice('review-message', `${result.saved} mês(es) publicado(s). ${result.replaced} registro(s) anterior(es) substituído(s). Confira no painel público.`, 'success');
    rows = [];
    importId = '';
    await loadPublished();
    // Mantém a mensagem de sucesso visível até a próxima ação.
    $('review-rows').replaceChildren();
    $('publish').disabled = true;
  } catch (error) {
    notice('review-message', error.message, 'error');
  }
});

$('add-another').addEventListener('click', () => { $('publish').disabled = false; });

