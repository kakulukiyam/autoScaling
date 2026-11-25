const INSTANCE_COLORS = [
  "#38bdf8",
  "#22c55e",
  "#f59e0b",
  "#a855f7",
  "#ec4899",
  "#14b8a6",
];

const state = {
  colorMap: new Map(),
  lbStats: new Map(),
  lbTotal: 0,
  lbLogs: [],
  autoPollTimer: null,
};

function getColorForInstance(id) {
  if (!state.colorMap.has(id)) {
    const idx = state.colorMap.size % INSTANCE_COLORS.length;
    state.colorMap.set(id, INSTANCE_COLORS[idx]);
  }
  return state.colorMap.get(id);
}

async function fetchJson(url, options = {}) {
  const resp = await fetch(url, { cache: "no-store", ...options });
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}`);
  }
  return resp.json();
}

async function refreshCurrentNode() {
  try {
    const info = await fetchJson(`/api/info?t=${Date.now()}`);
    document.getElementById("initial-instance-id").textContent =
      `${info.instance_id} (${info.availability_zone})`;

    const stressEl = document.getElementById("kpi-stress");
    const stressRemEl = document.getElementById("kpi-stress-rem");
    const badgeEl = document.getElementById("stress-mode-badge");

    if (info.stress_active) {
      stressEl.textContent = `${info.cpu_percent}% CPU`;
      stressEl.style.color = "#ef4444";
      stressRemEl.textContent = `Restante: ${info.stress_remaining_sec}s · Coordinador ${info.cluster_coordinator_active ? "activo" : "local"}`;
      badgeEl.textContent = "Estrés Activo";
      badgeEl.classList.add("active");
    } else {
      stressEl.textContent = `Inactivo (${info.cpu_percent}%)`;
      stressEl.style.color = "#22c55e";
      stressRemEl.textContent = "Listo para ejecutar prueba";
      badgeEl.textContent = "Reposo";
      badgeEl.classList.remove("active");
    }
  } catch (err) {
    console.error("Error consultando /api/info:", err);
  }
}

function drawCpuChart(history) {
  const canvas = document.getElementById("cpu-chart");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const padL = 42;
  const padR = 16;
  const padT = 16;
  const padB = 28;
  const plotW = w - padL - padR;
  const plotH = h - padT - padB;

  ctx.clearRect(0, 0, w, h);

  // Grilla horizontal
  ctx.strokeStyle = "#1e293b";
  ctx.fillStyle = "#94a3b8";
  ctx.font = "11px system-ui";
  ctx.lineWidth = 1;

  for (const pct of [0, 25, 50, 75, 100]) {
    const y = padT + plotH - (pct / 100) * plotH;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.fillText(`${pct}%`, 6, y + 4);
  }

  // Línea Scale-Up (45%) y Scale-Down (25%)
  const drawThreshold = (pct, color) => {
    const y = padT + plotH - (pct / 100) * plotH;
    ctx.save();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(padL, y);
    ctx.lineTo(w - padR, y);
    ctx.stroke();
    ctx.restore();
  };

  drawThreshold(45, "#ef4444");
  drawThreshold(25, "#22c55e");

  if (!history || history.length === 0) {
    ctx.fillStyle = "#94a3b8";
    ctx.fillText("Esperando datapoints de CloudWatch (1 min)...", padL + 20, padT + plotH / 2);
    return;
  }

  // Curva CPU
  ctx.strokeStyle = "#38bdf8";
  ctx.lineWidth = 2.5;
  ctx.beginPath();

  history.forEach((pt, idx) => {
    const x = history.length === 1
      ? padL + plotW / 2
      : padL + (idx / (history.length - 1)) * plotW;
    const y = padT + plotH - (Math.min(100, Math.max(0, pt.average)) / 100) * plotH;
    if (idx === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Puntos y último valor
  history.forEach((pt, idx) => {
    const x = history.length === 1
      ? padL + plotW / 2
      : padL + (idx / (history.length - 1)) * plotW;
    const y = padT + plotH - (Math.min(100, Math.max(0, pt.average)) / 100) * plotH;
    ctx.fillStyle = "#38bdf8";
    ctx.beginPath();
    ctx.arc(x, y, 3.5, 0, Math.PI * 2);
    ctx.fill();
  });

  const firstTs = history[0].timestamp.slice(11, 16);
  const lastTs = history[history.length - 1].timestamp.slice(11, 16);
  ctx.fillStyle = "#94a3b8";
  ctx.fillText(`${firstTs} UTC`, padL, h - 8);
  ctx.fillText(`${lastTs} UTC`, w - padR - 58, h - 8);
}

async function refreshAwsStatus() {
  try {
    const data = await fetchJson(`/api/aws-status?t=${Date.now()}`);

    if (data.asg) {
      document.getElementById("asg-name-pill").textContent = data.asg.name;
      document.getElementById("kpi-inservice").textContent =
        `${data.asg.in_service_count} / ${data.asg.max_size}`;
      document.getElementById("kpi-desired").textContent =
        `Deseadas: ${data.asg.desired_capacity} · Pendientes: ${data.asg.pending_count} · Terminando: ${data.asg.terminating_count}`;
      document.getElementById("kpi-limits").textContent =
        `${data.asg.min_size} – ${data.asg.max_size}`;
    }

    if (data.cpu_history && data.cpu_history.length > 0) {
      const latest = data.cpu_history[data.cpu_history.length - 1];
      document.getElementById("kpi-cpu").textContent = `${latest.average}%`;
      document.getElementById("kpi-cpu-time").textContent =
        `Último dato CloudWatch: ${latest.timestamp.slice(11, 19)} UTC`;
    }
    drawCpuChart(data.cpu_history || []);

    const alarmsEl = document.getElementById("alarms-container");
    if (data.alarms && data.alarms.length > 0) {
      alarmsEl.innerHTML = data.alarms.map((a) => `
        <div class="alarm-card">
          <div class="alarm-top">
            <strong class="mono" style="font-size:0.82rem">${a.name}</strong>
            <span class="alarm-state state-${a.state}">${a.state}</span>
          </div>
          <div style="font-size:0.8rem;color:#cbd5e1">
            Umbral: <strong>${a.threshold}%</strong> (${a.comparison === "GreaterThanOrEqualToThreshold" ? "≥" : "≤"} ${a.evaluation_periods}x${a.period}s)
          </div>
          <div class="alarm-reason">${a.reason || ""}</div>
        </div>
      `).join("");
    }

    const tbody = document.getElementById("instances-tbody");
    if (data.instances && data.instances.length > 0) {
      tbody.innerHTML = data.instances.map((i) => `
        <tr>
          <td class="mono">${i.instance_id}</td>
          <td>${i.availability_zone}</td>
          <td class="mono">${i.private_ip}</td>
          <td>${i.lifecycle_state}</td>
          <td>${i.target_health}</td>
        </tr>
      `).join("");
    } else {
      tbody.innerHTML = '<tr><td colspan="5">Sin instancias registradas.</td></tr>';
    }

    const actEl = document.getElementById("activities-list");
    if (data.activities && data.activities.length > 0) {
      actEl.innerHTML = data.activities.map((act) => `
        <div class="activity-item">
          <strong>[${act.status}]</strong> ${act.description}
          <small>${act.start_time || ""} — ${act.cause || ""}</small>
        </div>
      `).join("");
    }
  } catch (err) {
    console.error("Error consultando /api/aws-status:", err);
  }
}

async function startStressTest() {
  const btn = document.getElementById("btn-start-stress");
  const feedback = document.getElementById("stress-feedback");
  btn.disabled = true;
  try {
    const res = await fetchJson("/api/stress", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration: 300, cluster: true }),
    });
    feedback.innerHTML = `🔥 <strong>Estrés iniciado</strong> en modo <code>${res.mode}</code> por nodo <code class="mono">${res.handled_by}</code> (${res.workers} workers, ${res.duration_sec}s). Observa cómo la alarma Scale-Up pasa a <strong>ALARM</strong> y sube el ASG a 4 instancias.`;
    await refreshCurrentNode();
    await refreshAwsStatus();
  } catch (err) {
    feedback.textContent = `Error iniciando estrés: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

