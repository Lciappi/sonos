const $groups = document.getElementById("groups");
const $status = document.getElementById("status");
const $refresh = document.getElementById("refresh");
const $alarmsBtn = document.getElementById("alarms-btn");
const $drawer = document.getElementById("drawer");
const $drawerTitle = document.getElementById("drawer-title");
const $drawerBody = document.getElementById("drawer-body");
const $drawerClose = document.getElementById("drawer-close");
const $overlay = document.getElementById("overlay");

const draggingControls = new Set();
let lastState = null;
const tabState = new Map(); // coordinator -> active tab id
const tabData = new Map();  // `${coord}:${tab}` -> last fetched payload

// ----- API helpers -----

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
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

async function patchJSON(path, body) {
  const r = await fetch(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : null,
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function del(path) {
  const r = await fetch(path, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ----- main render loop -----

async function fetchState() {
  try {
    const data = await getJSON("/api/state");
    lastState = data;
    render(data);
    $status.textContent = `${data.count} speaker${data.count === 1 ? "" : "s"}`;
  } catch (e) {
    $status.textContent = `Error: ${e.message}`;
  }
}

function render({ groups }) {
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
    const isNew = !el;
    if (isNew) {
      el = document.createElement("section");
      el.className = "group";
      el.dataset.coordinator = g.coordinator;
      $groups.appendChild(el);
    }
    renderGroup(el, g, isNew);
  }
}

function renderGroup(el, g, isNew) {
  const np = g.now_playing || {};
  const state = (np.state || "").toUpperCase();
  const dotClass = state === "PLAYING" ? "playing" : state === "PAUSED_PLAYBACK" ? "paused" : "";
  const isPlaying = state === "PLAYING";
  const title = np.title || (state === "STOPPED" ? "—" : "Unknown");
  const artist = np.artist || "";
  const source = np.source || "";
  const art = np.art || "";

  const posSec = hmsToSec(np.position);
  const durSec = hmsToSec(np.duration);

  const activeTab = tabState.get(g.coordinator) || "modes";

  el.innerHTML = `
    <h2 class="group-name">
      <span class="dot ${dotClass}"></span>
      ${escapeHtml(g.name)}
      ${g.stereo_pair ? '<span class="badge pair">Stereo Pair</span>' : ""}
    </h2>
    <div class="now-playing">
      <div class="art" style="${art ? `background-image:url('${escapeAttr(art)}')` : ""}"></div>
      <div class="np-text">
        <div class="np-title">${escapeHtml(title)}</div>
        <div class="np-artist">${escapeHtml(artist)}</div>
        <div class="np-source">${escapeHtml(source)}</div>
      </div>
    </div>
    <div class="seek-row" data-coord="${escapeAttr(g.coordinator)}">
      <span class="seek-pos">${formatTime(posSec)}</span>
      <input type="range" min="0" max="${Math.max(durSec, 1)}" value="${posSec}" data-seek="${escapeAttr(g.coordinator)}" ${durSec === 0 ? "disabled" : ""} />
      <span class="seek-dur">${formatTime(durSec)}</span>
    </div>
    <div class="transport" data-coord="${escapeAttr(g.coordinator)}">
      <button data-act="previous" title="Previous">⏮</button>
      <button data-act="${isPlaying ? "pause" : "play"}" class="primary">${isPlaying ? "Pause" : "Play"}</button>
      <button data-act="next" title="Next">⏭</button>
    </div>
    <div class="tabs" data-coord="${escapeAttr(g.coordinator)}">
      <button class="tab ${activeTab === "modes" ? "active" : ""}" data-tab="modes">Modes</button>
      <button class="tab ${activeTab === "audio" ? "active" : ""}" data-tab="audio">Audio</button>
      <button class="tab ${activeTab === "queue" ? "active" : ""}" data-tab="queue">Queue</button>
      <button class="tab ${activeTab === "favorites" ? "active" : ""}" data-tab="favorites">Favorites</button>
      <button class="tab ${activeTab === "group" ? "active" : ""}" data-tab="group">Group</button>
      <button class="tab ${activeTab === "speakers" ? "active" : ""}" data-tab="speakers">Speakers</button>
    </div>
    <div class="tab-panel ${activeTab === "modes" ? "active" : ""}" data-panel="modes">${renderModes(g)}</div>
    <div class="tab-panel ${activeTab === "audio" ? "active" : ""}" data-panel="audio"><em class="fav-empty">Loading…</em></div>
    <div class="tab-panel ${activeTab === "queue" ? "active" : ""}" data-panel="queue"><em class="fav-empty">Loading…</em></div>
    <div class="tab-panel ${activeTab === "favorites" ? "active" : ""}" data-panel="favorites"><em class="fav-empty">Loading…</em></div>
    <div class="tab-panel ${activeTab === "group" ? "active" : ""}" data-panel="group">${renderGroupTab(g)}</div>
    <div class="tab-panel ${activeTab === "speakers" ? "active" : ""}" data-panel="speakers">${renderSpeakers(g)}</div>
  `;

  wireGroup(el, g);
  // Lazy-load whichever tab is active
  loadTabContent(el, g, activeTab);
}

// ----- tab renderers -----

function renderModes(g) {
  const mode = g.play_mode || "NORMAL";
  const cf = g.crossfade ? "checked" : "";
  const sleepMin = Math.round((g.sleep_remaining || 0) / 60);
  const sleepActive = g.sleep_remaining > 0
    ? `<span class="sleep-active">${sleepMin}m left</span>` : "";
  return `
    <div class="modes-grid">
      <label>Shuffle / repeat</label>
      <select data-mode="${escapeAttr(g.coordinator)}">
        ${["NORMAL","REPEAT_ALL","REPEAT_ONE","SHUFFLE","SHUFFLE_NOREPEAT","SHUFFLE_REPEAT_ONE"]
          .map(m => `<option value="${m}" ${m===mode?"selected":""}>${prettyMode(m)}</option>`).join("")}
      </select>

      <label>Crossfade</label>
      <div><input type="checkbox" data-cf="${escapeAttr(g.coordinator)}" ${cf} /></div>

      <label>Sleep timer</label>
      <div class="sleep-row">
        <input type="number" min="0" max="480" placeholder="min" data-sleep="${escapeAttr(g.coordinator)}" />
        <button data-sleep-set="${escapeAttr(g.coordinator)}">Set</button>
        <button data-sleep-clear="${escapeAttr(g.coordinator)}">Cancel</button>
        ${sleepActive}
      </div>
    </div>
  `;
}

function renderSpeakers(g) {
  return `
    <div data-speakers-for="${escapeAttr(g.coordinator)}">
      ${g.members.map(m => `
        <div class="member" data-uuid="${escapeAttr(m.uuid)}">
          <div class="member-name">
            ${escapeHtml(m.room_name)}
            ${m.is_coordinator && g.members.length > 1 ? '<span class="badge">lead</span>' : ""}
            ${m.pair_partner ? '<span class="badge pair">paired</span>' : ""}
            ${m.is_satellite ? '<span class="badge">satellite</span>' : ""}
          </div>
          ${m.is_satellite ? '<div></div><div></div>' : `
            <input type="range" min="0" max="100" value="${m.volume}" data-vol="${escapeAttr(m.uuid)}" />
            <div class="vol-readout" data-readout="${escapeAttr(m.uuid)}">${m.volume}</div>
          `}
        </div>
      `).join("")}
    </div>
  `;
}

function renderGroupTab(g) {
  if (!lastState) return "";
  const sameHousehold = lastState.groups.filter(o => o.household === g.household && o.coordinator !== g.coordinator);
  const sameHouseholdSpeakers = [];
  for (const og of lastState.groups) {
    if (og.household === g.household) {
      for (const m of og.members) sameHouseholdSpeakers.push(m);
    }
  }
  const ours = new Set(g.members.map(m => m.uuid));
  const others = sameHouseholdSpeakers.filter(s => !ours.has(s.uuid) && !s.is_satellite);
  const isMulti = g.members.length > 1;

  return `
    <div class="group-controls">
      <button data-everywhere="${escapeAttr(g.coordinator)}">Play everywhere</button>
      ${isMulti ? `<button data-solo-coord="${escapeAttr(g.coordinator)}">Ungroup all</button>` : ""}
    </div>
    <div>
      ${others.length === 0 ? '<div class="fav-empty">No other speakers in this household.</div>' : ""}
      ${others.map(s => `
        <div class="member" data-add-uuid="${escapeAttr(s.uuid)}">
          <div class="member-name">${escapeHtml(s.room_name)}</div>
          <div></div>
          <button data-add-to="${escapeAttr(g.coordinator)}" data-add-uuid="${escapeAttr(s.uuid)}">Add</button>
        </div>
      `).join("")}
    </div>
    ${isMulti ? `
      <div style="margin-top:10px; border-top:1px solid var(--line); padding-top:10px;">
        <div style="font-size:12px;color:var(--muted);margin-bottom:6px;">In this group:</div>
        ${g.members.filter(m => !m.is_satellite && !m.is_coordinator).map(m => `
          <div class="member">
            <div class="member-name">${escapeHtml(m.room_name)}</div>
            <div></div>
            <button data-leave-uuid="${escapeAttr(m.uuid)}">Leave</button>
          </div>
        `).join("")}
      </div>
    ` : ""}
  `;
}

// ----- async tab content -----

async function loadTabContent(el, g, tab) {
  const panel = el.querySelector(`[data-panel="${tab}"]`);
  if (!panel) return;
  if (tab === "modes" || tab === "speakers" || tab === "group") return; // sync

  if (tab === "audio") {
    try {
      const eq = await getJSON(`/api/${g.coordinator}/eq`);
      panel.innerHTML = renderAudio(g, eq);
      wireAudio(panel, g);
    } catch (e) {
      panel.innerHTML = `<em class="fav-empty">Error: ${escapeHtml(e.message)}</em>`;
    }
    return;
  }

  if (tab === "queue") {
    try {
      const { items } = await getJSON(`/api/${g.coordinator}/queue`);
      panel.innerHTML = renderQueue(g, items || []);
      wireQueue(panel, g);
    } catch (e) {
      panel.innerHTML = `<em class="fav-empty">Error: ${escapeHtml(e.message)}</em>`;
    }
    return;
  }

  if (tab === "favorites") {
    try {
      const [favs, plays] = await Promise.all([
        getJSON(`/api/${g.coordinator}/favorites`),
        getJSON(`/api/${g.coordinator}/playlists`),
      ]);
      panel.innerHTML = renderFavorites(g, favs.items || [], plays.items || []);
      wireFavorites(panel, g);
    } catch (e) {
      panel.innerHTML = `<em class="fav-empty">Error: ${escapeHtml(e.message)}</em>`;
    }
    return;
  }
}

function renderAudio(g, eq) {
  return `
    <div class="row">
      <label>Bass</label>
      <input type="range" min="-10" max="10" value="${eq.bass}" data-bass="${escapeAttr(g.coordinator)}" />
      <div class="readout" data-readout-bass>${eq.bass}</div>
    </div>
    <div class="row">
      <label>Treble</label>
      <input type="range" min="-10" max="10" value="${eq.treble}" data-treble="${escapeAttr(g.coordinator)}" />
      <div class="readout" data-readout-treble>${eq.treble}</div>
    </div>
    <div class="row">
      <label>Balance</label>
      <input type="range" min="-100" max="100" value="${eq.balance}" data-balance="${escapeAttr(g.coordinator)}" />
      <div class="readout" data-readout-balance>${eq.balance}</div>
    </div>
    <div class="row-toggle">
      <span>Loudness</span>
      <input type="checkbox" data-loud="${escapeAttr(g.coordinator)}" ${eq.loudness ? "checked" : ""} />
    </div>
  `;
}

function renderQueue(g, items) {
  if (!items.length) {
    return `<div class="fav-empty">Queue is empty.</div>`;
  }
  return `
    <div class="queue">
      ${items.map(t => `
        <div class="queue-item" data-pos="${t.position}">
          <span class="pos">${t.position}</span>
          <div class="meta">
            <div class="t">${escapeHtml(t.title || "—")}</div>
            <div class="a">${escapeHtml(t.artist || "")}</div>
          </div>
          <div class="actions">
            <button data-q-play="${t.position}" title="Play">▶</button>
            <button data-q-rm="${t.position}" class="rm" title="Remove">✕</button>
          </div>
        </div>
      `).join("")}
    </div>
    <div class="queue-actions">
      <input type="text" placeholder="Save queue as…" data-q-save-title />
      <button data-q-save="${escapeAttr(g.coordinator)}">Save</button>
      <button data-q-clear="${escapeAttr(g.coordinator)}">Clear</button>
    </div>
  `;
}

function renderFavorites(g, favs, plays) {
  const fmt = (kind, list) => list.length === 0
    ? `<div class="fav-empty">No ${kind}.</div>`
    : `<div class="fav-list">${list.map(f => `
        <div class="fav-item">
          <div>${escapeHtml(f.title || "—")}</div>
          <button class="play"
            data-${kind === "favorites" ? "play-fav" : "play-pl"}="${escapeAttr(g.coordinator)}"
            data-uri="${escapeAttr(f.uri)}"
            data-meta="${escapeAttr(f.metadata || "")}"
            data-container="${f.is_container ? "1" : "0"}">Play</button>
        </div>`).join("")}</div>`;
  return `
    <div style="font-size:12px; color: var(--muted); margin-bottom:6px;">Favorites</div>
    ${fmt("favorites", favs)}
    <div style="font-size:12px; color: var(--muted); margin:14px 0 6px;">Sonos playlists</div>
    ${fmt("playlists", plays)}
  `;
}

// ----- wiring -----

function wireGroup(el, g) {
  // Tabs
  el.querySelector(".tabs").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-tab]");
    if (!btn) return;
    const tab = btn.dataset.tab;
    tabState.set(g.coordinator, tab);
    el.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.tab === tab));
    el.querySelectorAll(".tab-panel").forEach(p => p.classList.toggle("active", p.dataset.panel === tab));
    loadTabContent(el, g, tab);
  });

  // Transport
  el.querySelector(".transport").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-act]");
    if (!btn) return;
    const act = btn.dataset.act;
    btn.disabled = true;
    try {
      await post(`/api/${g.coordinator}/${act}`);
      setTimeout(fetchState, 250);
    } catch (err) { setError(err); }
    finally { btn.disabled = false; }
  });

  // Seek bar
  const seek = el.querySelector(`input[data-seek="${cssEscape(g.coordinator)}"]`);
  if (seek && !seek.disabled) {
    seek.addEventListener("pointerdown", () => draggingControls.add(`seek:${g.coordinator}`));
    seek.addEventListener("change", async () => {
      draggingControls.delete(`seek:${g.coordinator}`);
      const seconds = parseInt(seek.value, 10);
      try {
        await post(`/api/${g.coordinator}/seek`, { position: secToHms(seconds) });
        setTimeout(fetchState, 200);
      } catch (err) { setError(err); }
    });
  }

  // Speakers tab volume sliders
  for (const range of el.querySelectorAll('input[data-vol]')) {
    const uuid = range.dataset.vol;
    const readout = el.querySelector(`[data-readout="${cssEscape(uuid)}"]`);
    range.addEventListener("pointerdown", () => draggingControls.add(`vol:${uuid}`));
    range.addEventListener("input", () => { readout.textContent = range.value; });
    range.addEventListener("change", () => {
      draggingControls.delete(`vol:${uuid}`);
      commitVolume(uuid, parseInt(range.value, 10));
    });
  }

  // Modes tab
  const modeSel = el.querySelector(`select[data-mode="${cssEscape(g.coordinator)}"]`);
  modeSel?.addEventListener("change", async () => {
    try { await post(`/api/${g.coordinator}/play_mode`, { mode: modeSel.value }); }
    catch (err) { setError(err); }
  });
  const cf = el.querySelector(`input[data-cf="${cssEscape(g.coordinator)}"]`);
  cf?.addEventListener("change", async () => {
    try { await post(`/api/${g.coordinator}/crossfade`, { on: cf.checked }); }
    catch (err) { setError(err); }
  });
  const sleepSet = el.querySelector(`button[data-sleep-set="${cssEscape(g.coordinator)}"]`);
  sleepSet?.addEventListener("click", async () => {
    const minutes = parseInt(el.querySelector(`input[data-sleep="${cssEscape(g.coordinator)}"]`).value || "0", 10);
    if (!minutes) return;
    try {
      await post(`/api/${g.coordinator}/sleep`, { seconds: minutes * 60 });
      setTimeout(fetchState, 250);
    } catch (err) { setError(err); }
  });
  const sleepClear = el.querySelector(`button[data-sleep-clear="${cssEscape(g.coordinator)}"]`);
  sleepClear?.addEventListener("click", async () => {
    try {
      await post(`/api/${g.coordinator}/sleep`, { seconds: 0 });
      setTimeout(fetchState, 250);
    } catch (err) { setError(err); }
  });

  // Group tab
  el.querySelector(`[data-everywhere="${cssEscape(g.coordinator)}"]`)?.addEventListener("click", async (e) => {
    e.target.disabled = true;
    try { await post(`/api/${g.coordinator}/group/everywhere`); setTimeout(fetchState, 400); }
    catch (err) { setError(err); }
    finally { e.target.disabled = false; }
  });
  el.querySelector(`[data-solo-coord="${cssEscape(g.coordinator)}"]`)?.addEventListener("click", async () => {
    // Force every non-coord member to unjoin
    for (const m of g.members) {
      if (m.uuid === g.coordinator || m.is_satellite) continue;
      try { await post(`/api/${m.uuid}/group/unjoin`); } catch (err) { setError(err); }
    }
    setTimeout(fetchState, 400);
  });
  for (const btn of el.querySelectorAll("[data-add-to]")) {
    btn.addEventListener("click", async () => {
      const target = btn.dataset.addUuid;
      const coord = btn.dataset.addTo;
      btn.disabled = true;
      try { await post(`/api/${target}/group/join`, { coordinator: coord }); setTimeout(fetchState, 300); }
      catch (err) { setError(err); }
      finally { btn.disabled = false; }
    });
  }
  for (const btn of el.querySelectorAll("[data-leave-uuid]")) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { await post(`/api/${btn.dataset.leaveUuid}/group/unjoin`); setTimeout(fetchState, 300); }
      catch (err) { setError(err); }
      finally { btn.disabled = false; }
    });
  }
}

