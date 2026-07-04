// ---- Map state ----
let flightMap = null;
let flightMarkers = {};
let mapRefreshInterval = null;
let mapOpen = false;
let activeMarker = null;
let routeRequestToken = 0;

let routeFlown = null, routeFlownHit = null;
let routeRemaining = null, routeRemainingHit = null;
let routeDepLabel = null, routeArrLabel = null;
let routeDepDot = null, routeArrDot = null;
let currentRouteFlightId = null;

const mapToggleBtn = document.getElementById('mapToggleBtn');
const zoomInBtn   = document.getElementById('zoomInBtn');
const zoomOutBtn  = document.getElementById('zoomOutBtn');

function initMap() {
  if (flightMap) return;
  const mapBounds = L.latLngBounds([[-60, -140], [85, 180]]);
  flightMap = L.map('map', {
    attributionControl: false,
    zoomControl: false,
    minZoom: 3,
    maxBounds: mapBounds,
    maxBoundsViscosity: 1.0
  }).setView([41.275, 28.751], 5);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    subdomains: 'abcd',
    minZoom: 3,
    maxZoom: 19
  }).addTo(flightMap);

  // Route line pane sits above markers; active marker pane sits above route.
  flightMap.createPane('routePane');
  flightMap.getPane('routePane').style.zIndex = 620;
  flightMap.createPane('activeMarkerPane');
  flightMap.getPane('activeMarkerPane').style.zIndex = 630;

  flightMap.on('zoomend moveend', checkISTOverlay);
}

// ── IST Terminal overlay ───────────────────────────────────────────────────────
const IST_CENTER = L.latLng(41.2609, 28.7518);
const IST_ZOOM_THRESHOLD = 11;
const IST_ZOOM_HIDE = 10;
let _istLayer = null;
let _istLoading = false;
let _istLoaded = false;

const _IST_GRAY = {
  terminal: { color: '#555', fillColor: '#252525', fillOpacity: 0.55, weight: 1.5 },
  runway:   { color: '#444', fillColor: '#1a1a1a', fillOpacity: 0.45, weight: 1 },
  taxiway:  { color: '#333', fillColor: 'transparent', fillOpacity: 0, weight: 0.8 },
  apron:    { color: '#333', fillColor: '#181818', fillOpacity: 0.3, weight: 0.5 },
  default:  { color: '#444', fillColor: '#1e1e1e', fillOpacity: 0.4, weight: 0.8 },
};
const _IST_PURPLE = {
  terminal: { color: '#a78bfa', fillColor: '#3b2060', fillOpacity: 0.75, weight: 1.5 },
  runway:   { color: '#6d5acd', fillColor: '#1e1535', fillOpacity: 0.6,  weight: 1 },
  taxiway:  { color: '#4c3f8a', fillColor: 'transparent', fillOpacity: 0, weight: 1 },
  apron:    { color: '#4c3f8a', fillColor: '#1a1230', fillOpacity: 0.4,  weight: 0.5 },
  default:  { color: '#6d5acd', fillColor: '#2a1a4a', fillOpacity: 0.5,  weight: 0.8 },
};

function applyISTStyle(styleMap) {
  if (!_istLayer) return;
  _istLayer.eachLayer(l => {
    const aeroway = l.feature?.properties?.aeroway;
    if (l.setStyle) l.setStyle(styleMap[aeroway] || styleMap.default);
  });
  document.getElementById('map').classList.toggle('ist-active', styleMap === _IST_PURPLE);
}

async function checkISTOverlay() {
  if (!flightMap) return;
  const zoom = flightMap.getZoom();
  const dist = flightMap.getCenter().distanceTo(IST_CENTER);
  const nearIST = dist < 40000;

  if (zoom >= IST_ZOOM_THRESHOLD && nearIST) {
    if (!_istLoaded && !_istLoading) await loadISTOverlay();
    if (_istLayer && !flightMap.hasLayer(_istLayer)) _istLayer.addTo(flightMap);
  } else if (zoom < IST_ZOOM_HIDE || !nearIST) {
    if (_istLayer && flightMap.hasLayer(_istLayer)) flightMap.removeLayer(_istLayer);
  }
}

