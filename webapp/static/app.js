'use strict';

// ── Helpers ────────────────────────────────────────────────────────────────────

function mod(score) {
  return Math.floor((score - 10) / 2);
}

function modStr(score) {
  const m = mod(score);
  return m >= 0 ? `+${m}` : `${m}`;
}

function bonusStr(b) {
  return b >= 0 ? `+${b}` : `${b}`;
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

// Latest full data for every character, for the full-sheet modal
const _charData = {};

// ── Character rendering ────────────────────────────────────────────────────────

function buildCharCard(char) {
  const card = el('div', 'character-card');
  card.dataset.id = char.id;

  // Portrait + identity — click for the full sheet
  const portraitWrap = el('div', 'char-portrait-wrap');
  portraitWrap.title = 'Open full character sheet';
  portraitWrap.addEventListener('click', () => openCharModal(char.id));

  const img = document.createElement('img');
  img.className = 'char-portrait';
  img.alt = char.name;
  img.dataset.charId = char.id;
  img.src = portraitSrc(char.id);
  img.onerror = () => img.classList.add('missing');
  portraitWrap.appendChild(img);

  const identity = el('div', 'char-identity');
  identity.appendChild(el('div', 'char-name', char.name));
  identity.appendChild(el('div', 'char-subtitle', `${char.race} ${char.class}${char.subclass ? ` (${char.subclass})` : ''} · Level ${char.level}`));
  identity.appendChild(el('div', 'char-player', char.player ? `played by ${char.player}` : ''));
  identity.appendChild(el('div', 'char-sheet-hint', 'view full sheet ↗'));
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
  card.appendChild(buildAbilitiesGrid(char));

  // Stats row
  const statsRow = el('div', 'stats-row');
  const statsData = [
    { val: char.ac ?? '—', lbl: 'AC' },
    { val: char.speed ? `${char.speed} ft` : '—', lbl: 'Speed' },
    { val: char.passive_perception ?? '—', lbl: 'Passive Perc' },
    { val: char.initiative_bonus != null ? bonusStr(char.initiative_bonus) : '—', lbl: 'Initiative' },
  ];
  statsData.forEach(s => {
    const item = el('div', 'stat-item');
    item.appendChild(el('span', 'stat-val', s.val));
    item.appendChild(el('span', 'stat-lbl', s.lbl));
    statsRow.appendChild(item);
  });
  card.appendChild(statsRow);

  card.appendChild(buildCardTabs(char));

  return card;
}

function buildAbilitiesGrid(char) {
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
  return abilGrid;
}

// Remember which tab each character card is on across re-renders
const _selectedTabs = {};

function buildCardTabs(char) {
  const wrap = el('div', 'card-tabs');
  const panes = {};

  panes['Bio'] = buildBioPane(char);
  panes['Attacks'] = buildAttacksPane(char);
  panes['Features'] = buildFeaturesPane(char);
  if ((char.spells?.known || []).length > 0 || Object.keys(char.spells?.slots || {}).length > 0) {
    panes['Spells'] = buildSpellsPane(char);
  }
  panes['Inventory'] = buildInventoryPane(char);

  const bar = el('div', 'tab-bar');
  const body = el('div', 'tab-body');
  const names = Object.keys(panes);
  const selected = _selectedTabs[char.id] && panes[_selectedTabs[char.id]]
    ? _selectedTabs[char.id] : names[0];

  names.forEach(name => {
    const btn = el('button', `tab-btn${name === selected ? ' active' : ''}`, name);
    btn.addEventListener('click', () => {
      _selectedTabs[char.id] = name;
      bar.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.textContent === name));
      body.innerHTML = '';
      body.appendChild(panes[name]);
    });
    bar.appendChild(btn);
  });
  body.appendChild(panes[selected]);

  wrap.appendChild(bar);
  wrap.appendChild(body);
  return wrap;
}

function buildBioPane(char) {
  const pane = el('div', 'tab-pane');

  const idLine = [char.alignment, char.background ? `${char.background} background` : null]
    .filter(Boolean).join(' · ');
  if (idLine) pane.appendChild(el('div', 'bio-idline', idLine));

  if (char.appearance) {
    const app = typeof char.appearance === 'string'
      ? char.appearance
      : Object.values(char.appearance).join(' ');
    pane.appendChild(el('div', 'bio-label', 'Appearance'));
    pane.appendChild(el('div', 'bio-text', app));
  }

  const p = char.personality || {};
  [['Traits', p.traits], ['Ideals', p.ideals], ['Bonds', p.bonds], ['Flaws', p.flaws]]
    .forEach(([label, items]) => {
      if (items && items.length > 0) {
        pane.appendChild(el('div', 'bio-label', label));
        items.forEach(t => pane.appendChild(el('div', 'bio-text', t)));
      }
    });

  if (pane.children.length === 0) return el('div', 'tab-pane tab-empty', 'A mysterious stranger.');
  return pane;
}

function buildAttacksPane(char) {
  const pane = el('div', 'tab-pane');
  const attacks = char.attacks || [];
  if (attacks.length === 0) return el('div', 'tab-pane tab-empty', 'No attacks listed.');
  attacks.forEach(a => {
    const row = el('div', 'attack-row');
    const head = el('div', 'attack-head');
    head.appendChild(el('span', 'attack-name', a.name));
    head.appendChild(el('span', 'attack-tohit', `${a.to_hit} to hit`));
    row.appendChild(head);
    const parts = [a.damage, a.range ? `range ${a.range}` : null,
      (a.properties || []).join(', ') || null, a.note || null].filter(Boolean);
    row.appendChild(el('div', 'attack-detail', parts.join(' · ')));
    pane.appendChild(row);
  });
  return pane;
}

