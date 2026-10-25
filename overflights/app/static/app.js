"use strict";

// Sequential blue ramp, steps 100-700 of the reference palette.
const BLUE = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
              "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"];
// Pass classes, in legend order. The colours are categorical slots 1-3.
const KINDS = [
  { id: "arrival", label: "Arrival", plural: "Arrivals" },
  { id: "departure", label: "Departure", plural: "Departures" },
  { id: "transit", label: "Transit", plural: "Transits" },
  { id: "unknown", label: "Unclassified", plural: "Unclassified" },
];
const KIND = Object.fromEntries(KINDS.map((k, i) => [k.id, { ...k, index: i }]));
// The map draws classes in this order, each on top of the last, so the
// fewer arrivals and departures stay visible over the transits.
const DRAW_ORDER = ["unknown", "transit", "arrival", "departure"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SVG_NS = "http://www.w3.org/2000/svg";

const $ = (sel) => document.querySelector(sel);

// ?theme=light or ?theme=dark overrides the system setting.
const forcedTheme = new URLSearchParams(location.search).get("theme");
if (forcedTheme === "light" || forcedTheme === "dark") document.documentElement.dataset.theme = forcedTheme;
const fmt = new Intl.NumberFormat("en-GB");
const fmt1 = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 1 });
const dateFmt = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit" });

const saved = {
  get(k) { try { return localStorage.getItem("overflights." + k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("overflights." + k, v); } catch { /* not available */ } },
};

const state = {
  info: null,
  passes: [],     // [id, ts, dist_m, alt_ft, flight, hex, kind] within the capture radius
  since: 0,
  tracks: new Map(),
  tablePasses: [], // the table's passes, before the radius filter
  tableLimit: 100,
  trackLimitHit: false,
};

// ---------- helpers ----------

function isDark() {
  const t = document.documentElement.dataset.theme;
  if (t) return t === "dark";
  return matchMedia("(prefers-color-scheme: dark)").matches;
}

function css(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Low values recede toward the surface: light end on a light page, dark end on a dark one.
function seqColor(v, max) {
  if (!v) return css("--empty");
  const ramp = isDark() ? BLUE.slice(0, 11).reverse() : BLUE.slice(1);
  const i = Math.min(ramp.length - 1, Math.floor((v / max) * ramp.length));
  return ramp[i];
}

function el(tag, attrs = {}, parent) {
  const node = tag in { svg: 1, rect: 1, text: 1, line: 1, g: 1 }
    ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "text") node.textContent = v;
    else node.setAttribute(k, v);
  }
  if (parent) parent.appendChild(node);
  return node;
}

async function getJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw Object.assign(new Error(`${path}: HTTP ${r.status}`), { status: r.status });
  return r.json();
}

// Home Assistant's ingress answers 401 when the page's session has expired,
// for example after the tab slept, and 502 while the App restarts.
function problem(err) {
  if (err.status === 401) return "This page's Home Assistant session has expired. Reload the page.";
  if (err.status >= 500) return "The App is not answering, perhaps because it is restarting. Trying again…";
  return "Cannot load data: " + err.message;
}

function km(m) { return fmt1.format(m / 1000) + " km"; }
function ft(a) { return a == null ? "–" : fmt.format(a) + " ft"; }
function hourLabel(h) { return String(h).padStart(2, "0") + ":00"; }
function radiusM() { return Number($("#radius").value) * 1000; }
function maxAlt() { return $("#max-alt").value; }
function kindFilter() { return $("#kind").value; }
function kindColor(kind) { return css("--" + kind); }

function startOfDay(ts) {
  const d = new Date(ts * 1000);
  d.setHours(0, 0, 0, 0);
  return d;
}

function filtered() {
  const r = radiusM();
  return state.passes.filter((p) => p[2] <= r);
}

// ---------- tooltip ----------

const tip = $("#tooltip");
function showTip(evt, value, label) {
  tip.replaceChildren(el("strong", { text: value }), document.createTextNode(label));
  tip.hidden = false;
  let x, y;
  if (evt.clientX !== undefined && evt.type !== "focus") {
    x = evt.clientX; y = evt.clientY;
  } else {
    const b = evt.target.getBoundingClientRect();
    x = b.right; y = b.top;
  }
  const w = tip.offsetWidth, h = tip.offsetHeight;
  tip.style.left = Math.min(x + 14, innerWidth - w - 8) + "px";
  tip.style.top = (y - h - 10 < 8 ? y + 16 : y - h - 10) + "px";
}
function hideTip() { tip.hidden = true; }
function hoverable(node, value, label) {
  node.setAttribute("tabindex", "0");
  node.setAttribute("aria-label", `${label}: ${value}`);
  node.addEventListener("pointermove", (e) => showTip(e, value, label));
  node.addEventListener("focus", (e) => showTip(e, value, label));
  node.addEventListener("pointerleave", hideTip);
  node.addEventListener("blur", hideTip);
}

// ---------- tiles ----------

function periodDays() {
  const now = state.info.now;
  return Math.max(1 / 24, (now - Math.max(state.since, state.info.first_ts || now)) / 86400);
}

