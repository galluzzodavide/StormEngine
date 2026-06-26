/* ==========================================
   StormEngine — Vanilla Leaflet Pro UI (EN)
   - Basemap: OSM / Esri World Imagery / (opt) Bing Aerial
   - AIS with default Leaflet marker + red route
   - Open-Meteo precipitation dots (blue→red), storms & extremes
   ========================================== */

/** >>> Optional: add your Bing Maps key to enable the “Bing” basemap */
const BING_KEY = ""; // e.g., "Axxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

/* ---------- MAP ---------- */
const map = L.map("map", { zoomControl: false }).setView([45.6, 13.2], 8);
L.control.zoom({ position: "topright" }).addTo(map);
L.control.scale({ metric: true, imperial: false, position: "bottomright" }).addTo(map);

// Labels pane above satellite
map.createPane("labels");
map.getPane("labels").style.zIndex = 650;
map.getPane("labels").style.pointerEvents = "none";

/* ---------- BASEMAPS ---------- */
const osmLayer = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: "© OpenStreetMap contributors",
});

const esriImagery = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
  {
    maxZoom: 19,
    attribution:
      "Tiles © Esri — Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community",
  }
);

const esriLabels = L.tileLayer(
  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_And_Places/MapServer/tile/{z}/{y}/{x}",
  { pane: "labels" }
);
const satelliteGroup = L.layerGroup([esriImagery, esriLabels]);

// Bing Aerial (quadkey)
function tileXYToQuadKey(x, y, z) {
  let q = "";
  for (let i = z; i > 0; i--) {
    let d = 0;
    const m = 1 << (i - 1);
    if ((x & m) !== 0) d++;
    if ((y & m) !== 0) d += 2;
    q += d.toString();
  }
  return q;
}
const BingLayer = L.TileLayer.extend({
  getTileUrl: function (coords) {
    const { x, y, z } = coords;
    const q = tileXYToQuadKey(x, y, z);
    const subs = this.options.subdomains || ["t0", "t1", "t2", "t3", "t4"];
    const s = subs[Math.floor(Math.random() * subs.length)];
    return `https://${s}.tiles.virtualearth.net/tiles/a${q}.jpeg?g=1&mkt=en-US&key=${this.options.key}`;
  },
});
const bingLayer =
  BING_KEY && BING_KEY.length > 10
    ? new BingLayer("", {
        key: BING_KEY,
        maxZoom: 19,
        subdomains: ["t0", "t1", "t2", "t3", "t4"],
        attribution:
          '© <a href="https://www.microsoft.com/maps/product/terms.html" target="_blank">Microsoft Bing</a>',
      })
    : null;

// Default: Satellite
let currentBase = satelliteGroup.addTo(map);

// Basemap toggles
function setBase(which) {
  if (currentBase) map.removeLayer(currentBase);
  if (which === "osm") currentBase = osmLayer.addTo(map);
  else if (which === "bing" && bingLayer) currentBase = bingLayer.addTo(map);
  else currentBase = satelliteGroup.addTo(map);
  document.getElementById("baseOSM").checked = which === "osm";
  document.getElementById("baseSAT").checked = which === "sat";
  if (document.getElementById("baseBING")) {
    document.getElementById("baseBING").checked = which === "bing";
  }
}
document.getElementById("baseOSM").addEventListener("change", () => setBase("osm"));
document.getElementById("baseSAT").addEventListener("change", () => setBase("sat"));
const bingRadio = document.getElementById("baseBING");
if (bingRadio) {
  if (!bingLayer) {
    bingRadio.disabled = true;
    bingRadio.title = "Add BING_KEY in main.js to enable";
  } else {
    bingRadio.addEventListener("change", () => setBase("bing"));
  }
}

/* ---------- OVERLAYS ---------- */
const aisGroup = L.layerGroup().addTo(map);
let pointsLayer = L.layerGroup().addTo(map);  // precipitation dots
let stormsLayer = L.layerGroup().addTo(map);  // strong thunderstorms
let extremeLayer = L.layerGroup().addTo(map); // extreme events

/* ---------- AIS (default markers + red route) ---------- */
const ships = {}; // mmsi -> { marker, polyline, path }
let selectedMMSI = null;
let followMarker = null;
let followSquare = null;

function shipPopup(mmsi, name, type) {
  return `<b>Name:</b> ${name}<br><b>MMSI:</b> ${mmsi}<br><b>Type:</b> ${type}`;
}

