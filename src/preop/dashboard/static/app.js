"use strict";

const ITEMS = [
  { key: "activity", name: "Activity", max: 4, icon: "i-activity",
    low: "Looking around", high: "Trying to get away", missing: "No one in view" },
  { key: "vocalization", name: "Vocalization", max: 6, icon: "i-voice",
    low: "Talking or quiet", high: "Sustained crying", missing: "No sound input" },
  { key: "emotional_expressivity", name: "Emotional expressivity", max: 4, icon: "i-face",
    low: "Happy", high: "Extremely upset", missing: "No face in view" },
  { key: "state_of_arousal", name: "State of arousal", max: 4, icon: "i-arousal",
    low: "Alert", high: "Panicked", missing: "No signals" },
  { key: "use_of_parents", name: "Use of parents", max: 4, icon: "i-parents",
    low: "Doesn't need parent", high: "Clinging or pushing away", missing: "No second person in view" },
];
const SCORE_MIN = 23.33;
const SCORE_MAX = 100;
const CUTOFF = 30; // Commonly used mYPAS cut-off in the literature, shown for orientation only.
const TREND_WINDOW = 10; // Ticks.
const TREND_POINTS = 3;
const SVG = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch { /* Private windows can block storage. These are only conveniences. */ }
  return null;
}

function useIcon(id) {
  const svg = document.createElementNS(SVG, "svg");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG, "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  return svg;
}

