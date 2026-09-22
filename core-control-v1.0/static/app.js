const $ = (s) => document.querySelector(s);
let state = null;
let selectedOutput = null;
let selectedControl = null;

async function post(url, body) {
  const r = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || 'Request failed');
  return data;
}

function clamp(v) { return Math.max(0, Math.min(100, Number(v) || 0)); }
function signNum(v) { const n = Number(v) || 0; return `${n > 0 ? '+' : ''}${n.toFixed(0)}`; }

function curvePath(curve) {
  const v = curve?.v || [], f = curve?.f || [];
  if (!v.length) return '';
  const minV = Math.min(...v), maxV = Math.max(...v), maxF = Math.max(...f, 1e-9);
  return v.map((x, i) => {
    const px = 45 + (x - minV) / (maxV - minV) * 670;
    const py = 260 - Math.max(0, f[i]) / maxF * 220;
    return `${i ? 'L' : 'M'}${px.toFixed(2)},${py.toFixed(2)}`;
  }).join(' ');
}

function meterHint(v) {
  if (v >= 95) return 'CRITICAL';
  if (v >= 80) return 'RED ZONE';
  if (v >= 65) return 'Getting dangerous';
  if (v >= 50) return 'Elevated';
  return 'Comfortable';
}

function loadRecords() {
  try { return JSON.parse(localStorage.getItem('coreControlV10Records') || '[]'); }
  catch { return []; }
}

function getPersonalBest() {
  const records = loadRecords();
  return records.length ? records[0].power : null;
}

function saveSuccessfulRecord(rec) {
  const records = loadRecords();
  records.push(rec);
  records.sort((a, b) => (b.power - a.power) || (b.integrity - a.integrity) || (b.battery - a.battery));
  const top = records.slice(0, 5);
  localStorage.setItem('coreControlV10Records', JSON.stringify(top));
  return top[0] === rec;
}

function renderRecords() {
  const box = $('#recordList');
  const records = loadRecords();
  const pb = getPersonalBest();
  $('#startPB').textContent = pb == null ? '—' : `${pb} MW`;
  if (!records.length) {
    box.innerHTML = '<div class="record-row"><span>—</span><strong>No successful run yet</strong><span></span><span></span></div>';
    return;
  }
  box.innerHTML = records.map((r, i) => `
    <div class="record-row">
      <span>#${i + 1}</span>
      <strong>${r.power} MW</strong>
      <span>Integrity ${r.integrity}</span>
      <span>${r.date}</span>
    </div>`).join('');
}

function renderTurnTrack() {
  const el = $('#turnTrack');
  el.innerHTML = '';
  for (let i = 1; i <= 20; i++) {
    const n = document.createElement('i');
    if (i < state.turn || (state.finished && state.survived)) n.classList.add('done');
    if (i === state.turn && !state.finished) n.classList.add('current');
    el.appendChild(n);
  }
}

function renderUpgrades() {
  const section = $('#ownedUpgrades');
  const box = $('#upgradeBadges');
  if (!state.upgrades?.length) {
    section.classList.add('hidden');
    box.innerHTML = '';
    return;
  }
  section.classList.remove('hidden');
  box.innerHTML = state.upgrades.map(u => `<span class="upgrade-badge">${u.icon} ${u.name}</span>`).join('');
}

function renderOutputs() {
  const box = $('#outputs');
  box.innerHTML = '';
  for (const out of state.outputs) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `output-button${selectedOutput === out.id ? ' selected' : ''}${out.id === 'high' ? ' high-output' : ''}`;
    b.dataset.id = out.id;
    b.innerHTML = `<strong>${out.name}</strong><b>+${out.generation} MW</b><small>${out.risk}</small>`;
    b.disabled = state.resolved || state.finished || state.upgrade_pending;
    b.addEventListener('click', () => {
      selectedOutput = out.id;
      renderOutputs();
      updateRunButton();
    });
    box.appendChild(b);
  }
}

function renderControls() {
  const box = $('#controls');
  box.innerHTML = '';
  for (const c of state.controls) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = `control-button${selectedControl === c.id ? ' selected' : ''}${c.id === 'scram' ? ' scram' : ''}${c.id === 'hold' ? ' hold' : ''}`;
    b.disabled = !c.available;
    b.dataset.id = c.id;
    const cost = c.cost === 0 ? 'FREE' : `🔋 ${c.cost}`;
    const reason = c.available ? c.description : c.disabled_reason;
    b.innerHTML = `<div class="top"><strong>${c.icon} ${c.name}</strong><b>${cost}</b></div><small>${reason}</small>`;
    b.addEventListener('click', () => {
      selectedControl = c.id;
      renderControls();
      updateRunButton();
    });
    box.appendChild(b);
  }
}

