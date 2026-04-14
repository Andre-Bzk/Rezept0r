/* Rezept0r – Frontend */

let currentRecipeData = null;
let tandoorConfigured = false;

async function checkHealth() {
  try {
    const res = await fetch('/api/health');
    const data = await res.json();
    tandoorConfigured = data.tandoor_configured;
  } catch (_) {}
}

function renderMarkdownBold(text) {
  const escaped = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  return escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

function showSection(id) {
  ['progress-section', 'result-section', 'error-section'].forEach(s => {
    document.getElementById(s).classList.add('hidden');
  });
  document.getElementById(id).classList.remove('hidden');
}

function setProgress(pct, message) {
  document.getElementById('progress-bar').style.width = pct + '%';
  document.getElementById('progress-message').textContent = message;
}

function showError(message) {
  showSection('error-section');
  document.getElementById('error-message').textContent = message;
}

function renderRecipe(data) {
  const { recipe, tandoor_json } = data;
  currentRecipeData = data;

  // Image
  const img = document.getElementById('recipe-image');
  if (recipe.image_url) {
    img.src = recipe.image_url;
    img.classList.remove('hidden');
    img.onerror = () => img.classList.add('hidden');
  } else {
    img.classList.add('hidden');
  }

  document.getElementById('recipe-title').textContent = recipe.title || '';

  const desc = document.getElementById('recipe-description');
  if (recipe.description) {
    desc.textContent = recipe.description;
    desc.classList.remove('hidden');
  } else {
    desc.classList.add('hidden');
  }

  // Meta tags
  if (recipe.servings) {
    document.getElementById('servings-value').textContent = recipe.servings + ' Portionen';
    document.getElementById('recipe-servings').classList.remove('hidden');
  }
  if (recipe.prep_time_minutes) {
    document.getElementById('prep-value').textContent = recipe.prep_time_minutes;
    document.getElementById('recipe-prep').classList.remove('hidden');
  }
  if (recipe.cook_time_minutes) {
    document.getElementById('cook-value').textContent = recipe.cook_time_minutes;
    document.getElementById('recipe-cook').classList.remove('hidden');
  }
  if (recipe.nutrition?.kcal_per_serving) {
    const sourceLabel = {
      'extracted': '',
      'usda': '(USDA)',
      'gpt4_estimate': '(Schätzung)'
    }[recipe.nutrition.source] || '';
    document.getElementById('kcal-value').textContent = Math.round(recipe.nutrition.kcal_per_serving);
    document.getElementById('kcal-source').textContent = sourceLabel;
    document.getElementById('recipe-kcal').classList.remove('hidden');
  }

  // Tags
  const tagList = document.getElementById('recipe-tags');
  tagList.innerHTML = '';
  (recipe.tags || []).forEach(tag => {
    const span = document.createElement('span');
    span.className = 'tag';
    span.textContent = tag;
    tagList.appendChild(span);
  });

  // Ingredients
  const ul = document.getElementById('ingredients-list');
  ul.innerHTML = '';
  (recipe.ingredients || []).forEach(ing => {
    const li = document.createElement('li');
    if (ing.amount || ing.unit) {
      const amountSpan = document.createElement('span');
      amountSpan.className = 'ingredient-amount';
      amountSpan.textContent = [ing.amount, ing.unit].filter(Boolean).join(' ');
      li.appendChild(amountSpan);
    }
    const nameSpan = document.createElement('span');
    nameSpan.textContent = ing.name;
    li.appendChild(nameSpan);
    if (ing.note) {
      const noteSpan = document.createElement('span');
      noteSpan.className = 'ingredient-note';
      noteSpan.textContent = '(' + ing.note + ')';
      li.appendChild(noteSpan);
    }
    ul.appendChild(li);
  });

  // Steps
  const ol = document.getElementById('steps-list');
  ol.innerHTML = '';
  (recipe.steps || []).forEach(step => {
    const li = document.createElement('li');
    li.innerHTML = renderMarkdownBold(step);
    ol.appendChild(li);
  });

  // Source link
  const sourceLink = document.getElementById('source-link');
  sourceLink.href = recipe.source_url || '#';

  // Tandoor fallback JSON
  document.getElementById('tandoor-json').value = JSON.stringify(tandoor_json, null, 2);

  document.getElementById('import-status').textContent = '';
  document.getElementById('tandoor-fallback').classList.add('hidden');

  showSection('result-section');
}

function startExtraction() {
  const url = document.getElementById('url-input').value.trim();
  if (!url) return;

  const btn = document.getElementById('extract-btn');
  btn.disabled = true;

  showSection('progress-section');
  setProgress(0, 'Starte Extraktion...');

  const sse = new EventSource('/api/extract/stream?url=' + encodeURIComponent(url));

  sse.addEventListener('status', e => {
    const data = JSON.parse(e.data);
    setProgress(data.progress, data.message);
  });

  sse.addEventListener('result', e => {
    sse.close();
    btn.disabled = false;
    const data = JSON.parse(e.data);
    renderRecipe(data);
    loadHistory();
  });

  sse.addEventListener('error', e => {
    sse.close();
    btn.disabled = false;
    if (e.data) {
      try {
        const data = JSON.parse(e.data);
        showError(data.message || 'Unbekannter Fehler');
      } catch (_) {
        showError('Verbindungsfehler. Bitte erneut versuchen.');
      }
    } else {
      showError('Verbindung zum Server unterbrochen.');
    }
  });
}

async function importToTandoor() {
  if (!currentRecipeData) return;
  const btn = document.getElementById('import-btn');
  const status = document.getElementById('import-status');

  if (!tandoorConfigured) {
    status.textContent = 'Tandoor nicht konfiguriert – JSON unten kopieren.';
    status.className = 'import-status error';
    showTandoorFallback();
    return;
  }

  btn.disabled = true;
  status.textContent = 'Importiere...';
  status.className = 'import-status';

  try {
    const res = await fetch('/api/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentRecipeData)
    });
    const data = await res.json();
    if (res.ok) {
      status.textContent = 'Erfolgreich importiert!';
      status.className = 'import-status success';
      loadHistory();
    } else {
      status.textContent = 'Fehler: ' + (data.detail || 'Import fehlgeschlagen');
      status.className = 'import-status error';
      showTandoorFallback();
    }
  } catch (_) {
    status.textContent = 'Netzwerkfehler beim Import';
    status.className = 'import-status error';
    showTandoorFallback();
  } finally {
    btn.disabled = false;
  }
}

