const PATHS = {
  state: "../data/simulation_results/current_state.json",
  leaderboard: "../data/simulation_results/leaderboard.json",
  lineups: "../data/simulation_results/lineups_history.json",
  marketDays: "../data/simulation_results/market_days.json",
  decisions: "../data/simulation_results/llm_decisions.json",
  players: "../data/players_dataset.json",
};

const COLORS = ["#177e72", "#d8672a", "#315fbd", "#8d4ab8", "#b58516", "#b83232"];

const state = {
  data: {},
  manager: null,
  round: null,
  marketDay: null,
  playerId: null,
  squadMode: "squad",
  decisionRound: null,
};

const el = {};

document.addEventListener("DOMContentLoaded", async () => {
  cacheElements();
  bindEvents();
  try {
    await loadData();
    initialiseState();
    render();
  } catch (error) {
    renderBootError(error);
  }
});

function cacheElements() {
  [
    "managerSelect",
    "roundSelect",
    "marketDaySelect",
    "playerSelect",
    "metricsGrid",
    "strategyCards",
    "squadTimeline",
    "marketBoard",
    "decisionFeed",
    "decisionRoundSelect",
    "decisionRoundLabel",
    "playerSummary",
    "pointsChart",
    "playerChart",
  ].forEach((id) => {
    el[id] = document.getElementById(id);
  });
}

function bindEvents() {
  el.managerSelect.addEventListener("change", () => {
    state.manager = el.managerSelect.value;
    syncDecisionRound();
    render();
  });
  el.roundSelect.addEventListener("change", () => {
    state.round = Number(el.roundSelect.value);
    syncMarketDays();
    render();
  });
  el.marketDaySelect.addEventListener("change", () => {
    state.marketDay = Number(el.marketDaySelect.value);
    renderMetrics();
    renderMarket();
    renderDecisions();
  });
  el.decisionRoundSelect.addEventListener("change", () => {
    state.decisionRound = Number(el.decisionRoundSelect.value);
    renderDecisions();
  });
  el.playerSelect.addEventListener("change", () => {
    state.playerId = Number(el.playerSelect.value);
    renderPlayer();
  });
  document.querySelectorAll("[data-squad-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.squadMode = button.dataset.squadMode;
      document.querySelectorAll("[data-squad-mode]").forEach((item) => {
        item.classList.toggle("active", item === button);
      });
      renderSquads();
    });
  });
}

async function loadData() {
  if (window.DEMO_DATA) {
    state.data = window.DEMO_DATA;
    state.data.playerById = new Map(state.data.players.map((player) => [Number(player.id), player]));
    return;
  }

  const entries = await Promise.all(
    Object.entries(PATHS).map(async ([key, path]) => {
      const response = await fetch(path);
      if (!response.ok) {
        throw new Error(`No se pudo cargar ${path}`);
      }
      return [key, await response.json()];
    }),
  );
  state.data = Object.fromEntries(entries);
  state.data.playerById = new Map(state.data.players.map((player) => [Number(player.id), player]));
}

function initialiseState() {
  const managers = state.data.leaderboard.map((item) => item.name);
  const rounds = getRounds();
  state.manager = managers[0];
  state.round = rounds[rounds.length - 1];
  state.decisionRound = state.round;
  syncMarketDays();
  populateManagerSelect(managers);
  populateRoundSelect(rounds);
  populateDecisionRoundSelect(rounds);
  populatePlayerSelect();
}

