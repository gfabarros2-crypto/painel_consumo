const state = { resource: 'water', period: null, records: [], sources: {}, lastUpdated: null, request: 0 };
const months = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
const $ = (id) => document.getElementById(id);
const number = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 });
const money = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const rate = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL', minimumFractionDigits: 4, maximumFractionDigits: 4 });
const percent = new Intl.NumberFormat('pt-BR', { style: 'decimal', minimumFractionDigits: 1, maximumFractionDigits: 1 });

function periodName(period, short = false) {
  const [year, month] = period.split('-');
  return short ? `${months[Number(month) - 1].slice(0, 3)}/${year.slice(2)}` : `${months[Number(month) - 1]} de ${year}`;
}

function unit() { return state.resource === 'water' ? 'm³' : 'kWh'; }
function consumption(value) { return value == null ? 'Não informado' : `${number.format(value)} ${unit()}`; }
function billed(value) { return value == null ? 'Não informado' : money.format(value); }
function show(which) {
  ['loading', 'error', 'empty', 'results'].forEach((id) => { $(id).hidden = id !== which; });
}

async function load() {
  show('loading');
  try {
    const response = await fetch('api/records', { cache: 'no-store' });
    if (!response.ok) throw new Error('Falha na consulta');
    const payload = await response.json();
    state.records = payload.records || [];
    state.sources = payload.sources || {};
    state.lastUpdated = payload.last_updated;
    if (payload.sources?.water) $('water-source').href = payload.sources.water;
    if (payload.sources?.energy) $('energy-source').href = payload.sources.energy;
    updateSourceNote();
    chooseResource(state.resource);
  } catch {
    show('error');
  }
}

function updateSourceNote() {
  const water = state.records.filter((r) => r.resource === 'water').map((r) => r.period).sort().at(-1);
  const energy = state.records.filter((r) => r.resource === 'energy').map((r) => r.period).sort().at(-1);
  const parts = [water && `água: ${periodName(water)}`, energy && `energia: ${periodName(energy)}`].filter(Boolean);
  const last = state.lastUpdated ? `Base atualizada em ${new Date(state.lastUpdated).toLocaleDateString('pt-BR')}. ` : 'Data de atualização da fonte original não informada. ';
  $('update-note').textContent = `${last}${parts.length ? `Última competência localizada — ${parts.join('; ')}.` : 'Ainda não há competência publicada na base.'}`;
}

