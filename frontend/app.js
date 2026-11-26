/* QYRAN 2.0+ — Real-Time Voice-to-3D Command Console (IT FEST 2026) */
(() => {
  'use strict';

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const esc = (s) =>
    String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // App State
  let uiLang = localStorage.getItem('qyran2_lang') || 'ru';
  let sfxEnabled = true;
  let state = null;
  let ws = null;
  let map = null;
  let mapReady = false;
  let mapFilter = 'all';
  let selectedChannel = 'radio';
  let scenarioRunning = false;
  let stopRequested = false;
  let currentAudio = null;
  let selectedFloor = null;

  // Map bookkeeping
  let gridLabelMarkers = [];
  let threatMarkers = [];
  let unitMarkers = {};
  let activeAnimations = {};
  let lastRenderedScenarioId = null;

  // Mic PTT state
  let mediaRecorder = null;
  let micStream = null;
  let audioChunks = [];
  let micAnalyser = null;
  let micAnimFrame = null;
  let isRecording = false;
  let staticWave = new Array(64).fill(0.08);

  // =========================================================================
  // 1. Bilingual RU / KZ UI Translations + Tactical WebAudio SFX & TTS
  // =========================================================================
  const I18N = {
    ru: {
      air_title: 'Эфир и живой микрофон',
      btn_run: '▶ Живой эфир (GPU)',
      btn_ptt: '🎙 Говорить [Space]',
      adv_lbl: '⚙ Клипы сценария · Радиофильтр · Файл WAV',
      feed_title: 'Лента расшифровок (AI Diff)',
      kpi_thr: 'Угроз',
      leg_p1: 'P1 Критично',
      leg_p2: 'P2 Оперативно',
      leg_ok: 'Решено',
      leg_own: 'Службы (OSRM)',
      m_all: 'Всё',
      m_thr: 'Угрозы',
      m_own: 'Службы',
      m_over: 'Обзор',
      now_lbl: 'ОБСТАНОВКА',
      tab_ops: '🚒 Силы',
      tab_cams: '📷 CV',
      tab_b3d: '🧊 3D',
      tab_law: '⚖️ Закон',
      tab_bench: '🧪 WER',
      tab_roi: '📊 ROI',
      foot_audit: '🔐 Криптографический аудит (SQLite · SHA-256 Hash Chain)',
      foot_brief: '📊 Автосводка смены (AI-Assisted · ст. 21)',
    },
    kk: {
      air_title: 'Радиоэфир және тікелей микрофон',
      btn_run: '▶ Тікелей эфир (GPU)',
      btn_ptt: '🎙 Сөйлеу [Space]',
      adv_lbl: '⚙ Сценарий клиптері · Радиосүзгі · WAV файл',
      feed_title: 'Мәтіндер лентасы (AI Diff)',
      kpi_thr: 'Қауіптер',
      leg_p1: 'P1 Сыни',
      leg_p2: 'P2 Жедел',
      leg_ok: 'Шешілді',
      leg_own: 'Қызметтер (OSRM)',
      m_all: 'Барлығы',
      m_thr: 'Қауіптер',
      m_own: 'Қызметтер',
      m_over: 'Шолу',
      now_lbl: 'ЖАҒДАЙ',
      tab_ops: '🚒 Күштер',
      tab_cams: '📷 CV',
      tab_b3d: '🧊 3D',
      tab_law: '⚖️ Заң',
      tab_bench: '🧪 WER',
      tab_roi: '📊 ROI',
      foot_audit: '🔐 Криптографиялық аудит (SQLite · SHA-256)',
      foot_brief: '📊 Ауысым автосводкасы (AI-Assisted · 21-бап)',
    },
  };
  const tr = (ru, kk) => (uiLang === 'kk' ? kk : ru);

  function applyI18n() {
    const dict = I18N[uiLang] || I18N.ru;
    $$('[data-i18n]').forEach((el) => {
      const k = el.dataset.i18n;
      if (dict[k]) el.textContent = dict[k];
    });
    document.documentElement.lang = uiLang;
  }

  let sfxCtx = null;
  function playTone(type) {
    if (!sfxEnabled) return;
    try {
      if (!sfxCtx) sfxCtx = new (window.AudioContext || window.webkitAudioContext)();
      const t = sfxCtx.currentTime;
      const seq = type === 'alert' ? [880, 660, 920] : type === 'ok' ? [523, 784] : [1180];
      seq.forEach((freq, i) => {
        const osc = sfxCtx.createOscillator();
        const gain = sfxCtx.createGain();
        osc.type = type === 'alert' ? 'triangle' : 'sine';
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.001, t + i * 0.11);
        gain.gain.exponentialRampToValueAtTime(0.07, t + i * 0.11 + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.001, t + i * 0.11 + 0.1);
        osc.connect(gain);
        gain.connect(sfxCtx.destination);
        osc.start(t + i * 0.11);
        osc.stop(t + i * 0.11 + 0.11);
      });
    } catch {}
  }

  function speakNotice(text) {
    if (!$('#chkTts') || !$('#chkTts').checked || !window.speechSynthesis) return;
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = uiLang === 'kk' ? 'kk-KZ' : 'ru-RU';
      u.rate = 1.08;
      window.speechSynthesis.speak(u);
    } catch {}
  }

  // =========================================================================
  // 2. MapLibre GL 3D Map + Automatic Air-Gapped Offline Fallback + Click Inspector
  // =========================================================================
  const OFFLINE_TACTICAL_STYLE = {
    version: 8,
    name: 'QYRAN Offline Tactical Dark',
    sources: {},
    layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#090f19' } }],
  };

  function initMap(center, zoom, pitch, bearing) {
    if (!window.maplibregl) return;
    let switchedOffline = false;
    map = new maplibregl.Map({
      container: 'map',
      style: 'https://tiles.openfreemap.org/styles/dark',
      center,
      zoom,
      pitch,
      bearing,
      maxPitch: 75,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'bottom-left');

    const onStyleReady = () => {
      mapReady = true;
      ensure3DBuildings();
      setupMapSources();
      if (state) syncMapWithState();
    };
    map.on('load', onStyleReady);
    map.on('style.load', () => {
      if (switchedOffline) onStyleReady();
    });

    // Air-gapped resilience: if external map tiles fail or stall >4.5s (e.g. bad EXPO Wi-Fi), switch cleanly to offline vector canvas!
    setTimeout(() => {
      if (!mapReady && !switchedOffline) {
        switchedOffline = true;
        console.info('Switching to QYRAN Offline Tactical Map style (air-gapped mode)');
        map.setStyle(OFFLINE_TACTICAL_STYLE);
      }
    }, 4500);

    // Click anywhere on 3D map to inspect GPS + grid square & quick-plot test incident
    map.on('click', (e) => {
      if (!state || !state.scenario) return;
      const { lng, lat } = e.lngLat;
      const g = state.scenario.grid;
      const col = Math.floor((lng - g.lon0) / g.dlon);
      const row = Math.floor((g.lat1 - lat) / g.dlat);
      const sq = col >= 0 && col < g.cols && row >= 0 && row < g.rows ? row * g.cols + col + 1 : null;
      const sqTxt = sq ? `Квадрат ${sq}` : 'Вне сетки';
      const draftCmd = sq ? `Квадрат ${sq}, обнаружен дрон, высота 150 метров` : `Пожар в районе ${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      new maplibregl.Popup({ offset: 8 })
        .setLngLat([lng, lat])
        .setHTML(
          `<div style="font-weight:700;color:#fff;margin-bottom:3px">📍 ${sqTxt}</div>
           <div class="mono" style="font-size:10.5px;color:#93c5fd">${lat.toFixed(5)}, ${lng.toFixed(5)}</div>
           <button class="sm blue" style="margin-top:7px;width:100%" onclick="window.__prefillCmd('${esc(draftCmd)}')">🎙 Тест-доклад сюда</button>`
        )
        .addTo(map);
    });
  }

  window.__prefillCmd = (cmd) => {
    $('#txtInput').value = cmd;
    $('#txtInput').focus();
  };

  function ensure3DBuildings() {
    try {
      const style = map.getStyle();
      const has3d = (style.layers || []).some((l) => l.type === 'fill-extrusion');
      if (!has3d && map.getSource('openmaptiles')) {
        map.addLayer({
          id: 'qyran-3d-buildings',
          type: 'fill-extrusion',
          source: 'openmaptiles',
          'source-layer': 'building',
          minzoom: 12.2,
          paint: {
            'fill-extrusion-color': '#1b273b',
            'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 14],
            'fill-extrusion-base': ['coalesce', ['get', 'render_min_height'], 0],
            'fill-extrusion-opacity': 0.84,
          },
        });
      }
    } catch {}
  }

  function setupMapSources() {
    const emptyFC = { type: 'FeatureCollection', features: [] };
    ['grid', 'hot-grid', 'zones', 'drone-track', 'forecast', 'unit-routes'].forEach((id) => {
      if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data: emptyFC });
    });
    if (!map.getLayer('grid-lines')) {
      map.addLayer({ id: 'grid-lines', type: 'line', source: 'grid', paint: { 'line-color': '#38bdf8', 'line-opacity': 0.24, 'line-dasharray': [2, 2] } });
      map.addLayer({ id: 'hot-grid-fill', type: 'fill', source: 'hot-grid', paint: { 'fill-color': '#ff3b30', 'fill-opacity': 0.16 } });
      map.addLayer({ id: 'zones-fill', type: 'fill', source: 'zones', paint: { 'fill-color': '#ff3b30', 'fill-opacity': 0.12 } });
      map.addLayer({ id: 'zones-line', type: 'line', source: 'zones', paint: { 'line-color': '#ff3b30', 'line-width': 2, 'line-dasharray': [3, 2] } });
      map.addLayer({
        id: 'unit-routes-line',
        type: 'line',
        source: 'unit-routes',
        paint: { 'line-color': ['coalesce', ['get', 'color'], '#38bdf8'], 'line-width': 3.5, 'line-opacity': 0.88, 'line-dasharray': [1.2, 1.2] },
      });
      map.addLayer({ id: 'drone-track-line', type: 'line', source: 'drone-track', paint: { 'line-color': '#ff3b30', 'line-width': 3.5 } });
      map.addLayer({ id: 'forecast-line', type: 'line', source: 'forecast', paint: { 'line-color': '#f59e0b', 'line-width': 2.5, 'line-dasharray': [2, 2] } });
    }
  }

  function buildGridGeo(g) {
    const features = [];
    for (let r = 0; r < g.rows; r++) {
      for (let c = 0; c < g.cols; c++) {
        const x = g.lon0 + c * g.dlon;
        const y = g.lat1 - r * g.dlat;
        const n = r * g.cols + c + 1;
        features.push({
          type: 'Feature',
          properties: { n },
          geometry: { type: 'Polygon', coordinates: [[[x, y], [x + g.dlon, y], [x + g.dlon, y - g.dlat], [x, y - g.dlat], [x, y]]] },
        });
      }
    }
    return { type: 'FeatureCollection', features };
  }

  function circlePolygon(center, radiusM, steps = 48) {
    const pts = [];
    for (let i = 0; i <= steps; i++) {
      const a = (i / steps) * Math.PI * 2;
      pts.push([
        center[0] + (radiusM / (111320 * Math.cos((center[1] * Math.PI) / 180))) * Math.cos(a),
        center[1] + (radiusM / 110540) * Math.sin(a),
      ]);
    }
    return pts;
  }

  function destinationPoint(origin, headingDeg, distM) {
    const rad = (headingDeg * Math.PI) / 180;
    return [
      origin[0] + (distM * Math.sin(rad)) / (111320 * Math.cos((origin[1] * Math.PI) / 180)),
      origin[1] + (distM * Math.cos(rad)) / 110540,
    ];
  }

  function syncMapWithState() {
    if (!mapReady || !state) return;
    const sc = state.scenario;

    if (lastRenderedScenarioId !== sc.id) {
      lastRenderedScenarioId = sc.id;
      selectedFloor = null;
      map.flyTo({ center: sc.center, zoom: sc.zoom, pitch: sc.pitch, bearing: sc.bearing, speed: 1.4 });
      const gfc = buildGridGeo(sc.grid);
      map.getSource('grid').setData(gfc);
      gridLabelMarkers.forEach((m) => m.remove());
      gridLabelMarkers = [];
      gfc.features.forEach((f) => {
        const el = document.createElement('div');
        el.style.cssText = 'font:700 10px Unbounded,sans-serif;color:rgba(56,189,248,.58);pointer-events:none';
        el.textContent = 'КВ ' + f.properties.n;
        gridLabelMarkers.push(
          new maplibregl.Marker({ element: el, anchor: 'top-left', offset: [4, 4] })
            .setLngLat(f.geometry.coordinates[0][0])
            .addTo(map)
        );
      });
      Object.values(unitMarkers).forEach((m) => m.remove());
      unitMarkers = {};
      Object.values(activeAnimations).forEach((id) => cancelAnimationFrame(id));
      activeAnimations = {};
    }

    const gfc = buildGridGeo(sc.grid);
    map.getSource('hot-grid').setData({
      type: 'FeatureCollection',
      features: gfc.features.filter((f) => (state.hot_squares || []).includes(f.properties.n)),
    });
    map.getSource('zones').setData({
      type: 'FeatureCollection',
      features: (state.perimeter_zones || []).map((z) => ({
        type: 'Feature',
        properties: { label: z.label },
        geometry: { type: 'Polygon', coordinates: [circlePolygon(z.center, z.radius_m)] },
      })),
    });
    map.getSource('drone-track').setData({
      type: 'FeatureCollection',
      features: (state.drone_track || []).length >= 2 ? [{ type: 'Feature', geometry: { type: 'LineString', coordinates: state.drone_track } }] : [],
    });

    const fcFeats = [];
    (state.incidents || []).forEach((inc) => {
      if (inc.status !== 'active') return;
      if (inc.target_coords) {
        fcFeats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [inc.coords, inc.target_coords] } });
      } else if (inc.heading_deg != null) {
        fcFeats.push({ type: 'Feature', geometry: { type: 'LineString', coordinates: [inc.coords, destinationPoint(inc.coords, inc.heading_deg, 1600)] } });
      }
    });
    map.getSource('forecast').setData({ type: 'FeatureCollection', features: fcFeats });

    const rColors = { fire: '#fb923c', pol: '#818cf8', med: '#ffffff', grid: '#facc15', own: '#38bdf8' };
    const rFeats = [];
    Object.entries(state.units || {}).forEach(([name, u]) => {
      if (u.active_route && sc.routes && sc.routes[u.active_route]) {
        rFeats.push({
          type: 'Feature',
          properties: { unit: name, color: rColors[u.cls] || '#38bdf8' },
          geometry: { type: 'LineString', coordinates: sc.routes[u.active_route].coords },
        });
      }
    });
    map.getSource('unit-routes').setData({ type: 'FeatureCollection', features: rFeats });

    threatMarkers.forEach((m) => m.remove());
    threatMarkers = [];
    (state.incidents || []).forEach((inc) => {
      const el = document.createElement('div');
      const colorCls = inc.status === 'resolved' ? 'grn' : inc.priority === 1 ? 'red' : 'amb';
      el.className = 'mk ' + colorCls;
      el.style.display = mapFilter === 'own' ? 'none' : '';
      const sensorBadge =
        inc.sensor_status === 'ok'
          ? `<span style="color:#4ade80">✔ ${esc(inc.sensor_label)}</span>`
          : `<span style="color:#fbbf24">⚠ Только голос (перепроверить)</span>`;
      const html = `
        <div style="font-weight:700;color:#fff;margin-bottom:3px">#${inc.id} · ${esc(inc.kind_label_ru)} [P${inc.priority}]</div>
        <div>📍 ${esc(inc.location_label)}</div>
        ${inc.floor ? `<div>🏢 Этаж: ${inc.floor}</div>` : ''}
        ${inc.count ? `<div>👥 Кол-во: ~${inc.count}</div>` : ''}
        ${inc.altitude_m ? `<div>↑ Высота: ${inc.altitude_m} м</div>` : ''}
        <div style="margin-top:4px;font-size:11px">${sensorBadge}</div>
        <div style="margin-top:4px;font-size:10px;color:#c4b5fd">🤖 AI-Assisted · Conf ${Math.round((inc.confidence || 0.85) * 100)}%</div>
      `;
      threatMarkers.push(
        new maplibregl.Marker({ element: el })
          .setLngLat(inc.coords)
          .setPopup(new maplibregl.Popup({ offset: 12 }).setHTML(html))
          .addTo(map)
      );
    });

    Object.entries(state.units || {}).forEach(([name, u]) => {
      if (!unitMarkers[name]) {
        const el = document.createElement('div');
        el.className = 'unit-mk ' + (u.cls || '');
        el.textContent = name;
        unitMarkers[name] = new maplibregl.Marker({ element: el })
          .setLngLat(u.pos)
          .setPopup(new maplibregl.Popup({ offset: 10 }).setHTML(`<b>${esc(name)}</b><br>${esc(u.role)}<br>Статус: ${esc(u.status)}`))
          .addTo(map);
      }
      unitMarkers[name].getElement().style.display = mapFilter === 'thr' ? 'none' : '';
    });
  }

  function animateUnitRoute(unitName, routeCoords, durationMs = 11000) {
    if (!unitMarkers[unitName] || !routeCoords || routeCoords.length < 2) return;
    if (activeAnimations[unitName]) cancelAnimationFrame(activeAnimations[unitName]);
    const t0 = performance.now();
    const step = (now) => {
      const p = Math.min(1, (now - t0) / durationMs);
      const exact = p * (routeCoords.length - 1);
      const i = Math.min(routeCoords.length - 2, Math.floor(exact));
      const f = exact - i;
      const a = routeCoords[i];
      const b = routeCoords[i + 1];
      unitMarkers[unitName].setLngLat([a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]);
      if (p < 1) activeAnimations[unitName] = requestAnimationFrame(step);
    };
    activeAnimations[unitName] = requestAnimationFrame(step);
  }

  function flyTo(coords, zoom = 15.1) {
    if (mapReady && coords) map.flyTo({ center: coords, zoom, speed: 1.15, essential: true });
  }

  // =========================================================================
  // 3. Waveform & Stage Indicators
  // =========================================================================
  function drawWaveform(bars, color = '#38bdf8') {
    const cv = $('#wave');
    if (!cv) return;
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, cv.width, cv.height);
    const n = bars.length || 64;
    const bw = cv.width / n;
    ctx.fillStyle = color;
    for (let i = 0; i < n; i++) {
      const v = Math.max(0.06, Math.min(1, bars[i] || 0.06));
      const bh = v * (cv.height - 12);
      ctx.fillRect(i * bw + 2, (cv.height - bh) / 2, Math.max(2, bw - 4), bh);
    }
  }

  function setStage(step) {
    for (let i = 1; i <= 4; i++) {
      const el = $('#st' + i);
      if (el) el.className = i < step ? 'dn' : i === step ? 'on' : '';
    }
  }

  function flashBanner(text) {
    const el = $('#flash-banner');
    el.innerHTML = `🚨 ${esc(text)}`;
    el.style.display = 'block';
    clearTimeout(el._t);
    el._t = setTimeout(() => (el.style.display = 'none'), 5200);
  }

  // =========================================================================
  // 4. Render All UI Panels
  // =========================================================================
  function renderAll() {
    if (!state) return;
    applyI18n();
    const sc = state.scenario;
    const k = state.kpis;

    $('#scenarioSel').value = sc.id;
    $('#clock').textContent = state.sim_time;
    $('#kThr').textContent = k.active_threats;
    $('#kHitl').textContent = k.pending_hitl;
    $('#kLawScore').textContent = state.compliance.compliance_score_pct + '%';
    $('#avgLat').textContent = k.avg_asr_ms ? `avg ${k.avg_asr_ms} ms` : 'ready';
    $('#chipHitl').className = 'chip ' + (k.pending_hitl > 0 ? 'warn' : 'ok');

    renderClipStrip();
    renderSampleChips();
    renderFeed();
    renderHitlOverlay();
    renderOpsTab();
    renderVisionResults();
    renderLawTab();
    renderRoiAndDispatchTab();
    renderFooter();
    syncMapWithState();
    renderBuildingControls();
    if (state.last_benchmark) renderBenchmark(state.last_benchmark);
  }

  function renderClipStrip() {
    const strip = $('#clipStrip');
    const seenIds = new Set((state.transmissions || []).map((t) => t.clip_id).filter(Boolean));
    strip.innerHTML = (state.scenario.clips || [])
      .map(
        (c) =>
          `<span class="clip-pill ${seenIds.has(c.id) ? 'done' : ''}" data-cid="${c.id}" title="${esc(c.from)} → ${esc(c.to)} [${c.lang}]">${c.id}·${c.lang}</span>`
      )
      .join('');
    strip.querySelectorAll('.clip-pill').forEach((el) => {
      el.onclick = () => processSingleClip(el.dataset.cid, true);
    });
  }

  function renderSampleChips() {
    const box = $('#sampleChips');
    box.innerHTML = (state.scenario.sample_commands || [])
      .map((cmd) => `<span class="schip" title="${esc(cmd)}">${esc(cmd.slice(0, 38))}${cmd.length > 38 ? '…' : ''}</span>`)
      .join('');
    box.querySelectorAll('.schip').forEach((el, idx) => {
      el.onclick = () => sendTextCommand(state.scenario.sample_commands[idx]);
    });
  }

  function renderDiffHtml(diffs) {
    if (!diffs || !diffs.length) return '';
    return diffs
      .map((d) =>
        d.changed
          ? `<span class="fix" title="Сырой Whisper ASR: «${esc(d.orig)}» → исправлено ИИ: «${esc(d.fixed)}»">${esc(d.fixed)}</span>`
          : esc(d.fixed)
      )
      .join(' ');
  }

  function renderFeed() {
    const feed = $('#feed');
    const txs = (state.transmissions || []).slice().reverse();
    if (!txs.length) {
      feed.innerHTML = `<div class="note" style="margin:12px">${tr(
        'Эфир пуст. Нажмите <b>«▶ Живой эфир (GPU)»</b>, нажмите <b>[Space]</b> для живого микрофона или кликните по любой точке 3D-карты.',
        'Эфир бос. <b>«▶ Тікелей эфир (GPU)»</b> басыңыз, микрофон үшін <b>[Space]</b> басыңыз немесе 3D картаға басыңыз.'
      )}</div>`;
      return;
    }

    feed.innerHTML = txs
      .map((t) => {
        const pCls = 'p' + (t.priority || 3);
        const sensorTag =
          t.sensor_status === 'ok'
            ? `<span class="tag ok">✔ ${esc(t.sensor_label)}</span>`
            : t.sensor_status === 'unverified'
            ? `<span class="tag unc">⚠ Только голос — перепроверить</span>`
            : `<span class="tag k">🎙 Команда</span>`;
        const hallTag = t.hallucination_recovered
          ? `<span class="tag ai" title="${esc(t.rescore_note || '')}">🛡 Анти-галлюцинация</span>`
          : '';
        const diffHtml = renderDiffHtml(t.diffs) || esc(t.repaired_text);
        const playBtn = t.audio_url
          ? `<button class="sm" style="margin-left:auto" onclick="event.stopPropagation();window.__playUrl('${t.audio_url}')">▶</button>`
          : '';
        const xaiList = (t.xai_factors || []).map((f) => `<li>${esc(f)}</li>`).join('');
        const cJson = t.coords ? `${t.coords[0]},${t.coords[1]}` : '';

        return `
        <div class="msg" onclick="window.__flyCoords('${cJson}')">
          <div class="top">
            <span class="mono">${esc(t.sim_time)}</span>
            <b>${esc(t.from_callsign)}</b> → <span>${esc(t.to_callsign)}</span>
            <span class="tag ${pCls}">P${t.priority}</span>
            <span class="tag">${t.detected_lang === 'kk' ? '🇰🇿 KK' : '🇷🇺 RU'}</span>
            <span class="mono" style="color:var(--blue)">${t.asr_latency_ms}ms</span>
            ${playBtn}
          </div>
          <div class="repaired">${diffHtml}</div>
          ${t.detected_lang === 'kk' ? `<div class="ru">${esc(t.translation_ru)}</div>` : ''}
          <div class="ent">
            <span class="tag k">📍 ${esc(t.location_label)}</span>
            ${t.floor ? `<span class="tag">🏢 ${t.floor} эт.</span>` : ''}
            ${t.count ? `<span class="tag">👥 ${t.count}</span>` : ''}
            ${t.altitude_m ? `<span class="tag">↑ ${t.altitude_m} м</span>` : ''}
            ${sensorTag}
            ${hallTag}
            <span class="tag ai" title="ст. 21 Закона РК № 230-VIII">🤖 ${Math.round((t.confidence || 0.85) * 100)}%</span>
          </div>
          ${
            xaiList
              ? `<details class="xai-det" onclick="event.stopPropagation()">
                   <summary>🔍 XAI объяснение (${t.repaired_count || 0} испр. · SNR ${t.snr_db ?? '—'} дБ)</summary>
                   <ul>${xaiList}</ul>
                 </details>`
              : ''
          }
        </div>`;
      })
      .join('');
  }

  window.__flyCoords = (csv) => {
    if (!csv) return;
    const [lon, lat] = csv.split(',').map(Number);
    if (!Number.isNaN(lon) && !Number.isNaN(lat)) flyTo([lon, lat], 15.3);
  };

  function renderHitlOverlay() {
    const box = $('#hitl-overlay');
    const pending = (state.recommendations || []).filter((r) => r.status === 'PENDING');
    if (!pending.length) {
      box.style.display = 'none';
      return;
    }
    const r = pending[pending.length - 1];
    const etaBadge =
      r.route_eta_min != null
        ? `<span class="tag k">🛣 ${esc(r.unit || '')} · ~${r.route_eta_min} мин (${r.route_dist_km} км · ${esc(r.route_source || 'OSRM')})</span>`
        : '';
    box.style.display = 'block';
    box.innerHTML = `
      <div class="hl-head">
        <h5>⚖️ РЕШЕНИЕ ОПЕРАТОРА (HITL)</h5>
        <span class="tag p${r.priority}">P${r.priority} · ${esc(r.id)}</span>
      </div>
      <div class="hl-body">${esc(uiLang === 'kk' && r.title_kk ? r.title_kk : r.title)}</div>
      <div class="hl-meta">
        ${etaBadge}
        <span class="tag ai">🤖 AI ${Math.round((r.confidence || 0.85) * 100)}%</span>
        ${r.sensor_status === 'ok' ? `<span class="tag ok">✔ ${esc(r.sensor_label)}</span>` : `<span class="tag unc">⚠ Только голос</span>`}
        ${pending.length > 1 ? `<span class="tag">+${pending.length - 1} ещё</span>` : ''}
      </div>
      <div class="hl-law">
        <b>Закон РК № 230-VIII (ст. 19):</b> Система высокого риска — автоисполнение заблокировано. Оператор: <code>${esc(state.operator_name)}</code>.
      </div>
      <div class="hl-actions">
        <button class="grn" onclick="window.__decide('${r.id}','APPROVED')">✔ Утвердить [Enter]</button>
        <button class="pri" onclick="window.__decide('${r.id}','REJECTED')">✖ Отклонить</button>
      </div>
    `;
  }

  function renderOpsTab() {
    const recs = (state.recommendations || []).slice().reverse();
    $('#hitlCntLbl').textContent = recs.filter((r) => r.status === 'PENDING').length + ' / ' + recs.length;
    $('#hitlQueue').innerHTML = recs.length
      ? recs
          .map(
            (r) => `
        <div class="card ${r.status.toLowerCase()}">
          <div class="ctop">
            <span>${esc(r.id)} · ${esc(r.unit || 'Штаб')} ${r.route_eta_min ? `(~${r.route_eta_min} мин)` : ''}</span>
            <span class="badge ${r.status === 'APPROVED' ? 'b-done' : r.status === 'REJECTED' ? 'b-fail' : 'b-warn'}">${r.status}</span>
          </div>
          <div class="cmeta" style="color:#e2e8f0">${esc(r.title)}</div>
          <div class="cmeta">${r.decided_by ? `Оператор: ${esc(r.decided_by)}` : 'Ожидает утверждения человеком (ст. 19)'}</div>
          ${
            r.status === 'PENDING'
              ? `<div class="cact">
                   <button class="sm grn" onclick="window.__decide('${r.id}','APPROVED')">✔ Утвердить</button>
                   <button class="sm pri" onclick="window.__decide('${r.id}','REJECTED')">✖ Отклонить</button>
                 </div>`
              : ''
          }
        </div>`
          )
          .join('')
      : `<div class="sub" style="margin-bottom:8px">Нет рекомендаций ИИ</div>`;

    const tasks = (state.tasks || []).slice().reverse();
    $('#taskCntLbl').textContent = tasks.length;
    const nowSec = Date.now() / 1000;
    $('#taskList').innerHTML = tasks.length
      ? tasks
          .map((k) => {
            const stMap = { new: ['НОВАЯ', 'b-new'], ack: ['ПРИНЯЛ', 'b-on'], go: ['В ПУТИ', 'b-go'], on: ['НА МЕСТЕ', 'b-on'], done: ['ВЫПОЛНЕНО', 'b-done'] };
            const [lbl, cls] = stMap[k.status] || [k.status, 'b-new'];
            const silentSec = k.status === 'new' ? Math.round(nowSec - k.born_ts) : 0;
            const silHtml =
              silentSec >= 12
                ? `<div class="sil-warn"><span>⏳ Молчит ${silentSec} с</span><button class="sm" onclick="window.__pingTask('${k.id}')">↻ Повторить</button></div>`
                : '';
            return `
            <div class="card">
              <div class="ctop"><span>${esc(k.id)} · ${esc(k.unit)}</span><span class="badge ${cls}">${lbl}</span></div>
              <div class="cmeta" style="color:#e2e8f0">${esc(k.text)}</div>
              <div class="cmeta">${esc(k.source)} · ${esc(k.created_time)}</div>
              ${silHtml}
              ${
                k.status !== 'done'
                  ? `<div class="cact">
                       <button class="sm" onclick="window.__setTask('${k.id}','on')">На месте</button>
                       <button class="sm grn" onclick="window.__setTask('${k.id}','done')">✔ Выполнено</button>
                     </div>`
                  : ''
              }
            </div>`;
          })
          .join('')
      : `<div class="sub" style="margin-bottom:8px">Задачи создаются из голосовых приказов и HITL-решений</div>`;

    const units = Object.entries(state.units || {});
    $('#unitCntLbl').textContent = units.length;
    $('#unitList').innerHTML = units
      .map(
        ([name, u]) => `
        <div class="urow" onclick="window.__flyUnit('${esc(name)}')">
          <div>
            <div class="nm">${esc(name)} <span class="sub">· ${esc(u.role)}</span></div>
            <div class="st">${esc(u.status)} · 👥 ${u.crew} · 🔋 ${u.battery}%</div>
          </div>
          <span class="badge b-on">GPS</span>
        </div>`
      )
      .join('');
  }

  // =========================================================================
  // 5. Live 4-Camera CCTV / Thermal Grid + Real Edge-Vision Upload
  // =========================================================================
  let camContexts = [];
  function initCameras() {
    const grid = $('#camsGrid');
    if (!grid) return;
    const defs = [
      ['CAM-01 · Небо / Сфера', 'drone'],
      ['CAM-02 · Павильон C2 (IR)', 'fire_smoke'],
      ['CAM-03 · Южный вход', 'crowd'],
      ['CAM-04 · Энергоузел (IR)', 'infrastructure'],
    ];
    grid.innerHTML = defs
      .map(
        (d, i) => `
      <div class="cam-box" id="camBox${i}">
        <canvas id="camCv${i}" width="260" height="162"></canvas>
        <span class="clb">${d[0]}</span>
        <span class="crec">● REC</span>
      </div>`
      )
      .join('');
    camContexts = defs.map((d, i) => ({
      box: $('#camBox' + i),
      cv: $('#camCv' + i),
      ctx: $('#camCv' + i).getContext('2d'),
      kind: d[1],
      thermal: i === 1 || i === 3,
    }));

    const drawLoop = (t) => {
      const activeKinds = new Set(((state && state.incidents) || []).filter((i) => i.status === 'active').map((i) => i.kind));
      camContexts.forEach((c, idx) => {
        const x = c.ctx;
        const w = c.cv.width;
        const h = c.cv.height;
        const hot = activeKinds.has(c.kind) || (idx === 1 && activeKinds.has('armed'));
        c.box.classList.toggle('alert', hot);

        // Background (thermal blue-violet vs CCTV dark)
        x.fillStyle = c.thermal ? '#091026' : '#090d12';
        x.fillRect(0, 0, w, h);

        // Subtle scanlines & horizon
        x.strokeStyle = 'rgba(148,163,184,0.08)';
        x.beginPath();
        x.moveTo(0, h * 0.62);
        x.lineTo(w, h * 0.62);
        x.stroke();
        const scanY = (t / 25 + idx * 40) % h;
        x.fillStyle = 'rgba(56,189,248,0.07)';
        x.fillRect(0, scanY, w, 2);

        if (hot) {
          const bx = 65 + Math.sin(t / 700 + idx) * 28;
          const by = 48 + Math.cos(t / 900 + idx) * 14;
          const bw = c.kind === 'crowd' ? 110 : 72;
          const bh = c.kind === 'drone' ? 42 : 68;
          if (c.thermal) {
            const grd = x.createRadialGradient(bx + bw / 2, by + bh / 2, 4, bx + bw / 2, by + bh / 2, 46);
            grd.addColorStop(0, 'rgba(255,230,80,0.85)');
            grd.addColorStop(0.45, 'rgba(255,70,30,0.55)');
            grd.addColorStop(1, 'rgba(255,59,48,0)');
            x.fillStyle = grd;
            x.fillRect(0, 0, w, h);
          }
          x.strokeStyle = '#ff3b30';
          x.lineWidth = 2;
          x.strokeRect(bx, by, bw, bh);
          x.fillStyle = '#ff3b30';
          x.fillRect(bx, by - 14, 96, 14);
          x.fillStyle = '#fff';
          x.font = 'bold 9.5px JetBrains Mono, monospace';
          const lbl = c.kind === 'drone' ? 'UAV 0.91' : c.kind === 'fire_smoke' ? 'SMOKE 0.88' : c.kind === 'crowd' ? 'CROWD ~120' : 'HOTSPOT 0.86';
          x.fillText(lbl, bx + 4, by - 4);
        } else {
          x.fillStyle = 'rgba(148,163,184,0.45)';
          x.font = '10px JetBrains Mono, monospace';
          x.fillText('CLEAR · 0 ANOMALIES', 10, h - 10);
        }
      });
      requestAnimationFrame(drawLoop);
    };
    requestAnimationFrame(drawLoop);
  }

  function renderVisionResults() {
    const el = $('#visionResult');
    if (!el || !state) return;
    const list = state.vision_analyses || [];
    if (!list.length) {
      el.innerHTML = '';
      return;
    }
    el.innerHTML = list
      .slice(0, 3)
      .map(
        (v) => `
      <div class="card ${v.verdict === 'ANOMALY_CONFIRMED' ? 'danger' : 'approved'}" style="margin-top:6px">
        <div class="ctop">
          <span>${esc(v.id)} · ${esc(v.filename)}</span>
          <span class="badge ${v.verdict === 'ANOMALY_CONFIRMED' ? 'b-fail' : 'b-pass'}">${v.verdict}</span>
        </div>
        <div class="cmeta">Огонь: <b>${v.fire_area_pct}%</b> · Дым/дымка: <b>${v.smoke_area_pct}%</b> · Разрешение: ${esc(v.resolution)}</div>
        ${(v.detections || []).map((d) => `<div class="cmeta" style="color:#fcd34d">▸ ${esc(d.label_ru)} (conf ${Math.round(d.confidence * 100)}%)</div>`).join('')}
      </div>`
      )
      .join('');
  }

  async function uploadVisionImage(blob, filename) {
    const fd = new FormData();
    fd.append('file', blob, filename);
    const resp = await fetch('/api/ingest/image', { method: 'POST', body: fd });
    if (resp.ok) {
      const res = await resp.json();
      state = res.state;
      playTone(res.analysis.verdict === 'ANOMALY_CONFIRMED' ? 'alert' : 'ok');
      flashBanner(`📷 Edge-Vision (${res.analysis.filename}): ${res.analysis.verdict}`);
      renderAll();
    }
  }

  function triggerSyntheticFireFrameTest() {
    // Generate a real fire/smoke JPEG frame on an offscreen canvas and send it to the REAL PIL+NumPy backend!
    const cv = document.createElement('canvas');
    cv.width = 320;
    cv.height = 200;
    const x = cv.getContext('2d');
    x.fillStyle = '#1e242b';
    x.fillRect(0, 0, 320, 200);
    // Dense gray smoke upper region
    x.fillStyle = '#9aa3ad';
    x.fillRect(20, 10, 280, 95);
    // Bright orange/red flame hotspot
    const g = x.createRadialGradient(175, 130, 8, 175, 130, 62);
    g.addColorStop(0, '#fff275');
    g.addColorStop(0.4, '#ff6b1a');
    g.addColorStop(1, '#b91c1c');
    x.fillStyle = g;
    x.beginPath();
    x.arc(175, 130, 58, 0, Math.PI * 2);
    x.fill();
    cv.toBlob((blob) => {
      if (blob) uploadVisionImage(blob, 'expo_c2_thermal_sample.jpg');
    }, 'image/jpeg', 0.92);
  }

  // =========================================================================
  // 6. Interactive 3D Building with Floor Selector & Plan Dispatch
  // =========================================================================
  const B3 = { ang: 0.62, dragX: null, auto: true };

  function renderBuildingControls() {
    if (!state || !state.building) return;
    const b = state.building;
    if (selectedFloor == null) selectedFloor = b.hot_floor;
    $('#b3dTitle').textContent = b.name;

    const pills = $('#floorPills');
    let html = '';
    for (let f = 1; f <= b.floors; f++) {
      const isHot = f === b.hot_floor;
      const on = f === selectedFloor;
      html += `<button class="sm ${on ? 'blue' : ''}" onclick="window.__pickFloor(${f})">${f} эт.${isHot ? ' 🔥' : ''}</button>`;
    }
    pills.innerHTML = html;

    const sel = $('#b3dUnitSel');
    const curVal = sel.value;
    sel.innerHTML = Object.keys(state.units || {})
      .map((u) => `<option value="${esc(u)}">${esc(u)}</option>`)
      .join('');
    if (curVal && state.units[curVal]) sel.value = curVal;

    $('#b3dNote').innerHTML = `
      <b>Выбран этаж ${selectedFloor} из ${b.floors}</b> (приоритетный очаг: ${b.hot_floor} эт.)<br>
      Внутри: <b>${b.remaining_inside} чел.</b> · Эвакуировано: <b style="color:var(--grn)">${b.evacuated_count} чел.</b><br>
      Датчики: ${(b.sensors || []).map((s) => `<code>${esc(s)}</code>`).join(' · ')}
    `;
  }

  window.__pickFloor = (f) => {
    selectedFloor = f;
    renderBuildingControls();
  };

  function init3DBuilding() {
    const cv = $('#b3d');
    if (!cv) return;
    const ctx = cv.getContext('2d');
    cv.onmousedown = (e) => {
      B3.dragX = e.clientX;
      B3.auto = false;
    };
    window.addEventListener('mouseup', () => (B3.dragX = null));
    cv.onmousemove = (e) => {
      if (B3.dragX != null) {
        B3.ang += (e.clientX - B3.dragX) / 140;
        B3.dragX = e.clientX;
      }
    };

    const iso = (x, y, z) => {
      const c = Math.cos(B3.ang);
      const s = Math.sin(B3.ang);
      const X = x - 340;
      const Y = y - 210;
      const xr = X * c - Y * s;
      const yr = X * s + Y * c;
      const sc = 0.62;
      return [360 + (xr - yr) * 0.87 * sc, 305 + (xr + yr) * 0.5 * sc - z * sc + 50];
    };
    const poly = (pts, fill, stroke) => {
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])));
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      if (stroke) { ctx.strokeStyle = stroke; ctx.stroke(); }
    };

    const loop = (t) => {
      if (B3.auto) B3.ang += 0.002;
      ctx.clearRect(0, 0, cv.width, cv.height);
      const b = (state && state.building) || { floors: 3, hot_floor: 2, remaining_inside: 45, evacuated_count: 0, smoke_active: false, armed_count: 0 };
      const focusF = selectedFloor || b.hot_floor;
      const F = b.floors <= 3 ? 86 : 58;
      const W = 680;
      const H = 420;

      for (let f = 1; f <= b.floors; f++) {
        const z = (f - 1) * F;
        const isHot = f === b.hot_floor;
        const isSel = f === focusF;
        poly(
          [[0, 0], [W, 0], [W, H], [0, H]].map((p) => iso(p[0], p[1], z)),
          isHot ? 'rgba(255,59,48,0.13)' : isSel ? 'rgba(56,189,248,0.12)' : 'rgba(56,189,248,0.04)',
          isHot ? 'rgba(255,59,48,0.9)' : isSel ? '#38bdf8' : 'rgba(56,189,248,0.34)'
        );
        const lb = iso(0, H, z + 10);
        ctx.fillStyle = isHot ? '#ff6b61' : isSel ? '#38bdf8' : '#94a3b8';
        ctx.font = 'bold 12px Inter';
        ctx.fillText(`${f} эт.`, lb[0] - 46, lb[1]);
        if (isSel) {
          [[40, 40, 260, 170], [340, 40, 290, 170], [40, 230, 590, 150]].forEach((r) => {
            poly(
              [[r[0], r[1]], [r[0] + r[2], r[1]], [r[0] + r[2], r[1] + r[3]], [r[0], r[1] + r[3]]].map((p) => iso(p[0], p[1], z)),
              null,
              'rgba(255,255,255,0.2)'
            );
          });
        }
      }

      [[0, 0], [W, 0], [W, H], [0, H]].forEach((p) => {
        ctx.beginPath();
        ctx.moveTo(...iso(p[0], p[1], 0));
        ctx.lineTo(...iso(p[0], p[1], (b.floors - 1) * F + 30));
        ctx.strokeStyle = 'rgba(56,189,248,0.26)';
        ctx.stroke();
      });

      const hotZ = (b.hot_floor - 1) * F;
      [[140, 120], [520, 120], [340, 310]].forEach((n, idx) => {
        const pt = iso(n[0], n[1], hotZ + 2);
        const k = (t / 1000 + idx * 0.45) % 2;
        ctx.strokeStyle = `rgba(56,189,248,${0.65 - k * 0.3})`;
        ctx.beginPath();
        ctx.ellipse(pt[0], pt[1], 8 + k * 24, (8 + k * 24) * 0.5, 0, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = '#38bdf8';
        ctx.fillRect(pt[0] - 3, pt[1] - 3, 6, 6);
      });

      const dots = Math.min(18, Math.max(0, Math.ceil((b.remaining_inside || 0) / 3)));
      for (let i = 0; i < dots; i++) {
        const pt = iso(110 + (i % 6) * 90 + Math.sin(t / 700 + i) * 7, 100 + Math.floor(i / 6) * 100 + Math.cos(t / 900 + i) * 6, hotZ + 5);
        const isArmed = i < (b.armed_count || 0);
        ctx.fillStyle = isArmed ? '#ff3b30' : '#facc15';
        ctx.beginPath();
        ctx.arc(pt[0], pt[1], isArmed ? 6 : 4, 0, Math.PI * 2);
        ctx.fill();
      }

      if (b.smoke_active) {
        const sp = iso(480, 110, hotZ + 12);
        for (let i = 0; i < 6; i++) {
          ctx.fillStyle = `rgba(226,232,240,${0.36 - i * 0.05})`;
          ctx.beginPath();
          ctx.arc(sp[0] + Math.sin(t / 450 + i) * 8, sp[1] - i * 15 - ((t / 35) % 15), 9 + i * 3.5, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      ctx.fillStyle = '#e2e8f0';
      ctx.font = 'bold 12px Inter';
      ctx.fillText(`Этаж очага: ${b.hot_floor} · Внутри: ${b.remaining_inside} чел. · Эвакуировано: ${b.evacuated_count} чел.`, 14, 486);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  }

  // =========================================================================
  // 7. Law Tab, Benchmark Tab, ROI & Exports Tab, Footer
  // =========================================================================
  function renderLawTab() {
    const comp = state.compliance;
    const ch = state.audit_chain;
    $('#lawScoreBig').textContent = comp.compliance_score_pct + '%';
    $('#chkStrictHitl').checked = !!comp.strict_hitl;
    $('#chkPiiRedact').checked = !!comp.pii_redaction_active;
    if (document.activeElement !== $('#inpOperator')) $('#inpOperator').value = state.operator_name || '';

    $('#chainCard').innerHTML = `
      <div class="ctop">
        <span>SQLite SHA-256 Hash Chain</span>
        <span class="badge ${ch.valid ? 'b-pass' : 'b-fail'}">${ch.valid ? '✔ VALID' : '✖ TAMPERED'}</span>
      </div>
      <div class="cmeta">Блоков: <b>${ch.total_blocks}</b> · Внешних облачных AI-вызовов: <b style="color:var(--grn)">${comp.cloud_ai_calls}</b></div>
      <div class="cmeta mono" style="font-size:10px;word-break:break-all;color:#86efac;margin-top:4px">HEAD: ${esc(ch.head_hash)}</div>
    `;

    $('#lawChecks').innerHTML = (comp.checks || [])
      .map(
        (c) => `
        <div class="chk-row">
          <div class="top">
            <span>${esc(uiLang === 'kk' ? c.title_kk : c.title_ru)}</span>
            <span class="badge ${c.status === 'PASS' ? 'b-pass' : c.status === 'WARN' ? 'b-warn' : 'b-fail'}">${c.status}</span>
          </div>
          <div class="art">${esc(c.article)}</div>
          <div class="det">${esc(c.detail)}</div>
        </div>`
      )
      .join('');
  }

  function renderBenchmark(b) {
    const rawW = Math.min(100, Math.max(4, b.wer_raw_pct));
    const repW = Math.min(100, Math.max(3, b.wer_repaired_pct));
    $('#benchContent').innerHTML = `
      <div class="kpi4">
        <div class="kbox"><b style="color:var(--grn)">-${b.wer_relative_reduction_pct}%</b><span>снижение WER (QYRAN)</span></div>
        <div class="kbox"><b style="color:var(--blue)">${b.avg_latency_ms} ms</b><span>задержка (${b.speedup_vs_realtime}× RT)</span></div>
        <div class="kbox"><b>${b.lang_detection_accuracy_pct}%</b><span>точность авто-языка</span></div>
        <div class="kbox"><b style="color:var(--amb)">${b.hallucinations_prevented}</b><span>галлюцинаций перехвачено</span></div>
      </div>
      <div class="wer-bar-wrap">
        <div style="font-weight:700;font-size:11.5px;color:#fff;margin-bottom:4px">WER · ${esc(b.model_id)} (${esc(b.device.toUpperCase())})</div>
        <div class="wer-line"><span class="lbl">Сырой Whisper</span><div class="wer-track"><div class="wer-fill" style="width:${rawW}%;background:var(--red)"></div></div><b class="mono">${b.wer_raw_pct}%</b></div>
        <div class="wer-line"><span class="lbl">QYRAN Repair</span><div class="wer-track"><div class="wer-fill" style="width:${repW}%;background:var(--grn)"></div></div><b class="mono" style="color:var(--grn)">${b.wer_repaired_pct}%</b></div>
        <div class="sub" style="margin-top:4px">CER: ${b.cer_raw_pct}% → <b style="color:var(--grn)">${b.cer_repaired_pct}%</b> · ${b.clips_evaluated} клипов (${b.total_audio_sec} с аудио)</div>
      </div>
      <table class="btable">
        <thead><tr><th>Клип</th><th>Яз</th><th>Класс</th><th>WER</th><th>ms</th></tr></thead>
        <tbody>
          ${b.rows
            .map(
              (r) => `<tr><td class="mono"><b>${r.id}</b>${r.hallucination_recovered ? ' 🛡' : ''}</td><td>${r.lang_detected}</td><td>${esc(r.extracted_kind)}</td><td class="mono">${r.wer_raw_pct}% → <b style="color:var(--grn)">${r.wer_repaired_pct}%</b></td><td class="mono">${r.latency_ms}</td></tr>`
            )
            .join('')}
        </tbody>
      </table>`;
  }

  function updateRoiCalculator() {
    const fac = Number($('#rngFac').value || 10);
    const price = Number($('#rngPrice').value || 4.5);
    const arrKzt = fac * price;
    const arrUsd = Math.round((arrKzt * 1000000) / 500 / 1000);
    $('#lblFac').textContent = fac;
    $('#lblPrice').textContent = price.toFixed(1) + ' млн ₸';
    $('#roiArrKzt').textContent = arrKzt.toFixed(1) + ' млн ₸';
    $('#roiArrUsd').textContent = `~$${arrUsd}K`;
  }

  function renderRoiAndDispatchTab() {
    const a = state.analytics || { manual_cycle_sec: 135, qyran_avg_sec: 0.75, speedup_factor: 180, time_saved_sec: 0, latency_series: [] };
    const k = state.kpis;
    $('#roiLiveKpis').innerHTML = `
      <div class="kbox"><b style="color:var(--grn)">${a.speedup_factor}×</b><span>быстрее ручного цикла (135с → ${a.qyran_avg_sec}с)</span></div>
      <div class="kbox"><b style="color:var(--blue)">${Math.round(a.time_saved_sec / 60)} мин</b><span>сэкономлено за эту сессию (${a.time_saved_sec} с)</span></div>
      <div class="kbox"><b style="color:var(--amb)">${k.repaired_words_total || 0}</b><span>радиоискажений исправлено ИИ</span></div>
      <div class="kbox"><b>${k.hallucinations_prevented || 0}</b><span>галлюцинаций Whisper остановлено</span></div>
    `;

    // Crisp inline SVG latency chart
    const ser = a.latency_series || [];
    if (ser.length) {
      const mx = Math.max(400, ...ser.map((x) => x.ms));
      const bw = Math.floor(340 / ser.length) - 4;
      const bars = ser
        .map((pt, i) => {
          const h = Math.max(8, Math.round((pt.ms / mx) * 64));
          const x = i * (bw + 4) + 6;
          const color = pt.lang === 'kk' ? '#38bdf8' : '#a78bfa';
          return `<rect x="${x}" y="${72 - h}" width="${Math.max(8, bw)}" height="${h}" rx="3" fill="${color}"><title>${pt.id}: ${pt.ms} ms (${pt.lang})</title></rect>`;
        })
        .join('');
      $('#latChartCard').innerHTML = `
        <div class="ctop"><span>⏱ Задержка Whisper GPU по сообщениям (ms)</span><span class="sub">🔵 KK · 🟣 RU</span></div>
        <svg viewBox="0 0 360 80" style="width:100%;height:76px;margin-top:6px">${bars}</svg>
      `;
    } else {
      $('#latChartCard').innerHTML = `<div class="sub">График задержки GPU заполнится после первых радиосообщений</div>`;
    }

    updateRoiCalculator();

    const services = [
      ['ЦОУ 112 / ДЧС', '🛰', 'Оперативный дежурный'],
      ['Пожарные 101', '🚒', 'Пожарный расчёт ПСЧ'],
      ['Полиция 102', '🚓', 'Кордон и эвакуация'],
      ['Скорая 103', '🚑', 'Бригада СМП'],
      ['Астана-РЭК / Энерго', '⚡', 'Аварийная бригада 110 кВ'],
      ['Мониторинг БПЛА', '📡', 'Безопасность возд. зоны'],
    ];
    $('#svcGrid').innerHTML = services
      .map((s) => `<button class="svc-btn" onclick="window.__dispatch('${esc(s[0])}')"><span>${s[1]} ${esc(s[0])}</span><small>${esc(s[2])}</small></button>`)
      .join('');

    const logs = state.dispatches || [];
    $('#dispatchLog').innerHTML = logs
      .map(
        (d) => `
      <div class="card approved">
        <div class="ctop"><span>${esc(d.reg_no)} · ${esc(d.service)}</span><span class="badge b-done">${esc(d.channel.toUpperCase())}</span></div>
        <div class="cmeta" style="color:#e2e8f0">${esc(d.summary)}</div>
        <div class="cmeta">📍 ${esc(d.location)} · ${esc(d.time)} · ✅ ${esc(d.status)}</div>
      </div>`
      )
      .join('');
  }

  function renderFooter() {
    const ch = state.audit_chain;
    const badge = $('#footChainBadge');
    badge.className = 'badge ' + (ch.valid ? 'b-pass' : 'b-fail');
    badge.textContent = ch.valid ? `✔ SHA-256 VALID (${ch.total_blocks})` : '✖ BROKEN';

    $('#auditList').innerHTML = (state.audit_log || [])
      .slice()
      .reverse()
      .map(
        (r) => `
      <div class="audit-row" title="prev: ${esc(r.prev_hash)}\nhash: ${esc(r.entry_hash)}">
        <span class="seq">#${r.seq}</span>
        <span class="tm">${esc(r.sim_time)}</span>
        <span class="act">${esc(r.actor)}</span>
        <span class="sum">[${esc(r.event_type)}] ${esc(r.summary)}</span>
        <span class="hsh">${esc(r.entry_hash.slice(0, 10))}…</span>
      </div>`
      )
      .join('');

    const k = state.kpis;
    $('#bMsg').textContent = k.messages;
    $('#bThr').textContent = k.active_threats;
    $('#bKk').textContent = k.kk_share_pct + '%';
    $('#bMs').textContent = k.avg_asr_ms + ' ms';

    const recent = (state.transmissions || []).slice(-5).reverse();
    $('#brief-list').innerHTML = recent.length
      ? recent.map((t) => `<li><b>${esc(t.sim_time)}</b> ${esc(t.summary_ru)}</li>`).join('')
      : '<li>Система на дежурстве. Ожидание радиодокладов…</li>';
  }

  // =========================================================================
  // 8. Backend Calls (Clips, Mic PTT, Audio Upload, Text, HITL, Tamper, Benchmark)
  // =========================================================================
  window.__playUrl = (url) => {
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    currentAudio = new Audio(url);
    currentAudio.play().catch(() => {});
  };

  async function processSingleClip(clipId, playSound = true) {
    if (!state) return;
    const sc = state.scenario;
    const clip = (sc.clips || []).find((c) => c.id === clipId);
    if (!clip) return;

    $('#airState').className = 'air-status live';
    $('#airState').textContent = '● В ЭФИРЕ (WHISPER GPU)';
    $('#airFrom').textContent = clip.from;
    $('#airTo').textContent = clip.to;
    $('#airTelemetry').textContent = `${clip.id}.wav · ${clip.lang.toUpperCase()}`;
    setStage(1);

    const pill = $(`.clip-pill[data-cid="${clipId}"]`);
    if (pill) pill.classList.add('active');

    let audioDone = Promise.resolve();
    if (playSound) {
      const audio = new Audio(`/api/audio/${sc.id}/${clip.filename}`);
      currentAudio = audio;
      audioDone = new Promise((res) => {
        audio.onended = res;
        audio.onerror = res;
        audio.play().catch(res);
      });
    }

    let animActive = true;
    const waveAnim = () => {
      if (!animActive) return;
      drawWaveform(Array.from({ length: 64 }, () => 0.14 + Math.random() * 0.8), '#ff3b30');
      requestAnimationFrame(waveAnim);
    };
    waveAnim();

    setStage(2);
    const langMode = $('#asrLangSel').value || 'auto';
    const resp = await fetch(`/api/scenarios/${sc.id}/clip/${clipId}?lang_mode=${langMode}`, { method: 'POST' });
    if (!resp.ok) { animActive = false; return; }
    setStage(3);
    const res = await resp.json();
    state = res.state;
    setStage(4);
    animActive = false;

    if (res.transmission) {
      if (res.transmission.waveform && res.transmission.waveform.length) {
        staticWave = res.transmission.waveform;
        drawWaveform(staticWave, '#38bdf8');
      }
      $('#airTelemetry').textContent = `${res.transmission.asr_latency_ms}ms · SNR ${res.transmission.snr_db}dB · ${Math.round(res.transmission.asr_confidence * 100)}%`;
      $('#nowTxt').textContent = `${res.transmission.summary_ru} (${res.transmission.from_callsign})`;
      if (res.transmission.priority <= 2) {
        flashBanner(res.transmission.summary_ru);
        playTone('alert');
        if (res.transmission.priority === 1) speakNotice(res.transmission.summary_ru);
      }
      if (res.transmission.coords) flyTo(res.transmission.coords, 15.0);
    }
    renderAll();

    if (playSound) await audioDone;
    $('#airState').className = 'air-status idle';
    $('#airState').textContent = 'ожидание';
  }

  async function runFullScenario() {
    if (scenarioRunning || !state) return;
    scenarioRunning = true;
    stopRequested = false;
    $('#btnRunScenario').disabled = true;
    $('#btnStopScenario').disabled = false;

    for (const c of state.scenario.clips || []) {
      if (stopRequested) break;
      await processSingleClip(c.id, true);
      if (stopRequested) break;
      await new Promise((r) => setTimeout(r, 850));
    }

    scenarioRunning = false;
    $('#btnRunScenario').disabled = false;
    $('#btnStopScenario').disabled = true;
    if (!stopRequested) {
      playTone('ok');
      $('#nowTxt').textContent = '✅ Живой сценарий завершён. Утвердите HITL-решения [Enter] или откройте «🖨 PDF Отчёт».';
    }
  }

  async function toggleMicRecording() {
    const btn = $('#btnPtt');
    if (isRecording) {
      isRecording = false;
      btn.classList.remove('rec');
      btn.textContent = I18N[uiLang].btn_ptt;
      playTone('ptt');
      if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
      if (micStream) micStream.getTracks().forEach((t) => t.stop());
      if (micAnimFrame) cancelAnimationFrame(micAnimFrame);
      return;
    }

    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      playTone('ptt');
      const actx = new (window.AudioContext || window.webkitAudioContext)();
      const src = actx.createMediaStreamSource(micStream);
      micAnalyser = actx.createAnalyser();
      micAnalyser.fftSize = 128;
      src.connect(micAnalyser);

      audioChunks = [];
      mediaRecorder = new MediaRecorder(micStream);
      mediaRecorder.ondataavailable = (e) => { if (e.data && e.data.size > 0) audioChunks.push(e.data); };
      mediaRecorder.onstop = async () => {
        const blob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
        await uploadAudioBlob(blob, 'mic_ptt.webm');
        actx.close().catch(() => {});
      };
      mediaRecorder.start();
      isRecording = true;
      btn.classList.add('rec');
      btn.textContent = '🔴 ЗАПИСЬ — [Space] отправить';
      $('#airState').className = 'air-status live';
      $('#airState').textContent = '● ЗАПИСЬ МИКРОФОНА';

      const buf = new Uint8Array(micAnalyser.frequencyBinCount);
      const drawLive = () => {
        if (!isRecording) return;
        micAnalyser.getByteFrequencyData(buf);
        drawWaveform(Array.from(buf).slice(0, 64).map((v) => Math.max(0.06, v / 255)), '#ff3b30');
        micAnimFrame = requestAnimationFrame(drawLive);
      };
      drawLive();
    } catch (err) {
      alert('Нет доступа к микрофону: ' + err.message);
    }
  }

  async function uploadAudioBlob(blob, filename) {
    $('#airState').className = 'air-status proc';
    $('#airState').textContent = 'WHISPER GPU…';
    $('#airFrom').textContent = 'Живой микрофон / файл';
    setStage(2);

    const fd = new FormData();
    fd.append('file', blob, filename);
    fd.append('lang', $('#asrLangSel').value || 'auto');
    fd.append('radio_degrade', $('#chkRadioDegrade').checked ? 'true' : 'false');

    const resp = await fetch('/api/ingest/audio', { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      flashBanner('Ошибка аудио: ' + (err.detail || resp.statusText));
      $('#airState').className = 'air-status idle';
      $('#airState').textContent = 'ошибка';
      return;
    }
    const res = await resp.json();
    state = res.state;
    setStage(4);
    if (res.transmission) {
      if (res.transmission.waveform && res.transmission.waveform.length) drawWaveform(res.transmission.waveform, '#22c55e');
      $('#airTelemetry').textContent = `${res.transmission.asr_latency_ms}ms · SNR ${res.transmission.snr_db}dB`;
      $('#nowTxt').textContent = `${res.transmission.summary_ru} — «${res.transmission.repaired_text}»`;
      playTone(res.transmission.priority <= 2 ? 'alert' : 'ok');
      if (res.transmission.coords) flyTo(res.transmission.coords, 15.0);
    }
    $('#airState').className = 'air-status idle';
    $('#airState').textContent = 'готово';
    renderAll();
  }

  async function sendTextCommand(text) {
    const clean = (text || '').trim();
    if (!clean) return;
    setStage(3);
    const resp = await fetch('/api/ingest/text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean, lang: $('#asrLangSel').value || 'auto' }),
    });
    if (resp.ok) {
      const res = await resp.json();
      state = res.state;
      setStage(4);
      if (res.transmission) {
        $('#nowTxt').textContent = res.transmission.summary_ru;
        playTone(res.transmission.priority <= 2 ? 'alert' : 'ok');
        if (res.transmission.coords) flyTo(res.transmission.coords, 15.0);
      }
      renderAll();
    }
  }

  window.__decide = async (recId, decision) => {
    const op = ($('#inpOperator') && $('#inpOperator').value) || state.operator_name;
    const resp = await fetch(`/api/recommendations/${recId}/decide`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, operator: op }),
    });
    if (resp.ok) {
      const res = await resp.json();
      state = res.state;
      playTone('ok');
      renderAll();
      if (res.dispatched_unit && res.dispatched_unit.route) {
        const rt = res.dispatched_unit.route;
        animateUnitRoute(res.dispatched_unit.unit, rt.coords, 11000);
        flashBanner(`✔ ${res.dispatched_unit.unit} направлен (${(rt.dist / 1000).toFixed(1)} км · ~${Math.max(1, Math.round(rt.dur / 60))} мин · ${rt.source})`);
      }
    }
  };

  window.__setTask = async (tid, status) => {
    const resp = await fetch(`/api/tasks/${tid}/status`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
    if (resp.ok) { state = (await resp.json()).state; renderAll(); }
  };

  window.__pingTask = async (tid) => {
    const resp = await fetch(`/api/tasks/${tid}/ping`, { method: 'POST' });
    if (resp.ok) { state = (await resp.json()).state; playTone('ptt'); flashBanner(`↻ Повторный радиовызов по ${tid}`); renderAll(); }
  };

  window.__flyUnit = (name) => { if (state && state.units && state.units[name]) flyTo(state.units[name].pos, 15.8); };

  window.__dispatch = async (service) => {
    const resp = await fetch('/api/dispatch/service', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ service, channel: selectedChannel }) });
    if (resp.ok) {
      const res = await resp.json();
      state = res.state;
      playTone('ok');
      flashBanner(`📤 ${res.dispatch.service} (${res.dispatch.reg_no}) · ${res.dispatch.location}`);
      renderAll();
    }
  };

  async function switchScenario(sid) {
    stopRequested = true;
    $('#tamperResult').innerHTML = '';
    const resp = await fetch(`/api/scenarios/${sid}/activate`, { method: 'POST' });
    if (resp.ok) {
      state = await resp.json();
      $('#nowTxt').textContent = `Активирован сценарий: ${state.scenario.title_ru}`;
      renderAll();
    }
  }

  async function runLiveBenchmark() {
    const btn = $('#btnRunBench');
    btn.disabled = true;
    btn.textContent = '⏳ GPU…';
    $('#benchContent').innerHTML = `<div class="note">⚡ Выполняется реальный прогон WAV-клипов на локальном Whisper GPU + расчёт WER/CER…</div>`;
    try {
      const resp = await fetch(`/api/benchmark/run?scenario_id=${state.scenario.id}`, { method: 'POST' });
      if (resp.ok) {
        const res = await resp.json();
        state.last_benchmark = res;
        playTone('ok');
        renderBenchmark(res);
        const stResp = await fetch('/api/state');
        if (stResp.ok) { state = await stResp.json(); renderFooter(); renderLawTab(); }
      }
    } finally {
      btn.disabled = false;
      btn.textContent = '▶ Запустить';
    }
  }

  async function runStressBurst() {
    if (!state) return;
    const btn = $('#btnStressBurst');
    btn.disabled = true;
    btn.textContent = '⚡…';
    try {
      const resp = await fetch(`/api/scenarios/${state.scenario.id}/stress-burst`, { method: 'POST' });
      if (resp.ok) {
        const res = await resp.json();
        state = res.state;
        playTone('alert');
        flashBanner(`⚡ ШКВАЛ ×${res.processed_count} ОБРАБОТАН ЗА ${res.elapsed_ms} мс (вручную: ~${Math.round(res.manual_equivalent_sec / 60)} мин!)`);
        $('#nowTxt').textContent = `⚡ Стресс-тест: ${res.processed_count} параллельных докладов kk/ru нанесены на 3D-карту за ${res.elapsed_ms} мс!`;
        if (mapReady) map.flyTo({ center: state.scenario.center, zoom: state.scenario.zoom - 0.6, pitch: 48 });
        renderAll();
      }
    } finally {
      btn.disabled = false;
      btn.textContent = '⚡ Шквал ×5';
    }
  }

  async function askCopilot(question) {
    const q = (question || '').trim();
    if (!q) return;
    const out = $('#copilotOut');
    out.style.display = 'block';
    out.innerHTML = `<span class="sub">⏳ Анализ оперативной базы…</span>`;
    const resp = await fetch('/api/copilot/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: q, lang: uiLang }),
    });
    if (resp.ok) {
      const res = await resp.json();
      const cites = (res.citations || []).map((c) => `<span class="tag k">${esc(c)}</span>`).join(' ');
      out.innerHTML = `
        <div style="font-weight:700;color:#fff;margin-bottom:4px">🤖 ${esc(res.headline)}</div>
        <ul style="margin-left:15px;color:#cbd5e1">${(res.bullets || []).map((b) => `<li>${esc(b)}</li>`).join('')}</ul>
        <div style="margin-top:6px;display:flex;gap:4px;flex-wrap:wrap;align-items:center">
          ${cites}
          <span class="tag ai" style="margin-left:auto">ст. 21 · Grounded</span>
        </div>`;
      // refresh audit log
      const stR = await fetch('/api/state');
      if (stR.ok) { state = await stR.json(); renderFooter(); }
    }
  }

  async function simulateTamperAttack() {
    const resp = await fetch('/api/audit/simulate-tamper', { method: 'POST' });
    if (!resp.ok) return;
    const t = await resp.json();
    playTone('alert');
    $('#tamperResult').innerHTML = `
      <div class="card danger">
        <div class="ctop"><span>🚨 АТАКА ПОДМЕНЫ ПЕРЕХВАЧЕНА (БЛОК #${t.broken_seq})</span><span class="badge b-fail">TAMPER DETECTED</span></div>
        <div class="cmeta" style="color:#fecaca">${esc(t.reason)}</div>
        <div class="cmeta">Оригинал: <i>${esc(t.original_summary)}</i></div>
        <div class="cmeta">Попытка подмены: <b style="color:#fca5a5">${esc(t.tampered_summary)}</b></div>
        <div class="cmeta mono" style="font-size:9.5px;word-break:break-all;margin-top:4px">
          Хеш в БД: ${esc((t.stored_hash || '').slice(0, 32))}…<br>
          Пересчёт: ${esc((t.recomputed_hash || '').slice(0, 32))}…
        </div>
        <div class="cmeta" style="color:#4ade80;margin-top:4px">✔ Тест выполнен в изолированной копии — рабочая SQLite-цепь не повреждена.</div>
      </div>`;
  }

  // =========================================================================
  // 9. Health, WebSocket, Hotkeys & Event Wiring
  // =========================================================================
  async function pollHealth() {
    try {
      const r = await fetch('/api/health');
      if (!r.ok) return;
      const h = await r.json();
      const dev = h.asr.gpu_name ? h.asr.gpu_name.replace('NVIDIA GeForce ', '').replace(' Laptop GPU', '') : h.asr.device.toUpperCase();
      $('#asrDevice').textContent = h.asr.loaded ? `${dev} ✔` : `${dev}…`;
    } catch {}
  }

  function connectWS() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.event === 'init' || msg.event === 'state_reset' || msg.event === 'state_update') {
          state = msg.data;
          renderAll();
        } else if (msg.data && msg.data.state) {
          state = msg.data.state;
          renderAll();
        }
      } catch {}
    };
    ws.onclose = () => setTimeout(connectWS, 2500);
  }

  function switchTab(tabId) {
    $$('.tabs button').forEach((x) => x.classList.toggle('on', x.dataset.t === tabId));
    $$('.pane').forEach((p) => p.classList.toggle('on', p.id === 'p-' + tabId));
  }

  function bindEvents() {
    $$('.tabs button').forEach((b) => (b.onclick = () => switchTab(b.dataset.t)));
    $('#chipLaw').onclick = () => switchTab('law');
    $('#chipHitl').onclick = () => switchTab('ops');

    $$('#modes button[data-m]').forEach((b) => {
      b.onclick = () => {
        $$('#modes button[data-m]').forEach((x) => x.classList.toggle('on', x === b));
        mapFilter = b.dataset.m;
        syncMapWithState();
      };
    });
    $('#btn3d').onclick = () => { if (mapReady) map.easeTo({ pitch: map.getPitch() > 20 ? 0 : 58, bearing: map.getPitch() > 20 ? 0 : -20 }); };
    $('#btnOverview').onclick = () => { if (mapReady && state) map.flyTo({ center: state.scenario.center, zoom: state.scenario.zoom - 0.5, pitch: state.scenario.pitch, bearing: state.scenario.bearing }); };

    $('#scenarioSel').onchange = (e) => switchScenario(e.target.value);
    $('#btnReset').onclick = () => switchScenario($('#scenarioSel').value);
    $('#btnRunScenario').onclick = runFullScenario;
    $('#btnStressBurst').onclick = runStressBurst;
    $('#btnStopScenario').onclick = () => { stopRequested = true; if (currentAudio) currentAudio.pause(); };

    // Grounded Commander Co-Pilot
    $('#btnAskCopilot').onclick = () => { askCopilot($('#copilotInput').value); $('#copilotInput').value = ''; };
    $('#copilotInput').onkeydown = (e) => { if (e.key === 'Enter') { askCopilot($('#copilotInput').value); $('#copilotInput').value = ''; } };
    $$('#copilotQuick .schip').forEach((el) => (el.onclick = () => askCopilot(el.dataset.q)));
    $('#btnPtt').onclick = toggleMicRecording;
    $('#btnUpload').onclick = () => $('#audioFile').click();
    $('#audioFile').onchange = (e) => { const f = e.target.files[0]; if (f) uploadAudioBlob(f, f.name); e.target.value = ''; };

    $('#btnSendTxt').onclick = () => { sendTextCommand($('#txtInput').value); $('#txtInput').value = ''; };
    $('#txtInput').onkeydown = (e) => { if (e.key === 'Enter') { sendTextCommand($('#txtInput').value); $('#txtInput').value = ''; } };

    // Header utility buttons
    $('#btnPitch').onclick = () => window.open('/pitch', '_blank');
    $('#btnStageXl').onclick = () => {
      document.body.classList.toggle('xl');
      $('#btnStageXl').classList.toggle('on', document.body.classList.contains('xl'));
      setTimeout(() => map && map.resize(), 150);
    };
    $('#btnSfx').onclick = () => {
      sfxEnabled = !sfxEnabled;
      $('#btnSfx').textContent = sfxEnabled ? '🔊' : '🔇';
    };
    $('#btnLang').onclick = () => {
      uiLang = uiLang === 'ru' ? 'kk' : 'ru';
      localStorage.setItem('qyran2_lang', uiLang);
      renderAll();
    };
    $('#btnHelp').onclick = () => $('#helpModal').classList.add('open');
    $('#btnCloseHelp').onclick = () => $('#helpModal').classList.remove('open');
    $('#helpModal').onclick = (e) => { if (e.target === $('#helpModal')) $('#helpModal').classList.remove('open'); };

    // Vision
    $('#btnUploadImg').onclick = () => $('#imgFile').click();
    $('#imgFile').onchange = (e) => { const f = e.target.files[0]; if (f) uploadVisionImage(f, f.name); e.target.value = ''; };
    $('#btnTestFireImg').onclick = triggerSyntheticFireFrameTest;

    // 3D building send plan
    $('#btnSend3dPlan').onclick = async () => {
      const unit = $('#b3dUnitSel').value;
      const fl = selectedFloor || (state && state.building && state.building.hot_floor) || 2;
      const resp = await fetch('/api/building/send-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ unit, floor: fl }),
      });
      if (resp.ok) {
        state = (await resp.json()).state;
        playTone('ok');
        flashBanner(`📤 3D-план этажа ${fl} передан группе ${unit}`);
        renderAll();
      }
    };

    // Compliance
    const pushCompliance = async () => {
      const resp = await fetch('/api/compliance/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ strict_hitl: $('#chkStrictHitl').checked, pii_redaction: $('#chkPiiRedact').checked, operator_name: $('#inpOperator').value }),
      });
      if (resp.ok) { state = await resp.json(); renderAll(); }
    };
    $('#chkStrictHitl').onchange = pushCompliance;
    $('#chkPiiRedact').onchange = pushCompliance;
    $('#btnSaveOp').onclick = pushCompliance;

    $('#btnVerifyChain').onclick = async () => {
      $('#tamperResult').innerHTML = '';
      const r = await fetch('/api/audit/verify');
      if (r.ok) {
        const v = await r.json();
        state.audit_chain = v;
        renderLawTab();
        renderFooter();
        playTone(v.valid ? 'ok' : 'alert');
        flashBanner(v.valid ? `🔐 SHA-256 ЦЕПЬ ПОДТВЕРЖДЕНА (${v.total_blocks}/${v.total_blocks} блоков)` : '⚠ НАРУШЕНИЕ ЦЕЛОСТНОСТИ ЦЕПИ!');
      }
    };
    $('#btnSimTamper').onclick = simulateTamperAttack;

    $('#btnTestPii').onclick = async () => {
      const resp = await fetch('/api/compliance/redact-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: $('#piiInput').value }),
      });
      if (resp.ok) {
        const res = await resp.json();
        const out = $('#piiOutput');
        out.style.display = 'block';
        out.innerHTML = `<b>Скрыто элементов ПДн: ${res.findings_count}</b><br>${esc(res.redacted)}`;
      }
    };

    // Benchmark & ROI Calculator
    $('#btnRunBench').onclick = runLiveBenchmark;
    $('#rngFac').oninput = updateRoiCalculator;
    $('#rngPrice').oninput = updateRoiCalculator;

    // Channel & Exports
    $$('#chanSel button').forEach((b) => {
      b.onclick = () => {
        selectedChannel = b.dataset.ch;
        $$('#chanSel button').forEach((x) => x.classList.toggle('blue', x === b));
      };
    });
    $('#expPdf').onclick = () => window.open('/api/export/report.html', '_blank');
    $('#btnFootPdf').onclick = () => window.open('/api/export/report.html', '_blank');
    $('#expMd').onclick = () => window.open(`/api/export/report.md?lang=${uiLang}`, '_blank');
    $('#btnFootRep').onclick = () => window.open(`/api/export/report.md?lang=${uiLang}`, '_blank');
    $('#expCot').onclick = () => window.open('/api/export/cot.xml', '_blank');
    $('#expGeo').onclick = () => window.open('/api/export/geojson', '_blank');
    $('#expAudit').onclick = () => window.open('/api/export/audit.json', '_blank');
    $('#btnFootAudit').onclick = () => window.open('/api/export/audit.json', '_blank');

    // Stage-ready Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
      const tag = (document.activeElement && document.activeElement.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.code === 'Space') {
        e.preventDefault();
        toggleMicRecording();
      } else if (e.key === 'Enter' && state) {
        const pending = (state.recommendations || []).filter((r) => r.status === 'PENDING');
        if (pending.length) {
          e.preventDefault();
          window.__decide(pending[pending.length - 1].id, 'APPROVED');
        }
      } else if (e.key === 'p' || e.key === 'P') {
        $('#btnStageXl').click();
      } else if (e.key === 'Escape') {
        $('#helpModal').classList.remove('open');
      } else if (['1', '2', '3', '4', '5', '6'].includes(e.key)) {
        const mapTabs = ['ops', 'cams', 'b3d', 'law', 'bench', 'roi'];
        switchTab(mapTabs[Number(e.key) - 1]);
      }
    });
  }

  async function boot() {
    bindEvents();
    drawWaveform(staticWave);
    initCameras();
    init3DBuilding();

    const resp = await fetch('/api/state');
    if (resp.ok) {
      state = await resp.json();
      initMap(state.scenario.center, state.scenario.zoom, state.scenario.pitch, state.scenario.bearing);
      renderAll();
    } else {
      initMap([71.4180, 51.0902], 14.1, 48, -18);
    }

    connectWS();
    pollHealth();
    setInterval(pollHealth, 5000);
    setInterval(() => {
      if (state && (state.tasks || []).some((k) => k.status === 'new')) renderOpsTab();
    }, 1000);
  }

  boot();
})();