function clock(seconds) {
  const total = Math.max(Math.round(seconds), 0);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

const state = {
  status: "idle",
  message: null,
  settings: {},
  history: [],
  lastScore: null,
  showingStart: false,
  cameraOn: store("lullaby.camera") !== "off",
  hover: null,
};

/* Critically damped springs. A new target keeps the current value and velocity, so values
   glide to each new reading instead of restarting. */
const springs = new Set();
let lastFrame = null;

function frame(now) {
  const dt = Math.min((now - (lastFrame ?? now)) / 1000, 1 / 30);
  lastFrame = now;
  for (const spring of springs) {
    const omega = (2 * Math.PI) / spring.response;
    spring.velocity += (-omega * omega * (spring.value - spring.target) - 2 * omega * spring.velocity) * dt;
    spring.value += spring.velocity * dt;
    if (Math.abs(spring.value - spring.target) < 0.002 && Math.abs(spring.velocity) < 0.002) {
      spring.value = spring.target;
      spring.velocity = 0;
      springs.delete(spring);
    }
    spring.apply(spring.value);
  }
  if (springs.size) requestAnimationFrame(frame);
  else lastFrame = null;
}

function makeSpring(apply, value = 0, response = 0.5) {
  const spring = { apply, value, target: value, velocity: 0, response };
  spring.to = (target) => {
    spring.target = target;
    if (reducedMotion.matches || document.hidden) {
      spring.value = target;
      spring.velocity = 0;
      springs.delete(spring);
      apply(target);
      return;
    }
    if (!springs.size) requestAnimationFrame(frame);
    springs.add(spring);
  };
  apply(value);
  return spring;
}

const gaugeSpring = makeSpring((share) => {
  $("gauge-fill").setAttribute("stroke-dasharray", `${Math.max(share * 100, 0).toFixed(2)} 100`);
});
const numberSpring = makeSpring((value) => {
  if (state.lastScore !== null) $("score-value").textContent = Math.round(value);
}, SCORE_MIN);

/* Five items */
const itemRows = new Map();
for (const item of ITEMS) {
  const li = document.createElement("li");
  const top = document.createElement("div");
  top.className = "item-top";
  const name = document.createElement("span");
  name.className = "item-name";
  name.textContent = item.name;
  const value = document.createElement("span");
  value.className = "item-value";
  top.append(useIcon(item.icon), name, value);
  const track = document.createElement("div");
  track.className = "track";
  const fill = document.createElement("div");
  fill.className = "track-fill";
  track.append(fill);
  const ends = document.createElement("div");
  ends.className = "ends";
  const low = document.createElement("span");
  low.textContent = item.low;
  const high = document.createElement("span");
  high.textContent = item.high;
  ends.append(low, high);
  li.append(top, track, ends);
  $("items").append(li);
  itemRows.set(item.key, {
    li, value,
    spring: makeSpring((share) => { fill.style.transform = `scaleX(${Math.max(share, 0)})`; }),
  });
}

function renderItems(tick) {
  for (const item of ITEMS) {
    const row = itemRows.get(item.key);
    const data = tick?.items?.[item.key];
    row.li.dataset.missing = String(!data);
    if (data) {
      row.value.textContent = `${data.rating.toFixed(1)} of ${item.max}`;
      row.spring.to((data.rating - 1) / (item.max - 1));
    } else {
      row.value.textContent = tick?.progress < 1 ? "After baseline" : item.missing;
      row.spring.to(0);
    }
  }
}

/* What it can see and hear */
function renderSignals(tick) {
  const s = tick?.signals;
  const rows = [
    ["Body", s?.people > 0, s?.people > 0 ? `Tracking${s.activity !== null ? `, moving ${s.activity.toFixed(2)}` : ""}` : "No one in view"],
    ["Second person", s?.people > 1, s?.people > 1 ? (s.parent_distance !== null ? `${s.parent_distance.toFixed(1)} body lengths away` : "In view") : "Not in view"],
    ["Face", s?.face, !s?.face_enabled ? "Off, OpenFace not running" : s.face ? "Found" : "Not found"],
    ["Voice", s?.voice, !s?.audio ? "No sound input" : `${s.voice ? "Heard" : "Quiet"}${s.dbfs !== null ? `, ${s.dbfs.toFixed(0)} dB` : ""}`],
    ["Heart rate", s?.heart_rate !== null && s?.heart_rate !== undefined && !s.heart_rate_simulated,
      s?.heart_rate_simulated ? "Simulated, not used" : s?.heart_rate ? `${s.heart_rate.toFixed(0)} bpm` : "Not connected"],
  ];
  const list = $("signals");
  list.replaceChildren(...rows.map(([name, on, text]) => {
    const li = document.createElement("li");
    li.dataset.on = String(Boolean(on));
    const label = document.createElement("span");
    label.className = "name";
    label.textContent = name;
    const value = document.createElement("span");
    value.className = "state";
    value.textContent = text;
    li.append(useIcon(on ? "i-check" : "i-dash"), label, value);
    return li;
  }));
}

/* Score */
function trend() {
  const scored = state.history.filter((tick) => tick.score !== null).map((tick) => tick.score);
  if (scored.length < TREND_WINDOW * 2) return null;
  const mean = (values) => values.reduce((a, b) => a + b, 0) / values.length;
  const change = mean(scored.slice(-TREND_WINDOW)) - mean(scored.slice(-TREND_WINDOW * 2, -TREND_WINDOW));
  if (change >= TREND_POINTS) return ["i-up", "Rising"];
  if (change <= -TREND_POINTS) return ["i-down", "Settling"];
  return ["i-flat", "Steady"];
}

function renderScore(tick) {
  const headline = $("score-headline");
  const sub = $("score-sub");
  const calibrating = !tick || tick.progress < 1;
  const scored = !calibrating && tick.score !== null;
  $("gauge-moon").toggleAttribute("hidden", scored);
  $("score-value").toggleAttribute("hidden", !scored);
  $("score-title").textContent = calibrating ? "Baseline" : "Distress score";

  if (state.status === "starting") {
    gaugeSpring.to(0);
    headline.replaceChildren("Waking up");
    sub.textContent = "Loading the models. This can take a moment.";
  } else if (calibrating && state.status === "running") {
    gaugeSpring.to(tick ? tick.progress : 0);
    headline.replaceChildren(`Learning what calm looks like, ${Math.round((tick?.progress ?? 0) * 100)}%`);
    sub.textContent = state.settings.source === "file"
      ? "Using the start of this video as the calm baseline."
      : "Sit calmly and say a few normal sentences.";
  } else if (calibrating) {
    gaugeSpring.to(0);
    headline.replaceChildren("Ended before the baseline finished");
    sub.textContent = "A score needs the full calm baseline first.";
  } else if (!scored) {
    headline.replaceChildren("Nothing to score right now");
    sub.textContent = "No signals are coming through.";
    gaugeSpring.to(0);
    state.lastScore = null;
  } else {
    if (state.lastScore === null) { numberSpring.value = tick.score; numberSpring.target = tick.score; }
    state.lastScore = tick.score;
    numberSpring.to(tick.score);
    gaugeSpring.to((tick.score - SCORE_MIN) / (SCORE_MAX - SCORE_MIN));
    const direction = trend();
    if (direction) headline.replaceChildren(trendNode(direction));
    else headline.replaceChildren("Just getting started");
    sub.textContent = `Confidence ${Math.round(tick.confidence * 100)}%. Lower when a signal can't be seen or heard.`;
  }
}

function trendNode([icon, word]) {
  const span = document.createElement("span");
  span.className = "trend score-headline";
  span.append(useIcon(icon), word);
  return span;
}

/* Chart: one series on one axis, with a crosshair on hover */
function el(name, attrs, text) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

function niceStep(seconds) {
  return [15, 30, 60, 120, 300, 600, 1200].find((step) => seconds / step <= 6) ?? 3600;
}

function chartScale() {
  const box = $("chart").getBoundingClientRect();
  const margin = { top: 12, right: 12, bottom: 24, left: 34 };
  const last = state.history.at(-1)?.t ?? 0;
  const domain = Math.max(last, 60, (state.settings.baseline_s ?? 0) * 1.5);
  const width = Math.max(box.width - margin.left - margin.right, 1);
  const height = Math.max(box.height - margin.top - margin.bottom, 1);
  return {
    box, margin, domain, width, height,
    x: (t) => margin.left + (t / domain) * width,
    y: (v) => margin.top + (1 - (v - 20) / 80) * height,
  };
}

function renderChart() {
  const host = $("chart");
  const scale = chartScale();
  if (scale.box.width < 10) return;
  const { x, y, margin, width, height, domain, box } = scale;
  const svg = el("svg", { viewBox: `0 0 ${box.width} ${box.height}`, role: "img",
    "aria-label": "Distress score over time. Use See the numbers for the values." });

  const calibrationEnd = state.history.find((tick) => tick.progress >= 1)?.t
    ?? (state.status === "running" || state.status === "starting" ? state.settings.baseline_s : state.history.at(-1)?.t) ?? 0;
  if (calibrationEnd > 0) {
    const bandWidth = Math.min(x(calibrationEnd), margin.left + width) - margin.left;
    svg.append(el("rect", { class: "baseline-band", x: margin.left, y: margin.top, width: bandWidth, height, rx: 8 }));
    if (bandWidth > 90) svg.append(el("text", { x: margin.left + 10, y: margin.top + 20 }, "Calm baseline"));
  }
  for (const value of [25, 50, 75, 100]) {
    svg.append(el("line", { class: "grid", x1: margin.left, x2: margin.left + width, y1: y(value), y2: y(value) }));
    svg.append(el("text", { x: margin.left - 8, y: y(value) + 4, "text-anchor": "end" }, value));
  }
  svg.append(el("line", { class: "ref", x1: margin.left, x2: margin.left + width, y1: y(CUTOFF), y2: y(CUTOFF) }));
  svg.append(el("text", { x: margin.left + width, y: y(CUTOFF) - 6, "text-anchor": "end" }, width < 420 ? "30" : "30, a common cut-off"));
  const step = niceStep(domain);
  for (let t = 0; t <= domain; t += step) {
    svg.append(el("text", { x: x(t), y: margin.top + height + 18, "text-anchor": t === 0 ? "start" : "middle" }, clock(t)));
  }

  let path = "";
  let open = false;
  let last = null;
  for (const tick of state.history) {
    if (tick.score === null) { open = false; continue; }
    path += `${open ? "L" : "M"}${x(tick.t).toFixed(1)} ${y(tick.score).toFixed(1)}`;
    open = true;
    last = tick;
  }
  if (path) svg.append(el("path", { class: "line", d: path }));
  if (last) svg.append(el("circle", { class: "last", cx: x(last.t), cy: y(last.score), r: 5 }));

  if (state.hover !== null) {
    const scored = state.history.filter((tick) => tick.score !== null);
    const time = ((state.hover - margin.left) / width) * domain;
    const near = scored.reduce((best, tick) => (!best || Math.abs(tick.t - time) < Math.abs(best.t - time) ? tick : best), null);
    if (near) {
      svg.append(el("line", { class: "cross", x1: x(near.t), x2: x(near.t), y1: margin.top, y2: margin.top + height }));
      svg.append(el("circle", { class: "last", cx: x(near.t), cy: y(near.score), r: 5 }));
      const tip = document.createElement("div");
      tip.className = "tooltip";
      tip.textContent = `${clock(near.t)}  ·  Score ${near.score.toFixed(0)}  ·  Confidence ${Math.round(near.confidence * 100)}%`;
      host.replaceChildren(svg, tip);
      const room = box.width - tip.offsetWidth - 4;
      tip.style.left = `${Math.max(Math.min(x(near.t) - tip.offsetWidth / 2, room), 4)}px`;
      return;
    }
  }
  host.replaceChildren(svg);
}

$("chart").addEventListener("pointermove", (event) => {
  state.hover = event.clientX - $("chart").getBoundingClientRect().left;
  renderChart();
});
$("chart").addEventListener("pointerleave", () => { state.hover = null; renderChart(); });
new ResizeObserver(() => renderChart()).observe($("chart"));

function renderNumbers() {
  if (!document.querySelector(".numbers").open) return;
  const rows = state.history.filter((tick) => tick.score !== null).slice(-12).reverse();
  $("numbers-body").replaceChildren(...rows.map((tick) => {
    const tr = document.createElement("tr");
    for (const text of [clock(tick.t), tick.score.toFixed(1), `${Math.round(tick.confidence * 100)}%`]) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.append(td);
    }
    return tr;
  }));
}
document.querySelector(".numbers").addEventListener("toggle", renderNumbers);

