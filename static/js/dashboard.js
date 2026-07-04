// ---- Dashboard state ----
const flightDashboard   = document.getElementById('flight-dashboard');
let dashboardPinned     = false;
let dashboardHoverTimeout = null;

document.getElementById('fd-close').addEventListener('click', () => {
  dashboardPinned = false;
  closeDashboard();
});

flightDashboard.addEventListener('mouseenter', () => clearTimeout(dashboardHoverTimeout));
flightDashboard.addEventListener('mouseleave', () => {
  if (!dashboardPinned) {
    dashboardHoverTimeout = setTimeout(() => {
      if (!dashboardPinned) {
        flightDashboard.classList.remove('visible');
        setTimeout(() => flightDashboard.classList.remove('animating'), 230);
      }
    }, 300);
  }
});

// ---- Time helpers ----
function fmtUtcTime(dtStr) {
  if (!dtStr) return null;
  const m = dtStr.match(/(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]} UTC` : null;
}

function etaFromDatetime(dtStr) {
  if (!dtStr) return null;
  const d = new Date(dtStr.replace(' ', 'T') + 'Z');
  if (isNaN(d)) return null;
  const mins = Math.round((d - Date.now()) / 60000);
  if (mins <= 0) return null;
  const h = Math.floor(mins / 60), m = mins % 60;
  return h > 0 ? `~${h}h ${m}m` : `~${m}m`;
}

function updateETA(remainingKm, speedKmh) {
  const el = document.getElementById('fd-eta');
  if (!remainingKm || !speedKmh || speedKmh < 50) { el.textContent = '—'; return; }
  const mins = Math.round((remainingKm / speedKmh) * 60);
  const h = Math.floor(mins / 60), m = mins % 60;
  el.textContent = h > 0 ? `~${h}h ${m}m` : `~${m}m`;
}

function haversineKm(lat1, lng1, lat2, lng2) {
  const R = 6371, toR = d => d * Math.PI / 180;
  const dLat = toR(lat2-lat1), dLng = toR(lng2-lng1);
  const a = Math.sin(dLat/2)**2 + Math.cos(toR(lat1)) * Math.cos(toR(lat2)) * Math.sin(dLng/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

// ---- Populate dashboard fields ----
function populateDashboard(f) {
  document.getElementById('fd-flight-id').textContent = f.flight_id || '—';
  document.getElementById('fd-status').textContent    = f.status || 'EN ROUTE';
  const dir = (f.from === 'IST') ? 'Departing Istanbul' : (f.to === 'IST') ? 'Arriving Istanbul' : '';
  document.getElementById('fd-direction').textContent = dir;
  document.getElementById('fd-from').textContent = f.from || '?';
  document.getElementById('fd-to').textContent   = f.to   || '?';

  // Altitude + trend arrow
  const altEl = document.getElementById('fd-altitude');
  if (f.altitude_ft) {
    let trendHtml = '';
    if (f.v_speed_fpm != null) {
      const vs = f.v_speed_fpm;
      if (vs > 1)       trendHtml = `<span class="fd-trend up">▲ +${Math.round(vs)} km/h</span>`;
      else if (vs < -1) trendHtml = `<span class="fd-trend down">▼ ${Math.round(vs)} km/h</span>`;
      else               trendHtml = '<span class="fd-trend flat">▬</span>';
    } else if (f.prev_altitude_ft) {
      const diff = f.altitude_ft - f.prev_altitude_ft;
      const abs  = Math.abs(Math.round(diff));
      if (abs <= 3000) {
        const label = abs >= 1000 ? `${(abs/1000).toFixed(1)}k` : abs;
        if (diff > 100)       trendHtml = `<span class="fd-trend up">▲ +${label}</span>`;
        else if (diff < -100) trendHtml = `<span class="fd-trend down">▼ −${label}</span>`;
        else                   trendHtml = '<span class="fd-trend flat">▬</span>';
      }
    }
    altEl.innerHTML = `${f.altitude_ft.toLocaleString()} ft${trendHtml}`;
  } else {
    altEl.textContent = '—';
  }

  document.getElementById('fd-speed').textContent   = f.speed_kmh ? `${f.speed_kmh} km/h` : '—';
  document.getElementById('fd-heading').textContent  = typeof f.heading === 'number' ? `${f.heading}°` : '—';
  document.getElementById('fd-aircraft').textContent = f.aircraft || '—';
  document.getElementById('fd-departure').textContent = fmtUtcTime(f.dep_estimated || f.departure) || '—';
  document.getElementById('fd-arrival').textContent   = fmtUtcTime(f.arr_estimated || f.arrival)   || '—';

  const isDep    = f.from === 'IST';
  const gate     = isDep ? f.dep_gate     : f.arr_gate;
  const terminal = isDep ? f.dep_terminal : f.arr_terminal;
  const delay    = isDep ? f.dep_delayed  : f.arr_delayed;

  const gateRow  = document.getElementById('fd-gate-row');
  const termRow  = document.getElementById('fd-terminal-row');
  const delayRow = document.getElementById('fd-delay-row');
  const bagRow   = document.getElementById('fd-baggage-row');

  if (gate)     { document.getElementById('fd-gate').textContent     = gate;     gateRow.style.display  = ''; }
  else gateRow.style.display = 'none';

  if (terminal) { document.getElementById('fd-terminal').textContent = terminal; termRow.style.display  = ''; }
  else termRow.style.display = 'none';

  if (delay) {
    document.getElementById('fd-delay').textContent = `${delay > 0 ? '+' : ''}${delay} min`;
    delayRow.style.display = '';
  } else delayRow.style.display = 'none';

  if (!isDep && f.arr_baggage) {
    document.getElementById('fd-baggage').textContent = f.arr_baggage;
    bagRow.style.display = '';
  } else bagRow.style.display = 'none';

  document.getElementById('fd-updated').textContent = f.updated_at || '—';
  if (f.lat != null && f.lng != null) {
    document.getElementById('fd-coords').textContent = `${f.lat.toFixed(2)}°, ${f.lng.toFixed(2)}°`;
  } else {
    document.getElementById('fd-coords').textContent = '—';
  }
}

// ---- Weather ----
async function fetchAndShowWeather(arrIata) {
  const divider = document.getElementById('fd-weather-divider');
  const section = document.getElementById('fd-weather');
  if (!arrIata || arrIata === '?') { divider.style.display = 'none'; section.style.display = 'none'; return; }
  try {
    const res = await fetch(`/api/weather?iata=${encodeURIComponent(arrIata)}`);
    if (!res.ok) { divider.style.display = 'none'; section.style.display = 'none'; return; }
    const w = await res.json();
    if (!w)      { divider.style.display = 'none'; section.style.display = 'none'; return; }
    document.getElementById('fd-weather-airport').textContent   = `${w.airport_name || arrIata} (${arrIata})`;
    document.getElementById('fd-weather-emoji').textContent     = w.emoji || '';
    document.getElementById('fd-weather-condition').textContent = w.condition || '—';
    document.getElementById('fd-weather-detail').textContent    =
      `${w.temp_c != null ? w.temp_c + '°C' : '—'} · ${w.wind_kmh != null ? w.wind_kmh + ' km/h wind' : '—'}`;
    divider.style.display = 'block';
    section.style.display = 'block';
  } catch (e) {
    divider.style.display = 'none';
    section.style.display = 'none';
  }
}

// ---- Progress track ----
function updateProgressTrack(routeData) {
  const wrap    = document.getElementById('fd-progress-wrap');
  const divider = document.getElementById('fd-progress-divider');
  if (!routeData || !routeData.current) { wrap.style.display = 'none'; divider.style.display = 'none'; return; }

  const { dep, arr, current } = routeData;
  const totalKm = haversineKm(dep.lat, dep.lng, arr.lat, arr.lng);
  const flownKm = haversineKm(dep.lat, dep.lng, current.lat, current.lng);
  const pct     = Math.min(Math.max(flownKm / totalKm, 0), 1);

  document.getElementById('fd-progress-done').style.width  = `${pct * 100}%`;
  document.getElementById('fd-progress-plane').style.left  = `${pct * 100}%`;
  document.getElementById('fd-prog-from').textContent = dep.iata_code || '—';
  document.getElementById('fd-prog-to').textContent   = arr.iata_code || '—';
  document.getElementById('fd-prog-dist').textContent  =
    `${Math.round(flownKm).toLocaleString()} / ${Math.round(totalKm).toLocaleString()} km`;

  wrap.style.display    = 'block';
  divider.style.display = 'block';
}

// ---- Open / close ----
function showDashboardPanel() {
  flightDashboard.classList.add('animating');
  requestAnimationFrame(() => requestAnimationFrame(() => flightDashboard.classList.add('visible')));
}

async function openDashboard(f, { pin = false } = {}) {
  if (pin) { dashboardPinned = true; flightDashboard.classList.add('pinned'); }
  document.getElementById('fd-weather-divider').style.display = 'none';
  document.getElementById('fd-weather').style.display         = 'none';
  document.getElementById('fd-eta').textContent = '—';
  populateDashboard(f);
  showDashboardPanel();

  try {
    const [flightRes, routeRes] = await Promise.all([
      fetch(`/api/flights/${encodeURIComponent(f.flight_id)}`),
      fetch(`/api/route/${encodeURIComponent(f.flight_id)}`)
    ]);

    let full = f;
    if (flightRes.ok) {
      const data = await flightRes.json();
      if (data) { full = data; populateDashboard(full); }
    }

    if (routeRes.ok) {
      const routeData = await routeRes.json();
      updateProgressTrack(routeData);
      const isDep      = full.from === 'IST';
      const estimated  = isDep ? full.dep_estimated : full.arr_estimated;
      const etaStr     = etaFromDatetime(estimated);
      if (etaStr) {
        document.getElementById('fd-eta').textContent = etaStr;
      } else if (routeData && routeData.current && routeData.arr) {
        const remKm = haversineKm(routeData.current.lat, routeData.current.lng, routeData.arr.lat, routeData.arr.lng);
        updateETA(remKm, full.speed_kmh);
      }
    } else {
      updateProgressTrack(null);
    }

    await fetchAndShowWeather(full.to);
  } catch (e) {
    updateProgressTrack(null);
  }
}

function closeDashboard() {
  flightDashboard.classList.remove('visible', 'pinned');
  setTimeout(() => flightDashboard.classList.remove('animating'), 230);
  dashboardPinned = false;
  if (activeMarker) {
    unhighlightMarker(activeMarker);
    activeMarker = null;
    ++routeRequestToken;
    clearRouteLayers();
    showAllMarkers();
  }
}
