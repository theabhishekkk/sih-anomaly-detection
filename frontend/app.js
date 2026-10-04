const state = { calibration: null, report: null, decisions: [], selected: null };
const $ = (selector) => document.querySelector(selector);
let csrfToken;

function setMessage(selector, message, kind = '') {
  const element = $(selector);
  element.textContent = message;
  element.className = `form-message${kind ? ` ${kind}` : ''}`;
}

async function requestJson(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
    if (!csrfToken) {
      const csrfResponse = await fetch('/api/csrf');
      const csrfPayload = await csrfResponse.json().catch(() => ({}));
      if (!csrfResponse.ok || !csrfPayload.csrf_token) {
        throw new Error('Sign in again before submitting this change.');
      }
      csrfToken = csrfPayload.csrf_token;
    }
    const headers = new Headers(options.headers || {});
    headers.set('X-CSRF-Token', csrfToken);
    options = { ...options, headers };
  }
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg || 'Invalid request').join('; ')
      : payload.detail;
    const message = detail || payload.error || `Request failed (${response.status}).`;
    throw new Error(message);
  }
  return payload;
}

function busy(button, busyState, label) {
  if (busyState) {
    button.dataset.label = button.textContent;
    button.textContent = label;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.label || button.textContent;
    button.disabled = false;
  }
}

function setFileName(input, target) {
  input.addEventListener('change', () => {
    state.demoMode = false;
    $(target).textContent = input.files?.[0]?.name || 'CSV · UTF-8';
  });
}

function formatNumber(value) {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat(undefined, { maximumSignificantDigits: 6 }).format(value);
}

function renderCalibration(calibration) {
  state.calibration = calibration;
  if (!calibration) {
    $('#metric-calibration').textContent = 'Not set';
    $('#calibration-foot').textContent = 'Upload reference data to begin';
    return;
  }
  $('#metric-calibration').textContent = 'Ready';
  const names = Object.keys(calibration.parameters || {});
  $('#calibration-foot').textContent =
    `${calibration.device_count} references · ${names.length} parameter${names.length === 1 ? '' : 's'}`;
}

function renderReport(report, createdAt) {
  state.report = report;
  if (!report) {
    $('#metric-total').textContent = '—';
    $('#metric-flagged').textContent = '—';
    $('#metric-health').textContent = '—';
    $('#run-time').textContent = '';
    renderDevices();
    return;
  }
  const summary = report.summary;
  $('#metric-total').textContent = summary.total_devices;
  $('#metric-flagged').textContent = summary.flagged_devices;
  $('#metric-health').textContent = `${formatNumber(summary.health_percentage)}%`;
  $('#run-time').textContent = createdAt
    ? new Date(createdAt).toLocaleString()
    : '';
  renderDevices();
}

function renderDevices() {
  const body = $('#device-rows');
  body.replaceChildren();
  const filter = $('#device-filter').value;
  const devices = (state.report?.devices || []).filter((device) => {
    if (filter === 'flagged') return device.flagged;
    if (filter === 'normal') return !device.flagged;
    return true;
  });
  if (!devices.length) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.className = 'empty-state';
    cell.colSpan = 6;
    cell.textContent = state.report
      ? 'No devices match this filter.'
      : 'Calibrate a reference lot, then analyze a screening CSV.';
    row.append(cell);
    body.append(row);
    return;
  }

  for (const device of devices) {
    const row = document.createElement('tr');
    const identity = document.createElement('td');
    identity.className = 'lot-cell';
    const link = document.createElement('button');
    link.type = 'button';
    link.className = 'device-link';
    link.textContent = device.device_id;
    link.addEventListener('click', () => showDevice(device));
    identity.append(link);
    const lot = document.createElement('small');
    lot.textContent = device.lot_id || 'Production lot';
    identity.append(lot);

    const parameter = document.createElement('td');
    parameter.textContent = device.parameter;
    const readings = document.createElement('td');
    readings.textContent = `${formatNumber(device.value_0h)} → ${formatNumber(device.value_24h)}`;
    const forecast = document.createElement('td');
    forecast.textContent = formatNumber(device.prediction_168h);
    const score = document.createElement('td');
    score.textContent = formatNumber(device.anomaly_score);
    const status = document.createElement('td');
    const pill = document.createElement('span');
    pill.className = `status-pill ${device.flagged ? 'flagged' : 'passed'}`;
    const dot = document.createElement('span');
    dot.className = 'status-dot';
    const statusText = document.createElement('span');
    statusText.textContent = device.flagged ? 'REVIEW' : 'PASSED';
    pill.append(dot, statusText);
    status.append(pill);
    row.append(identity, parameter, readings, forecast, score, status);
    body.append(row);
  }
}

