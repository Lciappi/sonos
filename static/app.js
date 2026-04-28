const $groups = document.getElementById("groups");
const $status = document.getElementById("status");
const $refresh = document.getElementById("refresh");

let pollTimer = null;
const draggingVolume = new Set();

async function fetchState() {
  try {
    const r = await fetch("/api/state");
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const data = await r.json();
    render(data);
    $status.textContent = `${data.count} speaker${data.count === 1 ? "" : "s"}`;
  } catch (e) {
    $status.textContent = `Error: ${e.message}`;
  }
}

async function post(path, body) {
  const r = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text || `HTTP ${r.status}`);
  }
  return r.json();
}

function render({ groups }) {
  // Preserve focus / range drag state across re-render by diffing on coordinator UUID.
  const existing = new Map();
  for (const el of $groups.querySelectorAll(".group")) {
    existing.set(el.dataset.coordinator, el);
  }

  const wanted = new Set(groups.map((g) => g.coordinator));
  for (const [uuid, el] of existing) {
    if (!wanted.has(uuid)) el.remove();
  }

  for (const g of groups) {
    let el = existing.get(g.coordinator);
    if (!el) {
      el = document.createElement("section");
      el.className = "group";
      el.dataset.coordinator = g.coordinator;
      $groups.appendChild(el);
    }
    el.innerHTML = renderGroup(g);
    wireGroup(el, g);
  }
}

function renderGroup(g) {
  const np = g.now_playing || {};
  const state = (np.state || "").toUpperCase();
  const dotClass = state === "PLAYING" ? "playing" : state === "PAUSED_PLAYBACK" ? "paused" : "";
  const isPlaying = state === "PLAYING";
  const title = escapeHtml(np.title || (state === "STOPPED" ? "—" : "Unknown"));
  const artist = escapeHtml(np.artist || "");
  const source = escapeHtml(np.source || "");
  const art = np.art ? `background-image: url('${escapeAttr(np.art)}')` : "";

  const memberRows = g.members
    .map(
      (m) => `
    <div class="member" data-uuid="${escapeAttr(m.uuid)}">
      <div class="member-name">
        ${escapeHtml(m.room_name)}
        ${m.is_coordinator && g.members.length > 1 ? '<span class="badge">lead</span>' : ""}
      </div>
      <input type="range" min="0" max="100" value="${m.volume}" data-uuid="${escapeAttr(m.uuid)}" />
      <div class="vol-readout" data-readout="${escapeAttr(m.uuid)}">${m.volume}</div>
    </div>`
    )
    .join("");

  return `
    <h2 class="group-name"><span class="dot ${dotClass}"></span>${escapeHtml(g.name)}</h2>
    <div class="now-playing">
      <div class="art" style="${art}"></div>
      <div class="np-text">
        <div class="np-title">${title}</div>
        <div class="np-artist">${artist}</div>
        <div class="np-source">${source}</div>
      </div>
    </div>
    <div class="transport" data-coord="${escapeAttr(g.coordinator)}">
      <button data-act="previous" title="Previous">⏮</button>
      <button data-act="${isPlaying ? "pause" : "play"}" class="primary">${isPlaying ? "Pause" : "Play"}</button>
      <button data-act="next" title="Next">⏭</button>
    </div>
    <div class="members">${memberRows}</div>
  `;
}

function wireGroup(el, g) {
  const transport = el.querySelector(".transport");
  transport.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    btn.disabled = true;
    try {
      await post(`/api/${g.coordinator}/${act}`);
      setTimeout(fetchState, 250);
    } catch (err) {
      $status.textContent = `Error: ${err.message}`;
    } finally {
      btn.disabled = false;
    }
  });

  for (const range of el.querySelectorAll('input[type="range"]')) {
    const uuid = range.dataset.uuid;
    const readout = el.querySelector(`[data-readout="${cssEscape(uuid)}"]`);

    range.addEventListener("pointerdown", () => draggingVolume.add(uuid));
    range.addEventListener("pointerup", () => {
      draggingVolume.delete(uuid);
      commitVolume(uuid, parseInt(range.value, 10));
    });
    range.addEventListener("input", () => {
      readout.textContent = range.value;
    });
    range.addEventListener("change", () => {
      commitVolume(uuid, parseInt(range.value, 10));
    });
  }
}

let volumeQueue = new Map();
async function commitVolume(uuid, value) {
  volumeQueue.set(uuid, value);
  // Coalesce rapid changes per uuid
  await new Promise((r) => setTimeout(r, 60));
  const v = volumeQueue.get(uuid);
  if (v !== value) return; // a newer value won
  volumeQueue.delete(uuid);
  try {
    await post(`/api/${uuid}/volume`, { volume: value });
  } catch (e) {
    $status.textContent = `Volume error: ${e.message}`;
  }
}

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
function escapeAttr(s) {
  return escapeHtml(s);
}
function cssEscape(s) {
  return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

$refresh.addEventListener("click", async () => {
  $refresh.disabled = true;
  $status.textContent = "Re-scanning…";
  try {
    await post("/api/refresh");
    await fetchState();
  } finally {
    $refresh.disabled = false;
  }
});

fetchState();
pollTimer = setInterval(() => {
  // Skip polling while user is dragging any volume slider, to avoid jitter.
  if (draggingVolume.size === 0) fetchState();
}, 2500);