// uses is either a plain string ("1/turn" — display only) or a tracked pool
// {max, remaining, per} the Bookkeeper ticks on use and resets on rests.
function buildFeatureUses(uses) {
  if (typeof uses !== 'object') return el('span', 'feature-uses', uses);
  const spent = (uses.remaining ?? 0) <= 0;
  const badge = el('span', `feature-uses${spent ? ' spent' : ''}`);
  const pips = el('span', 'slot-pips');
  for (let i = 0; i < (uses.max ?? 0); i++) {
    pips.appendChild(el('span', `slot-pip${i < (uses.remaining ?? 0) ? ' available' : ''}`, '◆'));
  }
  badge.appendChild(pips);
  badge.appendChild(el('span', null, ` ${uses.max}/${uses.per}${spent ? ' · spent' : ''}`));
  return badge;
}

function buildFeaturesPane(char) {
  const pane = el('div', 'tab-pane');
  const features = char.features || [];
  if (features.length === 0) return el('div', 'tab-pane tab-empty', 'No features listed.');
  features.forEach(f => {
    const row = el('div', 'feature-row');
    const head = el('div', 'feature-head');
    head.appendChild(el('span', 'feature-name', f.name));
    if (f.uses) head.appendChild(buildFeatureUses(f.uses));
    row.appendChild(head);
    const detail = [f.detail, f.source ? `(${f.source})` : null].filter(Boolean).join(' ');
    if (detail) row.appendChild(el('div', 'feature-detail', detail));
    pane.appendChild(row);
  });
  return pane;
}

function buildSpellsPane(char) {
  const pane = el('div', 'tab-pane');
  const spells = char.spells || {};
  const slots = spells.slots || {};
  Object.entries(slots).forEach(([lvl, s]) => {
    // slots stored as {"1": {"max": 2, "remaining": 1}}, {"1": {"total": 2, "used": 1}}, or {"1": 2}
    const total = typeof s === 'object' ? (s.max ?? s.total ?? 0) : s;
    const available = typeof s === 'object'
      ? (s.remaining ?? (total - (s.used || 0)))
      : s;
    const row = el('div', 'slot-row');
    row.appendChild(el('span', 'slot-label', `Level ${lvl} slots`));
    const pips = el('span', 'slot-pips');
    for (let i = 0; i < total; i++) {
      pips.appendChild(el('span', `slot-pip${i < available ? ' available' : ''}`, '◆'));
    }
    row.appendChild(el('span', 'slot-count', `${available}/${total}`));
    row.appendChild(pips);
    pane.appendChild(row);
  });
  (spells.known || []).forEach(sp => {
    const name = typeof sp === 'string' ? sp : sp.name;
    const entry = el('div', 'spell-known', name);
    if (typeof sp === 'object' && sp.detail) {
      entry.appendChild(el('div', 'spell-detail', sp.detail));
    }
    pane.appendChild(entry);
  });
  if (pane.children.length === 0) return el('div', 'tab-pane tab-empty', 'No spells yet.');
  return pane;
}

function buildInventoryPane(char, limit = 20) {
  const pane = el('div', 'tab-pane');
  const inventory = char.inventory || [];
  if (inventory.length > 0) {
    const invList = el('ul', 'inventory-list');
    inventory.slice(0, limit).forEach(entry => {
      const li = document.createElement('li');
      li.appendChild(el('span', 'item-name', entry.item));
      if (entry.qty && entry.qty !== 1) {
        li.appendChild(el('span', 'item-qty', `×${entry.qty}`));
      }
      invList.appendChild(li);
    });
    if (inventory.length > limit) {
      invList.appendChild(el('li', 'inventory-more', `…and ${inventory.length - limit} more (full sheet)`));
    }
    pane.appendChild(invList);
  }
  if (char.gold != null) {
    pane.appendChild(el('div', 'gold-line', `${char.gold} gp`));
  }
  if (pane.children.length === 0) return el('div', 'tab-pane tab-empty', 'Empty pockets.');
  return pane;
}

// One character shown at a time; party tabs across the top of the section
let _charOrder = [];
let _activeCharId = localStorage.getItem('active-char');

function renderCharacters(chars) {
  _charOrder = chars.map(c => c.id);
  chars.forEach(char => { _charData[char.id] = char; });
  if (!_charOrder.includes(_activeCharId)) _activeCharId = _charOrder[0] || null;
  renderCharTabs();
  renderActiveCharacter();
}

function renderCharTabs() {
  const bar = document.getElementById('char-tabs');
  bar.innerHTML = '';
  _charOrder.forEach(id => {
    const c = _charData[id];
    const hp = c.hp || {};
    const down = hp.max > 0 && (hp.current ?? 0) <= 0;
    const btn = el('button',
      `char-tab${id === _activeCharId ? ' active' : ''}${down ? ' down' : ''}`);
    btn.appendChild(el('span', 'char-tab-name', down ? `☠︎ ${c.name}` : c.name));
    const hpBar = el('span', 'char-tab-hp');
    const fill = el('span', `hp-fill ${hpClass(hp.current, hp.max)}`);
    fill.style.width = `${hpPct(hp.current, hp.max)}%`;
    hpBar.appendChild(fill);
    btn.appendChild(hpBar);
    btn.title = `${hp.current ?? '?'}/${hp.max ?? '?'} HP`;
    btn.addEventListener('click', () => {
      _activeCharId = id;
      localStorage.setItem('active-char', id);
      renderCharTabs();
      renderActiveCharacter();
    });
    bar.appendChild(btn);
  });
}

