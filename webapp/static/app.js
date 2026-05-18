'use strict';

// ── Helpers ────────────────────────────────────────────────────────────────────

function mod(score) {
  return Math.floor((score - 10) / 2);
}

function modStr(score) {
  const m = mod(score);
  return m >= 0 ? `+${m}` : `${m}`;
}

function hpClass(current, max) {
  if (max <= 0) return 'medium';
  const pct = current / max;
  if (pct > 0.5) return 'high';
  if (pct > 0.25) return 'medium';
  return 'low';
}

function hpPct(current, max) {
  if (max <= 0) return 0;
  return Math.max(0, Math.min(100, (current / max) * 100));
}

function formatTs(isoStr) {
  try {
    const d = new Date(isoStr);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch {
    return '';
  }
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text !== undefined) e.textContent = text;
  return e;
}

// ── Character rendering ────────────────────────────────────────────────────────

function buildCharCard(char) {
  const card = el('div', 'character-card');
  card.dataset.id = char.id;

  // AC badge
  const acBadge = el('span', 'char-ac-badge', `AC ${char.ac}`);
  card.appendChild(acBadge);

  // Portrait + identity
  const portraitWrap = el('div', 'char-portrait-wrap');

  const img = document.createElement('img');
  img.className = 'char-portrait';
  img.alt = char.name;
  img.src = `/api/portraits/${char.id}`;
  img.onerror = () => img.classList.add('missing');
  portraitWrap.appendChild(img);

  const identity = el('div', 'char-identity');
  identity.appendChild(el('div', 'char-name', char.name));
  identity.appendChild(el('div', 'char-subtitle', `${char.race} ${char.class}${char.subclass ? ` (${char.subclass})` : ''} · Level ${char.level}`));
  identity.appendChild(el('div', 'char-player', char.player ? `played by ${char.player}` : ''));
  portraitWrap.appendChild(identity);
  card.appendChild(portraitWrap);

  // HP
  const hp = char.hp || {};
  const hpRow = el('div', 'hp-row');
  hpRow.appendChild(el('span', 'hp-label', 'HP'));
  const hpBarWrap = el('div', 'hp-bar-wrap');
  const hpBar = el('div', 'hp-bar');
  const hpFill = el('div', `hp-fill ${hpClass(hp.current, hp.max)}`);
  hpFill.style.width = `${hpPct(hp.current, hp.max)}%`;
  hpBar.appendChild(hpFill);
  hpBarWrap.appendChild(hpBar);
  if (hp.temp) {
    const tempBar = el('div', 'hp-temp-indicator', `+${hp.temp} temp`);
    hpBarWrap.appendChild(tempBar);
  }
  hpRow.appendChild(hpBarWrap);
  hpRow.appendChild(el('span', 'hp-text', `${hp.current ?? '?'}/${hp.max ?? '?'}`));
  card.appendChild(hpRow);

  // Conditions
  const conditions = char.conditions || [];
  if (conditions.length > 0 || char.exhaustion > 0) {
    const condRow = el('div', 'conditions-row');
    conditions.forEach(c => condRow.appendChild(el('span', 'condition-tag', c)));
    if (char.exhaustion > 0) {
      condRow.appendChild(el('span', 'condition-tag', `Exhaustion ${char.exhaustion}`));
    }
    card.appendChild(condRow);
  }

  // Death saves
  const ds = char.death_saves || {};
  if (hp.current <= 0 && (ds.successes > 0 || ds.failures > 0)) {
    card.appendChild(el('div', 'death-saves',
      `Death saves — ✓ ${ds.successes}/3   ✗ ${ds.failures}/3`));
  }

  // Abilities
  const abils = char.abilities || {};
  const abilOrder = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
  const abilLabels = { str: 'STR', dex: 'DEX', con: 'CON', int: 'INT', wis: 'WIS', cha: 'CHA' };
  const abilGrid = el('div', 'abilities-grid');
  abilOrder.forEach(key => {
    const score = abils[key] ?? 10;
    const box = el('div', 'ability-box');
    box.appendChild(el('span', 'ability-label', abilLabels[key]));
    box.appendChild(el('span', 'ability-score', score));
    box.appendChild(el('span', 'ability-mod', modStr(score)));
    abilGrid.appendChild(box);
  });
  card.appendChild(abilGrid);

  // Stats row
  const statsRow = el('div', 'stats-row');
  const statsData = [
    { val: char.speed ? `${char.speed} ft` : '—', lbl: 'Speed' },
    { val: char.passive_perception ?? '—', lbl: 'Passive Perc' },
    { val: char.initiative_bonus != null ? (char.initiative_bonus >= 0 ? `+${char.initiative_bonus}` : `${char.initiative_bonus}`) : '—', lbl: 'Initiative' },
  ];
  statsData.forEach(s => {
    const item = el('div', 'stat-item');
    item.appendChild(el('span', 'stat-val', s.val));
    item.appendChild(el('span', 'stat-lbl', s.lbl));
    statsRow.appendChild(item);
  });
  card.appendChild(statsRow);

  // Inventory
  const inventory = char.inventory || [];
  if (inventory.length > 0) {
    card.appendChild(el('div', 'card-section-label', 'Inventory'));
    const invList = el('ul', 'inventory-list');
    inventory.slice(0, 20).forEach(entry => {
      const li = document.createElement('li');
      li.appendChild(el('span', 'item-name', entry.item));
      if (entry.qty && entry.qty !== 1) {
        li.appendChild(el('span', 'item-qty', `×${entry.qty}`));
      }
      invList.appendChild(li);
    });
    card.appendChild(invList);
    if (char.gold != null) {
      card.appendChild(el('div', 'gold-line', `${char.gold} gp`));
    }
  }

  return card;
}

