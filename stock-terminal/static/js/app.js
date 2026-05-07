// Temporary stub — replaced by subscriptions plan implementation
function openUpgradeModal(desc) {
  openAuthModal('register');
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let chart = null;
let currentSymbol = null;
let refreshInterval = null;
let refreshCountdown = 60;

// ---------------------------------------------------------------------------
// Format helpers
// ---------------------------------------------------------------------------
const dash = '—';

function fmt(v, dec = 2) {
  if (v == null) return dash;
  const f = parseFloat(v);
  if (isNaN(f)) return dash;
  return f.toFixed(dec);
}

function fmtPrice(v) {
  if (v == null) return dash;
  const f = parseFloat(v);
  if (isNaN(f)) return dash;
  return '$' + f.toFixed(2);
}

function fmtPct(v, alreadyPct = true) {
  if (v == null) return dash;
  const f = parseFloat(v);
  if (isNaN(f)) return dash;
  const sign = f >= 0 ? '+' : '';
  return sign + f.toFixed(2) + '%';
}

function fmtMarketCap(v) {
  if (v == null) return dash;
  const f = parseFloat(v);
  if (isNaN(f) || f === 0) return dash;
  if (f >= 1e12) return '$' + (f / 1e12).toFixed(2) + 'T';
  if (f >= 1e9)  return '$' + (f / 1e9).toFixed(1)  + 'B';
  if (f >= 1e6)  return '$' + (f / 1e6).toFixed(1)  + 'M';
  return '$' + f.toFixed(0);
}

function fmtVolume(v) {
  if (v == null) return dash;
  const f = parseFloat(v);
  if (isNaN(f) || f === 0) return dash;
  if (f >= 1e9) return (f / 1e9).toFixed(2) + 'B';
  if (f >= 1e6) return (f / 1e6).toFixed(1) + 'M';
  if (f >= 1e3) return (f / 1e3).toFixed(0) + 'K';
  return f.toFixed(0);
}

function fmtRatioPct(v) {
  // for ebitdaMargins (0.35 → 35.0%) and dividendYield (0.0038 → 0.38%)
  if (v == null) return dash;
  const f = parseFloat(v);
  if (isNaN(f)) return dash;
  return (f * 100).toFixed(2) + '%';
}

function colorClass(v) {
  if (v == null) return '';
  return parseFloat(v) >= 0 ? 'green' : 'red';
}

function set(id, text, cls = '') {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.className = 'val' + (cls ? ' ' + cls : '');
}

function setRaw(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------
function initChart(data) {
  const ctx = document.getElementById('price-chart').getContext('2d');
  if (chart) { chart.destroy(); chart = null; }

  chart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: data.chart.dates,
      datasets: [
        {
          label: 'Price',
          data: data.chart.prices,
          borderColor: '#00ff88',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.1,
          fill: false,
          order: 0,
        },
        {
          label: 'SMA 20',
          data: data.chart.sma20,
          borderColor: '#58a6ff',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0,
          spanGaps: false,
          fill: false,
          order: 1,
        },
        {
          label: 'SMA 50',
          data: data.chart.sma50,
          borderColor: '#f0b429',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0,
          spanGaps: false,
          fill: false,
          order: 2,
        },
        {
          label: 'SMA 200',
          data: data.chart.sma200,
          borderColor: '#f778ba',
          borderWidth: 1,
          pointRadius: 0,
          tension: 0,
          spanGaps: false,
          fill: false,
          order: 3,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a1a',
          borderColor: '#2a2a2a',
          borderWidth: 1,
          titleColor: '#666',
          bodyColor: '#e0e0e0',
          padding: 10,
          callbacks: {
            label: (ctx) => {
              const v = ctx.parsed.y;
              if (v == null) return null;
              return ' ' + ctx.dataset.label + ': $' + v.toFixed(2);
            }
          }
        },
      },
      scales: {
        x: {
          grid:  { color: '#1a1a1a', drawBorder: false },
          ticks: { color: '#555', maxTicksLimit: 8, font: { family: 'JetBrains Mono', size: 10 } },
        },
        y: {
          position: 'right',
          grid:  { color: '#1a1a1a', drawBorder: false },
          ticks: {
            color: '#555',
            font: { family: 'JetBrains Mono', size: 10 },
            callback: (v) => '$' + v.toFixed(0),
          },
        },
      },
    },
  });
}

function updateChart(data) {
  if (!chart) { initChart(data); return; }
  chart.data.labels = data.chart.dates;
  chart.data.datasets[0].data = data.chart.prices;
  chart.data.datasets[1].data = data.chart.sma20;
  chart.data.datasets[2].data = data.chart.sma50;
  chart.data.datasets[3].data = data.chart.sma200;
  chart.update('active');
}

// SMA toggle buttons
document.querySelectorAll('.sma-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!chart) return;
    const idx = parseInt(btn.dataset.dataset);
    const ds = chart.data.datasets[idx];
    ds.hidden = !ds.hidden;
    btn.classList.toggle('active', !ds.hidden);
    chart.update();
  });
});
document.querySelectorAll('.cmp-sma-toggle').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!cmpChart) return;
    const idx = parseInt(btn.dataset.dataset);
    const ds = cmpChart.data.datasets[idx];
    if (!ds) return;
    ds.hidden = !ds.hidden;
    btn.classList.toggle('active', !ds.hidden);
    cmpChart.update();
  });
});

// ---------------------------------------------------------------------------
// Renderers
// ---------------------------------------------------------------------------
function renderHeader(h) {
  document.getElementById('hdr-name').textContent = h.company_name || dash;
  document.getElementById('hdr-ticker').textContent = h.ticker || '';
  document.getElementById('hdr-exchange').textContent = h.exchange || '';
  document.getElementById('hdr-sector').textContent = h.sector || '';
  document.getElementById('hdr-industry').textContent = h.industry || '';

  const priceEl = document.getElementById('hdr-price');
  priceEl.textContent = fmtPrice(h.current_price);

  const chg = h.change;
  const pct = h.change_pct;
  const cls = colorClass(chg);
  const chgEl = document.getElementById('hdr-change');
  const pctEl = document.getElementById('hdr-changepct');
  chgEl.textContent = chg != null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) : dash;
  chgEl.style.color = cls === 'green' ? 'var(--green)' : cls === 'red' ? 'var(--red)' : '';
  pctEl.textContent = fmtPct(pct);
  pctEl.style.color = cls === 'green' ? 'var(--green)' : cls === 'red' ? 'var(--red)' : '';

  document.getElementById('hdr-bid').textContent    = fmtPrice(h.bid);
  document.getElementById('hdr-ask').textContent    = fmtPrice(h.ask);
  document.getElementById('hdr-spread').textContent = h.spread != null ? h.spread.toFixed(2) : dash;

  if (h.last_updated) {
    try {
      const d = new Date(h.last_updated);
      document.getElementById('hdr-updated').textContent =
        'LAST ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
    } catch(e) {}
  }
}

function renderPriceStats(ps) {
  set('ps-open',      fmtPrice(ps.open));
  set('ps-prevclose', fmtPrice(ps.prev_close));
  set('ps-high',      fmtPrice(ps.day_high));
  set('ps-low',       fmtPrice(ps.day_low));
  set('ps-vwap',      fmtPrice(ps.vwap));

  document.getElementById('range-lo').textContent = fmtPrice(ps.week52_low);
  document.getElementById('range-hi').textContent = fmtPrice(ps.week52_high);

  const dot = document.getElementById('range-dot');
  const pct = ps.week52_pct != null ? Math.max(2, Math.min(98, ps.week52_pct)) : 50;
  dot.style.left = pct + '%';
}

function renderVolume(vol) {
  set('vol-current', fmtVolume(vol.current));
  set('vol-avg',     fmtVolume(vol.avg_30d));

  const ratioEl = document.getElementById('vol-ratio');
  const r = vol.ratio;
  if (r == null) {
    ratioEl.textContent = dash;
    ratioEl.style.color = '';
  } else if (r > 2) {
    ratioEl.textContent = r.toFixed(2) + 'x  2x SURGE';
    ratioEl.style.color = 'var(--green)';
  } else if (r > 1.5) {
    ratioEl.textContent = r.toFixed(2) + 'x  HIGH';
    ratioEl.style.color = 'var(--yellow)';
  } else {
    ratioEl.textContent = r.toFixed(2) + 'x';
    ratioEl.style.color = 'var(--text)';
  }
}

function renderFundamentals(f) {
  set('f-mktcap',  fmtMarketCap(f.market_cap));
  set('f-pe',      fmt(f.pe_trailing));
  set('f-fwdpe',   fmt(f.pe_forward));
  set('f-eps',     fmtPrice(f.eps_ttm));
  set('f-pb',      fmt(f.price_to_book));
  set('f-evebitda',fmt(f.ev_ebitda));
  set('f-rev',     fmtMarketCap(f.revenue_ttm));
  set('f-ebitdam', fmtRatioPct(f.ebitda_margin));
  set('f-div',     fmtRatioPct(f.dividend_yield));
}

function renderTechnicals(t) {
  const rsiVal = t.rsi.value;
  const rsiLbl = t.rsi.label;
  set('t-rsi-val', fmt(rsiVal));
  const rsiLblEl = document.getElementById('t-rsi-lbl');
  if (rsiLbl) {
    rsiLblEl.textContent = rsiLbl;
    rsiLblEl.style.color = rsiLbl === 'Overbought' ? 'var(--red)' : rsiLbl === 'Oversold' ? 'var(--green)' : 'var(--muted)';
  } else {
    rsiLblEl.textContent = '';
  }

  set('t-macd-val',  fmt(t.macd.value, 4));
  set('t-macd-sig',  fmt(t.macd.signal, 4));
  set('t-macd-hist', fmt(t.macd.histogram, 4));
  const dirEl = document.getElementById('t-macd-dir');
  dirEl.textContent = t.macd.direction || dash;
  dirEl.style.color = t.macd.direction === 'Bullish' ? 'var(--green)' : t.macd.direction === 'Bearish' ? 'var(--red)' : '';

  function renderSMA(valId, posId, sma) {
    set(valId, fmtPrice(sma.value));
    const posEl = document.getElementById(posId);
    posEl.textContent = sma.position || '';
    posEl.style.color = sma.position === 'Above' ? 'var(--green)' : sma.position === 'Below' ? 'var(--red)' : '';
  }
  renderSMA('t-sma20-val',  't-sma20-pos',  t.sma20);
  renderSMA('t-sma50-val',  't-sma50-pos',  t.sma50);
  renderSMA('t-sma200-val', 't-sma200-pos', t.sma200);

  set('t-beta', fmt(t.beta));
  set('t-hv', t.hv30d != null ? t.hv30d.toFixed(1) + '%' : dash);
}

function renderAnalyst(a) {
  const total = (a.buy || 0) + (a.hold || 0) + (a.sell || 0);
  if (total > 0) {
    document.getElementById('an-bar-buy').style.width  = ((a.buy  || 0) / total * 100) + '%';
    document.getElementById('an-bar-hold').style.width = ((a.hold || 0) / total * 100) + '%';
    document.getElementById('an-bar-sell').style.width = ((a.sell || 0) / total * 100) + '%';
  }

  document.getElementById('an-buy').textContent  = a.buy  != null ? a.buy  : dash;
  document.getElementById('an-hold').textContent = a.hold != null ? a.hold : dash;
  document.getElementById('an-sell').textContent = a.sell != null ? a.sell : dash;

  const consEl = document.getElementById('an-consensus');
  consEl.textContent = a.consensus || dash;
  if (a.consensus) {
    const c = a.consensus;
    consEl.style.color =
      c === 'Strong Buy'  ? 'var(--green)' :
      c === 'Buy'         ? '#66ff99'      :
      c === 'Strong Sell' ? 'var(--red)'   :
      c === 'Sell'        ? '#ff7777'      :
      'var(--yellow)';
  }

  set('an-target', fmtPrice(a.target_price));
  const upEl = document.getElementById('an-upside');
  upEl.textContent = fmtPct(a.implied_upside);
  upEl.style.color = a.implied_upside != null
    ? (a.implied_upside >= 0 ? 'var(--green)' : 'var(--red)')
    : '';
}

function renderAll(data) {
  renderHeader(data.header);
  renderPriceStats(data.price_stats);
  renderVolume(data.volume);
  renderFundamentals(data.fundamentals);
  renderTechnicals(data.technicals);
  renderAnalyst(data.analyst);
  updateChart(data);
}

// ---------------------------------------------------------------------------
// Show/hide states
// ---------------------------------------------------------------------------
function showSkeleton() {
  document.getElementById('skeleton').classList.remove('hidden');
  document.getElementById('app-body').style.display = 'none';
  document.getElementById('error-panel').style.display = 'none';
  document.getElementById('terminal-empty').style.display = 'none';
}

function hideSkeleton() {
  document.getElementById('skeleton').classList.add('hidden');
}

function showTerminal() {
  document.getElementById('app-body').style.display = 'block';
  document.getElementById('terminal-empty').style.display = 'none';
}

function showError(msg) {
  document.getElementById('error-msg').textContent = msg;
  document.getElementById('error-panel').style.display = 'block';
  document.getElementById('app-body').style.display = 'none';
  document.getElementById('terminal-empty').style.display = '';
  hideSkeleton();
}

function loadChip(ticker) {
  document.getElementById('ticker-input').value = ticker;
  loadTicker(ticker);
}

// ---------------------------------------------------------------------------
// Refresh timer
// ---------------------------------------------------------------------------
function startRefresh(symbol) {
  if (refreshInterval) clearInterval(refreshInterval);
  refreshCountdown = 60;
  updateRefreshDisplay();

  refreshInterval = setInterval(() => {
    refreshCountdown--;
    updateRefreshDisplay();
    if (refreshCountdown <= 0) {
      refreshCountdown = 60;
      loadTicker(symbol, true);
    }
  }, 1000);
}

function updateRefreshDisplay() {
  const el = document.getElementById('refresh-status');
  if (el) el.textContent = 'AUTO-REFRESH IN ' + refreshCountdown + 's';
}

// ---------------------------------------------------------------------------
// Main fetch
// ---------------------------------------------------------------------------
async function loadTicker(symbol, isRefresh = false) {
  currentSymbol = symbol;
  if (!isRefresh) showSkeleton();

  try {
    const res = await apiFetch('/api/ticker/' + encodeURIComponent(symbol));
    if (!res.ok) {
      let detail = 'Request failed with status ' + res.status;
      try { detail = (await res.json()).detail || detail; } catch(e) {}
      showError(detail);
      return;
    }
    const data = await res.json();
    renderAll(data);
    if (!isRefresh) {
      showTerminal();
      hideSkeleton();
      startRefresh(symbol);
    }
  } catch (e) {
    showError('Network error: ' + e.message);
  }
}

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------
document.getElementById('search-btn').addEventListener('click', () => {
  const sym = document.getElementById('ticker-input').value.trim().toUpperCase();
  if (sym) loadTicker(sym);
});

document.getElementById('ticker-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('search-btn').click();
});

document.getElementById('retry-btn').addEventListener('click', () => {
  if (currentSymbol) loadTicker(currentSymbol);
});

// Hide skeleton on initial page load
document.getElementById('skeleton').classList.add('hidden');

// ---------------------------------------------------------------------------
// Nav tab switching
// ---------------------------------------------------------------------------
const PAGES = ['terminal', 'portfolio', 'news', 'watchlist', 'earnings'];
document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const page = tab.dataset.page;
    document.getElementById('terminal-page').style.display      = page === 'terminal'  ? '' : 'none';
    document.getElementById('portfolio-page').style.display     = page === 'portfolio' ? 'block' : 'none';
    document.getElementById('news-page').style.display          = page === 'news'      ? 'block' : 'none';
    document.getElementById('watchlist-page').style.display     = page === 'watchlist' ? 'block' : 'none';
    document.getElementById('earnings-cal-page').style.display  = page === 'earnings'  ? 'block' : 'none';
    if (page === 'portfolio' && pfPositions.length > 0 && !pfData) loadPortfolio();
    if (page === 'news' && !newsLoaded) loadNews();
    if (page === 'watchlist') { loadMacro(); if (!wlLoaded && wlTickers.length > 0) loadWatchlist(); }
    if (page === 'earnings') ecInit();
  });
});

// ---------------------------------------------------------------------------
// Portfolio state
// ---------------------------------------------------------------------------
let pfPositions = JSON.parse(localStorage.getItem('pf_positions') || '[]');
let pfChart     = null;
let sectorChart = null;
let pfData      = null;
let mcChart     = null;
let mcDays      = 252;
const mcCache   = new Map();   // keyed by `days`; cleared on explicit re-run or position change

function savePfPositions() {
  localStorage.setItem('pf_positions', JSON.stringify(pfPositions));
  mcCache.clear();
}

// ---------------------------------------------------------------------------
// Portfolio formatting helpers
// ---------------------------------------------------------------------------
function pfFmtMoney(v) {
  if (v == null || isNaN(v)) return '—';
  return '$' + parseFloat(v).toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
}
function pfFmtPct(v) {
  if (v == null || isNaN(v)) return '—';
  const f = parseFloat(v);
  return (f >= 0 ? '+' : '') + f.toFixed(2) + '%';
}
function pfColor(v) {
  if (v == null || isNaN(v)) return '';
  return parseFloat(v) >= 0 ? 'var(--green)' : 'var(--red)';
}

// ---------------------------------------------------------------------------
// Render positions table (local data only, no prices yet)
// ---------------------------------------------------------------------------
function renderPfTable(data) {
  const hasData = data && data.positions && data.positions.length > 0;
  const localOnly = !data;

  document.getElementById('pf-empty').style.display = pfPositions.length === 0 ? '' : 'none';
  document.getElementById('pf-table-section').classList.toggle('hidden', pfPositions.length === 0);

  const tbody = document.getElementById('pf-tbody');
  tbody.innerHTML = '';

  const rows = data ? data.positions : pfPositions.map(p => ({
    ticker: p.ticker, company_name: p.ticker, sector: null,
    shares: p.shares, avg_cost: p.avg_cost,
    current_price: null, market_value: null, cost_basis: p.shares * p.avg_cost,
    pnl_dollar: null, pnl_pct: null, day_change_dollar: null, day_change_pct: null, weight: null,
  }));

  rows.forEach((pos, i) => {
    const tr = document.createElement('tr');
    const weightFlag = pos.weight && pos.weight > 20 ? ' pf-concentration' : '';
    tr.innerHTML = `
      <td>
        <span class="pf-ticker-lnk" onclick="jumpToTerminal('${pos.ticker}')">${pos.ticker}</span>
        <span class="pf-name">${pos.company_name || ''}</span>
      </td>
      <td>${pos.shares}</td>
      <td>${pfFmtMoney(pos.avg_cost)}</td>
      <td>${pos.current_price != null ? pfFmtMoney(pos.current_price) : '—'}</td>
      <td>${pos.market_value != null ? pfFmtMoney(pos.market_value) : '—'}</td>
      <td>${pfFmtMoney(pos.cost_basis)}</td>
      <td style="color:${pfColor(pos.pnl_dollar)}">${pfFmtMoney(pos.pnl_dollar)}</td>
      <td style="color:${pfColor(pos.pnl_pct)}">${pfFmtPct(pos.pnl_pct)}</td>
      <td style="color:${pfColor(pos.day_change_dollar)}">${pos.day_change_dollar != null ? pfFmtMoney(pos.day_change_dollar) : '—'}</td>
      <td style="color:${pfColor(pos.day_change_pct)}">${pfFmtPct(pos.day_change_pct)}</td>
      <td class="${weightFlag}">${pos.weight != null ? pos.weight.toFixed(1) + '%' : '—'}</td>
      <td><button class="pf-del-btn" onclick="deletePosition(${i})">✕</button></td>
    `;
    tbody.appendChild(tr);
  });

  // Totals row
  if (data) {
    const t = data.totals;
    document.getElementById('tot-mv').textContent = pfFmtMoney(t.market_value);
    document.getElementById('tot-cb').textContent = pfFmtMoney(t.cost_basis);
    const pnlEl = document.getElementById('tot-pnl');
    pnlEl.textContent = pfFmtMoney(t.pnl_dollar);
    pnlEl.style.color = pfColor(t.pnl_dollar);
    const pnlPctEl = document.getElementById('tot-pnl-pct');
    pnlPctEl.textContent = pfFmtPct(t.pnl_pct);
    pnlPctEl.style.color = pfColor(t.pnl_pct);
    const dayEl = document.getElementById('tot-day');
    dayEl.textContent = t.day_change_dollar != null ? pfFmtMoney(t.day_change_dollar) : '—';
    dayEl.style.color = pfColor(t.day_change_dollar);
    const dayPctEl = document.getElementById('tot-day-pct');
    dayPctEl.textContent = pfFmtPct(t.day_change_pct);
    dayPctEl.style.color = pfColor(t.day_change_pct);
  }
}

// ---------------------------------------------------------------------------
// Render metrics panel
// ---------------------------------------------------------------------------
function renderMetrics(data) {
  const m = data.metrics;
  const t = data.totals;

  const tvEl = document.getElementById('m-total-value');
  tvEl.textContent = pfFmtMoney(m.total_value);

  document.getElementById('m-positions-count').textContent = m.num_positions + ' position' + (m.num_positions !== 1 ? 's' : '');

  const pnlEl = document.getElementById('m-pnl-dollar');
  pnlEl.textContent = pfFmtMoney(t.pnl_dollar);
  pnlEl.style.color = pfColor(t.pnl_dollar);
  const pnlPctEl = document.getElementById('m-pnl-pct');
  pnlPctEl.textContent = pfFmtPct(t.pnl_pct);
  pnlPctEl.style.color = pfColor(t.pnl_pct);

  const dayEl = document.getElementById('m-day-dollar');
  dayEl.textContent = t.day_change_dollar != null ? pfFmtMoney(t.day_change_dollar) : '—';
  dayEl.style.color = pfColor(t.day_change_dollar);
  const dayPctEl = document.getElementById('m-day-pct');
  dayPctEl.textContent = pfFmtPct(t.day_change_pct);
  dayPctEl.style.color = pfColor(t.day_change_pct);

  const betaEl = document.getElementById('m-beta');
  betaEl.textContent = m.beta != null ? m.beta.toFixed(2) : '—';
  betaEl.style.color = m.beta != null && m.beta > 1.5 ? 'var(--yellow)' : '';

  const hvEl = document.getElementById('m-hv');
  hvEl.textContent = m.hv30d != null ? m.hv30d.toFixed(1) + '%' : '—';

  const sharpeEl = document.getElementById('m-sharpe');
  sharpeEl.textContent = m.sharpe != null ? m.sharpe.toFixed(2) : '—';
  sharpeEl.style.color = m.sharpe != null && m.sharpe < 0 ? 'var(--red)' : '';

  const ddEl = document.getElementById('m-drawdown');
  ddEl.textContent = m.max_drawdown != null ? m.max_drawdown.toFixed(1) + '%' : '—';
  ddEl.style.color = m.max_drawdown != null ? 'var(--red)' : '';

  const concEl = document.getElementById('m-conc-count');
  const flags = m.concentration_flags || [];
  if (flags.length === 0) {
    concEl.textContent = 'None';
    concEl.style.color = 'var(--green)';
    document.getElementById('conc-list').textContent = '';
  } else {
    concEl.textContent = flags.length + ' position' + (flags.length > 1 ? 's' : '');
    concEl.style.color = 'var(--yellow)';
    document.getElementById('conc-list').textContent = flags.join(', ') + ' > 20%';
  }
}