function drawFollowSquare(lat, lng) {
  const side = 0.036; // ~4 km
  const b = [
    [lat - side / 2, lng - side / 2],
    [lat - side / 2, lng + side / 2],
    [lat + side / 2, lng + side / 2],
    [lat + side / 2, lng - side / 2],
  ];
  if (followSquare) map.removeLayer(followSquare);
  followSquare = L.polygon(b, { color: "#2563eb", fillColor: "#3b82f6", fillOpacity: 0.2 }).addTo(map);
}

document.getElementById("selectShipBtn").onclick = function () {
  selectedMMSI = (document.getElementById("mmsiInput").value || "").trim() || null;
};

async function updateShips() {
  try {
    const res = await fetch("/navi");
    const data = await res.json();
    let selectedShipRecord = null;

    data.forEach((ship) => {
      const { mmsi, lat, lon, name = "N/A", type = "Unknown" } = ship;
      if (lat == null || lon == null) return;
      const key = String(mmsi);
      const latlng = [lat, lon];

      if (!ships[key]) {
        const marker = L.marker(latlng).addTo(aisGroup).bindPopup(shipPopup(mmsi, name, type));
        const polyline = L.polyline([latlng], { color: "#ef4444", weight: 2, opacity: 0.95 }).addTo(aisGroup); // RED route
        ships[key] = { marker, polyline, path: [latlng] };
      } else {
        const ctx = ships[key];
        ctx.path.push(latlng);
        ctx.marker.setLatLng(latlng).bindPopup(shipPopup(mmsi, name, type));
        ctx.polyline.setLatLngs(ctx.path); // stays aligned with marker path
      }

      if (selectedMMSI && key === selectedMMSI) selectedShipRecord = ship;
    });

    // visually prioritize selected ship (z-index)
    Object.entries(ships).forEach(([key, ctx]) => {
      ctx.marker.setZIndexOffset(selectedMMSI === key ? 1000 : 0);
    });

    // center & square on followed ship
    if (selectedShipRecord) {
      const { lat, lon } = selectedShipRecord;
      if (!followMarker) followMarker = L.marker([lat, lon], { zIndexOffset: 1100 }).addTo(map);
      followMarker.setLatLng([lat, lon]);
      drawFollowSquare(lat, lon);
      map.setView([lat, lon], Math.max(map.getZoom(), 14));
    }
  } catch (e) {
    // ignore fetch errors
  }
}

async function updateSelectedShip() {
  if (!selectedMMSI) return;
  try {
    const res = await fetch(`/get_ship_position?mmsi=${encodeURIComponent(String(selectedMMSI))}`);
    const pos = await res.json();
    if (pos.error) return;
    const { lat, lng } = pos;
    if (!followMarker) followMarker = L.marker([lat, lng], { zIndexOffset: 1100 }).addTo(map);
    else followMarker.setLatLng([lat, lng]);
    drawFollowSquare(lat, lng);
  } catch (e) {}
}
setInterval(updateShips, 5000);
setInterval(updateSelectedShip, 5000);

/* ---------- WEATHER (blue → red dots) ---------- */
const AREA = { latMin: 45.0, latMax: 46.0, lonMin: 12.0, lonMax: 14.0 };
function stepForZoom(z) {
  if (z >= 11) return 0.1;
  if (z >= 10) return 0.15;
  if (z >= 9) return 0.2;
  return 0.25;
}

const CLIENT_CACHE_TTL = 9 * 60 * 1000;
const omCache = new Map();
let omTimesRef = null;

let omOpacity = 0.95;
let sizeBoost = 1.6;
let omTimer = null;

const omHour = document.getElementById("omHour");
const omHourLabel = document.getElementById("omHourLabel");
const omAutoplay = document.getElementById("omAutoplay");
const omStatus = document.getElementById("omStatus");
const omOpacityInp = document.getElementById("omOpacity");
const omOpacityVal = document.getElementById("omOpacityVal");
const sizeBoostInp = document.getElementById("omSizeBoost");
const sizeBoostVal = document.getElementById("omSizeBoostVal");
const toggleStorms = document.getElementById("toggleStorms");
const toggleExtreme = document.getElementById("toggleExtreme");

