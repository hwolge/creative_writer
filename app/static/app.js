'use strict';

// ── State ─────────────────────────────────────────────────────────────────────

const S = {
  project: null,
  planOptions: null,      // array of ChapterOption from /plan/propose
  selectedOption: null,   // index into planOptions
  chapterNumber: null,
  currentScene: null,
  currentChapter: null,
  draft: null,            // { prose, facts_delta, scene_id }
};

// ── API helpers ───────────────────────────────────────────────────────────────

async function api(method, path, body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== null) opts.body = JSON.stringify(body);
  const res = await fetch(path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function loading(msg = 'Working…') {
  document.getElementById('loading-msg').textContent = msg;
  document.getElementById('loading-overlay').classList.add('visible');
}

function doneLoading() {
  document.getElementById('loading-overlay').classList.remove('visible');
}

function showAlert(containerId, type, html) {
  const el = document.getElementById(containerId);
  el.innerHTML = `<div class="alert alert-${type}">${html}</div>`;
}

function badge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ── Tab routing ───────────────────────────────────────────────────────────────

document.querySelectorAll('nav button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(`tab-${btn.dataset.tab}`).classList.add('active');
    if (btn.dataset.tab === 'state') loadState();
    if (btn.dataset.tab === 'archive') loadArchive();
    if (btn.dataset.tab === 'write') loadCurrentScene();
  });
});

// ── Status bar ────────────────────────────────────────────────────────────────

async function refreshStatus() {
  try {
    const data = await api('GET', '/project/status');
    document.getElementById('sb-project').textContent = data.project || '—';
    document.getElementById('sb-threads').textContent = data.open_threads ?? '—';

    const ch = data.current_chapter;
    document.getElementById('sb-chapter').textContent =
      ch ? `#${ch.number} ${ch.title || ''} [${ch.status}]` : '—';

    const sc = data.current_scene;
    document.getElementById('sb-scene').textContent =
      sc ? `#${sc.scene_id} seq ${sc.sequence} [${sc.status}]` : '—';

    const issues = data.continuity_issues;
    const wrap = document.getElementById('sb-issues-wrap');
    if (issues > 0) {
      wrap.style.display = '';
      document.getElementById('sb-issues').textContent = issues;
    } else {
      wrap.style.display = 'none';
    }

    S.project = data.project;
    S.currentScene = data.current_scene;
    S.currentChapter = data.current_chapter;

    // Pre-fill arc goal from seeded chapter if available
    if (ch && ch.status === 'planned' && ch.arc_goal) {
      const input = document.getElementById('arc-goal-input');
      if (!input.value) input.value = ch.arc_goal;
      S.chapterNumber = ch.number;
    } else if (ch) {
      S.chapterNumber = ch ? ch.number + (ch.status === 'complete' ? 1 : 0) : 1;
    }
  } catch (e) {
    console.warn('Status fetch failed:', e.message);
  }
}

// ── PLAN tab ──────────────────────────────────────────────────────────────────

document.getElementById('btn-propose').addEventListener('click', async () => {
  const goal = document.getElementById('arc-goal-input').value.trim();
  if (!goal) { alert('Enter an arc goal first.'); return; }

  loading('Asking GPT-5.4 to propose 3 chapter options… (this may take ~30s)');
  try {
    const data = await api('POST', '/plan/propose', { arc_goal: goal });
    S.planOptions = data.options;
    S.selectedOption = null;
    renderPlanOptions(data.options);
    document.getElementById('plan-options-section').style.display = '';
    document.getElementById('plan-result').innerHTML = '';
    document.getElementById('btn-confirm-plan').disabled = true;
  } catch (e) {
    alert('Error: ' + e.message);
  } finally {
    doneLoading();
  }
});

function renderPlanOptions(options) {
  const grid = document.getElementById('options-grid');
  grid.innerHTML = '';
  options.forEach((opt, i) => {
    const card = document.createElement('div');
    card.className = 'option-card';
    card.innerHTML = `
      <h3>${esc(opt.title)}</h3>
      <div class="meta"><strong>POV:</strong> ${esc(opt.pov)}</div>
      <div class="meta">${esc(opt.emotional_arc)}</div>
      <ul class="scenes-list">
        ${opt.scenes.map(s => `<li>${esc(s.brief)}</li>`).join('')}
      </ul>
      <div class="pills">
        ${opt.reveals.map(r => `<span class="pill">${esc(r)}</span>`).join('')}
        ${opt.continuity_risks.map(r => `<span class="pill warn">${esc(r)}</span>`).join('')}
      </div>`;
    card.addEventListener('click', () => {
      document.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
      card.classList.add('selected');
      S.selectedOption = i;
      document.getElementById('btn-confirm-plan').disabled = false;
    });
    grid.appendChild(card);
  });
}

