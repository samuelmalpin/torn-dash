const api = {
  me: "/api/auth/me",
  logout: "/api/auth/logout",
  health: "/api/health",
  overview: "/api/overview",
  timeseries: "/api/timeseries",
  warRoom: "/api/faction/war-room",
};

const $ = (id) => document.getElementById(id);

function formatMoney(value) {
  return Number(value || 0).toLocaleString("fr-FR") + " $";
}

function formatDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("fr-FR");
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

  return { points };
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
  $("user-pill").textContent = `${me.username} • ${me.role}`;
}

async function loadHealth() {
  const health = await apiFetch(api.health);
  $("health-pill").textContent = health.torn_configured ? "Online" : "API key manquante";
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

async function loadTimeseries(historyPoints) {
  const data = await apiFetch(`${api.timeseries}?points=${historyPoints}`);
  const points = data.points || [];
  renderSparkline("chart-money", points.map((p) => Number(p.money || 0)));
  renderSparkline("chart-energy", points.map((p) => Number(p.energy_current || 0)), true);
  renderSparkline("chart-points", points.map((p) => Number(p.points || 0)));
}

async function loadWarRoom() {
  const data = await apiFetch(api.warRoom);
  renderWarRoom(data.snapshot);
}

async function refresh() {
  try {
    const health = await loadHealth();
    await Promise.all([loadOverview(), loadTimeseries(health.history_points || 48), loadWarRoom()]);
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