// ---------------------------------------------------------------------------
// Render sector chart
// ---------------------------------------------------------------------------
function renderSectorChart(sectors) {
  const labels = Object.keys(sectors);
  const values = Object.values(sectors);
  const ctx = document.getElementById('sector-chart').getContext('2d');
  if (sectorChart) { sectorChart.destroy(); sectorChart = null; }

  const colors = ['#4fc3f7','#00ff88','#ffb74d','#f48fb1','#ce93d8','#80cbc4','#a5d6a7','#fff176','#ffcc80','#ef9a9a'];

  sectorChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors.slice(0, labels.length),
        borderWidth: 0,
        borderRadius: 1,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a1a', borderColor: '#2a2a2a', borderWidth: 1,
          callbacks: { label: ctx => ' ' + ctx.parsed.x.toFixed(1) + '%' }
        }
      },
      scales: {
        x: {
          grid: { color: '#1a1a1a' },
          ticks: { color: '#555', font: { family: 'JetBrains Mono', size: 10 }, callback: v => v.toFixed(0) + '%' },
        },
        y: {
          grid: { display: false },
          ticks: { color: '#888', font: { family: 'JetBrains Mono', size: 10 } },
        }
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Render correlation heatmap
// ---------------------------------------------------------------------------
function renderCorrelation(corr) {
  const container = document.getElementById('corr-container');
  if (!corr || !corr.tickers || corr.tickers.length < 2) {
    container.innerHTML = '<div style="color:var(--muted);font-size:11px">Need ≥2 positions for correlation.</div>';
    return;
  }
  const tickers = corr.tickers;
  const values  = corr.values;

  function corrColor(v) {
    if (v == null) return '#222';
    // -1 → red, 0 → #333, +1 → green
    if (v >= 0) {
      const t = v;
      const r = Math.round(0 + t * 0);
      const g = Math.round(80 + t * (255 - 80));
      const b = Math.round(60 + t * (60 - 60));
      return `rgb(${Math.round(40*(1-t))},${g},${Math.round(60*(1-t))})`;
    } else {
      const t = -v;
      return `rgb(${Math.round(80 + t*175)},${Math.round(40*(1-t))},${Math.round(40*(1-t))})`;
    }
  }

  function textColor(v) {
    if (v == null) return '#555';
    return Math.abs(v) > 0.4 ? '#000' : '#aaa';
  }

  let html = '<table class="corr-table"><thead><tr><th></th>';
  tickers.forEach(t => { html += `<th>${t}</th>`; });
  html += '</tr></thead><tbody>';
  tickers.forEach((rowT, r) => {
    html += `<tr><th style="text-align:right;padding-right:8px">${rowT}</th>`;
    tickers.forEach((colT, c) => {
      const v = values[r][c];
      const bg = corrColor(v);
      const fg = textColor(v);
      html += `<td style="background:${bg};color:${fg}">${v != null ? v.toFixed(2) : '—'}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Render portfolio chart
// ---------------------------------------------------------------------------
function renderPfChart(chartData) {
  if (!chartData) return;
  const ctx = document.getElementById('pf-chart').getContext('2d');
  if (pfChart) { pfChart.destroy(); pfChart = null; }

  const datasets = [
    {
      label: 'Portfolio',
      data: chartData.portfolio,
      borderColor: '#00ff88', borderWidth: 2,
      pointRadius: 0, tension: 0.1, fill: false, order: 0,
    }
  ];
  if (chartData.spy) {
    datasets.push({
      label: 'SPY',
      data: chartData.spy,
      borderColor: '#4fc3f7', borderWidth: 1,
      pointRadius: 0, tension: 0, fill: false, order: 1,
    });
  }

  pfChart = new Chart(ctx, {
    type: 'line',
    data: { labels: chartData.dates, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#1a1a1a', borderColor: '#2a2a2a', borderWidth: 1,
          titleColor: '#666', bodyColor: '#e0e0e0', padding: 10,
          callbacks: { label: ctx => { const v = ctx.parsed.y; return v != null ? ' ' + ctx.dataset.label + ': $' + v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}) : null; } }
        }
      },
      scales: {
        x: { grid: { color: '#1a1a1a' }, ticks: { color: '#555', maxTicksLimit: 8, font: { family: 'JetBrains Mono', size: 10 } } },
        y: { position: 'right', grid: { color: '#1a1a1a' }, ticks: { color: '#555', font: { family: 'JetBrains Mono', size: 10 }, callback: v => '$' + v.toLocaleString('en-US',{maximumFractionDigits:0}) } }
      }
    }
  });

  // SPY toggle
  document.getElementById('spy-toggle').addEventListener('click', function() {
    if (!pfChart || pfChart.data.datasets.length < 2) return;
    const ds = pfChart.data.datasets[1];
    ds.hidden = !ds.hidden;
    this.classList.toggle('active', !ds.hidden);
    pfChart.update();
  });
}

// ---------------------------------------------------------------------------
// Load portfolio from API
// ---------------------------------------------------------------------------
async function loadPortfolio() {
  if (pfPositions.length === 0) { renderPfTable(null); return; }
  const btn = document.getElementById('pf-load-btn');
  btn.textContent = `Loading ${pfPositions.length} positions…`;
  btn.disabled = true;
  try {
    // Extend timeout — yfinance pulls + risk metrics can take 30-50s in Railway
    // cold pods, especially with many positions or rate-limited Yahoo responses.
    const res = await apiFetch('/api/portfolio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions: pfPositions }),
    }, 60000);
    if (!res.ok) {
      let d = 'Failed'; try { d = (await res.json()).detail; } catch(e) {}
      alert('Portfolio error: ' + d); return;
    }
    pfData = await res.json();
    renderPfTable(pfData);
    renderMetrics(pfData);
    if (pfData.sectors) renderSectorChart(pfData.sectors);
    if (pfData.correlation) renderCorrelation(pfData.correlation);
    if (pfData.chart) renderPfChart(pfData.chart);
    const mcBtn = document.getElementById('pf-mc-btn');
    if (mcBtn) mcBtn.style.display = '';
    // Re-run news impact now that we have sector info for each holding
    if (newsLoaded) loadPortfolioNewsImpact();
  } catch(e) {
    const isTimeout = e.name === 'AbortError' || /abort/i.test(e.message || '');
    alert(isTimeout
      ? 'Request timed out — Yahoo Finance is slow right now. Hit Refresh Prices to try again.'
      : 'Network error: ' + e.message);
  } finally {
    btn.textContent = 'Refresh Prices';
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Monte Carlo simulation
// ---------------------------------------------------------------------------
function triggerMonteCarlo() {
  mcCache.clear();   // explicit re-run: drop all cached timeframes for fresh paths
  const panel = document.getElementById('pf-mc-panel');
  if (panel) panel.style.display = '';
  loadMonteCarlo();
}

async function loadMonteCarlo() {
  if (!pfPositions.length) return;
  if (mcCache.has(mcDays)) {
    const cached = mcCache.get(mcDays);
    renderMCChart(cached);
    renderMCStats(cached.stats, cached.initial_value, cached.model_inputs);
    return;
  }
  const btn = document.getElementById('pf-mc-btn');
  if (btn) { btn.textContent = 'Running…'; btn.disabled = true; }
  try {
    const res = await apiFetch('/api/portfolio/montecarlo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ positions: pfPositions, days: mcDays }),
    }, 90000);
    const data = await res.json();
    mcCache.set(mcDays, data);
    renderMCChart(data);
    renderMCStats(data.stats, data.initial_value, data.model_inputs);
  } catch (err) {
    console.warn('Monte Carlo failed:', err);
    const statsEl = document.getElementById('pf-mc-stats');
    if (statsEl) statsEl.innerHTML = `<div style="color:var(--red);font-size:11px;padding:8px">Simulation failed: ${err.message || err}</div>`;
  } finally {
    if (btn) { btn.textContent = 'Run Monte Carlo'; btn.disabled = false; }
  }
}

function renderMCChart(data) {
  if (!data || !data.paths) return;
  const p      = data.paths;
  const step   = Math.max(1, Math.ceil(data.days / 10));
  const labels = Array.from({ length: data.days + 1 }, (_, i) => i === 0 ? 'Now' : (i % step === 0 ? `Day ${i}` : ''));
  if (mcChart) { mcChart.destroy(); mcChart = null; }
  const canvas = document.getElementById('pf-mc-chart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  mcChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Best (95th)',    data: p.p95, borderColor: '#00ff88', borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0 },
        { label: '75th Pct',      data: p.p75, borderColor: '#4fc3f7', borderWidth: 1,   pointRadius: 0, fill: false, tension: 0 },
        { label: 'Median (50th)', data: p.p50, borderColor: '#e0e0e0', borderWidth: 2,   pointRadius: 0, fill: false, tension: 0 },
        { label: '25th Pct',      data: p.p25, borderColor: '#ff9800', borderWidth: 1,   pointRadius: 0, fill: false, tension: 0 },
        { label: 'Worst (5th)',   data: p.p5,  borderColor: '#ff5252', borderWidth: 1.5, pointRadius: 0, fill: false, tension: 0 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: { duration: 400 },
      plugins: {
        legend: { labels: { color: '#777', font: { family: 'JetBrains Mono', size: 10 }, boxWidth: 12 } },
        tooltip: {
          mode: 'index', intersect: false,
          callbacks: {
            label: ctx => `${ctx.dataset.label}: $${Math.round(ctx.parsed.y).toLocaleString('en-US')}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: '#555', font: { family: 'JetBrains Mono', size: 9 }, maxRotation: 0 }, grid: { color: '#1a1a1a' } },
        y: { ticks: { color: '#555', font: { family: 'JetBrains Mono', size: 9 }, callback: v => '$' + Math.round(v).toLocaleString() }, grid: { color: '#1a1a1a' } },
      },
    },
  });
}

function renderMCStats(stats, initialValue, modelInputs) {
  const el = document.getElementById('pf-mc-stats');
  if (!el || !stats) return;
  const fmtPct  = v => (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
  const fmtMoney = v => '$' + Math.round(v).toLocaleString('en-US');
  const p5ret = stats.p5_return;

  const statsGrid = `
    <div class="pf-mc-stats-grid">
      <div class="pf-mc-stat"><span class="mc-label">Expected Return</span><span class="mc-val ${stats.expected_return >= 0 ? 'pos' : 'neg'}">${fmtPct(stats.expected_return)}</span></div>
      <div class="pf-mc-stat"><span class="mc-label">5th %ile Return</span><span class="mc-val ${p5ret >= 0 ? 'pos' : 'neg'}">${fmtPct(p5ret)}</span></div>
      <div class="pf-mc-stat"><span class="mc-label">P(Gain)</span><span class="mc-val">${stats.prob_gain}%</span></div>
      <div class="pf-mc-stat"><span class="mc-label">Median Final</span><span class="mc-val">${fmtMoney(stats.median_final)}</span></div>
      <div class="pf-mc-stat"><span class="mc-label">Best Case (95th)</span><span class="mc-val pos">${fmtMoney(stats.p95_final)}</span></div>
      <div class="pf-mc-stat"><span class="mc-label">Worst Case (5th)</span><span class="mc-val neg">${fmtMoney(stats.p5_final)}</span></div>
    </div>
  `;

  let warnHtml = '';
  let modelHtml = '';
  if (modelInputs && typeof modelInputs.sigma_annual_portfolio === 'number') {
    const sigmaP = modelInputs.sigma_annual_portfolio;
    if (sigmaP > 70) {
      warnHtml = `
        <div class="pf-mc-warn">
          High-volatility portfolio (σ ≈ ${sigmaP.toFixed(1)}% annualized). Under GBM, median and mean can diverge substantially: the Itô correction (−½σ²) pulls the median down while the right tail lifts the mean. This is a property of the model, not an error.
        </div>
      `;
    }
    const rows = (modelInputs.per_asset || []).map(a => {
      const tk = safeTicker(a.ticker);
      return `<div class="mi-row"><span class="mi-tk">${tk}</span><span>σ ${a.sigma_annual.toFixed(1)}%</span><span>β ${a.beta.toFixed(2)}</span><span>w ${a.weight.toFixed(1)}%</span></div>`;
    }).join('');
    modelHtml = `
      <div class="pf-mc-model-inputs">
        <div class="mi-head">Model inputs · portfolio σ ${sigmaP.toFixed(1)}% annualized</div>
        ${rows}
      </div>
    `;
  }

  el.innerHTML = statsGrid + warnHtml + modelHtml;
}

// Timeframe pill wiring
document.querySelectorAll('.pf-mc-tf').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.pf-mc-tf').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    mcDays = parseInt(btn.dataset.days, 10);
    loadMonteCarlo();
  });
});

// ---------------------------------------------------------------------------
// Add / delete positions
// ---------------------------------------------------------------------------
function addPosition() {
  const ticker = document.getElementById('pf-ticker').value.trim().toUpperCase();
  const shares  = parseFloat(document.getElementById('pf-shares').value);
  const cost    = parseFloat(document.getElementById('pf-cost').value);
  if (!ticker || isNaN(shares) || shares <= 0 || isNaN(cost) || cost <= 0) {
    alert('Enter a valid ticker, shares, and avg cost.'); return;
  }
  const existing = pfPositions.findIndex(p => p.ticker === ticker);
  if (existing >= 0) {
    pfPositions[existing] = { ticker, shares, avg_cost: cost };
  } else {
    pfPositions.push({ ticker, shares, avg_cost: cost });
  }
  savePfPositions();
  document.getElementById('pf-ticker').value = '';
  document.getElementById('pf-shares').value = '';
  document.getElementById('pf-cost').value = '';
  renderPfTable(null);
}

function deletePosition(i) {
  pfPositions.splice(i, 1);
  savePfPositions();
  pfData = null;
  renderPfTable(null);
  document.getElementById('corr-container').innerHTML = '<div style="color:var(--muted);font-size:11px">Load prices to compute correlations.</div>';
}

function jumpToTerminal(ticker) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.querySelector('.nav-tab[data-page="terminal"]').classList.add('active');
  document.getElementById('terminal-page').style.display  = '';
  document.getElementById('portfolio-page').style.display = 'none';
  document.getElementById('news-page').style.display      = 'none';
  document.getElementById('ticker-input').value = ticker;
  loadTicker(ticker);
}

document.getElementById('pf-add-btn').addEventListener('click', addPosition);
document.getElementById('pf-load-btn').addEventListener('click', loadPortfolio);
document.getElementById('pf-ticker').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('pf-shares').focus(); });
document.getElementById('pf-shares').addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('pf-cost').focus(); });
document.getElementById('pf-cost').addEventListener('keydown', e => { if (e.key === 'Enter') addPosition(); });

// Render saved positions on load
renderPfTable(null);

// ---------------------------------------------------------------------------
// News
// ---------------------------------------------------------------------------
let newsSortMode = 'date'; // 'date' | 'score'
let newsLoaded = false;
let newsArticles = [];
let newsActiveFilter = 'All';
let newsRefreshTimer = null;

const CAT_CLASS = {
  'Fed/Monetary Policy': 'cat-fed',
  'Geopolitics':         'cat-geo',
  'Commodities':         'cat-comm',
  'Tech/AI':             'cat-tech',
  'Markets':             'cat-markets',
  'Macro Economy':       'cat-macro',
};

function scoreDots(score) {
  if (score >= 10) {
    return Array(5).fill('<span class="score-dot dot-red"></span>').join('');
  } else if (score >= 8) {
    return Array(4).fill('<span class="score-dot dot-orange"></span>').join('');
  } else {
    return Array(3).fill('<span class="score-dot dot-gray"></span>').join('');
  }
}

function timeAgo(isoStr) {
  if (!isoStr) return '';
  try {
    const diff = (Date.now() - new Date(isoStr).getTime()) / 1000;
    if (diff < 3600)  return Math.round(diff / 60)  + 'm ago';
    if (diff < 86400) return Math.round(diff / 3600) + 'h ago';
    return Math.round(diff / 86400) + 'd ago';
  } catch(e) { return ''; }
}

function renderNewsCards(articles) {
  const feed = document.getElementById('news-feed');
  const empty = document.getElementById('news-empty');

  let filtered = newsActiveFilter === 'All'
    ? articles
    : articles.filter(a => a.category === newsActiveFilter);

  // Portfolio-only filter
  if (typeof _nfPfOnly !== 'undefined' && _nfPfOnly) {
    const affectedIds = new Set((_pfImpacts || []).map(i => i.article_id));
    filtered = filtered.filter(a => affectedIds.has(newsArticles.indexOf(a)));
  }

  // Sort by user-selected mode
  filtered = [...filtered].sort((a, b) => {
    if (newsSortMode === 'score') {
      const sd = (b.importance_score || 0) - (a.importance_score || 0);
      if (sd !== 0) return sd;
      const ta = a.published_at ? new Date(a.published_at).getTime() : 0;
      const tb = b.published_at ? new Date(b.published_at).getTime() : 0;
      return tb - ta;
    }
    // default: newest first, tiebreak by score
    const ta = a.published_at ? new Date(a.published_at).getTime() : 0;
    const tb = b.published_at ? new Date(b.published_at).getTime() : 0;
    if (tb !== ta) return tb - ta;
    return (b.importance_score || 0) - (a.importance_score || 0);
  });

  if (filtered.length === 0) {
    feed.classList.add('hidden');
    empty.classList.remove('hidden');
    return;
  }
  empty.classList.add('hidden');
  feed.classList.remove('hidden');

  feed.innerHTML = filtered.map((a, i) => {
    const origIdx  = newsArticles.indexOf(a);
    const impacts  = _articleImpacts(origIdx);
    const catCls   = CAT_CLASS[a.category] || 'cat-macro';
    const isCrit   = a.importance_score >= 10;
    const hasPfHit = impacts.length > 0;
    const delay    = Math.min(i * 60, 400);

    const impactHtml = hasPfHit ? `
      <div class="pf-impact-bar">
        <div class="pf-impact-hdr">▸ YOUR PORTFOLIO</div>
        ${impacts.map(imp => `
          <div class="pf-impact-row">
            <span class="pf-impact-ticker ${imp.direction}">${imp.ticker}</span>
            <span class="pf-impact-note">${imp.note}</span>
          </div>`).join('')}
      </div>` : '';

    return `
      <div class="news-card${isCrit ? ' critical' : ''}${hasPfHit ? ' pf-hit' : ''}" style="animation-delay:${delay}ms">
        <div class="card-top">
          <span class="cat-badge ${catCls}">${a.category}</span>
          <span class="score-dots">${scoreDots(a.importance_score)}</span>
          ${isCrit ? '<span class="critical-label">CRITICAL</span>' : ''}
        </div>
        <a class="card-headline" href="${a.url || '#'}" target="_blank" rel="noopener">${a.title}</a>
        <div class="card-meta">
          <span class="src">${a.source}</span>
          ${a.published_at ? ' &middot; ' + timeAgo(a.published_at) : ''}
        </div>
        ${a.market_impact ? `<div class="card-impact">${a.market_impact}</div>` : ''}
        ${impactHtml}
      </div>
    `;
  }).join('');
}

async function loadNews(force = false) {
  const skeleton = document.getElementById('news-skeleton');
  const feed     = document.getElementById('news-feed');
  const empty    = document.getElementById('news-empty');

  skeleton.style.display = '';
  feed.classList.add('hidden');
  empty.classList.add('hidden');

  try {
    const url = force ? '/api/news?refresh=true' : '/api/news';
    const res = await apiFetch(url, {}, 60000);
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    newsArticles = data.articles || [];
    newsLoaded = true;

    skeleton.style.display = 'none';
    renderNewsCards(newsArticles);
    // Async — doesn't block render; re-renders when impact data arrives
    loadPortfolioNewsImpact();

    const ts = data.cached_at ? new Date(data.cached_at) : new Date();
    document.getElementById('news-last-updated').textContent =
      'Updated ' + ts.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});

    // auto-refresh every 15 min
    if (newsRefreshTimer) clearTimeout(newsRefreshTimer);
    newsRefreshTimer = setTimeout(() => {
      newsLoaded = false;
      if (document.getElementById('news-page').style.display !== 'none') loadNews();
    }, 15 * 60 * 1000);

  } catch(e) {
    skeleton.style.display = 'none';
    empty.textContent = 'Failed to load news: ' + e.message;
    empty.classList.remove('hidden');
  }
}

// Category filter — scoped to [data-cat] only so sort buttons keep their active state
document.querySelectorAll('.filter-btn[data-cat]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn[data-cat]').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    newsActiveFilter = btn.dataset.cat;
    renderNewsCards(newsArticles);
  });
});

// Sort buttons
document.getElementById('sort-date')?.addEventListener('click', function() {
  newsSortMode = 'date';
  document.querySelectorAll('#sort-date, #sort-score').forEach(b => b.classList.remove('active'));
  this.classList.add('active');
  renderNewsCards(newsArticles);
});
document.getElementById('sort-score')?.addEventListener('click', function() {
  newsSortMode = 'score';
  document.querySelectorAll('#sort-date, #sort-score').forEach(b => b.classList.remove('active'));
  this.classList.add('active');
  renderNewsCards(newsArticles);
});

// Refresh button — disables itself while fetching, shows progress text
document.getElementById('news-refresh-btn').addEventListener('click', function() {
  newsLoaded = false;
  const btn = this;
  btn.disabled = true;
  btn.textContent = '↻ Refreshing…';
  loadNews(true).finally(() => {
    btn.disabled = false;
    btn.textContent = '↻ Refresh';
  });
});

// ---------------------------------------------------------------------------
// Nav — update to handle watchlist tab
// ---------------------------------------------------------------------------
// patch the existing nav handler to also show/hide watchlist-page
const _origNavHandler = document.querySelectorAll('.nav-tab');
_origNavHandler.forEach(tab => {
  // remove old listeners by cloning (avoids double-fire)
});
// Re-bind all tab clicks cleanly
document.querySelectorAll('.nav-tab').forEach(tab => {
  const clone = tab.cloneNode(true);
  tab.parentNode.replaceChild(clone, tab);
});
document.querySelectorAll('.nav-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const page = tab.dataset.page;
    document.getElementById('terminal-page').style.display      = page === 'terminal'  ? '' : 'none';
    document.getElementById('portfolio-page').style.display     = page === 'portfolio' ? 'block' : 'none';
    document.getElementById('news-page').style.display          = page === 'news'      ? 'block' : 'none';
    document.getElementById('watchlist-page').style.display     = page === 'watchlist' ? 'block' : 'none';
    document.getElementById('earnings-cal-page').style.display  = page === 'earnings'  ? 'block' : 'none';
    document.getElementById('alerts-page').style.display        = page === 'alerts'    ? 'block' : 'none';
    document.getElementById('screener-page').style.display      = page === 'screener'  ? 'block' : 'none';
    document.getElementById('yields-page').style.display        = page === 'yields'    ? 'block' : 'none';
    if (page === 'portfolio' && pfPositions.length > 0 && !pfData) loadPortfolio();
    if (page === 'portfolio' && authToken) loadTransactions();
    if (page === 'news'      && !newsLoaded) loadNews();
    if (page === 'watchlist') { loadMacro(); if (!wlLoaded && wlTickers.length > 0) loadWatchlist(); }
    if (page === 'earnings') ecInit();
    if (page === 'alerts' && authToken) loadAlerts();
    if (page === 'screener') initScreener();
    if (page === 'yields') yieldsInit();
  });
});

// ---------------------------------------------------------------------------
// Macro Dashboard
// ---------------------------------------------------------------------------
let macroInterval = null;