function renderAudit(decisions) {
  state.decisions = decisions || [];
  $('#audit-count').textContent = `${state.decisions.length} logged`;
  const list = $('#audit-list');
  list.replaceChildren();
  if (!state.decisions.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-copy';
    empty.textContent = 'Decisions made during review will appear here with their evidence.';
    list.append(empty);
    return;
  }
  for (const decision of state.decisions) {
    const item = document.createElement('article');
    item.className = 'audit-item';
    const action = document.createElement('span');
    action.className = `audit-action ${decision.action === 'override_flag' ? 'override' : ''}`;
    action.textContent = decision.action === 'override_flag' ? 'Flag overridden' : 'Rejection approved';
    const identity = document.createElement('strong');
    identity.textContent = `${decision.device_id} · ${decision.inspector}`;
    const reason = document.createElement('span');
    reason.className = 'audit-reason';
    reason.textContent = decision.reason;
    const time = document.createElement('time');
    time.className = 'audit-time';
    time.dateTime = decision.created_at;
    time.textContent = new Date(decision.created_at).toLocaleString();
    item.append(action, identity, reason, time);
    list.append(item);
  }
}

async function refreshState() {
  try {
    const data = await requestJson('/api/state');
    renderCalibration(data.calibration?.data || null);
    renderReport(data.screening?.data || null, data.screening?.created_at);
    renderAudit(data.decisions);
    const identity = await requestJson('/api/whoami');
    $('#signed-in-user').textContent = identity.user?.name || '';
    $('#sign-out').hidden = !identity.authenticated;
  } catch (error) {
    setMessage('#screening-message', `Could not load saved state: ${error.message}`, 'error');
  }
}

async function signOut() {
  try {
    await requestJson('/auth/logout', { method: 'POST' });
    window.location.assign('/');
  } catch (error) {
    setMessage('#screening-message', `Could not sign out: ${error.message}`, 'error');
  }
}

async function calibrate() {
  const button = $('#calibrate-button');
  const file = $('#reference-file').files?.[0];
  busy(button, true, 'Calibrating…');
  setMessage('#calibration-message', 'Building robust reference distributions…');
  try {
    let result;
    if (file) {
      const form = new FormData();
      form.append('file', file);
      form.append('direction', $('#direction').value);
      const slopeInput = $('#safety-slope').value.trim();
      if (slopeInput) form.append('safety_slope', slopeInput);
      result = await requestJson('/api/calibration/upload', { method: 'POST', body: form });
    } else if (state.demoMode) {
      result = await requestJson('/api/calibration', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reference: createDemoReference(),
          direction: $('#direction').value,
        }),
      });
    } else {
      throw new Error('Choose a known-good reference CSV, or use the interactive demo.');
    }
    renderCalibration(result.calibration);
    setMessage(
      '#calibration-message',
      `Baseline saved for ${result.calibration.device_count} known-good devices.`,
      'success',
    );
  } catch (error) {
    setMessage('#calibration-message', error.message, 'error');
  } finally {
    busy(button, false);
  }
}