/* Camera */
function renderCamera() {
  const live = state.status === "running" || state.status === "starting";
  const on = state.cameraOn && live;
  const image = $("camera");
  $("camera-frame").dataset.on = String(on);
  $("camera-toggle").textContent = state.cameraOn ? "Hide" : "Show";
  $("camera-toggle").hidden = !live;
  $("camera-title").textContent = state.settings.source === "file" ? "Video" : "Camera";
  $("camera-empty").textContent = live ? "View is hidden" : "Session ended";
  if (on && !image.getAttribute("src")) image.src = `video.mjpeg?${Date.now()}`;
  if (!on && image.getAttribute("src")) image.removeAttribute("src");
}

$("camera-toggle").addEventListener("click", () => {
  state.cameraOn = !state.cameraOn;
  store("lullaby.camera", state.cameraOn ? "on" : "off");
  renderCamera();
});
$("camera").addEventListener("error", () => {
  $("camera").removeAttribute("src");
  if (state.status === "starting" || state.status === "running") setTimeout(renderCamera, 1000);
});

/* Page state */
const STATUS = {
  starting: ["i-dash", "Starting", ""],
  finished: ["i-check", "Finished", ""],
  stopped: ["i-check", "Stopped", ""],
  error: ["i-alert", "Something went wrong", "alert"],
};

