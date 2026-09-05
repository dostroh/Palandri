const state = { skip: 0, limit: 24, query: '', language: 'all', platform: 'all', total: 0, items: [] };
const $ = (selector) => document.querySelector(selector);

function escapeHtml(value = '') { return String(value).replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char])); }
function formatTime(value) { if (!value) return '—'; const date = new Date(value); return Number.isNaN(date.valueOf()) ? value : `${date.toISOString().slice(0, 19).replace('T', ' ')}Z`; }
function formatCount(value) { return Number(value || 0).toLocaleString(); }
function postId(item) { return item.post_id || 'unknown'; }
function authorName(item) { return item.author?.username || item.author?.display_name || item.author?.user_id || item.author_id || 'unknown'; }
function engagement(item) { const data = item.engagement || {}; return `<span>♥ ${formatCount(data.like_count ?? data.likes)}</span><span>↗ ${formatCount(data.retweet_count ?? data.reposts ?? data.forward_count)}</span><span>◌ ${formatCount(data.reply_count ?? data.comments)}</span>`; }
function analytics(item) {
  const insights = item.ml_insights || item.analytics || item.inferred_attributes || {};
  const sentiment = insights.sentiment || {};
  const stance = insights.stance || {};
  const trends = insights.trends || {};
  const chips = [];
  if (trends.topic_category || insights.topic_category) chips.push(`<span class="analysis-chip topic">${escapeHtml(trends.topic_category || insights.topic_category)}</span>`);
  if (sentiment.primary_emotion) chips.push(`<span class="analysis-chip emotion">${escapeHtml(sentiment.primary_emotion)}</span>`);
  if (stance.label) chips.push(`<span class="analysis-chip stance">${escapeHtml(stance.label)}</span>`);
  if (typeof sentiment.polarity_score === 'number') chips.push(`<span class="analysis-chip polarity ${sentiment.polarity_score < 0 ? 'negative' : 'positive'}">pol ${sentiment.polarity_score.toFixed(2)}</span>`);
  if (typeof insights.risk_score === 'number') chips.push(`<span class="analysis-chip risk">risk ${insights.risk_score}</span>`);
  return chips.length ? `<span class="analytics-strip">${chips.join('')}</span>` : '<span class="analysis-pending">NLP pending</span>';
}

function renderPosts(items, append = false) {
  const body = $('#posts-body');
  if (!append) body.innerHTML = '';
  if (!items.length && !append) { body.innerHTML = '<tr><td colspan="5" class="loading">No events match this view.</td></tr>'; return; }
  for (const item of items) {
    const platform = item.platform || 'unknown';
    const author = item.author || {};
    const channel = item.channel?.channel_name || item.metadata?.subreddit || '—';
    const text = escapeHtml(item.text || item.content || '');
    const row = document.createElement('tr');
    row.innerHTML = `<td><div class="event-id">${escapeHtml(postId(item))}</div><div class="event-time">${escapeHtml(formatTime(item.timestamp || item.created_at))}</div></td><td><div class="signal-line"><span class="signal-text">${text || '<span class="event-time">No text content</span>'}</span>${analytics(item)}</div></td><td><div class="author-name">${escapeHtml(authorName(item))}</div><div class="author-id">${escapeHtml(author.user_id || item.author_id || '—')}</div></td><td><span class="source-tag">${escapeHtml(platform)}</span><span class="lang-tag">${escapeHtml(item.language || '—')}</span><div class="event-time channel-label">${escapeHtml(channel)}</div></td><td class="engagement">${engagement(item)}</td>`;
    body.appendChild(row);
  }
}

function renderBars(platforms = {}) {
  const host = $('#source-bars'); host.innerHTML = '';
  const entries = Object.entries(platforms); const max = Math.max(...entries.map(([, value]) => value), 1);
  if (!entries.length) { host.innerHTML = '<div class="loading">No source data</div>'; return; }
  entries.forEach(([label, value], index) => { host.insertAdjacentHTML('beforeend', `<div class="bar-item"><div class="bar-label"><span>${escapeHtml(label)}</span><span>${formatCount(value)}</span></div><div class="bar-track"><div class="bar-fill ${index % 2 ? 'amber' : ''}" style="width:${Math.max((value / max) * 100, 3)}%"></div></div></div>`); });
}