function renderActiveCharacter() {
  const inner = document.getElementById('characters-inner');
  inner.innerHTML = '';
  const char = _charData[_activeCharId];
  if (char) inner.appendChild(buildCharCard(char));
}

function updateCharacterCard(char) {
  _charData[char.id] = char;
  if (!_charOrder.includes(char.id)) _charOrder.push(char.id);
  if (!_activeCharId) _activeCharId = char.id;
  renderCharTabs(); // names / hurt states / new arrivals
  // Full rebuild keeps every field honest (AC, level, stats — not just HP);
  // _selectedTabs preserves the open detail tab across the swap.
  if (char.id === _activeCharId) renderActiveCharacter();
  refreshCharModal(char.id);
}

// ── Character full-sheet modal ─────────────────────────────────────────────────

const SKILLS = {
  acrobatics: 'dex', animal_handling: 'wis', arcana: 'int', athletics: 'str',
  deception: 'cha', history: 'int', insight: 'wis', intimidation: 'cha',
  investigation: 'int', medicine: 'wis', nature: 'int', perception: 'wis',
  performance: 'cha', persuasion: 'cha', religion: 'int',
  sleight_of_hand: 'dex', stealth: 'dex', survival: 'wis',
};

function skillLabel(key) {
  return key.split('_').map(w => w[0].toUpperCase() + w.slice(1)).join(' ');
}

let _openCharId = null;

function openCharModal(id) {
  _openCharId = id;
  refreshCharModal(id);
  document.getElementById('char-modal').classList.remove('hidden');
}

function refreshCharModal(id) {
  if (_openCharId !== id) return;
  const char = _charData[id];
  if (!char) return;
  const body = document.getElementById('char-modal-body');
  body.innerHTML = '';
  body.appendChild(buildFullSheet(char));
}

// Cache-buster bumped when a portrait is uploaded/changed, so every <img>
// re-fetches without a full reload.
let _portraitVersion = 0;

function portraitSrc(id) {
  return `/api/portraits/${id}${_portraitVersion ? `?v=${_portraitVersion}` : ''}`;
}

function refreshPortraits() {
  _portraitVersion = Date.now();
  document.querySelectorAll('.char-portrait, .sheet-portrait').forEach(img => {
    img.classList.remove('missing');
    img.src = portraitSrc(img.dataset.charId);
  });
}