function renderStatus(tick) {
  const pill = $("status");
  const live = state.status === "running";
  const spec = live
    ? tick && tick.progress < 1
      ? ["i-dash", "Calibrating", ""]
      : ["i-check", state.settings.source === "file" ? "Replaying" : "Live", "live"]
    : STATUS[state.status];
  pill.hidden = !spec || state.showingStart;
  if (spec) {
    pill.dataset.tone = spec[2];
    pill.replaceChildren(useIcon(spec[0]), spec[1]);
  }
  const active = state.status === "starting" || live;
  $("stop").hidden = !active || state.showingStart;
  $("new").hidden = active || state.status === "idle" || state.showingStart;
}

function renderNotice(tick) {
  const notice = $("session-notice");
  let text = null;
  if (state.message) text = state.message;
  else if (tick?.upset?.length) {
    text = `Already looked upset during the baseline (${tick.upset.join(", ")}). Scores may read low.`;
  }
  notice.hidden = !text;
  if (text) notice.replaceChildren(useIcon("i-alert"), text);
}

function render() {
  const tick = state.history.at(-1);
  const hasSession = state.status !== "idle";
  const showStart = !hasSession || state.showingStart;
  $("start").hidden = !showStart;
  $("session").hidden = showStart;
  $("back").hidden = !hasSession;
  renderStatus(tick);
  if (showStart) return;
  const name = state.settings.source === "file" ? state.settings.name : "Camera and mic";
  $("session-name").textContent = name ?? "";
  renderNotice(tick);
  renderScore(tick);
  renderItems(tick);
  renderSignals(tick);
  renderChart();
  renderNumbers();
  renderCamera();
}

