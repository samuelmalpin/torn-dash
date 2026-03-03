const api = {
  me: "/api/auth/me",
  logout: "/api/auth/logout",
  health: "/api/health",
  overview: "/api/overview",
  market: "/api/market",
  timeseries: "/api/timeseries",
  insights: "/api/insights",
  opportunities: "/api/opportunities",
  marketSeries: "/api/market/series",
  backtest: "/api/strategy/backtest",
  warRoom: "/api/faction/war-room",
};

const $ = (id) => document.getElementById(id);
let currentUser = null;
let trackedItems = [];

function formatMoney(value) {
  return Number(value || 0).toLocaleString("fr-FR") + " $";
}

function formatDate(value) {
  if (!value) return "--";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("fr-FR");
}

function setList(elementId, entries, formatter) {
  const host = $(elementId);
  host.innerHTML = "";
  if (!entries || entries.length === 0) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Aucune donnée";
    host.appendChild(li);
    return;
  }

  entries.forEach((entry) => {
    const li = document.createElement("li");
    li.textContent = formatter(entry);
    host.appendChild(li);
  });
}

function lineGeometry(values, width, height, padding = 6) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values);
  const min = Math.min(...values);
  const span = Math.max(1, max - min);
  const points = values.map((value, index) => {
    const x = padding + (index * (width - padding * 2)) / (values.length - 1);
    const y = height - padding - ((value - min) * (height - padding * 2)) / span;
    return { x, y };
  });
  return { points, min, max };
}

function renderSparkline(svgId, values, usePurple = false) {
  const svg = $(svgId);
  svg.innerHTML = "";
  const width = Number(svg.viewBox.baseVal.width || 320);
  const height = Number(svg.viewBox.baseVal.height || 90);
  const geometry = lineGeometry(values, width, height);
  if (!geometry) return;

  const area = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  const polyPoints = geometry.points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ");
  area.setAttribute("points", `6,${height - 6} ${polyPoints} ${width - 6},${height - 6}`);
  area.setAttribute("class", "sparkline-area");
  svg.appendChild(area);

  const line = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
  line.setAttribute("points", polyPoints);
  line.setAttribute("class", usePurple ? "sparkline-line purple" : "sparkline-line");
  svg.appendChild(line);
}

function renderInsights(items) {
  const host = $("insights-grid");
  host.innerHTML = "";

  if (!items || items.length === 0) {
    const div = document.createElement("div");
    div.className = "insight-card empty";
    div.textContent = "Aucun insight marché pour le moment.";
    host.appendChild(div);
    return;
  }

  items.slice(0, 6).forEach((item) => {
    const div = document.createElement("div");
    div.className = "insight-card";
    const deltaClass = item.delta_percent <= 0 ? "delta-good" : "delta-bad";
    const deltaLabel = `${item.delta_percent > 0 ? "+" : ""}${item.delta_percent.toFixed(2)}%`;

    div.innerHTML = `
      <div class="insight-item">${item.item_name} (#${item.item_id})</div>
      <div class="insight-price">${formatMoney(item.latest_price)} vs moy ${formatMoney(item.average_price)}</div>
      <div class="${deltaClass}">Écart: ${deltaLabel}</div>
    `;
    host.appendChild(div);
  });
}

function movingAverage(values, window = 6) {
  return values.map((_, index) => {
    const start = Math.max(0, index - window + 1);
    const chunk = values.slice(start, index + 1);
    return chunk.reduce((acc, value) => acc + value, 0) / chunk.length;
  });
}