function updateRunButton() {
  const b = $('#runReactor');
  const ready = !!selectedOutput && !!selectedControl && !state?.resolved && !state?.finished && !state?.upgrade_pending;
  b.disabled = !ready;
  if (!ready) {
    b.textContent = 'CHOOSE OUTPUT + CONTROL';
    return;
  }
  const output = state.outputs.find(o => o.id === selectedOutput);
  b.textContent = `RUN REACTOR · +${output?.generation || 0} MW`;
}

function renderResult(result) {
  const card = $('#resultCard');
  if (!result) {
    card.innerHTML = '<span>READY</span><strong>Take a safe turn — or push harder for the record.</strong>';
    return;
  }
  const heatClass = result.heat_change > 10 ? 'bad' : result.heat_change > 0 ? 'warn' : 'good';
  const stressClass = result.stress_change > 10 ? 'bad' : result.stress_change > 0 ? 'warn' : 'good';
  let headline = `${result.output_name} OUTPUT · ${result.control_icon} ${result.control_name}`;
  if (result.effective_output === 'scram') headline = '🚨 EMERGENCY SHUTDOWN';
  const loadClass = result.core_load >= 4 ? 'bad' : result.core_load >= 2 ? 'warn' : 'good';
  card.innerHTML = `
    <span>TURN RESULT</span>
    <strong>${headline}</strong>
    <div class="result-grid">
      <div><span>POWER</span><b class="good">+${result.generation}</b></div>
      <div><span>HEAT</span><b class="${heatClass}">${signNum(result.heat_change)}</b></div>
      <div><span>STRESS</span><b class="${stressClass}">${signNum(result.stress_change)}</b></div>
      <div><span>CORE LOAD</span><b class="${loadClass}">${result.core_load}/6</b></div>
      <div><span>INTEGRITY</span><b class="${result.damage ? 'bad' : result.repaired ? 'good' : ''}">${result.damage ? `-${result.damage}` : result.repaired ? `+${result.repaired}` : '0'}</b></div>
    </div>`;
}

function renderState(data, keepSelection = false) {
  state = data;
  if (!keepSelection) { selectedOutput = null; selectedControl = null; }
  $('#game').classList.remove('hidden');
  $('#turnLabel').textContent = `TURN ${state.turn} / ${state.max_turns}`;
  $('#eventTitle').textContent = state.event.title;
  $('#eventDescription').textContent = state.event.description;
  $('#eventTag').textContent = state.event.tag;
  $('#eventTag').classList.toggle('crisis', !!state.event.crisis);
  renderTurnTrack();

  $('#powerGenerated').textContent = state.generated_power;
  const pb = getPersonalBest();
  $('#personalBest').textContent = pb == null ? '—' : `${pb} MW`;
  if (pb == null) {
    $('#pbHint').textContent = 'Finish all 20 turns to set a record.';
  } else if (state.generated_power > pb) {
    $('#pbHint').textContent = `Above PB by ${state.generated_power - pb} MW — survive to bank it!`;
  } else {
    $('#pbHint').textContent = `${pb - state.generated_power} MW to catch your PB.`;
  }
  $('#battery').textContent = `${state.battery}/${state.max_battery}`;
  $('#integrity').textContent = state.integrity;

  const heat = clamp(state.heat), stress = clamp(state.stress);
  $('#heatValue').textContent = `${heat.toFixed(0)}%`;
  $('#stressValue').textContent = `${stress.toFixed(0)}%`;
  $('#heatBar').style.width = `${heat}%`;
  $('#stressBar').style.width = `${stress}%`;
  $('#heatHint').textContent = meterHint(heat);
  $('#stressHint').textContent = meterHint(stress);
  $('#heatHint').className = heat >= 80 ? 'bad' : heat >= 65 ? 'warn' : '';
  $('#stressHint').className = stress >= 80 ? 'bad' : stress >= 65 ? 'warn' : '';

  const load = Math.max(0, Math.min(state.max_core_load || 6, Number(state.core_load) || 0));
  $('#loadValue').textContent = `${load} / ${state.max_core_load || 6}`;
  $('#loadHint').textContent = load >= 5 ? 'Back off now' : load >= 3 ? 'Controls weakening' : load >= 1 ? 'Building pressure' : 'Ready to push';
  $('#loadHint').className = load >= 5 ? 'bad' : load >= 3 ? 'warn' : '';
  const seg = $('#loadSegments');
  seg.innerHTML = '';
  for (let i = 1; i <= (state.max_core_load || 6); i++) {
    const el = document.createElement('i');
    if (i <= load) el.classList.add('active');
    if (i <= load && load >= 5) el.classList.add('critical');
    seg.appendChild(el);
  }

  const orb = $('#coreOrb');
  orb.style.setProperty('--heat', heat);
  orb.style.setProperty('--stress', stress);
  orb.classList.toggle('hot', heat >= 66);
  orb.classList.toggle('danger', heat >= 80 || stress >= 80);

  const forecast = state.forecast;
  if (forecast) {
    $('#forecastTitle').textContent = forecast.title;
    $('#forecastTag').textContent = `${forecast.crisis ? '⚠ ' : ''}${forecast.tag}`;
  } else {
    $('#forecastTitle').textContent = 'No next turn';
    $('#forecastTag').textContent = 'SURVIVE THIS TURN TO BANK THE RECORD';
  }

  const curve = state.result?.curve || state.current_curve;
  $('#currentPath').setAttribute('d', curvePath(curve));
  $('#normalPath').setAttribute('d', curvePath(state.normal_curve));

  renderOutputs();
  renderControls();
  renderUpgrades();
  renderResult(state.result);
  updateRunButton();

  const next = $('#nextTurn');
  if (state.resolved) {
    next.classList.remove('hidden');
    if (state.finished) next.textContent = state.survived ? 'VIEW FINAL RECORD' : 'VIEW FAILED RUN';
    else if (state.upgrade_pending) next.textContent = 'CHOOSE UPGRADE';
    else next.textContent = 'NEXT TURN';
  } else {
    next.classList.add('hidden');
  }
}