function renderCharacters(chars) {
  const inner = document.getElementById('characters-inner');
  inner.innerHTML = '';
  chars.forEach(char => inner.appendChild(buildCharCard(char)));
}

function updateCharacterCard(char) {
  const existing = document.querySelector(`.character-card[data-id="${char.id}"]`);
  if (!existing) {
    // New character — full render
    document.getElementById('characters-inner').appendChild(buildCharCard(char));
    return;
  }

  // Patch HP fill
  const hp = char.hp || {};
  const hpFill = existing.querySelector('.hp-fill');
  if (hpFill) {
    hpFill.style.width = `${hpPct(hp.current, hp.max)}%`;
    hpFill.className = `hp-fill ${hpClass(hp.current, hp.max)}`;
  }
  const hpText = existing.querySelector('.hp-text');
  if (hpText) hpText.textContent = `${hp.current ?? '?'}/${hp.max ?? '?'}`;

  // Patch conditions
  const conditions = char.conditions || [];
  const exhaustion = char.exhaustion || 0;
  let condRow = existing.querySelector('.conditions-row');
  if (conditions.length > 0 || exhaustion > 0) {
    if (!condRow) {
      condRow = el('div', 'conditions-row');
      existing.insertBefore(condRow, existing.querySelector('.abilities-grid'));
    }
    condRow.innerHTML = '';
    conditions.forEach(c => condRow.appendChild(el('span', 'condition-tag', c)));
    if (exhaustion > 0) condRow.appendChild(el('span', 'condition-tag', `Exhaustion ${exhaustion}`));
  } else if (condRow) {
    condRow.remove();
  }

  // Patch death saves
  const ds = char.death_saves || {};
  let dsEl = existing.querySelector('.death-saves');
  if (hp.current <= 0 && (ds.successes > 0 || ds.failures > 0)) {
    if (!dsEl) {
      dsEl = el('div', 'death-saves', '');
      const hpRow = existing.querySelector('.hp-row');
      hpRow.insertAdjacentElement('afterend', dsEl);
    }
    dsEl.textContent = `Death saves — ✓ ${ds.successes}/3   ✗ ${ds.failures}/3`;
  } else if (dsEl) {
    dsEl.remove();
  }
}

// ── Feed rendering ─────────────────────────────────────────────────────────────

let _lastFeedLocation = null;

function appendFeedEntry(entry) {
  const container = document.getElementById('feed-entries');

  // Location change marker
  if (entry.location && entry.location !== _lastFeedLocation && _lastFeedLocation !== null) {
    const marker = el('div', 'feed-location-marker', entry.location);
    container.appendChild(marker);
  }
  _lastFeedLocation = entry.location;

  const bq = document.createElement('blockquote');
  bq.className = `feed-entry feed-type-${entry.type || 'narration'}`;
  bq.textContent = entry.text;

  const ts = el('span', 'feed-ts', formatTs(entry.ts));
  bq.appendChild(ts);

  container.appendChild(bq);
  container.scrollTop = container.scrollHeight;
}

function renderFeed(entries) {
  _lastFeedLocation = null;
  document.getElementById('feed-entries').innerHTML = '';
  if (!entries || entries.length === 0) return;

  // Show location marker for first entry
  if (entries[0].location) {
    const marker = el('div', 'feed-location-marker', entries[0].location);
    document.getElementById('feed-entries').appendChild(marker);
    _lastFeedLocation = entries[0].location;
  }

  entries.forEach(entry => appendFeedEntry(entry));
}

// ── Header ────────────────────────────────────────────────────────────────────

