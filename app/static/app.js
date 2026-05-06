'use strict';

// ── Reverse-proxy prefix ──────────────────────────────────────────────────────
// The page is always served at the root of the app, so window.location.pathname
// IS the proxy prefix.  Examples:
//   https://wolge.se/writer/  → ROOT = "/writer"
//   http://localhost:8000/    → ROOT = ""
// All fetch() calls go through api() which prepends ROOT automatically.
const ROOT = window.location.pathname.replace(/\/$/, '');

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
  const res = await fetch(ROOT + path, opts);
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
    if (btn.dataset.tab === 'projects') loadProjects();
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
      document.getElementById('approval-result').style.display = 'none';
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

    // If there's an existing draft, show it; otherwise just update the brief
    // without touching approval-result — let the user keep reading it after a
    // tab-switch, and only clear it when they actively start writing.
    if (data.scene.status === 'draft' && data.scene.full_text) {
      document.getElementById('prose-editor').value = data.scene.full_text;
      S.draft = { prose: data.scene.full_text, facts_delta: data.scene.facts_delta, scene_id: data.scene.scene_id };
      document.getElementById('draft-area').style.display = '';
      document.getElementById('approval-result').style.display = 'none';
      renderDeltaFlags(data.scene.facts_delta);
    } else {
      document.getElementById('draft-area').style.display = 'none';
      document.getElementById('prose-editor').value = '';
      // Do NOT hide approval-result here — it may still be showing the previous
      // scene's result. It gets cleared explicitly when a new write is started.
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
      html += `<div class="alert alert-warn">
        <strong>${data.low_confidence_items.length} low-confidence item${data.low_confidence_items.length > 1 ? 's' : ''} flagged</strong>
        — saved to <strong>State → Continuity Issues</strong> where you can auto-resolve or dismiss each one.
        <ul class="flags-list" style="margin-top:6px">
          ${data.low_confidence_items.map(i => `<li>${esc(i)}</li>`).join('')}
        </ul>
      </div>`;
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

// ── Add character manually ────────────────────────────────────────────────────

window.toggleAddCharForm = () => {
  const form = document.getElementById('add-char-form');
  const visible = form.style.display !== 'none';
  form.style.display = visible ? 'none' : 'block';
  if (!visible) {
    document.getElementById('new-char-name').focus();
    document.getElementById('add-char-error').style.display = 'none';
  }
};

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('btn-add-char')?.addEventListener('click', async () => {
    const name = document.getElementById('new-char-name').value.trim();
    const role = document.getElementById('new-char-role').value.trim();
    const appearance = document.getElementById('new-char-appearance').value.trim();
    const voice = document.getElementById('new-char-voice').value.trim();
    const errEl = document.getElementById('add-char-error');

    if (!name) { errEl.textContent = 'Name is required.'; errEl.style.display = 'block'; return; }

    const facts = {};
    if (role) facts.role = role;
    if (appearance) facts.appearance = appearance;

    const body = { name, facts };
    if (voice) body.voice_samples = [voice];

    const btn = document.getElementById('btn-add-char');
    btn.disabled = true;
    btn.textContent = 'Adding…';
    errEl.style.display = 'none';

    try {
      await api('POST', '/state/characters', body);
      // Clear form
      ['new-char-name','new-char-role','new-char-appearance','new-char-voice'].forEach(id => {
        document.getElementById(id).value = '';
      });
      document.getElementById('add-char-form').style.display = 'none';
      await loadCharacters();
    } catch (e) {
      errEl.textContent = e.message || 'Failed to add character.';
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false;
      btn.textContent = 'Add Character';
    }
  });
});

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
      <tr id="issue-row-${i.issue_id}">
        <td>${i.issue_id}</td>
        <td>${badge(i.severity)}</td>
        <td>${esc(i.description)}</td>
        <td style="white-space:nowrap;display:flex;gap:6px">
          <button class="btn btn-secondary" style="padding:4px 10px;font-size:12px"
              onclick="resolveIssue(${i.issue_id}, this)">Dismiss</button>
          <button class="btn btn-primary" style="padding:4px 10px;font-size:12px"
              onclick="autoResolveIssue(${i.issue_id}, this)">Auto-resolve ✦</button>
        </td>
      </tr>`).join('');
  } catch (e) { console.warn(e); }
}

window.resolveIssue = async (id, btn) => {
  btn.disabled = true;
  try {
    await api('POST', `/state/issues/${id}/resolve`);
    document.getElementById(`issue-row-${id}`)?.remove();
    const tbody = document.getElementById('issues-tbody');
    if (!tbody.querySelector('tr')) {
      document.getElementById('issues-card').style.display = 'none';
    }
    await refreshStatus();
  } catch (e) { btn.disabled = false; alert(e.message); }
};

window.autoResolveIssue = async (id, btn) => {
  const row = document.getElementById(`issue-row-${id}`);
  const descCell = row?.cells[2];
  btn.disabled = true;
  btn.textContent = 'Resolving…';
  try {
    const data = await api('POST', `/state/issues/${id}/auto-resolve`);
    // Replace the row with a success summary, then fade it out
    if (row) {
      row.innerHTML = `
        <td colspan="4" class="alert alert-success" style="padding:8px 12px">
          <strong>✦ Auto-resolved:</strong> ${esc(data.resolution)}
          ${data.character_updates?.length ? `<br><small>Updated: ${data.character_updates.map(u => u.name).join(', ')}</small>` : ''}
        </td>`;
      setTimeout(() => {
        row.remove();
        const tbody = document.getElementById('issues-tbody');
        if (tbody && !tbody.querySelector('tr')) {
          document.getElementById('issues-card').style.display = 'none';
        }
      }, 4000);
    }
    await refreshStatus();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Auto-resolve ✦';
    alert('Auto-resolve failed: ' + e.message);
  }
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

function proseToHtml(text) {
  if (!text) return '<p>[No text yet]</p>';
  return text.split(/\n\n+/)
    .map(p => p.trim()).filter(Boolean)
    .map(p => `<p>${esc(p).replace(/\n/g, '<br>')}</p>`)
    .join('');
}

async function showSceneViewer(sceneId, brief) {
  try {
    const scene = await api('GET', `/archive/scenes/${sceneId}`);
    document.getElementById('scene-viewer-title').textContent = `Scene ${sceneId} — ${brief}`;
    document.getElementById('scene-viewer-text').innerHTML = proseToHtml(scene.full_text);
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

// ── PROJECTS tab ─────────────────────────────────────────────────────────────

async function loadProjects() {
  const tbody = document.getElementById('projects-tbody');
  try {
    const data = await api('GET', '/project/list');
    if (!data.projects.length) {
      tbody.innerHTML = '<tr><td colspan="3" class="empty-state">No projects found.</td></tr>';
      return;
    }
    tbody.innerHTML = data.projects.map(p => `
      <tr id="proj-row-${esc(p.slug)}">
        <td><code>${esc(p.slug)}</code></td>
        <td>${p.active ? '<span class="badge badge-open">active</span>' : ''}</td>
        <td style="display:flex;gap:6px">
          ${!p.active ? `<button class="btn btn-primary" style="padding:4px 10px;font-size:12px"
              onclick="switchProject('${esc(p.slug)}', this)">Switch</button>` : ''}
          ${!p.active ? `<button class="btn btn-danger" style="padding:4px 10px;font-size:12px"
              onclick="deleteProject('${esc(p.slug)}', this)">Delete</button>` : ''}
        </td>
      </tr>`).join('');
  } catch (e) {
    if (tbody) tbody.innerHTML = `<tr><td colspan="3" class="alert alert-error">${esc(e.message)}</td></tr>`;
  }
}

window.switchProject = async (slug, btn) => {
  btn.disabled = true;
  btn.textContent = 'Switching…';
  try {
    await api('POST', `/project/switch/${encodeURIComponent(slug)}`);
    await refreshStatus();
    await loadLanguage();
    await loadProjects();   // re-render active badge
    // Reload Write tab state for the new project
    await loadCurrentScene();
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Switch';
    alert('Switch failed: ' + e.message);
  }
};

window.deleteProject = async (slug, btn) => {
  if (!confirm(`Permanently delete project "${slug}"? This cannot be undone.`)) return;
  btn.disabled = true;
  try {
    await api('DELETE', `/project/${encodeURIComponent(slug)}`);
    document.getElementById(`proj-row-${slug}`)?.remove();
  } catch (e) {
    btn.disabled = false;
    alert('Delete failed: ' + e.message);
  }
};

document.getElementById('btn-load-template').addEventListener('click', async () => {
  try {
    const tmpl = await api('GET', '/project/seed-template');
    document.getElementById('new-project-seed').value = JSON.stringify(tmpl, null, 2);
    // Pre-fill slug from template if slug field is empty
    const slugInput = document.getElementById('new-project-slug');
    if (!slugInput.value && tmpl.project_slug) slugInput.value = tmpl.project_slug;
  } catch (e) { alert('Could not load template: ' + e.message); }
});

document.getElementById('btn-create-project').addEventListener('click', async () => {
  const slug = document.getElementById('new-project-slug').value.trim();
  const seedRaw = document.getElementById('new-project-seed').value.trim();
  const resultEl = document.getElementById('create-project-result');

  if (!slug) { alert('Enter a project slug.'); return; }
  if (!seedRaw) { alert('Paste a seed JSON or load the template first.'); return; }

  let seed;
  try { seed = JSON.parse(seedRaw); }
  catch (e) { alert('Invalid JSON: ' + e.message); return; }

  loading('Creating project…');
  try {
    const data = await api('POST', '/project/create', { slug, seed });
    resultEl.innerHTML = `<div class="alert alert-success">
      <strong>Project "${esc(data.created)}" created.</strong>
      ${data.characters} characters · ${data.plot_threads} threads · ${data.arc_goals} arc goals.<br>
      <button class="btn btn-primary" style="margin-top:8px"
        onclick="switchProject('${esc(data.created)}', this)">Switch to this project →</button>
    </div>`;
    document.getElementById('new-project-slug').value = '';
    document.getElementById('new-project-seed').value = '';
    await loadProjects();
  } catch (e) {
    resultEl.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
  } finally {
    doneLoading();
  }
});

// ── Language selector ─────────────────────────────────────────────────────────

async function loadLanguage() {
  try {
    const bible = await api('GET', '/state/bible');
    const lang = bible.output_language || 'English';
    const sel = document.getElementById('language-select');
    // Select matching option, or add a custom one if not in the list
    const match = [...sel.options].find(o => o.value.toLowerCase() === lang.toLowerCase());
    if (match) {
      sel.value = match.value;
    } else {
      const opt = new Option(lang, lang, true, true);
      sel.appendChild(opt);
    }
  } catch (e) { /* no project loaded yet — ignore */ }
}

document.getElementById('language-select').addEventListener('change', async (e) => {
  const lang = e.target.value;
  try {
    await api('PATCH', '/state/bible', { output_language: lang });
  } catch (err) {
    console.warn('Failed to save language:', err.message);
  }
});

// ── Boot ──────────────────────────────────────────────────────────────────────

(async () => {
  await refreshStatus();
  await loadCurrentScene();
  await loadLanguage();
  await loadProjects();   // pre-load so the Projects tab is ready instantly
})();