// Gradient blue→red
const BR_STOPS = [
  [0.0, "#2c7fb8"],
  [0.25, "#7fcdbb"],
  [0.5, "#ffffbf"],
  [0.75, "#fdae61"],
  [1.0, "#d7301f"],
];
function hexToRgb(h) {
  const s = h.replace("#", "");
  return [parseInt(s.slice(0, 2), 16), parseInt(s.slice(2, 4), 16), parseInt(s.slice(4, 6), 16)];
}
function rgbToHex([r, g, b]) {
  return "#" + [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}
function mix(a, b, t) { return a + (b - a) * t; }
function interpStops(t, stops) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 0; i < stops.length - 1; i++) {
    const [p1, c1] = stops[i], [p2, c2] = stops[i + 1];
    if (t >= p1 && t <= p2) {
      const tt = (t - p1) / (p2 - p1);
      const [r1, g1, b1] = hexToRgb(c1);
      const [r2, g2, b2] = hexToRgb(c2);
      return rgbToHex([Math.round(mix(r1, r2, tt)), Math.round(mix(g1, g2, tt)), Math.round(mix(b1, b2, tt))]);
    }
  }
  return stops[stops.length - 1][1];
}

// Visible grid helpers
function clamp(v, a, b) { return Math.min(b, Math.max(a, v)); }
function ceilToStep(v, step) { return Math.ceil(v / step) * step; }
function floorToStep(v, step) { return Math.floor(v / step) * step; }
function visibleGrid(step, paddingDeg = 0.05) {
  const b = map.getBounds();
  let south = clamp(b.getSouth() - paddingDeg, AREA.latMin, AREA.latMax);
  let north = clamp(b.getNorth() + paddingDeg, AREA.latMin, AREA.latMax);
  let west  = clamp(b.getWest()  - paddingDeg, AREA.lonMin, AREA.lonMax);
  let east  = clamp(b.getEast()  + paddingDeg, AREA.lonMin, AREA.lonMax);

  south = ceilToStep(south, step);
  west  = ceilToStep(west,  step);
  north = floorToStep(north, step);
  east  = floorToStep(east,  step);

  const coords = [];
  for (let lat = south; lat <= north + 1e-9; lat = +(lat + step).toFixed(4)) {
    for (let lon = west; lon <= east + 1e-9; lon = +(lon + step).toFixed(4)) {
      coords.push([+lat.toFixed(4), +lon.toFixed(4)]);
    }
  }
  return coords;
}

// Server proxy with cache
async function fetchPoint(lat, lon) {
  const url = `/openmeteo?lat=${lat}&lon=${lon}`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error("HTTP " + resp.status);
  const j = await resp.json();
  return {
    time: j.hourly.time,
    precip: j.hourly.precipitation,
    wcode: j.hourly.weathercode,
    cape: j.hourly.cape,
    gust: j.hourly.windgusts_10m,
    wind: j.hourly.windspeed_10m,
    prob: j.hourly.precipitation_probability,
  };
}

let fetching = false;
let pendingRefresh = false;

async function refreshVisibleData() {
  if (fetching) { pendingRefresh = true; return; }
  fetching = true;

  try {
    const step = stepForZoom(map.getZoom());
    const coords = visibleGrid(step);
    const now = Date.now();
    const toFetch = [];

    for (const [lat, lon] of coords) {
      const key = `${lat},${lon}`;
      const cached = omCache.get(key);
      if (!cached || now - cached.ts > CLIENT_CACHE_TTL) toFetch.push([lat, lon, key]);
    }

    omStatus.textContent = `in view: ${coords.length} | to fetch: ${toFetch.length}`;

    const concurrency = 10;
    let i = 0;
    async function worker() {
      while (i < toFetch.length) {
        const [lat, lon, key] = toFetch[i++];
        try {
          const data = await fetchPoint(lat, lon);
          if (!omTimesRef) omTimesRef = data.time;
          omCache.set(key, { ...data, lat, lon, ts: Date.now() });
        } catch (e) {}
        await new Promise((r) => setTimeout(r, 80));
      }
    }
    await Promise.all(Array.from({ length: Math.min(concurrency, toFetch.length || 1) }, worker));

    drawHour(+omHour.value);
    omStatus.textContent = `in view: ${coords.length} | cache: ${omCache.size}`;
  } finally {
    fetching = false;
    if (pendingRefresh) { pendingRefresh = false; refreshVisibleData(); }
  }
}

