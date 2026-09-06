const DASH_LIMIT = 5;
const ALL_LIMIT = 50;
const TEXT_LIMIT = 75;
const state = { skip: 0, total: 0, query: '', language: 'all', platform: 'all', cache: new Map(), polled: null };
const $ = (selector) => document.querySelector(selector);

function escapeHtml(value = '') { return String(value).replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char])); }
function formatTime(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : `${date.toISOString().slice(0, 19).replace('T', ' ')}Z`; }
function shortTime(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? String(value).slice(0, 11) : date.toISOString().slice(5, 16).replace('T', ' '); }
function formatCount(value) { return Number(value || 0).toLocaleString(); }
function authorName(item) { return item.author?.username || item.author?.display_name || item.author?.user_id || item.author_id || 'unknown'; }

/* ---------------- compact one-line rows ---------------- */

let keySeq = 0;

function platformTag(platform) {
  const value = String(platform || '').toLowerCase();
  const telegram = value.startsWith('tele');
  const label = telegram ? 'TG' : (value.startsWith('tw') || value === 'x') ? 'TW' : (platform || '··').slice(0, 2).toUpperCase();
  return `<span class="pr-plat${telegram ? ' tg' : ''}">${escapeHtml(label)}</span>`;
}

function rowChips(item) {
  const insights = item.ml_insights || item.analytics || {};
  const sentiment = insights.sentiment || {};
  const chips = [];
  if (sentiment.primary_emotion) chips.push(`<i class="chip emotion">${escapeHtml(sentiment.primary_emotion)}</i>`);
  if (typeof sentiment.polarity_score === 'number') chips.push(`<i class="chip ${sentiment.polarity_score < 0 ? 'neg' : 'pos'}">${sentiment.polarity_score.toFixed(2)}</i>`);
  if (typeof insights.risk_score === 'number') chips.push(`<i class="chip risk">r${insights.risk_score}</i>`);
  return `<span class="pr-chips">${chips.join('')}</span>`;
}

function renderRows(items, host, append = false, highlight = null) {
  if (!append) host.innerHTML = '';
  if (!items.length && !append) { host.innerHTML = '<div class="loading">No events match this view.</div>'; return; }
  const html = items.map((item) => {
    const key = item.post_id || `anon-${++keySeq}`;
    state.cache.set(key, item);
    const isNew = highlight ? ' is-new' : '';
    // Collapse newlines so a multi-line post still previews as one clean line.
    const text = String(item.text || item.content || '').replace(/\s+/g, ' ').trim();
    const clipped = text.length > TEXT_LIMIT;
    const preview = clipped ? `${text.slice(0, TEXT_LIMIT).trimEnd()}…` : text;
    return `<button class="post-row${isNew}" type="button" data-key="${escapeHtml(key)}"${text ? ` title="${escapeHtml(text)}"` : ''}>`
      + `<span class="pr-time">${escapeHtml(shortTime(item.timestamp || item.created_at))}</span>`
      + platformTag(item.platform)
      + `<span class="pr-author">@${escapeHtml(authorName(item))}</span>`
      + `<span class="pr-text${text ? '' : ' empty'}">${text ? escapeHtml(preview) : 'no text content'}</span>`
      + `<span class="pr-more">${clipped ? 'more' : ''}</span>`
      + rowChips(item)
      + `<span class="pr-caret">›</span>`
      + `</button>`;
  }).join('');
  host.insertAdjacentHTML('beforeend', html);
}

/* ---------------- detail drawer ---------------- */

function detailItem(label, value) {
  if (value === undefined || value === null || value === '') return '';
  return `<div class="d-item"><span>${escapeHtml(label)}</span><strong>${escapeHtml(String(value))}</strong></div>`;
}

function detailSection(title, inner) {
  const body = Array.isArray(inner) ? inner.filter(Boolean).join('') : inner;
  if (!body) return '';
  const wrapped = Array.isArray(inner) ? `<div class="d-grid">${body}</div>` : body;
  return `<div class="d-section"><h4>${escapeHtml(title)}</h4>${wrapped}</div>`;
}