function wireAudio(panel, g) {
  const slide = (selector, readoutAttr, endpoint) => {
    const el = panel.querySelector(selector);
    if (!el) return;
    const readout = panel.querySelector(`[data-readout-${readoutAttr}]`);
    el.addEventListener("input", () => { readout.textContent = el.value; });
    el.addEventListener("change", async () => {
      try { await post(`/api/${g.coordinator}/${endpoint}`, { value: parseInt(el.value, 10) }); }
      catch (err) { setError(err); }
    });
  };
  slide(`input[data-bass]`, "bass", "bass");
  slide(`input[data-treble]`, "treble", "treble");
  slide(`input[data-balance]`, "balance", "balance");
  const loud = panel.querySelector(`input[data-loud]`);
  loud?.addEventListener("change", async () => {
    try { await post(`/api/${g.coordinator}/loudness`, { on: loud.checked }); }
    catch (err) { setError(err); }
  });
}

function wireQueue(panel, g) {
  panel.addEventListener("click", async (e) => {
    const playBtn = e.target.closest("button[data-q-play]");
    const rmBtn = e.target.closest("button[data-q-rm]");
    const clearBtn = e.target.closest("button[data-q-clear]");
    const saveBtn = e.target.closest("button[data-q-save]");
    try {
      if (playBtn) {
        await post(`/api/${g.coordinator}/queue/play`, { position: parseInt(playBtn.dataset.qPlay, 10) });
        setTimeout(fetchState, 250);
      } else if (rmBtn) {
        await post(`/api/${g.coordinator}/queue/remove`, { position: parseInt(rmBtn.dataset.qRm, 10) });
        loadTabContent(panel.parentElement, g, "queue");
      } else if (clearBtn) {
        if (!confirm("Clear queue?")) return;
        await post(`/api/${g.coordinator}/queue/clear`);
        loadTabContent(panel.parentElement, g, "queue");
      } else if (saveBtn) {
        const titleInput = panel.querySelector("[data-q-save-title]");
        const title = (titleInput.value || "").trim();
        if (!title) { titleInput.focus(); return; }
        await post(`/api/${g.coordinator}/queue/save`, { title });
        titleInput.value = "";
      }
    } catch (err) { setError(err); }
  });
}