function drawPoints(idx) {
  pointsLayer.clearLayers();
  const step = stepForZoom(map.getZoom());
  const coords = visibleGrid(step);
  for (const [lat, lon] of coords) {
    const key = `${lat},${lon}`;
    const rec = omCache.get(key);
    if (!rec) continue;
    const p = rec.precip?.[idx] ?? 0;

    const t = Math.min(1, p / 10);
    const color = interpStops(t, BR_STOPS);
    const r = Math.max(4, Math.min(22, (4 + Math.sqrt(p) * 6) * sizeBoost));

    const marker = L.circleMarker([lat, lon], {
      radius: r,
      color,
      weight: 1,
      fillColor: color,
      fillOpacity: omOpacity,
      opacity: omOpacity,
      interactive: false,
    }).bindTooltip(`${p.toFixed(2)} mm/h`, { direction: "top", offset: [0, -r] });

    pointsLayer.addLayer(marker);
  }
  if (!map.hasLayer(pointsLayer)) pointsLayer.addTo(map);
}

function codeIsThunder(code) { return code === 95 || code === 96 || code === 99; }

function drawStormLayers(idx) {
  stormsLayer.clearLayers();
  if (toggleStorms.checked) {
    for (const [, rec] of omCache) {
      const p = rec.precip?.[idx] ?? 0;
      const code = rec.wcode?.[idx] ?? null;
      const cape = rec.cape?.[idx] ?? 0;
      if (codeIsThunder(code) || (cape >= 1000 && p >= 3)) {
        L.circleMarker([rec.lat, rec.lon], {
          radius: 7,
          color: "#b10026",
          fillColor: "#b10026",
          fillOpacity: 0.9,
          weight: 1,
        })
          .bindTooltip(
            `Thunderstorm (heuristic)\nprecip: ${p.toFixed(2)} mm/h\nCAPE: ${Math.round(cape)} J/kg\nwcode: ${code}`
          )
          .addTo(stormsLayer);
      }
    }
    if (!map.hasLayer(stormsLayer)) stormsLayer.addTo(map);
  } else if (map.hasLayer(stormsLayer)) map.removeLayer(stormsLayer);

  extremeLayer.clearLayers();
  if (toggleExtreme.checked) {
    for (const [, rec] of omCache) {
      const p = rec.precip?.[idx] ?? 0;
      const cape = rec.cape?.[idx] ?? 0;
      const gust = rec.gust?.[idx] ?? 0;
      if (p >= 8 || (cape >= 2000 && gust >= 25)) {
        L.circleMarker([rec.lat, rec.lon], {
          radius: 9,
          color: "#6f00ff",
          fillColor: "#6f00ff",
          fillOpacity: 0.9,
          weight: 1,
        })
          .bindTooltip(
            `Extreme event (heuristic)\nprecip: ${p.toFixed(2)} mm/h\nCAPE: ${Math.round(cape)} J/kg\ngusts: ${(gust * 3.6).toFixed(0)} km/h`
          )
          .addTo(extremeLayer);
      }
    }
    if (!map.hasLayer(extremeLayer)) extremeLayer.addTo(map);
  } else if (map.hasLayer(extremeLayer)) map.removeLayer(extremeLayer);
}

function drawHour(idx) {
  omHour.value = idx;
  const t = omTimesRef?.[idx];
  omHourLabel.textContent = t ? new Date(t).toLocaleString() : "—";
  drawPoints(idx);
  drawStormLayers(idx);
}

// UI bindings
omHour.addEventListener("input", () => drawHour(+omHour.value));
omOpacityInp.addEventListener("input", (e) => {
  omOpacity = parseFloat(e.target.value);
  omOpacityVal.textContent = omOpacity.toFixed(2);
  drawHour(+omHour.value);
});
sizeBoostInp.addEventListener("input", (e) => {
  sizeBoost = parseFloat(e.target.value);
  sizeBoostVal.textContent = `${sizeBoost.toFixed(1)}×`;
  drawHour(+omHour.value);
});
omAutoplay.addEventListener("change", () => {
  if (omAutoplay.checked) {
    if (omTimer) clearInterval(omTimer);
    omTimer = setInterval(() => {
      let v = +omHour.value + 1;
      if (v > +omHour.max) v = 0;
      drawHour(v);
    }, 900);
  } else {
    if (omTimer) clearInterval(omTimer);
    omTimer = null;
  }
});
toggleStorms.addEventListener("change", () => drawHour(+omHour.value));
toggleExtreme.addEventListener("change", () => drawHour(+omHour.value));

// Refresh data on map move/zoom (debounced)
let mvTimer = null;
function scheduleRefresh() {
  clearTimeout(mvTimer);
  mvTimer = setTimeout(refreshVisibleData, 200);
}
map.on("moveend", scheduleRefresh);
map.on("zoomend", scheduleRefresh);

// init
(async () => {
  await refreshVisibleData();
  drawHour(0);
  setBase("sat");
})();