function emotionBars(distribution = {}) {
  const entries = Object.entries(distribution);
  if (!entries.length) return '';
  const max = Math.max(...entries.map(([, value]) => Number(value) || 0), 0.0001);
  return entries.map(([label, value]) => {
    const score = Number(value) || 0;
    return `<div class="emo-row"><span class="emo-name">${escapeHtml(label)}</span><span class="emo-track"><span class="emo-fill" style="width:${Math.max((score / max) * 100, 3)}%"></span></span><span class="emo-val">${score.toFixed(2)}</span></div>`;
  }).join('');
}

function openDetail(key) {
  const item = state.cache.get(key);
  if (!item) return;
  const insights = item.ml_insights || item.analytics || {};
  const sentiment = insights.sentiment || {};
  const stance = insights.stance || {};
  const demographics = insights.demographics || {};
  const trends = insights.trends || {};
  const network = insights.network_signals || {};
  const burst = insights.burst_signal || {};
  const author = item.author || {};
  const channel = item.channel || {};
  const engagementData = item.engagement || {};
  const text = String(item.text || item.content || '').trim();

  $('#detail-title').textContent = item.post_id || 'Event';
  $('#detail-eyebrow').textContent = `${item.platform || 'UNKNOWN'} / EVENT DETAIL`;
  $('#detail-sub').textContent = formatTime(item.timestamp || item.created_at);

  const keywords = Array.isArray(trends.extracted_keywords) ? trends.extracted_keywords : [];
  const sections = [
    `<p class="drawer-text${text ? '' : ' empty'}">${text ? escapeHtml(text) : 'No text content — media-only post.'}</p>`,
    detailSection('AUTHOR', [
      detailItem('username', author.username),
      detailItem('display name', author.display_name),
      detailItem('user id', author.user_id || item.author_id),
      typeof author.follower_count === 'number' ? detailItem('followers', formatCount(author.follower_count)) : '',
      author.is_bot !== undefined ? detailItem('is bot', String(author.is_bot)) : '',
      detailItem('bio', author.bio),
    ]),
    detailSection('CHANNEL', [
      detailItem('name', channel.channel_name),
      detailItem('id', channel.channel_id),
      detailItem('type', channel.channel_type),
      typeof channel.member_count === 'number' ? detailItem('members', formatCount(channel.member_count)) : '',
    ]),
    detailSection('SENTIMENT', [
      detailItem('primary emotion', sentiment.primary_emotion),
      typeof sentiment.polarity_score === 'number' ? detailItem('polarity', sentiment.polarity_score.toFixed(2)) : '',
      typeof sentiment.confidence === 'number' ? detailItem('confidence', sentiment.confidence.toFixed(2)) : '',
      sentiment.sarcasm_flag !== undefined ? detailItem('sarcasm flag', String(sentiment.sarcasm_flag)) : '',
    ]),
    detailSection('EMOTION DISTRIBUTION', emotionBars(sentiment.emotion_distribution)),
    detailSection('STANCE', [
      detailItem('target entity', stance.target_entity),
      detailItem('label', stance.label),
      typeof stance.confidence === 'number' ? detailItem('confidence', stance.confidence.toFixed(2)) : '',
    ]),
    detailSection('DEMOGRAPHICS', [
      detailItem('age bracket', demographics.inferred_age_bracket),
      detailItem('location', demographics.inferred_location),
      detailItem('profession', demographics.inferred_profession),
      detailItem('language', demographics.language || item.language),
    ]),
    detailSection('TRENDS', [
      detailItem('topic', trends.topic_category),
      detailItem('topic id', trends.topic_id),
    ]),
    keywords.length ? detailSection('KEYWORDS', `<div class="d-chips">${keywords.map((word) => `<i class="chip topic">${escapeHtml(word)}</i>`).join('')}</div>`) : '',
    detailSection('NETWORK SIGNALS', [
      typeof network.bot_likelihood_score === 'number' ? detailItem('bot likelihood', network.bot_likelihood_score) : '',
      typeof network.centrality_seed_weight === 'number' ? detailItem('centrality', network.centrality_seed_weight) : '',
      network.is_potential_kol !== undefined ? detailItem('potential KOL', String(network.is_potential_kol)) : '',
      typeof network.forward_chain_depth === 'number' ? detailItem('forward depth', network.forward_chain_depth) : '',
    ]),
    detailSection('BURST SIGNAL', [
      typeof burst.z_score === 'number' ? detailItem('z-score', burst.z_score) : '',
      burst.is_burst !== undefined ? detailItem('is burst', String(burst.is_burst)) : '',
      typeof insights.risk_score === 'number' ? detailItem('risk score', insights.risk_score) : '',
    ]),
    detailSection('ENGAGEMENT', [
      typeof engagementData.like_count === 'number' ? detailItem('likes', formatCount(engagementData.like_count)) : '',
      typeof engagementData.retweet_count === 'number' ? detailItem('retweets', formatCount(engagementData.retweet_count)) : '',
      typeof engagementData.reply_count === 'number' ? detailItem('replies', formatCount(engagementData.reply_count)) : '',
      typeof engagementData.impression_count === 'number' ? detailItem('impressions', formatCount(engagementData.impression_count)) : '',
      typeof engagementData.views === 'number' ? detailItem('views', formatCount(engagementData.views)) : '',
      typeof engagementData.forward_count === 'number' ? detailItem('forwards', formatCount(engagementData.forward_count)) : '',
      typeof engagementData.reaction_count === 'number' ? detailItem('reactions', formatCount(engagementData.reaction_count)) : '',
    ]),
  ];

  $('#detail-body').innerHTML = sections.filter(Boolean).join('');
  $('#detail-drawer').hidden = false;
  $('#detail-backdrop').hidden = false;
  $('#detail-close').focus();
}