async function loadMacro() {
  try {
    const res = await apiFetch('/api/macro');
    if (!res.ok) return;
    const data = await res.json();
    renderMacro(data.indicators || []);
    const el = document.getElementById('macro-last-updated');
    if (el) el.textContent = 'MACRO UPDATED ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  } catch(e) {}
  if (!macroInterval) {
    macroInterval = setInterval(() => {
      if (document.getElementById('watchlist-page').style.display !== 'none') loadMacro();
    }, 60000);
  }
}

function renderMacro(indicators) {
  const grid = document.getElementById('macro-grid');
  if (!grid) return;
  grid.innerHTML = indicators.map(ind => {
    const chgPct = ind.change_pct;
    const color  = chgPct == null ? '' : chgPct >= 0 ? 'var(--green)' : 'var(--red)';
    const sign   = chgPct != null && chgPct >= 0 ? '+' : '';
    const priceStr = ind.price != null ? formatMacroPrice(ind.name, ind.price) : '—';
    const chgStr   = chgPct != null ? `${sign}${chgPct.toFixed(2)}%` : '—';
    const dirClass = chgPct == null ? '' : chgPct >= 0 ? 'up' : 'down';
    return `
      <div class="macro-card ${dirClass}">
        <span class="mc-name">${ind.name}</span>
        <span class="mc-price">${priceStr}</span>
        <div class="mc-chg" style="color:${color}">${chgStr}</div>
      </div>`;
  }).join('');
}

function formatMacroPrice(name, v) {
  if (v == null) return '—';
  if (name === 'BTC') return '$' + v.toLocaleString('en-US', {maximumFractionDigits: 0});
  if (name === 'VIX') return v.toFixed(2);
  if (name === '10Y Yield') return v.toFixed(3) + '%';
  if (name === 'DXY') return v.toFixed(2);
  if (name.includes('Oil') || name.includes('Gold')) return '$' + v.toFixed(2);
  return v.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

// ---------------------------------------------------------------------------
// Watchlist
// ---------------------------------------------------------------------------
let wlTickers  = JSON.parse(localStorage.getItem('wl_tickers') || '[]');
let wlData     = [];
let wlLoaded   = false;

function saveWlTickers() { localStorage.setItem('wl_tickers', JSON.stringify(wlTickers)); }

function renderWlTable(positions) {
  const wrap  = document.getElementById('wl-table-wrap');
  const empty = document.getElementById('wl-empty');
  if (wlTickers.length === 0) { wrap.classList.add('hidden'); empty.classList.remove('hidden'); return; }
  wrap.classList.remove('hidden'); empty.classList.add('hidden');

  const rows = positions.length > 0 ? positions : wlTickers.map(t => ({ ticker: t, company_name: t }));
  document.getElementById('wl-tbody').innerHTML = rows.map((p, i) => {
    const chgColor = p.change_pct != null ? (p.change_pct >= 0 ? 'var(--green)' : 'var(--red)') : '';
    const sign     = p.change_pct != null && p.change_pct >= 0 ? '+' : '';
    let rangeHtml  = '—';
    if (p.week52_low != null && p.week52_high != null && p.current_price != null && p.week52_high !== p.week52_low) {
      const pct = Math.max(2, Math.min(98, (p.current_price - p.week52_low) / (p.week52_high - p.week52_low) * 100));
      rangeHtml = `<span class="mini-range"><span class="mini-dot" style="left:${pct}%"></span></span>`;
    }
    return `<tr onclick="jumpToTerminal('${p.ticker}')">
      <td><span class="wl-ticker-cell">${p.ticker}</span><span class="wl-name-cell">${p.company_name || ''}</span></td>
      <td>${p.current_price != null ? '$' + p.current_price.toFixed(2) : '—'}</td>
      <td style="color:${chgColor}">${p.change != null ? (p.change >= 0 ? '+' : '') + '$' + Math.abs(p.change).toFixed(2) : '—'}</td>
      <td style="color:${chgColor}">${p.change_pct != null ? sign + p.change_pct.toFixed(2) + '%' : '—'}</td>
      <td>${p.market_cap != null ? fmtMarketCap(p.market_cap) : '—'}</td>
      <td>${p.pe_trailing != null ? p.pe_trailing.toFixed(1) : '—'}</td>
      <td>${p.volume != null ? fmtVolume(p.volume) : '—'}</td>
      <td>${p.day_high != null ? '$' + p.day_high.toFixed(2) : '—'}</td>
      <td>${p.day_low != null ? '$' + p.day_low.toFixed(2) : '—'}</td>
      <td>${rangeHtml}</td>
      <td onclick="event.stopPropagation()"><button class="wl-del" onclick="removeWlTicker(${i})">✕</button></td>
    </tr>`;
  }).join('');
}

async function loadWatchlist() {
  if (wlTickers.length === 0) { renderWlTable([]); return; }
  const status = document.getElementById('wl-status');
  if (status) status.textContent = 'Loading...';
  try {
    const res = await apiFetch('/api/watchlist?tickers=' + encodeURIComponent(wlTickers.join(',')));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    wlData   = data.positions || [];
    wlLoaded = true;
    renderWlTable(wlData);
    if (status) status.textContent = 'Updated ' + new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
  } catch(e) {
    if (status) status.textContent = 'Error: ' + e.message;
  }
}

function addWlTicker() {
  const val = document.getElementById('wl-ticker-input').value.trim().toUpperCase();
  if (!val) return;
  if (wlTickers.includes(val)) { alert(val + ' already in watchlist'); return; }
  wlTickers.push(val);
  saveWlTickers();
  document.getElementById('wl-ticker-input').value = '';
  wlLoaded = false;
  renderWlTable([]);
  loadWatchlist();
}

function removeWlTicker(i) {
  wlTickers.splice(i, 1);
  saveWlTickers();
  wlData.splice(i, 1);
  renderWlTable(wlData);
}

document.getElementById('wl-add-btn').addEventListener('click', addWlTicker);
document.getElementById('wl-refresh-btn').addEventListener('click', () => { wlLoaded = false; loadWatchlist(); });
document.getElementById('wl-ticker-input').addEventListener('keydown', e => { if (e.key === 'Enter') addWlTicker(); });

// Initial render from localStorage
renderWlTable([]);

// ---------------------------------------------------------------------------
// Earnings Calendar
// ---------------------------------------------------------------------------
async function loadEarnings() {
  if (pfPositions.length === 0) return;
  const tickers = pfPositions.map(p => p.ticker).join(',');
  try {
    const res = await apiFetch('/api/earnings?tickers=' + encodeURIComponent(tickers));
    if (!res.ok) return;
    const data = await res.json();
    renderEarnings(data.earnings || []);
  } catch(e) {}
}

function renderEarnings(earnings) {
  const panel = document.getElementById('earnings-panel');
  const tbody = document.getElementById('earnings-tbody');
  if (!panel || !tbody) return;
  if (earnings.length === 0) { panel.classList.add('hidden'); return; }
  panel.classList.remove('hidden');

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  tbody.innerHTML = earnings.map(e => {
    const d       = e.earnings_date ? new Date(e.earnings_date + 'T00:00:00') : null;
    const daysAway = d ? Math.round((d - today) / 86400000) : null;
    let daysCls = '', daysLabel = '—';
    if (daysAway != null) {
      daysLabel = daysAway === 0 ? 'TODAY' : daysAway === 1 ? 'Tomorrow' : `${daysAway}d`;
      daysCls = daysAway === 0 ? 'earnings-today' : daysAway <= 7 ? 'earnings-soon' : '';
    }
    const dateStr = d ? d.toLocaleDateString('en-US', {month:'short', day:'numeric', year:'numeric'}) : '—';
    return `<tr>
      <td style="color:var(--accent);font-weight:700">${e.ticker}</td>
      <td style="color:var(--muted);font-size:11px">${e.company_name || ''}</td>
      <td>${dateStr}</td>
      <td class="${daysCls}">${daysLabel}</td>
      <td>${e.eps_estimate != null ? '$' + e.eps_estimate.toFixed(2) : '—'}</td>
    </tr>`;
  }).join('');
}

// Hook earnings load into portfolio refresh
const _origLoadPortfolio = loadPortfolio;
loadPortfolio = async function() {
  await _origLoadPortfolio();
  loadEarnings();
};

// ---------------------------------------------------------------------------
// Options Analytics
// ---------------------------------------------------------------------------
let optionsData = null;
let smileChart  = null;
let optionsPanelOpen = false;

// ATM vertical line plugin for Chart.js
const atmLinePlugin = {
  id: 'atmLine',
  afterDatasetsDraw(chart, _args, opts) {
    if (opts == null || opts.xValue == null) return;
    const { ctx, scales, chartArea } = chart;
    const xScale = scales.x;
    if (!xScale) return;
    const px = xScale.getPixelForValue(opts.xValue);
    if (px == null || isNaN(px)) return;
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = 'rgba(255,255,255,0.25)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(px, chartArea.top);
    ctx.lineTo(px, chartArea.bottom);
    ctx.stroke();
    ctx.restore();
  }
};
Chart.register(atmLinePlugin);

// ── Toggle collapse ──────────────────────────────────────────────────────────
document.getElementById('options-toggle').addEventListener('click', () => {
  optionsPanelOpen = !optionsPanelOpen;
  const body  = document.getElementById('options-body');
  const arrow = document.getElementById('options-arrow');
  body.classList.toggle('hidden', !optionsPanelOpen);
  arrow.classList.toggle('open', optionsPanelOpen);
});

// ── Main fetch ───────────────────────────────────────────────────────────────
async function loadOptions(symbol) {
  const panel = document.getElementById('options-panel');
  panel.classList.add('hidden');
  optionsData = null;

  try {
    const res = await apiFetch('/api/options/' + encodeURIComponent(symbol));
    if (!res.ok) return;
    const data = await res.json();
    if (!data.available) return;

    optionsData = data;
    panel.classList.remove('hidden');

    if (data.is_sparse) {
      document.getElementById('options-sparse-warn').classList.remove('hidden');
    } else {
      document.getElementById('options-sparse-warn').classList.add('hidden');
    }

    renderImpliedMoves(data.implied_moves || []);
    buildSmileSelector(data);
    if (data.default_smile_exp && data.smiles && data.smiles[data.default_smile_exp]) {
      renderSmileChart(data.smiles[data.default_smile_exp]);
    }
    if (data.surface) renderVolSurface(data.surface);
  } catch(e) {
    // silently skip — options unavailable
  }
}

// ── Implied Move Strip ───────────────────────────────────────────────────────
function renderImpliedMoves(moves) {
  const strip = document.getElementById('implied-strip');
  if (!moves.length) { strip.innerHTML = '<span style="color:var(--muted);font-size:11px">No implied move data available.</span>'; return; }

  strip.innerHTML = moves.map(m => {
    const pct = m.implied_move_pct;
    let cls = 'g';
    if (pct > 10) cls = 'r';
    else if (pct > 6) cls = 'o';
    else if (pct > 3) cls = 'y';
    return `
      <div class="move-card">
        <span class="move-pct ${cls}">±${pct != null ? pct.toFixed(1) : '—'}%</span>
        <span class="move-date">${m.exp_label || m.expiration}</span>
        <span class="move-dte">${m.days_to_expiry != null ? m.days_to_expiry + 'd' : ''}</span>
        <div class="move-tooltip">
          ATM Strike: $${m.atm_strike != null ? m.atm_strike.toFixed(0) : '—'}<br>
          Call Mid: $${m.atm_call_mid != null ? m.atm_call_mid.toFixed(2) : '—'}<br>
          Put Mid: $${m.atm_put_mid  != null ? m.atm_put_mid.toFixed(2)  : '—'}
        </div>
      </div>`;
  }).join('');
}

// ── Smile expiration selector ────────────────────────────────────────────────
function buildSmileSelector(data) {
  const sel = document.getElementById('smile-exp-select');
  sel.innerHTML = '';
  const exps = data.available_expirations || [];
  exps.forEach(e => {
    const opt = document.createElement('option');
    opt.value = e.expiration;
    opt.textContent = e.exp_label + (e.days_to_expiry != null ? '  (' + e.days_to_expiry + 'd)' : '');
    if (e.expiration === data.default_smile_exp) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.onchange = () => {
    const exp = sel.value;
    if (data.smiles && data.smiles[exp]) {
      renderSmileChart(data.smiles[exp]);
    }
  };
}

// ── IV Smile Chart ────────────────────────────────────────────────────────────
function renderSmileChart(smileExp) {
  if (!smileExp || !smileExp.strikes) return;

  const strikes = smileExp.strikes;
  const labels   = strikes.map(s => s.strike);
  const callIVs  = strikes.map(s => (s.call_iv != null && s.call_iv > 0) ? s.call_iv : null);
  const putIVs   = strikes.map(s => (s.put_iv  != null && s.put_iv  > 0) ? s.put_iv  : null);
  const atmStrike = smileExp.atm_strike;

  // Skew badge
  const badge = document.getElementById('smile-skew-badge');
  if (smileExp.skew_label) {
    badge.textContent = smileExp.skew_label;
    badge.className   = 'smile-skew-badge';
    if (smileExp.skew_label.startsWith('PUT'))  badge.classList.add('put');
    else if (smileExp.skew_label.startsWith('CALL')) badge.classList.add('call');
    else badge.classList.add('sym');
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }

  const ctx = document.getElementById('smile-chart').getContext('2d');
  if (smileChart) { smileChart.destroy(); smileChart = null; }

  smileChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Call IV',
          data: callIVs,
          borderColor: '#4fc3f7',
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: '#4fc3f7',
          tension: 0.2,
          fill: false,
          spanGaps: true,
        },
        {
          label: 'Put IV',
          data: putIVs,
          borderColor: '#ffb74d',
          borderWidth: 2,
          pointRadius: 3,
          pointBackgroundColor: '#ffb74d',
          tension: 0.2,
          fill: false,
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: {
            color: '#7d8590', font: { family: 'Inter', size: 10 },
            boxWidth: 12, padding: 14,
          }
        },
        tooltip: {
          backgroundColor: '#1a1a1a', borderColor: '#2a2a2a', borderWidth: 1,
          titleColor: '#666', bodyColor: '#e0e0e0', padding: 10,
          callbacks: {
            title: (items) => '$' + items[0].label,
            label: (ctx) => {
              const v = ctx.parsed.y;
              return v != null ? ' ' + ctx.dataset.label + ': ' + v.toFixed(1) + '%' : null;
            },
          }
        },
        atmLine: { xValue: atmStrike },
      },
      scales: {
        x: {
          type: 'linear',
          grid:  { color: '#1a1a1a' },
          ticks: { color: '#555', maxTicksLimit: 10, font: { family: 'JetBrains Mono', size: 10 },
                   callback: v => '$' + v },
          title: { display: true, text: 'Strike', color: '#555', font: { size: 10 } },
        },
        y: {
          position: 'right',
          grid:  { color: '#1a1a1a' },
          ticks: { color: '#555', font: { family: 'JetBrains Mono', size: 10 },
                   callback: v => v.toFixed(0) + '%' },
          title: { display: true, text: 'Implied Volatility', color: '#555', font: { size: 10 } },
        },
      },
    },
  });
}

// ── Volatility Surface Heatmap ────────────────────────────────────────────────
function surfaceColor(iv, ivMin, ivMax) {
  if (iv == null) return '#1a1a22';
  const t = ivMax > ivMin ? Math.max(0, Math.min(1, (iv - ivMin) / (ivMax - ivMin))) : 0.5;
  if (t < 0.5) {
    const s = t * 2;
    return `rgb(${Math.round(20 + s*40)},${Math.round(40 + s*20)},${Math.round(100 - s*40)})`;
  } else {
    const s = (t - 0.5) * 2;
    return `rgb(${Math.round(60 + s*140)},${Math.round(60 - s*20)},${Math.round(60 - s*20)})`;
  }
}

function surfaceTextColor(iv, ivMin, ivMax) {
  if (iv == null) return '#444';
  const t = ivMax > ivMin ? (iv - ivMin) / (ivMax - ivMin) : 0.5;
  return (t < 0.25 || (t > 0.35 && t < 0.65)) ? '#ccc' : '#fff';
}

function renderVolSurface(surface) {
  const thead = document.getElementById('surface-thead');
  const tbody = document.getElementById('surface-tbody');
  if (!surface || !surface.rows || !surface.rows.length) {
    thead.innerHTML = ''; tbody.innerHTML = '';
    return;
  }

  const { rows, iv_min, iv_max } = surface;
  const exps = rows[0].cells.map(c => c);

  // Header
  thead.innerHTML = '<tr><th>Moneyness</th>' +
    exps.map(c => `<th>${c.exp_label}</th>`).join('') + '</tr>';

  // Rows
  tbody.innerHTML = rows.map(row => {
    const label = `${row.moneyness_label}<br><span style="color:var(--label);font-size:9px">$${row.strike != null ? row.strike.toFixed(0) : '—'}</span>`;
    const cells = row.cells.map(c => {
      const iv  = c.avg_iv;
      const bg  = surfaceColor(iv, iv_min, iv_max);
      const fg  = surfaceTextColor(iv, iv_min, iv_max);
      const atm = c.is_atm ? ' atm-cell' : '';
      const tip = `Strike $${row.strike != null ? row.strike.toFixed(0) : '—'} | ${c.exp_label} | IV: ${iv != null ? iv.toFixed(1) + '%' : '—'} | Call OI: ${c.call_oi != null ? Math.round(c.call_oi).toLocaleString() : '—'} | Put OI: ${c.put_oi != null ? Math.round(c.put_oi).toLocaleString() : '—'}`;
      return `<td class="${atm}" style="background:${bg};color:${fg}" title="${tip}">${iv != null ? iv.toFixed(1) + '%' : '—'}</td>`;
    }).join('');
    return `<tr><td>${label}</td>${cells}</tr>`;
  }).join('');
}