async function screenLot() {
  const button = $('#screen-button');
  const file = $('#screening-file').files?.[0];
  if (!state.calibration) {
    setMessage('#screening-message', 'Calibrate a known-good reference lot first.', 'error');
    return;
  }
  busy(button, true, 'Analyzing lot…');
  setMessage('#screening-message', 'Scoring readings and forecasting 168h drift…');
  try {
    const slopeInput = $('#safety-slope').value.trim();
    let result;
    if (file) {
      const form = new FormData();
      form.append('file', file);
      if (slopeInput) form.append('safety_slope', slopeInput);
      result = await requestJson('/api/screen/upload', { method: 'POST', body: form });
    } else if (state.demoMode) {
      const devices = createDemoProductionLot();
      const payload = { devices };
      if (slopeInput) payload.safety_slope = Number(slopeInput);
      result = await requestJson('/api/screen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    } else {
      throw new Error('Choose a production-lot CSV, or use the interactive demo.');
    }
    renderReport(result, result.created_at);
    setMessage(
      '#screening-message',
      `${result.summary.flagged_devices} of ${result.summary.total_devices} devices require review.`,
      result.summary.flagged_devices ? '' : 'success',
    );
  } catch (error) {
    setMessage('#screening-message', error.message, 'error');
  } finally {
    busy(button, false);
  }
}

function createDemoReference() {
  return Array.from({ length: 30 }, (_, index) => {
    const value0 = 9.8 + index * 0.014;
    const delta24 = 0.19 + (index % 5) * 0.009;
    const forecastError = (index % 7 - 3) * 0.025;
    return {
      device_id: `REF-${String(index + 1).padStart(3, '0')}`,
      lot_id: 'REFERENCE-LOT-01',
      parameter: 'leakage_current_uA',
      value_0h: Number(value0.toFixed(3)),
      value_24h: Number((value0 + delta24).toFixed(3)),
      value_96h: Number((value0 + delta24 * 4 + forecastError).toFixed(3)),
      value_168h: Number((value0 + delta24 * 7 + forecastError).toFixed(3)),
    };
  });
}

function createDemoProductionLot() {
  const normal = Array.from({ length: 11 }, (_, index) => {
    const value0 = 9.9 + (index % 5) * 0.035;
    const delta24 = 0.18 + (index % 3) * 0.008;
    return {
      device_id: `SIH-${String(index + 1).padStart(3, '0')}`,
      lot_id: 'DEMO-LOT-07',
      parameter: 'leakage_current_uA',
      value_0h: Number(value0.toFixed(3)),
      value_24h: Number((value0 + delta24).toFixed(3)),
    };
  });
  normal[7] = {
    device_id: 'SIH-008',
    lot_id: 'DEMO-LOT-07',
    parameter: 'leakage_current_uA',
    value_0h: 10.02,
    value_24h: 45,
  };
  return normal;
}

function appendSvg(svg, tag, attributes = {}, text = '') {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  if (text) element.textContent = text;
  svg.append(element);
  return element;
}

function renderChart(device) {
  const container = $('#device-chart');
  container.replaceChildren();
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 620 200');
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', 'Measured and forecast burn-in values');
  const points = [
    { hour: 0, value: device.value_0h, label: '0h measured' },
    { hour: 24, value: device.value_24h, label: '24h measured' },
    { hour: 168, value: device.prediction_168h, label: '168h forecast' },
  ];
  const direction = state.calibration?.direction === 'lower' ? -1 : 1;
  const safeEnd = device.value_0h + direction * device.safety_slope * 168;
  const values = points.map((point) => point.value).concat([safeEnd]);
  let minValue = Math.min(...values);
  let maxValue = Math.max(...values);
  const span = Math.max(maxValue - minValue, Math.abs(maxValue) * 0.05, 1e-6);
  minValue -= span * 0.16;
  maxValue += span * 0.16;
  const x = (hour) => 58 + (hour / 168) * 530;
  const y = (value) => 163 - ((value - minValue) / (maxValue - minValue)) * 127;
  for (let index = 0; index <= 4; index += 1) {
    const horizontal = 36 + index * 31;
    appendSvg(svg, 'line', { x1: 58, x2: 588, y1: horizontal, y2: horizontal, stroke: '#25354b', 'stroke-width': 1 });
  }
  appendSvg(svg, 'line', { x1: 58, x2: 588, y1: y(safeEnd), y2: y(safeEnd), stroke: '#f3c56b', 'stroke-width': 1.5, 'stroke-dasharray': '5 5' });
  appendSvg(svg, 'text', { x: 585, y: y(safeEnd) - 6, 'text-anchor': 'end', class: 'chart-label', fill: '#f3c56b' }, 'SAFETY LIMIT');
  appendSvg(svg, 'polyline', {
    points: points.map((point) => `${x(point.hour)},${y(point.value)}`).join(' '),
    fill: 'none',
    stroke: '#4bd6c4',
    'stroke-width': 3,
    'stroke-linecap': 'round',
    'stroke-linejoin': 'round',
  });
  for (const point of points) {
    appendSvg(svg, 'circle', {
      cx: x(point.hour),
      cy: y(point.value),
      r: point.hour === 168 ? 5 : 4,
      fill: point.hour === 168 ? '#ff737d' : '#4bd6c4',
      stroke: '#101b2b',
      'stroke-width': 2,
    });
    appendSvg(svg, 'text', {
      x: x(point.hour) + (point.hour === 24 ? 18 : 0),
      y: 185,
      'text-anchor': point.hour === 0 ? 'start' : point.hour === 168 ? 'end' : 'middle',
      class: 'chart-label',
    }, point.label);
  }
  appendSvg(svg, 'text', { x: 8, y: 18, class: 'chart-label' }, `${device.parameter} · predicted ${formatNumber(device.prediction_168h)}`);
  container.append(svg);
}

async function showDevice(device) {
  state.selected = device;
  $('#dialog-title').textContent = `${device.device_id} · ${device.parameter}`;
  $('#device-explanation').textContent = device.reason;
  $('#explanation-source').textContent = 'EVIDENCE-BASED SHAP';
  setMessage('#decision-message', '');
  renderChart(device);
  const evidence = $('#device-evidence');
  evidence.replaceChildren();
  const tiles = [
    ['0H READING', formatNumber(device.value_0h)],
    ['24H READING', formatNumber(device.value_24h)],
    ['168H FORECAST', formatNumber(device.prediction_168h)],
    ['ROBUST SCORE', formatNumber(device.anomaly_score)],
    ['DRIFT / HOUR', formatNumber(device.predicted_drift_per_hour)],
    ['SAFETY SLOPE', formatNumber(device.safety_slope)],
  ];
  for (const [label, value] of tiles) {
    const tile = document.createElement('div');
    tile.className = 'evidence-tile';
    const caption = document.createElement('span');
    caption.textContent = label;
    const reading = document.createElement('strong');
    reading.textContent = value;
    tile.append(caption, reading);
    evidence.append(tile);
  }
  const shapList = $('#shap-values');
  shapList.replaceChildren();
  for (const item of device.explanations) {
    const row = document.createElement('div');
    row.className = 'shap-row';
    const name = document.createElement('span');
    name.textContent = item.feature.replaceAll('_', ' ');
    const score = document.createElement('span');
    score.textContent = `robust z ${formatNumber(item.robust_z_score)}`;
    const attribution = document.createElement('strong');
    attribution.textContent = formatNumber(item.shap_value);
    row.append(name, score, attribution);
    shapList.append(row);
  }
  $('#device-dialog').showModal();
  try {
    const result = await requestJson(`/api/devices/${encodeURIComponent(device.device_id)}/explain`);
    $('#device-explanation').textContent = result.explanation;
    $('#explanation-source').textContent =
        result.llm_status === 'available' ? 'LOCAL OLLAMA' : 'EVIDENCE-BASED SHAP';
  } catch (error) {
    $('#device-explanation').textContent = `${device.reason} Explanation service error: ${error.message}`;
    $('#explanation-source').textContent = 'SERVICE ERROR';
  }
}

async function recordDecision(action) {
  if (!state.selected) return;
  const inspector = $('#inspector-name').value.trim();
  const reason = $('#decision-reason').value.trim();
  if (!inspector || !reason) {
    setMessage('#decision-message', 'Inspector name and decision rationale are required.', 'error');
    return;
  }
  try {
    const decision = await requestJson('/api/decisions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: state.selected.device_id,
        action,
        inspector,
        reason,
      }),
    });
    state.decisions.unshift(decision);
    renderAudit(state.decisions);
    setMessage('#decision-message', 'Decision and screening evidence recorded.', 'success');
  } catch (error) {
    setMessage('#decision-message', error.message, 'error');
  }
}

async function loadDemo() {
  $('#direction').value = 'higher';
  $('#reference-file').value = '';
  $('#screening-file').value = '';
  state.demoMode = true;
  $('#reference-file-name').textContent = 'Using built-in demo reference cohort';
  $('#screening-file-name').textContent = 'Using demo production lot (11 devices)';
  await calibrate();
  if (state.calibration) await screenLot();
  state.demoMode = false;
}

setFileName($('#reference-file'), '#reference-file-name');
setFileName($('#screening-file'), '#screening-file-name');
$('#calibrate-button').addEventListener('click', calibrate);
$('#screen-button').addEventListener('click', screenLot);
$('#demo-button').addEventListener('click', loadDemo);
$('#device-filter').addEventListener('change', renderDevices);
$('#close-dialog').addEventListener('click', () => $('#device-dialog').close());
$('#sign-out').addEventListener('click', signOut);
$('#approve-rejection').addEventListener('click', () => recordDecision('approve_rejection'));
$('#override-flag').addEventListener('click', () => recordDecision('override_flag'));
$('#device-dialog').addEventListener('click', (event) => {
  if (event.target === $('#device-dialog')) $('#device-dialog').close();
});

refreshState();