function wireFavorites(panel, g) {
  panel.addEventListener("click", async (e) => {
    const fav = e.target.closest("button[data-play-fav]");
    const pl = e.target.closest("button[data-play-pl]");
    const btn = fav || pl;
    if (!btn) return;
    const body = {
      uri: btn.dataset.uri,
      metadata: btn.dataset.meta,
      is_container: btn.dataset.container === "1",
    };
    btn.disabled = true;
    try {
      await post(`/api/${g.coordinator}/${fav ? "play_favorite" : "play_playlist"}`, body);
      setTimeout(fetchState, 400);
    } catch (err) { setError(err); }
    finally { btn.disabled = false; }
  });
}

// ----- volume queue (debounce per uuid) -----

let volumeQueue = new Map();
async function commitVolume(uuid, value) {
  volumeQueue.set(uuid, value);
  await new Promise((r) => setTimeout(r, 60));
  const v = volumeQueue.get(uuid);
  if (v !== value) return;
  volumeQueue.delete(uuid);
  try {
    await post(`/api/${uuid}/volume`, { volume: value });
  } catch (e) {
    setError(e);
  }
}

// ----- alarms drawer -----

$alarmsBtn.addEventListener("click", openAlarms);
$drawerClose.addEventListener("click", closeDrawer);
$overlay.addEventListener("click", closeDrawer);