async function loadISTOverlay() {
  _istLoading = true;
  // Only aeroway features — no generic buildings
  const query = `[out:json][timeout:15];
(
  way["aeroway"~"terminal|runway|taxiway|apron|pier|gate|hangar"](41.22,28.68,41.31,28.82);
  way["building"~"terminal|hangar|aerodrome"](41.22,28.68,41.31,28.82);
  relation["aeroway"](41.22,28.68,41.31,28.82);
);
out body;>;out skel qt;`;

  try {
    const res = await fetch('https://overpass-api.de/api/interpreter', {
      method: 'POST',
      body: query
    });
    const osm = await res.json();
    const geojson = osmtogeojson(osm);

    _istLayer = L.geoJSON(geojson, {
      style: f => {
        const aeroway = f.properties?.aeroway;
        return _IST_GRAY[aeroway] || _IST_GRAY.default;
      },
      onEachFeature: (f, layer) => {
        const name = f.properties?.name;
        if (name) layer.bindTooltip(name, { permanent: false, className: 'ist-tooltip' });
      }
    });

    _istLoaded = true;
  } catch (e) {
    console.warn('IST overlay failed:', e);
  }
  _istLoading = false;
}


zoomInBtn.addEventListener('click',  () => flightMap && flightMap.zoomIn());
zoomOutBtn.addEventListener('click', () => flightMap && flightMap.zoomOut());

// ---- Marker helpers ----
function flightDirection(f) {
  if (f.status && f.status.toLowerCase() === 'landed') return 'landed';
  if (f.from === 'IST') return 'departure';
  if (f.to   === 'IST') return 'arrival';
  return 'departure';
}