function renderTiles(rows) {
  const box = $("#tiles");
  box.replaceChildren();
  const tile = (label, value, sub) => {
    const t = el("div", { class: "tile" }, box);
    el("div", { class: "label", text: label }, t);
    el("div", { class: "value", text: value }, t);
    if (sub) el("div", { class: "sub", text: sub }, t);
  };
  const days = periodDays();
  tile("Overflights", fmt.format(rows.length), `within ${km(radiusM())}`);
  tile("Per day", fmt1.format(rows.length / days), days < 1 ? "so far" : "on average");

  const byHour = new Array(24).fill(0);
  for (const p of rows) byHour[new Date(p[1] * 1000).getHours()]++;
  const top = byHour.indexOf(Math.max(...byHour));
  tile("Busiest hour", rows.length ? `${hourLabel(top)}–${hourLabel((top + 1) % 24)}` : "–",
       rows.length ? `${fmt.format(byHour[top])} overflights` : "");

  const withAlt = rows.filter((p) => p[3] != null);
  if (withAlt.length) {
    const low = withAlt.reduce((a, b) => (b[3] < a[3] ? b : a));
    tile("Lowest", ft(low[3]), `${low[4] || low[5]} · ${dateFmt.format(low[1] * 1000)}`);
  } else {
    tile("Lowest", "–");
  }
}

// ---------- week heatmap ----------

function weekdayCounts() {
  // How many of each weekday the period covers, to give a per-day rate.
  const counts = new Array(7).fill(0);
  const start = startOfDay(Math.max(state.since, state.info.first_ts || state.info.now));
  const end = new Date(state.info.now * 1000);
  for (const d = new Date(start); d <= end; d.setDate(d.getDate() + 1)) counts[(d.getDay() + 6) % 7]++;
  return counts;
}

function renderWeek(rows) {
  const box = $("#week");
  box.replaceChildren();
  const grid = Array.from({ length: 7 }, () => new Array(24).fill(0));
  for (const p of rows) {
    const d = new Date(p[1] * 1000);
    grid[(d.getDay() + 6) % 7][d.getHours()]++;
  }
  const max = Math.max(1, ...grid.flat());
  const ndays = weekdayCounts();

  const width = box.clientWidth || 800;
  const left = 36, top = 4, bottom = 20;
  const cw = (width - left) / 24, ch = Math.max(18, Math.min(30, cw * 0.8));
  const svg = el("svg", { width, height: top + ch * 7 + bottom, role: "img",
                          "aria-label": "Overflights by weekday and hour" }, box);
  for (let r = 0; r < 7; r++) {
    el("text", { x: left - 6, y: top + ch * r + ch / 2 + 4, "text-anchor": "end", text: DAYS[r] }, svg);
    for (let h = 0; h < 24; h++) {
      const v = grid[r][h];
      const cell = el("rect", { class: "cell", x: left + cw * h + 1, y: top + ch * r + 1,
        width: Math.max(1, cw - 2), height: ch - 2, rx: 2, fill: seqColor(v, max) }, svg);
      const rate = ndays[r] ? ` · ${fmt1.format(v / ndays[r])} per ${DAYS[r]}` : "";
      hoverable(cell, `${fmt.format(v)} overflights`, `${DAYS[r]} ${hourLabel(h)}–${hourLabel((h + 1) % 24)}${rate}`);
    }
  }
  for (let h = 0; h < 24; h += cw < 28 ? 3 : 1) {
    el("text", { x: left + cw * h + cw / 2, y: top + ch * 7 + 14, "text-anchor": "middle", text: hourLabel(h) }, svg);
  }

  const table = $("#week-table");
  table.replaceChildren();
  const head = el("tr", {}, el("thead", {}, table));
  el("th", { text: "Day" }, head);
  for (let h = 0; h < 24; h++) el("th", { text: String(h).padStart(2, "0") }, head);
  const body = el("tbody", {}, table);
  for (let r = 0; r < 7; r++) {
    const tr = el("tr", {}, body);
    el("td", { text: DAYS[r] }, tr);
    for (let h = 0; h < 24; h++) el("td", { text: grid[r][h] }, tr);
  }
}

// ---------- day x hour heatmap ----------