function openAlarms() {
  $drawerTitle.textContent = "Alarms";
  $drawer.classList.remove("hidden");
  $overlay.classList.remove("hidden");
  refreshAlarms();
}

function closeDrawer() {
  $drawer.classList.add("hidden");
  $overlay.classList.add("hidden");
}

async function refreshAlarms() {
  $drawerBody.innerHTML = `<em class="fav-empty">Loading…</em>`;
  try {
    const { items } = await getJSON("/api/alarms");
    const speakers = (lastState?.groups || []).flatMap(g => g.members).filter(m => !m.is_satellite);
    const speakerByUuid = Object.fromEntries(speakers.map(s => [s.uuid, s]));
    $drawerBody.innerHTML = renderAlarmList(items, speakerByUuid) + renderAlarmForm(speakers);
    wireAlarmsDrawer(items, speakerByUuid);
  } catch (e) {
    $drawerBody.innerHTML = `<em class="fav-empty">Error: ${escapeHtml(e.message)}</em>`;
  }
}

function renderAlarmList(items, byUuid) {
  if (items.length === 0) return `<div class="fav-empty">No alarms.</div>`;
  return items.map(a => `
    <div class="alarm" data-id="${escapeAttr(a.id)}">
      <div class="alarm-head">
        <div class="alarm-time">${escapeHtml(a.start_time)}</div>
        <input type="checkbox" data-toggle="${escapeAttr(a.id)}" ${a.enabled ? "checked" : ""} />
      </div>
      <div class="alarm-meta">
        ${escapeHtml(byUuid[a.room_uuid]?.room_name || a.room_uuid || "?")}
        · ${escapeHtml(prettyRecurrence(a.recurrence))}
        · ${escapeHtml(a.play_mode)}
        · vol ${a.volume}
      </div>
      <div class="alarm-actions">
        <button data-delete="${escapeAttr(a.id)}" class="delete">Delete</button>
      </div>
    </div>
  `).join("");
}