async function stopStressTest() {
  const btn = document.getElementById("btn-stop-stress");
  const feedback = document.getElementById("stress-feedback");
  btn.disabled = true;
  try {
    const res = await fetchJson("/api/stress/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cluster: true }),
    });
    feedback.innerHTML = `🛑 <strong>Estrés detenido</strong> en todo el clúster desde <code class="mono">${res.handled_by}</code>. La CPU bajará a ~1% y la alarma Scale-Down devolverá el ASG a 1 instancia tras 2 minutos.`;
    await refreshCurrentNode();
    await refreshAwsStatus();
  } catch (err) {
    feedback.textContent = `Error deteniendo estrés: ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

function renderLoadBalanceUI() {
  const summaryEl = document.getElementById("lb-summary");
  const barsEl = document.getElementById("lb-bars");
  const logEl = document.getElementById("lb-log");

  const entries = Array.from(state.lbStats.values()).sort((a, b) => b.count - a.count);
  summaryEl.innerHTML = `Total peticiones enviadas: <strong>${state.lbTotal}</strong> · Instancias distintas alcanzadas: <strong>${entries.length}</strong>`;

  barsEl.innerHTML = entries.map((item) => {
    const pct = state.lbTotal > 0 ? ((item.count / state.lbTotal) * 100).toFixed(1) : "0.0";
    const color = getColorForInstance(item.instance_id);
    return `
      <div class="lb-bar-item">
        <div class="lb-bar-head">
          <span>
            <strong class="mono" style="color:${color}">${item.instance_id}</strong>
            <span style="color:#94a3b8"> · ${item.availability_zone} · ${item.private_ip}</span>
          </span>
          <span>
            CPU: <strong>${item.cpu_percent}%</strong> ·
            <strong>${item.count}</strong> peticiones (<strong>${pct}%</strong>)
          </span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${pct}%; background:${color};"></div>
        </div>
      </div>
    `;
  }).join("");

  logEl.innerHTML = state.lbLogs.slice(0, 60).map((line) => `<div>${line}</div>`).join("");
}

async function sendSingleLbProbe(seq) {
  const t0 = performance.now();
  const info = await fetchJson(`/api/info?seq=${seq}&t=${Date.now()}-${Math.random()}`);
  const ms = Math.round(performance.now() - t0);

  state.lbTotal += 1;
  const existing = state.lbStats.get(info.instance_id) || {
    instance_id: info.instance_id,
    availability_zone: info.availability_zone,
    private_ip: info.private_ip,
    cpu_percent: info.cpu_percent,
    count: 0,
  };
  existing.count += 1;
  existing.cpu_percent = info.cpu_percent;
  state.lbStats.set(info.instance_id, existing);

  const timeStr = new Date().toLocaleTimeString();
  state.lbLogs.unshift(
    `[${timeStr}] #${state.lbTotal} -> ${info.instance_id} (${info.availability_zone}, ${info.private_ip}) CPU ${info.cpu_percent}% · ${ms}ms`
  );
  if (state.lbLogs.length > 100) state.lbLogs.pop();
}