function renderHeader(current) {
  document.getElementById('header-date').textContent =
    `${current.in_game_date || ''}${current.time_of_day ? ', ' + current.time_of_day : ''}`;
  const loc = current.location || {};
  document.getElementById('header-location').textContent =
    [loc.specific, loc.settlement].filter(Boolean).join(', ');
  document.getElementById('header-weather').textContent = current.weather || '';
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function renderSidebar(quests, worldFlags, current) {
  renderQuests(quests);
  renderWorldFlags(worldFlags);
  renderLocationDetail(current);
}

function renderQuests(quests) {
  const list = document.getElementById('quests-list');
  list.innerHTML = '';
  if (!quests || quests.length === 0) {
    list.appendChild(el('li', null, 'No active quests.'));
    return;
  }
  quests.forEach(q => {
    const li = document.createElement('li');
    li.className = 'quest-item';
    li.appendChild(el('div', 'quest-title', q.title));
    if (q.summary) li.appendChild(el('div', 'quest-summary', q.summary));
    if (q.objectives && q.objectives.length > 0) {
      const ul = el('ul', 'quest-objectives');
      q.objectives.forEach(obj => ul.appendChild(el('li', null, obj)));
      li.appendChild(ul);
    }
    list.appendChild(li);
  });
}

function renderWorldFlags(flags) {
  const list = document.getElementById('worldflags-list');
  list.innerHTML = '';
  const entries = Object.entries(flags || {});
  if (entries.length === 0) {
    list.appendChild(el('li', null, 'Nothing yet.'));
    return;
  }
  entries.forEach(([, note]) => {
    list.appendChild(el('li', null, note));
  });
}

function renderLocationDetail(current) {
  const detail = document.getElementById('location-detail');
  detail.innerHTML = '';
  if (!current) return;
  const loc = current.location || {};
  if (loc.specific) detail.appendChild(el('div', 'loc-specific', loc.specific));
  if (loc.settlement && loc.settlement !== loc.specific) {
    detail.appendChild(el('div', 'loc-settlement', loc.settlement));
  }
  if (loc.region) detail.appendChild(el('div', null, loc.region));
  if (current.in_game_date) {
    const dateEl = el('div', null, current.in_game_date);
    dateEl.style.marginTop = '6px';
    dateEl.style.fontSize = '12px';
    dateEl.style.color = 'var(--parchment-dim)';
    detail.appendChild(dateEl);
  }
}

// ── Combat bar ────────────────────────────────────────────────────────────────

function renderCombat(combat) {
  const bar = document.getElementById('combat-bar');
  if (!combat || !combat.active) {
    bar.classList.add('hidden');
    return;
  }
  bar.classList.remove('hidden');

  document.getElementById('combat-round').textContent = `Round ${combat.round}`;

  const track = document.getElementById('initiative-track');
  track.innerHTML = '';
  const order = combat.order || [];
  order.forEach((c, i) => {
    const span = el('div', `combatant${i === combat.turn_index ? ' active' : ''}${c.hp <= 0 ? ' down' : ''}`);
    span.appendChild(el('span', 'combatant-name', c.name));
    const hpStr = c.max_hp ? `${c.hp}/${c.max_hp}` : `${c.hp} HP`;
    const hpEl = el('span', `combatant-hp${c.hp <= 0 ? ' low' : (c.hp / (c.max_hp || 1) < 0.25 ? ' low' : '')}`, hpStr);
    span.appendChild(hpEl);
    track.appendChild(span);
  });
}

// ── SSE ───────────────────────────────────────────────────────────────────────

function connectSSE() {
  const es = new EventSource('/events');

  es.addEventListener('feed_entry', e => {
    appendFeedEntry(JSON.parse(e.data));
  });

  es.addEventListener('character_update', e => {
    updateCharacterCard(JSON.parse(e.data));
  });

  es.addEventListener('combat_update', e => {
    renderCombat(JSON.parse(e.data));
  });

  es.addEventListener('state_update', e => {
    renderHeader(JSON.parse(e.data));
    renderLocationDetail(JSON.parse(e.data));
  });

  es.addEventListener('sidebar_update', e => {
    const data = JSON.parse(e.data);
    renderSidebar(data.quests, data.world_flags, data.current);
  });

  es.onerror = () => {
    // Browser auto-reconnects EventSource — no manual retry needed
  };
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  try {
    const data = await fetch('/api/state').then(r => r.json());
    renderCharacters(data.characters || []);
    renderFeed(data.feed || []);
    renderHeader(data.current || {});
    renderSidebar(data.quests || [], data.world_flags || {}, data.current || {});
    renderCombat(data.combat);
    connectSSE();
  } catch (err) {
    console.error('Failed to load initial state:', err);
  }
}

document.addEventListener('DOMContentLoaded', init);