function renderAlarmForm(speakers) {
  const favSlot = `<select data-form-fav><option value="">— pick a favorite (loaded after room) —</option></select>`;
  return `
    <div style="font-size:12px;color:var(--muted);margin:18px 0 6px;">New alarm</div>
    <div class="alarm-form">
      <label>Time</label>
      <input type="time" data-form-time value="07:00" step="60" />

      <label>Days</label>
      <select data-form-recurrence>
        <option value="DAILY">Every day</option>
        <option value="WEEKDAYS">Weekdays</option>
        <option value="WEEKENDS">Weekends</option>
        <option value="ONCE">Once</option>
      </select>

      <label>Room</label>
      <select data-form-room>
        ${speakers.map(s => `<option value="${escapeAttr(s.uuid)}">${escapeHtml(s.room_name)}</option>`).join("")}
      </select>

      <label>Volume</label>
      <input type="number" min="0" max="100" value="25" data-form-volume />

      <label>Music</label>
      ${favSlot}

      <div class="full">
        <button data-form-create>Create alarm</button>
      </div>
    </div>
  `;
}

function wireAlarmsDrawer(items, byUuid) {
  $drawerBody.querySelectorAll("[data-toggle]").forEach(cb => {
    cb.addEventListener("change", async () => {
      try {
        await patchJSON(`/api/alarms/${cb.dataset.toggle}`, { enabled: cb.checked });
      } catch (e) { setError(e); cb.checked = !cb.checked; }
    });
  });
  $drawerBody.querySelectorAll("[data-delete]").forEach(b => {
    b.addEventListener("click", async () => {
      if (!confirm("Delete this alarm?")) return;
      try {
        await del(`/api/alarms/${b.dataset.delete}`);
        refreshAlarms();
      } catch (e) { setError(e); }
    });
  });

  // Favorites loader: when room changes, fetch favorites from that speaker's group coord
  const room = $drawerBody.querySelector("[data-form-room]");
  const favSel = $drawerBody.querySelector("[data-form-fav]");
  const loadFavs = async () => {
    favSel.innerHTML = `<option value="">Loading…</option>`;
    const uuid = room.value;
    try {
      const { items } = await getJSON(`/api/${uuid}/favorites`);
      favSel.innerHTML = `<option value="">— none —</option>` + items.map(f =>
        `<option value="${escapeAttr(f.uri)}" data-meta="${escapeAttr(f.metadata || "")}">${escapeHtml(f.title)}</option>`
      ).join("");
    } catch (e) {
      favSel.innerHTML = `<option value="">(error)</option>`;
    }
  };
  if (room) {
    room.addEventListener("change", loadFavs);
    loadFavs();
  }

  $drawerBody.querySelector("[data-form-create]")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const time = $drawerBody.querySelector("[data-form-time]").value;
      const recurrence = $drawerBody.querySelector("[data-form-recurrence]").value;
      const room_uuid = $drawerBody.querySelector("[data-form-room]").value;
      const volume = parseInt($drawerBody.querySelector("[data-form-volume]").value, 10);
      const favOpt = favSel.options[favSel.selectedIndex];
      const program_uri = favSel.value;
      const program_metadata = favOpt?.dataset?.meta || "";
      await post("/api/alarms", {
        start_time: time + ":00",
        duration: "01:00:00",
        recurrence,
        enabled: true,
        room_uuid,
        program_uri,
        program_metadata,
        play_mode: "SHUFFLE",
        volume,
      });
      refreshAlarms();
    } catch (err) { setError(err); }
    finally { btn.disabled = false; }
  });
}