function renderDays(rows) {
  const box = $("#days");
  box.replaceChildren();
  const first = startOfDay(Math.max(state.since, state.info.first_ts || state.info.now));
  const days = [];
  for (const d = new Date(first); d.getTime() <= state.info.now * 1000; d.setDate(d.getDate() + 1)) {
    days.push(new Date(d));
  }
  const index = new Map(days.map((d, i) => [d.toDateString(), i]));
  const grid = days.map(() => new Array(24).fill(0));
  for (const p of rows) {
    const d = new Date(p[1] * 1000);
    const i = index.get(d.toDateString());
    if (i !== undefined) grid[i][d.getHours()]++;
  }
  const max = Math.max(1, ...grid.flat());

  const left = 36, top = 4, bottom = 20, ch = 12;
  const avail = (box.clientWidth || 800) - left;
  const cw = Math.max(4, Math.min(28, avail / days.length));
  const gap = cw > 6 ? 1 : 0.5;
  const svg = el("svg", { width: left + cw * days.length, height: top + ch * 24 + bottom, role: "img",
                          "aria-label": "Overflights by day and hour" }, box);
  for (let h = 0; h < 24; h += 3) {
    el("text", { x: left - 6, y: top + ch * h + ch / 2 + 4, "text-anchor": "end", text: hourLabel(h) }, svg);
  }
  days.forEach((d, i) => {
    for (let h = 0; h < 24; h++) {
      const v = grid[i][h];
      const cell = el("rect", { class: "cell", x: left + cw * i + gap, y: top + ch * h + gap,
        width: cw - 2 * gap, height: ch - 2 * gap, rx: cw > 6 ? 2 : 0, fill: seqColor(v, max) }, svg);
      hoverable(cell, `${fmt.format(v)} overflights`, `${dateFmt.format(d)}, ${hourLabel(h)}–${hourLabel((h + 1) % 24)}`);
    }
  });
  // Label the first day and each Monday, spaced so labels never collide.
  let lastX = -Infinity;
  days.forEach((d, i) => {
    const x = left + cw * i;
    if ((i === 0 || d.getDay() === 1) && x - lastX > 64 && x < left + cw * days.length - 40) {
      el("text", { x, y: top + ch * 24 + 14, text: dateFmt.format(d).replace(/^\w+ /, "") }, svg);
      lastX = x;
    }
  });
  box.scrollLeft = box.scrollWidth;
}

// ---------- closest-approach histogram ----------

function renderHist() {
  const box = $("#hist");
  box.replaceChildren();
  const cap = state.info.capture_radius_m;
  const bin = cap > 20000 ? 1000 : 500;
  const n = Math.ceil(cap / bin);
  const counts = new Array(n).fill(0);
  for (const p of state.passes) counts[Math.min(n - 1, Math.floor(p[2] / bin))]++;
  const max = Math.max(1, ...counts);
  const r = radiusM();

  const width = box.clientWidth || 800, height = 180;
  const left = 44, top = 8, bottom = 22, ph = height - top - bottom;
  const bw = (width - left - 20) / n;
  const svg = el("svg", { width, height, role: "img",
                          "aria-label": "Aircraft by distance at closest approach" }, box);
  const step = niceStep(max);
  for (let v = 0; v <= max; v += step) {
    const y = top + ph - (v / max) * ph;
    el("line", { x1: left, x2: left + bw * n, y1: y, y2: y, stroke: v ? css("--grid") : css("--axis") }, svg);
    el("text", { x: left - 6, y: y + 4, "text-anchor": "end", text: fmt.format(v) }, svg);
  }
  counts.forEach((v, i) => {
    const h = (v / max) * ph;
    const inside = (i + 1) * bin <= r;
    // A tall transparent hit area makes short bars easy to point at.
    const hit = el("rect", { class: "bar", x: left + bw * i, y: top, width: bw, height: ph, fill: "transparent" }, svg);
    if (v) {
      el("rect", { x: left + bw * i + 1, y: top + ph - h, width: Math.max(1, bw - 2), height: h,
                   rx: Math.min(2, bw / 4), fill: inside ? css("--series-1") : css("--other"),
                   "pointer-events": "none" }, svg);
    }
    hoverable(hit, `${fmt.format(v)} aircraft`, `closest point ${fmt1.format(i * bin / 1000)}–${fmt1.format((i + 1) * bin / 1000)} km`);
    hit.addEventListener("click", () => setRadius((i + 1) * bin / 1000));
    hit.addEventListener("keydown", (e) => { if (e.key === "Enter") setRadius((i + 1) * bin / 1000); });
  });
  const tickEvery = cap > 20000 ? 5000 : 2000;
  for (let m = 0; m <= cap; m += tickEvery) {
    el("text", { x: left + (m / bin) * bw, y: height - 6, "text-anchor": "middle", text: `${m / 1000} km` }, svg);
  }
  const rx = left + (r / bin) * bw;
  el("line", { x1: rx, x2: rx, y1: top, y2: top + ph, stroke: css("--text"), "stroke-width": 1.5,
               "stroke-dasharray": "4 3" }, svg);
}

function niceStep(max) {
  const raw = max / 4;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) || mag;
}

// ---------- map ----------

// The receiver cannot see aircraft low over the airport, so an arrival's
// track ends, and a departure's starts, some kilometres from the runway.
// The map joins that end to a runway end with a dashed line.
const LINK_MAX_M = 25000;
// Join only an aircraft within this angle of a runway's extended centreline.
// One that the receiver lost on a downwind or base leg has a turn still to
// fly, and a straight line would cross country it never flew over.
const LINK_MAX_ANGLE = Math.tan((25 * Math.PI) / 180);
const DASH = [6, 5];  // px on, px off