function renderCandlesAndMA(series) {
  const svg = $("chart-candles");
  svg.innerHTML = "";
  const width = Number(svg.viewBox.baseVal.width || 640);
  const height = Number(svg.viewBox.baseVal.height || 180);

  if (!series || series.length < 2) return;

  const prices = series.map((row) => Number(row.lowest_price || 0));
  const grouped = [];
  const bucketSize = Math.max(2, Math.floor(prices.length / 24));
  for (let i = 0; i < prices.length; i += bucketSize) {
    const chunk = prices.slice(i, i + bucketSize);
    if (!chunk.length) continue;
    grouped.push({
      open: chunk[0],
      close: chunk[chunk.length - 1],
      high: Math.max(...chunk),
      low: Math.min(...chunk),
    });
  }

  if (!grouped.length) return;

  const highs = grouped.map((g) => g.high);
  const lows = grouped.map((g) => g.low);
  const max = Math.max(...highs);
  const min = Math.min(...lows);
  const span = Math.max(1, max - min);
  const toY = (value) => height - 10 - ((value - min) * (height - 20)) / span;

  const candleWidth = Math.max(4, (width - 12) / grouped.length - 2);
  grouped.forEach((candle, idx) => {
    const x = 6 + idx * (candleWidth + 2);
    const wick = document.createElementNS("http://www.w3.org/2000/svg", "line");
    wick.setAttribute("x1", `${x + candleWidth / 2}`);
    wick.setAttribute("x2", `${x + candleWidth / 2}`);
    wick.setAttribute("y1", `${toY(candle.high)}`);
    wick.setAttribute("y2", `${toY(candle.low)}`);
    wick.setAttribute("class", "candle-wick");
    svg.appendChild(wick);

    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    const bodyTop = Math.min(toY(candle.open), toY(candle.close));
    const bodyHeight = Math.max(2, Math.abs(toY(candle.open) - toY(candle.close)));
    rect.setAttribute("x", `${x}`);
    rect.setAttribute("y", `${bodyTop}`);
    rect.setAttribute("width", `${candleWidth}`);
    rect.setAttribute("height", `${bodyHeight}`);
    rect.setAttribute("class", "candle-body");
    svg.appendChild(rect);
  });

  const ma = movingAverage(grouped.map((g) => g.close), 5);
  const maGeometry = lineGeometry(ma, width, height, 8);
  if (maGeometry) {
    const maLine = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    maLine.setAttribute(
      "points",
      maGeometry.points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ")
    );
    maLine.setAttribute("class", "ma-line");
    svg.appendChild(maLine);
  }
}

function renderVolatility(series) {
  const svg = $("chart-volatility");
  svg.innerHTML = "";
  if (!series || series.length < 3) return;

  const prices = series.map((row) => Number(row.lowest_price || 0));
  const volatility = prices.slice(1).map((value, index) => {
    const prev = prices[index] || 1;
    return Math.abs(((value - prev) / prev) * 100);
  });
  renderSparkline("chart-volatility", volatility, true);
}

function renderHeatmap(series) {
  const host = $("heatmap");
  host.innerHTML = "";
  if (!series || !series.length) return;

  const prices = series.map((row) => Number(row.lowest_price || 0));
  const max = Math.max(...prices);
  const min = Math.min(...prices);
  const span = Math.max(1, max - min);

  prices.slice(-96).forEach((price) => {
    const level = (price - min) / span;
    const hue = 210 - Math.round(level * 140);
    const alpha = 0.25 + level * 0.65;
    const cell = document.createElement("div");
    cell.className = "heat-cell";
    cell.style.background = `hsla(${hue}, 92%, 62%, ${alpha.toFixed(2)})`;
    host.appendChild(cell);
  });
}

function fillMarketSelector(items) {
  const select = $("market-item-select");
  select.innerHTML = "";
  items.forEach((itemId) => {
    const option = document.createElement("option");
    option.value = String(itemId);
    option.textContent = `Item #${itemId}`;
    select.appendChild(option);
  });
}