document.getElementById('btn-confirm-plan').addEventListener('click', async () => {
  if (S.selectedOption === null) return;
  const chNum = S.chapterNumber || 1;
  loading('Saving chapter plan…');
  try {
    const data = await api('POST', '/plan/confirm', {
      chapter_number: chNum,
      option_index: S.selectedOption,
      options: S.planOptions,
    });
    const ch = data.chapter;
    showAlert('plan-result', 'success',
      `<strong>Chapter ${ch.number} planned: "${esc(ch.title)}"</strong><br>
       ${data.scenes_queued} scenes queued. Switch to the <strong>Write</strong> tab to begin.`);
    document.getElementById('btn-confirm-plan').disabled = true;
    document.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
    await refreshStatus();
  } catch (e) {
    showAlert('plan-result', 'error', esc(e.message));
  } finally {
    doneLoading();
  }
});

document.getElementById('btn-replan').addEventListener('click', () => {
  document.getElementById('plan-options-section').style.display = 'none';
  S.planOptions = null;
  S.selectedOption = null;
});

// ── WRITE tab ─────────────────────────────────────────────────────────────────

async function loadCurrentScene() {
  try {
    const data = await api('GET', '/scene/current');
    const noScene = document.getElementById('write-no-scene');
    const sceneArea = document.getElementById('write-scene-area');

    if (!data.scene) {
      noScene.style.display = '';
      sceneArea.style.display = 'none';
      return;
    }

    noScene.style.display = 'none';
    sceneArea.style.display = '';

    document.getElementById('write-brief-text').textContent = data.scene.brief;
    S.currentScene = data.scene;

    const chCtx = document.getElementById('write-chapter-context');
    const chText = document.getElementById('write-chapter-text');
    if (data.chapter) {
      chText.textContent = `#${data.chapter.number} "${data.chapter.title || ''}" — ${data.chapter.arc_goal}`;
      chCtx.style.display = '';
    } else {
      chCtx.style.display = 'none';
    }

    // If there's an existing draft, show it
    if (data.scene.status === 'draft' && data.scene.full_text) {
      document.getElementById('prose-editor').value = data.scene.full_text;
      S.draft = { prose: data.scene.full_text, facts_delta: data.scene.facts_delta, scene_id: data.scene.scene_id };
      document.getElementById('draft-area').style.display = '';
      document.getElementById('approval-result').style.display = 'none';
      renderDeltaFlags(data.scene.facts_delta);
    } else {
      document.getElementById('draft-area').style.display = 'none';
      document.getElementById('prose-editor').value = '';
      document.getElementById('approval-result').style.display = 'none';
    }
  } catch (e) {
    console.warn('loadCurrentScene error:', e.message);
  }
}

document.getElementById('btn-write').addEventListener('click', async () => {
  const note = document.getElementById('author-note').value.trim();
  loading('Writing scene… GPT-5.4 is drafting prose. This may take 30–60 seconds.');
  try {
    const data = await api('POST', '/scene/write', { author_note: note });
    S.draft = data;
    document.getElementById('prose-editor').value = data.prose;
    document.getElementById('draft-area').style.display = '';
    document.getElementById('approval-result').style.display = 'none';
    document.getElementById('author-note').value = '';
    renderDeltaFlags(data.facts_delta);
    await refreshStatus();
  } catch (e) {
    alert('Write error: ' + e.message);
  } finally {
    doneLoading();
  }
});

function renderDeltaFlags(delta) {
  const flags = delta?.continuity_flags || [];
  const box = document.getElementById('delta-flags');
  const list = document.getElementById('delta-flags-list');
  if (flags.length === 0) { box.style.display = 'none'; return; }
  box.style.display = '';
  list.innerHTML = flags.map(f =>
    `<li>[${esc(f.severity.toUpperCase())}] ${esc(f.description)}</li>`
  ).join('');
}

