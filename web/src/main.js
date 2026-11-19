import { initDb, loadAll, sql } from './data.js';
import { createScene, SCALE } from './scene.js';
import { diverging, css, gradientCss } from './colors.js';

const $ = (id) => document.getElementById(id);
const fmt = (v, d = 2) => (v >= 0 ? '+' : '−') + Math.abs(v).toFixed(d);

const PRESETS = [
  ['Anomalía por década', `SELECT decade, round(avg(anomaly_c), 3) AS anomalia_c\nFROM decadal_anomaly_grid\nGROUP BY decade ORDER BY decade`],
  ['Las celdas que más se calientan', `SELECT latitude, longitude, trend_c_per_decade\nFROM trend_grid\nORDER BY trend_c_per_decade DESC\nLIMIT 10`],
  ['Los 10 años más cálidos', `SELECT year, anomaly_c\nFROM annual_anomaly\nWHERE complete\nORDER BY anomaly_c DESC\nLIMIT 10`],
  ['Meses por encima de +1 °C', `SELECT year, count(*) AS meses\nFROM monthly_anomaly\nWHERE anomaly_c > 1\nGROUP BY year ORDER BY year DESC\nLIMIT 15`],
];

let data, scene, mode = 'decade', decade = 2020, playing = false, timer = null;
let decades = [];

function cellsFor() {
  if (mode === 'trend') return data.trend.map((r) => ({ lat: r.latitude, lon: r.longitude, value: r.trend_c_per_decade }));
  return data.decadal.filter((r) => r.decade === decade).map((r) => ({ lat: r.latitude, lon: r.longitude, value: r.anomaly_c, n: r.n_years }));
}

function renderHeadline() {
  const s = data.summary;
  $('headline').textContent = `${fmt(s.total_warming_c, 1)} °C entre ${s.period_start} y ${s.period_end} · ${fmt(s.trend_c_per_decade)} °C por década`;
}

function renderLegend() {
  const max = SCALE[mode];
  const unit = mode === 'trend' ? '°C por década' : '°C respecto a 1991–2020';
  $('legend').innerHTML = `
    <div class="legend-title">${mode === 'trend' ? 'Ritmo de calentamiento' : 'Anomalía de temperatura'}</div>
    <div class="legend-bar" style="background:${gradientCss(max)}"></div>
    <div class="legend-ticks"><span>${fmt(-max, 1)}</span><span>0</span><span>${fmt(max, 1)}</span></div>
    <div class="legend-unit">${unit}. Altura y color de cada columna.</div>`;
}

function renderNote() {
  $('note').textContent =
    mode === 'trend'
      ? `Pendiente lineal 1950–2025 en cada celda de 0,1° (≈9 km).`
      : `Media de la década ${decade}–${decade + 9} frente a 1991–2020. Celdas de 0,1° (≈9 km): ERA5-Land no distingue barrancos ni costa.`;
}

function setDecade(d) {
  decade = d;
  document.querySelectorAll('.chip').forEach((c) => c.setAttribute('aria-pressed', String(Number(c.dataset.d) === d)));
  placeBracket();
  refresh();
}

function refresh() {
  scene.update({ cells: cellsFor(), mode, label: `${mode}-${decade}` });
  renderLegend();
  renderNote();
  $('bracket').hidden = mode === 'trend';
  $('decades').classList.toggle('dim', mode === 'trend');
}

function buildStripes() {
  const complete = data.annual.filter((r) => r.complete);
  const el = $('stripes');
  el.innerHTML = '';
  const max = 1.2;
  complete.forEach((r) => {
    const s = document.createElement('div');
    s.className = 'stripe';
    s.style.background = css(diverging(r.anomaly_c, max));
    s.dataset.year = r.year;
    s.dataset.v = r.anomaly_c;
    el.appendChild(s);
  });
  $('ax-start').textContent = complete[0].year;
  $('ax-end').textContent = complete[complete.length - 1].year;
  el.addEventListener('pointermove', (e) => {
    const t = e.target.closest('.stripe');
    if (!t) return hideTip();
    showTip(e.clientX, e.clientY, `<b>${t.dataset.year}</b><br>${fmt(Number(t.dataset.v))} °C`);
  });
  el.addEventListener('pointerleave', hideTip);
  el.addEventListener('click', (e) => {
    const t = e.target.closest('.stripe');
    if (!t) return;
    setMode('decade');
    setDecade(Math.floor(Number(t.dataset.year) / 10) * 10);
  });
}

function placeBracket() {
  const complete = data.annual.filter((r) => r.complete);
  const first = complete[0].year;
  const n = complete.length;
  const startIdx = Math.max(0, decade - first);
  const endIdx = Math.min(n, decade + 10 - first);
  const b = $('bracket');
  b.style.left = `${(startIdx / n) * 100}%`;
  b.style.width = `${((endIdx - startIdx) / n) * 100}%`;
}