// ----- header buttons -----

$refresh.addEventListener("click", async () => {
  $refresh.disabled = true;
  $status.textContent = "Re-scanning…";
  try {
    await post("/api/refresh");
    await fetchState();
  } finally { $refresh.disabled = false; }
});

// ----- helpers -----

function setError(e) { $status.textContent = `Error: ${e.message}`; }

function escapeHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function escapeAttr(s) { return escapeHtml(s); }
function cssEscape(s) {
  return (window.CSS && CSS.escape) ? CSS.escape(s) : String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
}

function hmsToSec(hms) {
  if (!hms) return 0;
  const parts = String(hms).split(":").map(n => parseInt(n, 10) || 0);
  if (parts.length === 3) return parts[0]*3600 + parts[1]*60 + parts[2];
  if (parts.length === 2) return parts[0]*60 + parts[1];
  return 0;
}
function secToHms(s) {
  s = Math.max(0, Math.floor(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return `${h}:${String(m).padStart(2,"0")}:${String(ss).padStart(2,"0")}`;
}
function formatTime(s) {
  if (!s) return "0:00";
  const m = Math.floor(s / 60), ss = s % 60;
  return `${m}:${String(ss).padStart(2,"0")}`;
}
function prettyMode(m) {
  return {
    NORMAL: "Normal",
    REPEAT_ALL: "Repeat all",
    REPEAT_ONE: "Repeat one",
    SHUFFLE: "Shuffle + repeat",
    SHUFFLE_NOREPEAT: "Shuffle",
    SHUFFLE_REPEAT_ONE: "Shuffle + repeat one",
  }[m] || m;
}
function prettyRecurrence(r) {
  if (r === "DAILY") return "Every day";
  if (r === "WEEKDAYS") return "Weekdays";
  if (r === "WEEKENDS") return "Weekends";
  if (r === "ONCE") return "Once";
  return r;
}

// ----- bootstrap -----

fetchState();
setInterval(() => {
  if (draggingControls.size === 0) fetchState();
}, 2500);