async function runLoadBalanceTest() {
  const btn = document.getElementById("btn-lb-test");
  const total = parseInt(document.getElementById("lb-count").value, 10) || 40;
  btn.disabled = true;
  state.lbStats.clear();
  state.lbTotal = 0;
  state.lbLogs = [];

  try {
    const batchSize = 5;
    for (let i = 0; i < total; i += batchSize) {
      const batch = [];
      for (let j = 0; j < batchSize && i + j < total; j += 1) {
        batch.push(sendSingleLbProbe(i + j + 1));
      }
      await Promise.all(batch);
      renderLoadBalanceUI();
    }
  } catch (err) {
    state.lbLogs.unshift(`Error en petición: ${err.message}`);
    renderLoadBalanceUI();
  } finally {
    btn.disabled = false;
  }
}

document.getElementById("btn-start-stress").addEventListener("click", startStressTest);
document.getElementById("btn-stop-stress").addEventListener("click", stopStressTest);
document.getElementById("btn-lb-test").addEventListener("click", runLoadBalanceTest);

document.getElementById("lb-auto-toggle").addEventListener("change", (ev) => {
  if (ev.target.checked) {
    state.autoPollTimer = setInterval(async () => {
      try {
        await sendSingleLbProbe(state.lbTotal + 1);
        renderLoadBalanceUI();
      } catch (e) {
        console.error(e);
      }
    }, 1000);
  } else if (state.autoPollTimer) {
    clearInterval(state.autoPollTimer);
    state.autoPollTimer = null;
  }
});

refreshCurrentNode();
refreshAwsStatus();
setInterval(refreshCurrentNode, 5000);
setInterval(refreshAwsStatus, 5000);
