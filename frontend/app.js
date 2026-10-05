const state = {
  calibration: null,
  report: null,
  decisions: [],
  runs: [],
  selected: null,
  user: null,
  aiMessages: [],
  aiStatus: null,
};
const $ = (selector) => document.querySelector(selector);
let csrfToken;
let authConfig = { supabase_enabled: false };
let supabaseSession = loadSupabaseSession();

function loadSupabaseSession() {
  try {
    const stored = sessionStorage.getItem('sih-supabase-session');
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}

function saveSupabaseSession(session) {
  supabaseSession = session;
  if (session) sessionStorage.setItem('sih-supabase-session', JSON.stringify(session));
  else sessionStorage.removeItem('sih-supabase-session');
}

function setMessage(selector, message, kind = '') {
  const element = $(selector);
  element.textContent = message;
  element.className = `form-message${kind ? ` ${kind}` : ''}`;
}

async function requestJson(url, options = {}) {
  const method = (options.method || 'GET').toUpperCase();
  const isAuthRoute = url.startsWith('/api/auth/');
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)
      && !authConfig.supabase_enabled && !isAuthRoute) {
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
  const headers = new Headers(options.headers || {});
  if (authConfig.supabase_enabled && supabaseSession?.access_token
      && url !== '/api/auth/login' && url !== '/api/auth/refresh') {
    headers.set('Authorization', `Bearer ${supabaseSession.access_token}`);
  }
  options = { ...options, headers };
  let response = await fetch(url, options);
  if (response.status === 401 && authConfig.supabase_enabled
      && supabaseSession?.refresh_token && url !== '/api/auth/refresh') {
    const refreshResponse = await fetch('/api/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: supabaseSession.refresh_token }),
    });
    const refreshed = await refreshResponse.json().catch(() => ({}));
    if (refreshResponse.ok && refreshed.access_token && refreshed.refresh_token) {
      saveSupabaseSession(refreshed);
      headers.set('Authorization', `Bearer ${refreshed.access_token}`);
      response = await fetch(url, { ...options, headers });
    } else {
      saveSupabaseSession(null);
    }
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((item) => item.msg || 'Invalid request').join('; ')
      : payload.detail;
    const message = detail || payload.error || `Request failed (${response.status}).`;
    const error = new Error(message);
    error.status = response.status;
    throw error;
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
    if (input.files?.length && state.demoMode) {
      state.demoMode = false;
      state.chamber = null;
      if (state.calibration?.is_demo) renderCalibration(null);
      state.aiMessages = [];
      renderAiChat([]);
      renderReport(null);
      renderChamber(null);
    }
    $(target).textContent = input.files?.[0]?.name || 'CSV · UTF-8';
  });
}

function updateClock() {
  const now = new Date();
  $('#local-clock').textContent = new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(now);
  $('#local-date').textContent = new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    timeZoneName: 'short',
  }).format(now);
}

function renderChamber(chamber) {
  state.chamber = chamber || null;
  const status = $('#chamber-status');
  if (!chamber) {
    status.textContent = 'NO TELEMETRY';
    status.dataset.status = 'unknown';
    $('#chamber-source').textContent =
      'Live chamber health is unavailable until chamber sensors are connected. Device screening does not measure chamber conditions.';
    $('#chamber-temperature').textContent = '—';
    $('#chamber-humidity').textContent = '—';
    $('#chamber-cycle').textContent = 'Waiting for chamber telemetry';
    return;
  }
  status.textContent = chamber.status === 'stable' ? 'DEMO · NOMINAL' : 'DEMO · CHECK';
  status.dataset.status = chamber.status === 'stable' ? 'stable' : 'warning';
  $('#chamber-source').textContent =
    'SIMULATED DEMO PROFILE · Illustrative values only; no physical chamber is connected.';
  $('#chamber-temperature').textContent =
    `${formatNumber(chamber.temperature_c)} °C / ${formatNumber(chamber.temperature_setpoint_c)} °C target`;
  $('#chamber-humidity').textContent =
    `${formatNumber(chamber.humidity_percent)}% / ${formatNumber(chamber.humidity_setpoint_percent)}% target`;
  $('#chamber-cycle').textContent = chamber.cycle || 'Demo chamber profile';
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
    `${calibration.device_count} ${calibration.is_demo ? 'built-in demo ' : ''}references · ${names.length} parameter${names.length === 1 ? '' : 's'}`;
}