/* Updates from the server */
function connect() {
  const socket = new WebSocket(`ws://${location.host}/ws`);
  socket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    if (message.type === "tick") {
      state.history.push(message.tick);
    } else {
      const startedHere = state.status !== message.status && (message.status === "starting");
      Object.assign(state, {
        status: message.status,
        message: message.message,
        settings: message.settings,
        history: message.history,
      });
      if (startedHere) { state.showingStart = false; state.lastScore = null; }
    }
    render();
  };
  socket.onclose = () => setTimeout(connect, 1000);
}

/* Start screen */
const form = $("start-form");

function baselineHint() {
  const file = form.elements.source.value === "file";
  $("path-field").hidden = !file;
  $("baseline-hint").textContent = file
    ? "The start of the video must be calm for this long."
    : "Sit calmly and say a few normal sentences for this long.";
}
form.addEventListener("change", baselineHint);

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = $("start-error");
  const button = $("start-button");
  error.hidden = true;
  button.disabled = true;
  const source = form.elements.source.value;
  const path = $("path").value.trim();
  if (source === "file") store("lullaby.path", path);
  try {
    const response = await fetch("api/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ source, path: source === "file" ? path : null, baseline_s: Number(form.elements.baseline.value) }),
    });
    if (!response.ok) {
      const body = await response.json();
      throw new Error(typeof body.detail === "string" ? body.detail : "That didn't work. Please try again.");
    }
    state.showingStart = false;
    render();
  } catch (problem) {
    error.replaceChildren(useIcon("i-alert"), problem.message);
    error.hidden = false;
  } finally {
    button.disabled = false;
  }
});

$("stop").addEventListener("click", () => fetch("api/session/stop", { method: "POST" }));
$("new").addEventListener("click", () => { state.showingStart = true; render(); });
$("back").addEventListener("click", () => { state.showingStart = false; render(); });

fetch("api/defaults").then((response) => response.json()).then((defaults) => {
  const remembered = store("lullaby.path");
  $("path").value = defaults.video ?? remembered ?? "";
  if (defaults.video) {
    form.elements.source.value = "file";
    form.elements.baseline.value = "30";
  }
  baselineHint();
});
baselineHint();
render();
connect();