function showTandoorFallback() {
  document.getElementById('tandoor-fallback').classList.remove('hidden');
}

function copyJson() {
  const ta = document.getElementById('tandoor-json');
  ta.select();
  navigator.clipboard.writeText(ta.value).catch(() => document.execCommand('copy'));
  const btn = document.getElementById('copy-json-btn');
  btn.textContent = 'Kopiert!';
  setTimeout(() => btn.textContent = 'JSON kopieren', 2000);
}

// ── History ──────────────────────────────────────────────────────────────────

function formatDate(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return d.toLocaleDateString('de-DE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit'
  });
}

async function loadHistory() {
  try {
    const res = await fetch('/api/history');
    const entries = await res.json();
    renderHistory(entries);
  } catch (_) {}
}

function renderHistory(entries) {
  const section = document.getElementById('history-section');
  const container = document.getElementById('history-list');
  if (!section || !container) return;

  if (!Array.isArray(entries) || entries.length === 0) {
    section.classList.add('hidden');
    return;
  }

  section.classList.remove('hidden');
  container.innerHTML = '';
  entries.forEach(entry => {
    try {
      container.appendChild(buildHistoryCard(entry));
    } catch (e) {
      console.error('History card render error:', e, entry);
    }
  });
}

function buildHistoryCard(entry) {
  const recipe = entry.recipe_data?.recipe || {};
  const card = document.createElement('div');
  card.className = 'history-card';

  // ── Header (always visible) ──
  const header = document.createElement('div');
  header.className = 'history-card-header';

  const imageUrl = entry.image_url || recipe.image_url;
  if (imageUrl) {
    const img = document.createElement('img');
    img.className = 'history-thumb';
    img.src = imageUrl;
    img.alt = '';
    img.onerror = () => img.remove();
    header.appendChild(img);
  }

  const info = document.createElement('div');
  info.className = 'history-info';

  const title = document.createElement('h3');
  title.className = 'history-title';
  title.textContent = entry.title || 'Unbekanntes Rezept';
  info.appendChild(title);

  if (recipe.description) {
    const desc = document.createElement('p');
    desc.className = 'history-desc';
    desc.textContent = recipe.description;
    info.appendChild(desc);
  }

  // Meta-Tags (Portionen, Zeit, kcal)
  const metaTags = document.createElement('div');
  metaTags.className = 'meta-tags';
  const addMetaTag = (icon, text) => {
    const span = document.createElement('span');
    span.className = 'meta-tag';
    span.innerHTML = `<span class="icon">${icon}</span> ${text}`;
    metaTags.appendChild(span);
  };
  if (recipe.servings) addMetaTag('&#9201;', recipe.servings + ' Portionen');
  if (recipe.prep_time_minutes) addMetaTag('&#9201;', 'Vorbereitung: ' + recipe.prep_time_minutes + ' Min.');
  if (recipe.cook_time_minutes) addMetaTag('&#128293;', 'Kochen: ' + recipe.cook_time_minutes + ' Min.');
  if (recipe.nutrition?.kcal_per_serving) {
    const sourceLabel = { usda: ' (USDA)', gpt4_estimate: ' (Schätzung)' }[recipe.nutrition.source] || '';
    addMetaTag('&#128293;', Math.round(recipe.nutrition.kcal_per_serving) + ' kcal' + sourceLabel);
  }
  if (metaTags.children.length) info.appendChild(metaTags);

  if (recipe.tags?.length) {
    const tagList = document.createElement('div');
    tagList.className = 'tag-list history-tags';
    recipe.tags.forEach(tag => {
      const span = document.createElement('span');
      span.className = 'tag';
      span.textContent = tag;
      tagList.appendChild(span);
    });
    info.appendChild(tagList);
  }

  const meta = document.createElement('div');
  meta.className = 'history-meta';

  const dateSpan = document.createElement('span');
  dateSpan.className = 'history-date';
  dateSpan.textContent = formatDate(entry.extracted_at);
  meta.appendChild(dateSpan);

  if (entry.imported_at) {
    const badge = document.createElement('span');
    badge.className = 'history-imported-badge';
    badge.textContent = 'Importiert ' + formatDate(entry.imported_at);
    meta.appendChild(badge);
  }

  info.appendChild(meta);
  header.appendChild(info);

  // Controls
  const controls = document.createElement('div');
  controls.className = 'history-controls';

  const toggleBtn = document.createElement('button');
  toggleBtn.className = 'history-toggle-btn';
  toggleBtn.title = 'Auf-/Zuklappen';
  toggleBtn.innerHTML = '&#9660;';
  controls.appendChild(toggleBtn);

  const deleteBtn = document.createElement('button');
  deleteBtn.className = 'history-delete-btn';
  deleteBtn.title = 'Löschen';
  deleteBtn.innerHTML = '&#10005;';
  controls.appendChild(deleteBtn);

  header.appendChild(controls);
  card.appendChild(header);

  // ── Body (collapsed by default) ──
  const body = document.createElement('div');
  body.className = 'history-card-body hidden';

  const bodyInner = document.createElement('div');
  bodyInner.className = 'recipe-body';

  if (recipe.ingredients?.length) {
    const ingSection = document.createElement('div');
    ingSection.className = 'ingredients-section';
    const ingTitle = document.createElement('h3');
    ingTitle.textContent = 'Zutaten';
    ingSection.appendChild(ingTitle);
    const ul = document.createElement('ul');
    ul.className = 'ingredients-list';
    recipe.ingredients.forEach(ing => {
      const li = document.createElement('li');
      if (ing.amount || ing.unit) {
        const amountSpan = document.createElement('span');
        amountSpan.className = 'ingredient-amount';
        amountSpan.textContent = [ing.amount, ing.unit].filter(Boolean).join(' ');
        li.appendChild(amountSpan);
      }
      const nameSpan = document.createElement('span');
      nameSpan.textContent = ing.name;
      li.appendChild(nameSpan);
      if (ing.note) {
        const noteSpan = document.createElement('span');
        noteSpan.className = 'ingredient-note';
        noteSpan.textContent = '(' + ing.note + ')';
        li.appendChild(noteSpan);
      }
      ul.appendChild(li);
    });
    ingSection.appendChild(ul);
    bodyInner.appendChild(ingSection);
  }

  if (recipe.steps?.length) {
    const stepsSection = document.createElement('div');
    stepsSection.className = 'steps-section';
    const stepsTitle = document.createElement('h3');
    stepsTitle.textContent = 'Zubereitung';
    stepsSection.appendChild(stepsTitle);
    const ol = document.createElement('ol');
    ol.className = 'steps-list';
    recipe.steps.forEach(step => {
      const li = document.createElement('li');
      li.innerHTML = renderMarkdownBold(step);
      ol.appendChild(li);
    });
    stepsSection.appendChild(ol);
    bodyInner.appendChild(stepsSection);
  }

  // Hero-Bild im aufgeklappten Zustand (vor bodyInner einfügen)
  if (imageUrl) {
    const heroImg = document.createElement('img');
    heroImg.className = 'recipe-image';
    heroImg.src = imageUrl;
    heroImg.alt = '';
    heroImg.onerror = () => heroImg.remove();
    body.appendChild(heroImg);
  }
  body.appendChild(bodyInner);

  // Actions
  const actions = document.createElement('div');
  actions.className = 'recipe-actions';

  if (recipe.source_url) {
    const sourceLink = document.createElement('a');
    sourceLink.href = recipe.source_url;
    sourceLink.target = '_blank';
    sourceLink.className = 'btn btn-secondary';
    sourceLink.textContent = 'Originalrezept';
    actions.appendChild(sourceLink);
  }

  if (!entry.imported_at) {
    const importBtn = document.createElement('button');
    importBtn.className = 'btn btn-primary';
    importBtn.textContent = 'In Tandoor importieren';
    const importStatus = document.createElement('span');
    importStatus.className = 'import-status';

    importBtn.addEventListener('click', async () => {
      if (!tandoorConfigured) {
        importStatus.textContent = 'Tandoor nicht konfiguriert.';
        importStatus.className = 'import-status error';
        return;
      }
      importBtn.disabled = true;
      importStatus.textContent = 'Importiere...';
      importStatus.className = 'import-status';
      try {
        const payload = { ...entry.recipe_data, history_id: entry.id };
        const res = await fetch('/api/import', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok) {
          await loadHistory();
        } else {
          importStatus.textContent = 'Fehler: ' + (data.detail || 'Import fehlgeschlagen');
          importStatus.className = 'import-status error';
          importBtn.disabled = false;
        }
      } catch (_) {
        importStatus.textContent = 'Netzwerkfehler';
        importStatus.className = 'import-status error';
        importBtn.disabled = false;
      }
    });

    actions.appendChild(importBtn);
    actions.appendChild(importStatus);
  }

  body.appendChild(actions);
  card.appendChild(body);

  // ── Toggle ──
  toggleBtn.addEventListener('click', () => {
    const expanded = !body.classList.contains('hidden');
    body.classList.toggle('hidden', expanded);
    toggleBtn.innerHTML = expanded ? '&#9660;' : '&#9650;';
    card.classList.toggle('history-card--expanded', !expanded);
  });

  // ── Delete ──
  deleteBtn.addEventListener('click', async () => {
    if (!confirm('Rezept aus dem Verlauf löschen?')) return;
    try {
      await fetch('/api/history/' + entry.id, { method: 'DELETE' });
      card.remove();
      if (!document.querySelector('#history-list .history-card')) {
        document.getElementById('history-section').classList.add('hidden');
      }
    } catch (_) {}
  });

  return card;
}

// ── Event listeners ──────────────────────────────────────────────────────────

document.getElementById('extract-btn').addEventListener('click', startExtraction);
document.getElementById('url-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') startExtraction();
});
document.getElementById('import-btn').addEventListener('click', importToTandoor);
document.getElementById('copy-json-btn').addEventListener('click', copyJson);

// Init
checkHealth();
loadHistory();