async function loadSummary() {
  const response = await fetch('/api/summary');
  if (!response.ok) throw new Error('Summary unavailable');
  const data = await response.json();
  $('#total-posts').textContent = formatCount(data.total_posts);
  $('#source-count').textContent = Object.keys(data.platforms || {}).length;
  $('#source-detail').textContent = Object.keys(data.platforms || {}).join(' / ') || 'No sources';
  const languages = Object.entries(data.languages || {});
  const top = languages[0]; $('#top-language').textContent = top ? top[0].toUpperCase() : '—'; $('#top-language-count').textContent = top ? `${formatCount(top[1])} observed events` : 'Waiting for data';
  $('#db-name').textContent = data.database || 'apiprocessing'; renderBars(data.platforms); $('#sync-label').textContent = `Synced ${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
}

async function loadPosts(append = false) {
  const params = new URLSearchParams({ limit: state.limit, skip: append ? state.skip : 0 }); if (state.query) params.set('q', state.query); if (state.language !== 'all') params.set('language', state.language); if (state.platform !== 'all') params.set('platform', state.platform);
  const response = await fetch(`/api/posts?${params}`); if (!response.ok) throw new Error('Posts unavailable'); const data = await response.json(); state.total = data.total; state.skip = (append ? state.skip : 0) + data.items.length; renderPosts(data.items, append); $('#result-count').textContent = `${formatCount(data.total)} matching events`; $('#load-more').style.display = state.skip < data.total ? 'flex' : 'none';
}

async function loadEdges() { const response = await fetch('/api/edges'); if (!response.ok) return; const data = await response.json(); $('#edge-count').textContent = formatCount(data.items.length); const host = $('#edge-list'); host.innerHTML = data.items.length ? data.items.map(edge => `<div class="edge-item"><div class="edge-route"><span>${escapeHtml(edge.source_author_id || 'unknown')}</span><i data-lucide="arrow-right"></i><span>${escapeHtml(edge.target_author_id || 'unknown')}</span></div><div class="edge-type">${escapeHtml(edge.edge_type || 'interaction')} / ${escapeHtml(formatTime(edge.timestamp))}</div></div>`).join('') : '<div class="loading">No edges yet</div>'; lucide.createIcons(); }

async function loadAll() { try { await Promise.all([loadSummary(), loadPosts(false), loadEdges()]); } catch (error) { $('#sync-label').textContent = 'MongoDB unavailable'; document.querySelectorAll('.loading').forEach(node => { node.textContent = 'Could not reach the data service.'; }); } }
function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }

$('#search-input').addEventListener('input', debounce((event) => { state.query = event.target.value; state.skip = 0; loadPosts(false); }, 350));
$('#language-filter').addEventListener('change', (event) => { state.language = event.target.value; state.skip = 0; loadPosts(false); });
$('#platform-filter').addEventListener('change', (event) => { state.platform = event.target.value; state.skip = 0; loadPosts(false); });
$('#load-more').addEventListener('click', () => loadPosts(true));
$('#refresh-button').addEventListener('click', () => { $('#refresh-button').classList.add('rotating'); loadAll().finally(() => $('#refresh-button').classList.remove('rotating')); });
$('#refresh-edges').addEventListener('click', loadEdges);
$('#clear-search').addEventListener('click', () => { $('#search-input').value = ''; $('#language-filter').value = 'all'; $('#platform-filter').value = 'all'; state.query = ''; state.language = 'all'; state.platform = 'all'; state.skip = 0; loadPosts(false); });
function tickClock() { $('#live-window').textContent = new Date().toISOString().slice(11, 19); }
setInterval(tickClock, 1000); setInterval(loadAll, 30000); tickClock(); lucide.createIcons(); loadAll();