// Return the [lat, lon] that a track's open end joins, or null.
function runwayLink(kind, pts) {
  if ((kind !== "arrival" && kind !== "departure") || pts.length < 2) return null;
  const { airport, runways } = state.info;
  if (!airport) return null;
  const i = kind === "arrival" ? pts.length - 2 : 0;
  const p = [pts[i], pts[i + 1]];
  const kx = 111195 * Math.cos((p[0] * Math.PI) / 180), ky = 111195;
  const xy = (q) => [(q[1] - p[1]) * kx, (q[0] - p[0]) * ky];  // metres from p
  // Without runways, join the airport point.
  if (!runways.length) return Math.hypot(...xy(airport)) <= LINK_MAX_M ? airport : null;
  // On final approach or the initial climb, the aircraft is on a runway's
  // extended centreline, outside one of its ends. Pick the end with the
  // aircraft beyond it and nearest the centreline.
  let best = null, bestCross = Infinity;
  for (const [lat1, lon1, lat2, lon2] of runways) {
    for (const [end, other] of [[[lat1, lon1], [lat2, lon2]], [[lat2, lon2], [lat1, lon1]]]) {
      const [ex, ey] = xy(end), [ox, oy] = xy(other);
      const len = Math.hypot(ex - ox, ey - oy) || 1;
      const ux = (ex - ox) / len, uy = (ey - oy) / len;  // outward from this end
      const vx = -ex, vy = -ey;                            // from the end to the aircraft
      if (Math.hypot(vx, vy) > LINK_MAX_M) continue;
      const along = vx * ux + vy * uy, cross = Math.abs(vx * uy - vy * ux);
      if (along > 0 && cross <= along * LINK_MAX_ANGLE && cross < bestCross) { best = end; bestCross = cross; }
    }
  }
  return best;
}

// Tracks fade with age. Each bucket is [label, maximum age in seconds, opacity].
const AGES = [["Last day", 86400, 1], ["Last week", 7 * 86400, 0.6], ["Older", Infinity, 0.28]];
function ageOpacity(ts) {
  const age = Date.now() / 1000 - ts;
  return AGES.find(([, max]) => age <= max)[2];
}

// Each track is drawn 3 px wide: the pixel and its eight neighbours.
const BRUSH = [-1, 0, 1].flatMap((dy) => [-1, 0, 1].map((dx) => [dx, dy]));
function hexRGB(h) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); }

const DensityLayer = L.Layer.extend({
  onAdd(map) {
    this._map = map;
    this._canvas = L.DomUtil.create("canvas", "density");
    this._canvas.style.pointerEvents = "none";
    map.getPanes().overlayPane.appendChild(this._canvas);
    map.on("moveend resize", this.redraw, this);
    this.redraw();
  },
  onRemove(map) {
    L.DomUtil.remove(this._canvas);
    map.off("moveend resize", this.redraw, this);
  },
  setTracks(tracks) { this._tracks = tracks; this.redraw(); },  // id -> {kind, ts, pts, link}
  setHighlight(id) { this._highlight = id; this.redraw(); },
  setHidden(kinds) { this._hidden = kinds; this.redraw(); },  // a Set of kind ids

  redraw() {
    const map = this._map;
    if (!map) return;
    const size = map.getSize();
    const w = size.x, h = size.y;
    const canvas = this._canvas;
    canvas.width = w; canvas.height = h;
    canvas.style.width = w + "px"; canvas.style.height = h + "px";
    L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
    const ctx = canvas.getContext("2d");
    const tracks = this._tracks || new Map();
    if (!tracks.size) return;

    const scale = 256 * 2 ** map.getZoom();
    const origin = map.getPixelBounds().min;
    const px = (lon) => ((lon + 180) / 360) * scale - origin.x;
    const py = (lat) => {
      const s = Math.sin((lat * Math.PI) / 180);
      return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * scale - origin.y;
    };

    // For each class, keep the opacity of the newest track through each pixel.
    const grids = KINDS.map(() => new Float32Array(w * h));
    let kgrid, alpha;
    // Mark the pixels of one segment. A dashed segment counts its dashes from
    // (x0, y0), so the dashes of many tracks line up at the runway end.
    const segment = (x0, y0, x1, y1, dashed) => {
      if ((x0 < 0 && x1 < 0) || (y0 < 0 && y1 < 0) || (x0 >= w && x1 >= w) || (y0 >= h && y1 >= h)) return;
      const steps = Math.ceil(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0))) || 1;
      for (let k = 0; k <= steps; k++) {
        if (dashed && k % (DASH[0] + DASH[1]) >= DASH[0]) continue;
        const cx = Math.round(x0 + ((x1 - x0) * k) / steps), cy = Math.round(y0 + ((y1 - y0) * k) / steps);
        for (const [dx, dy] of BRUSH) {
          const x = cx + dx, y = cy + dy;
          if (x < 0 || y < 0 || x >= w || y >= h) continue;
          const idx = y * w + x;
          if (kgrid[idx] < alpha) kgrid[idx] = alpha;
        }
      }
    };
    const hidden = this._hidden || new Set();
    for (const { kind, ts, pts, link } of tracks.values()) {
      if (hidden.has(kind)) continue;
      kgrid = grids[KIND[kind].index];
      alpha = ageOpacity(ts);
      let x0, y0;
      for (let i = 0; i < pts.length; i += 2) {
        const x1 = px(pts[i + 1]), y1 = py(pts[i]);
        if (i > 0) segment(x0, y0, x1, y1, false);
        x0 = x1; y0 = y1;
      }
      if (link) {
        const i = kind === "arrival" ? pts.length - 2 : 0;
        segment(px(link[1]), py(link[0]), px(pts[i + 1]), py(pts[i]), true);
      }
    }

    // Each pixel takes the colour of the top class in DRAW_ORDER that has a
    // track through it, at the opacity of that class's newest track there.
    const topFirst = DRAW_ORDER.map((k) => KIND[k].index).reverse();
    const colors = KINDS.map((k) => hexRGB(kindColor(k.id)));
    const img = ctx.createImageData(w, h);
    for (let i = 0; i < w * h; i++) {
      let best = -1;
      for (const k of topFirst) if (grids[k][i]) { best = k; break; }
      if (best < 0) continue;
      const c = colors[best];
      const o = i * 4;
      img.data[o] = c[0]; img.data[o + 1] = c[1]; img.data[o + 2] = c[2];
      img.data[o + 3] = Math.round(255 * grids[best][i]);
    }
    ctx.putImageData(img, 0, 0);

    const t = this._highlight != null && tracks.get(this._highlight);
    if (t) {
      const hl = t.pts;
      ctx.lineWidth = 4;
      ctx.lineJoin = "round";
      ctx.strokeStyle = css("--text");
      ctx.beginPath();
      for (let i = 0; i < hl.length; i += 2) {
        const x = px(hl[i + 1]), y = py(hl[i]);
        if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y);
      }
      ctx.stroke();
      if (t.link) {
        const i = t.kind === "arrival" ? hl.length - 2 : 0;
        ctx.setLineDash(DASH);
        ctx.beginPath();
        ctx.moveTo(px(t.link[1]), py(t.link[0]));
        ctx.lineTo(px(hl[i + 1]), py(hl[i]));
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
  },
});