function closeDetail() { $('#detail-drawer').hidden = true; $('#detail-backdrop').hidden = true; }

/* ---------------- views ---------------- */

function currentView() { return location.hash.startsWith('#/all') ? 'all' : 'dashboard'; }

function showView(name) {
  $('#view-dashboard').hidden = name !== 'dashboard';
  $('#view-all').hidden = name !== 'all';
  $('#crumb-view').textContent = name === 'all' ? 'ALL EVENTS' : 'OVERVIEW';
  // Exactly one nav item is active: the archive link, or whichever anchor the hash points at.
  const activeHref = name === 'all' ? '#/all' : (location.hash && location.hash !== '#/all' ? location.hash : '#overview');
  document.querySelectorAll('.nav-item').forEach((node) => node.classList.toggle('active', node.getAttribute('href') === activeHref));
}

function route() {
  closeDetail();
  const view = currentView();
  showView(view);
  state.skip = 0;
  if (view === 'all') return loadAllPosts(false);
  // Charts sized to a hidden container while the archive was open; resize now it is visible.
  Object.values(charts).forEach((instance) => instance && instance.resize());
  return Promise.all([loadDashboardPosts(), loadIntel()]);
}

/* ---------------- data ---------------- */

function filterParams(limit, skip) {
  const params = new URLSearchParams({ limit, skip });
  if (state.query) params.set('q', state.query);
  if (state.language !== 'all') params.set('language', state.language);
  if (state.platform !== 'all') params.set('platform', state.platform);
  return params;
}

async function loadSummary() {
  const response = await fetch('/api/summary');
  if (!response.ok) throw new Error('Summary unavailable');
  const data = await response.json();
  $('#total-posts').textContent = formatCount(data.total_posts);
  $('#source-count').textContent = Object.keys(data.platforms || {}).length;
  $('#source-detail').textContent = Object.keys(data.platforms || {}).join(' / ') || 'No sources';
  const languages = Object.entries(data.languages || {});
  const top = languages[0];
  $('#top-language').textContent = top ? top[0].toUpperCase() : '—';
  $('#top-language-count').textContent = top ? `${formatCount(top[1])} observed events` : 'Waiting for data';
  $('#db-name').textContent = data.database || 'apitoprocessing';
  if (data.collection) $('#db-collection').textContent = data.collection;
  renderBars(data.platforms);
  $('#sync-label').textContent = `Synced ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`;
}

function clearPinnedPoll() {
  state.polled = null;
  $('#poll-pin').hidden = true;
}