function buildChips() {
  const complete = data.annual.filter((r) => r.complete).map((r) => r.year);
  decades = [...new Set(complete.map((y) => Math.floor(y / 10) * 10))];
  const wrap = $('decades');
  decades.forEach((d) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip';
    b.dataset.d = d;
    b.textContent = `${d}s`;
    b.setAttribute('aria-pressed', String(d === decade));
    b.addEventListener('click', () => {
      stop();
      setMode('decade');
      setDecade(d);
    });
    wrap.appendChild(b);
  });
}

function setMode(m) {
  mode = m;
  document.querySelectorAll('.seg-btn').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === m)));
  if (m === 'trend') stop();
  refresh();
}

function stop() {
  playing = false;
  clearInterval(timer);
  $('play').textContent = '▶ Reproducir';
  $('play').setAttribute('aria-label', 'Reproducir décadas');
}

function play() {
  if (playing) return stop();
  setMode('decade');
  playing = true;
  $('play').textContent = '❚❚ Pausar';
  $('play').setAttribute('aria-label', 'Pausar');
  let i = decades.indexOf(decade);
  if (i === decades.length - 1) i = -1;
  const step = () => {
    i += 1;
    if (i >= decades.length) return stop();
    setDecade(decades[i]);
  };
  step();
  timer = setInterval(step, 1500);
}

// Tooltip
const tip = $('tooltip');
function showTip(x, y, html) {
  tip.innerHTML = html;
  tip.hidden = false;
  const w = tip.offsetWidth;
  const left = Math.min(x + 14, innerWidth - w - 8);
  tip.style.transform = `translate(${Math.max(8, left)}px, ${Math.max(8, y - 14 - tip.offsetHeight)}px)`;
}
function hideTip() {
  tip.hidden = true;
}

function setupSql() {
  const input = $('sql-input');
  input.value = PRESETS[0][1];
  PRESETS.forEach(([label, q]) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'chip small';
    b.textContent = label;
    b.addEventListener('click', () => {
      input.value = q;
      run();
    });
    $('presets').appendChild(b);
  });
  const run = async () => {
    const t0 = performance.now();
    const out = $('sql-result');
    try {
      const { cols, rows } = await sql(input.value);
      const ms = Math.round(performance.now() - t0);
      $('sql-status').textContent = `${rows.length} filas · ${ms} ms · en tu navegador`;
      const esc = (v) => String(v).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]);
      out.innerHTML =
        `<table><thead><tr>${cols.map((c) => `<th scope="col">${esc(c)}</th>`).join('')}</tr></thead><tbody>` +
        rows.slice(0, 200).map((r) => `<tr>${cols.map((c) => `<td>${esc(r[c])}</td>`).join('')}</tr>`).join('') +
        `</tbody></table>`;
    } catch (e) {
      $('sql-status').textContent = 'Error en la consulta';
      out.innerHTML = `<pre class="err">${String(e.message || e).replace(/</g, '&lt;')}</pre>`;
    }
  };
  $('sql-run').addEventListener('click', run);
  input.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') run();
  });
  $('sql-toggle').addEventListener('click', () => {
    const panel = $('sql');
    const open = panel.hidden;
    panel.hidden = !open;
    $('sql-toggle').setAttribute('aria-expanded', String(open));
    $('sql-toggle').textContent = open ? 'Cerrar SQL' : 'Consultar con SQL';
    if (open && !$('sql-result').innerHTML) run();
  });
}

async function main() {
  scene = createScene({
    parent: $('scene'),
    onHover: (o) => {
      if (!o) return hideTip();
      const v = o.value;
      const body =
        mode === 'trend'
          ? `${fmt(v)} °C por década`
          : `${fmt(v)} °C <span class="mut">en la década ${decade}s</span>`;
      showTip(o.x, o.y, `<b>${o.lat.toFixed(1)}°N, ${Math.abs(o.lon).toFixed(1)}°O</b><br>${body}`);
    },
  });
  try {
    await initDb();
    data = await loadAll();
  } catch (e) {
    $('headline').textContent = 'No se pudieron cargar los datos. Ejecuta python/export_gold.py para generar web/public/data.';
    console.error(e);
    return;
  }
  decade = Math.max(...data.decadal.map((r) => r.decade));
  renderHeadline();
  buildChips();
  buildStripes();
  setupSql();
  placeBracket();
  document.querySelectorAll('.seg-btn').forEach((b) => b.addEventListener('click', () => setMode(b.dataset.mode)));
  $('play').addEventListener('click', play);
  setDecade(decade);
  scene.intro();
  window.__ready = true;
}

main();