// ── Earnings Calendar ────────────────────────────────────────────────────────
const EC_COMPANIES = [
  { ticker:"AB", name:"AllianceBernstein", date:"2026-04-28", time:"Before Market Open", color:"#00205B", logoText:"AB", confirmed:true, reported:true, nextDate:"2026-07-28", stockReaction:-1.93, eps:0.83, epsPrior:0.78, rev:1.20, fpe:13, epsConsensus:0.84, revConsensus:1.15, epsSurprise:{pct:-1.2,dir:"down",note:"Narrow EPS miss ($0.83 adj. vs $0.84 est.); GAAP revenue $1.20B beat on stronger activity fees"}, watch:{catalysts:["Adjusted EPS $0.83, +4% y/y — narrow miss on estimates but distribution held at $0.83/unit","GAAP net revenues $1.20B — meaningfully beat FactSet consensus of ~$895M","AUM $838.6B, up 6.9% y/y despite $7.1B net outflows in the quarter","Private markets platform at $85B AUM, up 13% y/y — the key growth narrative intact","FY2026 performance fee outlook raised to $95M–$115M (prior: $80M–$100M)"],risks:["Active net outflows of ~$6B remain a headwind to fee revenue mix","Stock fell ~1.9% — market focused on the EPS miss despite revenue beat","Fee compression in core equity/fixed income products persists","Equitable (parent) capital allocation decisions remain a watch item"],quote:"A <strong>mixed print</strong> — GAAP revenues blew past estimates but adjusted EPS narrowly missed. Net outflows of $7.1B and a 1.9% stock decline on the day underscore the market's focus on flow momentum. The private markets franchise ($85B AUM, +13% y/y) remains the re-rating catalyst. Next print: July 28."} },
  { ticker:"TSLA", name:"Tesla", date:"2026-04-22", time:"After Market Close", color:"#E31937", logoText:"T", confirmed:true, reported:true, nextDate:"2026-07-22", stockReaction:-3.59, eps:0.41, epsPrior:0.73, rev:22.39, fpe:72, epsConsensus:0.37, revConsensus:22.35, epsSurprise:{pct:10.8,dir:"up",note:"Beat EPS; slight revenue miss; capex raised $5B above prior guidance"}, watch:{catalysts:["Non-GAAP EPS $0.41 vs $0.37 expected — margins better than feared","Revenue $22.39B — slight miss vs $22.64B consensus","Model Q launch and Austin robotaxi pilot remain the long-term growth thesis","Energy storage (Megapack) backlog commentary positive"],risks:["Capex raised to $25B for 2026, up $5B from prior guidance — spooked investors","Stock fell 3.6% on earnings day despite EPS beat","China competitive pressure from BYD continues to weigh on ASPs","Revenue miss signals demand softness even as profitability stabilized"],quote:"A <strong>beat on EPS, but the $5B capex raise above prior guidance</strong> overshadowed the print — TSLA fell 3.6% on the day. The robotaxi thesis remains the bull case. Next print: July 22."} },
  { ticker:"GOOGL", name:"Alphabet", date:"2026-04-29", time:"After Market Close", color:"#4285F4", logoText:"G", confirmed:true, eps:2.63, epsPrior:1.89, rev:106.9, fpe:22, epsSurprise:{pct:6.8,dir:"up",note:"Beat Q4 on Cloud acceleration"}, watch:{catalysts:["Google Cloud revenue growth — consensus at ~29% y/y; $106.9B total rev expected","Gemini 3 monetization signals in Search and Workspace","YouTube ad revenue strength vs. TikTok comps","Capex guide — AI infra spend expected to rise to $90B+ for 2026"],risks:["DOJ remedy phase overhang on search default payments","AI Overviews cannibalization of paid click volume","Waymo losses widening as geographic expansion accelerates","FX headwinds from stronger dollar"],quote:"Every quarter is now a referendum on whether <strong>AI helps or hurts Search economics</strong>. Cloud growth needs to stay above 28% to sustain the re-rating."} },
  { ticker:"MSFT", name:"Microsoft", date:"2026-04-29", time:"After Market Close", color:"#00A4EF", logoText:"M", confirmed:true, eps:4.07, epsPrior:3.03, rev:81.4, fpe:32, epsSurprise:{pct:3.1,dir:"up",note:"Beat on Azure and commercial bookings"}, watch:{catalysts:["Azure growth — company guided 37–38% CC; consensus wants 38%+ to re-rate","Copilot seat count and per-seat attach rates (commercial Copilot M365)","OpenAI-related capacity commentary and GPU utilization","Commercial bookings and RPO (remaining performance obligations)"],risks:["Capex dollar figure vs. revenue — AI ROI skepticism is back","Activision integration deceleration in gaming","Sequential Azure deceleration from the prior year's strong comp","Windows/PC refresh cycle softer than hoped"],quote:"Microsoft guided Azure 37–38% CC for Q3 — the market needs <strong>38%+ to call this a beat</strong>. The AI capacity narrative is under a tougher sequential comp. Revenue consensus: $81.4B."} },
  { ticker:"META", name:"Meta Platforms", date:"2026-04-29", time:"After Market Close", color:"#1877F2", logoText:"M", confirmed:true, eps:6.67, epsPrior:4.71, rev:55.4, fpe:24, epsSurprise:{pct:8.4,dir:"up",note:"Beat Q4 on ad pricing and Reels"}, watch:{catalysts:["Ad impression growth and pricing split","Reality Labs loss narrowing vs. Street's -$4.8B expectation","Llama 4 commercial traction and AI assistant DAU","Threads monetization onset"],risks:["2026 capex guidance — prior raise to $105B spooked shorts","China ad spend rollover (Temu/Shein) on tariff regime","Regulatory action in EU on DSA/DMA compliance costs","Reels engagement plateauing among Gen Z"],quote:"Revenue consensus revised up sharply to $55.4B (+31% y/y) — Street pricing in a strong print. <strong>Capex trajectory and China ad spend durability</strong> (Temu/Shein tariff impact) are the swing factors."} },
  { ticker:"AMZN", name:"Amazon", date:"2026-04-29", time:"After Market Close", color:"#FF9900", logoText:"a", confirmed:true, eps:1.63, epsPrior:0.98, rev:177.2, fpe:38, epsSurprise:{pct:11.2,dir:"up",note:"AWS margin blowout last quarter"}, watch:{catalysts:["AWS growth — Street consensus 25%, BofA at 28%; AWS rev ~$36.8B expected","Total revenue consensus $177.1B — operating income $16.5–$21.5B guided","Advertising revenue growth, now a $65B+ run rate","Bedrock / Trainium customer adoption callouts"],risks:["Operating income guide came in below Street's $22.2B — already flagged cautiously","FY2026 CapEx expanding ~4x to nearly $200B — ROI scrutiny intense","Consumer weakness in discretionary categories under tariff pressure","AWS margin range wide (30.9–40%) — execution variance is elevated"],quote:"<strong>AWS growth and the operating income guide are the two numbers.</strong> Revenue consensus at $177.1B; the debate is whether AWS growth hits 25% or surprises toward 28%."} },
  { ticker:"AAPL", name:"Apple", date:"2026-04-30", time:"After Market Close", color:"#A2AAAD", logoText:"", confirmed:true, eps:1.95, epsPrior:1.65, rev:109.7, fpe:30, epsSurprise:{pct:2.3,dir:"up",note:"Modest Q1 beat on Services"}, watch:{catalysts:["iPhone units — particularly iPhone 17 sell-through in China","Services revenue growth rate — Street at 14% y/y","Apple Intelligence rollout impact on upgrade cycle","India manufacturing commentary and tariff mitigation strategy"],risks:["China regulatory retaliation risk on App Store or iCloud","Tariff impact on bill of materials and gross margin","Services growth deceleration if ad market softens","Valuation at 30x forward needs flawless execution"],quote:"The <strong>Services flywheel vs. hardware tariff risk</strong> is the central tension. A clean $1.95 EPS print with 14%+ Services growth would re-rate the stock; a margin warning would punish it."} },
  { ticker:"AMD", name:"AMD", date:"2026-04-28", time:"After Market Close", color:"#ED1C24", logoText:"AMD", confirmed:true, eps:0.96, epsPrior:0.62, rev:7.73, fpe:40, epsSurprise:{pct:5.2,dir:"up",note:"Data center GPU strong in Q4"}, watch:{catalysts:["MI300/MI350 GPU data center revenue — Street at $3.2B for the quarter","PC client recovery commentary","Gaming segment exit strategy update","Design win pipeline for next-gen MI400 series"],risks:["NVIDIA H100/H200 competition holding AI GPU share","Export restrictions may limit China data center TAM","Client PC ASP pressure from Intel and Qualcomm","Memory bandwidth constraints may limit MI300 adoption ceiling"],quote:"AMD's data center GPU run rate is the proof point — <strong>$3B+ in AI GPU quarterly revenue would confirm the NVIDIA challenger narrative</strong>."} },
  { ticker:"PLTR", name:"Palantir", date:"2026-05-05", time:"Before Market Open", color:"#1D2951", logoText:"P", confirmed:true, eps:0.13, epsPrior:0.07, rev:0.862, fpe:140, epsSurprise:{pct:7.2,dir:"up",note:"US government and commercial both beat"}, watch:{catalysts:["US Commercial revenue — Street at $320M, AIP momentum is the narrative","US Government revenue stability vs. DOGE budget risk","Rule of 40 score trajectory","International commercial ramp"],risks:["DOGE defense budget cuts could pressure US Government ARR","Valuation at 140x forward demands continued re-acceleration","International commercial remains subscale","Revenue concentration in large government contracts"],quote:"Palantir trades on AIP commercial traction — <strong>US Commercial revenue growth above 55% y/y is the bull case trigger</strong>. Government headcount scrutiny under DOGE is the bear overhang."} },
  { ticker:"NVDA", name:"NVIDIA", date:"2026-05-28", time:"After Market Close", color:"#76B900", logoText:"NV", confirmed:true, eps:0.90, epsPrior:0.61, rev:43.1, fpe:38, epsSurprise:{pct:9.8,dir:"up",note:"Blackwell demand continues to exceed supply"}, watch:{catalysts:["Data Center revenue — Street at $38.8B; Blackwell supply ramp commentary","Gross margin trajectory — Street watching for 73–75% range","Sovereign AI and hyperscaler capex signals","H20 export restriction impact on China revenue"],risks:["H20/export restrictions permanently reduce China TAM","Gross margin compression if Blackwell yields disappoint","AMD/Gaudi 3 competition in cost-sensitive workloads","Inventory build risk if hyperscaler capex pauses"],quote:"The single most important earnings print of the season. <strong>Blackwell supply ramp and gross margin</strong> are the two numbers. H20 China restrictions have been flagged; the market wants to hear about the rest-of-world pipeline."} },
  { ticker:"CRM", name:"Salesforce", date:"2026-05-28", time:"After Market Close", color:"#00A1E0", logoText:"S", confirmed:true, eps:2.63, epsPrior:2.44, rev:9.85, fpe:28, epsSurprise:{pct:3.6,dir:"up",note:"Agentforce attach rates impressed"}, watch:{catalysts:["Agentforce ARR and seat attach — the key AI monetization metric","cRPO growth — leading indicator of future revenue","Operating margin expansion toward 33%+","Data Cloud growth rate"],risks:["Agentforce remains early-stage; hard to size TAM confidently","Legacy CRM renewal pressure from Microsoft Dynamics","Macro softness impacting enterprise deal sizes and timing","Net revenue retention trending down"],quote:"Salesforce needs to show <strong>Agentforce is converting from pilots to paid seats at scale</strong>. Any slip in cRPO growth will be punished at 28x forward."} },
  { ticker:"COST", name:"Costco", date:"2026-06-04", time:"After Market Close", color:"#005DAA", logoText:"C", confirmed:true, eps:4.04, epsPrior:3.78, rev:62.5, fpe:48, epsSurprise:{pct:1.8,dir:"up",note:"Comp sales steady at +7% ex-fuel"}, watch:{catalysts:["Comp sales growth — Street at 7% ex-fuel; US comparable needs to hold","Membership fee income growth and renewal rate","E-commerce penetration acceleration","International comp sales, esp. Canada and Asia"],risks:["High valuation at 48x needs perfect execution","Tariff impact on imported food/goods if passed through","Membership renewal headwinds from wallet fatigue","Labor cost inflation at distribution centers"],quote:"Costco's <strong>membership renewal rate is the moat metric</strong> — any slip below 92% triggers a valuation reset. The tariff question is whether the price advantage widens or compresses at 48x."} },
  { ticker:"ORCL", name:"Oracle", date:"2026-06-09", time:"After Market Close", color:"#F80000", logoText:"OR", confirmed:true, eps:1.68, epsPrior:1.41, rev:14.8, fpe:22, epsSurprise:{pct:4.1,dir:"up",note:"OCI cloud growth re-accelerating"}, watch:{catalysts:["OCI revenue growth — Street at 52% y/y; AI GPU cluster demand","Remaining performance obligations — backlog now >$97B","Database and autonomous DB migration tailwind","Multi-cloud partnership traction with Azure/AWS"],risks:["OCI capacity constrained — can they ship enough GPU clusters?","License attrition as customers migrate to SaaS/cloud","Valuation reset risk if OCI growth decelerates","Autonomous DB cannibalizes high-margin on-prem"],quote:"Oracle's <strong>$97B+ RPO backlog is the structural bull case</strong> — the question is whether OCI can actually build out fast enough to recognize it."} },
  { ticker:"ADBE", name:"Adobe", date:"2026-06-18", time:"After Market Close", color:"#FF0000", logoText:"AD", confirmed:true, eps:5.15, epsPrior:4.48, rev:5.91, fpe:26, epsSurprise:{pct:2.5,dir:"up",note:"Creative Cloud AI features lifted ARPU"}, watch:{catalysts:["Net new ARR — Street at $550M; Firefly AI monetization ramp","Document Cloud growth, esp. Acrobat AI features","Digital Experience cloud ARR trajectory","ARPU expansion from AI-tier pricing"],risks:["Canva and Figma (post-failed merger) taking creative market share","Midjourney/Sora threat to Firefly differentiation","Slowdown in enterprise seat expansion","FX headwinds in European market"],quote:"Adobe's <strong>Firefly monetization is the AI revenue test for SaaS</strong> — the market wants to see net new ARR inflecting above $550M to validate the AI upsell thesis."} },
  { ticker:"FDX", name:"FedEx", date:"2026-06-17", time:"After Market Close", color:"#4D148C", logoText:"FX", confirmed:true, eps:5.25, epsPrior:5.29, rev:21.9, fpe:13, epsSurprise:{pct:2.1,dir:"up",note:"DRIVE cost savings ahead of schedule"}, watch:{catalysts:["DRIVE cost savings — on track for $4B+ cumulative by FY27","Express-Ground network consolidation progress","B2B volume recovery as industrial cycle improves","Operating margin trajectory toward 10%+"],risks:["US-China trade tension dampening air freight volumes","Amazon Logistics eating last-mile share","Fuel surcharge revenue declining on lower crude","Peak season capacity utilization below prior years"],quote:"The <strong>DRIVE cost program is the equity story</strong> — every quarter FedEx needs to show $200M+ in incremental savings to justify the re-rating to 13x."} },
  { ticker:"NKE", name:"Nike", date:"2026-06-25", time:"After Market Close", color:"#111111", logoText:"N", confirmed:true, eps:0.61, epsPrior:0.99, rev:10.8, fpe:28, epsSurprise:{pct:-4.2,dir:"down",note:"Prior quarter missed on DTC weakness"}, watch:{catalysts:["DTC revenue and gross margin recovery — Street needs +200bps","China market rebound — fell -17% y/y last quarter","Win Now plan execution — product and wholesale channel reset","FY27 guidance credibility"],risks:["China consumer discretionary spending not recovering","On, Hoka, New Balance taking premium running share","Tariff impact on Vietnam/Indonesia manufacturing","Gross margin structural compression from promotions"],quote:"Nike's <strong>Win Now turnaround needs to show in the DTC margin line</strong> — a gross margin print below 43% would re-price the recovery timeline materially."} },
  { ticker:"MELI", name:"MercadoLibre", date:"2026-05-07", time:"After Market Close", color:"#FFE600", logoText:"ML", confirmed:true, eps:12.45, epsPrior:7.35, rev:6.24, fpe:40, epsSurprise:{pct:6.3,dir:"up",note:"Fintech (Mercado Pago) outpaced GMV"}, watch:{catalysts:["GMV growth — Street at 23% y/y in USD; Brazil momentum","Mercado Pago TPV and credit portfolio quality","MPOS device uptake in underbanked markets","Gross margin inflection on logistics cost reduction"],risks:["Brazil FX volatility compresses USD-reported revenue","Credit loss provisions rising as consumer credit scales","Regulatory risk in Brazil on fintech lending","Argentina macro normalization could reduce tailwind"],quote:"<strong>Mercado Pago TPV growth and credit portfolio NPL ratio</strong> are the swing variables — if fintech keeps outpacing commerce, the story re-rates toward a fintech multiple."} },
  { ticker:"HOOD", name:"Robinhood", date:"2026-05-07", time:"After Market Close", color:"#00C805", logoText:"R", confirmed:true, eps:0.48, epsPrior:0.18, rev:0.924, fpe:22, epsSurprise:{pct:8.9,dir:"up",note:"Crypto and options activity surged"}, watch:{catalysts:["PFOF revenue and options notional — volatility drives Robinhood","Gold subscriber count and ARPU","Crypto trading notional — BTC/ETH rally impacts Q1 revenue","Active users and net deposits"],risks:["PFOF regulatory risk re-emerging under new SEC leadership","Crypto trading revenue highly cyclical","Customer acquisition costs rising in competitive brokerage market","Concentration in retail day-traders who churn"],quote:"Robinhood is a <strong>volatility leveraged play on retail participation</strong> — high VIX and crypto momentum in Q1 should produce a strong print, but the durability question is always the bear case."} },
  { ticker:"LYFT", name:"Lyft", date:"2026-05-06", time:"After Market Close", color:"#FF00BF", logoText:"L", confirmed:true, eps:0.22, epsPrior:0.09, rev:1.48, fpe:26, epsSurprise:{pct:3.8,dir:"up",note:"Rides volume beat; take-rate stable"}, watch:{catalysts:["Gross bookings growth — Street at 14% y/y","Take-rate trajectory — needs to hold above 28.5%","Driver supply health and incentive cost per ride","Autonomous vehicle partnership with Mobileye/May Mobility — timeline"],risks:["Uber's superior brand and international scale","Driver cost normalization risk","Robotaxi transition risk — LYFT dependent on Uber's or Tesla's success","Price elasticity ceiling on ride frequency"],quote:"LYFT needs to show <strong>gross bookings growth above 14% and a stable take-rate</strong> to maintain its discount-to-Uber multiple compression thesis."} },
  { ticker:"NU", name:"Nu Holdings", date:"2026-05-13", time:"Before Market Open", color:"#820AD1", logoText:"NU", confirmed:true, eps:0.12, epsPrior:0.09, rev:2.85, fpe:24, epsSurprise:{pct:10.2,dir:"up",note:"Mexico and Colombia growth ahead of plan"}, watch:{catalysts:["Customer growth — 110M+ customers in Brazil/Mexico/Colombia","ARPAC (avg revenue per active customer) expansion","NPL and credit provision trajectory as loan book scales","Mexico activation rate and credit card spend"],risks:["Brazil consumer credit cycle risk — NPLs could spike","FX (BRL, MXN) against USD compresses reported revenue","Regulatory pressure on interchange fees in Brazil","Competition from incumbent banks in credit card space"],quote:"Nu's <strong>ARPAC trajectory and NPL management</strong> are the two proof points — if they can scale revenue without proportional provision growth, the multiple re-rates."} },
  { ticker:"WMT", name:"Walmart", date:"2026-05-15", time:"Before Market Open", color:"#0071CE", logoText:"WM", confirmed:true, eps:0.58, epsPrior:0.60, rev:167.8, fpe:30, epsSurprise:{pct:3.1,dir:"up",note:"US comp sales and advertising beat"}, watch:{catalysts:["US comp sales — Street at +4.3%; grocery share gains","Walmart Connect advertising revenue — $4.4B run rate","Sam's Club comp sales acceleration","Flipkart/India progress"],risks:["Tariff impact on general merchandise COGS","High-income shopper retention as macro stabilizes","Advertising take-rate pressure from Amazon","Sam's Club membership renewal slowing"],quote:"Walmart is <strong>the tariff bellwether</strong> — commentary on how COGS are being managed vs. Costco and Amazon will set the tone for the entire retail sector."} },
  { ticker:"AVGO", name:"Broadcom", date:"2026-06-11", time:"After Market Close", color:"#CC0000", logoText:"AV", confirmed:true, eps:1.61, epsPrior:1.12, rev:14.9, fpe:24, epsSurprise:{pct:4.4,dir:"up",note:"XPU custom AI chip ramp exceeded estimates"}, watch:{catalysts:["Custom AI silicon (XPU) revenue — the Google TPU and Meta MTIA proxy","AI networking revenue — Tomahawk 5 and Jericho ramp","VMware integration synergies on track","Semiconductor cycle recovery in networking/storage"],risks:["Hyperscaler custom silicon concentration risk (Google + Meta ~60% of AI rev)","VMware customer attrition under new licensing model","Broadband and industrial semi recovery slower than expected","Export control risk on high-bandwidth networking chips"],quote:"Broadcom's custom AI silicon is <strong>the anti-NVIDIA trade</strong> — XPU revenue above $4.5B for the quarter would validate the hyperscaler co-design thesis at scale."} },
  { ticker:"BAC", name:"Bank of America", date:"2026-04-15", time:"Before Market Open", color:"#E31837", logoText:"BA", confirmed:true, reported:true, nextDate:"2026-07-15", stockReaction:2.1, eps:0.83, epsPrior:0.76, rev:27.4, fpe:12, epsConsensus:0.81, revConsensus:26.9, epsSurprise:{pct:3.7,dir:"up",note:"Beat on NII and trading revenue"}, watch:{catalysts:["NII of $14.4B beat consensus, guided to modest growth through 2026","Trading revenue strong: FICC +4%, Equities +12% y/y","Consumer deposits up 3% sequentially — deposit beta stabilizing","Announced $25B buyback authorization alongside earnings"],risks:["CRE (commercial real estate) reserve builds a watch item","Investment banking pipeline mixed — M&A slower than peers","Consumer NCO rate ticked up to 0.59% — monitoring","Guide assumes stable curve — sensitive to Fed path"],quote:"A <strong>clean beat across the board</strong> — NII trajectory and the buyback announcement were the standouts. Next print (July 15) will test whether deposit beta has truly peaked."} },
  { ticker:"AXP", name:"American Express", date:"2026-04-17", time:"Before Market Open", color:"#006FCF", logoText:"AX", confirmed:true, reported:true, nextDate:"2026-07-17", stockReaction:1.8, eps:3.68, epsPrior:3.33, rev:17.8, fpe:19, epsConsensus:3.52, revConsensus:17.6, epsSurprise:{pct:4.5,dir:"up",note:"Beat on billings and net card fee growth"}, watch:{catalysts:["Billed business +8% y/y — T&E led at +10%, robust premium spend","Net card fee revenue +16% on Platinum/Gold refresh uptake","Millennial/Gen-Z now 36% of total billings, growing 15%+ y/y","Raised FY2026 EPS guide to $15.40–$15.80 (prior: $15.00–$15.50)"],risks:["Credit costs stable but NCOs ticked up to 2.1% from 1.9%","Small business (SBS) billings softest segment at +3%","Rewards cost intensity rising as Plat/Gold usage climbs","International growth decelerated vs. expectations"],quote:"A <strong>confident beat-and-raise</strong> — the guide bump was the real story. T&E durability proves the premium consumer is still showing up. Next print: July 17."} },
  { ticker:"JPM", name:"JPMorgan Chase", date:"2026-04-14", time:"Before Market Open", color:"#0066B2", logoText:"JP", confirmed:true, reported:true, nextDate:"2026-07-14", stockReaction:1.2, eps:4.82, epsPrior:4.44, rev:44.2, fpe:14, epsConsensus:4.58, revConsensus:43.4, epsSurprise:{pct:5.2,dir:"up",note:"Beat on trading and IB revenue"}, watch:{catalysts:["Markets revenue strong — FICC +6%, Equities +11% y/y","Investment banking fees +22%, driven by M&A advisory rebound","NII guide held at $92B for 2026, implying resilience","CET1 ratio at 15.4%, announced $30B buyback authorization"],risks:["Consumer credit reserve build nudged up $250M","Commercial real estate office book still a slow burn","Deposit betas may not have fully peaked","Dimon commentary on geopolitics and macro tone cautious"],quote:"The <strong>fortress balance sheet once again delivered</strong> — markets strength offset a slightly cautious consumer credit read. Next print: July 14."} },
  { ticker:"GS", name:"Goldman Sachs", date:"2026-04-15", time:"Before Market Open", color:"#7399C6", logoText:"GS", confirmed:true, reported:true, nextDate:"2026-07-15", stockReaction:2.8, eps:12.85, epsPrior:11.58, rev:14.8, fpe:14, epsConsensus:11.80, revConsensus:14.2, epsSurprise:{pct:8.9,dir:"up",note:"Investment banking and trading blew out"}, watch:{catalysts:["Global Banking & Markets revenue +18%, best Q1 since 2021","Advisory fees +35% on deal environment reopening","Asset & Wealth Management AUM hit $3.1T record","Platform Solutions losses narrowing meaningfully"],risks:["Equity underwriting still below cycle average","Expense growth of 9% y/y deserves monitoring","Loan provisions up modestly on CRE exposures","Deal pipeline fragility if macro turns"],quote:"Goldman's <strong>I-banking franchise roared back</strong> — this is the cleanest read-through yet that the deal environment has reopened. Next print: July 15."} },
  { ticker:"MS", name:"Morgan Stanley", date:"2026-04-16", time:"Before Market Open", color:"#002663", logoText:"MS", confirmed:true, reported:true, nextDate:"2026-07-16", stockReaction:1.5, eps:2.48, epsPrior:2.02, rev:17.2, fpe:16, epsConsensus:2.28, revConsensus:16.8, epsSurprise:{pct:8.8,dir:"up",note:"Wealth Management margin expansion"}, watch:{catalysts:["Wealth Management net new assets $95B, pre-tax margin 29%","Institutional Securities +14% on trading strength","Investment banking fees +28%, M&A leading","Total client assets surpass $8.0T"],risks:["Net new asset growth decelerated sequentially","E*Trade integration benefits largely realized","Expense ratio elevated at 71%","Rate-sensitive sweep deposits still bleeding"],quote:"The <strong>wealth management flywheel keeps spinning</strong> — Morgan Stanley remains the cleanest story in big banks. Next print: July 16."} },
  { ticker:"LMT", name:"Lockheed Martin", date:"2026-04-22", time:"Before Market Open", color:"#003366", logoText:"LM", confirmed:true, reported:true, nextDate:"2026-07-21", stockReaction:-0.8, eps:6.95, epsPrior:6.39, rev:18.1, fpe:20, epsConsensus:6.70, revConsensus:18.0, epsSurprise:{pct:3.7,dir:"up",note:"Beat on segment margin, F-35 delivery light"}, watch:{catalysts:["Backlog hit record $178B on international demand","Missiles & Fire Control +16%, tailwind from European rearmament","FY26 guide reaffirmed: EPS $27.00–$27.30","$1.2B returned to shareholders via buybacks/dividends"],risks:["F-35 deliveries came in light (126 vs. 130 expected)","Aeronautics margins pressured by TR-3 costs","Classified programs cadence lumpy","DoD budget timing adds modest Q2 uncertainty"],quote:"A <strong>beat on margin offset a soft F-35 delivery print</strong> — the backlog is the bull case now. Stock chopped slightly on the delivery miss. Next print: July 21."} },
  { ticker:"GEV", name:"GE Vernova", date:"2026-04-22", time:"Before Market Open", color:"#00AEEF", logoText:"GE", confirmed:true, reported:true, nextDate:"2026-07-22", stockReaction:4.5, eps:1.12, epsPrior:0.48, rev:8.4, fpe:52, epsConsensus:0.85, revConsensus:8.2, epsSurprise:{pct:31.8,dir:"up",note:"Power and Electrification margins surged"}, watch:{catalysts:["Power orders +24%, gas turbine slot book sold out through 2028","Electrification revenue +32%, grid modernization tailwind","FY26 EPS guide raised to $4.40–$4.80 (prior: $4.00–$4.40)","FCF hit $720M vs. $280M prior year"],risks:["Wind segment still losing money, offshore drag persists","Supply chain for large transformers remains tight","Valuation at 52x leaves little room for stumble","Lumpy deal timing in large-frame gas"],quote:"A <strong>textbook beat-and-raise</strong> — the gas slot shortage is a multi-year tailwind and electrification growth is accelerating. Next print: July 22."} },
  { ticker:"INTC", name:"Intel", date:"2026-04-23", time:"After Market Close", color:"#0071C5", logoText:"IN", confirmed:true, reported:true, nextDate:"2026-07-23", stockReaction:18.0, eps:0.29, epsPrior:-0.35, rev:13.58, fpe:28, epsConsensus:0.18, revConsensus:12.8, epsSurprise:{pct:61.1,dir:"up",note:"Massive beat — data center +22% y/y; Q2 guide blew past Street expectations"}, watch:{catalysts:["Non-GAAP EPS $0.29 vs $0.18 consensus — data center drove the upside","Revenue $13.58B vs $12.8B expected — first clean beat in several quarters","Data center revenue +22% y/y to $5.1B — AI demand lifting server CPU","Q2 guide: $13.8–$14.8B revenue, EPS $0.20 — well above Street's $13.07B / $0.09"],risks:["GAAP EPS still -$0.73 — restructuring charges and foundry losses persist","18A external customer ramp still needs to prove out at scale","Can data center momentum sustain against NVIDIA/AMD competitive pressure?"],quote:"<strong>A genuine turnaround beat</strong> — data center rebound and a strong Q2 guide sent shares surging +18%+ after hours. GAAP losses persist but the narrative is finally shifting. Next print: July 23."} },
  { ticker:"PG", name:"Procter & Gamble", date:"2026-04-24", time:"Before Market Open", color:"#003DA5", logoText:"PG", confirmed:true, reported:true, nextDate:"2026-07-25", stockReaction:4.0, eps:1.63, epsPrior:1.52, rev:21.24, fpe:24, epsConsensus:1.56, revConsensus:20.52, epsSurprise:{pct:4.5,dir:"up",note:"Beat on volume growth — first volume increase across P&G in a year"}, watch:{catalysts:["Net sales +7% y/y to $21.24B — beat $20.52B consensus","Diluted EPS $1.63 vs $1.56 expected; core EPS $1.59","Volume +2% — first across-company volume growth in four quarters","Organic sales +3% on mix and pricing, North America stable"],risks:["FY2026 EPS guidance maintained but flagged toward the lower end of range","Tariff and geopolitical cost pressures flagged for H2","Private label share in paper products still a headwind","China / SK-II segment recovery remains sluggish"],quote:"P&G's <strong>first broad volume growth in a year was the headline</strong> — trade-down fears are easing. Stock +4% on the print. Guidance held but the tone on the back half is cautious. Next print: July 25."} },
  { ticker:"KO", name:"Coca-Cola", date:"2026-04-28", time:"Before Market Open", color:"#F40009", logoText:"KO", confirmed:true, reported:true, nextDate:"2026-07-28", stockReaction:5.5, eps:0.86, epsPrior:0.68, rev:12.47, fpe:25, epsConsensus:0.81, revConsensus:12.31, epsSurprise:{pct:6.2,dir:"up",note:"Beat on EPS and revenue; organic revenue +10%, strongest in five quarters; FY26 EPS guide raised"}, watch:{catalysts:["Comparable EPS $0.86 vs $0.81 consensus — +18% y/y, clear beat","Adjusted revenue $12.47B vs $12.31B expected — +12% reported","Organic revenue +10% — best performance in five quarters, volume +3% globally","FY2026 EPS growth guide raised to 8–9% (prior: 7–8%) on lower tax rate","Stock +5.5% on the day — strongest consumer staples reaction of earnings season so far"],risks:["FY organic revenue growth target unchanged at 4–5% — back-half caution implied","North America volume still slightly soft — pricing-led beat rather than pure volume","GLP-1 beverage volume tail risk persists in longer-term models","FX translation headwinds remained a drag on reported results"],quote:"A <strong>strong beat-and-raise print</strong> under new CEO Henrique Braun — organic growth of 10% and a guide raise drove shares up 5.5%, the biggest one-day move in years. Next print: July 28."} },
  { ticker:"V", name:"Visa", date:"2026-04-28", time:"After Market Close", color:"#1A1F71", logoText:"V", confirmed:true, reported:true, nextDate:"2026-07-28", stockReaction:4.1, eps:3.31, epsPrior:2.51, rev:11.2, fpe:28, epsConsensus:3.09, revConsensus:10.72, epsSurprise:{pct:7.1,dir:"up",note:"Strong beat — revenue +17% y/y; payments volume +9%, cross-border +12%; new $20B buyback authorized"}, watch:{catalysts:["Non-GAAP EPS $3.31 vs $3.09 consensus — +20% y/y, clean beat","Revenue $11.2B vs $10.72B consensus — +17% y/y, above high end of estimates","Payments volume +9%, cross-border volume +12% — global travel and commerce robust","Processed transactions +9% y/y; new $20B buyback program announced","Stock +4.1% after hours; Mastercard also lifted on read-through"],risks:["DOJ/merchant litigation overhang remains an ongoing legal watch item","Stablecoin and real-time-rail disintermediation remains a structural long-term risk","FX translation from stronger dollar a modest headwind","US consumer spending deceleration a risk if macro softens in H2"],quote:"Visa's <strong>beat-and-repeat machine delivered again</strong> — revenue +17%, cross-border +12%, and a $20B buyback lit the aftermarket. The global consumer remains resilient. Next print: July 28."} },
  { ticker:"BA", name:"Boeing", date:"2026-04-22", time:"Before Market Open", color:"#0033A0", logoText:"B", confirmed:true, reported:true, nextDate:"2026-07-22", stockReaction:1.23, eps:-0.11, epsPrior:-1.24, rev:22.22, fpe:null, epsConsensus:-0.29, revConsensus:21.78, epsSurprise:{pct:62.1,dir:"up",note:"Big beat — revenue surged 14% y/y; 737 MAX deliveries recovering"}, watch:{catalysts:["Revenue +14% y/y to $22.22B — strongest quarterly growth since production recovery","GAAP EPS -$0.11 vs -$0.29 consensus — substantially better than feared","737 MAX delivery cadence improving; backlog demand remains robust","Defense segments showed modest improvement; Spirit AeroSystems integration progressing"],risks:["Free cash flow still negative at -$2.44/share trailing — leverage (D/E 9.98) remains elevated","GAAP losses persist despite the EPS beat; full profitability is a 2027+ story","FAA quality audit process ongoing — any regulatory friction could disrupt ramp","Fixed-price defense contracts (T-7A, KC-46) still a margin headwind"],quote:"A <strong>genuine recovery beat</strong> — revenue up 14% and EPS well above consensus signals the worst is behind Boeing. But free cash flow is still negative and the debt load is substantial. Next print: July 22."} },
  { ticker:"ABBV", name:"AbbVie", date:"2026-04-29", time:"Before Market Open", color:"#071D49", logoText:"AB", confirmed:true, eps:2.69, epsPrior:2.31, rev:14.78, fpe:17, epsSurprise:{pct:4.1,dir:"up",note:"Skyrizi and Rinvoq outperformed"}, watch:{catalysts:["Skyrizi/Rinvoq immunology franchise — combined $7B quarter?","Humira biosimilar erosion — pace and magnitude","Aesthetics (Botox, Juvederm) recovery in China","Pipeline updates on Teliso-V, Emrelis"],risks:["Humira decline sharper than modeled","Medicare Part D IRA impact on U.S. pricing","Aesthetics category still soft in US","Parkinson's/psychiatric pipeline setbacks"],quote:"<strong>Skyrizi + Rinvoq have fully replaced Humira</strong> in the growth narrative — any shortfall there would crack the bull case."} },
  { ticker:"MRK", name:"Merck", date:"2026-04-30", time:"Before Market Open", color:"#00857C", logoText:"MK", confirmed:true, eps:-1.35, epsPrior:1.72, rev:16.06, fpe:13, epsSurprise:{pct:3.8,dir:"up",note:"Keytruda and Animal Health strong; consensus suppressed by ~$9B Sidera acquisition charge"}, watch:{catalysts:["Keytruda sales run rate — approaching $30B annualized","Subcutaneous Keytruda approval and launch trajectory","Animal Health performance post-supply issues","Gardasil China demand inflection"],risks:["Keytruda patent cliff (2028) weighing on multiple","Gardasil China inventory overhang persisting","Pipeline thinness outside oncology","M&A premium anxiety if a large deal emerges"],quote:"GAAP EPS expected deeply negative (-$1.35) due to the ~$9B upfront charge for the Sidera acquisition; adjusted EPS still positive. <strong>Keytruda and subcutaneous launch progress</strong> are the real metrics to watch here."} },
  { ticker:"LLY", name:"Eli Lilly", date:"2026-04-30", time:"Before Market Open", color:"#D52B1E", logoText:"LY", confirmed:true, eps:7.26, epsPrior:3.34, rev:17.78, fpe:48, epsSurprise:{pct:5.8,dir:"up",note:"Mounjaro and Zepbound beat expectations"}, watch:{catalysts:["Mounjaro + Zepbound combined revenue — Street now modeling ~$7.5B combined","Supply capacity commentary — injection device capacity unlocking further?","Orforglipron (oral GLP-1) Phase 3 data timing — pivotal catalyst","FY26 guide raise probability — consensus estimates revised up 2.7% in past 30 days"],risks:["Compounding pharmacy legal framework uncertainty — could impact near-term access","Novo Nordisk's CagriSema cardiovascular data read-through","Pricing concessions under Medicare negotiation (IRA)","Manufacturing ramp slippage in injectable capacity"],quote:"Consensus EPS has been revised up again to $7.26 (+117% y/y) on $17.78B revenue — <strong>Mounjaro/Zepbound estimates keep rising faster than the Street can keep up</strong>. The oral GLP-1 (orforglipron) data timeline is now the single biggest option value in biopharma."} },
  { ticker:"XOM", name:"ExxonMobil", date:"2026-05-01", time:"Before Market Open", color:"#EB1A23", logoText:"EX", confirmed:true, eps:1.04, epsPrior:2.06, rev:81.1, fpe:13, epsSurprise:{pct:-2.1,dir:"down",note:"Refining margins compressed Q4"}, watch:{catalysts:["Permian and Guyana production growth — targeting 4.3 Mboe/d","Pioneer integration synergy realization","Refining margin recovery on seasonal demand","Capital return — $20B buyback pace sustained?"],risks:["Oil price volatility on OPEC+ policy","Chemicals margin continues to disappoint","Downstream earnings sensitivity to crack spreads","Guyana legal/political risk on production sharing"],quote:"EPS estimates cut to $1.04 on softer oil prices — <strong>Permian + Guyana volume growth</strong> is the offset, but realizations are the governor."} },
  { ticker:"CVX", name:"Chevron", date:"2026-05-01", time:"Before Market Open", color:"#0054A4", logoText:"CV", confirmed:true, eps:2.10, epsPrior:2.03, rev:48.6, fpe:14, epsSurprise:{pct:1.2,dir:"up",note:"Slight beat on upstream volumes"}, watch:{catalysts:["Hess acquisition closing update and Guyana stake commentary","Permian production growth toward 1.0 Mboe/d target","Downstream margin recovery","Buyback pace and dividend commentary"],risks:["Venezuela asset impairment risk","Australia LNG operational reliability","Refining margin pressure persists","Guyana arbitration ruling delay"],quote:"The <strong>Hess closing + Guyana exposure</strong> remains the asymmetric catalyst — upstream execution is steady but Hess is the story."} },
  { ticker:"PFE", name:"Pfizer", date:"2026-05-05", time:"Before Market Open", color:"#0093D0", logoText:"PF", confirmed:true, eps:0.63, epsPrior:0.55, rev:13.8, fpe:11, epsSurprise:{pct:2.4,dir:"up",note:"Paxlovid inventory drawdown less severe than feared"}, watch:{catalysts:["Oncology pipeline progress — Talzenna, Padcev, Nurtec","Danuglipron (oral GLP-1) Phase 2 readout timing","Cost-cutting program ($4.5B in savings) execution","Non-COVID revenue growth rate"],risks:["Paxlovid COVID demand unpredictable","Loss of exclusivity wave beginning 2026–2027","GLP-1 pipeline behind Lilly and Novo Nordisk","Seagen acquisition integration costs"],quote:"Pfizer's <strong>cost restructuring and oncology pipeline</strong> are the re-rating levers — the COVID revenue cliff is largely priced in, but the Street needs visibility on the next growth leg."} },
  { ticker:"HD", name:"Home Depot", date:"2026-05-20", time:"Before Market Open", color:"#FF6600", logoText:"HD", confirmed:true, eps:3.68, epsPrior:3.63, rev:39.9, fpe:24, epsSurprise:{pct:1.8,dir:"up",note:"Pro segment held steady; DIY softer"}, watch:{catalysts:["Comparable store sales — Street at +2.0% y/y; Pro customer health","SRS Distribution integration synergies","Spring selling season read-through","Housing turnover recovery commentary"],risks:["High mortgage rates suppressing housing turnover and remodel spend","DIY customer pullback on macro uncertainty","Tariff impact on lumber, imported tools, hardware","Valuation at 24x needs comp acceleration"],quote:"Home Depot is the <strong>housing market proxy</strong> — any sign of mortgage rate relief and housing turnover recovery would catalyze a meaningful re-rate. Pro segment durability is the near-term anchor."} },
  { ticker:"MU", name:"Micron", date:"2026-06-25", time:"After Market Close", color:"#003087", logoText:"MU", confirmed:true, eps:1.48, epsPrior:-1.73, rev:8.48, fpe:14, epsSurprise:{pct:6.2,dir:"up",note:"HBM3E supply sold out through 2026"}, watch:{catalysts:["HBM3E revenue — on track for $3B+ in 2026; pricing and allocation","DRAM pricing cycle — upcycle just beginning?","NAND profitability recovery timeline","AI server memory content per socket"],risks:["China export restrictions limiting data center revenue","Oversupply risk if Samsung ramps aggressively in 2H","NAND still loss-making; recovery timeline extended","Cyclical demand uncertainty beyond AI workloads"],quote:"Micron's <strong>HBM3E allocation to NVIDIA and hyperscalers</strong> is sold out — the question is how large the AI memory TAM grows and whether Samsung can close the technology gap."} },
  { ticker:"UNH", name:"UnitedHealth Group", date:"2026-04-17", time:"Before Market Open", color:"#002677", logoText:"UH", confirmed:true, reported:true, nextDate:"2026-07-17", stockReaction:-8.5, eps:6.91, epsPrior:6.61, rev:109.6, fpe:21, epsConsensus:7.29, revConsensus:109.2, epsSurprise:{pct:-5.2,dir:"down",note:"Medical loss ratio jumped to 87.1%, well above consensus of 85.5%; guidance withdrawn"}, watch:{catalysts:["Revenue $109.6B — slight beat on top line","Optum segment showed resilience at +8% y/y","Federal employee plan membership commentary","Long-term MCR target reaffirmation would be positive"],risks:["Medical loss ratio 87.1% vs 85.5% expected — the miss that moved the stock -8.5%","FY2026 EPS guidance withdrawn pending MCR review","DOJ investigation into Medicare Advantage billing practices","Competitor Humana and CVS Health will read through this miss"],quote:"A <strong>rare Optum-era guidance withdrawal</strong> — the MLR miss and guidance pull spooked the market badly. The UNH multiple had priced in near-perfection; this was not that. Next print: July 17."} },
  { ticker:"UBER", name:"Uber", date:"2026-05-06", time:"After Market Close", color:"#000000", logoText:"UB", confirmed:true, eps:0.83, epsPrior:0.32, rev:11.9, fpe:30, epsSurprise:{pct:5.1,dir:"up",note:"Gross bookings beat; take-rate expanded"}, watch:{catalysts:["Gross bookings growth — Street at 18% y/y","Trips growth and take-rate (Street: 28.8%)","Autonomous vehicle partnership commentary — Waymo, BYD","Freight recovery if industrial cycle turns"],risks:["Autonomous (Waymo/Tesla) competitive overhang","Driver supply / incentive cost normalization","International markets FX translation","Any slowdown in consumer services spend"],quote:"Uber is the <strong>direct LYFT comparable</strong> — watch gross bookings growth and take-rate delta to judge whether the scale advantage is widening. Reports same day as LYFT."} }
];