async function loadDashboardPosts() {
  // Straight after a poll, show what was just fetched. The timeline is ordered by when a
  // post was written, not when it was ingested, so fresh results about an older event can
  // land well below the fold — which is exactly when you most want to see them.
  if (state.polled) {
    const shown = state.polled.items.slice(0, DASH_LIMIT);
    renderRows(shown, $('#posts-body'), false, true);
    $('#poll-pin-text').textContent =
      `Showing ${shown.length} of ${state.polled.items.length} post(s) from your last ${state.polled.label} poll`;
    $('#poll-pin').hidden = false;
    $('#result-count').textContent = `${formatCount(shown.length)} of ${formatCount(state.polled.items.length)} just polled`;
    return;
  }

  $('#poll-pin').hidden = true;
  const response = await fetch(`/api/posts?${filterParams(DASH_LIMIT, 0)}`);
  if (!response.ok) throw new Error('Posts unavailable');
  const data = await response.json();
  renderRows(data.items, $('#posts-body'), false);
  $('#result-count').textContent = `${formatCount(data.items.length)} of ${formatCount(data.total)} matching events`;
}

async function loadAllPosts(append = false) {
  const skip = append ? state.skip : 0;
  const response = await fetch(`/api/posts?${filterParams(ALL_LIMIT, skip)}`);
  if (!response.ok) throw new Error('Posts unavailable');
  const data = await response.json();
  state.total = data.total;
  state.skip = skip + data.items.length;
  renderRows(data.items, $('#all-posts-body'), append);
  $('#all-result-count').textContent = `${formatCount(state.skip)} of ${formatCount(data.total)} matching events`;
  $('#all-load-more').style.display = state.skip < data.total ? 'flex' : 'none';
}

function renderBars(platforms = {}) {
  const host = $('#source-bars'); host.innerHTML = '';
  const entries = Object.entries(platforms); const max = Math.max(...entries.map(([, value]) => value), 1);
  if (!entries.length) { host.innerHTML = '<div class="loading">No source data</div>'; return; }
  entries.forEach(([label, value], index) => { host.insertAdjacentHTML('beforeend', `<div class="bar-item"><div class="bar-label"><span>${escapeHtml(label)}</span><span>${formatCount(value)}</span></div><div class="bar-track"><div class="bar-fill ${index % 2 ? 'amber' : ''}" style="width:${Math.max((value / max) * 100, 3)}%"></div></div></div>`); });
}

async function loadEdges() { const response = await fetch('/api/edges'); if (!response.ok) return; const data = await response.json(); $('#edge-count').textContent = formatCount(data.items.length); const host = $('#edge-list'); host.innerHTML = data.items.length ? data.items.map(edge => `<div class="edge-item"><div class="edge-route"><span>${escapeHtml(edge.source_author_id || 'unknown')}</span><i data-lucide="arrow-right"></i><span>${escapeHtml(edge.target_author_id || 'unknown')}</span></div><div class="edge-type">${escapeHtml(edge.edge_type || 'interaction')} / ${escapeHtml(formatTime(edge.timestamp))}</div></div>`).join('') : '<div class="loading">No edges yet</div>'; lucide.createIcons(); }

async function loadAll() {
  try {
    const onDashboard = currentView() === 'dashboard';
    const tasks = [loadSummary(), loadEdges(), onDashboard ? loadDashboardPosts() : loadAllPosts(false)];
    // ECharts measures its container on init, so only draw while the dashboard is visible.
    if (onDashboard) tasks.push(loadIntel());
    await Promise.all(tasks);
  } catch (error) {
    $('#sync-label').textContent = 'MongoDB unavailable';
    document.querySelectorAll('.loading').forEach(node => { node.textContent = 'Could not reach the data service.'; });
  }
}

function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }

/* ---------------- filters (shared between both views) ---------------- */

function syncFilterInputs() {
  ['#search-input', '#all-search-input'].forEach((selector) => { const node = $(selector); if (node) node.value = state.query; });
  ['#language-filter', '#all-language-filter'].forEach((selector) => { const node = $(selector); if (node) node.value = state.language; });
  ['#platform-filter', '#all-platform-filter'].forEach((selector) => { const node = $(selector); if (node) node.value = state.platform; });
}

function applyFilters() {
  syncFilterInputs();
  state.skip = 0;
  clearPinnedPoll();  // a search means you are looking for something else now
  if (currentView() === 'all') return loadAllPosts(false);
  // The radar/KPIs are query-scoped too, so a search re-profiles the emotional response.
  return Promise.all([loadDashboardPosts(), loadIntel()]);
}