function populateManagerSelect(managers) {
  el.managerSelect.innerHTML = managers
    .map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`)
    .join("");
  el.managerSelect.value = state.manager;
}

function populateRoundSelect(rounds) {
  el.roundSelect.innerHTML = rounds
    .map((round) => `<option value="${round}">Jornada ${round}</option>`)
    .join("");
  el.roundSelect.value = String(state.round);
}

function populateDecisionRoundSelect(rounds) {
  el.decisionRoundSelect.innerHTML = rounds
    .map((round) => `<option value="${round}">Jornada ${round}</option>`)
    .join("");
  el.decisionRoundSelect.value = String(state.decisionRound || state.round);
}

function populatePlayerSelect() {
  const interestingIds = new Set();
  state.data.marketDays.forEach((day) => {
    day.sales.forEach((sale) => interestingIds.add(Number(sale.player_id)));
  });
  getLineupManager(state.manager)?.lineup_history?.forEach((entry) => {
    [...(entry.squad || []), ...(entry.lineup || [])].forEach((player) => interestingIds.add(Number(player.player_id)));
  });

  const players = [...interestingIds]
    .map((id) => state.data.playerById.get(id))
    .filter(Boolean)
    .sort((a, b) => (b.marketValue || 0) - (a.marketValue || 0))
    .slice(0, 80);

  state.playerId = state.playerId || Number(players[0]?.id);
  el.playerSelect.innerHTML = players
    .map((player) => `<option value="${player.id}">${escapeHtml(fixText(player.name))}</option>`)
    .join("");
  el.playerSelect.value = String(state.playerId);
}

function syncMarketDays() {
  const days = state.data.marketDays
    .filter((day) => Number(day.round) === Number(state.round))
    .map((day) => Number(day.market_day));
  state.marketDay = days.includes(state.marketDay) ? state.marketDay : days[0] || 1;
  if (el.marketDaySelect) {
    el.marketDaySelect.innerHTML = days
      .map((day) => `<option value="${day}">Dia ${day}</option>`)
      .join("");
    el.marketDaySelect.value = String(state.marketDay);
  }
}

function render() {
  el.managerSelect.value = state.manager;
  el.roundSelect.value = String(state.round);
  el.marketDaySelect.value = String(state.marketDay);
  syncDecisionRound();
  el.decisionRoundSelect.value = String(state.decisionRound);
  renderMetrics();
  renderStrategies();
  renderPoints();
  renderSquads();
  renderMarket();
  renderPlayer();
  renderDecisions();
}

function renderMetrics() {
  const row = state.data.leaderboard.find((item) => item.name === state.manager);
  const market = getMarketSlice();
  const sold = market.sales.filter((sale) => sale.status === "sold").length;
  const managerDecisions = getDecisionItems(state.manager);
  const metrics = [
    ["Puntos totales", formatNumber(row?.points_total || 0)],
    ["Caja", formatMoney(row?.cash || 0)],
    ["Valor plantilla", formatMoney(row?.squad_value || 0)],
    ["Compras dia", `${sold}/${market.sales.length}`],
    ["Traspasos", formatNumber(row?.transfers_made || 0)],
    ["Formacion actual", row?.formation || "-"],
    ["Decisiones LLM", formatNumber(managerDecisions.length)],
    ["Jornada activa", String(state.round)],
  ];
  el.metricsGrid.innerHTML = metrics
    .map(([label, value]) => `<article class="metric"><span>${label}</span><strong>${value}</strong></article>`)
    .join("");
}

function renderStrategies() {
  el.strategyCards.innerHTML = state.data.leaderboard
    .map((manager, index) => {
      const active = manager.name === state.manager ? " active" : "";
      const color = COLORS[index % COLORS.length];
      return `
        <button class="strategy-card${active}" data-manager-card="${escapeHtml(manager.name)}" style="border-left: 5px solid ${color}">
          <div class="card-top">
            <strong>${escapeHtml(manager.name)}</strong>
            <span class="tag">${escapeHtml(manager.strategy)}</span>
          </div>
          <p class="muted">${strategyText(manager.sport_strategy, manager.economic_strategy)}</p>
          <span>${formatNumber(manager.points_total)} pts · ${formatMoney(manager.cash)} caja</span>
        </button>
      `;
    })
    .join("");
  document.querySelectorAll("[data-manager-card]").forEach((card) => {
    card.addEventListener("click", () => {
      state.manager = card.dataset.managerCard;
      render();
    });
  });
}

function renderPoints() {
  const rounds = getRounds();
  const series = state.data.lineups.map((manager, index) => {
    let cumulative = state.data.leaderboard.find((item) => item.name === manager.name)?.points_total || 0;
    const history = [...manager.lineup_history].sort((a, b) => b.round - a.round);
    const byRound = new Map();
    history.forEach((entry) => {
      byRound.set(Number(entry.round), cumulative);
      cumulative -= Number(entry.points_round || 0);
    });
    return {
      name: manager.name,
      color: COLORS[index % COLORS.length],
      values: rounds.map((round) => ({ x: round, y: byRound.get(round) || null })),
    };
  });
  drawLineChart(el.pointsChart, series, { yFormatter: formatNumber, xLabel: "Jornada" });
}

function renderSquads() {
  const manager = getLineupManager(state.manager);
  const entries = [...(manager?.lineup_history || [])].sort((a, b) => a.round - b.round);
  const visible = entries.filter((entry) => Number(entry.round) <= Number(state.round));
  if (!visible.length) {
    el.squadTimeline.innerHTML = emptyHtml();
    return;
  }
  el.squadTimeline.innerHTML = visible
    .map((entry) => {
      const players = state.squadMode === "lineup" ? entry.lineup || [] : entry.squad || entry.lineup || [];
      return `
        <div class="timeline-row">
          <div class="timeline-head">
            <strong>Jornada ${entry.round} · ${escapeHtml(entry.formation || "")}</strong>
            <span class="tag">${formatNumber(entry.points_round || 0)} pts</span>
          </div>
          ${renderPitch(entry, players)}
        </div>
      `;
    })
    .join("");
}

function renderPitch(entry, players) {
  const placed = placePlayersOnPitch(entry, players);
  const starterIds = new Set((entry.lineup || []).map((player) => Number(player.player_id)));
  return `
    <div class="pitch" aria-label="Campo de futbol">
      <div class="pitch-lines"></div>
      ${placed
        .map((item) => {
          const starter = starterIds.has(Number(item.player.player_id));
          const full = state.data.playerById.get(Number(item.player.player_id));
          return `
            <div class="pitch-player ${starter ? "starter" : "reserve"}" style="left:${item.x}%; top:${item.y}%">
              <strong>${escapeHtml(shortName(fixText(item.player.player)))}</strong>
              <span>${escapeHtml(shortPosition(item.player.position || full?.position))} · ${compactNumber(full?.marketValue || 0)}</span>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function placePlayersOnPitch(entry, players) {
  if (state.squadMode === "lineup") {
    return placeLineupByFormation(entry.formation, entry.lineup || players);
  }
  return placeSquadByPosition(players);
}

function placeLineupByFormation(formation, lineup) {
  const buckets = {
    Portero: lineup.filter((player) => normalisePosition(player.position) === "Portero"),
    Defensa: lineup.filter((player) => normalisePosition(player.position) === "Defensa"),
    Mediocampista: lineup.filter((player) => normalisePosition(player.position) === "Mediocampista"),
    Delantero: lineup.filter((player) => normalisePosition(player.position) === "Delantero"),
  };
  const parsed = String(formation || "")
    .split("-")
    .map((part) => Number(part))
    .filter(Boolean);
  const expected = {
    Defensa: parsed[0] || buckets.Defensa.length,
    Mediocampista: parsed[1] || buckets.Mediocampista.length,
    Delantero: parsed[2] || buckets.Delantero.length,
  };
  return [
    ...spreadLine(buckets.Portero.slice(0, 1), 88),
    ...spreadLine(buckets.Defensa.slice(0, expected.Defensa), 67),
    ...spreadLine(buckets.Mediocampista.slice(0, expected.Mediocampista), 43),
    ...spreadLine(buckets.Delantero.slice(0, expected.Delantero), 18),
  ];
}

function placeSquadByPosition(players) {
  const groups = {
    Portero: players.filter((player) => normalisePosition(player.position) === "Portero"),
    Defensa: players.filter((player) => normalisePosition(player.position) === "Defensa"),
    Mediocampista: players.filter((player) => normalisePosition(player.position) === "Mediocampista"),
    Delantero: players.filter((player) => normalisePosition(player.position) === "Delantero"),
  };
  return [
    ...spreadLine(groups.Portero, 88),
    ...spreadLine(groups.Defensa, 67),
    ...spreadLine(groups.Mediocampista, 43),
    ...spreadLine(groups.Delantero, 18),
  ];
}

function spreadLine(players, y) {
  const count = players.length;
  if (!count) return [];
  const minX = count > 5 ? 14 : 20;
  const maxX = count > 5 ? 86 : 80;
  return players.map((player, index) => {
    const row = count > 6 ? Math.floor(index / Math.ceil(count / 2)) : 0;
    const rowItems = count > 6 ? Math.ceil(count / 2) : count;
    const rowIndex = count > 6 ? index % rowItems : index;
    const denominator = Math.max(1, rowItems - 1);
    return {
      player,
      x: rowItems === 1 ? 50 : minX + ((maxX - minX) * rowIndex) / denominator,
      y: y + row * 8,
    };
  });
}

function normalisePosition(position) {
  const text = fixText(position).toLowerCase();
  if (text.includes("port")) return "Portero";
  if (text.includes("def")) return "Defensa";
  if (text.includes("medio") || text.includes("centro")) return "Mediocampista";
  if (text.includes("del")) return "Delantero";
  return "Mediocampista";
}

function shortPosition(position) {
  const normalised = normalisePosition(position);
  return { Portero: "POR", Defensa: "DEF", Mediocampista: "MED", Delantero: "DEL" }[normalised] || "JUG";
}

function shortName(name) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length <= 2) return parts.join(" ");
  return `${parts[0]} ${parts[parts.length - 1]}`;
}

function renderMarket() {
  const slice = getMarketSlice();
  if (!slice.sales.length && !slice.listings.length) {
    el.marketBoard.innerHTML = emptyHtml();
    return;
  }
  const sales = [...slice.sales].sort((a, b) => Number(b.price || b.ask_price || 0) - Number(a.price || a.ask_price || 0));
  el.marketBoard.innerHTML = sales
    .map((sale) => {
      const status = sale.status === "sold" ? "sold" : "unsold";
      const buyer = sale.buyer ? `Comprador: ${escapeHtml(sale.buyer)}` : sale.status === "sold_to_market" ? "Venta al mercado" : "Sin comprador";
      const bids = (sale.bids || [])
        .slice(0, 4)
        .map((bid) => `${escapeHtml(bid.manager)} ${formatMoney(bid.bid)}`)
        .join(" · ");
      return `
        <div class="market-item ${status}">
          <div class="market-head">
            <strong>${escapeHtml(fixText(sale.player))}</strong>
            <span class="tag">${formatMoney(sale.price || sale.ask_price || 0)}</span>
          </div>
          <span>${buyer} · Salida: ${formatMoney(sale.ask_price || 0)}</span>
          ${bids ? `<span>Pujas: ${bids}</span>` : ""}
        </div>
      `;
    })
    .join("");
}

function renderPlayer() {
  const player = state.data.playerById.get(Number(state.playerId));
  if (!player) {
    el.playerSummary.innerHTML = emptyHtml();
    return;
  }
  const valueSeries = getValueSeries(player);
  const pointsSeries = (player.points_history || [])
    .filter((entry) => Number(entry.round) >= 25)
    .map((entry) => ({ x: Number(entry.round), y: Number(entry.points || 0) }));
  drawLineChart(
    el.playerChart,
    [
      { name: "Valor", color: "#177e72", values: valueSeries },
      { name: "Puntos", color: "#d8672a", values: pointsSeries },
    ],
    { yFormatter: compactNumber, xLabel: "Jornada / ventana" },
  );
  el.playerSummary.innerHTML = `
    <div class="player-chip">
      <strong>${escapeHtml(fixText(player.name))}</strong>
      <span>${escapeHtml(fixText(player.teamName))} · ${escapeHtml(player.position || "-")}</span>
      <span>Valor actual: ${formatMoney(player.marketValue || 0)} · Puntos: ${formatNumber(player.points || 0)} · Media: ${formatNumber(player.averagePoints || 0)}</span>
    </div>
  `;
}

function renderDecisions() {
  syncDecisionRound();
  const items = getDecisionItems(state.manager)
    .filter((item) => Number(item.round) === Number(state.decisionRound))
    .sort(
      (a, b) =>
        Number(a.market_day || 99) - Number(b.market_day || 99) ||
        String(a.decision_type || "").localeCompare(String(b.decision_type || "")),
    );
  el.decisionRoundSelect.value = String(state.decisionRound);
  el.decisionRoundLabel.textContent = items.length
    ? `${items.length} decisiones en J${state.decisionRound}`
    : `Sin decisiones en J${state.decisionRound}`;
  if (!items.length) {
    el.decisionFeed.innerHTML = emptyHtml();
    return;
  }
  el.decisionFeed.innerHTML = items
    .map((item) => {
      const trace = item.decision_trace || [];
      const factors = item.key_factors || [];
      const risks = item.risk_flags || [];
      const status = decisionStatus(item);
      const confidence = item.confidence;
      return `
        <div class="decision-item ${status.className}">
          <div class="card-top">
            <strong>J${item.round} · Dia ${item.market_day || "-"} · ${escapeHtml(item.decision_type || "decision")}</strong>
            <span class="tag">${escapeHtml(status.label)}</span>
          </div>
          <p>${escapeHtml(formatDecisionText(item.summary || status.message))}</p>
          ${typeof confidence === "number" ? `<span>Confianza declarada: ${Math.round(confidence * 100)}%</span>` : ""}
          ${renderDecisionList("Factores", factors)}
          ${renderDecisionList("Riesgos", risks)}
          ${renderDecisionList("Traza", trace)}
          ${renderDecisionObject("Propuesta LLM", item.raw_response)}
          ${renderDecisionObject("Decision final aplicada", item.final_decision)}
        </div>
      `;
    })
    .join("");
}

function renderDecisionList(title, values) {
  const items = (values || []).filter(Boolean);
  if (!items.length) return "";
  return `
    <div class="decision-block">
      <strong>${escapeHtml(title)}</strong>
      <div class="decision-trace">
        ${items.map((step) => `<p>${escapeHtml(formatDecisionText(step))}</p>`).join("")}
      </div>
    </div>
  `;
}

function renderDecisionObject(title, value) {
  if (!value || typeof value !== "object") return "";
  return `
    <details class="decision-json">
      <summary>${escapeHtml(title)}</summary>
      <pre>${escapeHtml(formatDecisionObject(value))}</pre>
    </details>
  `;
}

function formatDecisionObject(value) {
  return JSON.stringify(enrichDecisionObject(value), null, 2)
    .replace(/"([^"]+)":/g, "$1:")
    .replace(/[{}"]/g, "")
    .trim();
}

function formatDecisionText(value) {
  return fixText(value).replace(/\bID\s*:?\s*(\d+)\b/gi, (match, id) => {
    const name = playerNameById(id);
    return name ? `${name} (ID ${id})` : match;
  });
}

function enrichDecisionObject(value, parentKey = "") {
  if (Array.isArray(value)) {
    if (["sell_player_ids", "lineup_player_ids", "sale_player_ids"].includes(parentKey)) {
      return value.map((id) => playerLabelById(id));
    }
    return value.map((item) => enrichDecisionObject(item, parentKey));
  }
  if (typeof value === "string") {
    return formatDecisionText(value);
  }
  if (!value || typeof value !== "object") {
    return value;
  }

  const enriched = {};
  Object.entries(value).forEach(([key, item]) => {
    if (key === "player_id") {
      enriched.jugador = playerLabelById(item);
      return;
    }
    if (key === "bid_by_player_id" && item && typeof item === "object" && !Array.isArray(item)) {
      enriched.pujas = Object.fromEntries(
        Object.entries(item).map(([playerId, bid]) => [playerLabelById(playerId), formatMoney(bid)]),
      );
      return;
    }
    if (["sell_player_ids", "lineup_player_ids", "sale_player_ids"].includes(key)) {
      enriched[key.replace("_ids", "")] = enrichDecisionObject(item, key);
      return;
    }
    enriched[key] = enrichDecisionObject(item, key);
  });
  return enriched;
}

function playerLabelById(id) {
  const name = playerNameById(id);
  return name ? `${name} (ID ${id})` : `ID ${id}`;
}

function playerNameById(id) {
  const player = state.data.playerById?.get(Number(id));
  return player ? fixText(player.name) : "";
}

function syncDecisionRound() {
  const rounds = getRounds();
  if (!rounds.length) {
    state.decisionRound = null;
    return;
  }
  state.decisionRound = rounds.includes(Number(state.decisionRound))
    ? Number(state.decisionRound)
    : Number(state.round || rounds[rounds.length - 1]);
  if (!rounds.includes(Number(state.decisionRound))) {
    state.decisionRound = rounds[rounds.length - 1];
  }
}

function decisionStatus(item) {
  const llmStatus = item.llm_status || {};
  if (llmStatus.parsed && !item.fallback_used) {
    return { className: "valid", label: "LLM", message: "Decision LLM parseada correctamente." };
  }
  if (llmStatus.parsed && item.recovered_after_run) {
    return { className: "recovered", label: "Recuperada", message: "La respuesta LLM original era parcial; se recupero el razonamiento despues de la ejecucion. La simulacion uso fallback en tiempo real." };
  }
  if (item.fallback_used && llmStatus.error) {
    return { className: "fallback", label: "Fallback", message: `Fallback tras error LLM: ${llmStatus.error}` };
  }
  if (item.fallback_used && llmStatus.has_raw_output) {
    return { className: "fallback", label: "No parseable", message: "El LLM respondio, pero la salida no fue parseable; se uso fallback." };
  }
  if (item.fallback_used) {
    return { className: "fallback", label: "Fallback", message: "No hubo decision LLM util; se uso fallback determinista." };
  }
  return { className: "unknown", label: "Sin estado", message: "No hay metadatos suficientes para explicar esta decision." };
}

function getRounds() {
  return [...new Set(state.data.lineups.flatMap((manager) => manager.lineup_history.map((entry) => Number(entry.round))))].sort(
    (a, b) => a - b,
  );
}

function getMarketSlice() {
  return (
    state.data.marketDays.find(
      (day) => Number(day.round) === Number(state.round) && Number(day.market_day) === Number(state.marketDay),
    ) || { listings: [], sales: [] }
  );
}

function getLineupManager(name) {
  return state.data.lineups.find((manager) => manager.name === name);
}

function getDecisionItems(name) {
  const manager = state.data.decisions.find((item) => item.name === name);
  return manager?.llm_decision_history || [];
}

function getValueSeries(player) {
  const history = player.marketValueHistory || [];
  if (history.length) {
    return history.map((entry, index) => ({ x: index + 1, y: Number(entry.value || 0), label: entry.window }));
  }
  return (player.marketValue_history || []).map((value, index) => ({ x: index + 1, y: Number(value || 0) }));
}

function playerChip(player) {
  const full = state.data.playerById.get(Number(player.player_id));
  return `
    <div class="player-chip">
      <strong>${escapeHtml(fixText(player.player))}</strong>
      <span>${escapeHtml(player.position || full?.position || "-")}</span>
      <span>${formatMoney(full?.marketValue || 0)} · ${formatNumber(full?.points || 0)} pts</span>
    </div>
  `;
}

function drawLineChart(canvas, series, options = {}) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  canvas.width = Math.max(320, Math.floor(rect.width * dpr));
  canvas.height = Math.floor((Number(canvas.getAttribute("height")) || 260) * dpr);
  ctx.scale(dpr, dpr);

  const width = canvas.width / dpr;
  const height = canvas.height / dpr;
  ctx.clearRect(0, 0, width, height);

  const pad = { top: 18, right: 16, bottom: 34, left: 56 };
  const points = series.flatMap((item) => item.values.filter((point) => point.y !== null && Number.isFinite(point.y)));
  if (!points.length) {
    ctx.fillStyle = "#68736f";
    ctx.fillText("Sin datos", 16, 28);
    return;
  }
  const xs = points.map((point) => Number(point.x));
  const ys = points.map((point) => Number(point.y));
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(0, Math.min(...ys));
  const maxY = Math.max(...ys) * 1.08 || 1;
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const xScale = (x) => pad.left + ((x - minX) / Math.max(1, maxX - minX)) * plotW;
  const yScale = (y) => pad.top + (1 - (y - minY) / Math.max(1, maxY - minY)) * plotH;

  ctx.strokeStyle = "#dfe5df";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#68736f";
  ctx.font = "12px system-ui";
  for (let i = 0; i <= 4; i += 1) {
    const y = pad.top + (plotH / 4) * i;
    const value = maxY - ((maxY - minY) / 4) * i;
    ctx.beginPath();
    ctx.moveTo(pad.left, y);
    ctx.lineTo(width - pad.right, y);
    ctx.stroke();
    ctx.fillText((options.yFormatter || formatNumber)(value), 8, y + 4);
  }

  series.forEach((item) => {
    const values = item.values.filter((point) => point.y !== null && Number.isFinite(point.y));
    ctx.strokeStyle = item.color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    values.forEach((point, index) => {
      const x = xScale(Number(point.x));
      const y = yScale(Number(point.y));
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    values.forEach((point) => {
      ctx.fillStyle = item.color;
      ctx.beginPath();
      ctx.arc(xScale(Number(point.x)), yScale(Number(point.y)), 3, 0, Math.PI * 2);
      ctx.fill();
    });
  });

  ctx.fillStyle = "#68736f";
  ctx.fillText(`${options.xLabel || "X"} ${minX}-${maxX}`, pad.left, height - 10);
  let legendX = pad.left;
  series.forEach((item) => {
    ctx.fillStyle = item.color;
    ctx.fillRect(legendX, 8, 10, 10);
    ctx.fillStyle = "#17211f";
    ctx.fillText(item.name, legendX + 14, 17);
    legendX += ctx.measureText(item.name).width + 34;
  });
}

function strategyText(sport, economic) {
  const sportText = {
    cracks: "Busca jugadores diferenciales y alto techo de puntos.",
    mejor_forma: "Prioriza rendimiento reciente y regularidad.",
    grandes_clubes: "Confia en futbolistas de clubes fuertes.",
    equipos_pequenos: "Explora valor oculto en equipos modestos.",
    arriesgado: "Acepta volatilidad para perseguir subidas grandes.",
  };
  const ecoText = {
    balanceado: "Gestiona caja y plantilla con prudencia.",
    tacano: "Compra con disciplina y evita sobrepagar.",
    fichar_a_toda_costa: "Presiona el mercado cuando ve oportunidad.",
  };
  return `${sportText[sport] || sport}. ${ecoText[economic] || economic}`;
}

function formatMoney(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M EUR`;
  if (Math.abs(number) >= 1_000) return `${(number / 1_000).toFixed(0)}k EUR`;
  return `${Math.round(number)} EUR`;
}

function compactNumber(value) {
  const number = Number(value || 0);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (Math.abs(number) >= 1_000) return `${(number / 1_000).toFixed(0)}k`;
  return formatNumber(number);
}

function formatNumber(value) {
  return new Intl.NumberFormat("es-ES", { maximumFractionDigits: 1 }).format(Number(value || 0));
}

function fixText(value) {
  if (value === null || value === undefined) return "";
  const text = String(value);
  if (!/[ÃÂ�]/.test(text)) return text;
  try {
    const bytes = Uint8Array.from([...text].map((char) => char.charCodeAt(0)));
    return new TextDecoder("utf-8").decode(bytes);
  } catch {
    return text;
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function emptyHtml() {
  return document.getElementById("emptyTemplate").innerHTML;
}

function renderBootError(error) {
  el.metricsGrid.innerHTML = `
    <article class="metric">
      <span>No se pudieron cargar los datos</span>
      <strong>Servidor requerido</strong>
    </article>
  `;
  const message = `
    <div class="empty">
      Abre la demo desde un servidor local para que el navegador pueda leer los JSON.
      Comando: python -m http.server 8090 --bind 127.0.0.1
      Detalle: ${escapeHtml(error.message || error)}
    </div>
  `;
  ["strategyCards", "squadTimeline", "marketBoard", "decisionFeed", "playerSummary"].forEach((id) => {
    if (el[id]) el[id].innerHTML = message;
  });
}