function makeFlightIcon(direction, heading) {
  const rotation = (typeof heading === 'number') ? heading : 0;
  const arrow = `<svg class="flight-arrow" style="transform: rotate(${rotation}deg)" viewBox="0 0 24 24">` +
    `<path d="M12 1 L13.4 9 L19 10.5 L19 12 L13.6 11.3 L14.2 17.5 L16.5 19.5 L16.5 21 L12 19.7 L7.5 21 L7.5 19.5 L9.8 17.5 L10.4 11.3 L5 12 L5 10.5 L10.6 9 Z" ` +
    `fill="#fff" stroke="#fff" stroke-width="1" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  return L.divIcon({
    className: '',
    html: `<div class="flight-marker-icon ${direction}">${arrow}</div>`,
    iconSize: [20, 20],
    iconAnchor: [10, 10],
    popupAnchor: [0, -20]
  });
}

function highlightMarker(marker) {
  const el = marker.getElement();
  const inner = el && el.querySelector('.flight-marker-icon');
  if (inner) inner.classList.add('highlighted');
  const activePane = flightMap && flightMap.getPane('activeMarkerPane');
  if (el && activePane) activePane.appendChild(el);
}

function unhighlightMarker(marker) {
  const el = marker.getElement();
  const inner = el && el.querySelector('.flight-marker-icon');
  if (inner) inner.classList.remove('highlighted');
  const markerPane = flightMap && flightMap.getPane('markerPane');
  if (el && markerPane) markerPane.appendChild(el);
}

function setActiveMarker(marker) {
  if (activeMarker && activeMarker !== marker) unhighlightMarker(activeMarker);
  activeMarker = marker;
  highlightMarker(marker);
  drawSplitRoute(marker._flightId);
}

// ---- Great-circle interpolation ----
function toRad(d) { return d * Math.PI / 180; }
function toDeg(r) { return r * 180 / Math.PI; }

function latLngToVector([lat, lng]) {
  const phi = toRad(lat), lambda = toRad(lng);
  return [Math.cos(phi) * Math.cos(lambda), Math.cos(phi) * Math.sin(lambda), Math.sin(phi)];
}

function vectorToLatLng([x, y, z]) {
  return [toDeg(Math.asin(Math.max(-1, Math.min(1, z)))), toDeg(Math.atan2(y, x))];
}

function slerp(v0, v1, t) {
  const dot = Math.max(-1, Math.min(1, v0[0]*v1[0] + v0[1]*v1[1] + v0[2]*v1[2]));
  const theta = Math.acos(dot);
  if (theta < 1e-6) return v0;
  const sinTheta = Math.sin(theta);
  const a = Math.sin((1-t)*theta) / sinTheta;
  const b = Math.sin(t*theta) / sinTheta;
  return [a*v0[0]+b*v1[0], a*v0[1]+b*v1[1], a*v0[2]+b*v1[2]];
}

function greatCirclePoints(start, end, steps = 80) {
  const v0 = latLngToVector(start), v1 = latLngToVector(end);
  const points = [];
  for (let i = 0; i <= steps; i++) points.push(vectorToLatLng(slerp(v0, v1, i/steps)));
  return points;
}

// ---- Route drawing ----
function clearRouteLayers() {
  [routeFlown, routeFlownHit, routeRemaining, routeRemainingHit,
   routeDepLabel, routeArrLabel, routeDepDot, routeArrDot].forEach(l => { if (l) flightMap.removeLayer(l); });
  routeFlown = routeFlownHit = routeRemaining = routeRemainingHit =
  routeDepLabel = routeArrLabel = routeDepDot = routeArrDot = null;
  currentRouteFlightId = null;
  applyISTStyle(_IST_GRAY);
}

async function drawSplitRoute(flightId) {
  const token = ++routeRequestToken;
  clearRouteLayers();
  if (!flightId) { showAllMarkers(); return; }
  currentRouteFlightId = flightId;
  try {
    const res = await fetch(`/api/route/${encodeURIComponent(flightId)}`);
    if (token !== routeRequestToken) return;
    if (!res.ok) return;
    const data = await res.json();
    if (token !== routeRequestToken) return;
    if (!data) return;

    clearRouteLayers();
    currentRouteFlightId = flightId;
    hideOtherMarkers(flightId);

    const depLatLng = [data.dep.lat, data.dep.lng];
    const arrLatLng = [data.arr.lat, data.arr.lng];
    const curLatLng = data.current ? [data.current.lat, data.current.lng] : null;

    const flownCurve     = greatCirclePoints(depLatLng, curLatLng || arrLatLng);
    const remainingCurve = curLatLng ? greatCirclePoints(curLatLng, arrLatLng) : null;
    const allPoints      = remainingCurve ? flownCurve.concat(remainingCurve) : flownCurve;

    const zoomToRoute = () => flightMap.fitBounds(L.latLngBounds(allPoints), { padding: [60, 60] });

    routeFlown = L.polyline(flownCurve, {
      pane: 'routePane', color: '#9b59b6', weight: 3, opacity: 0.55, dashArray: '6 8', interactive: false
    }).addTo(flightMap);
    routeFlownHit = makeRouteHitArea(flownCurve, zoomToRoute);

    if (remainingCurve) {
      routeRemaining = L.polyline(remainingCurve, {
        pane: 'routePane', color: '#9b59b6', weight: 5, opacity: 0.95, interactive: false
      }).addTo(flightMap);
      routeRemainingHit = makeRouteHitArea(remainingCurve, zoomToRoute);
    }

    routeDepDot   = makeAirportDot(depLatLng);
    routeArrDot   = makeAirportDot(arrLatLng);
    routeDepLabel = makeAirportLabel(depLatLng, data.dep);
    routeArrLabel = makeAirportLabel(arrLatLng, data.arr);

    // Turn IST overlay purple if it's one of the route airports
    const depIsIST = data.dep.iata_code === 'IST';
    const arrIsIST = data.arr.iata_code === 'IST';
    if (depIsIST || arrIsIST) applyISTStyle(_IST_PURPLE);

  } catch (e) {
    console.error('Failed to load flight route', e);
  }
}

function makeAirportDot(latLng) {
  return L.circleMarker(latLng, {
    pane: 'routePane', radius: 6, color: '#c896f0', weight: 2,
    fillColor: '#9b59b6', fillOpacity: 1, interactive: false
  }).addTo(flightMap);
}

function makeAirportLabel(latLng, airport) {
  const text = airport.name ? `${airport.name} (${airport.iata_code})` : airport.iata_code;
  return L.marker(latLng, {
    icon: L.divIcon({ className: '', html: '', iconSize: [0, 0] }),
    pane: 'routePane', interactive: false, keyboard: false
  }).bindTooltip(text, { permanent: true, direction: 'bottom', offset: [0, 8], className: 'airport-label' })
    .addTo(flightMap);
}

function makeRouteHitArea(curve, onPress) {
  const hit = L.polyline(curve, { color: '#000', weight: 22, opacity: 0.01 }).addTo(flightMap);
  hit.on('mousedown', (e) => { L.DomEvent.stop(e); onPress(); });
  hit.on('click',     (e) => { L.DomEvent.stop(e); onPress(); });
  return hit;
}


function hideOtherMarkers(exceptFlightId) {
  Object.values(flightMarkers).forEach(m => m.setOpacity(m._flightId === exceptFlightId ? 1 : 0.08));
}

function showAllMarkers() {
  Object.values(flightMarkers).forEach(m => m.setOpacity(1));
}

// ---- Marker management ----
function addOrUpdateFlightMarker(f) {
  const direction = flightDirection(f);

  if (flightMarkers[f.flight_id]) {
    const existing = flightMarkers[f.flight_id];
    existing._flightData = f;
    existing.setLatLng([f.lat, f.lng]);
    if (existing._direction !== direction) {
      existing.setIcon(makeFlightIcon(direction, f.heading));
      existing._direction = direction;
      existing._heading = f.heading;
    } else if (typeof f.heading === 'number' && existing._heading !== f.heading) {
      const el = existing.getElement();
      const arrow = el && el.querySelector('.flight-arrow');
      if (arrow) arrow.style.transform = `rotate(${f.heading}deg)`;
      existing._heading = f.heading;
    }
  } else {
    const marker = L.marker([f.lat, f.lng], { icon: makeFlightIcon(direction, f.heading) })
      .addTo(flightMap)
      .bindTooltip(f.flight_id, { className: 'flight-tooltip', direction: 'top', offset: [0, -10] });
    marker._direction = direction;
    marker._heading   = f.heading;
    marker._flightId  = f.flight_id;
    marker._flightData = f;

    marker.on('mouseover', () => {
      highlightMarker(marker);
      drawSplitRoute(marker._flightId);
      clearTimeout(dashboardHoverTimeout);
      if (!dashboardPinned) openDashboard(marker._flightData);
    });

    marker.on('mouseout', () => {
      if (activeMarker === marker) return;
      unhighlightMarker(marker);
      if (activeMarker) {
        drawSplitRoute(activeMarker._flightId);
      } else {
        ++routeRequestToken;
        clearRouteLayers();
        showAllMarkers();
      }
      if (!dashboardPinned) {
        dashboardHoverTimeout = setTimeout(() => {
          if (!dashboardPinned) {
            flightDashboard.classList.remove('visible');
            setTimeout(() => flightDashboard.classList.remove('animating'), 230);
          }
        }, 300);
      }
    });

    marker.on('click', () => {
      flightMap.flyTo(marker.getLatLng(), 7, { duration: 1.2 });
      setActiveMarker(marker);
      openDashboard(marker._flightData, { pin: true });
    });

    flightMarkers[f.flight_id] = marker;
  }
  return flightMarkers[f.flight_id];
}

async function refreshFlights() {
  try {
    const res     = await fetch('/api/flights');
    const flights = await res.json();
    const seen    = new Set();
    let depCount = 0, arrCount = 0;

    flights.forEach(f => {
      if (f.lat == null || f.lng == null) return;
      seen.add(f.flight_id);
      addOrUpdateFlightMarker(f);
      if (f.from === 'IST') depCount++; else arrCount++;
    });

    document.getElementById('legend-dep-count').textContent = depCount ? `(${depCount})` : '';
    document.getElementById('legend-arr-count').textContent = arrCount ? `(${arrCount})` : '';

    Object.keys(flightMarkers).forEach(id => {
      if (!seen.has(id)) { flightMap.removeLayer(flightMarkers[id]); delete flightMarkers[id]; }
    });
  } catch (e) {
    console.error('Failed to fetch flight data', e);
  }
}

function openMap() {
  let needsResize = false;
  if (!mapOpen) {
    mapOpen = true;
    needsResize = true;
    document.body.classList.add('map-open');
    mapToggleBtn.textContent = '✕ Close Map';
    initMap();
    if (!mapRefreshInterval) mapRefreshInterval = setInterval(refreshFlights, 15000);
  }
  return new Promise(resolve => {
    requestAnimationFrame(() => {
      if (needsResize) flightMap.invalidateSize();
      resolve(refreshFlights());
    });
  });
}

function closeMap() {
  if (!mapOpen) return;
  mapOpen = false;
  document.body.classList.remove('map-open');
  mapToggleBtn.textContent = '🗺️ Map';
  if (mapRefreshInterval) { clearInterval(mapRefreshInterval); mapRefreshInterval = null; }
  closeDashboard();
}

mapToggleBtn.addEventListener('click', () => mapOpen ? closeMap() : openMap());