const onSearch = debounce((event) => { state.query = event.target.value; applyFilters(); }, 350);
$('#search-input').addEventListener('input', onSearch);
$('#all-search-input').addEventListener('input', onSearch);
['#language-filter', '#all-language-filter'].forEach((selector) => $(selector).addEventListener('change', (event) => { state.language = event.target.value; applyFilters(); }));
['#platform-filter', '#all-platform-filter'].forEach((selector) => $(selector).addEventListener('change', (event) => { state.platform = event.target.value; applyFilters(); }));
['#clear-search', '#all-clear-search'].forEach((selector) => $(selector).addEventListener('click', () => { state.query = ''; state.language = 'all'; state.platform = 'all'; applyFilters(); }));

/* ---------------- intel: KPIs, bot graph, emotion radar ---------------- */

const ROLE_STYLE = {
  patient_zero: { name: 'Patient-zero', color: '#ef767a' },
  amplifier: { name: 'Amplifier', color: '#eab464' },
  organic: { name: 'Organic', color: '#9bd18b' },
};
const ROLE_ORDER = ['patient_zero', 'amplifier', 'organic'];
const charts = { graph: null, radar: null };
let lastRadar = [];
let lastGraph = null;
// Re-drawing a force-directed graph restarts its layout, so settled nodes jump to new
// positions. Fingerprint the data and only redraw when it actually changed.
const chartSignatures = { graph: null, radar: null };

function graphSignature(graph) {
  return JSON.stringify([
    graph.nodes.map((node) => `${node.id}|${node.role}|${node.degree}`).sort(),
    graph.links.map((link) => `${link.source}>${link.target}`).sort(),
  ]);
}

function radarSignature(radar, includeNeutral) {
  return JSON.stringify([includeNeutral, radar.map((entry) => `${entry.axis}|${entry.raw}`)]);
}

function chart(key, id) {
  if (!charts[key]) charts[key] = echarts.init(document.getElementById(id), null, { renderer: 'canvas' });
  return charts[key];
}

function capturePositions() {
  // Read where the force layout has actually settled each node, so a redraw can pin
  // them back instead of scattering everything the user had already made sense of.
  if (!charts.graph) return {};
  try {
    const series = charts.graph.getModel().getSeriesByIndex(0);
    if (!series) return {};
    const data = series.getData();
    const positions = {};
    data.each((index) => {
      const layout = data.getItemLayout(index);
      const raw = data.getRawDataItem(index);
      const id = raw && raw.id;
      if (id && layout && Number.isFinite(layout[0]) && Number.isFinite(layout[1])) {
        positions[id] = { x: layout[0], y: layout[1] };
      }
    });
    return positions;
  } catch (error) {
    return {};
  }
}

function renderGraph(graph) {
  const signature = graphSignature(graph);
  if (signature === chartSignatures.graph && charts.graph) return;  // same accounts and edges: leave the layout settled
  chartSignatures.graph = signature;

  const previous = capturePositions();
  const instance = chart('graph', 'bot-graph');
  const nodes = graph.nodes.map((node) => {
    const item = {
      id: node.id,
      name: node.label,
      category: ROLE_ORDER.indexOf(node.role),
      symbolSize: Math.min(9 + node.degree * 5, 34),
      value: node.degree,
    };
    const seen = previous[node.id];
    if (seen) {
      // Already on screen: pin it exactly where it was. Only genuinely new accounts
      // are left free for the force layout to position around them.
      item.x = seen.x;
      item.y = seen.y;
      item.fixed = true;
    }
    return item;
  });
  instance.setOption({
    backgroundColor: 'transparent',
    tooltip: { formatter: (p) => (p.dataType === 'node' ? `${escapeHtml(p.data.name)}<br/>${ROLE_STYLE[ROLE_ORDER[p.data.category]].name} · degree ${p.data.value}` : '') },
    legend: { show: false },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      data: nodes,
      links: graph.links.map((link) => ({ source: link.source, target: link.target })),
      categories: ROLE_ORDER.map((role) => ({ name: ROLE_STYLE[role].name, itemStyle: { color: ROLE_STYLE[role].color } })),
      force: { repulsion: 150, edgeLength: [40, 110], gravity: 0.12 },
      lineStyle: { color: '#375151', curveness: 0.16, opacity: 0.75 },
      label: { show: false },
      emphasis: { focus: 'adjacency', label: { show: true, color: '#f2f5f3', fontSize: 10 } },
    }],
  }, true);
  const roles = graph.roles;
  $('#graph-foot').textContent =
    `${graph.nodes.length} connected accounts · ${graph.links.length} interactions · `
    + `${roles.patient_zero} patient-zero / ${roles.amplifier} amplifier / ${roles.organic} organic`
    + (graph.isolated ? ` · ${graph.isolated} accounts with no captured interaction (hidden)` : '');
}