document.getElementById('btn-approve').addEventListener('click', async () => {
  const prose = document.getElementById('prose-editor').value.trim();
  if (!prose) { alert('Prose is empty.'); return; }
  loading('Reconciling state… (gpt-5.4-mini is validating facts)');
  try {
    const data = await api('POST', '/scene/approve', { prose });
    document.getElementById('draft-area').style.display = 'none';
    const approvalEl = document.getElementById('approval-result');
    approvalEl.style.display = '';

    let html = `<div class="alert alert-success">
      <strong>Scene approved.</strong><br>${esc(data.summary)}
    </div>`;

    if (data.low_confidence_items?.length) {
      html += `<div class="alert alert-warn"><strong>Low-confidence items flagged:</strong><ul class="flags-list">
        ${data.low_confidence_items.map(i => `<li>${esc(i)}</li>`).join('')}
      </ul></div>`;
    }

    if (data.chapter_complete) {
      html += `<div class="alert alert-info"><strong>Chapter complete!</strong><br>
        ${data.chapter_summary ? esc(data.chapter_summary) : ''}
        <br><br>Go to <strong>Plan</strong> to plan the next chapter.</div>`;
    } else {
      html += `<div class="btn-row">
        <button class="btn btn-primary" id="btn-next-scene">Write Next Scene →</button>
      </div>`;
    }

    approvalEl.innerHTML = html;

    document.getElementById('btn-next-scene')?.addEventListener('click', async () => {
      await loadCurrentScene();
      approvalEl.style.display = 'none';
    });

    await refreshStatus();
  } catch (e) {
    alert('Approve error: ' + e.message);
  } finally {
    doneLoading();
  }
});

document.getElementById('btn-reject').addEventListener('click', () => {
  document.getElementById('draft-area').style.display = 'none';
  document.getElementById('author-note').value = '';
  S.draft = null;
  // Scroll to the write controls so user can add a note
  document.getElementById('write-controls').scrollIntoView({ behavior: 'smooth' });
});

// ── STATE tab ─────────────────────────────────────────────────────────────────

async function loadState() {
  await Promise.all([loadCharacters(), loadThreads(), loadIssues(), loadTimeline()]);
}

async function loadCharacters() {
  try {
    const chars = await api('GET', '/state/characters');
    const grid = document.getElementById('chars-grid');
    if (!chars.length) { grid.innerHTML = '<div class="empty-state">No characters yet.</div>'; return; }
    grid.innerHTML = chars.map(c => `
      <div class="char-card" data-name="${esc(c.name)}">
        <h4>${esc(c.name)}</h4>
        <div class="char-role">${esc(c.role || '')}</div>
        ${c.status ? `<div class="char-role" style="margin-top:4px;font-style:italic">${esc(c.status)}</div>` : ''}
      </div>`).join('');

    grid.querySelectorAll('.char-card').forEach(card => {
      card.addEventListener('click', () => toggleCharDetail(card, card.dataset.name));
    });
  } catch (e) { console.warn(e); }
}

async function toggleCharDetail(card, name) {
  // Remove any open drawers
  document.querySelectorAll('.detail-drawer').forEach(d => d.remove());
  const existing = card.nextElementSibling;
  if (existing?.classList.contains('detail-drawer') && existing.classList.contains('open')) {
    existing.remove(); return;
  }

  try {
    const char = await api('GET', `/state/characters/${encodeURIComponent(name)}`);
    const drawer = document.createElement('div');
    drawer.className = 'detail-drawer open';
    const factsJson = JSON.stringify(char.facts, null, 2);
    const samples = (char.voice_samples || []).map(s => `<em>"${esc(s)}"</em>`).join('<br>');
    drawer.innerHTML = `
      <pre>${esc(factsJson)}</pre>
      ${samples ? `<div style="margin-top:10px;font-size:13px;color:var(--text-muted)">${samples}</div>` : ''}`;
    card.insertAdjacentElement('afterend', drawer);
  } catch (e) { console.warn(e); }
}