let ecInitialized = false;
let ecFilter = 'all';

function ecGetNow() {
  return new Date();
}

function ecDaysUntil(dateStr) {
  const d = new Date(dateStr + 'T16:00:00');
  const ms = d - ecGetNow();
  return Math.max(0, Math.ceil(ms / (1000 * 60 * 60 * 24)));
}

function ecHoursMins(dateStr) {
  const d = new Date(dateStr + 'T16:00:00');
  let ms = d - ecGetNow();
  if (ms <= 0) return { d: 0, h: 0, m: 0 };
  const days  = Math.floor(ms / 86400000); ms -= days * 86400000;
  const hours = Math.floor(ms / 3600000);  ms -= hours * 3600000;
  const mins  = Math.floor(ms / 60000);
  return { d: days, h: hours, m: mins };
}

function ecFmtDate(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  const days = ['SUN','MON','TUE','WED','THU','FRI','SAT'];
  const months = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];
  return { day: d.getDate(), month: months[d.getMonth()], weekday: days[d.getDay()] };
}

function ecFmtNext(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  const months = ['January','February','March','April','May','June','July','August','September','October','November','December'];
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

function ecWeekOf(dateStr) {
  const d = new Date(dateStr + 'T12:00:00');
  const dow = d.getDay();
  const monday = new Date(d); monday.setDate(d.getDate() - ((dow + 6) % 7));
  const friday = new Date(monday); friday.setDate(monday.getDate() + 4);
  const m = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `Week of ${monday.getDate()} ${m[monday.getMonth()]} – ${friday.getDate()} ${m[friday.getMonth()]}`;
}

function ecIsOwned(ticker) {
  return pfPositions.some(p => (p.ticker || '').toUpperCase() === ticker.toUpperCase());
}

function ecIsWatching(ticker) {
  return (typeof wlTickers !== 'undefined') && wlTickers.some(t => t.toUpperCase() === ticker.toUpperCase());
}

function ecGoToTicker(ticker) {
  // Switch to Terminal tab
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  const termTab = document.querySelector('.nav-tab[data-page="terminal"]');
  if (termTab) termTab.classList.add('active');
  document.getElementById('earnings-cal-page').style.display = 'none';
  document.getElementById('terminal-page').style.display = '';
  // Load the ticker
  loadTicker(ticker.toUpperCase());
}

function ecRenderCountdowns() {
  const el = document.getElementById('ec-countdowns');
  if (!el) return;
  const now = ecGetNow();
  const upcoming = EC_COMPANIES
    .filter(c => !c.reported && new Date(c.date + 'T23:00:00') >= now)
    .filter(c => ecIsOwned(c.ticker))
    .slice(0, 6);
  if (upcoming.length === 0) {
    el.innerHTML = '';
    return;
  }
  el.innerHTML = upcoming.map(c => {
    const d = ecDaysUntil(c.date);
    return `<div class="ec-cd">
      <div class="ec-cd-tk">${c.ticker}</div>
      <div class="ec-cd-num">${d}</div>
      <div class="ec-cd-lbl">days</div>
    </div>`;
  }).join('');
}

function ecRenderCards() {
  const el = document.getElementById('ec-calendar');
  if (!el) return;
  const now = ecGetNow();

  // Clone with live owned/watching state
  const data = EC_COMPANIES.map(c => ({
    ...c,
    owned: ecIsOwned(c.ticker),
    watchlist: ecIsWatching(c.ticker)
  }));

  // Sort by date ascending
  data.sort((a, b) => new Date(a.date) - new Date(b.date));

  const filtered = data.filter(c => {
    if (ecFilter === 'all') return true;
    if (ecFilter === 'holdings') return c.owned;
    if (ecFilter === 'watchlist') return c.watchlist;
    const m = new Date(c.date + 'T12:00:00').getMonth() + 1;
    return m === parseInt(ecFilter);
  });

  if (filtered.length === 0) {
    el.innerHTML = '<div class="ec-empty">No earnings match this filter.</div>';
    return;
  }

  el.innerHTML = '';
  const reported = filtered.filter(c => c.reported);
  const upcoming = filtered.filter(c => !c.reported);

  // Recently reported section
  if (reported.length > 0) {
    const h = document.createElement('div');
    h.className = 'ec-week-head ec-reported-head';
    h.innerHTML = `Recently Reported <span class="ec-wcount">${reported.length} result${reported.length > 1 ? 's' : ''}</span>`;
    el.appendChild(h);
    reported.forEach(c => el.appendChild(ecMakeCard(c)));
  }

  // Upcoming — grouped by week
  const groups = {};
  upcoming.forEach(c => {
    const w = ecWeekOf(c.date);
    if (!groups[w]) groups[w] = [];
    groups[w].push(c);
  });

  Object.keys(groups).forEach(week => {
    const h = document.createElement('div');
    h.className = 'ec-week-head';
    const cnt = groups[week].length;
    h.innerHTML = `${week} <span class="ec-wcount">${cnt} report${cnt > 1 ? 's' : ''}</span>`;
    el.appendChild(h);
    groups[week].forEach(c => el.appendChild(ecMakeCard(c)));
  });
}

function ecMakeCard(c) {
  const card = document.createElement('div');
  const isPast = new Date(c.date + 'T23:00:00') < ecGetNow();
  const timer = ecHoursMins(c.date);
  const daysLeft = ecDaysUntil(c.date);
  const d = ecFmtDate(c.date);

  let cls = 'ec-card';
  if (c.owned) cls += ' ec-owned';
  if (c.watchlist) cls += ' ec-watching';
  if (c.reported) cls += ' ec-reported';
  card.className = cls;
  card.dataset.ticker = c.ticker;

  const arrow = c.epsSurprise.dir === 'up' ? '▲' : '▼';
  const epsClass = c.epsSurprise.dir === 'up' ? 'ec-up' : 'ec-dn';
  const sign = c.epsSurprise.pct > 0 ? '+' : '';
  const epsVal = c.eps != null ? `$${c.eps.toFixed(2)}` : '—';
  const revVal = c.rev != null ? `$${c.rev.toFixed(1)}B` : '—';
  const fpeVal = c.fpe != null ? `${c.fpe}x` : '—';
  const epsLabel  = c.reported ? 'Actual EPS'   : 'Consensus EPS';
  const revLabel  = c.reported ? 'Actual Rev'   : 'Revenue Est.';
  const epsSub    = c.reported && c.epsConsensus != null ? `Est: $${c.epsConsensus.toFixed(2)}` : (c.epsPrior != null ? `Prior yr: $${c.epsPrior.toFixed(2)}` : '');
  const revSub    = c.reported && c.revConsensus != null ? `Est: $${c.revConsensus.toFixed(1)}B` : 'Street consensus';
  const surpriseLbl = c.reported ? 'EPS Surprise' : 'Last Q Surprise';
  const watchLbl  = c.reported ? 'What We Learned' : 'What to Watch';
  const catLbl    = c.reported ? '▲ Highlights'  : '▲ Catalysts';
  const riskLbl   = c.reported ? '▼ Watch Items' : '▼ Risks';

  let statusBadge;
  if (c.reported) {
    statusBadge = `<div class="ec-badge ec-b-reported"><span class="ec-dot"></span>REPORTED</div>`;
  } else if (c.confirmed) {
    statusBadge = `<div class="ec-badge ec-b-confirmed"><span class="ec-dot"></span>CONFIRMED</div>`;
  } else {
    statusBadge = `<div class="ec-badge ec-b-tentative"><span class="ec-dot"></span>TENTATIVE</div>`;
  }

  const reactionHtml = c.reported && c.stockReaction != null
    ? `<span class="ec-reaction ${c.stockReaction >= 0 ? 'ec-up' : 'ec-dn'}">${c.stockReaction >= 0 ? '+' : ''}${c.stockReaction.toFixed(1)}%</span>`
    : '';

  card.innerHTML = `
    <div class="ec-card-head">
      <div class="ec-logo" style="background:${c.color}">${c.logoText || c.ticker[0]}</div>
      <div>
        <div class="ec-co-name">${c.name} ${reactionHtml}</div>
        <div class="ec-co-tk" data-ticker="${c.ticker}">${c.ticker}</div>
        <div class="ec-badges">
          ${statusBadge}
          ${c.owned    ? `<div class="ec-badge ec-b-owned">★ OWNED</div>` : ''}
          ${c.watchlist ? `<div class="ec-badge ec-b-watch">👁 WATCHING</div>` : ''}
        </div>
      </div>
      <div class="ec-date-col">
        <div class="ec-dt">${d.day}</div>
        <div class="ec-mo">${d.month} · ${d.weekday}</div>
        <div class="ec-wh">${c.time}</div>
      </div>
      <div class="ec-chev">▼</div>
    </div>
    <div class="ec-body">
      <div class="ec-body-inner">
        ${!isPast ? `
          <div class="ec-mini-timer">
            <div class="ec-mt"><div class="ec-n">${timer.d}</div><div class="ec-l">Days</div></div>
            <div class="ec-mt"><div class="ec-n">${timer.h}</div><div class="ec-l">Hours</div></div>
            <div class="ec-mt"><div class="ec-n">${timer.m}</div><div class="ec-l">Mins</div></div>
          </div>` : ''}
        <div class="ec-stats">
          <div class="ec-stat ${c.reported ? 'ec-stat-actual' : ''}">
            <div class="ec-lbl">${epsLabel}</div>
            <div class="ec-val">${epsVal}</div>
            <div class="ec-sub">${epsSub}</div>
          </div>
          <div class="ec-stat ${c.reported ? 'ec-stat-actual' : ''}">
            <div class="ec-lbl">${revLabel}</div>
            <div class="ec-val">${revVal}</div>
            <div class="ec-sub">${revSub}</div>
          </div>
          <div class="ec-stat">
            <div class="ec-lbl">Forward P/E</div>
            <div class="ec-val">${fpeVal}</div>
            <div class="ec-sub">${c.fpe != null ? 'NTM basis' : 'Data TBD'}</div>
          </div>
          <div class="ec-stat">
            <div class="ec-lbl">${surpriseLbl}</div>
            <div class="ec-val ${epsClass}">${c.epsSurprise.pct !== 0 ? arrow + ' ' + sign + c.epsSurprise.pct.toFixed(1) + '%' : '—'}</div>
            <div class="ec-sub">${c.epsSurprise.note}</div>
          </div>
          <div class="ec-stat">
            <div class="ec-lbl">${c.reported ? 'Stock Reaction' : 'Days to Report'}</div>
            <div class="ec-val ${c.reported ? (c.stockReaction >= 0 ? 'ec-up' : 'ec-dn') : ''}">${c.reported ? (c.stockReaction >= 0 ? '+' : '') + c.stockReaction.toFixed(1) + '%' : (isPast ? '✓' : daysLeft)}</div>
            <div class="ec-sub">${c.reported ? 'Day-of close vs prior' : c.time}</div>
          </div>
        </div>
        <div class="ec-wtw">
          <h4>${watchLbl}</h4>
          <div class="ec-wtw-grid">
            <div class="ec-wtw-col ec-cat"><h5>${catLbl}</h5><ul>${c.watch.catalysts.map(x => `<li>${x}</li>`).join('')}</ul></div>
            <div class="ec-wtw-col ec-risk"><h5>${riskLbl}</h5><ul>${c.watch.risks.map(x => `<li>${x}</li>`).join('')}</ul></div>
          </div>
          <div class="ec-quote">${c.watch.quote}</div>
          ${c.reported && c.nextDate ? `<div class="ec-next-report">Next earnings: <strong>${ecFmtNext(c.nextDate)}</strong> — Q2 2026 results</div>` : ''}
        </div>
      </div>
    </div>
  `;

  // Toggle open/close
  card.querySelector('.ec-card-head').addEventListener('click', () => {
    card.classList.toggle('ec-open');
  });

  // Ticker click → go to terminal
  card.querySelector('.ec-co-tk').addEventListener('click', e => {
    e.stopPropagation();
    ecGoToTicker(c.ticker);
  });

  return card;
}

function ecInit() {
  if (!ecInitialized) {
    // Wire filters
    document.querySelectorAll('.ec-flt').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.ec-flt').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        ecFilter = btn.dataset.ef;
        ecRenderCards();
      });
    });

    // Live timer update every minute
    setInterval(() => {
      document.querySelectorAll('#ec-calendar .ec-card').forEach(card => {
        const ticker = card.dataset.ticker;
        const c = EC_COMPANIES.find(x => x.ticker === ticker);
        if (!c || c.reported) return;
        const t = ecHoursMins(c.date);
        const ns = card.querySelectorAll('.ec-mt .ec-n');
        if (ns.length === 3) { ns[0].textContent = t.d; ns[1].textContent = t.h; ns[2].textContent = t.m; }
      });
    }, 60000);

    ecInitialized = true;
  }
  ecRenderCountdowns();
  ecRenderCards();
}
// ---------------------------------------------------------------------------
// Price Alerts
// ---------------------------------------------------------------------------
let _alerts = [];