function renderRadar(radar) {
  const includeNeutral = $('#radar-neutral').checked;
  // The toggle is part of the fingerprint, so flipping it always redraws.
  const signature = radarSignature(radar, includeNeutral);
  if (signature === chartSignatures.radar && charts.radar) return;
  chartSignatures.radar = signature;

  const axes = includeNeutral ? radar : radar.filter((entry) => entry.axis !== 'Neutrality');
  const peak = Math.max(...axes.map((entry) => entry.raw), 0);
  const values = axes.map((entry) => (peak ? Math.round((entry.raw / peak) * 1000) / 10 : 0));
  const instance = chart('radar', 'emotion-radar');
  instance.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      formatter: () => axes.map((entry, index) =>
        `${entry.axis}: ${values[index]} <span style="color:#6d7a7b">(weight ${entry.raw.toFixed(2)} · ${entry.labels.join(', ')})</span>`
      ).join('<br/>'),
    },
    radar: {
      indicator: axes.map((entry) => ({ name: entry.axis, max: 100 })),
      shape: 'polygon',
      splitNumber: 4,
      axisName: { color: '#9ba9aa', fontFamily: 'IBM Plex Mono, monospace', fontSize: 10 },
      splitLine: { lineStyle: { color: '#2b3a40' } },
      splitArea: { areaStyle: { color: ['#141d21', '#182126'] } },
      axisLine: { lineStyle: { color: '#2b3a40' } },
    },
    series: [{
      type: 'radar',
      data: [{ value: values, name: 'Emotional profile' }],
      symbolSize: 4,
      itemStyle: { color: '#70d6d1' },
      lineStyle: { color: '#70d6d1', width: 2 },
      areaStyle: { color: 'rgba(112,214,209,0.18)' },
    }],
  }, true);
  $('#radar-foot').textContent = includeNeutral
    ? 'Normalized against the strongest vector. Neutrality usually dominates news-style corpora.'
    : 'Neutrality excluded so the affective vectors stay readable — tick the box to include it.';
}

async function loadIntel() {
  const params = new URLSearchParams();
  if (state.query) params.set('q', state.query);
  const response = await fetch(`/api/intel${params.toString() ? '?' + params : ''}`);
  if (!response.ok) throw new Error('Intel unavailable');
  const data = await response.json();
  const kpi = data.kpis;

  $('#kpi-campaigns').textContent = formatCount(kpi.campaigns);
  $('#kpi-campaigns-note').textContent = kpi.campaign_topics.length ? kpi.campaign_topics.join(', ') : 'No topic bursting';
  $('#kpi-campaigns-badge').textContent = kpi.campaigns ? 'ACTIVE' : 'QUIET';
  $('#kpi-campaigns-badge').className = `kpi-badge${kpi.campaigns ? ' pulsing red' : ' green'}`;

  $('#kpi-seed').textContent = formatCount(kpi.patient_zero);
  $('#kpi-seed-badge').className = `kpi-badge${kpi.patient_zero ? ' red pulsing' : ' green'}`;
  $('#kpi-seed-badge').textContent = kpi.patient_zero ? 'SEEDS' : 'NONE';

  $('#kpi-synchrony').textContent = `${kpi.synchrony}%`;
  $('#kpi-synchrony-note').textContent = `${formatCount(kpi.synchronized_posts)} of ${formatCount(data.post_count)} posts repeat another account`;
  $('#kpi-synchrony-badge').className = `kpi-badge${kpi.synchrony >= 20 ? ' red pulsing' : kpi.synchrony > 0 ? ' amber' : ' green'}`;
  $('#kpi-synchrony-badge').textContent = kpi.synchrony > 0 ? 'COORD' : 'CLEAR';

  $('#kpi-risk').textContent = kpi.risk_level;
  $('#kpi-risk-note').textContent = `mean risk ${kpi.risk_mean} across ${formatCount(data.post_count)} posts`;
  const riskClass = { HIGH: ' red pulsing', ELEVATED: ' red', MODERATE: ' amber', LOW: ' green' }[kpi.risk_level] || '';
  $('#kpi-risk-badge').className = `kpi-badge${riskClass}`;
  $('#kpi-risk-badge').textContent = kpi.risk_level;

  lastRadar = data.radar;
  lastGraph = data.graph;
  renderGraph(lastGraph);
  renderRadar(lastRadar);
}