function chooseResource(resource) {
  state.resource = resource;
  document.querySelectorAll('[role="tab"]').forEach((tab) => {
    const active = tab.dataset.resource === resource;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  $('dashboard-content').setAttribute('aria-labelledby', `tab-${resource}`);
  const periods = state.records.filter((r) => r.resource === resource).map((r) => r.period).sort();
  const years = [...new Set(periods.map((p) => p.slice(0, 4)))].sort().reverse();
  $('year-select').replaceChildren(...years.map((year) => new Option(year, year)));
  $('year-select').disabled = !years.length;
  $('month-select').disabled = !years.length;
  if (!periods.length) {
    $('month-select').replaceChildren(new Option('—', ''));
    $('empty-detail').textContent = resource === 'water'
      ? 'Não há valores de água confirmados na base. Consulte a planilha oficial na seção de metodologia.'
      : 'Ainda não há demonstrativo de energia da EMPETUR conferido para alimentar esta aba. A consulta será liberada após o envio e a revisão do documento.';
    $('empty-source').href = 'https://www.empetur.pe.gov.br/consumo-de-agua';
    show('empty');
    return;
  }
  state.period = periods.at(-1);
  $('year-select').value = state.period.slice(0, 4);
  fillMonths(state.period.slice(5));
  renderPeriod();
}

function fillMonths(selectedMonth) {
  $('month-select').replaceChildren(...months.map((name, index) => new Option(name, String(index + 1).padStart(2, '0'))));
  $('month-select').value = selectedMonth;
}

async function renderPeriod() {
  const request = ++state.request;
  state.period = `${$('year-select').value}-${$('month-select').value}`;
  show('loading');
  try {
    const url = `api/period?resource=${encodeURIComponent(state.resource)}&period=${encodeURIComponent(state.period)}`;
    const response = await fetch(url, { cache: 'no-store' });
    if (!response.ok) throw new Error('Falha na consulta');
    const data = await response.json();
    if (request !== state.request) return;
    if (!data.selected) {
      $('empty-detail').textContent = `Não há valor registrado para ${periodName(state.period).toLowerCase()}. Um mês sem informação não é tratado como consumo zero.`;
      $('empty-source').href = state.sources[state.resource] || 'https://www.empetur.pe.gov.br/consumo-de-agua';
      show('empty');
      return;
    }
    drawResults(data);
    show('results');
  } catch {
    if (request === state.request) show('error');
  }
}

function drawResults(data) {
  const record = data.selected;
  $('period-title').textContent = periodName(data.period);
  $('consumption').textContent = record.consumption == null ? '—' : number.format(record.consumption);
  $('consumption-unit').textContent = record.consumption == null ? `${unit()} não informado na fonte` : `${unit()} registrados`;
  $('total').textContent = billed(record.total_brl);
  $('average').textContent = data.average === null ? '—' : number.format(data.average);
  $('average-note').textContent = data.average === null ? `Histórico sem ${unit()} suficiente` : `${unit()} nos seis meses anteriores`;
  $('variation').textContent = data.variation_percent === null ? '—' : `${data.variation_percent > 0 ? '+' : ''}${percent.format(data.variation_percent)}%`;
  $('variation-note').textContent = data.variation_percent === null ? 'Comparação indisponível' : 'Em relação à média de seis meses';
  $('status').textContent = data.status.label;
  $('status').className = `status ${data.status.code}`;
  $('comparison-explanation').hidden = !data.comparison_reason;
  $('comparison-explanation').textContent = data.comparison_reason || '';
  drawChart(data);
  drawHistory(data);
  drawDetails(record);
}

function drawChart(data) {
  const items = [...data.history, { period: data.period, record: data.selected }];
  const billing = !items.some((item) => item.record?.consumption != null) && items.some((item) => item.record?.total_brl != null);
  const valueOf = (item) => billing ? item.record?.total_brl : item.record?.consumption;
  const showValue = (value) => billing ? billed(value) : consumption(value);
  const values = items.map(valueOf).filter((value) => value != null);
  const ceiling = Math.max(1, ...values, billing ? 0 : (data.average ?? 0)) * 1.14;
  const chart = $('chart');
  chart.classList.toggle('billing', billing);
  chart.replaceChildren();
  $('chart-title').textContent = billing ? 'Evolução do valor faturado' : 'Consumo e referência histórica';
  $('chart-unit').textContent = billing ? 'R$' : unit();
  $('legend-primary').lastChild.textContent = billing ? 'Valor faturado' : 'Consumo registrado';
  $('legend-reference').hidden = billing;
  const plot = document.createElement('div');
  plot.className = 'chart-plot';
  if (!billing && data.average !== null) {
    const line = document.createElement('div');
    line.className = 'average-line';
    line.style.bottom = `${data.average / ceiling * 100}%`;
    line.title = `Média: ${consumption(data.average)}`;
    plot.append(line);
  }
  items.forEach((item, index) => {
    const column = document.createElement('div');
    column.className = `chart-column${index === 6 ? ' selected' : ''}`;
    const bar = document.createElement('div');
    const value = valueOf(item);
    bar.className = `bar${value != null ? '' : ' missing'}`;
    if (value != null) {
      bar.style.height = `${Math.max(value === 0 ? 2 : 5, value / ceiling * 100)}%`;
      bar.title = `${periodName(item.period)}: ${showValue(value)}`;
    } else {
      bar.style.height = '100%';
      bar.title = `${periodName(item.period)}: sem informação`;
    }
    column.append(bar);
    plot.append(column);
  });
  const labels = document.createElement('div');
  labels.className = 'chart-labels';
  items.forEach((item) => {
    const label = document.createElement('span');
    label.textContent = periodName(item.period, true);
    labels.append(label);
  });
  chart.append(plot, labels);
  chart.setAttribute('aria-label', `${billing ? 'Valor faturado' : 'Consumo'} por mês: ` + items.map((item) => `${periodName(item.period)}: ${showValue(valueOf(item))}`).join('; ') + (billing || data.average === null ? '. Média de consumo indisponível.' : `. Média dos seis meses anteriores: ${consumption(data.average)}.`));
  $('chart-caption').textContent = billing
    ? 'O demonstrativo não informa kWh. As barras representam somente o valor faturado; a média e a classificação do consumo ficam indisponíveis.'
    : data.average === null ? 'A linha de referência aparece quando os seis meses anteriores têm consumo registrado.' : `Linha tracejada: média de ${consumption(data.average)}.`;
}

function drawHistory(data) {
  const body = $('history-body');
  body.replaceChildren();
  [...data.history, { period: data.period, record: data.selected }].forEach((item, index) => {
    const row = document.createElement('tr');
    if (index === 6) row.className = 'selected-row';
    const fields = [
      periodName(item.period),
      item.record ? consumption(item.record.consumption) : '—',
      item.record ? billed(item.record.total_brl) : '—',
      !item.record ? 'Sem informação' : item.record.consumption == null ? 'Fatura informada; consumo ausente' : item.record.consumption === 0 ? 'Zero registrado' : 'Informado',
    ];
    fields.forEach((value, i) => {
      const cell = document.createElement(i === 0 ? 'th' : 'td');
      if (i === 0) cell.scope = 'row';
      cell.textContent = value;
      row.append(cell);
    });
    body.append(row);
  });
}

function drawDetails(record) {
  const list = $('detail-list');
  list.replaceChildren();
  const add = (name, value) => {
    const term = document.createElement('dt');
    const detail = document.createElement('dd');
    term.textContent = name;
    detail.textContent = value;
    list.append(term, detail);
  };
  add('Consumo', consumption(record.consumption));
  if (state.resource === 'water') {
    if (record.water_brl !== null) add('Valor da água', money.format(record.water_brl));
    if (record.sewage_brl !== null) add('Valor do esgoto', money.format(record.sewage_brl));
  } else {
    add('Custo médio faturado', record.consumption == null ? 'Indisponível: kWh não informado' : record.consumption === 0 ? 'Indisponível: consumo zero' : record.total_brl == null ? 'Indisponível: fatura não informada' : `${rate.format(record.total_brl / record.consumption)} / kWh`);
  }
  add('Total faturado', billed(record.total_brl));
  const receipt = $('receipt');
  receipt.replaceChildren();
  const sourceLabel = document.createElement('p');
  sourceLabel.className = 'receipt-note';
  if (record.source_url) {
    const source = document.createElement('a');
    source.href = record.source_url;
    source.target = '_blank';
    source.rel = 'noopener noreferrer';
    source.textContent = 'Abrir demonstrativo de origem ↗';
    receipt.append(source);
  } else {
    sourceLabel.textContent = 'Link do demonstrativo não informado para esta competência.';
    receipt.append(sourceLabel);
  }
  if (record.receipt_approved && record.receipt_url) {
    const proof = document.createElement('a');
    proof.href = record.receipt_url;
    proof.target = '_blank';
    proof.rel = 'noopener noreferrer';
    proof.textContent = 'Abrir comprovante aprovado ↗';
    receipt.append(proof);
  } else {
    const note = document.createElement('p');
    note.className = 'receipt-note';
    note.textContent = 'Comprovante não disponível para divulgação.';
    receipt.append(note);
  }
}

document.querySelectorAll('[role="tab"]').forEach((tab) => {
  tab.addEventListener('click', () => chooseResource(tab.dataset.resource));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 'water' : event.key === 'End' ? 'energy' : tab.dataset.resource === 'water' ? 'energy' : 'water';
    chooseResource(next);
    $(`tab-${next}`).focus();
  });
});
$('year-select').addEventListener('change', () => { fillMonths('01'); renderPeriod(); });
$('month-select').addEventListener('change', renderPeriod);
$('retry').addEventListener('click', load);
load();
