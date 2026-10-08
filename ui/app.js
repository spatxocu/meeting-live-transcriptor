const $ = (id) => document.getElementById(id);

let api = null;
let boot = null;
let meetings = [];
let current = null;
let status = { state: "idle", started: 0, busy: null, meeting_id: null };
let query = "";
let ticker = null;
let partials = {};
let toastTimer = null;

const clock = (seconds) => {
  const total = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${String(m).padStart(2, "0")}:${s}`;
};

const el = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

function toast(message) {
  const box = $("toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { box.hidden = true; }, 3200);
}

// ---- sidebar --------------------------------------------------------

function renderList() {
  const list = $("list");
  list.replaceChildren();
  if (!meetings.length) {
    list.append(el("div", "list-empty", query ? "Nothing matches that search." : "Your meetings will appear here."));
    return;
  }
  for (const meeting of meetings) {
    const item = el("div", "item" + (current && current.id === meeting.id ? " active" : ""));
    item.append(el("div", "t", meeting.title));
    const info = el("div", "m");
    const date = new Date(meeting.created);
    info.append(el("span", "", date.toLocaleDateString(undefined, { month: "short", day: "numeric" }) +
      ", " + date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })));
    if (status.meeting_id === meeting.id) info.append(el("span", "live", "recording"));
    else if (status.busy === meeting.id) info.append(el("span", "live", "transcribing"));
    else if (meeting.duration) info.append(el("span", "", clock(meeting.duration)));
    item.append(info);
    if (meeting.snippet) item.append(el("div", "s", meeting.snippet));
    item.onclick = () => select(meeting.id);
    list.append(item);
  }
}

async function refreshList() {
  meetings = await api.list_meetings(query);
  renderList();
}

// ---- meeting view ---------------------------------------------------

function highlighted(text) {
  const node = el("span", "line");
  const needle = query.trim().toLowerCase();
  const at = needle ? text.toLowerCase().indexOf(needle) : -1;
  if (at >= 0) {
    node.append(text.slice(0, at), el("mark", "", text.slice(at, at + needle.length)),
      text.slice(at + needle.length));
  } else {
    node.textContent = text;
  }
  return node;
}

// A section is one person's uninterrupted run of sentences.
function sections() {
  const result = [];
  current.segments.forEach((segment, index) => {
    const last = result[result.length - 1];
    if (last && last.speaker === segment.speaker) last.segments.push(segment);
    else result.push({ speaker: segment.speaker, first: index, segments: [segment] });
  });
  return result;
}

const sectionText = (section) => section.segments.map((s) => s.text).join(" ");

function sectionNode(section, partial = false) {
  const block = el("div", "turn" + (partial ? " partial" : ""));
  const head = el("div", "turn-head");
  head.append(el("span", "who " + section.speaker.toLowerCase().replace(/[^a-z]/g, ""), section.speaker));
  head.append(el("time", "", clock(section.segments[0].start)));
  if (!partial) {
    const copy = el("button", "copy-turn", "Copy");
    copy.title = "Copy this section";
    copy.onclick = () => copyText(sectionText(section), "Section copied");
    head.append(copy);
  }
  const body = el("p", "turn-body" + (current.audio_url && !partial ? " seekable" : ""));
  for (const segment of section.segments) {
    const line = highlighted(segment.text);
    line.dataset.start = segment.start;
    body.append(line, " ");
  }
  block.append(head, body);
  return block;
}

function renderPartials() {
  const scroller = $("transcript");
  const pinned = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  const rows = Object.values(partials).sort((a, b) => a.start - b.start)
    .map((partial) => sectionNode({ speaker: partial.speaker, segments: [partial] }, true));
  if (rows.length && !current.segments.length) $("segs").replaceChildren();
  $("live").replaceChildren(...rows);
  if (pinned) scroller.scrollTop = scroller.scrollHeight;
}

function renderTranscript(fromIndex = 0) {
  const scroller = $("transcript");
  const box = $("segs");
  const pinned = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 80;
  if (!current.segments.length) {
    const live = status.meeting_id === current.id;
    if (Object.keys(partials).length) { box.replaceChildren(); return; }
    box.replaceChildren(el("div", "transcript-empty", live
      ? "Listening… words appear as people speak."
      : status.busy === current.id ? "Transcribing…" : "No speech was transcribed in this meeting."));
    return;
  }
  if (box.firstChild && box.firstChild.classList.contains("transcript-empty")) box.replaceChildren();
  // Sections that end before the changed sentences are untouched; redraw the rest.
  const all = sections();
  let keep = 0;
  while (fromIndex > 0 && keep < all.length && all[keep].first + all[keep].segments.length < fromIndex) keep++;
  keep = Math.min(keep, box.children.length);
  while (box.children.length > keep) box.lastChild.remove();
  for (const section of all.slice(keep)) box.append(sectionNode(section));
  if (pinned && (fromIndex > 0 || status.meeting_id === current.id)) scroller.scrollTop = scroller.scrollHeight;
}

function renderMeta() {
  const date = new Date(current.created);
  const parts = [date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })];
  if (current.duration) parts.push(clock(current.duration));
  parts.push(`${current.segments.length} line${current.segments.length === 1 ? "" : "s"}`);
  if (current.source && current.source !== "recording") parts.push(current.source);
  $("meta").textContent = parts.join("  ·  ");
}

function renderButtons() {
  const live = current && status.meeting_id === current.id;
  const working = current && status.busy === current.id;
  $("improveBtn").disabled = !current || !current.can_improve || live || status.state !== "idle" || !!status.busy;
  $("deleteBtn").disabled = !current || live || working;
  $("copyBtn").disabled = !current || !current.segments.length;
  $("copyLastBtn").disabled = !current || !current.segments.length;
  document.querySelectorAll("[data-export]").forEach((b) => { b.disabled = !current || !current.segments.length; });
}

function renderDetail() {
  $("empty").hidden = !!current;
  $("detail").hidden = !current;
  if (!current) return;
  $("title").value = current.title;
  const player = $("player");
  if (current.audio_url) {
    if (player.dataset.id !== current.id || !player.src) {
      player.src = current.audio_url;
      player.dataset.id = current.id;
    }
    player.hidden = false;
  } else {
    player.pause();
    player.removeAttribute("src");
    player.dataset.id = "";
    player.hidden = true;
  }
  $("progress").hidden = true;
  renderMeta();
  renderTranscript();
  renderButtons();
}

async function select(id) {
  const meeting = id ? await api.get_meeting(id) : null;
  current = meeting;
  partials = {};
  $("live").replaceChildren();
  renderDetail();
  renderList();
}

function transcriptText() {
  return current.segments.map((s) => `[${clock(s.start)}] ${s.speaker}: ${s.text}`).join("\n");
}

function copyTranscript() {
  return copyText(transcriptText(), "Whole transcript copied");
}

function copyLatest() {
  const all = sections();
  const latest = all[all.length - 1];
  return copyText(sectionText(latest), `Copied what ${latest.speaker === "You" ? "you" : latest.speaker.toLowerCase()} said last`);
}

async function copyText(text, message) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (error) {
    const area = el("textarea");
    area.value = text;
    document.body.append(area);
    area.select();
    document.execCommand("copy");
    area.remove();
  }
  toast(message);
}

// ---- recording state ------------------------------------------------

function renderStatus() {
  const button = $("rec");
  const recording = status.state === "recording";
  button.classList.toggle("on", recording);
  button.disabled = status.state === "finishing" || (status.state === "idle" && !!status.busy);
  $("meters").hidden = !recording;
  clearInterval(ticker);
  const voice = boot.settings.voice_command;
  if (recording) {
    const tick = () => {
      $("recLabel").textContent = "Stop  " + clock(Date.now() / 1000 - status.started);
    };
    tick();
    ticker = setInterval(tick, 500);
    $("hint").textContent = voice ? 'Say "stop recording" or press Ctrl+Alt+R' : "Press Ctrl+Alt+R to stop";
  } else if (status.state === "finishing") {
    $("recLabel").textContent = "Finishing transcript…";
    $("hint").textContent = "Catching up on the last few sentences.";
  } else {
    $("recLabel").textContent = "Start recording";
    $("hint").textContent = status.busy ? "Transcribing a file…"
      : voice ? 'Say "start recording" or press Ctrl+Alt+R' : "Shortcut: Ctrl+Alt+R";
    $("meterMic").style.width = $("meterSystem").style.width = "0";
  }
  renderButtons();
}

function renderModel(model) {
  const banner = $("modelBanner");
  banner.classList.toggle("error", model.status === "error");
  banner.hidden = model.status === "ready";
  banner.textContent = model.status === "error"
    ? `Could not load the speech model "${model.name}". Check your internet connection and restart. ${model.error}`
    : `Preparing speech model "${model.name}"… the first run downloads it.`;
}

window.LT = {
  onEvent(kind, data) {
    if (!boot) return;
    if (kind === "status") {
      const was = status.meeting_id;
      status = data;
      renderStatus();
      renderList();
      if (data.meeting_id && data.meeting_id !== was) select(data.meeting_id);
    } else if (kind === "meetings") {
      refreshList();
    } else if (kind === "meeting") {
      if (current && current.id === data) select(data);
    } else if (kind === "segments") {
      if (current && current.id === data.id) {
        current.segments = current.segments.slice(0, data.offset).concat(data.tail);
        renderTranscript(data.offset);
        renderMeta();
        renderButtons();
      }
    } else if (kind === "partial") {
      if (!current || current.id !== data.id) return;
      if (data.text) partials[data.speaker] = data;
      else if (partials[data.speaker] && partials[data.speaker].start <= data.start + 0.01) delete partials[data.speaker];
      renderPartials();
    } else if (kind === "level") {
      const bar = data.source === "mic" ? $("meterMic") : $("meterSystem");
      bar.style.width = Math.min(100, Math.round(Math.sqrt(data.level) * 220)) + "%";
    } else if (kind === "model") {
      renderModel(data);
    } else if (kind === "progress") {
      if (current && current.id === data.id) {
        $("progress").hidden = data.value === null;
        if (data.value !== null) {
          const percent = Math.round(data.value * 100);
          $("progressBar").style.width = percent + "%";
          $("progressLabel").textContent = `Transcribing… ${percent}%`;
        }
      }
    } else if (kind === "toast") {
      toast(data);
    }
  },
};

// ---- wiring ---------------------------------------------------------

function fillSelect(select, options, value) {
  select.replaceChildren();
  for (const [id, label] of options) {
    const option = el("option", "", label);
    option.value = id;
    select.append(option);
  }
  select.value = value;
}

async function saveSettings(patch) {
  boot.settings = await api.set_settings(patch);
  renderStatus();
}

async function init() {
  api = window.pywebview.api;
  boot = await api.boot();
  meetings = boot.meetings;
  status = boot.status;

  fillSelect($("setLanguage"), [["auto", "Auto-detect"], ...boot.languages], boot.settings.language);
  fillSelect($("setLive"), boot.live_models.map((m) => [m.id, m.label]), boot.settings.live_model);
  fillSelect($("setHq"), boot.hq_models.map((m) => [m.id, m.label]), boot.settings.hq_model);
  $("setVoice").checked = boot.settings.voice_command;
  const fillMics = (names) => {
    const chosen = boot.settings.microphone;
    const options = [["default", "Windows default"], ...names.map((n) => [n, n])];
    if (chosen !== "default" && !names.includes(chosen)) options.push([chosen, chosen + " (not connected)"]);
    fillSelect($("setMic"), options, chosen);
  };
  fillMics(boot.microphones);
  $("setMic").onchange = (e) => saveSettings({ microphone: e.target.value });
  $("folderPath").textContent = boot.folder;

  $("rec").onclick = async () => {
    const result = status.state === "recording" ? await api.stop_recording() : await api.start_recording();
    if (result && result.error) toast(result.error);
  };
  let searchTimer = null;
  $("search").oninput = (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      query = event.target.value;
      refreshList();
      if (current) renderTranscript();
    }, 200);
  };
  $("importBtn").onclick = async () => {
    const result = await api.import_file();
    if (result.error) toast(result.error);
    if (result.ok) { await refreshList(); select(result.id); }
  };
  $("settingsBtn").onclick = async () => {
    $("settings").showModal();
    fillMics(await api.list_microphones());
  };
  $("setLanguage").onchange = (e) => saveSettings({ language: e.target.value });
  $("setLive").onchange = (e) => saveSettings({ live_model: e.target.value });
  $("setHq").onchange = (e) => saveSettings({ hq_model: e.target.value });
  $("setVoice").onchange = (e) => saveSettings({ voice_command: e.target.checked });
  $("openFolder").onclick = () => api.open_folder();

  const applyFolder = (result) => {
    if (result.error) toast(result.error);
    if (!result.ok) return false;
    boot.folder = result.folder;
    $("folderPath").textContent = result.folder;
    current = null;
    renderDetail();
    refreshList();
    toast(result.moved ? `Saving to ${result.folder}. Moved ${result.moved} meeting${result.moved === 1 ? "" : "s"} there.`
      : `Meetings will be saved in ${result.folder}`);
    return true;
  };
  $("changeFolder").onclick = async () => applyFolder(await api.choose_folder());
  if (boot.needs_folder) {
    const welcome = $("welcome");
    $("welcomePath").textContent = boot.default_folder;
    welcome.addEventListener("cancel", (event) => event.preventDefault());
    $("welcomeChoose").onclick = async () => { if (applyFolder(await api.choose_folder())) welcome.close(); };
    $("welcomeDefault").onclick = async () => { if (applyFolder(await api.set_folder(boot.default_folder))) welcome.close(); };
    welcome.showModal();
  }

  $("title").onchange = async (event) => {
    if (!current) return;
    const title = event.target.value.trim();
    if (!title) { event.target.value = current.title; return; }
    current.title = title;
    await api.rename_meeting(current.id, title);
    refreshList();
  };
  $("title").onkeydown = (event) => { if (event.key === "Enter") event.target.blur(); };
  $("copyBtn").onclick = copyTranscript;
  $("copyLastBtn").onclick = copyLatest;
  document.querySelectorAll("[data-export]").forEach((button) => {
    button.onclick = async () => {
      const result = await api.export_meeting(current.id, button.dataset.export);
      if (result.ok) toast("Saved to " + result.path);
    };
  });
  $("improveBtn").onclick = async () => {
    const result = await api.improve_meeting(current.id);
    if (result.error) toast(result.error);
  };
  $("deleteBtn").onclick = async () => {
    if (!confirm(`Delete "${current.title}" and its audio? This cannot be undone.`)) return;
    if (await api.delete_meeting(current.id)) {
      current = null;
      renderDetail();
      refreshList();
    }
  };

  const player = $("player");
  $("transcript").onclick = (event) => {
    const line = event.target.closest(".seekable .line");
    if (!line || !current.audio_url || window.getSelection().toString()) return;
    player.currentTime = Number(line.dataset.start);
    player.play();
  };
  player.ontimeupdate = () => {
    if (!current) return;
    const rows = $("segs").querySelectorAll(".line");
    let active = -1;
    current.segments.forEach((s, i) => { if (s.start <= player.currentTime + 0.1) active = i; });
    rows.forEach((row, i) => row.classList.toggle("playing", i === active && !player.paused));
  };

  $("rec").disabled = false;
  renderModel(boot.model);
  renderStatus();
  renderList();
  if (status.meeting_id) select(status.meeting_id);
}

window.addEventListener("pywebviewready", init);