$('#graph-relayout').addEventListener('click', () => {
  if (!lastGraph) return;
  // Disposing drops the pinned coordinates, so the next render starts from a clean layout.
  if (charts.graph) { charts.graph.dispose(); charts.graph = null; }
  chartSignatures.graph = null;
  renderGraph(lastGraph);
});

$('#radar-neutral').addEventListener('change', () => { if (lastRadar.length) renderRadar(lastRadar); });
window.addEventListener('resize', debounce(() => {
  Object.values(charts).forEach((instance) => instance && instance.resize());
}, 150));

/* ---------------- live poll ---------------- */

const pollState = { source: 'x', running: false };
const POLL_PLACEHOLDER = {
  x: 'Keywords, e.g. finance OR "Link Analysis"',
  telegram: 'Channel, e.g. @bloomberg',
};

function setPollStatus(text, kind) {
  const node = $('#poll-status');
  node.hidden = !text;
  node.textContent = text || '';
  node.className = `poll-status${kind ? ' ' + kind : ''}`;
}

document.querySelectorAll('.poll-tab').forEach((tab) => tab.addEventListener('click', () => {
  pollState.source = tab.dataset.source;
  document.querySelectorAll('.poll-tab').forEach((node) => node.classList.toggle('active', node === tab));
  $('#poll-query').placeholder = POLL_PLACEHOLDER[pollState.source];
  $('#poll-query').focus();
}));

$('#poll-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (pollState.running) return;
  const query = $('#poll-query').value.trim();
  if (!query) { setPollStatus('Enter keywords or a channel first.', 'err'); return; }

  pollState.running = true;
  $('#poll-run').disabled = true;
  const label = pollState.source === 'x' ? 'X' : 'Telegram';
  setPollStatus(`Polling ${label} for "${query}"… first run loads the NLP models, which can take ~30s.`, 'busy');

  try {
    const response = await fetch('/api/poll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: pollState.source, query, limit: Number($('#poll-limit').value) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || `Poll failed (${response.status})`);

    const dropped = data.skipped ? ` ${data.skipped} non-${data.language || 'en'} result(s) skipped.` : '';
    if (!data.fetched) {
      setPollStatus(data.message || 'No new posts matched.', 'ok');
    } else {
      // Pin these to the top of the timeline; ordering by post time would otherwise bury them.
      state.polled = { items: data.items || [], label };
      setPollStatus(`Fetched ${data.fetched} post(s) from ${label}, analysed ${data.analyzed}.${dropped} Pinned to the timeline.`, 'ok');
    }
    await loadAll();
  } catch (error) {
    // fetch() rejects with a bare TypeError when it cannot reach the server at all,
    // which reads as a useless "Failed to fetch" in the UI.
    const message = error instanceof TypeError
      ? 'Cannot reach the API. Is the server still running? Restart it with: uvicorn web.app:app --env-file .env'
      : String(error.message || error);
    setPollStatus(message, 'err');
  } finally {
    pollState.running = false;
    $('#poll-run').disabled = false;
  }
});

$('#poll-pin-clear').addEventListener('click', () => { clearPinnedPoll(); loadDashboardPosts(); });
$('#all-load-more').addEventListener('click', () => loadAllPosts(true));
$('#refresh-button').addEventListener('click', () => { $('#refresh-button').classList.add('rotating'); loadAll().finally(() => $('#refresh-button').classList.remove('rotating')); });
$('#refresh-edges').addEventListener('click', loadEdges);

document.addEventListener('click', (event) => {
  const row = event.target.closest('.post-row');
  if (row) { openDetail(row.dataset.key); return; }
  if (event.target.closest('#detail-close') || event.target.closest('#detail-backdrop')) closeDetail();
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeDetail(); });
window.addEventListener('hashchange', route);

function tickClock() { $('#live-window').textContent = new Date().toISOString().slice(11, 19); }
setInterval(tickClock, 1000);
setInterval(loadAll, 30000);
tickClock();
lucide.createIcons();
showView(currentView());
loadAll();