let map, density, radiusCircle;
// Classes that the map does not draw. The viewer toggles them in the legend.
const hiddenKinds = new Set((saved.get("hidden") || "").split(",").filter((k) => k in KIND));

function toggleKind(kind) {
  if (hiddenKinds.has(kind)) hiddenKinds.delete(kind); else hiddenKinds.add(kind);
  saved.set("hidden", [...hiddenKinds].join(","));
  density.setHidden(hiddenKinds);
  renderMapLegend();
}

function setupMap() {
  const home = state.info.home;
  // Quarter-level zoom steps, and half a level for each button press or
  // wheel notch, so zooming moves in small steps.
  map = L.map("map", { zoomAnimation: false, scrollWheelZoom: false,
                       zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 120 });
  const bounds = L.latLng(home).toBounds(2 * state.info.capture_radius_m);
  // Show the airport too, where arrivals and departures end.
  if (state.info.airport) bounds.extend(L.latLng(state.info.airport).toBounds(8000));
  map.fitBounds(bounds);
  // The App fetches each tile once and keeps it (see tiles.py).
  L.tileLayer("tiles/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(map);
  density = new DensityLayer().addTo(map);
  nowLayer = L.layerGroup().addTo(map);
  density.setHidden(hiddenKinds);
  radiusCircle = L.circle(home, { radius: radiusM(), color: css("--text-2"), weight: 1.5,
                                  dashArray: "5 4", fill: false, interactive: false }).addTo(map);
  L.circleMarker(home, { radius: 5, color: css("--surface"), weight: 2, fillColor: css("--text"),
                         fillOpacity: 1, interactive: false }).addTo(map);
  map.on("focus", () => map.scrollWheelZoom.enable());
  map.on("blur", () => map.scrollWheelZoom.disable());
}

function renderMapLegend() {
  const counts = Object.fromEntries(KINDS.map((k) => [k.id, 0]));
  for (const t of state.tracks.values()) counts[t.kind]++;
  const box = $("#map-legend");
  box.replaceChildren();
  for (const k of KINDS) {
    if (kindFilter() && kindFilter() !== k.id) continue;
    const shown = !hiddenKinds.has(k.id);
    const item = el("button", { type: "button", class: "key", "aria-pressed": String(shown),
                                title: `${shown ? "Hide" : "Show"} ${k.plural.toLowerCase()} on the map` }, box);
    el("span", { class: "swatch", style: `background: ${kindColor(k.id)}` }, item);
    item.append(`${k.plural} ${fmt.format(counts[k.id])}`);
    item.addEventListener("click", () => toggleKind(k.id));
  }
  let linked = false;
  for (const t of state.tracks.values()) if (t.link && !hiddenKinds.has(t.kind)) { linked = true; break; }
  const ages = el("span", { class: "ages", "aria-label": "Track age" }, box);
  for (const [label, , opacity] of AGES) {
    const key = el("span", { class: "age" }, ages);
    el("span", { class: "age-line", style: `opacity: ${opacity}` }, key);
    key.append(label);
  }
  el("span", { class: "muted-note", text: "Click a class to show or hide it. Older tracks are fainter." +
    (linked ? " Dashed: the path to or from the runway, below the receiver's view and estimated." : "") }, box);
  const n = state.tracks.size;
  let drawn = 0;
  for (const t of state.tracks.values()) if (!hiddenKinds.has(t.kind)) drawn++;
  const hiddenNote = drawn < n ? ` The map shows ${fmt.format(drawn)} of them.` : "";
  $("#map-note").textContent = n
    ? `Paths of the ${state.trackLimitHit ? "newest " : ""}${fmt.format(n)} aircraft that came within ${km(radiusM())}.${hiddenNote} Scroll to zoom after clicking the map.`
    : `No aircraft came within ${km(radiusM())} in this period.`;
}

// ---------- latest table ----------

const TABLE_PERIODS = { 3600: "in the last hour", 86400: "in the last day", 604800: "in the last week", 0: "since logging began" };

// The table has its own period. It reuses the page's passes when they cover
// that period, and otherwise asks the server with the same filters.
async function loadTable() {
  const secs = Number($("#table-period").value);
  const since = secs ? Math.floor(Date.now() / 1000 - secs) : 0;
  state.tableLimit = 100;
  if (since >= state.since) {
    state.tablePasses = state.passes.filter((p) => p[1] >= since);
  } else {
    state.tablePasses = (await getJSON("api/passes?" + query({ since }))).rows;
  }
}

function renderLatest() {
  const r = radiusM();
  const rows = state.tablePasses.filter((p) => p[2] <= r);
  const shown = rows.slice(-state.tableLimit).reverse();
  const period = TABLE_PERIODS[$("#table-period").value];
  $("#latest-note").textContent = rows.length > shown.length
    ? `The newest ${fmt.format(shown.length)} of ${fmt.format(rows.length)} overflights ${period}.`
    : `${fmt.format(rows.length)} overflight${rows.length === 1 ? "" : "s"} ${period}.`;
  $("#latest-more").hidden = rows.length <= shown.length;
  const table = $("#latest");
  table.replaceChildren();
  const head = el("tr", {}, el("thead", {}, table));
  for (const h of ["Time", "Flight", "Type", "Closest", "Altitude", ""]) el("th", { text: h }, head);
  const body = el("tbody", {}, table);
  for (const p of shown) {
    const [id, ts, dist, alt, flight, hex, kind] = p;
    const tr = el("tr", {}, body);
    const d = new Date(ts * 1000);
    el("td", { text: `${dateFmt.format(d)} ${timeFmt.format(d)}` }, tr);
    el("td", { text: flight || hex.toUpperCase() }, tr);
    const type = el("td", {}, tr);
    el("span", { class: "swatch", style: `background: ${kindColor(kind)}` }, type);
    type.append(KIND[kind].label);
    el("td", { text: km(dist) }, tr);
    el("td", { text: ft(alt) }, tr);
    const link = el("td", {}, tr);
    if (!hex.startsWith("~") && !hex.startsWith("zz")) {
      const day = d.toISOString().slice(0, 10);
      // Centre the map on the house, or it opens elsewhere until the trace loads.
      const [lat, lon] = state.info.home;
      el("a", { href: `https://globe.adsbexchange.com/?icao=${encodeURIComponent(hex)}&showTrace=${day}` +
                      `&lat=${lat.toFixed(3)}&lon=${lon.toFixed(3)}&zoom=9`,
                target: "_blank", rel: "noopener", text: "Trace" }, link);
    }
    tr.addEventListener("pointerenter", () => density.setHighlight(id));
    tr.addEventListener("pointerleave", () => density.setHighlight(null));
  }
  if (!rows.length) {
    el("td", { colspan: 6, class: "empty-note", text: `No overflights ${period}.` }, el("tr", {}, body));
  }
}

// ---------- overhead now ----------

let nowLayer;
function airportLabel(a) { return a.city && a.code ? `${a.code} ${a.city}` : a.code || a.name || "?"; }

function vertical(fpm) {
  if (fpm == null) return null;
  if (Math.abs(fpm) < 300) return "level";
  return `${fpm > 0 ? "climbing" : "descending"} ${fmt.format(Math.abs(Math.round(fpm / 100) * 100))} ft/min`;
}

// How long ago, in words: "3 min ago", "2 h 5 min ago", "yesterday 18:40".
function ago(ts, now) {
  const min = Math.max(0, Math.round((now - ts) / 60));
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  if (min < 24 * 60) return `${Math.floor(min / 60)} h ${min % 60} min ago`;
  return `${dateFmt.format(ts * 1000)} ${timeFmt.format(ts * 1000)}`;
}

// The card shows the aircraft overhead now. When there are none, it shows
// the last aircraft that came within the radius.
function renderNow(data) {
  const box = $("#now");
  box.replaceChildren();
  nowLayer.clearLayers();
  const area = `within ${km(data.radius_m)} of the house` +
    (data.max_alt_ft ? ` and below ${ft(data.max_alt_ft)}` : "");
  const live = data.receiving && data.aircraft.length > 0;
  $("#now-title").textContent = live || !data.last ? "Overhead now" : "Last overhead";
  if (!data.receiving) {
    el("p", { class: "muted", text: "The App is not receiving from the ADS-B receiver." }, box);
  }
  if (live) {
    for (const a of data.aircraft) planeRow(box, a, false);
  } else if (data.last) {
    el("p", { class: "muted", text: `Nothing ${area} now. The last aircraft that was:` }, box);
    planeRow(box, data.last, true, data.now);
  } else if (data.receiving) {
    el("p", { class: "muted", text: `Nothing overhead. Aircraft show here while they are ${area}.` }, box);
  }
}

// One aircraft. `past` is a logged pass, with figures for its closest point.
function planeRow(box, a, past, now) {
  const name = a.callsign || a.hex.toUpperCase();
  const row = el("div", { class: "plane" }, box);
  if (a.photo) {
    el("img", { src: a.photo, alt: `Photo of ${a.registration || name}`, loading: "lazy",
                referrerpolicy: "no-referrer" }, row);
  }
  const text = el("div", {}, row);
  const who = el("div", { class: "who", text: name }, text);
  if (a.registration && a.registration !== name) el("span", { class: "reg", text: a.registration }, who);
  const what = [a.airline || a.owner, a.type].filter(Boolean).join(" · ");
  if (what) el("div", { class: "line", text: what }, text);
  if (a.origin && a.destination) {
    const route = el("div", { class: "line", text: `${airportLabel(a.origin)} → ${airportLabel(a.destination)}` }, text);
    if (a.route_plausible === false) {
      el("div", { class: "route-doubt", text: "adsbdb.com gives this route, but it does not fit the aircraft's position, so it may be out of date." }, text);
      route.title = "The route may be out of date";
    }
  }
  const figures = el("div", { class: "figures" }, text);
  const shown = past
    ? [`${timeFmt.format(a.ts * 1000)}, ${ago(a.ts, now)}`, `closest ${km(a.distance_m)}`,
       `at ${ft(a.altitude_ft)}`, KIND[a.kind].label]
    : [ft(a.altitude_ft), vertical(a.vertical_fpm), a.speed_kt != null && `${fmt.format(a.speed_kt)} kt`,
       `${km(a.distance_m)} away`];
  for (const f of shown) if (f) el("span", { text: f }, figures);
  if (!a.hex.startsWith("~") && !a.hex.startsWith("zz")) {
    const day = new Date((past ? a.ts : now || Date.now() / 1000) * 1000).toISOString().slice(0, 10);
    el("a", { href: `https://globe.adsbexchange.com/?icao=${encodeURIComponent(a.hex)}` + (past ? `&showTrace=${day}` : ""),
              target: "_blank", rel: "noopener", text: past ? "Trace" : "Live track" }, figures);
  }
  // A logged pass is marked at its closest point, as a hollow ring.
  L.circleMarker([a.lat, a.lon], { radius: 6, color: past ? css("--text") : css("--surface"), weight: 2,
                                   fillColor: css("--text"), fillOpacity: past ? 0 : 1, interactive: false })
    .bindTooltip(name, { permanent: true, direction: "right", offset: [8, 0], className: "plane-label" })
    .addTo(nowLayer);
}

// The radius slider is shared: the App keeps its value, and the Overhead
// sensor uses it. A page follows a change made in another browser.
let nowSeq = 0;
async function pollNow() {
  if (expired) return;
  const seq = ++nowSeq;
  try {
    const data = await getJSON("api/now");
    if (seq !== nowSeq) return;
    if (!radiusTimer && Math.abs(data.radius_m - radiusM()) >= 1) {
      showRadius(data.radius_m);
    }
    renderNow(data);
  } catch (err) {
    $("#now").replaceChildren(el("p", { class: "muted", text: problem(err) }));
    if (err.status === 401) { expired = true; stopPolling(); }
  }
}

// ---------- data loading ----------

function query(extra = {}) {
  const p = new URLSearchParams({ since: state.since, ...extra });
  if (maxAlt()) p.set("max_alt", maxAlt());
  if (kindFilter()) p.set("kind", kindFilter());
  return p.toString();
}

async function loadPasses() {
  const period = Number($("#period").value);
  state.since = period ? Math.floor(Date.now() / 1000 - period * 86400) : 0;
  const data = await getJSON("api/passes?" + query());
  state.passes = data.rows;
}

let trackSeq = 0;
async function loadTracks() {
  const seq = ++trackSeq;
  const data = await getJSON("api/tracks?" + query({ radius: Math.round(radiusM()) }));
  if (seq !== trackSeq) return;
  const tracks = new Map();
  for (const [id, kind, ts, deltas] of data.tracks) {
    const pts = new Float64Array(deltas.length);
    let lat = 0, lon = 0;
    for (let i = 0; i < deltas.length; i += 2) {
      lat += deltas[i]; lon += deltas[i + 1];
      pts[i] = lat / 1e5; pts[i + 1] = lon / 1e5;
    }
    tracks.set(id, { kind, ts, pts, link: runwayLink(kind, pts) });
  }
  state.tracks = tracks;
  state.trackLimitHit = data.tracks.length >= data.limit;
  density.setTracks(tracks);
  renderMapLegend();
}

function renderAll() {
  const rows = filtered();
  renderTiles(rows);
  renderWeek(rows);
  renderDays(rows);
  renderHist();
  renderLatest();
  renderMapLegend();
  radiusCircle.setRadius(radiusM());
}

async function reload() {
  document.body.classList.add("loading");
  try {
    state.info = await getJSON("api/info");
    renderStatus();
    await loadPasses();
    await loadTable();
    renderAll();
    await loadTracks();
  } catch (err) {
    $("#status").textContent = problem(err);
  } finally {
    document.body.classList.remove("loading");
  }
}

let trackTimer, radiusTimer = null;
function setRadius(kmValue) {
  $("#radius").value = kmValue;
  onRadius();
}
// Redraw the page for the slider's radius.
function showRadius(m) {
  if (m !== undefined) $("#radius").value = m / 1000;
  $("#radius-out").textContent = km(radiusM());
  renderAll();
  clearTimeout(trackTimer);
  trackTimer = setTimeout(() => loadTracks().catch((err) => { $("#status").textContent = problem(err); }), 350);
}
// The viewer moved the slider. Send the new radius to the App once the
// slider stops, then refresh the Overhead now card.
function onRadius() {
  showRadius();
  clearTimeout(radiusTimer);
  radiusTimer = setTimeout(async () => {
    try {
      const r = await fetch("api/radius", { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify({ radius_m: Math.round(radiusM()) }) });
      if (!r.ok) throw Object.assign(new Error(`api/radius: HTTP ${r.status}`), { status: r.status });
    } catch (err) {
      $("#status").textContent = problem(err);
    }
    radiusTimer = null;
    pollNow();
  }, 400);
}

function renderStatus() {
  const i = state.info;
  const parts = [];
  if (i.last_error) parts.push(`Receiver not reachable: ${i.last_error}`);
  else if (i.last_poll_ok) parts.push(`Receiving · ${fmt.format(i.aircraft_now)} aircraft in range now`);
  parts.push(`${fmt.format(i.passes)} aircraft logged within ${km(i.capture_radius_m)}`);
  if (i.first_ts) parts.push(`since ${dateFmt.format(i.first_ts * 1000)}`);
  parts.push(`${fmt1.format(i.db_bytes / 1e6)} MB`);
  if (i.demo_passes) parts.push(`includes ${fmt.format(i.demo_passes)} demo passes`);
  $("#status").textContent = parts.join(" · ");
}

async function main() {
  state.info = await getJSON("api/info");
  const r = $("#radius");
  r.max = state.info.capture_radius_m / 1000;
  r.value = state.info.radius_m / 1000;
  if (saved.get("period")) $("#period").value = saved.get("period");
  const alt = saved.get("max_alt") ?? (state.info.default_max_alt_ft ? String(state.info.default_max_alt_ft) : "");
  $("#max-alt").value = alt;
  if ($("#max-alt").value !== alt) $("#max-alt").value = "";
  $("#radius-out").textContent = km(radiusM());
  const kind = saved.get("kind") || "";
  $("#kind").value = kind;
  if ($("#kind").value !== kind) $("#kind").value = "";

  const tablePeriod = saved.get("table_period");
  if (tablePeriod && tablePeriod in TABLE_PERIODS) $("#table-period").value = tablePeriod;

  setupMap();
  r.addEventListener("input", onRadius);
  $("#period").addEventListener("change", () => { saved.set("period", $("#period").value); reload(); });
  $("#max-alt").addEventListener("change", () => { saved.set("max_alt", $("#max-alt").value); reload(); });
  $("#kind").addEventListener("change", () => { saved.set("kind", $("#kind").value); reload(); });
  $("#table-period").addEventListener("change", async () => {
    saved.set("table_period", $("#table-period").value);
    try { await loadTable(); renderLatest(); } catch (err) { $("#latest-note").textContent = problem(err); }
  });
  $("#latest-more").addEventListener("click", () => { state.tableLimit += 100; renderLatest(); });

  let resizeTimer;
  addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(renderAll, 150); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    renderAll();
    density.redraw();
  });

  await reload();
  pollNow();
  startPolling();
  // A hidden tab does not poll, so a sleeping tab sends no requests.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPolling(); else { poll(); pollNow(); startPolling(); }
  });
}

let pollTimer = null, nowTimer = null, expired = false;
async function poll() {
  if (expired) return;
  try {
    state.info = await getJSON("api/info");
    renderStatus();
  } catch (err) {
    $("#status").textContent = problem(err);
    if (err.status === 401) { expired = true; stopPolling(); }
  }
}
// The receiver gives a new position every few seconds, so the Overhead now
// card asks every 5 seconds, and the status line every 30.
function startPolling() {
  if (expired) return;
  if (!pollTimer) pollTimer = setInterval(poll, 30000);
  if (!nowTimer) nowTimer = setInterval(pollNow, 5000);
}
function stopPolling() {
  clearInterval(pollTimer); clearInterval(nowTimer);
  pollTimer = nowTimer = null;
}

main().catch((err) => { $("#status").textContent = problem(err); });