async function uploadPortrait(id, file, statusEl) {
  statusEl.textContent = 'Uploading…';
  try {
    const res = await fetch(`/api/portraits/${id}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type },
      body: file,
    });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    statusEl.textContent = '';
    refreshPortraits();
  } catch (err) {
    statusEl.textContent = `Upload failed: ${err.message}`;
  }
}

// Click the portrait in the full sheet to change it
function makePortraitClickable(img, id, statusEl) {
  const wrap = el('div', 'sheet-portrait-wrap');
  wrap.title = 'Change portrait';
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'image/png,image/jpeg,image/webp';
  input.hidden = true;
  input.addEventListener('change', () => {
    if (input.files[0]) uploadPortrait(id, input.files[0], statusEl);
  });
  wrap.addEventListener('click', () => input.click());
  wrap.appendChild(img);
  wrap.appendChild(el('span', 'sheet-portrait-hint', 'change portrait'));
  wrap.appendChild(input);
  return wrap;
}

function sheetSection(title, node) {
  const sec = el('section', 'sheet-section');
  sec.appendChild(el('h3', 'sheet-section-title', title));
  sec.appendChild(node);
  return sec;
}

function buildFullSheet(char) {
  const sheet = el('div', 'full-sheet');

  // Header
  const head = el('div', 'sheet-head');
  const img = document.createElement('img');
  img.className = 'sheet-portrait';
  img.alt = char.name;
  img.dataset.charId = char.id;
  img.src = portraitSrc(char.id);
  img.onerror = () => img.classList.add('missing');
  const uploadStatus = el('span', 'portrait-upload-status');
  head.appendChild(makePortraitClickable(img, char.id, uploadStatus));
  const id = el('div', 'sheet-identity');
  id.appendChild(el('div', 'sheet-name', char.name));
  id.appendChild(el('div', 'sheet-subtitle',
    `${char.race} ${char.class}${char.subclass ? ` (${char.subclass})` : ''} · Level ${char.level}${char.xp != null ? ` · ${char.xp} XP` : ''}`));
  if (char.player) id.appendChild(el('div', 'char-player', `played by ${char.player}`));
  id.appendChild(uploadStatus);
  const hp = char.hp || {};
  const vitals = el('div', 'sheet-vitals');
  [
    ['HP', `${hp.current ?? '?'}/${hp.max ?? '?'}${hp.temp ? ` +${hp.temp}` : ''}`],
    ['AC', char.ac ?? '—'],
    ['Speed', char.speed ? `${char.speed} ft` : '—'],
    ['Init', char.initiative_bonus != null ? bonusStr(char.initiative_bonus) : '—'],
    ['Passive Perc', char.passive_perception ?? '—'],
    ['Hit Dice', char.hit_dice ? `${char.hit_dice.remaining}/${char.hit_dice.total} ${char.hit_dice.size}` : '—'],
  ].forEach(([lbl, val]) => {
    const v = el('div', 'sheet-vital');
    v.appendChild(el('span', 'stat-val', String(val)));
    v.appendChild(el('span', 'stat-lbl', lbl));
    vitals.appendChild(v);
  });
  id.appendChild(vitals);
  head.appendChild(id);
  sheet.appendChild(head);

  const cols = el('div', 'sheet-columns');

  // Left column: abilities, saves, skills, languages, proficiencies
  const left = el('div', 'sheet-col');
  left.appendChild(sheetSection('Abilities', buildAbilitiesGrid(char)));

  const abils = char.abilities || {};
  const prof = char.proficiency_bonus || 2;
  const saveProfs = char.save_proficiencies || [];
  const savesList = el('div', 'sheet-list');
  ['str', 'dex', 'con', 'int', 'wis', 'cha'].forEach(a => {
    const isProf = saveProfs.includes(a);
    const bonus = mod(abils[a] ?? 10) + (isProf ? prof : 0);
    const row = el('div', `sheet-list-row${isProf ? ' prof' : ''}`);
    row.appendChild(el('span', null, `${a.toUpperCase()} save${isProf ? ' ●' : ''}`));
    row.appendChild(el('span', 'sheet-bonus', bonusStr(bonus)));
    savesList.appendChild(row);
  });
  left.appendChild(sheetSection('Saving Throws', savesList));

  const skills = char.skills || {};
  const skillsList = el('div', 'sheet-list');
  Object.entries(SKILLS).forEach(([key, ab]) => {
    const level = skills[key]; // undefined | "proficient" | "expertise"
    let bonus = mod(abils[ab] ?? 10);
    if (level === 'expertise') bonus += 2 * prof;
    else if (level === 'proficient') bonus += prof;
    const row = el('div', `sheet-list-row${level ? ' prof' : ''}`);
    row.appendChild(el('span', null,
      `${skillLabel(key)} (${ab.toUpperCase()})${level === 'expertise' ? ' ●●' : level === 'proficient' ? ' ●' : ''}`));
    row.appendChild(el('span', 'sheet-bonus', bonusStr(bonus)));
    skillsList.appendChild(row);
  });
  left.appendChild(sheetSection('Skills', skillsList));

  if ((char.languages || []).length > 0) {
    left.appendChild(sheetSection('Languages', el('div', 'sheet-text', char.languages.join(', '))));
  }
  if (char.proficiencies) {
    const profNode = el('div', 'sheet-text');
    Object.entries(char.proficiencies).forEach(([kind, list]) => {
      if (list && list.length) profNode.appendChild(el('div', null, `${kind}: ${list.join(', ')}`));
    });
    left.appendChild(sheetSection('Proficiencies', profNode));
  }
  cols.appendChild(left);

  // Right column: attacks, spells, features, inventory, bio
  const right = el('div', 'sheet-col');
  right.appendChild(sheetSection('Attacks', buildAttacksPane(char)));
  if ((char.spells?.known || []).length > 0 || Object.keys(char.spells?.slots || {}).length > 0) {
    right.appendChild(sheetSection('Spells', buildSpellsPane(char)));
  }
  right.appendChild(sheetSection('Features', buildFeaturesPane(char)));
  right.appendChild(sheetSection('Inventory', buildInventoryPane(char, Infinity)));
  right.appendChild(sheetSection('Bio', buildBioPane(char)));
  cols.appendChild(right);

  sheet.appendChild(cols);
  return sheet;
}

// ── Feed rendering ─────────────────────────────────────────────────────────────

let _lastFeedLocation = null;
const _seenFeedIds = new Set();

// Work-log row at the foot of the feed — empty until the first activity step
// lands (renderDmActivity fills it), so it never says anything the step list
// doesn't.
function showDmThinking() {
  const container = document.getElementById('feed-entries');
  if (document.getElementById('dm-thinking')) return;
  const row = el('div', 'dm-thinking');
  row.id = 'dm-thinking';
  const steps = el('div', 'dm-steps');
  steps.id = 'dm-steps';
  row.appendChild(steps);
  container.appendChild(row);
  container.scrollTop = container.scrollHeight;
}

// Live activity from the DM's turn (SSE dm_activity): which role is at work,
// player-safe labels only. The last step spins; earlier ones get a check.
function renderDmActivity(activity) {
  setSayBusy(!!(activity && activity.busy));
  if (!activity || !activity.busy) {
    hideDmThinking();
    return;
  }
  showDmThinking();
  const stepsEl = document.getElementById('dm-steps');
  const container = document.getElementById('feed-entries');
  const nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 120;
  stepsEl.innerHTML = '';
  const recent = (activity.steps || []).slice(-4);
  recent.forEach((s, i) => {
    const current = i === recent.length - 1;
    const row = el('div', `dm-step ${current ? 'current' : 'done'}`);
    row.appendChild(el('span', 'dm-step-mark', current ? '↻' : '✓'));
    row.appendChild(el('span', null, s));
    stepsEl.appendChild(row);
  });
  if (nearBottom) container.scrollTop = container.scrollHeight;
}

function hideDmThinking() {
  const row = document.getElementById('dm-thinking');
  if (row) row.remove();
}

function appendFeedEntry(entry) {
  const container = document.getElementById('feed-entries');

  // The same entry can arrive via both /api/state and SSE (initial-load and
  // reconnect races) — render each id once.
  if (entry.id) {
    if (_seenFeedIds.has(entry.id)) return;
    _seenFeedIds.add(entry.id);
  }

  // Respect the reader: only autoscroll if they were already at the bottom.
  const nearBottom =
    container.scrollHeight - container.scrollTop - container.clientHeight < 120;

  // Location change marker
  if (entry.location && entry.location !== _lastFeedLocation && _lastFeedLocation !== null) {
    const marker = el('div', 'feed-location-marker', entry.location);
    container.appendChild(marker);
  }
  _lastFeedLocation = entry.location;

  hideDmThinking();

  const bq = document.createElement('blockquote');
  bq.className = `feed-entry feed-type-${entry.type || 'narration'}`;
  bq.appendChild(el('span', 'feed-text', entry.text));

  // Mechanical changes ride under the prose that explains them
  if (entry.effects && entry.effects.length > 0) {
    const fx = el('div', 'feed-effects');
    entry.effects.forEach(effect => fx.appendChild(el('div', 'feed-effect', effect)));
    bq.appendChild(fx);
  }

  bq.appendChild(el('span', 'feed-ts', formatTs(entry.ts)));

  container.appendChild(bq);
  if (entry.type === 'player') showDmThinking();
  if (nearBottom) container.scrollTop = container.scrollHeight;
}

function renderFeed(entries) {
  hideDmThinking();
  _lastFeedLocation = null;
  _seenFeedIds.clear();
  const container = document.getElementById('feed-entries');
  container.innerHTML = '';
  if (!entries || entries.length === 0) return;

  // Show location marker for first entry
  if (entries[0].location) {
    container.appendChild(el('div', 'feed-location-marker', entries[0].location));
    _lastFeedLocation = entries[0].location;
  }

  entries.forEach(entry => appendFeedEntry(entry));
  container.scrollTop = container.scrollHeight;
}

// ── Header ────────────────────────────────────────────────────────────────────

function renderHeader(current) {
  const campaign = current.campaign || 'Campaign Companion';
  document.getElementById('header-campaign').textContent = campaign;
  document.title = campaign;

  // Don't repeat the time of day if the date string already carries it
  let date = current.in_game_date || '';
  const tod = current.time_of_day || '';
  if (tod && !date.toLowerCase().includes(tod.toLowerCase())) date += `, ${tod}`;

  const loc = current.location || {};
  const location = [loc.specific, loc.settlement].filter(Boolean).join(', ');
  const weather = current.weather || '';

  [['header-location', location], ['header-date', date], ['header-weather', weather]]
    .forEach(([id, value]) => {
      const span = document.getElementById(id);
      span.textContent = value;
      span.title = value; // full text on hover — the bar ellipsizes
    });
  // dividers only between non-empty neighbors
  document.getElementById('header-div-1').classList.toggle('hidden', !location);
  document.getElementById('header-div-2').classList.toggle('hidden', !(date && weather));
}

// ── Sidebar ───────────────────────────────────────────────────────────────────

function renderSidebar(quests, worldFlags, current, dramatis, questHooks) {
  renderQuests(quests, questHooks);
  renderWhosWho(dramatis);
  renderResources(current);
  renderLocationDetail(current);
}

function renderResources(current) {
  const list = document.getElementById('resources-list');
  list.innerHTML = '';
  const res = (current && current.party_resources) || {};
  const entries = Object.entries(res);
  if (entries.length === 0) {
    list.appendChild(el('li', null, 'The pack is empty.'));
    return;
  }
  const label = k => k.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());
  entries.forEach(([k, v]) => {
    const li = el('li', 'resource-item');
    if (typeof v === 'number') {
      li.appendChild(el('span', 'resource-name', label(k)));
      li.appendChild(el('span', 'resource-count', String(v)));
    } else {
      // string values: "Name — detail" reads better than raw key + blob
      li.appendChild(el('span', 'resource-name', label(k)));
      li.appendChild(el('div', 'resource-note', String(v)));
    }
    list.appendChild(li);
  });
}

// Open/closed state of sidebar <details> groups, keyed by group name, so
// SSE re-renders don't undo what the player expanded or collapsed.
const sbCollapse = new Map();
function collapsible(key, summaryText, summaryClass, defaultOpen) {
  const d = document.createElement('details');
  d.open = sbCollapse.has(key) ? sbCollapse.get(key) : defaultOpen;
  d.appendChild(el('summary', summaryClass, summaryText));
  d.addEventListener('toggle', () => sbCollapse.set(key, d.open));
  return d;
}

function renderWhosWho(dramatis) {
  const list = document.getElementById('whoswho-list');
  list.innerHTML = '';
  if (!dramatis || dramatis.length === 0) {
    list.appendChild(el('li', null, 'No one yet — go meet somebody!'));
    return;
  }
  const tagLabels = { friend: 'Friend', enemy: 'Enemy', unknown: '?' };
  const item = c => {
    const li = document.createElement('li');
    li.className = 'whoswho-item';
    const head = el('div', 'whoswho-head');
    head.appendChild(el('span', 'whoswho-name', c.name));
    const disp = tagLabels[c.disposition] ? c.disposition : 'unknown';
    head.appendChild(el('span', `whoswho-tag whoswho-${disp}`, tagLabels[disp]));
    li.appendChild(head);
    if (c.note) li.appendChild(el('div', 'whoswho-note', c.note));
    return li;
  };
  // Group by optional 'category' in first-appearance order; uncategorized
  // entries render first, unheaded and always visible.
  const groups = new Map();
  dramatis.forEach(c => {
    const k = c.category || '';
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(c);
  });
  (groups.get('') || []).forEach(c => list.appendChild(item(c)));
  groups.forEach((members, cat) => {
    if (!cat) return;
    const li = document.createElement('li');
    const d = collapsible(`who:${cat}`, cat, 'sidebar-subhead', false);
    const ul = el('ul', 'whoswho-group');
    members.forEach(c => ul.appendChild(item(c)));
    d.appendChild(ul);
    li.appendChild(d);
    list.appendChild(li);
  });
}

function renderQuests(quests, hooks) {
  const list = document.getElementById('quests-list');
  list.innerHTML = '';
  if ((!quests || quests.length === 0) && (!hooks || hooks.length === 0)) {
    list.appendChild(el('li', null, 'No active quests.'));
    return;
  }
  (quests || []).forEach(q => {
    const li = document.createElement('li');
    li.className = 'quest-item';
    li.appendChild(el('div', 'quest-title', q.title));
    if (q.summary) li.appendChild(el('div', 'quest-summary', q.summary));
    if (q.objectives && q.objectives.length > 0) {
      const ul = el('ul', 'quest-objectives');
      const doneRe = /^DONE(?:\s*\([^)]*\))?\s*[:—–-]\s*/i;
      const open = q.objectives.filter(o => !doneRe.test(o));
      const done = q.objectives.filter(o => doneRe.test(o));
      open.forEach(obj => ul.appendChild(el('li', null, obj)));
      li.appendChild(ul);
      if (done.length > 0) {
        const d = collapsible(`quest:${q.title}`, `✓ ${done.length} done`, 'objective-done-summary', false);
        const dul = el('ul', 'quest-objectives');
        done.forEach(obj => {
          const li2 = el('li', 'objective-done');
          li2.appendChild(el('span', 'objective-check', '✓ '));
          li2.appendChild(el('s', null, obj.replace(doneRe, '')));
          dul.appendChild(li2);
        });
        d.appendChild(dul);
        li.appendChild(d);
      }
    }
    list.appendChild(li);
  });
  if (hooks && hooks.length > 0) {
    list.appendChild(el('li', 'sidebar-subhead', 'On the horizon'));
    hooks.forEach(h => {
      const li = document.createElement('li');
      li.className = 'quest-item quest-hook';
      if (h.title) li.appendChild(el('div', 'quest-title', h.title));
      if (h.pitch) li.appendChild(el('div', 'quest-summary', h.pitch));
      list.appendChild(li);
    });
  }
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
    detail.appendChild(el('div', 'loc-date', current.in_game_date));
  }
}

// ── Combat bar ────────────────────────────────────────────────────────────────

function renderCombat(combat) {
  const bar = document.getElementById('combat-bar');
  const active = !!(combat && combat.active);
  bar.classList.toggle('hidden', !active);
  // Reserve the bar's row only while it's visible — no dead strip otherwise
  document.body.classList.toggle('combat-active', active);
  if (!active) return;

  document.getElementById('combat-round').textContent = `Round ${combat.round}`;

  const track = document.getElementById('initiative-track');
  track.innerHTML = '';
  const order = combat.order || [];
  order.forEach((c, i) => {
    const span = el('div', `combatant${i === combat.turn_index ? ' active' : ''}${c.hp <= 0 ? ' down' : ''}`);
    span.appendChild(el('span', 'combatant-name', c.name));
    const hpStr = c.max_hp ? `${c.hp}/${c.max_hp}` : (c.hp != null ? `${c.hp} HP` : '');
    const low = c.hp != null && (c.hp <= 0 || c.hp / (c.max_hp || 1) < 0.25);
    span.appendChild(el('span', `combatant-hp${low ? ' low' : ''}`, hpStr));
    track.appendChild(span);
  });
}

// ── Settings ──────────────────────────────────────────────────────────────────

const SETTING_CONTROLS = {
  rules_strictness: ['set-rules-strictness', 'value'],
  beginner_mode: ['set-beginner-mode', 'checked'],
  show_rolls: ['set-show-rolls', 'checked'],
  kid_friendly: ['set-kid-friendly', 'checked'],
  narration_style: ['set-narration-style', 'value'],
  custom_rules: ['set-custom-rules', 'value'],
};

function renderSettings(settings) {
  Object.entries(SETTING_CONTROLS).forEach(([key, [id, prop]]) => {
    if (key in settings) document.getElementById(id)[prop] = settings[key];
  });
}

function collectSettings() {
  const out = {};
  Object.entries(SETTING_CONTROLS).forEach(([key, [id, prop]]) => {
    out[key] = document.getElementById(id)[prop];
  });
  return out;
}

async function saveSettings() {
  const status = document.getElementById('settings-status');
  try {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(collectSettings()),
    });
    if (!res.ok) throw new Error(await res.text());
    renderSettings(await res.json());
    status.textContent = 'Saved — the DM will honor this from their next narration.';
  } catch (err) {
    status.textContent = 'Could not save settings.';
    console.error('settings save failed:', err);
  }
  setTimeout(() => { status.textContent = ''; }, 5000);
}

// ── "The DM is thinking" ──────────────────────────────────────────────────────
// A turn can take a while (the DM reads files and rolls dice before it writes),
// so the chat says so rather than looking broken.

// One turn at a time: the chat box locks while the DM works, so a second
// message can't silently queue behind the first (table request). Lock on
// send; the dm_activity stream (and the snapshot on reconnect) unlocks.
function setSayBusy(busy) {
  const box = document.getElementById('say-text');
  box.disabled = busy;
  box.placeholder = busy ? 'The DM is replying…' : 'What do you do?';
  document.getElementById('say-send').disabled = busy;
  if (!busy) box.focus();
}

// Error notes under the chat box. Busy state is the activity log in the feed
// (SSE dm_activity) — no polling, no second "thinking" message.
function sayNote(note) {
  const el = document.getElementById('say-thinking');
  el.textContent = note || '';
  el.classList.toggle('hidden', !note);
  if (note) setTimeout(() => sayNote(''), 6000);
}

// ── Developer settings (hidden unless the URL carries #dev) ────────────────────
// Prompt A/B testing and model choice. Deliberately not in Table Settings:
// these change how the DM is built, not how it plays.

const DEV_HELP = {
  dm: 'The harness prompt — how the model runs as DM',
};

function devEnabled() {
  if (location.hash === '#dev') localStorage.setItem('devMode', '1');
  if (location.hash === '#nodev') localStorage.removeItem('devMode');
  return localStorage.getItem('devMode') === '1';
}

function renderDev(data) {
  const roleModels = data.role_models || {};
  // Model dropdown for one role: '' = inherit the global model. A hand-typed
  // model id that isn't in MODEL_CHOICES still round-trips as an extra option.
  const modelSelect = (role, current) => role === 'dm' ? '' : `
      <select data-model-role="${role}" title="Model for this role">
        <option value="">↑ global model</option>
        ${data.models.map(m =>
          `<option value="${m.id}" ${m.id === current ? 'selected' : ''}>${m.id}</option>`
        ).join('')}
        ${!current || data.models.some(m => m.id === current) ? ''
          : `<option value="${current}" selected>${current}</option>`}
      </select>`;

  const rows = data.registry.map(entry => `
    <label class="setting-row">
      <span class="setting-label">${entry.role}</span>
      <select data-role="${entry.role}" ${entry.variants.length < 2 ? 'disabled' : ''}>
        ${entry.variants.map(v =>
          `<option value="${v}" ${v === entry.selected ? 'selected' : ''}>${v}</option>`
        ).join('')}
      </select>
      ${modelSelect(entry.role, roleModels[entry.role] || '')}
      <span class="setting-desc">${DEV_HELP[entry.role] || entry.source}</span>
    </label>`).join('');

  document.getElementById('dev-body').innerHTML = `
    <label class="setting-row">
      <span class="setting-label">Model</span>
      <select id="dev-model">
        ${data.models.map(m =>
          `<option value="${m.id}" ${m.id === data.model ? 'selected' : ''}>${m.id}</option>`
        ).join('')}
        ${data.models.some(m => m.id === data.model) ? ''
          : `<option value="${data.model}" selected>${data.model}</option>`}
      </select>
    </label>
    <p class="settings-hint">Per role: prompt variant, then the model that role's
      subagent runs on (roles are separate agents the DM consults — "↑ global
      model" inherits the dropdown above). Add
      <code>prompts/&lt;role&gt;/&lt;name&gt;.md</code> for more prompt choices —
      see <code>prompts/README.md</code>.</p>
    ${rows}
    <div class="settings-actions">
      <span id="dev-status"></span>
      <button id="dev-reset">New DM thread</button>
      <button id="dev-save">Save</button>
    </div>`;

  document.getElementById('dev-save').addEventListener('click', saveDev);
  document.getElementById('dev-reset').addEventListener('click', resetThread);
}

async function saveDev() {
  const chosen = {};
  document.querySelectorAll('#dev-body select[data-role]').forEach(sel => {
    chosen[sel.dataset.role] = sel.value;
  });
  const roleModels = {};
  document.querySelectorAll('#dev-body select[data-model-role]').forEach(sel => {
    if (sel.value) roleModels[sel.dataset.modelRole] = sel.value;
  });
  const status = document.getElementById('dev-status');
  try {
    const res = await fetch('/api/dev', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompts: chosen, role_models: roleModels,
                             model: document.getElementById('dev-model').value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'save failed');
    status.textContent = 'Saved — applies on the DM\'s next turn.';
  } catch (err) {
    status.textContent = String(err.message || err);
  }
  setTimeout(() => { status.textContent = ''; }, 5000);
}

async function resetThread() {
  const status = document.getElementById('dev-status');
  status.textContent = 'Starting a fresh thread…';
  try {
    await fetch('/api/dev/reset-thread', { method: 'POST' });
    status.textContent = 'Thread cleared — campaign state untouched.';
  } catch (err) {
    status.textContent = 'Could not clear the thread.';
  }
  setTimeout(() => { status.textContent = ''; }, 5000);
}

async function toggleDev(on) {
  document.getElementById('dev-section').classList.toggle('hidden', !on);
  if (on && !document.getElementById('dev-body').childElementCount) {
    try {
      renderDev(await (await fetch('/api/dev')).json());
    } catch (err) {
      console.error('dev settings failed to load:', err);
    }
  }
}

function initDev() {
  const box = document.getElementById('set-dev-mode');
  box.checked = devEnabled();
  box.addEventListener('change', () => {
    localStorage.setItem('devMode', box.checked ? '1' : '');
    toggleDev(box.checked);
  });
  toggleDev(box.checked);
}

// ── Modals (shared behavior) ──────────────────────────────────────────────────

function initModals() {
  document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
    backdrop.addEventListener('click', e => {
      if (e.target === backdrop) closeModal(backdrop.id);
    });
  });
  document.querySelectorAll('.modal-close').forEach(btn => {
    btn.addEventListener('click', () => closeModal(btn.dataset.close));
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      document.querySelectorAll('.modal-backdrop:not(.hidden)')
        .forEach(b => closeModal(b.id));
    }
  });
  document.getElementById('settings-btn').addEventListener('click', () => {
    document.getElementById('settings-modal').classList.remove('hidden');
  });
  document.getElementById('settings-save').addEventListener('click', saveSettings);

  // Player input → POST /api/say; the entry comes back through the SSE feed.
  const sayText = document.getElementById('say-text');
  document.getElementById('say-form').addEventListener('submit', async e => {
    e.preventDefault();
    const text = sayText.value.trim();
    if (!text) return;
    setSayBusy(true);
    try {
      const res = await fetch('/api/say', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      if (res.ok) {
        sayText.value = '';
      } else {
        const data = await res.json().catch(() => ({}));
        sayNote(data.detail || 'The DM could not take that.');
        setSayBusy(false);
      }
    } catch (err) {
      sayNote('Could not reach the app. Try again.');
      setSayBusy(false);
    }
  });

  // Sidebar drawer — open by default on wide screens (it docks there, so the
  // chronicle keeps full width), collapsed on smaller ones. An explicit
  // toggle is remembered per browser and beats the default.
  const stored = localStorage.getItem('sidebar');
  const wide = window.matchMedia('(min-width: 1800px)').matches;
  if (stored ? stored === 'open' : wide) {
    document.body.classList.add('sidebar-open');
  }
  document.getElementById('sidebar-toggle').addEventListener('click', () => {
    const open = document.body.classList.toggle('sidebar-open');
    localStorage.setItem('sidebar', open ? 'open' : 'closed');
  });
  // Character sheet drawer (phone only — the toggle is hidden on desktop).
  document.getElementById('chars-toggle').addEventListener('click', () => {
    document.body.classList.toggle('chars-open');
  });
  // pointerdown, not click: tab clicks re-render the tab bar, so by the time
  // a click bubbles here its target is detached and looks "outside".
  document.addEventListener('pointerdown', e => {
    if (!document.body.classList.contains('chars-open')) return;
    if (e.target.closest('#characters-column, #chars-toggle')) return;
    document.body.classList.remove('chars-open');
  });

  // On narrow screens, a click outside the sidebar (and its toggle) closes it.
  document.addEventListener('click', e => {
    if (window.matchMedia('(min-width: 1800px)').matches) return;
    if (!document.body.classList.contains('sidebar-open')) return;
    if (e.target.closest('#sidebar-column, #sidebar-toggle')) return;
    document.body.classList.remove('sidebar-open');
    localStorage.setItem('sidebar', 'closed');
  });
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
  if (id === 'char-modal') _openCharId = null;
}

// ── SSE ───────────────────────────────────────────────────────────────────────

function applySnapshot(data) {
  renderCharacters(data.characters || []);
  renderFeed(data.feed || []);
  renderHeader(data.current || {});
  renderSidebar(data.quests || [], data.world_flags || {}, data.current || {}, data.dramatis || [], data.quest_hooks || []);
  renderCombat(data.combat);
  if (data.settings) renderSettings(data.settings);
  renderDmActivity(data.dm_activity);
}

function connectSSE() {
  const es = new EventSource('/events');
  let _dropped = false;

  // Anything pushed while the connection was down is gone from the stream,
  // so after a reconnect pull the full snapshot and re-render.
  es.onopen = async () => {
    if (!_dropped) return;
    _dropped = false;
    try {
      applySnapshot(await fetch('/api/state').then(r => r.json()));
    } catch { /* next reconnect will retry */ }
  };

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
    const current = JSON.parse(e.data);
    renderHeader(current);
    renderLocationDetail(current);
  });

  es.addEventListener('sidebar_update', e => {
    const data = JSON.parse(e.data);
    renderSidebar(data.quests, data.world_flags, data.current, data.dramatis, data.quest_hooks);
  });

  es.addEventListener('settings_update', e => {
    renderSettings(JSON.parse(e.data));
  });

  es.addEventListener('dm_activity', e => {
    renderDmActivity(JSON.parse(e.data));
  });

  es.addEventListener('portrait_update', () => {
    refreshPortraits();
  });

  es.onerror = () => {
    // Browser auto-reconnects EventSource; onopen resyncs the snapshot
    _dropped = true;
  };
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  initModals();
  initDev();
  try {
    applySnapshot(await fetch('/api/state').then(r => r.json()));
    connectSSE();
  } catch (err) {
    console.error('Failed to load initial state:', err);
  }
}

document.addEventListener('DOMContentLoaded', init);