async function loadAlerts() {
  if (!authUser) { _updateGuestBanners(); return; }
  try {
    const { data, error } = await sbClient
      .from('price_alerts')
      .select('id, ticker, condition, target_price, triggered, created_at')
      .order('created_at', { ascending: false });
    if (error) throw error;
    _alerts = (data || []).map(r => ({
      id: r.id, ticker: r.ticker, condition: r.condition,
      target_price: Number(r.target_price), triggered: !!r.triggered,
      created_at: r.created_at,
    }));
    renderAlerts();
  } catch (e) { console.warn('loadAlerts failed:', e); }
}

function renderAlerts() {
  const tbody = document.getElementById('alerts-tbody');
  const empty = document.getElementById('alerts-empty');
  if (!tbody) return;
  if (!_alerts.length) {
    tbody.innerHTML = '';
    if (empty) empty.style.display = 'block';
    return;
  }
  if (empty) empty.style.display = 'none';
  tbody.innerHTML = _alerts.map(a => `<tr>
    <td style="font-weight:700;color:var(--accent)">${a.ticker}</td>
    <td><span class="alert-condition-badge ${a.condition}">${a.condition.toUpperCase()}</span></td>
    <td>$${a.target_price.toFixed(2)}</td>
    <td>${a.triggered ? '<span style="color:var(--muted);font-size:11px">Triggered ✓</span>' : '<span style="color:var(--accent);font-size:11px">● Active</span>'}</td>
    <td style="color:var(--muted);font-size:11px">${(a.created_at || '').slice(0,10)}</td>
    <td><button class="alert-del-btn" onclick="deleteAlert(${a.id})">×</button></td>
  </tr>`).join('');
}

async function deleteAlert(id) {
  try {
    const { error } = await sbClient.from('price_alerts').delete().eq('id', id);
    if (error) console.warn('Delete alert failed:', error);
  } catch (e) { console.warn('Delete alert failed:', e); }
  _alerts = _alerts.filter(a => a.id !== id);
  renderAlerts();
}

function openAlertModal(ticker) {
  const tickerEl = document.getElementById('al-ticker');
  const priceEl = document.getElementById('al-price');
  const errEl = document.getElementById('al-error');
  if (tickerEl) tickerEl.value = ticker || '';
  if (priceEl) priceEl.value = '';
  if (errEl) errEl.textContent = '';
  document.getElementById('alert-modal-overlay').classList.add('open');
  setTimeout(() => (ticker ? priceEl : tickerEl)?.focus(), 50);
}

document.getElementById('add-alert-btn')?.addEventListener('click', () => openAlertModal(''));
document.getElementById('ticker-alert-btn')?.addEventListener('click', () => openAlertModal(currentSymbol || ''));
document.getElementById('al-cancel')?.addEventListener('click', () => document.getElementById('alert-modal-overlay').classList.remove('open'));
document.getElementById('al-submit')?.addEventListener('click', async () => {
  const ticker = (document.getElementById('al-ticker')?.value || '').trim().toUpperCase();
  const cond   = document.getElementById('al-cond')?.value;
  const price  = parseFloat(document.getElementById('al-price')?.value);
  const errEl  = document.getElementById('al-error');
  if (!ticker)                { errEl.textContent = 'Enter a ticker symbol.'; return; }
  if (isNaN(price)||price<=0) { errEl.textContent = 'Enter a valid price.'; return; }
  if (!authUser)              { errEl.textContent = 'Sign in to save alerts.'; return; }
  const { error } = await sbClient.from('price_alerts').insert({
    user_id: authUser.id, ticker, condition: cond, target_price: price,
  });
  if (error) { errEl.textContent = error.message || 'Failed to save alert.'; return; }
  document.getElementById('alert-modal-overlay').classList.remove('open');
  await loadAlerts();
});

// ---------------------------------------------------------------------------
// Transaction History
// ---------------------------------------------------------------------------
let _txs = [];
let _txType = 'buy';

async function loadTransactions() {
  if (!authUser) return;
  try {
    const { data, error } = await sbClient
      .from('transactions')
      .select('id, ticker, transaction_type, shares, price, transaction_date, notes')
      .order('transaction_date', { ascending: false });
    if (error) throw error;
    _txs = (data || []).map(r => ({
      id: r.id, ticker: r.ticker, tx_type: r.transaction_type,
      shares: Number(r.shares), price: Number(r.price),
      date: r.transaction_date, notes: r.notes || '',
    }));
    renderTxTable();
  } catch (e) { console.warn('loadTransactions failed:', e); }
}

function renderTxTable() {
  const tbody = document.getElementById('tx-tbody');
  const empty = document.getElementById('tx-empty');
  if (!tbody) return;
  if (!_txs.length) { tbody.innerHTML = ''; if (empty) empty.style.display = 'block'; return; }
  if (empty) empty.style.display = 'none';
  tbody.innerHTML = _txs.map(tx => {
    const total = (tx.shares * tx.price).toFixed(2);
    return `<tr>
      <td>${tx.date}</td>
      <td style="font-weight:700;color:var(--accent)">${tx.ticker}</td>
      <td class="${tx.tx_type === 'buy' ? 'tx-buy' : 'tx-sell'}">${tx.tx_type.toUpperCase()}</td>
      <td>${tx.shares}</td><td>$${tx.price.toFixed(2)}</td><td>$${total}</td>
      <td style="color:var(--muted);font-size:11px">${tx.notes || '—'}</td>
      <td><button onclick="deleteTx(${tx.id})" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:14px" onmouseover="this.style.color='var(--red)'" onmouseout="this.style.color='var(--muted)'">×</button></td>
    </tr>`;
  }).join('');
}

async function deleteTx(id) {
  try {
    const { error } = await sbClient.from('transactions').delete().eq('id', id);
    if (error) console.warn('Delete transaction failed:', error);
  } catch (e) { console.warn('Delete transaction failed:', e); }
  _txs = _txs.filter(t => t.id !== id);
  renderTxTable();
}

document.getElementById('tx-buy-btn')?.addEventListener('click', () => {
  _txType = 'buy';
  document.getElementById('tx-buy-btn').className = 'tx-type-btn active-buy';
  document.getElementById('tx-sell-btn').className = 'tx-type-btn';
});
document.getElementById('tx-sell-btn')?.addEventListener('click', () => {
  _txType = 'sell';
  document.getElementById('tx-sell-btn').className = 'tx-type-btn active-sell';
  document.getElementById('tx-buy-btn').className = 'tx-type-btn';
});

function openTxModal() {
  _txType = 'buy';
  document.getElementById('tx-buy-btn').className = 'tx-type-btn active-buy';
  document.getElementById('tx-sell-btn').className = 'tx-type-btn';
  ['tx-ticker','tx-shares','tx-price','tx-notes'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const dateEl = document.getElementById('tx-date');
  if (dateEl) dateEl.value = new Date().toISOString().slice(0,10);
  const errEl = document.getElementById('tx-error');
  if (errEl) errEl.textContent = '';
  document.getElementById('tx-modal-overlay').classList.add('open');
  setTimeout(() => document.getElementById('tx-ticker')?.focus(), 50);
}

document.getElementById('log-tx-btn')?.addEventListener('click', openTxModal);
document.getElementById('tx-cancel')?.addEventListener('click', () => document.getElementById('tx-modal-overlay').classList.remove('open'));
document.getElementById('tx-submit')?.addEventListener('click', async () => {
  const ticker = (document.getElementById('tx-ticker')?.value || '').trim().toUpperCase();
  const shares = parseFloat(document.getElementById('tx-shares')?.value);
  const price  = parseFloat(document.getElementById('tx-price')?.value);
  const date   = document.getElementById('tx-date')?.value;
  const notes  = document.getElementById('tx-notes')?.value || '';
  const errEl  = document.getElementById('tx-error');
  if (!ticker)                   { errEl.textContent = 'Enter a ticker.'; return; }
  if (isNaN(shares)||shares<=0)  { errEl.textContent = 'Enter valid shares.'; return; }
  if (isNaN(price)||price<=0)    { errEl.textContent = 'Enter valid price.'; return; }
  if (!date)                     { errEl.textContent = 'Select a date.'; return; }
  if (!authUser)                 { errEl.textContent = 'Sign in to save transactions.'; return; }
  const { error } = await sbClient.from('transactions').insert({
    user_id: authUser.id, ticker, transaction_type: _txType,
    shares, price, transaction_date: date, notes,
  });
  if (error) { errEl.textContent = error.message || 'Failed to save.'; return; }
  document.getElementById('tx-modal-overlay').classList.remove('open');
  await loadTransactions();
});

// ---------------------------------------------------------------------------
// Stock Screener
// ---------------------------------------------------------------------------
let _scData = [];
let _scSortCol = 'market_cap';
let _scSortAsc = false;
let _scInited = false;

async function initScreener() {
  if (_scInited) return;
  try {
    const res  = await apiFetch('/api/screener?sector=Technology');
    const data = await res.json();
    const sel  = document.getElementById('screener-sector-sel');
    if (sel && data.sectors) {
      sel.innerHTML = data.sectors.map(s => `<option value="${s}">${s}</option>`).join('');
    }
    _scInited = true;
    _scData = data.results || [];
    renderScTable();
  } catch {}
}

async function runScreener() {
  const btn    = document.getElementById('screener-run-btn');
  const status = document.getElementById('screener-status');
  const sector = document.getElementById('screener-sector-sel')?.value || 'Technology';
  const maxPe  = document.getElementById('screener-max-pe')?.value;
  const change = document.getElementById('screener-change-sel')?.value;
  const cap    = document.getElementById('screener-cap-sel')?.value;

  let url = `/api/screener?sector=${encodeURIComponent(sector)}`;
  if (maxPe)               url += `&max_pe=${maxPe}`;
  if (change === 'gainers') url += '&min_change=0';
  if (change === 'losers')  url += '&max_change=0';
  if (change === 'up2')     url += '&min_change=2';
  if (change === 'down2')   url += '&max_change=-2';
  if (cap === 'large')      url += '&min_cap=10000000000';
  if (cap === 'mid')        url += '&min_cap=2000000000&max_cap=10000000000';
  if (cap === 'small')      url += '&max_cap=2000000000';

  if (btn)    { btn.disabled = true; btn.textContent = 'Loading…'; }
  if (status) status.textContent = 'Fetching (~20s)…';

  try {
    const res  = await apiFetch(url);
    const data = await res.json();
    _scData = data.results || [];
    if (status) status.textContent = `${_scData.length} results`;
    renderScTable();
  } catch {
    if (status) status.textContent = 'Error. Try again.';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Run Screener'; }
  }
}

function renderScTable() {
  const tbody = document.getElementById('screener-tbody');
  if (!tbody) return;
  const sorted = [..._scData].sort((a, b) => {
    const av = a[_scSortCol]; const bv = b[_scSortCol];
    if (av == null) return 1; if (bv == null) return -1;
    return _scSortAsc ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });
  if (!sorted.length) {
    tbody.innerHTML = '<tr><td colspan="9" style="text-align:center;color:var(--muted);padding:30px">No results. Adjust filters and run again.</td></tr>';
    return;
  }
  const fmtCap = v => !v ? '—' : v >= 1e12 ? `$${(v/1e12).toFixed(1)}T` : v >= 1e9 ? `$${(v/1e9).toFixed(1)}B` : `$${(v/1e6).toFixed(0)}M`;
  const fmtPct = v => v == null ? '—' : `<span style="color:${v >= 0 ? 'var(--accent)' : 'var(--red)'}">${v >= 0 ? '+' : ''}${v.toFixed(2)}%</span>`;
  const fmt2   = v => v == null ? '—' : v.toFixed(2);
  const fmtDY  = v => v == null ? '—' : `${(v * 100).toFixed(2)}%`;
  tbody.innerHTML = sorted.map(r => `<tr onclick="scGoTicker('${r.ticker}')">
    <td><span class="s-ticker">${r.ticker}</span></td>
    <td><span class="s-company">${r.company}</span></td>
    <td style="color:var(--text)">$${fmt2(r.price)}</td>
    <td>${fmtPct(r.change_pct)}</td>
    <td style="color:var(--muted)">${fmtCap(r.market_cap)}</td>
    <td style="color:var(--muted)">${r.pe == null ? '—' : r.pe.toFixed(1) + 'x'}</td>
    <td style="color:var(--muted)">${r.forward_pe == null ? '—' : r.forward_pe.toFixed(1) + 'x'}</td>
    <td style="color:var(--muted)">${fmt2(r.beta)}</td>
    <td style="color:var(--muted)">${fmtDY(r.div_yield)}</td>
  </tr>`).join('');
}

function scGoTicker(ticker) {
  const termTab = document.querySelector('.nav-tab[data-page="terminal"]');
  if (termTab) termTab.click();
  setTimeout(() => {
    const inp = document.getElementById('ticker-input');
    const btn = document.getElementById('search-btn');
    if (inp && btn) { inp.value = ticker; btn.click(); }
  }, 80);
}

document.getElementById('screener-run-btn')?.addEventListener('click', runScreener);
document.querySelectorAll('.screener-table th[data-col]').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (_scSortCol === col) _scSortAsc = !_scSortAsc;
    else { _scSortCol = col; _scSortAsc = false; }
    renderScTable();
  });
});