async function loadThreads() {
  try {
    const threads = await api('GET', '/state/threads');
    const tbody = document.getElementById('threads-tbody');
    if (!threads.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No threads yet.</td></tr>'; return; }
    tbody.innerHTML = threads.map(t => `
      <tr>
        <td><code>${esc(t.thread_id)}</code></td>
        <td>${esc(t.title)}</td>
        <td>${badge(t.status)}</td>
        <td>${esc(t.summary)}</td>
      </tr>`).join('');
  } catch (e) { console.warn(e); }
}

async function loadIssues() {
  try {
    const issues = await api('GET', '/state/issues?unresolved_only=true');
    const tbody = document.getElementById('issues-tbody');
    const card = document.getElementById('issues-card');
    if (!issues.length) {
      card.style.display = 'none'; return;
    }
    card.style.display = '';
    tbody.innerHTML = issues.map(i => `
      <tr>
        <td>${i.issue_id}</td>
        <td>${badge(i.severity)}</td>
        <td>${esc(i.description)}</td>
        <td><button class="btn btn-secondary" style="padding:4px 10px;font-size:12px"
            onclick="resolveIssue(${i.issue_id}, this)">Resolve</button></td>
      </tr>`).join('');
  } catch (e) { console.warn(e); }
}

window.resolveIssue = async (id, btn) => {
  btn.disabled = true;
  try {
    await api('POST', `/state/issues/${id}/resolve`);
    btn.closest('tr').remove();
    await refreshStatus();
  } catch (e) { btn.disabled = false; alert(e.message); }
};

async function loadTimeline() {
  try {
    const events = await api('GET', '/state/timeline');
    const tbody = document.getElementById('timeline-tbody');
    if (!events.length) { tbody.innerHTML = '<tr><td colspan="2" class="empty-state">No timeline events yet.</td></tr>'; return; }
    tbody.innerHTML = events.map(e => `
      <tr><td>${e.story_day ?? '?'}</td><td>${esc(e.description)}</td></tr>`).join('');
  } catch (e) { console.warn(e); }
}

// ── ARCHIVE tab ───────────────────────────────────────────────────────────────

async function loadArchive() {
  await loadChapters();
}

async function loadChapters() {
  try {
    const chapters = await api('GET', '/archive/chapters');
    const tbody = document.getElementById('chapters-tbody');
    if (!chapters.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No chapters yet.</td></tr>'; return; }
    tbody.innerHTML = chapters.map(c => `
      <tr class="chapter-row" data-num="${c.number}">
        <td>#${c.number}</td>
        <td>${esc(c.title || '—')}</td>
        <td style="max-width:300px">${esc(c.arc_goal)}</td>
        <td>${badge(c.status)}</td>
      </tr>`).join('');

    tbody.querySelectorAll('.chapter-row').forEach(row => {
      row.addEventListener('click', () => loadSceneList(parseInt(row.dataset.num)));
    });
  } catch (e) { console.warn(e); }
}

async function loadSceneList(chapterNum) {
  const section = document.getElementById('scenes-section');
  document.getElementById('scene-viewer').style.display = 'none';
  section.style.display = '';
  document.getElementById('scenes-heading').textContent = `Scenes — Chapter ${chapterNum}`;

  try {
    const scenes = await api('GET', `/archive/scenes?chapter=${chapterNum}`);
    const tbody = document.getElementById('scenes-tbody');
    if (!scenes.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty-state">No scenes.</td></tr>'; return; }
    tbody.innerHTML = scenes.map(s => `
      <tr style="cursor:pointer" data-scene-id="${s.scene_id}">
        <td>${s.scene_id}</td>
        <td>${s.sequence}</td>
        <td>${esc(s.brief)}</td>
        <td>${badge(s.status)}</td>
      </tr>`).join('');

    tbody.querySelectorAll('tr[data-scene-id]').forEach(row => {
      row.addEventListener('click', () => showSceneViewer(parseInt(row.dataset.sceneId), row.cells[2].textContent));
    });
  } catch (e) { console.warn(e); }
}

async function showSceneViewer(sceneId, brief) {
  try {
    const scene = await api('GET', `/archive/scenes/${sceneId}`);
    document.getElementById('scene-viewer-title').textContent = `Scene ${sceneId} — ${brief}`;
    document.getElementById('scene-viewer-text').textContent = scene.full_text || '[No text yet]';
    document.getElementById('scene-viewer').style.display = '';
    document.getElementById('scene-viewer').scrollIntoView({ behavior: 'smooth' });
  } catch (e) { alert(e.message); }
}

document.getElementById('btn-close-viewer').addEventListener('click', () => {
  document.getElementById('scene-viewer').style.display = 'none';
});

document.getElementById('btn-search').addEventListener('click', doSearch);
document.getElementById('search-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') doSearch();
});

async function doSearch() {
  const q = document.getElementById('search-input').value.trim();
  if (q.length < 2) return;
  const results = document.getElementById('search-results');
  try {
    const data = await api('GET', `/archive/search?q=${encodeURIComponent(q)}`);
    if (!data.length) { results.innerHTML = '<div class="empty-state">No results.</div>'; return; }
    results.innerHTML = data.map(r => `
      <div class="scene-result" data-scene-id="${r.scene_id}">
        <div class="scene-meta">Scene ${r.scene_id} · Chapter ${r.chapter_id}</div>
        <div class="scene-brief">${esc(r.brief)}</div>
        ${r.summary ? `<div style="font-size:13px;color:var(--text-muted);margin-top:4px">${esc(r.summary)}</div>` : ''}
      </div>`).join('');

    results.querySelectorAll('.scene-result').forEach(el => {
      el.addEventListener('click', () => {
        // Switch to archive tab if not already there
        document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
        document.querySelector('[data-tab="archive"]').classList.add('active');
        document.getElementById('tab-archive').classList.add('active');
        showSceneViewer(parseInt(el.dataset.sceneId), el.querySelector('.scene-brief').textContent);
      });
    });
  } catch (e) { results.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`; }
}

// ── Boot ──────────────────────────────────────────────────────────────────────

(async () => {
  await refreshStatus();
  await loadCurrentScene();
})();