function renderWarRoom(snapshot) {
  const host = $("war-room-box");
  if (!snapshot) {
    host.classList.add("empty");
    host.textContent = "Aucune donnée faction (configure FACTION_ID).";
    return;
  }

  host.classList.remove("empty");
  const critical = (snapshot.critical_members || [])
    .slice(0, 5)
    .map((member) => `${member.name}: ${member.status}`)
    .join(" • ");

  host.innerHTML = `
    <div><strong>${snapshot.name}</strong> • ${snapshot.members_online}/${snapshot.members_total} online</div>
    <div>Respect: ${snapshot.respect.toLocaleString("fr-FR")} • Chain: ${snapshot.chain_current} (timeout ${snapshot.chain_timeout}s)</div>
    <div>Priorités: ${critical || "Aucune critique"}</div>
    <div>Maj: ${formatDate(snapshot.timestamp)}</div>
  `;
}

function applySavedLayout() {
  const dashboard = $("dashboard-widgets");
  const saved = localStorage.getItem("torn_nexus_layout");
  if (!saved) return;

  try {
    const ordered = JSON.parse(saved);
    ordered.forEach((widgetId) => {
      const widget = dashboard.querySelector(`[data-widget="${widgetId}"]`);
      if (widget) dashboard.appendChild(widget);
    });
  } catch {
    localStorage.removeItem("torn_nexus_layout");
  }
}

function saveLayout() {
  const dashboard = $("dashboard-widgets");
  const layout = Array.from(dashboard.querySelectorAll(".widget")).map((node) => node.dataset.widget);
  localStorage.setItem("torn_nexus_layout", JSON.stringify(layout));
}

function initDragAndDrop() {
  const dashboard = $("dashboard-widgets");
  let dragged = null;

  dashboard.querySelectorAll(".widget").forEach((widget) => {
    const handle = widget.querySelector(".drag-handle");
    widget.setAttribute("draggable", "true");

    handle.addEventListener("mousedown", () => {
      widget.setAttribute("draggable", "true");
    });

    widget.addEventListener("dragstart", () => {
      dragged = widget;
      widget.classList.add("dragging");
    });

    widget.addEventListener("dragend", () => {
      widget.classList.remove("dragging");
      dragged = null;
      saveLayout();
    });

    widget.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (!dragged || dragged === widget) return;
      const rect = widget.getBoundingClientRect();
      const before = event.clientY < rect.top + rect.height / 2;
      if (before) {
        dashboard.insertBefore(dragged, widget);
      } else {
        dashboard.insertBefore(dragged, widget.nextSibling);
      }
    });
  });
}

async function apiFetch(url, options = {}) {
  const response = await fetch(url, options);
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

async function loadAuthContext() {
  const me = await apiFetch(api.me);
  currentUser = me;
  $("user-pill").textContent = `${me.username} • ${me.role}`;
  if (me.role !== "admin") {
    $("run-backtest-btn").style.display = "none";
  }
}

async function loadHealth() {
  const health = await apiFetch(api.health);
  trackedItems = health.tracked_items || [];
  $("health-pill").textContent = health.torn_configured
    ? `Online • ${trackedItems.length} items trackés`
    : "API key manquante";
  if (trackedItems.length) {
    fillMarketSelector(trackedItems);
  }
  return health;
}

async function loadOverview() {
  const data = await apiFetch(api.overview);
  const snapshot = data.snapshot;
  if (snapshot) {
    $("level").textContent = snapshot.level;
    $("money").textContent = formatMoney(snapshot.money);
    $("points").textContent = snapshot.points;
    $("energy").textContent = `${snapshot.energy_current}/${snapshot.energy_max}`;
    $("nerve").textContent = `${snapshot.nerve_current}/${snapshot.nerve_max}`;
    $("timestamp").textContent = formatDate(snapshot.timestamp);
  }

  setList("alerts-list", data.alerts, (alert) => `[${formatDate(alert.timestamp)}] (${alert.kind}) ${alert.message}`);
  setList("events-list", data.events, (event) => `[${formatDate(event.timestamp)}] ${event.text}`);
}

async function loadMarketTable() {
  const data = await apiFetch(api.market);
  const body = $("market-body");
  body.innerHTML = "";

  const rows = (data.history || []).slice(0, 20);
  if (!rows.length) {
    const tr = document.createElement("tr");
    tr.innerHTML = '<td colspan="3" class="empty">Aucune donnée marché</td>';
    body.appendChild(tr);
    return;
  }

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${formatDate(row.timestamp)}</td><td>${row.item_name} (#${row.item_id})</td><td>${formatMoney(row.lowest_price)}</td>`;
    body.appendChild(tr);
  });
}