function renderReport(report, createdAt) {
  state.report = report;
  if (!report) {
    $('#metric-total').textContent = '—';
    $('#metric-flagged').textContent = '—';
    $('#metric-health').textContent = '—';
    $('#run-time').textContent = '';
    renderDevices();
    renderIntelligence();
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
  renderIntelligence();
}

function renderIntelligence() {
  const report = state.report;
  const devices = report?.devices || [];
  const context = $('#intel-context');
  const distribution = $('#risk-distribution');
  const legend = $('#risk-legend');
  const hotspotList = $('#parameter-hotspots');
  const queue = $('#review-queue');
  const trend = $('#run-trend');
  const bands = [
    { label: 'Routine · <1', className: 'risk-low', count: 0 },
    { label: 'Watch · 1–2', className: 'risk-watch', count: 0 },
    { label: 'Elevated · 2–3.5', className: 'risk-elevated', count: 0 },
    { label: 'High · ≥3.5', className: 'risk-high', count: 0 },
  ];

  if (!report) {
    context.textContent = 'Waiting for a screened lot';
    $('#lot-verdict').textContent = 'No lot analyzed';
    $('#lot-verdict').className = 'verdict-title';
    $('#lot-verdict-copy').textContent = 'Screen a production lot to see its review status and evidence summary.';
    $('#intel-reviewed').textContent = '—';
    $('#intel-review-rate').textContent = '—';
    $('#intel-parameters').textContent = '—';
    renderChamber(null);
    distribution.setAttribute('aria-label', 'No screening readings yet');
    distribution.querySelectorAll('.risk-segment').forEach((segment) => {
      segment.style.width = '0%';
      segment.removeAttribute('title');
    });
    legend.replaceChildren();
    hotspotList.innerHTML = '<p class="empty-copy">Screen a lot to compare parameter risk.</p>';
    queue.innerHTML = '<p class="empty-copy">Flagged devices will appear here after screening.</p>';
    $('#forecast-method-note').textContent = 'Forecast method and limitations will appear with screening results.';
    renderTrend();
    return;
  }

  const summary = report.summary;
  const flaggedPercent = summary.total_devices
    ? (100 * summary.flagged_devices) / summary.total_devices
    : 0;
  context.textContent = state.demoMode ? 'Interactive demo · not saved' : 'Latest screening evidence';
  const verdict = $('#lot-verdict');
  verdict.textContent = summary.flagged_devices
    ? 'Engineering review recommended'
    : 'No current review flags';
  verdict.className = `verdict-title${summary.flagged_devices ? ' needs-review' : ' within-limits'}`;
  $('#lot-verdict-copy').textContent = summary.flagged_devices
    ? `${summary.flagged_devices} of ${summary.total_devices} devices have an anomaly or drift limit flag. Review the highest-priority evidence before making a QA decision.`
    : `No anomaly or safety-slope thresholds were exceeded across ${summary.total_devices} screened devices. This is screening evidence, not an automatic release decision.`;
  $('#intel-reviewed').textContent = summary.total_devices;
  $('#intel-review-rate').textContent = `${formatNumber(flaggedPercent)}%`;
  $('#intel-parameters').textContent = new Set(devices.map((device) => device.parameter)).size;

  const parameters = new Map();
  const byDevice = new Map();
  for (const device of devices) {
    const score = Math.max(0, Number(device.anomaly_score) || 0);
    const bandIndex = score < 1 ? 0 : score < 2 ? 1 : score < 3.5 ? 2 : 3;
    bands[bandIndex].count += 1;

    if (!parameters.has(device.parameter)) {
      parameters.set(device.parameter, { total: 0, flagged: 0, maxScore: 0 });
    }
    const parameter = parameters.get(device.parameter);
    parameter.total += 1;
    parameter.flagged += Number(Boolean(device.flagged));
    parameter.maxScore = Math.max(parameter.maxScore, score);

    const previous = byDevice.get(device.device_id);
    if (!previous || Number(Boolean(device.flagged)) > Number(Boolean(previous.flagged))
        || (device.flagged === previous.flagged && score > previous.anomaly_score)) {
      byDevice.set(device.device_id, device);
    }
  }

  const count = devices.length;
  distribution.setAttribute(
    'aria-label',
    `${count} readings: ${bands.map((band) => `${band.count} ${band.label}`).join(', ')}`,
  );
  distribution.querySelectorAll('.risk-segment').forEach((segment, index) => {
    const percentage = count ? (100 * bands[index].count) / count : 0;
    segment.style.width = `${percentage}%`;
    segment.title = `${bands[index].label}: ${bands[index].count} readings`;
  });
  legend.replaceChildren();
  for (const band of bands) {
    const item = document.createElement('span');
    item.className = 'risk-legend-item';
    const swatch = document.createElement('i');
    swatch.className = band.className;
    const label = document.createElement('span');
    label.textContent = band.label;
    const value = document.createElement('strong');
    value.textContent = band.count;
    item.append(swatch, label, value);
    legend.append(item);
  }

  hotspotList.replaceChildren();
  const rankedParameters = [...parameters.entries()]
    .sort((left, right) => right[1].flagged - left[1].flagged
      || right[1].maxScore - left[1].maxScore);
  for (const [name, metrics] of rankedParameters.slice(0, 5)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'hotspot-row';
    button.title = `Filter device evidence to ${name}`;
    const heading = document.createElement('span');
    heading.className = 'hotspot-name';
    heading.textContent = name.replaceAll('_', ' ');
    const bar = document.createElement('span');
    bar.className = 'hotspot-track';
    const fill = document.createElement('span');
    fill.className = `hotspot-fill${metrics.flagged ? ' flagged' : ''}`;
    fill.style.width = `${metrics.total ? (100 * metrics.flagged) / metrics.total : 0}%`;
    bar.append(fill);
    const value = document.createElement('strong');
    value.textContent = `${metrics.flagged}/${metrics.total}`;
    button.append(heading, bar, value);
    button.addEventListener('click', () => {
      $('#device-search').value = name;
      renderDevices();
      $('#lot-overview').scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    hotspotList.append(button);
  }
  if (!rankedParameters.length) {
    hotspotList.innerHTML = '<p class="empty-copy">No parameter readings were returned.</p>';
  }

  queue.replaceChildren();
  const riskPriority = (device) => {
    const direction = state.calibration?.direction === 'lower' ? -1 : 1;
    const worseningDrift = (Number(device.predicted_drift_per_hour) || 0) * direction;
    const safetySlope = Number(device.safety_slope) || 0;
    const slopePriority = safetySlope > 0 ? worseningDrift / safetySlope : 0;
    return Math.max((Number(device.anomaly_score) || 0) / 3.5, slopePriority);
  };
  const priorities = [...byDevice.values()]
    .filter((device) => device.flagged)
    .sort((left, right) => riskPriority(right) - riskPriority(left))
    .slice(0, 4);
  for (const device of priorities) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'queue-item';
    const copy = document.createElement('span');
    const identity = document.createElement('strong');
    identity.textContent = device.device_id;
    const detail = document.createElement('small');
    detail.textContent = `${device.parameter.replaceAll('_', ' ')} · ${device.slope_flag ? 'drift limit exceeded' : 'anomaly score elevated'}`;
    copy.append(identity, detail);
    const score = document.createElement('span');
    score.className = 'queue-score';
    score.textContent = `RISK ${formatNumber(device.anomaly_score)}`;
    score.title = `Prioritized by the larger of anomaly score / 3.5 or worsening drift / safety slope (${formatNumber(riskPriority(device))}× threshold)`;
    button.append(copy, score);
    button.addEventListener('click', () => showDevice(device));
    queue.append(button);
  }
  if (!priorities.length) {
    queue.innerHTML = '<p class="empty-copy">No devices are currently flagged for review.</p>';
  }

  const forecastMethods = [...new Set(devices.map((device) => device.forecast_method).filter(Boolean))];
  const methodSummary = forecastMethods.length
    ? forecastMethods.join(' · ')
    : report.forecast_method || 'Forecast method not reported';
  $('#forecast-method-note').textContent = `${methodSummary}. Forecasts are estimates; confirm against measured outcomes before release.`;
  renderTrend();
}

function renderTrend() {
  const container = $('#run-trend');
  container.replaceChildren();
  const runs = state.demoMode ? [] : (state.runs || []).slice(0, 8).reverse();
  if (!runs.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-copy';
    empty.textContent = state.demoMode
      ? 'Demo runs are not saved and are excluded from the production trend.'
      : 'Saved production screenings will appear here.';
    container.append(empty);
    return;
  }
  for (const run of runs) {
    const total = Number(run.summary?.total_devices) || 0;
    const flagged = Number(run.summary?.flagged_devices) || 0;
    const rate = total ? Math.min(100, (100 * flagged) / total) : 0;
    const item = document.createElement('div');
    item.className = 'trend-item';
    const label = document.createElement('span');
    label.textContent = `#${run.id}`;
    const track = document.createElement('span');
    track.className = 'trend-track';
    const fill = document.createElement('span');
    fill.className = `trend-fill${rate ? ' flagged' : ''}`;
    fill.style.height = `${Math.max(rate, total ? 4 : 0)}%`;
    track.append(fill);
    track.title = `${flagged} of ${total} devices flagged (${formatNumber(rate)}%)`;
    const value = document.createElement('strong');
    value.textContent = `${formatNumber(rate)}%`;
    item.append(label, track, value);
    container.append(item);
  }
  $('#trend-caption').textContent = `${runs.length} SAVED RUN${runs.length === 1 ? '' : 'S'}`;
}

function renderDevices() {
  const body = $('#device-rows');
  body.replaceChildren();
  const filter = $('#device-filter').value;
  const query = $('#device-search').value.trim().toLowerCase();
  const sort = $('#device-sort').value;
  const devices = (state.report?.devices || [])
    .filter((device) => {
      if (filter === 'flagged' && !device.flagged) return false;
      if (filter === 'normal' && device.flagged) return false;
      return `${device.device_id} ${device.lot_id || ''} ${device.parameter}`
        .toLowerCase().includes(query);
    })
    .sort((left, right) => {
      if (sort === 'device') return left.device_id.localeCompare(right.device_id);
      if (sort === 'score-low') return left.anomaly_score - right.anomaly_score;
      return right.anomaly_score - left.anomaly_score;
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

function renderHistory(runs) {
  state.runs = runs || [];
  renderTrend();
  const container = $('#run-history');
  container.replaceChildren();
  if (!state.runs.length) {
    const empty = document.createElement('p');
    empty.className = 'empty-copy';
    empty.textContent = 'Your completed production screenings will appear here.';
    container.append(empty);
    return;
  }
  for (const run of state.runs) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'run-history-item';
    const title = document.createElement('strong');
    title.textContent = `Run #${run.id} · ${run.summary.total_devices} devices`;
    const meta = document.createElement('span');
    meta.textContent = `${run.summary.flagged_devices} for review · ${new Date(run.created_at).toLocaleString()}`;
    button.append(title, meta);
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        const result = await requestJson(`/api/runs/${run.id}`);
        state.demoMode = false;
        state.aiMessages = [];
        renderAiChat([]);
        renderReport(result.report, result.created_at);
        $('#lot-overview').scrollIntoView({ behavior: 'smooth', block: 'start' });
      } catch (error) {
        setMessage('#screening-message', `Could not load screening run: ${error.message}`, 'error');
      } finally {
        button.disabled = false;
      }
    });
    container.append(button);
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
  if (authConfig.supabase_enabled && !supabaseSession?.access_token) {
    setMessage('#auth-message', 'Sign in with an allowed QA account.');
    $('#supabase-login').hidden = false;
    $('#sign-out').hidden = true;
    $('#demo-button').disabled = false;
    return;
  }
  try {
    const identity = await requestJson('/api/whoami');
    state.user = identity.user || null;
    $('#signed-in-user').textContent = identity.user?.name || identity.user?.email || '';
    $('#sign-out').hidden = !identity.authenticated;
    $('#supabase-login').hidden = identity.authenticated || !authConfig.supabase_enabled;
    if (identity.user?.email) $('#inspector-name').value = identity.user.email;
  } catch (error) {
    if (error.status === 401 && authConfig.supabase_enabled) {
      saveSupabaseSession(null);
      $('#supabase-login').hidden = false;
      $('#sign-out').hidden = true;
      $('#signed-in-user').textContent = '';
      setMessage('#auth-message', 'Your session expired. Please sign in again.', 'error');
      return;
    }
    setMessage('#auth-message', `Could not verify sign-in: ${error.message}`, 'error');
    return;
  }
  try {
    const data = await requestJson('/api/state');
    renderCalibration(data.calibration?.data || null);
    renderReport(data.screening?.data || null, data.screening?.created_at);
    renderAudit(data.decisions);
    renderHistory(data.runs);
    state.demoMode = false;
    updateAiStatus().catch((error) => {
      $('#ai-status').textContent = `AI STATUS UNKNOWN · ${error.message}`;
    });
    $('#demo-button').disabled = false;
  } catch (error) {
    setMessage('#screening-message', `Could not load saved state: ${error.message}`, 'error');
  }
}

async function signOut() {
  try {
    if (authConfig.supabase_enabled) {
      await requestJson('/api/auth/logout', { method: 'POST' });
      saveSupabaseSession(null);
    } else {
      await requestJson('/auth/logout', { method: 'POST' });
    }
    window.location.assign('/');
  } catch (error) {
    setMessage('#screening-message', `Could not sign out: ${error.message}`, 'error');
  }
}

async function initializeAuthentication() {
  try {
    const response = await fetch('/api/auth/config');
    authConfig = await response.json();
    $('#supabase-login').hidden = !authConfig.supabase_enabled;
    if (authConfig.supabase_enabled) {
      await refreshState();
      return;
    }
    await refreshState();
  } catch (error) {
    setMessage('#auth-message', `Authentication setup failed: ${error.message}`, 'error');
  }
}

async function signInWithSupabase(event) {
  event.preventDefault();
  const button = $('#supabase-login button[type="submit"]');
  busy(button, true, 'Signing in…');
  setMessage('#auth-message', '');
  try {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: $('#auth-email').value.trim(),
        password: $('#auth-password').value,
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(result.detail || `Sign-in failed (${response.status}).`);
    if (!result.access_token || !result.refresh_token) {
      throw new Error('Supabase returned an incomplete sign-in session.');
    }
    saveSupabaseSession(result);
    $('#auth-password').value = '';
    await refreshState();
  } catch (error) {
    setMessage('#auth-message', error.message, 'error');
  } finally {
    busy(button, false);
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
    } else {
      throw new Error('Choose a known-good reference CSV, or use the built-in calibration option.');
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

async function useBuiltInCalibration() {
  const button = $('#builtin-calibration');
  busy(button, true, 'Loading sample calibration…');
  setMessage('#calibration-message', 'Loading a built-in known-good reference cohort…');
  try {
    const result = await requestJson('/api/demo');
    state.demoMode = true;
    state.aiMessages = [];
    renderAiChat([]);
    renderCalibration({ ...result.calibration, is_demo: true });
    renderReport(null);
    renderChamber(result.chamber);
    $('#reference-file').value = '';
    $('#reference-file-name').textContent = 'Built-in sample cohort · 30 known-good devices';
    setMessage(
      '#calibration-message',
      'Built-in calibration is ready. Analyze a lot to test the 100-device simulated screening; sample data is not saved.',
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
      state.demoMode = false;
      renderChamber(null);
      const form = new FormData();
      form.append('file', file);
      if (slopeInput) form.append('safety_slope', slopeInput);
      result = await requestJson('/api/screen/upload', { method: 'POST', body: form });
    } else if (state.demoMode) {
      const payload = {};
      if (slopeInput) payload.safety_slope = Number(slopeInput);
      result = await requestJson('/api/demo/screen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      renderChamber(result.chamber);
    } else {
      throw new Error('Choose a production-lot CSV, or use the interactive demo.');
    }
    renderReport(result, result.created_at);
    state.aiMessages = [];
    renderAiChat([]);
    renderHistory((await requestJson('/api/runs')).runs);
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

function csvCell(value) {
  const text = value == null ? '' : String(value);
  return `"${text.replaceAll('"', '""')}"`;
}

function exportDevices() {
  const devices = state.report?.devices || [];
  if (!devices.length) {
    setMessage('#screening-message', 'There are no screening results to export.', 'error');
    return;
  }
  const columns = [
    ['device_id', 'Device ID'],
    ['lot_id', 'Lot ID'],
    ['parameter', 'Parameter'],
    ['value_0h', '0h reading'],
    ['value_24h', '24h reading'],
    ['prediction_168h', '168h forecast'],
    ['anomaly_score', 'Robust score'],
    ['predicted_drift_per_hour', 'Drift per hour'],
    ['flagged', 'Requires review'],
    ['reason', 'Evidence'],
  ];
  const csv = [
    columns.map(([, heading]) => csvCell(heading)).join(','),
    ...devices.map((device) => columns.map(([key]) => csvCell(device[key])).join(',')),
  ].join('\r\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'burn-in-screening-results.csv';
  link.click();
  URL.revokeObjectURL(url);
}

async function askCopilot(event) {
  event.preventDefault();
  const question = $('#ai-question').value.trim();
  if (!question) return;
  const nextMessages = [...state.aiMessages, { role: 'user', content: question }].slice(-12);
  const button = $('#ai-ask');
  busy(button, true, 'Thinking…');
  $('#ai-question').disabled = true;
  $('#ai-evidence').replaceChildren();
  renderAiChat([...nextMessages, { role: 'assistant', content: 'Reviewing screening evidence…', pending: true }]);
  try {
    const endpoint = state.demoMode ? '/api/demo/chat' : '/api/ai/chat';
    const result = await requestJson(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: nextMessages }),
    });
    state.aiMessages = [...nextMessages, { role: 'assistant', content: result.answer }].slice(-12);
    $('#ai-status').textContent = result.llm_status === 'available'
      ? result.source.toUpperCase()
      : result.llm_status === 'demo_evidence'
        ? 'DEMO · EVIDENCE-BASED FALLBACK'
        : 'LOCAL AI UNAVAILABLE · EVIDENCE FALLBACK';
    $('#ai-question').value = '';
    renderAiChat(state.aiMessages);
    $('#ai-evidence').textContent =
      `${result.evidence.flagged_devices} flagged of ${result.evidence.total_devices} devices in context`;
  } catch (error) {
    if (error.status === 503) $('#ai-status').textContent = 'LOCAL OLLAMA UNAVAILABLE';
    renderAiChat([...state.aiMessages, { role: 'user', content: question }, {
      role: 'assistant',
      content: error.message,
    }]);
  } finally {
    busy(button, false);
    $('#ai-question').disabled = false;
    $('#ai-question').focus();
  }
}

function renderAiChat(messages) {
  const log = $('#ai-chat-log');
  log.replaceChildren();
  const displayMessages = messages.length
    ? messages
    : [{
      role: 'assistant',
      content: 'Screen a lot, then ask questions about its evidence. Ollama runs the model locally; no AI API subscription or external AI service is required.',
    }];
  for (const message of displayMessages) {
    const bubble = document.createElement('p');
    bubble.className = `ai-chat-message ${message.role}${message.pending ? ' pending' : ''}`;
    bubble.textContent = message.content;
    log.append(bubble);
  }
  log.scrollTop = log.scrollHeight;
}

function clearAiChat() {
  state.aiMessages = [];
  $('#ai-evidence').replaceChildren();
  renderAiChat([{
    role: 'assistant',
    content: 'Conversation cleared. Ask about the current screening evidence.',
  }]);
}

async function updateAiStatus() {
  const result = await requestJson('/api/ai/status');
  state.aiStatus = result;
  const status = $('#ai-status');
  status.dataset.status = result.status;
  if (result.status === 'ready') {
    status.textContent = `LOCAL · ${result.model}`;
  } else if (result.status === 'model_missing') {
    status.textContent = `MODEL MISSING · RUN: ${result.setup_command}`;
  } else if (result.status === 'unavailable') {
    status.textContent = 'OLLAMA OFFLINE · START THE LOCAL MODEL';
  } else {
    status.textContent = 'LOCAL AI NOT CONFIGURED';
  }
}

async function checkAiStatus() {
  const button = $('#ai-check');
  busy(button, true, 'Checking…');
  try {
    await updateAiStatus();
  } catch (error) {
    const status = $('#ai-status');
    status.dataset.status = 'unavailable';
    status.textContent = `AI STATUS CHECK FAILED · ${error.message}`;
  } finally {
    busy(button, false);
  }
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
  const reviewStatus = $('#device-review-status');
  const reviewReasons = [];
  if (device.anomaly_flag) reviewReasons.push('robust anomaly threshold exceeded');
  if (device.slope_flag) reviewReasons.push('forecast drift exceeds the safety slope');
  reviewStatus.classList.toggle('passed', !device.flagged);
  reviewStatus.textContent = device.flagged
    ? `REQUIRES REVIEW · ${reviewReasons.join(' · ') || 'screening threshold exceeded'}`
    : 'PASS · No configured anomaly or forecast-drift threshold was exceeded.';
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
  $('.decision-form').hidden = state.demoMode;
  const readOnlyNote = $('#decision-readonly-note');
  readOnlyNote.hidden = !state.demoMode;
  readOnlyNote.textContent = state.demoMode
    ? 'Interactive demo evidence is simulated and read-only. Sign in with an authorized QA account and screen a production lot to record an auditable decision.'
    : '';
  if (state.demoMode) return;
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
  const inspector = state.user?.email || $('#inspector-name').value.trim();
  const reason = $('#decision-reason').value.trim();
  if ((!inspector && !authConfig.supabase_enabled) || !reason) {
    setMessage('#decision-message', 'Inspector identity and decision rationale are required.', 'error');
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
  const button = $('#demo-button');
  busy(button, true, 'Loading demo…');
  setMessage('#calibration-message', '');
  setMessage('#screening-message', '');
  $('#direction').value = 'higher';
  $('#reference-file').value = '';
  $('#screening-file').value = '';
  try {
    const result = await requestJson('/api/demo');
    state.demoMode = true;
    state.aiMessages = [];
    renderAiChat([]);
    $('#ai-status').textContent = state.aiStatus?.status === 'ready'
      ? `DEMO · LOCAL ${state.aiStatus.model}`
      : 'DEMO · READ-ONLY EVIDENCE';
    $('#reference-file-name').textContent = 'Demo reference cohort (read-only)';
    $('#screening-file-name').textContent = 'Demo production lot (100 devices)';
    renderCalibration({ ...result.calibration, is_demo: true });
    renderReport(result.report);
    renderChamber(result.chamber);
    renderAudit([]);
    setMessage(
      '#calibration-message',
      `Demo baseline built from ${result.calibration.device_count} known-good devices.`,
      'success',
    );
    setMessage(
      '#screening-message',
      `${result.report.summary.flagged_devices} of ${result.report.summary.total_devices} demo devices require review. Demo data is not saved.`,
      result.report.summary.flagged_devices ? '' : 'success',
    );
  } catch (error) {
    setMessage('#screening-message', `Could not load demo: ${error.message}`, 'error');
  } finally {
    busy(button, false);
  }
}

setFileName($('#reference-file'), '#reference-file-name');
setFileName($('#screening-file'), '#screening-file-name');
$('#calibrate-button').addEventListener('click', calibrate);
$('#screen-button').addEventListener('click', screenLot);
$('#demo-button').addEventListener('click', loadDemo);
$('#builtin-calibration').addEventListener('click', useBuiltInCalibration);
$('#device-filter').addEventListener('change', renderDevices);
$('#device-search').addEventListener('input', renderDevices);
$('#device-sort').addEventListener('change', renderDevices);
renderIntelligence();
$('#export-button').addEventListener('click', exportDevices);
$('#ai-form').addEventListener('submit', askCopilot);
$('#ai-clear').addEventListener('click', clearAiChat);
$('#ai-check').addEventListener('click', checkAiStatus);
document.querySelectorAll('.ai-suggestion').forEach((button) => {
  button.addEventListener('click', () => {
    $('#ai-question').value = button.dataset.question || '';
    $('#ai-form').requestSubmit();
  });
});
$('#close-dialog').addEventListener('click', () => $('#device-dialog').close());
$('#sign-out').addEventListener('click', signOut);
$('#supabase-login').addEventListener('submit', signInWithSupabase);
$('#approve-rejection').addEventListener('click', () => recordDecision('approve_rejection'));
$('#override-flag').addEventListener('click', () => recordDecision('override_flag'));
$('#device-dialog').addEventListener('click', (event) => {
  if (event.target === $('#device-dialog')) $('#device-dialog').close();
});

initializeAuthentication();
updateClock();
window.setInterval(updateClock, 1000);