async function beginRun() {
  try {
    const data = await post('/api/new-run', {});
    $('#startPanel').classList.add('hidden');
    $('#endPanel').classList.add('hidden');
    $('#upgradePanel').classList.add('hidden');
    renderState(data);
    window.scrollTo({top: 0, behavior: 'smooth'});
  } catch (e) { alert(e.message); }
}

async function runReactor() {
  if (!selectedOutput || !selectedControl) return;
  $('#runReactor').disabled = true;
  try {
    const data = await post('/api/action', {
      run_id: state.run_id,
      output_id: selectedOutput,
      control_id: selectedControl
    });
    renderState(data, true);
  } catch (e) { alert(e.message); updateRunButton(); }
}

function showUpgradePanel() {
  $('#game').classList.add('hidden');
  const panel = $('#upgradePanel');
  panel.classList.remove('hidden');
  const box = $('#upgradeChoices');
  box.innerHTML = '';
  for (const u of state.upgrade_choices || []) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'upgrade-choice';
    b.innerHTML = `<span class="icon">${u.icon}</span><strong>${u.name}</strong><small>${u.description}</small>`;
    b.addEventListener('click', async () => {
      b.disabled = true;
      try {
        await post('/api/upgrade', {run_id: state.run_id, upgrade_id: u.id});
        const next = await post('/api/next', {run_id: state.run_id});
        panel.classList.add('hidden');
        renderState(next);
        window.scrollTo({top: 0, behavior: 'smooth'});
      } catch (e) { alert(e.message); b.disabled = false; }
    });
    box.appendChild(b);
  }
}

async function continueFlow() {
  if (state.finished) {
    finishRun();
    return;
  }
  if (state.upgrade_pending) {
    showUpgradePanel();
    return;
  }
  try {
    const data = await post('/api/next', {run_id: state.run_id});
    renderState(data);
    window.scrollTo({top: 0, behavior: 'smooth'});
  } catch (e) { alert(e.message); }
}

function finishRun() {
  $('#game').classList.add('hidden');
  $('#upgradePanel').classList.add('hidden');
  const panel = $('#endPanel');
  panel.classList.remove('hidden');

  $('#endPower').textContent = `${state.generated_power} MW`;
  $('#endIntegrity').textContent = state.integrity;
  $('#endBattery').textContent = state.battery;

  if (state.survived) {
    $('#endEyebrow').textContent = 'RUN COMPLETE · RECORD ELIGIBLE';
    $('#endTitle').textContent = 'You kept the core alive.';
    $('#endSummary').textContent = `20 turns survived · HIGH used ${state.stats.high_turns} times · HOLD used ${state.stats.hold_turns} times · peak Core Load ${state.stats.max_core_load_seen}/${state.max_core_load} · ${state.stats.damage_taken} total damage taken.`;
    const isRecord = saveSuccessfulRecord({
      power: state.generated_power,
      integrity: state.integrity,
      battery: state.battery,
      date: new Date().toLocaleDateString(),
      seed: state.seed
    });
    $('#recordMessage').textContent = isRecord ? 'NEW PERSONAL BEST — RECORD SAVED' : 'SUCCESSFUL RUN — RECORD SAVED';
  } else {
    $('#endEyebrow').textContent = 'CORE FAILURE · RUN INVALID';
    $('#endTitle').textContent = 'The record is lost.';
    $('#endSummary').textContent = `You produced ${state.generated_power} MW, but the core failed on Turn ${state.turn}. Failed runs are not recorded.`;
    $('#recordMessage').textContent = 'NO RECORD SAVED';
  }

  renderRecords();
  window.scrollTo({top: panel.offsetTop - 20, behavior: 'smooth'});
}

$('#startRun').addEventListener('click', beginRun);
$('#newRun').addEventListener('click', beginRun);
$('#playAgain').addEventListener('click', beginRun);
$('#runReactor').addEventListener('click', runReactor);
$('#nextTurn').addEventListener('click', continueFlow);

renderRecords();