async function loadTimeseries(historyPoints) {
  const data = await apiFetch(`${api.timeseries}?points=${historyPoints}`);
  const points = data.points || [];
  renderSparkline("chart-money", points.map((p) => Number(p.money || 0)));
  renderSparkline("chart-energy", points.map((p) => Number(p.energy_current || 0)), true);
  renderSparkline("chart-points", points.map((p) => Number(p.points || 0)));
}

async function loadInsights() {
  const data = await apiFetch(api.insights);
  renderInsights(data.market || []);
}

async function loadOpportunities() {
  const data = await apiFetch(api.opportunities);
  const summary = data.summary || { buy: 0, watch: 0, skip: 0 };
  $("opportunities-summary").textContent = `BUY: ${summary.buy} • WATCH: ${summary.watch} • SKIP: ${summary.skip}`;

  const items = data.items || [];
  setList(
    "opportunities-list",
    items,
    (item) =>
      `[${item.action}] ${item.item_name} (#${item.item_id}) • conf ${item.confidence}% • ` +
      `Δ ${item.drop_percent}%/${item.threshold_percent}% • ` +
      `potentiel ${formatMoney(item.expected_return)} (${item.expected_return_percent}%)`
  );
}

async function loadWarRoom() {
  const data = await apiFetch(api.warRoom);
  renderWarRoom(data.snapshot);
}

async function loadAdvancedMarketChart() {
  const select = $("market-item-select");
  if (!select.value) return;
  const itemId = Number(select.value);
  const data = await apiFetch(`${api.marketSeries}?item_id=${itemId}&limit=240`);
  const series = data.series || [];
  renderCandlesAndMA(series);
  renderVolatility(series);
  renderHeatmap(series);
}

async function runBacktest() {
  const select = $("market-item-select");
  const itemId = Number(select.value);
  if (!itemId || !currentUser || currentUser.role !== "admin") return;

  const box = $("backtest-box");
  box.classList.remove("empty");
  box.textContent = "Exécution backtest...";
  try {
    const data = await apiFetch(`${api.backtest}?item_id=${itemId}`);
    const report = data.report;
    const signal = data.latest_signal;
    box.innerHTML = `
      <div>Item #${itemId} • Signaux: ${report.signals} • Win rate: ${report.win_rate}%</div>
      <div>Avg return: ${report.avg_return_percent}% • Wins/Losses: ${report.wins}/${report.losses}</div>
      <div>Signal actuel: ${signal.has_signal ? "BUY" : "NO-SIGNAL"} (drop ${signal.drop_percent || 0}% / seuil ${signal.dynamic_threshold || 0}%)</div>
    `;
  } catch (error) {
    box.classList.add("empty");
    box.textContent = `Backtest indisponible (${error.message})`;
  }
}

async function refresh() {
  try {
    const health = await loadHealth();
    await Promise.all([
      loadOverview(),
      loadMarketTable(),
      loadTimeseries(health.history_points || 48),
      loadInsights(),
      loadOpportunities(),
      loadWarRoom(),
      loadAdvancedMarketChart(),
    ]);
  } catch (error) {
    $("health-pill").textContent = "Erreur API";
    console.error(error);
  }
}

async function logout() {
  await fetch(api.logout, { method: "POST" });
  window.location.href = "/login";
}

function wireEvents() {
  $("logout-btn").addEventListener("click", logout);
  $("market-item-select").addEventListener("change", loadAdvancedMarketChart);
  $("run-backtest-btn").addEventListener("click", runBacktest);
}

async function bootstrap() {
  applySavedLayout();
  initDragAndDrop();
  wireEvents();
  await loadAuthContext();
  await refresh();
  setInterval(refresh, 30000);
}

bootstrap();