// ---------------------------------------------------------------------------
// Live Earnings Calendar
// ---------------------------------------------------------------------------
async function ecLoadLive() {
  const btn = document.getElementById('ec-live-btn');
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  try {
    const res  = await apiFetch('/api/earnings/upcoming');
    const data = await res.json();
    const earnings = data.earnings || [];
    const container = document.getElementById('ec-live-results');
    if (!container) return;
    if (!earnings.length) { container.innerHTML = '<p style="color:var(--muted);text-align:center;padding:20px">No upcoming earnings found for the next 60 days.</p>'; return; }
    const rows = earnings.map(e => {
      const daysUntil = Math.ceil((new Date(e.earnings_date) - new Date()) / 86400000);
      const urgency   = daysUntil <= 7 ? 'color:var(--accent)' : daysUntil <= 14 ? 'color:#f0c000' : 'color:var(--muted)';
      const mcap = e.market_cap ? (e.market_cap >= 1e12 ? `$${(e.market_cap/1e12).toFixed(1)}T` : e.market_cap >= 1e9 ? `$${(e.market_cap/1e9).toFixed(1)}B` : '') : '';
      return `<tr style="border-bottom:1px solid var(--border);cursor:pointer" onclick="ecGoToTicker && ecGoToTicker('${e.ticker}')">
        <td style="padding:8px 12px;font-weight:700;color:var(--accent)">${e.ticker}</td>
        <td style="padding:8px 12px;color:var(--text);font-size:12px">${e.company_name}</td>
        <td style="padding:8px 12px;color:var(--muted);font-size:11px">${e.sector}</td>
        <td style="padding:8px 12px;font-size:12px;${urgency}">${e.earnings_date}</td>
        <td style="padding:8px 12px;color:var(--muted);font-size:11px;${urgency}">${daysUntil > 0 ? `in ${daysUntil}d` : 'today'}</td>
        <td style="padding:8px 12px;color:var(--muted);font-size:11px">${e.eps_estimate != null ? `$${e.eps_estimate.toFixed(2)}` : '—'}</td>
        <td style="padding:8px 12px;color:var(--muted);font-size:11px">${mcap}</td>
      </tr>`;
    }).join('');
    container.innerHTML = `<table style="width:100%;border-collapse:collapse;font-size:12px">
      <thead><tr style="background:var(--panel2)">
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">Ticker</th>
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">Company</th>
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">Sector</th>
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">Date</th>
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">Countdown</th>
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">EPS Est.</th>
        <th style="padding:8px 12px;text-align:left;color:var(--label);font-size:10px;letter-spacing:.1em;text-transform:uppercase">Mkt Cap</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
  } catch(e) {
    const container = document.getElementById('ec-live-results');
    if (container) container.innerHTML = '<p style="color:var(--red);text-align:center;padding:20px">Failed to load live data. Check the API.</p>';
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh'; }
  }
}

// ---------------------------------------------------------------------------
// ── Compare Panel ────────────────────────────────────────────────────────────
// ---------------------------------------------------------------------------
let cmpChart  = null;
let cmpSymbol = null;
let cmpSmileChart  = null;
let cmpOptionsData = null;
let cmpOptionsPanelOpen = false;

function renderCompare(data) {
  // Helper: set textContent on element prefixed with 'cmp-'
  const cs = (id, val) => { const el = document.getElementById('cmp-' + id); if (el) el.textContent = val ?? dash; };

  const h    = data.header       || {};
  const ps   = data.price_stats  || {};
  const vol  = data.volume       || {};
  const fund = data.fundamentals || {};
  const tech = data.technicals   || {};
  const a    = data.analyst      || {};

  // ── Header ────────────────────────────────────────────────────────────────
  cs('hdr-name',     h.company_name || cmpSymbol);
  cs('hdr-ticker',   h.ticker   || '');
  cs('hdr-exchange', h.exchange || '');
  cs('hdr-sector',   h.sector   || '');
  cs('hdr-industry', h.industry || '');
  cs('hdr-price',    fmtPrice(h.current_price));

  const chg = h.change; const pct = h.change_pct;
  const cls = colorClass(chg);
  const chgEl = document.getElementById('cmp-hdr-change');
  const pctEl = document.getElementById('cmp-hdr-changepct');
  chgEl.textContent = chg != null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) : dash;
  chgEl.style.color = cls === 'green' ? 'var(--green)' : cls === 'red' ? 'var(--red)' : '';
  pctEl.textContent = fmtPct(pct);
  pctEl.style.color = cls === 'green' ? 'var(--green)' : cls === 'red' ? 'var(--red)' : '';

  cs('hdr-bid',    fmtPrice(h.bid));
  cs('hdr-ask',    fmtPrice(h.ask));
  cs('hdr-spread', h.spread != null ? h.spread.toFixed(2) : dash);

  if (h.last_updated) {
    try {
      const d = new Date(h.last_updated);
      document.getElementById('cmp-hdr-updated').textContent =
        'LAST ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', timeZoneName: 'short' });
    } catch(e) {}
  }

  // ── Price Stats ───────────────────────────────────────────────────────────
  cs('ps-open',      fmtPrice(ps.open));
  cs('ps-prevclose', fmtPrice(ps.prev_close));
  cs('ps-high',      fmtPrice(ps.day_high));
  cs('ps-low',       fmtPrice(ps.day_low));
  cs('ps-vwap',      fmtPrice(ps.vwap));
  document.getElementById('cmp-range-lo').textContent = fmtPrice(ps.week52_low);
  document.getElementById('cmp-range-hi').textContent = fmtPrice(ps.week52_high);
  const dot = document.getElementById('cmp-range-dot');
  const dotPct = ps.week52_pct != null ? Math.max(2, Math.min(98, ps.week52_pct)) : 50;
  dot.style.left = dotPct + '%';

  // ── Volume ────────────────────────────────────────────────────────────────
  cs('vol-current', fmtVolume(vol.current));
  cs('vol-avg',     fmtVolume(vol.avg_30d));
  const ratioEl = document.getElementById('cmp-vol-ratio');
  const r = vol.ratio;
  if (r == null) { ratioEl.textContent = dash; ratioEl.style.color = ''; }
  else if (r > 2)   { ratioEl.textContent = r.toFixed(2) + 'x  2x SURGE'; ratioEl.style.color = 'var(--green)'; }
  else if (r > 1.5) { ratioEl.textContent = r.toFixed(2) + 'x  HIGH';     ratioEl.style.color = 'var(--yellow)'; }
  else              { ratioEl.textContent = r.toFixed(2) + 'x';            ratioEl.style.color = 'var(--text)'; }

  // ── Fundamentals ─────────────────────────────────────────────────────────
  cs('f-mktcap',   fmtMarketCap(fund.market_cap));
  cs('f-pe',       fmt(fund.pe_trailing));
  cs('f-fwdpe',    fmt(fund.pe_forward));
  cs('f-eps',      fmtPrice(fund.eps_ttm));
  cs('f-pb',       fmt(fund.price_to_book));
  cs('f-evebitda', fmt(fund.ev_ebitda));
  cs('f-rev',      fmtMarketCap(fund.revenue_ttm));
  cs('f-ebitdam',  fmtRatioPct(fund.ebitda_margin));
  cs('f-div',      fmtRatioPct(fund.dividend_yield));

  // ── Technicals ────────────────────────────────────────────────────────────
  cs('t-rsi-val', fmt(tech.rsi?.value));
  const rsiLblEl = document.getElementById('cmp-t-rsi-lbl');
  const rsiLbl = tech.rsi?.label;
  if (rsiLbl) {
    rsiLblEl.textContent = rsiLbl;
    rsiLblEl.style.color = rsiLbl === 'Overbought' ? 'var(--red)' : rsiLbl === 'Oversold' ? 'var(--green)' : 'var(--muted)';
  } else { rsiLblEl.textContent = ''; }

  cs('t-macd-val',  fmt(tech.macd?.value, 4));
  cs('t-macd-sig',  fmt(tech.macd?.signal, 4));
  cs('t-macd-hist', fmt(tech.macd?.histogram, 4));
  const dirEl = document.getElementById('cmp-t-macd-dir');
  dirEl.textContent = tech.macd?.direction || dash;
  dirEl.style.color = tech.macd?.direction === 'Bullish' ? 'var(--green)' : tech.macd?.direction === 'Bearish' ? 'var(--red)' : '';

  const cmpSMA = (sfx, sma) => {
    const vEl = document.getElementById('cmp-t-' + sfx + '-val');
    const pEl = document.getElementById('cmp-t-' + sfx + '-pos');
    if (vEl) vEl.textContent = fmtPrice(sma?.value);
    if (pEl) { pEl.textContent = sma?.position || ''; pEl.style.color = sma?.position === 'Above' ? 'var(--green)' : sma?.position === 'Below' ? 'var(--red)' : ''; }
  };
  cmpSMA('sma20',  tech.sma20);
  cmpSMA('sma50',  tech.sma50);
  cmpSMA('sma200', tech.sma200);
  cs('t-beta', fmt(tech.beta));
  cs('t-hv', tech.hv30d != null ? tech.hv30d.toFixed(1) + '%' : dash);

  // ── Analyst ───────────────────────────────────────────────────────────────
  const total = (a.buy || 0) + (a.hold || 0) + (a.sell || 0);
  if (total > 0) {
    document.getElementById('cmp-an-bar-buy').style.width  = ((a.buy  || 0) / total * 100) + '%';
    document.getElementById('cmp-an-bar-hold').style.width = ((a.hold || 0) / total * 100) + '%';
    document.getElementById('cmp-an-bar-sell').style.width = ((a.sell || 0) / total * 100) + '%';
  }
  document.getElementById('cmp-an-buy').textContent  = a.buy  != null ? a.buy  : dash;
  document.getElementById('cmp-an-hold').textContent = a.hold != null ? a.hold : dash;
  document.getElementById('cmp-an-sell').textContent = a.sell != null ? a.sell : dash;
  const consEl = document.getElementById('cmp-an-consensus');
  consEl.textContent = a.consensus || dash;
  if (a.consensus) {
    const c = a.consensus;
    consEl.style.color = c === 'Strong Buy' ? 'var(--green)' : c === 'Buy' ? '#66ff99' : c === 'Strong Sell' ? 'var(--red)' : c === 'Sell' ? '#ff7777' : 'var(--yellow)';
  }
  cs('an-target', fmtPrice(a.target_price));
  const upEl = document.getElementById('cmp-an-upside');
  upEl.textContent = fmtPct(a.implied_upside);
  upEl.style.color = a.implied_upside != null ? (a.implied_upside >= 0 ? 'var(--green)' : 'var(--red)') : '';

  // ── Chart ─────────────────────────────────────────────────────────────────
  if (cmpChart) { cmpChart.destroy(); cmpChart = null; }
  if (data.chart?.dates?.length && data.chart?.prices?.length) {
    const ctx    = document.getElementById('cmp-chart').getContext('2d');
    const prices = data.chart.prices;
    const isUp   = prices.length > 1 && prices[prices.length - 1] >= prices[0];
    const col    = isUp ? '#00ff88' : '#ff5050';
    const gradFn = c => {
      const g = c.chart.ctx.createLinearGradient(0, 0, 0, 280);
      g.addColorStop(0, isUp ? 'rgba(0,255,136,.15)' : 'rgba(255,80,80,.15)');
      g.addColorStop(1, 'rgba(0,0,0,0)');
      return g;
    };
    const mkSMA = (d, color) => d ? { label: '', data: d, borderColor: color, borderWidth: 1, pointRadius: 0, fill: false, tension: 0.3 } : null;
    cmpChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: data.chart.dates,
        datasets: [
          { label: cmpSymbol, data: prices, borderColor: col, borderWidth: 1.5, pointRadius: 0, fill: true, backgroundColor: gradFn, tension: 0.3 },
          mkSMA(data.chart.sma20,  '#58a6ff'),
          mkSMA(data.chart.sma50,  '#f0b429'),
          mkSMA(data.chart.sma200, '#f778ba'),
        ].filter(Boolean),
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => '$' + ctx.parsed.y.toFixed(2) } },
        },
        scales: {
          x: { display: false },
          y: { display: true, position: 'right', ticks: { color: '#555', font: { size: 9 }, maxTicksLimit: 5, callback: v => '$' + v.toFixed(0) }, grid: { color: 'rgba(255,255,255,0.04)' } },
        },
      },
    });
  }
}

async function loadCompare(symbol) {
  symbol = symbol.trim().toUpperCase();
  if (!symbol) return;
  cmpSymbol = symbol;
  document.getElementById('cmp-empty').style.display   = 'none';
  document.getElementById('cmp-body').style.display    = 'none';
  document.getElementById('cmp-loading').style.display = 'block';
  if (cmpSmileChart) { cmpSmileChart.destroy(); cmpSmileChart = null; }
  document.getElementById('cmp-options-panel').classList.add('hidden');
  try {
    const res = await apiFetch('/api/ticker/' + encodeURIComponent(symbol));
    if (!res.ok) throw new Error('not found');
    const data = await res.json();
    renderCompare(data);
    document.getElementById('cmp-loading').style.display = 'none';
    document.getElementById('cmp-body').style.display    = 'block';
    loadCmpOptions(symbol);
  } catch (e) {
    document.getElementById('cmp-loading').style.display = 'none';
    document.getElementById('cmp-empty').style.display   = '';
    const emptyMsg = document.getElementById('cmp-empty-msg');
    if (emptyMsg) emptyMsg.textContent = 'Ticker not found or no data available.';
  }
}

function _openCompare() {
  document.getElementById('compare-panel').classList.add('open');
  document.getElementById('compare-toggle-btn').classList.add('active');
  document.getElementById('compare-toggle-btn').textContent = '✕ Remove Asset';
  setTimeout(() => document.getElementById('cmp-input').focus(), 80);
}
function _closeCompare() {
  document.getElementById('compare-panel').classList.remove('open');
  document.getElementById('compare-toggle-btn').classList.remove('active');
  document.getElementById('compare-toggle-btn').textContent = '＋ Add Asset';
  document.getElementById('cmp-body').style.display  = 'none';
  document.getElementById('cmp-empty').style.display = '';
  const emptyMsg = document.getElementById('cmp-empty-msg');
  if (emptyMsg) emptyMsg.innerHTML = 'Enter a ticker above<br>to compare side by side';
  document.getElementById('cmp-input').value = '';
  if (cmpChart) { cmpChart.destroy(); cmpChart = null; }
  if (cmpSmileChart) { cmpSmileChart.destroy(); cmpSmileChart = null; }
  document.getElementById('cmp-options-panel').classList.add('hidden');
  document.getElementById('cmp-options-body').classList.add('hidden');
  cmpOptionsPanelOpen = false;
  cmpOptionsData = null;
  cmpSymbol = null;
  ['cmp-an-bar-buy','cmp-an-bar-hold','cmp-an-bar-sell'].forEach(id => {
    const el = document.getElementById(id); if (el) el.style.width = '0%';
  });
}

// ── Compare Options Analytics ─────────────────────────────────────────────────

document.getElementById('cmp-options-toggle').addEventListener('click', () => {
  cmpOptionsPanelOpen = !cmpOptionsPanelOpen;
  document.getElementById('cmp-options-body').classList.toggle('hidden', !cmpOptionsPanelOpen);
  document.getElementById('cmp-options-arrow').classList.toggle('open', cmpOptionsPanelOpen);
});

async function loadCmpOptions(symbol) {
  const panel = document.getElementById('cmp-options-panel');
  panel.classList.add('hidden');
  cmpOptionsData = null;
  try {
    const res = await apiFetch('/api/options/' + encodeURIComponent(symbol));
    if (!res.ok) return;
    const data = await res.json();
    if (!data.available) return;
    cmpOptionsData = data;
    panel.classList.remove('hidden');
    document.getElementById('cmp-options-sparse-warn').classList.toggle('hidden', !data.is_sparse);
    renderCmpImpliedMoves(data.implied_moves || []);
    buildCmpSmileSelector(data);
    if (data.default_smile_exp && data.smiles && data.smiles[data.default_smile_exp]) {
      renderCmpSmileChart(data.smiles[data.default_smile_exp]);
    }
    if (data.surface) renderCmpVolSurface(data.surface);
  } catch(e) {}
}

function renderCmpImpliedMoves(moves) {
  const strip = document.getElementById('cmp-implied-strip');
  if (!moves.length) { strip.innerHTML = '<span style="color:var(--muted);font-size:11px">No implied move data available.</span>'; return; }
  strip.innerHTML = moves.map(m => {
    const pct = m.implied_move_pct;
    let cls = 'g';
    if (pct > 10) cls = 'r';
    else if (pct > 6) cls = 'o';
    else if (pct > 3) cls = 'y';
    return `<div class="move-card">
      <span class="move-pct ${cls}">±${pct != null ? pct.toFixed(1) : '—'}%</span>
      <span class="move-date">${m.exp_label || m.expiration}</span>
      <span class="move-dte">${m.days_to_expiry != null ? m.days_to_expiry + 'd' : ''}</span>
      <div class="move-tooltip">
        ATM Strike: $${m.atm_strike != null ? m.atm_strike.toFixed(0) : '—'}<br>
        Call Mid: $${m.atm_call_mid != null ? m.atm_call_mid.toFixed(2) : '—'}<br>
        Put Mid: $${m.atm_put_mid  != null ? m.atm_put_mid.toFixed(2)  : '—'}
      </div>
    </div>`;
  }).join('');
}

function buildCmpSmileSelector(data) {
  const sel = document.getElementById('cmp-smile-exp-select');
  sel.innerHTML = '';
  const exps = data.available_expirations || [];
  exps.forEach(e => {
    const opt = document.createElement('option');
    opt.value = e.expiration;
    opt.textContent = e.exp_label + (e.days_to_expiry != null ? '  (' + e.days_to_expiry + 'd)' : '');
    if (e.expiration === data.default_smile_exp) opt.selected = true;
    sel.appendChild(opt);
  });
  sel.onchange = () => {
    const exp = sel.value;
    if (data.smiles && data.smiles[exp]) renderCmpSmileChart(data.smiles[exp]);
  };
}

function renderCmpSmileChart(smileExp) {
  if (!smileExp || !smileExp.strikes) return;
  const strikes   = smileExp.strikes;
  const labels    = strikes.map(s => s.strike);
  const callIVs   = strikes.map(s => (s.call_iv != null && s.call_iv > 0) ? s.call_iv : null);
  const putIVs    = strikes.map(s => (s.put_iv  != null && s.put_iv  > 0) ? s.put_iv  : null);
  const atmStrike = smileExp.atm_strike;

  const badge = document.getElementById('cmp-smile-skew-badge');
  if (smileExp.skew_label) {
    badge.textContent = smileExp.skew_label;
    badge.className   = 'smile-skew-badge';
    if (smileExp.skew_label.startsWith('PUT'))       badge.classList.add('put');
    else if (smileExp.skew_label.startsWith('CALL')) badge.classList.add('call');
    else badge.classList.add('sym');
    badge.classList.remove('hidden');
  } else {
    badge.classList.add('hidden');
  }

  const ctx = document.getElementById('cmp-smile-chart').getContext('2d');
  if (cmpSmileChart) { cmpSmileChart.destroy(); cmpSmileChart = null; }
  cmpSmileChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Call IV', data: callIVs, borderColor: '#4fc3f7', borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#4fc3f7', tension: 0.2, fill: false, spanGaps: true },
        { label: 'Put IV',  data: putIVs,  borderColor: '#ffb74d', borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#ffb74d', tension: 0.2, fill: false, spanGaps: true },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: true, labels: { color: '#7d8590', font: { family: 'Inter', size: 10 }, boxWidth: 12, padding: 14 } },
        tooltip: {
          backgroundColor: '#1a1a1a', borderColor: '#2a2a2a', borderWidth: 1,
          titleColor: '#666', bodyColor: '#e0e0e0', padding: 10,
          callbacks: {
            title: items => '$' + items[0].label,
            label: ctx => { const v = ctx.parsed.y; return v != null ? ' ' + ctx.dataset.label + ': ' + v.toFixed(1) + '%' : null; },
          },
        },
        atmLine: { xValue: atmStrike },
      },
      scales: {
        x: { type: 'linear', grid: { color: '#1a1a1a' }, ticks: { color: '#555', maxTicksLimit: 10, font: { family: 'JetBrains Mono', size: 10 }, callback: v => '$' + v }, title: { display: true, text: 'Strike', color: '#555', font: { size: 10 } } },
        y: { position: 'right', grid: { color: '#1a1a1a' }, ticks: { color: '#555', font: { family: 'JetBrains Mono', size: 10 }, callback: v => v.toFixed(0) + '%' }, title: { display: true, text: 'Implied Volatility', color: '#555', font: { size: 10 } } },
      },
    },
  });
}

function renderCmpVolSurface(surface) {
  const thead = document.getElementById('cmp-surface-thead');
  const tbody = document.getElementById('cmp-surface-tbody');
  if (!surface || !surface.rows || !surface.rows.length) { thead.innerHTML = ''; tbody.innerHTML = ''; return; }
  const { rows, iv_min, iv_max } = surface;
  const exps = rows[0].cells.map(c => c);
  thead.innerHTML = '<tr><th>Moneyness</th>' + exps.map(c => `<th>${c.exp_label}</th>`).join('') + '</tr>';
  tbody.innerHTML = rows.map(row => {
    const label = `${row.moneyness_label}<br><span style="color:var(--label);font-size:9px">$${row.strike != null ? row.strike.toFixed(0) : '—'}</span>`;
    const cells = row.cells.map(c => {
      const iv  = c.avg_iv;
      const bg  = surfaceColor(iv, iv_min, iv_max);
      const fg  = surfaceTextColor(iv, iv_min, iv_max);
      const atm = c.is_atm ? ' atm-cell' : '';
      const tip = `Strike $${row.strike != null ? row.strike.toFixed(0) : '—'} | ${c.exp_label} | IV: ${iv != null ? iv.toFixed(1) + '%' : '—'} | Call OI: ${c.call_oi != null ? Math.round(c.call_oi).toLocaleString() : '—'} | Put OI: ${c.put_oi != null ? Math.round(c.put_oi).toLocaleString() : '—'}`;
      return `<td class="${atm}" style="background:${bg};color:${fg}" title="${tip}">${iv != null ? iv.toFixed(1) + '%' : '—'}</td>`;
    }).join('');
    return `<tr><td>${label}</td>${cells}</tr>`;
  }).join('');
}

// Compare toggle
document.getElementById('compare-toggle-btn').addEventListener('click', () => {
  const open = document.getElementById('compare-panel').classList.contains('open');
  open ? _closeCompare() : _openCompare();
});
document.getElementById('cmp-close-btn').addEventListener('click', _closeCompare);
document.getElementById('cmp-go-btn').addEventListener('click', () => {
  loadCompare(document.getElementById('cmp-input').value);
});
document.getElementById('cmp-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') loadCompare(document.getElementById('cmp-input').value);
});

// ---------------------------------------------------------------------------
// ── Portfolio-aware news ─────────────────────────────────────────────────────
// ---------------------------------------------------------------------------
let _pfImpacts    = [];   // [{article_id, ticker, direction, note}]
let _nfPfOnly     = false;

async function loadPortfolioNewsImpact() {
  // Use pfData.positions (has real sector from yfinance) when available,
  // otherwise fall back to raw pfPositions (no sector info).
  let tickerObjs;
  if (pfData && pfData.positions && pfData.positions.length > 0) {
    tickerObjs = pfData.positions.map(p => ({ ticker: p.ticker, sector: p.sector || '' }));
  } else {
    tickerObjs = (pfPositions || []).map(p => ({ ticker: p.ticker, sector: '' }));
  }
  tickerObjs = tickerObjs.filter(t => t.ticker);
  if (!tickerObjs.length || !newsArticles.length) return;

  // Reveal the Portfolio sidebar panel (hidden until holdings are loaded)
  const pfPanel = document.getElementById('pf-filter-panel');
  if (pfPanel) pfPanel.style.display = '';

  const articles = newsArticles.map((a, i) => ({
    id: i, title: a.title || '', summary: a.summary || ''
  }));

  try {
    const res  = await apiFetch('/api/news/portfolio-impact', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tickers: tickerObjs, articles }),
    });
    const data = await res.json();
    _pfImpacts = data.impacts || [];
    renderNewsCards(newsArticles);   // re-render with badges
  } catch {}
}

function _articleImpacts(articleIdx) {
  return _pfImpacts.filter(i => i.article_id === articleIdx);
}

// Portfolio filter button (sidebar)
document.getElementById('nf-pf-btn')?.addEventListener('click', function() {
  _nfPfOnly = !_nfPfOnly;
  this.classList.toggle('active', _nfPfOnly);
  renderNewsCards(newsArticles);
});

// ── Wire options into ticker load ────────────────────────────────────────────
const _origLoadTicker = loadTicker;
loadTicker = async function(symbol, isRefresh = false) {
  await _origLoadTicker(symbol, isRefresh);
  if (!isRefresh) loadOptions(symbol);
  // Reset AI panel when new ticker loaded
  if (!isRefresh) {
    document.getElementById('ai-panel').classList.remove('visible');
    document.getElementById('ai-content').innerHTML = '';
  }
};

// ---------------------------------------------------------------------------
// Auth state — synced with Supabase session via onAuthStateChange below
// ---------------------------------------------------------------------------
let authToken = null;
let authUser  = null;

// One-time cleanup of legacy JWT-era localStorage keys
localStorage.removeItem('auth_token');
localStorage.removeItem('auth_user');

// ---------------------------------------------------------------------------
// Server sync helpers (portfolio + watchlist) — direct to Supabase with RLS
// ---------------------------------------------------------------------------
async function pushPortfolioToServer() {
  if (!authUser || !pfPositions) return;
  try {
    const userId = authUser.id;
    await sbClient.from('portfolio_holdings').delete().eq('user_id', userId);
    if (pfPositions.length > 0) {
      const seen = new Set();
      const rows = [];
      for (const p of pfPositions) {
        const tk = (p.ticker || '').toUpperCase().trim();
        if (!tk || seen.has(tk)) continue;
        seen.add(tk);
        rows.push({ user_id: userId, ticker: tk, shares: p.shares, avg_cost: p.avg_cost });
      }
      if (rows.length) await sbClient.from('portfolio_holdings').insert(rows);
    }
  } catch (_) { /* offline — local state is the source of truth */ }
}

async function pushWatchlistToServer() {
  if (!authUser || !wlTickers) return;
  try {
    const userId = authUser.id;
    await sbClient.from('watchlist').delete().eq('user_id', userId);
    const seen = new Set();
    const rows = [];
    for (const t of wlTickers) {
      const tk = (t || '').toUpperCase().trim();
      if (!tk || seen.has(tk)) continue;
      seen.add(tk);
      rows.push({ user_id: userId, ticker: tk });
    }
    if (rows.length) await sbClient.from('watchlist').insert(rows);
  } catch (_) { /* offline */ }
}

async function syncAfterLogin() {
  if (!authUser) return;
  try {
    const [pfRes, wlRes] = await Promise.all([
      sbClient.from('portfolio_holdings').select('ticker, shares, avg_cost'),
      sbClient.from('watchlist').select('ticker').order('created_at', { ascending: true }),
    ]);
    if (pfRes.error) { console.warn('portfolio fetch:', pfRes.error); return; }
    if (wlRes.error) { console.warn('watchlist fetch:', wlRes.error); return; }

    const serverPositions = (pfRes.data || []).map(r => ({
      ticker: r.ticker, shares: Number(r.shares), avg_cost: Number(r.avg_cost),
    }));
    const serverTickers = (wlRes.data || []).map(r => r.ticker);

    if (serverPositions.length > 0) {
      pfPositions = serverPositions;
      localStorage.setItem('pf_positions', JSON.stringify(pfPositions));
    } else if (pfPositions.length > 0) {
      await pushPortfolioToServer();
    }

    if (serverTickers.length > 0) {
      wlTickers = serverTickers;
      localStorage.setItem('wl_tickers', JSON.stringify(wlTickers));
    } else if (wlTickers.length > 0) {
      await pushWatchlistToServer();
    }

    renderPfTable(null);
    pfData = null;
    renderWlTable([]);
    wlLoaded = false;
  } catch (err) {
    console.warn('syncAfterLogin failed:', err);
  }
}

// ---------------------------------------------------------------------------
// Auth helpers — app is fully public, no gate
// ---------------------------------------------------------------------------
function lockApp()   { /* removed — app is public */ }
function unlockApp() { /* removed */ }

function _applySession(session) {
  if (session) {
    authToken = session.access_token;
    authUser  = { id: session.user.id, email: session.user.email };
  } else {
    authToken = null;
    authUser  = null;
  }
  document.body.classList.toggle('authed', !!authUser);
  document.body.classList.toggle('guest',  !authUser);
  renderUserPill();
  _updateGuestBanners();
}

// Kept for backwards compat — the UI flow now goes through onAuthStateChange.
function setAuth() {
  renderUserPill();
  _updateGuestBanners();
  syncAfterLogin();
  loadAlerts();
  loadTransactions();
}

function clearAuth() {
  if (typeof sbClient !== 'undefined' && sbClient && sbClient.auth) {
    sbClient.auth.signOut().catch(() => {});
  }
  authToken = null;
  authUser  = null;
  _alerts = [];
  _txs = [];
  renderUserPill();
  _updateGuestBanners();
  if (typeof renderAlerts === 'function') renderAlerts();
  if (typeof renderTxTable === 'function') renderTxTable();
}

function renderUserPill() {
  const signInBtn = document.getElementById('nav-signin-btn');
  const pill      = document.getElementById('nav-user-pill');
  const avatar    = document.getElementById('nav-avatar');
  const emailEl   = document.getElementById('nav-user-email');
  if (authUser) {
    signInBtn.style.display = 'none';
    pill.classList.add('visible');
    avatar.textContent = authUser.email[0].toUpperCase();
    emailEl.textContent = authUser.email;
  } else {
    signInBtn.style.display = '';   // show Sign In when logged out
    pill.classList.remove('visible');
  }
}

function _updateGuestBanners() {
  const loggedIn = !!authUser;
  const el = (id) => document.getElementById(id);
  // portfolio banner
  if (el('pf-guest-banner'))  el('pf-guest-banner').style.display  = loggedIn ? 'none' : 'block';
  // watchlist banner
  if (el('wl-guest-banner'))  el('wl-guest-banner').style.display  = loggedIn ? 'none' : 'block';
  // alerts — guest state vs real content
  if (el('alerts-guest'))     el('alerts-guest').style.display     = loggedIn ? 'none' : 'block';
  if (el('alerts-tbl'))       el('alerts-tbl').style.display       = loggedIn ? ''     : 'none';
  if (el('add-alert-btn'))    el('add-alert-btn').style.display     = loggedIn ? ''     : 'none';
}

// Subscribe to Supabase auth state. Fires INITIAL_SESSION on load with current
// session (or null), then SIGNED_IN / SIGNED_OUT / TOKEN_REFRESHED / PASSWORD_RECOVERY.
// Guarded so the rest of the page still works if SUPABASE_URL/ANON_KEY weren't
// injected (e.g. local dev without .env) — in that case the app stays in guest mode.
if (typeof sbClient !== 'undefined' && sbClient && sbClient.auth) {
  sbClient.auth.onAuthStateChange((event, session) => {
    _applySession(session);
    if ((event === 'SIGNED_IN' || event === 'INITIAL_SESSION') && session) {
      syncAfterLogin();
      loadAlerts();
      loadTransactions();
    } else if (event === 'SIGNED_OUT') {
      _alerts = [];
      _txs = [];
      if (typeof renderAlerts === 'function') renderAlerts();
      if (typeof renderTxTable === 'function') renderTxTable();
    } else if (event === 'PASSWORD_RECOVERY') {
      document.getElementById('auth-overlay')?.classList.add('open');
      document.getElementById('auth-main-fields').style.display = 'none';
      document.getElementById('auth-reset-view').classList.add('visible');
    }
  });
} else {
  console.warn('Supabase client not initialized — app running in guest-only mode');
}

// Initial paint before INITIAL_SESSION fires — assume guest until SDK reports
document.body.classList.add('guest');
renderUserPill();
_updateGuestBanners();

// ---------------------------------------------------------------------------
// Auth modal
// ---------------------------------------------------------------------------
let authMode = 'login'; // 'login' | 'register'

function openAuthModal(mode = 'login') {
  authMode = mode;
  document.getElementById('auth-overlay').classList.add('open');
  document.getElementById('auth-error').textContent = '';
  document.getElementById('auth-email').value = '';
  document.getElementById('auth-password').value = '';
  document.querySelectorAll('.auth-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.auth === mode);
  });
  document.getElementById('auth-submit-btn').textContent = mode === 'login' ? 'Sign In' : 'Create Account';
  setTimeout(() => document.getElementById('auth-email').focus(), 50);
}

function closeAuthModal() {
  document.getElementById('auth-overlay').classList.remove('open');
}

document.getElementById('nav-signin-btn').addEventListener('click', () => openAuthModal('login'));
document.getElementById('auth-close').addEventListener('click', closeAuthModal);
document.getElementById('auth-overlay').addEventListener('click', e => {
  if (e.target === document.getElementById('auth-overlay')) closeAuthModal();
});

document.querySelectorAll('.auth-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    authMode = tab.dataset.auth;
    document.querySelectorAll('.auth-tab').forEach(t => t.classList.toggle('active', t.dataset.auth === authMode));
    document.getElementById('auth-submit-btn').textContent = authMode === 'login' ? 'Sign In' : 'Create Account';
    document.getElementById('auth-error').textContent = '';
  });
});

// Enter key submits
document.getElementById('auth-password').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('auth-submit-btn').click();
});
document.getElementById('auth-email').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('auth-password').focus();
});

document.getElementById('auth-submit-btn').addEventListener('click', async () => {
  const btn      = document.getElementById('auth-submit-btn');
  const errorEl  = document.getElementById('auth-error');
  const email    = document.getElementById('auth-email').value.trim();
  const password = document.getElementById('auth-password').value;

  if (!email || !password) { errorEl.textContent = 'Please fill in all fields.'; return; }

  btn.disabled = true;
  btn.textContent = authMode === 'login' ? 'Signing in…' : 'Creating account…';
  errorEl.style.color = '';
  errorEl.textContent = '';

  try {
    if (authMode === 'login') {
      const { error } = await sbClient.auth.signInWithPassword({ email, password });
      if (error) throw error;
      // onAuthStateChange handles sync + render
      closeAuthModal();
    } else {
      const { data, error } = await sbClient.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin + '/' },
      });
      if (error) throw error;
      // If email confirmation is required, no session is returned yet.
      if (!data.session) {
        errorEl.style.color = 'var(--accent)';
        errorEl.textContent = 'Account created. Check your email to confirm.';
        btn.disabled = false;
        btn.textContent = 'Create Account';
        return;
      }
      closeAuthModal();
    }
  } catch (err) {
    errorEl.textContent = (err && err.message) || 'Something went wrong.';
    btn.disabled = false;
    btn.textContent = authMode === 'login' ? 'Sign In' : 'Create Account';
  }
});

document.getElementById('nav-logout-btn').addEventListener('click', () => {
  clearAuth();
  document.getElementById('ai-panel').classList.remove('visible');
});

// ---------------------------------------------------------------------------
// Password Reset
// ---------------------------------------------------------------------------
document.getElementById('auth-forgot-link')?.addEventListener('click', () => {
  document.getElementById('auth-main-fields').style.display = 'none';
  document.getElementById('auth-forgot-view').classList.add('visible');
  document.getElementById('auth-reset-view').classList.remove('visible');
});
document.getElementById('auth-forgot-back')?.addEventListener('click', () => {
  document.getElementById('auth-main-fields').style.display = '';
  document.getElementById('auth-forgot-view').classList.remove('visible');
});
document.getElementById('forgot-submit-btn')?.addEventListener('click', async () => {
  const email = document.getElementById('forgot-email')?.value.trim();
  const errEl = document.getElementById('forgot-error');
  const succEl = document.getElementById('forgot-success');
  if (!email) { if (errEl) errEl.textContent = 'Enter your email.'; return; }
  const btn = document.getElementById('forgot-submit-btn');
  btn.disabled = true; btn.textContent = 'Sending…';
  if (errEl) errEl.textContent = '';
  try {
    await sbClient.auth.resetPasswordForEmail(email, {
      redirectTo: window.location.origin + '/',
    });
  } catch (e) { console.warn('Forgot password request failed:', e); }
  if (succEl) succEl.style.display = '';
  btn.disabled = false; btn.textContent = 'Send Reset Link';
});
document.getElementById('reset-submit-btn')?.addEventListener('click', async () => {
  const pw1 = document.getElementById('reset-password-input')?.value;
  const pw2 = document.getElementById('reset-password-confirm')?.value;
  const errEl = document.getElementById('reset-error');
  if (pw1 !== pw2) { if (errEl) errEl.textContent = 'Passwords do not match.'; return; }
  if (!pw1 || pw1.length < 6) { if (errEl) errEl.textContent = 'Min. 6 characters.'; return; }
  const btn = document.getElementById('reset-submit-btn');
  btn.disabled = true; btn.textContent = 'Updating…';
  try {
    const { error } = await sbClient.auth.updateUser({ password: pw1 });
    if (error) {
      if (errEl) errEl.textContent = error.message || 'Could not update password.';
      btn.disabled = false; btn.textContent = 'Update Password';
      return;
    }
    closeAuthModal();
    document.getElementById('auth-main-fields').style.display = '';
    document.getElementById('auth-reset-view').classList.remove('visible');
    window.history.replaceState({}, '', '/');
  } catch {
    if (errEl) errEl.textContent = 'Network error.';
    btn.disabled = false; btn.textContent = 'Update Password';
  }
});
// PASSWORD_RECOVERY event from onAuthStateChange handles the recovery-link entry point.

// ---------------------------------------------------------------------------
// Wire save functions → server push on every change
// (savePfPositions and saveWlTickers are declared earlier;
//  we override them here once auth JS is in scope)
// ---------------------------------------------------------------------------
const _localSavePf = savePfPositions;
savePfPositions = function () {
  _localSavePf();
  pushPortfolioToServer();
};

const _localSaveWl = saveWlTickers;
saveWlTickers = function () {
  _localSaveWl();
  pushWatchlistToServer();
};

// ---------------------------------------------------------------------------
// AI Analysis
// ---------------------------------------------------------------------------
let aiAbortCtrl = null;

function renderMarkdown(text) {
  return text
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/(<li>.*<\/li>\n?)+/g, match => `<ul>${match}</ul>`)
    .replace(/\n\n/g, '</p><p>')
    .replace(/^(?!<[hup])/gm, '')
    .trim();
}

document.getElementById('ai-analyze-btn').addEventListener('click', async () => {
  if (!authToken) {
    openAuthModal('login');
    return;
  }
  if (!currentSymbol) return;

  const btn     = document.getElementById('ai-analyze-btn');
  const panel   = document.getElementById('ai-panel');
  const content = document.getElementById('ai-content');

  // Abort previous if running
  if (aiAbortCtrl) aiAbortCtrl.abort();
  aiAbortCtrl = new AbortController();

  btn.disabled = true;
  btn.classList.add('loading');
  btn.innerHTML = '<span class="ai-btn-icon">↻</span> Analyzing…';
  panel.classList.add('visible');
  content.innerHTML = '<span class="ai-cursor"></span>';

  let raw = '';

  try {
    const res = await apiFetch(`/api/analyze/${currentSymbol}`, {
      headers: { Authorization: `Bearer ${authToken}` },
      signal: aiAbortCtrl.signal,
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Analysis failed' }));
      if (res.status === 401) {
        clearAuth();
        closeAuthModal();
        openAuthModal('login');
        panel.classList.remove('visible');
        return;
      }
      content.innerHTML = `<p style="color:var(--red)">${err.detail}</p>`;
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    content.innerHTML = '<span class="ai-cursor"></span>';
    const cursor = content.querySelector('.ai-cursor');

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      for (const line of chunk.split('\n')) {
        if (!line.startsWith('data: ')) continue;
        const payload = line.slice(6).trim();
        if (payload === '[DONE]') break;
        try {
          const { text, error } = JSON.parse(payload);
          if (error) { raw += `\n\n*Error: ${error}*`; break; }
          if (text) raw += text;
        } catch { /* partial chunk */ }
      }
      // Re-render with cursor at end
      const _sanitize = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize : (h => h);
      content.innerHTML = _sanitize(renderMarkdown(raw)) + '<span class="ai-cursor"></span>';
      content.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // Final render without cursor
    const _sanitizeFinal = typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize : (h => h);
    content.innerHTML = _sanitizeFinal(renderMarkdown(raw));

  } catch (err) {
    if (err.name !== 'AbortError') {
      content.innerHTML = `<p style="color:var(--red)">Connection error. Please try again.</p>`;
    }
  } finally {
    btn.disabled = false;
    btn.classList.remove('loading');
    btn.innerHTML = '<span class="ai-btn-icon">✦</span> Re-analyze';
  }
});

// ---------------------------------------------------------------------------
// Global Yields page — D3 world map + Chart.js sovereign yield curves
// ---------------------------------------------------------------------------
const yieldsState = {
  countries:   null,           // { code: {code, name, iso_n3, yield_10y, slope_2_10, source} }
  byIso:       null,           // map iso_n3 string -> country obj
  worldGeo:    null,           // topojson FeatureCollection
  selected:    null,           // currently selected country code
  compare:     [],             // additional country codes
  detailCache: {},             // code -> full curve response
  curveChart:  null,
  mode:        'picker',       // 'picker' | 'heatmap-10y' | 'heatmap-slope'
  status:      'pending',
};
const YIELDS_COMPARE_MAX  = 4;
const YIELDS_PALETTE      = ['#00d97e', '#58a6ff', '#f0b429', '#f778ba', '#a371f7'];
const YIELDS_HEATMAP_LO   = '#1d3a5f';
const YIELDS_HEATMAP_HI   = '#f0b429';
const YIELDS_INVERTED_COL = '#f85149';

async function yieldsInit() {
  if (yieldsState.countries && yieldsState.worldGeo) {
    yieldsRenderMap();
    return;
  }
  const status = document.getElementById('yields-status');
  if (status) status.textContent = 'Loading map and yield data…';
  try {
    const [countriesRes, geoRes] = await Promise.all([
      apiFetch('/api/yields/countries'),
      fetch('/static/data/world-110m.json'),
    ]);
    const countriesPayload = await countriesRes.json();
    const geo              = await geoRes.json();
    yieldsState.countries  = {};
    yieldsState.byIso      = {};
    for (const c of countriesPayload.countries) {
      yieldsState.countries[c.code] = c;
      yieldsState.byIso[c.iso_n3]   = c;
    }
    yieldsState.worldGeo = geo;
    if (status) {
      const fresh = countriesPayload.countries.filter(c => c.source.startsWith('fred')).length;
      const total = countriesPayload.countries.length;
      status.textContent = `${total} countries · ${fresh} live from FRED · snapshot ${countriesPayload.as_of}`;
    }
    yieldsRenderMap();
    yieldsBindToolbar();
    yieldsBindCompareModal();
    // Restore last selection
    const last = localStorage.getItem('yields_last');
    if (last && yieldsState.countries[last]) yieldsSelectCountry(last);
  } catch (e) {
    if (status) status.textContent = 'Failed to load yield data. Try again.';
  }
}

function yieldsRenderMap() {
  const wrap = document.getElementById('yields-map');
  if (!wrap) return;
  // The first render right after the tab becomes visible can read a stale
  // clientWidth. Re-check after the next frame and re-run if it grew.
  const measuredW = wrap.clientWidth || 320;
  if (!yieldsState._didLayoutSettle) {
    yieldsState._didLayoutSettle = true;
    setTimeout(() => {
      const trueW = document.getElementById('yields-map')?.clientWidth || 0;
      if (trueW > measuredW + 8) yieldsRenderMap();
    }, 50);
  }
  wrap.innerHTML = '';
  const w = measuredW;
  const h = 520;
  if (!yieldsState._resizeObs && typeof ResizeObserver !== 'undefined') {
    let lastW = w;
    yieldsState._resizeObs = new ResizeObserver(entries => {
      const cw = entries[0].contentRect.width;
      if (Math.abs(cw - lastW) < 4) return;
      lastW = cw;
      if (yieldsState.countries && yieldsState.worldGeo) yieldsRenderMap();
    });
    yieldsState._resizeObs.observe(wrap);
  }
  const svg = d3.select(wrap)
    .append('svg')
    .attr('viewBox', `0 0 ${w} ${h}`)
    .attr('preserveAspectRatio', 'xMidYMid meet');

  const projection = d3.geoNaturalEarth1()
    .fitSize([w, h - 20], topojson.feature(yieldsState.worldGeo, yieldsState.worldGeo.objects.countries));
  const path = d3.geoPath(projection);

  const features = topojson.feature(yieldsState.worldGeo, yieldsState.worldGeo.objects.countries).features;

  svg.selectAll('path.yields-country')
    .data(features)
    .join('path')
    .attr('class', d => {
      const c = yieldsState.byIso[d.id];
      return c ? 'yields-country supported' : 'yields-country';
    })
    .attr('d', path)
    .style('fill', d => yieldsCountryFill(d))
    .on('mouseenter', (evt, d) => yieldsOnHover(evt, d, true))
    .on('mousemove',  (evt, d) => yieldsOnHover(evt, d, false))
    .on('mouseleave', () => yieldsHideTooltip())
    .on('click', (evt, d) => {
      const c = yieldsState.byIso[d.id];
      if (c) yieldsSelectCountry(c.code);
    });

  yieldsRenderLegend();
  yieldsRefreshSelectionMarks();
}

function yieldsCountryFill(feature) {
  const c = yieldsState.byIso[feature.id];
  if (!c) return '#0d1117';                       // unsupported
  if (yieldsState.mode === 'picker') return '#1e2530';
  if (yieldsState.mode === 'heatmap-10y') {
    const v = c.yield_10y;
    if (v == null) return '#1e2530';
    return yieldsHeatmapColor(v, yieldsState._range10y);
  }
  if (yieldsState.mode === 'heatmap-slope') {
    const s = c.slope_2_10;          // bps
    if (s == null) return '#1e2530';
    if (s < -10) return YIELDS_INVERTED_COL;
    return yieldsHeatmapColor(s, yieldsState._rangeSlope);
  }
  return '#1e2530';
}

function yieldsHeatmapColor(v, range) {
  if (!range) return '#1e2530';
  const t = Math.max(0, Math.min(1, (v - range[0]) / (range[1] - range[0] || 1)));
  // Interpolate between LO and HI colors via d3
  return d3.interpolateRgb(YIELDS_HEATMAP_LO, YIELDS_HEATMAP_HI)(t);
}

function yieldsRenderLegend() {
  const legend = document.getElementById('yields-map-legend');
  if (!legend) return;
  if (yieldsState.mode === 'picker') {
    legend.style.display = 'none';
    return;
  }
  legend.style.display = 'block';
  const isSlope = yieldsState.mode === 'heatmap-slope';
  // Compute range
  const vals = Object.values(yieldsState.countries)
    .map(c => isSlope ? c.slope_2_10 : c.yield_10y)
    .filter(v => v != null);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  if (isSlope) yieldsState._rangeSlope = [Math.max(lo, -100), hi];
  else         yieldsState._range10y   = [lo, hi];
  document.getElementById('yields-legend-title').textContent = isSlope
    ? '2-10 Slope (bps) · red = inverted'
    : '10Y Yield (%)';
  // Build gradient bar with 10 stops
  const bar = document.getElementById('yields-legend-bar');
  bar.innerHTML = '';
  for (let i = 0; i < 10; i++) {
    const t = i / 9;
    const v = lo + t * (hi - lo);
    const div = document.createElement('div');
    div.style.background = (isSlope && v < -10) ? YIELDS_INVERTED_COL : d3.interpolateRgb(YIELDS_HEATMAP_LO, YIELDS_HEATMAP_HI)(t);
    bar.appendChild(div);
  }
  document.getElementById('yields-legend-min').textContent = isSlope ? `${lo.toFixed(0)} bps` : `${lo.toFixed(2)}%`;
  document.getElementById('yields-legend-max').textContent = isSlope ? `${hi.toFixed(0)} bps` : `${hi.toFixed(2)}%`;
}

function yieldsRefreshFills() {
  d3.select('#yields-map svg').selectAll('path.yields-country')
    .style('fill', d => yieldsCountryFill(d));
}

function yieldsRefreshSelectionMarks() {
  d3.select('#yields-map svg').selectAll('path.yields-country')
    .classed('selected', d => {
      const c = yieldsState.byIso[d.id];
      return c && c.code === yieldsState.selected;
    })
    .classed('compared', d => {
      const c = yieldsState.byIso[d.id];
      return c && yieldsState.compare.includes(c.code);
    });
}

function yieldsOnHover(evt, feature, fadeIn) {
  const c = yieldsState.byIso[feature.id];
  if (!c) { yieldsHideTooltip(); return; }
  const tt = document.getElementById('yields-tooltip');
  if (!tt) return;
  const slope = c.slope_2_10;
  const slopeLabel = slope == null ? '—'
    : slope < -10 ? `Inverted (${slope.toFixed(0)} bps)`
    : slope < 30  ? `Flat (${slope.toFixed(0)} bps)`
    : slope < 150 ? `Normal (${slope.toFixed(0)} bps)`
    : `Steep (${slope.toFixed(0)} bps)`;
  const sourceLabel = c.source === 'fred-live' ? 'Live · yfinance'
    : c.source === 'fred-rescaled' ? 'FRED 10Y · rescaled snapshot'
    : 'Snapshot · no live feed available';
  tt.innerHTML = '';
  const name = document.createElement('div'); name.className = 'tt-name'; name.textContent = c.name; tt.appendChild(name);
  const r1 = document.createElement('div'); r1.className = 'tt-row';
  r1.innerHTML = `<span class="tt-label">10Y</span><span class="tt-val">${c.yield_10y == null ? '—' : c.yield_10y.toFixed(2) + '%'}</span>`;
  tt.appendChild(r1);
  const r2 = document.createElement('div'); r2.className = 'tt-row';
  r2.innerHTML = `<span class="tt-label">2-10</span><span class="tt-val">${slopeLabel}</span>`;
  tt.appendChild(r2);
  const src = document.createElement('div'); src.className = 'tt-source'; src.textContent = sourceLabel; tt.appendChild(src);
  // Position relative to map wrap
  const wrap = document.getElementById('yields-map-wrap').getBoundingClientRect();
  tt.style.display = 'block';
  tt.style.left = (evt.clientX - wrap.left + 14) + 'px';
  tt.style.top  = (evt.clientY - wrap.top  + 14) + 'px';
}

function yieldsHideTooltip() {
  const tt = document.getElementById('yields-tooltip');
  if (tt) tt.style.display = 'none';
}

async function yieldsSelectCountry(code) {
  yieldsState.selected = code;
  localStorage.setItem('yields_last', code);
  yieldsRefreshSelectionMarks();
  await yieldsRenderDetail();
}

async function yieldsLoadDetail(code) {
  if (yieldsState.detailCache[code]) return yieldsState.detailCache[code];
  const res = await apiFetch(`/api/yields/${code}`);
  const data = await res.json();
  yieldsState.detailCache[code] = data;
  return data;
}

async function yieldsRenderDetail() {
  const panel = document.getElementById('yields-detail');
  if (!panel) return;
  if (!yieldsState.selected) {
    panel.classList.add('empty');
    panel.textContent = 'Select a country on the map to view its yield curve.';
    return;
  }
  panel.classList.remove('empty');
  panel.textContent = '';

  const allCodes = [yieldsState.selected, ...yieldsState.compare.filter(c => c !== yieldsState.selected)];
  let primary;
  let allDetails;
  try {
    allDetails = await Promise.all(allCodes.map(c => yieldsLoadDetail(c)));
    primary = allDetails[0];
  } catch (e) {
    panel.textContent = 'Failed to load curve.';
    return;
  }

  // Header
  const header = document.createElement('div');
  const name = document.createElement('div');
  name.className = 'yields-detail-name';
  name.textContent = primary.name;
  const sub = document.createElement('div');
  sub.className = 'yields-detail-sub';
  sub.textContent = `Snapshot ${primary.as_of} · last fetch ${new Date(primary.last_update).toLocaleTimeString()}`;
  const srcBadge = document.createElement('span');
  srcBadge.className = 'yields-detail-source ' + primary.source;
  const SOURCE_LABELS = {
    'fred-live':     'LIVE · YFINANCE',
    'fred-rescaled': 'FRED RESCALED',
    'snapshot':      'SNAPSHOT',
  };
  srcBadge.textContent = SOURCE_LABELS[primary.source] || primary.source;
  srcBadge.style.marginLeft = '10px';
  name.appendChild(srcBadge);
  header.appendChild(name);
  header.appendChild(sub);
  // For non-US (snapshot), explain why deltas are not live
  if (primary.source === 'snapshot' && primary.code !== 'US') {
    const note = document.createElement('div');
    note.className = 'yields-detail-sub';
    note.style.color = 'var(--label)';
    note.style.marginTop = '4px';
    note.textContent = 'Live yield feeds for foreign sovereigns require a paid data subscription. Δ1d / Δ1w populate as the daemon accumulates daily snapshots over time.';
    header.appendChild(note);
  }
  panel.appendChild(header);

  // Curve chart
  const curveWrap = document.createElement('div');
  curveWrap.id = 'yields-curve-wrap';
  const canvas = document.createElement('canvas');
  canvas.id = 'yields-curve-chart';
  curveWrap.appendChild(canvas);
  panel.appendChild(curveWrap);

  // Spreads
  const spreads = document.createElement('div');
  spreads.id = 'yields-spreads';
  const spreadCards = [
    { lbl: '2-10 Spread',  val: primary.spread_2_10,       suffix: '%', signed: true },
    { lbl: '3M-10Y',       val: primary.spread_3m_10y,     suffix: '%', signed: true },
    { lbl: 'Curve Shape',  val: primary.classification,    text: true },
    { lbl: 'vs UST 10Y',   val: primary.spread_vs_ust_10y, suffix: '%', signed: true, hideIfNull: true },
  ];
  for (const card of spreadCards) {
    if (card.hideIfNull && card.val == null) continue;
    const div = document.createElement('div');
    div.className = 'spread-card';
    const lbl = document.createElement('div'); lbl.className = 'lbl'; lbl.textContent = card.lbl;
    const val = document.createElement('div'); val.className = 'val';
    if (card.text) {
      val.textContent = card.val || '—';
      if (card.val === 'Inverted') val.classList.add('red');
      else if (card.val === 'Steep') val.classList.add('green');
      else if (card.val === 'Flat')  val.classList.add('yellow');
    } else {
      if (card.val == null) {
        val.textContent = '—';
      } else {
        const sign = card.val >= 0 ? '+' : '';
        val.textContent = sign + card.val.toFixed(2) + (card.suffix || '');
        if (card.signed) val.classList.add(card.val >= 0 ? 'green' : 'red');
      }
    }
    div.appendChild(lbl); div.appendChild(val);
    spreads.appendChild(div);
  }
  panel.appendChild(spreads);

  // Tenor table (primary country only)
  const table = document.createElement('table');
  table.className = 'yields-table';
  const thead = document.createElement('thead');
  thead.innerHTML = '<tr><th>Tenor</th><th>Yield</th><th>Δ 1d</th><th>Δ 1w</th></tr>';
  table.appendChild(thead);
  const tbody = document.createElement('tbody');
  for (let i = 0; i < primary.tenors.length; i++) {
    const tr = document.createElement('tr');
    const tdT = document.createElement('td'); tdT.textContent = primary.tenors[i];
    const tdY = document.createElement('td'); tdY.textContent = primary.yields[i].toFixed(2) + '%';
    const tdD1 = document.createElement('td');
    const tdD7 = document.createElement('td');
    const d1 = primary.changes_1d_bps?.[i];
    const d7 = primary.changes_1w_bps?.[i];
    yieldsFormatBps(tdD1, d1);
    yieldsFormatBps(tdD7, d7);
    tr.appendChild(tdT); tr.appendChild(tdY); tr.appendChild(tdD1); tr.appendChild(tdD7);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  panel.appendChild(table);

  yieldsDrawCurveChart(allDetails);
}

function yieldsFormatBps(td, v) {
  if (v == null) {
    td.textContent = '—';
    td.className = 'bps-null';
    return;
  }
  const sign = v >= 0 ? '+' : '';
  td.textContent = sign + v.toFixed(1) + ' bps';
  td.className = v > 0 ? 'bps-pos' : v < 0 ? 'bps-neg' : '';
}

function yieldsDrawCurveChart(details) {
  const canvas = document.getElementById('yields-curve-chart');
  if (!canvas) return;
  if (yieldsState.curveChart) { yieldsState.curveChart.destroy(); yieldsState.curveChart = null; }
  const ctx = canvas.getContext('2d');
  const labels = details[0].tenors;
  const datasets = details.map((d, i) => ({
    label: d.code + ' ' + d.name,
    data: d.yields,
    borderColor: YIELDS_PALETTE[i % YIELDS_PALETTE.length],
    backgroundColor: YIELDS_PALETTE[i % YIELDS_PALETTE.length] + '22',
    tension: 0.25,
    pointRadius: 3,
    borderWidth: 2,
  }));
  yieldsState.curveChart = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: details.length > 1, position: 'top', labels: { color: '#e6edf3', font: { family: 'JetBrains Mono', size: 10 }, boxWidth: 10 } },
        tooltip: { backgroundColor: '#1a1a1a', titleColor: '#e6edf3', bodyColor: '#e6edf3', borderColor: '#2a2a2a', borderWidth: 1 },
      },
      scales: {
        x: { ticks: { color: '#7d8590', font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: '#1a1a1a' } },
        y: { ticks: { color: '#7d8590', font: { family: 'JetBrains Mono', size: 10 }, callback: v => v.toFixed(1) + '%' }, grid: { color: '#1a1a1a' } },
      },
    },
  });
}

function yieldsBindToolbar() {
  document.querySelectorAll('.yields-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.yields-mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      yieldsState.mode = btn.dataset.mode;
      yieldsRenderLegend();
      yieldsRefreshFills();
    });
  });
  const cmpBtn = document.getElementById('yields-compare-add');
  if (cmpBtn) cmpBtn.addEventListener('click', yieldsOpenCompareModal);
}

function yieldsBindCompareModal() {
  const list = document.getElementById('yields-cmp-list');
  if (!list) return;
  list.innerHTML = '';
  const sorted = Object.values(yieldsState.countries).sort((a, b) => a.name.localeCompare(b.name));
  for (const c of sorted) {
    const div = document.createElement('div');
    div.className = 'yields-cmp-item';
    div.dataset.code = c.code;
    const left = document.createElement('span'); left.textContent = c.name; div.appendChild(left);
    const y10 = document.createElement('span'); y10.className = 'y10';
    y10.textContent = c.yield_10y == null ? '—' : c.yield_10y.toFixed(2) + '%';
    div.appendChild(y10);
    div.addEventListener('click', () => yieldsToggleCompare(c.code));
    list.appendChild(div);
  }
}

function yieldsToggleCompare(code) {
  if (code === yieldsState.selected) return;       // primary cannot be a compare overlay
  const idx = yieldsState.compare.indexOf(code);
  if (idx >= 0) {
    yieldsState.compare.splice(idx, 1);
  } else {
    if (yieldsState.compare.length >= YIELDS_COMPARE_MAX) {
      yieldsState.compare.shift();                 // FIFO when at capacity
    }
    yieldsState.compare.push(code);
  }
  yieldsRefreshCompareList();
  yieldsRefreshSelectionMarks();
  yieldsRenderDetail();
}

function yieldsRefreshCompareList() {
  document.querySelectorAll('.yields-cmp-item').forEach(el => {
    el.classList.toggle('active', yieldsState.compare.includes(el.dataset.code));
  });
}

function yieldsOpenCompareModal() {
  yieldsRefreshCompareList();
  document.getElementById('yields-compare-modal').classList.add('visible');
}

function yieldsCloseCompareModal() {
  document.getElementById('yields-compare-modal').classList.remove('visible');
}

