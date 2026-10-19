'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const state = {events: [], active: null, photo: null, tab: 'photos', filter: 'all', busy: false,
  settings: null, ai: null, caption: null, editing: false, revision: 0, job: null, facts: null, factsDirty: false,
  compareOriginal: false, generatingCaption: false};
const editDefaults = {rotation:0,flip_horizontal:false,flip_vertical:false,brightness:1,contrast:1,saturation:1,sharpness:1};
const photoSettingKeys = ['x','y','zoom',...Object.keys(editDefaults)];
let pendingPhoto = null, photoTimer = null, photoWrites = Promise.resolve(), exportSettingsWrites = Promise.resolve();

async function api(path, options = {}) {
  const headers = options.body && !(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {};
  const response = await fetch(`/api${path}`, {...options, headers: {...headers, ...options.headers}});
  if (!response.ok) {
    let message = 'Something went wrong. Please try again.';
    try {
      const result = await response.json();
      message = Array.isArray(result.detail) ? result.detail.map(item => `${item.loc.slice(1).join(' ')}: ${item.msg}`).join('; ') : result.detail || message;
    } catch { /* Keep the useful fallback for unexpected server responses. */ }
    throw new Error(message);
  }
  return response.json();
}

function toast(message, error = false) {
  const item = document.createElement('div');
  item.className = `toast${error ? ' error' : ''}`;
  item.textContent = message;
  // Keep quick actions from stacking notices over the photo controls.
  $('#toasts').replaceChildren(item);
  setTimeout(() => item.remove(), error ? 8500 : 5000);
}

function reportError(error) { console.error(error); toast(error.message || String(error), true); }
function eventURL(suffix = '') { return `/events/${state.active.id}${suffix}`; }
function photoURL(photo, kind = 'thumbnail') { return `/api/events/${state.active.id}/photos/${photo.id}/${kind}`; }
function dateLabel(value) { return new Intl.DateTimeFormat(undefined, {month:'short', day:'numeric', year:'numeric'}).format(new Date(`${value}T12:00:00`)); }
function selectedPhotos() { return state.active?.photos.filter(photo => photo.selected) || []; }
function selectedPhoto() { return state.active?.photos.find(photo => photo.id === state.photo); }
function isLocalAI() { return state.ai?.provider === 'Ollama'; }
function canDownload() { const photos = selectedPhotos(); return photos.length > 0 && photos.every(photo => photo.exported_at); }
function disabled() { return state.busy ? 'disabled' : ''; }
function leaveCaption() { return !(state.caption?.dirty || state.factsDirty) || confirm('You have unsaved caption or event facts. Leave without saving them?'); }

function renderSidebar() {
  $('#event-count').textContent = state.events.length;
  $('#library-nav').classList.toggle('active', !state.active);
  $('#recent-events').innerHTML = state.events.length ? state.events.slice(0, 6).map(event => `
    <button class="recent-event ${state.active?.id === event.id ? 'current' : ''}" data-event="${event.id}" ${disabled()}>
      <span class="event-dot"></span><span>${escapeHTML(event.name)}</span>
    </button>`).join('') : '<p class="no-recent">Your next story starts<br>with a new event.</p>';
  $('#breadcrumb').textContent = state.active ? 'Event workspace' : 'Event library';
  $$('[data-action="new-event"], [data-action="library"]', $('.sidebar')).forEach(button => {
    if (button.tagName === 'BUTTON') button.disabled = state.busy;
  });
}

function renderLibrary(query = '') {
  const total = state.events.reduce((sum, event) => sum + event.photos.length, 0);
  const exported = state.events.reduce((sum, event) => sum + event.photos.filter(photo => photo.exported_at).length, 0);
  $('#main').innerHTML = `
    <div class="page-heading"><div><p class="eyebrow">THE STORIES. THE PEOPLE. THE MISSION.</p>
      <h1>Your ministry. In focus.</h1><p class="subheading">A little less photo prep. A little more time for the story.</p></div>
      <button class="button primary" data-action="new-event">${icon('plus')}New event</button></div>
    <div class="stats-row">
      ${stat('folder', state.events.length, 'Events organized')}
      ${stat('photo', total, 'Original photos preserved')}
      ${stat('check', exported, 'Photos ready to share')}
    </div>
    <div class="section-heading"><h2>Your events</h2>${state.events.length ? '<input class="search" id="event-search" aria-label="Search events" placeholder="Search your events…">' : '<span>A PLACE FOR EVERY PART OF YOUR COVERAGE</span>'}</div>
    ${state.events.length ? '<div class="event-grid" id="event-grid"></div>' : `
    <section class="empty-hero">
      <div class="empty-main"><div class="empty-art">${icon('photo')}</div><h2>Make room for<br>your next story.</h2>
        <p>Bring your event photos together, add your DMM watermark, and prepare captions with care.</p>
        <button class="button primary" data-action="new-event">Create your first event${icon('arrow')}</button></div>
      <div class="empty-steps">
        ${step('01','One event, all in one place','Originals, edited photos, and captions get their own folders.')}
        ${step('02','Your familiar DMM branding','Load your transparent watermark and frame every photo.')}
        ${step('03','Ready for your final review','Draft a factual caption, export your photos, and share your story.')}
      </div>
    </section>`}
    <div class="local-note">${icon('shield')}<span><strong>Your photos stay on your computer.</strong> Choose local AI captions with Ollama, or send event text to OpenAI using your API account.</span></div>`;
  if (state.events.length) renderEventCards(query);
  renderSidebar();
}

function stat(name, value, label) { return `<div class="stat"><div class="stat-icon">${icon(name)}</div><div><div class="stat-value">${value}</div><div class="stat-label">${label}</div></div></div>`; }
function step(number, title, description) { return `<div class="step"><div class="step-number">${number}</div><div><h3>${title}</h3><p>${description}</p></div></div>`; }

function renderEventCards(query = '') {
  const events = state.events.filter(event => event.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  $('#event-grid').innerHTML = events.length ? events.map(event => {
    const cover = event.photos.find(photo => photo.favorite) || event.photos[0];
    return `<button class="event-card" data-event="${event.id}">
      <div class="event-cover">${cover ? `<img src="/api/events/${event.id}/photos/${cover.id}/thumbnail" alt="" loading="lazy">` : icon('folder')}</div>
      <div class="event-card-content"><div class="event-date">${escapeHTML(dateLabel(event.date))}</div><h3>${escapeHTML(event.name)}</h3>
      <div class="event-meta"><span>${event.photos.length} photo${event.photos.length === 1 ? '' : 's'}</span><span>${event.photos.filter(photo => photo.exported_at).length} exported &nbsp; ↗</span></div></div>
    </button>`;
  }).join('') : '<p class="no-matches">No events match your search.</p>';
}

async function refreshEvents() { state.events = await api('/events'); renderSidebar(); }

async function openEvent(id) {
  if (state.busy) return;
  if (state.active?.id === id) return;
  if (!leaveCaption()) return;
  await flushPhoto();
  const [event, caption] = await Promise.all([api(`/events/${id}`), api(`/events/${id}/captions`)]);
  state.active = event; state.photo = event.photos[0]?.id || null; state.tab = 'photos'; state.filter = 'all'; state.job = null;
  state.compareOriginal = false;
  state.facts = {activities:event.activities, purpose:event.purpose, outcomes:event.outcomes}; state.factsDirty = false;
  state.caption = {text:caption.text, saved:caption.text, dirty:false, missing:[], style:'album', photo_caption:'', include_footer:true, include_credit:true, stale:false, mode:'ai', length:'standard', instructions:'', generatedMode:null};
  renderWorkspace();
}

async function library() {
  if (state.busy || !leaveCaption()) return;
  await flushPhoto();
  state.active = null; state.caption = null; state.photo = null; state.facts = null; state.factsDirty = false;
  await refreshEvents(); renderLibrary();
}

function renderWorkspace() {
  const event = state.active;
  if (!event) return renderLibrary();
  $('#main').innerHTML = `
    <div class="page-heading event-heading"><div><p class="eyebrow">EVENT WORKSPACE</p><h1>${escapeHTML(event.name)}</h1>
      <div class="meta-line"><span>${escapeHTML(dateLabel(event.date))}</span>${event.venue ? `<span>·</span><span>${escapeHTML(event.venue)}</span>` : ''}<span>·</span><span>${event.photos.length} photos</span></div></div>
      <div class="heading-actions"><button class="button secondary small" data-action="edit-event" ${disabled()}>${icon('edit')}Event details</button>
      <button class="button secondary small" data-action="open-folder">${icon('folder')}Open folder</button></div></div>
    <div class="tabs" role="tablist" aria-label="Event tools">
      <button class="tab ${state.tab === 'photos' ? 'active' : ''}" data-tab="photos" role="tab" aria-selected="${state.tab === 'photos'}" ${state.generatingCaption ? 'disabled' : ''}>${icon('photo')}Photos<span class="tab-count">${event.photos.length}</span></button>
      <button class="tab ${state.tab === 'captions' ? 'active' : ''}" data-tab="captions" role="tab" aria-selected="${state.tab === 'captions'}" ${state.generatingCaption ? 'disabled' : ''}>${icon('text')}Caption maker</button>
    </div>
    <section id="event-pane" aria-label="${state.tab === 'photos' ? 'Photo workspace' : 'Caption maker'}">${state.tab === 'photos' ? photosHTML() : captionsHTML()}</section>
    <div class="storage-strip">${icon('folder')}<span>${escapeHTML(event.folder)}</span></div>`;
  renderSidebar();
  if (state.tab === 'photos') {
    renderGallery(); renderPreview(); renderJob(); bindDropzone();
  }
}

function photosHTML() {
  const event = state.active;
  return `
    ${!event.has_watermark ? `<div class="watermark-notice"><p><strong>Bring your DMM watermark.</strong>Load your original transparent PNG. We’ll keep its design and remember it for new events.</p><button class="button secondary small" data-action="watermark" ${disabled()}>${icon('upload')}Load watermark</button></div>` : ''}
    <div class="photo-toolbar"><div class="toolbar-left"><button class="button primary small" data-action="add-photos" ${disabled()}>${icon('plus')}Add photos</button><span class="toolbar-hint">JPG, PNG &amp; WebP</span></div>
      <div class="toolbar-right">${event.has_watermark ? `<button class="button secondary small" data-action="watermark" ${disabled()}>${icon('upload')}Change watermark</button>` : ''}
      ${event.photos.length ? `<button class="button ghost small" data-action="select-all" ${disabled()}>${event.photos.every(photo => photo.selected) ? 'Deselect all' : 'Select all'}</button>` : ''}</div></div>
    ${event.photos.length ? `<div class="workbench"><div class="gallery-panel"><div class="panel-header"><h3>Event photos</h3><span id="selected-count">${selectedPhotos().length} selected</span></div>
      <div class="gallery-filter"><button class="filter-button ${state.filter === 'all' ? 'active' : ''}" data-filter="all">All photos</button><button class="filter-button ${state.filter === 'favorites' ? 'active' : ''}" data-filter="favorites">Favorites</button></div>
      <div class="photo-grid" id="photo-grid"></div></div><div class="preview-panel" id="preview-panel"></div></div>` : `
    <div class="dropzone" id="dropzone" role="button" tabindex="0" aria-label="Add event photos"><div>${icon('upload')}</div><h3>Your coverage starts here.</h3><p>Drop your event photos here, or choose files from your computer.</p><span class="button secondary">Choose photos</span><p>JPG, PNG and WebP · Up to 60 MB and 50 megapixels each<br>Your originals are copied to RAW without changes.</p></div>`}
    ${event.photos.length ? `<div class="export-bar"><div class="export-options">
      <label>IMAGE SIZE<select id="export-size" ${disabled()}><option value="2048" ${event.long_edge === 2048 ? 'selected' : ''}>2048 px · Facebook</option><option value="3200" ${event.long_edge === 3200 ? 'selected' : ''}>3200 px · Large</option><option value="0" ${event.long_edge === 0 ? 'selected' : ''}>Full crop resolution</option></select></label>
      <label>FORMAT<select id="export-format" ${disabled()}><option value="jpeg" ${event.format === 'jpeg' ? 'selected' : ''}>JPG · Smaller files</option><option value="png" ${event.format === 'png' ? 'selected' : ''}>PNG · Lossless</option></select></label>
      </div><div class="export-buttons"><a class="button secondary ${canDownload() && !state.busy ? '' : 'download-disabled'}" id="download-zip" href="/api/events/${event.id}/download" download aria-disabled="${!canDownload() || state.busy}">${icon('download')}Download ZIP</a>
      <button class="button primary" data-action="export" ${state.busy || !event.has_watermark || !selectedPhotos().length ? 'disabled' : ''}>${icon('check')}Export ${selectedPhotos().length} photo${selectedPhotos().length === 1 ? '' : 's'}</button></div></div>` : ''}
    <div id="job-status" aria-live="polite"></div>`;
}

function renderGallery() {
  if (!$('#photo-grid')) return;
  const photos = state.active.photos.filter(photo => state.filter === 'all' || photo.favorite);
  $('#photo-grid').innerHTML = photos.length ? photos.map(photo => `
    <div class="photo-tile ${photo.id === state.photo ? 'current' : ''} ${photo.selected ? '' : 'excluded'}" data-photo="${photo.id}" tabindex="0" role="button" aria-label="Preview ${escapeHTML(photo.name)}" aria-pressed="${photo.id === state.photo}">
      <img src="${photoURL(photo)}" alt="${escapeHTML(photo.name)}" loading="lazy">
      <div class="tile-controls"><button class="tile-control ${photo.selected ? 'checked' : ''}" data-select="${photo.id}" aria-label="${photo.selected ? 'Exclude' : 'Include'} ${escapeHTML(photo.name)}" aria-pressed="${photo.selected}" ${disabled()}>${photo.selected ? icon('check') : ''}</button>
      <button class="tile-control ${photo.favorite ? 'starred' : ''}" data-favorite="${photo.id}" aria-label="Favorite ${escapeHTML(photo.name)}" aria-pressed="${photo.favorite}" ${disabled()}>${icon('star')}</button></div>
      ${photo.exported_at ? '<span class="exported-dot">EXPORTED</span>' : ''}<div class="tile-name" title="${escapeHTML(photo.name)}">${escapeHTML(photo.name)}</div>
    </div>`).join('') : '<div class="no-matches">Star a photo to add it to your favorites.</div>';
}

function renderPreview() {
  if (!$('#preview-panel')) return;
  const photo = selectedPhoto();
  if (!photo) { $('#preview-panel').innerHTML = '<div class="empty-gallery">Choose a photo to preview it.</div>'; return; }
  $('#preview-panel').innerHTML = `<div class="panel-header"><h3>Publication preview</h3><button class="button ghost small" id="compare-button" data-action="compare-original" aria-pressed="${state.compareOriginal}">${icon('eye')}${state.compareOriginal ? 'Show edited' : 'Compare original'}</button></div>
    <div class="preview-stage"><img id="preview-image" src="${photoURL(photo, state.compareOriginal ? 'before' : 'preview')}?v=${state.revision}" alt="${state.compareOriginal ? 'Original' : 'Publication preview'} of ${escapeHTML(photo.name)}"></div>
    <div class="preview-controls"><div class="transform-toolbar" aria-label="Rotate and flip photo">
      <button class="button secondary small" data-action="rotate-left" ${disabled()}>${icon('rotate-left')}Rotate left</button>
      <button class="button secondary small" data-action="rotate-right" ${disabled()}>${icon('rotate-right')}Rotate right</button>
      <button class="icon-button ${photo.flip_horizontal ? 'toggled' : ''}" data-action="flip-horizontal" aria-label="Flip horizontal" aria-pressed="${photo.flip_horizontal}" ${disabled()}>${icon('flip-h')}</button>
      <button class="icon-button ${photo.flip_vertical ? 'toggled' : ''}" data-action="flip-vertical" aria-label="Flip vertical" aria-pressed="${photo.flip_vertical}" ${disabled()}>${icon('flip-v')}</button>
      <span class="rotation-value">${photo.rotation}°</span></div>
    <div class="editor-controls-grid"><section><div class="control-heading"><strong>Photo framing</strong><button class="button ghost small" data-action="reset-framing" ${disabled()}>Reset</button></div>
    ${slider('zoom','Zoom',photo.zoom,1,3,.01,`${Number(photo.zoom).toFixed(2)}×`)}
    ${slider('x','Horizontal',photo.x,0,1,.01,`${Math.round(photo.x * 100)}%`)}
    ${slider('y','Vertical',photo.y,0,1,.01,`${Math.round(photo.y * 100)}%`)}
    ${slider('opacity','Watermark',state.active.opacity,.1,1,.05,`${Math.round(state.active.opacity * 100)}%`)}
    </section><section><div class="control-heading"><strong>Basic adjustments</strong><button class="button ghost small" data-action="reset-edits" ${disabled()}>Reset edits</button></div>
    ${slider('brightness','Brightness',photo.brightness,.25,2,.05,`${Math.round(photo.brightness * 100)}%`)}
    ${slider('contrast','Contrast',photo.contrast,.25,2,.05,`${Math.round(photo.contrast * 100)}%`)}
    ${slider('saturation','Color',photo.saturation,0,2,.05,`${Math.round(photo.saturation * 100)}%`)}
    ${slider('sharpness','Sharpness',photo.sharpness,0,3,.1,`${Math.round(photo.sharpness * 100)}%`)}
    </section></div><p class="preview-footnote">${state.active.has_watermark ? 'Photos fill your template without stretching. All edits save automatically and affect the photo beneath your watermark.' : 'Photo edits work now. Load your watermark to enable framing and export.'}<br>Source: ${photo.width} × ${photo.height} px. Originals stay unchanged.</p></div>`;
  $('#preview-image').addEventListener('error', () => {
    if ($('#preview-state')) $('#preview-state').textContent = 'Preview unavailable — try reloading the event';
  });
}

function slider(key, label, value, min, max, step, output) {
  const needsWatermark = ['x','y','zoom','opacity'].includes(key);
  return `<label class="slider-row" for="slider-${key}"><span>${label}</span><input id="slider-${key}" data-slider="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" ${state.busy || needsWatermark && !state.active.has_watermark ? 'disabled' : ''}><output id="output-${key}">${output}</output></label>`;
}

function refreshPreviewImage() {
  const photo = selectedPhoto();
  if (photo && $('#preview-image')) $('#preview-image').src = `${photoURL(photo, state.compareOriginal ? 'before' : 'preview')}?v=${state.revision}`;
  if ($('#compare-button')) {
    $('#compare-button').setAttribute('aria-pressed', String(state.compareOriginal));
    $('#compare-button').innerHTML = `${icon('eye')}${state.compareOriginal ? 'Show edited' : 'Compare original'}`;
  }
}

async function transformPhoto(changes) {
  if (!selectedPhoto()) return;
  Object.assign(selectedPhoto(),changes); state.compareOriginal = false;
  queuePhoto(); await flushPhoto(); renderPreview();
}

function queuePhoto() {
  const photo = selectedPhoto();
  if (!photo) return;
  delete photo.exported_at; updateDownload();
  pendingPhoto = {eventId:state.active.id, photo:{...photo}};
  clearTimeout(photoTimer);
  photoTimer = setTimeout(() => flushPhoto().catch(reportError), 240);
}

async function flushPhoto() {
  clearTimeout(photoTimer);
  if (pendingPhoto) {
    const pending = pendingPhoto; pendingPhoto = null;
    const settings = Object.fromEntries(photoSettingKeys.map(key => [key, pending.photo[key]]));
    photoWrites = photoWrites.catch(() => {}).then(async () => {
      const updated = await api(`/events/${pending.eventId}/photos/${pending.photo.id}`, {method:'PATCH',body:JSON.stringify(settings)});
      if (state.active?.id === pending.eventId) {
        const current = state.active.photos.find(photo => photo.id === updated.id);
        // Local slider values may already be ahead of this queued response.
        if (current && !updated.exported_at) delete current.exported_at;
        state.revision++;
        if (state.photo === updated.id) refreshPreviewImage();
        updateDownload();
        renderGallery();
      }
    });
  }
  await photoWrites;
}

function updateDownload() {
  const link = $('#download-zip');
  if (link) { link.classList.toggle('download-disabled', !canDownload() || state.busy); link.setAttribute('aria-disabled', String(!canDownload() || state.busy)); }
}

async function saveExportSettings() {
  const event = state.active;
  const settings = {opacity:event.opacity, long_edge:Number($('#export-size')?.value ?? event.long_edge), format:$('#export-format')?.value ?? event.format};
  const eventId = event.id;
  // Snapshot and enqueue before yielding; edits and consecutive settings changes
  // must not overwrite each other's local state or overtake one another.
  exportSettingsWrites = exportSettingsWrites.catch(() => {}).then(async () => {
    await flushPhoto();
    const updated = await api(`/events/${eventId}/export-settings`, {method:'PUT',body:JSON.stringify(settings)});
    if (state.active?.id !== eventId) return;
    for (const key of ['opacity','long_edge','format']) state.active[key] = updated[key];
    for (const photo of state.active.photos) {
      if (!updated.photos.find(item => item.id === photo.id)?.exported_at) delete photo.exported_at;
    }
    state.revision++; refreshPreviewImage(); renderGallery(); updateDownload();
  });
  await exportSettingsWrites;
}

function captionsHTML() {
  const event = state.active, caption = state.caption;
  return `<fieldset class="caption-workspace" ${state.generatingCaption ? 'disabled' : ''}><div class="caption-layout"><section class="card"><h3>Start with the facts.</h3><p class="card-intro">Your event details shape the caption. Use confirmed information and complete sentences.</p>
    <form id="facts-form" class="facts-form">
      <label>What actually happened?<textarea name="activities" rows="4" maxlength="8000" placeholder="Describe the confirmed activities and key moments.">${escapeHTML(state.facts.activities)}</textarea></label>
      <label>Why was the event held?<textarea name="purpose" rows="3" maxlength="4000" placeholder="State the ministry purpose or need the event addressed.">${escapeHTML(state.facts.purpose)}</textarea></label>
      <label>Verified outcomes <span class="field-note">Optional — include only confirmed results.</span><textarea name="outcomes" rows="3" maxlength="4000" placeholder="Confirmed decisions, outcomes, or follow-up plans.">${escapeHTML(state.facts.outcomes)}</textarea></label>
      <button class="button secondary small" type="submit" ${disabled()}>${icon('check')}Save event facts</button>
    </form><p class="caption-principle">“News first, faith naturally.”</p><p class="field-note">Keep names, statistics, quotations, and outcomes grounded in confirmed facts. AI drafts need your final editorial review.</p></section>
    <section class="card"><div class="caption-title"><h3>AI caption maker</h3><span class="ai-badge">${icon('sparkles')}DMM VOICE</span></div><p class="card-intro">Turn your confirmed event facts into a professional, mission-centered caption. Review the wording before publication.</p>
      <div class="caption-mode" aria-label="Caption generation method"><button data-mode="ai" class="${caption.mode === 'ai' ? 'active' : ''}" aria-pressed="${caption.mode === 'ai'}" ${disabled()}>${icon('sparkles')}AI writer</button><button data-mode="template" class="${caption.mode === 'template' ? 'active' : ''}" aria-pressed="${caption.mode === 'template'}" ${disabled()}>Offline template</button></div>
      ${caption.mode === 'ai' ? `<div class="ai-connection-strip"><span>${isLocalAI() ? 'Local AI · No API key' : state.ai?.configured ? 'OpenAI API key configured' : 'Choose local AI or connect OpenAI'}<small>${escapeHTML(state.ai?.model || 'gpt-4.1-mini')} · ${isLocalAI() ? 'Ollama must be running with this model installed' : state.ai?.configured ? 'Access is checked when generating' : 'Local AI works without an API key'}</small></span><button class="button secondary small" data-action="ai-settings" ${disabled()}>${state.ai?.configured ? 'Settings' : 'Connect'}</button></div>` : '<p class="field-note">Offline mode arranges your entered facts without calling an AI service.</p>'}
      <div class="caption-style" aria-label="Caption type"><button data-style="album" class="${caption.style === 'album' ? 'active' : ''}" aria-pressed="${caption.style === 'album'}">Album caption</button><button data-style="photo" class="${caption.style === 'photo' ? 'active' : ''}" aria-pressed="${caption.style === 'photo'}">Single photo</button></div>
      ${caption.style === 'photo' ? `<label>Describe this photo<textarea id="photo-description" maxlength="8000" placeholder="Who or what is shown? Use confirmed names and actions.">${escapeHTML(caption.photo_caption)}</textarea></label>` : ''}
      ${caption.mode === 'ai' ? `<div class="ai-writing-options"><label>Caption length<select id="caption-length" ${disabled()}><option value="short" ${caption.length === 'short' ? 'selected' : ''}>Short · a quick highlight</option><option value="standard" ${caption.length === 'standard' ? 'selected' : ''}>Standard · event coverage</option><option value="long" ${caption.length === 'long' ? 'selected' : ''}>Detailed · a fuller story</option></select></label>
      <label>Editorial direction <span class="field-note">Optional — guide the emphasis or tone, keeping the facts unchanged.</span><textarea id="caption-instructions" maxlength="1500" rows="2" placeholder="e.g. Emphasize youth participation and keep the tone warm." ${disabled()}>${escapeHTML(caption.instructions)}</textarea></label></div>` : ''}
      <div class="caption-options"><label class="check-label"><input type="checkbox" id="include-footer" ${caption.include_footer ? 'checked' : ''}>DMM footer &amp; hashtags</label><label class="check-label"><input type="checkbox" id="include-credit" ${caption.include_credit ? 'checked' : ''}>Photographer credit</label></div>
      <button class="button primary" data-action="generate-caption" ${state.busy || caption.mode === 'ai' && !state.ai?.configured ? 'disabled' : ''}>${icon(caption.mode === 'ai' ? 'sparkles' : 'text')}${state.generatingCaption ? 'Writing your caption…' : caption.mode === 'ai' ? 'Generate AI caption' : 'Create draft'}</button>
      ${caption.mode === 'ai' ? `<p class="ai-send-note">${isLocalAI() ? 'Generation runs through Ollama on this computer. No API key or cloud upload. The first caption can take longer while the model loads.' : 'Generating sends the saved event text and writing preferences to OpenAI. No photos are uploaded. API usage charges apply.'}</p>` : ''}
      ${caption.error ? `<div class="caption-warning" role="alert"><strong>Caption generation could not finish.</strong>${escapeHTML(caption.error)} Your existing draft is preserved.</div>` : ''}
      <div class="caption-draft"><div class="caption-draft-header"><strong>Your caption</strong><span class="draft-badge">EDITORIAL REVIEW REQUIRED</span></div>
      <textarea id="caption-text" aria-label="Caption draft" maxlength="30000" placeholder="Your draft will appear here. You can also write or paste your own caption.">${escapeHTML(caption.text)}</textarea>
      <div class="caption-actions"><button class="button secondary small" data-action="copy-caption">${icon('copy')}Copy text</button><button class="button primary small" data-action="save-caption">${icon('check')}Save caption</button><span class="caption-saved" id="caption-save-state">${caption.dirty ? 'Unsaved changes' : caption.text ? 'Saved to CAPTIONS' : ''}</span></div>
      <div id="caption-notice">${captionNotice()}</div></div>
    </section></div></fieldset>`;
}

function captionNotice() {
  const caption = state.caption;
  const missing = caption.missing.length ? `<strong>Details still needing confirmation</strong>${caption.missing.map(escapeHTML).join(' · ')}<br>` : '';
  const stale = caption.stale ? '<strong>Event facts changed.</strong>Create a new draft or update this caption to match the saved facts.<br>' : '';
  return `<div class="caption-warning">${stale}${missing}${caption.generatedMode === 'ai' ? 'AI wording can contain mistakes. Check every name, number, quotation, and claim against your event facts.' : 'Confirm every detail against your event facts.'} Nothing is published automatically.</div>`;
}

async function showAISettings() {
  state.ai = await api('/ai/settings');
  $('#ai-form').reset(); $('#ai-key').value = '';
  $('#ai-provider').value = isLocalAI() ? 'ollama' : 'openai';
  renderAIProvider(state.ai);
  $('#ai-dialog').showModal();
}

function renderAIProvider(settings) {
  const local = settings.provider === 'Ollama';
  $('#ai-model').value = settings.model;
  $('#ai-key-field').hidden = local; $('#local-ai-setup').hidden = !local;
  $('#ai-disconnect').hidden = local || settings.source !== 'session';
  $('#ai-key').placeholder = settings.configured ? 'Leave blank to keep the configured key' : 'Paste your OpenAI API key';
  $('#ai-model-note').textContent = local ? 'Use a downloaded local model. qwen2.5:3b is a practical starting point for 16 GB RAM.' : 'Use an available OpenAI model supporting the Responses API and structured output.';
  $('#ai-usage-note').textContent = local ? 'Local AI needs no API account or per-caption payment. Model downloads need internet; generation uses your PC’s hardware.' : 'OpenAI captions require internet and API billing. A ChatGPT subscription does not include API usage.';
  $('#ai-status-note').textContent = local ? 'Save your selection, and use Check local model to verify Ollama and the downloaded model.' : settings.configured ? `Key configured from ${settings.source === 'environment' ? 'the launch environment' : 'this session'}. Generate a caption to check access.` : 'No OpenAI key is configured. Choose Local AI above to work without one.';
}

async function changeAIProvider() {
  const provider = $('#ai-provider').value;
  $('#ai-key').value = '';
  const settings = await api(`/ai/settings?provider=${provider}`);
  if ($('#ai-provider').value === provider) renderAIProvider(settings);
}

async function checkLocalAI() {
  const button = $('[data-action="check-ollama"]'); button.disabled = true;
  const model = $('#ai-model').value.trim();
  $('#ai-status-note').textContent = 'Checking Ollama and the selected model…';
  try {
    const status = await api(`/ai/local-status?model=${encodeURIComponent(model)}`);
    if ($('#ai-provider').value === 'ollama' && $('#ai-model').value.trim() === model) $('#ai-status-note').textContent = status.detail;
  } finally { button.disabled = false; }
}

async function submitAI(event) {
  event.preventDefault(); const button = $('#ai-submit'); button.disabled = true;
  const payload = {provider:$('#ai-provider').value, model:$('#ai-model').value.trim()};
  if (payload.provider === 'openai' && $('#ai-key').value.trim()) payload.api_key = $('#ai-key').value.trim();
  $('#ai-key').value = '';
  try {
    state.ai = await api('/ai/settings',{method:'PUT',body:JSON.stringify(payload)});
    $('#ai-dialog').close();
    if (state.active && state.tab === 'captions') renderWorkspace();
    toast(isLocalAI() ? 'Local AI selected. Keep Ollama running with your model downloaded.' : state.ai.configured ? 'AI settings saved. Generate a caption to check access.' : 'Model saved. Add an API key or choose Local AI.');
  } finally { button.disabled = false; }
}

async function disconnectAI() {
  state.ai = await api('/ai/session',{method:'DELETE'});
  $('#ai-dialog').close();
  if (state.active && state.tab === 'captions') renderWorkspace();
  toast(state.ai.configured ? 'Session key forgotten. The launch environment still supplies a key.' : 'Session key forgotten. Offline captions remain available.');
}

function showEventDialog(editing = false) {
  if (state.busy) return;
  state.editing = editing;
  const form = $('#event-form'); form.reset();
  if (editing) {
    for (const input of $$('input[name]', form)) input.value = state.active[input.name] || '';
  } else {
    const today = new Date();
    form.elements.date.value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
  }
  $('#event-dialog-title').textContent = editing ? 'Edit event details' : 'Create an event';
  $('#event-submit').innerHTML = `${editing ? 'Save details' : 'Create event'}${icon('arrow')}`;
  $('#event-dialog').showModal();
}

async function submitEvent(event) {
  event.preventDefault();
  const button = $('#event-submit'); button.disabled = true;
  try {
    const details = Object.fromEntries(new FormData(event.target));
    if (state.editing) {
      const {activities,purpose,outcomes} = state.active;
      state.active = await api(eventURL(), {method:'PUT',body:JSON.stringify({...details,activities,purpose,outcomes})});
      state.caption.stale = Boolean(state.caption.text);
      $('#event-dialog').close(); renderWorkspace(); await refreshEvents(); toast('Event details saved.');
    } else {
      if (!leaveCaption()) return;
      const created = await api('/events', {method:'POST',body:JSON.stringify(details)});
      if (state.caption) state.caption.dirty = false;
      state.factsDirty = false;
      $('#event-dialog').close(); await refreshEvents(); await openEvent(created.id);
      toast('Event created. Your RAW, EDITED, and CAPTIONS folders are ready.');
    }
  } finally { button.disabled = false; }
}

async function importFiles(files) {
  if (!files.length || state.busy || !state.active) return;
  await flushPhoto(); state.busy = true; renderWorkspace();
  let accepted = 0; const rejected = [];
  try {
    for (let offset=0; offset<files.length; offset+=20) {
      const body = new FormData();
      for (const file of files.slice(offset, offset+20)) body.append('files',file);
      toast(`Copying photos ${offset+1}–${Math.min(offset+20, files.length)} of ${files.length}…`);
      const result = await api(eventURL('/photos'), {method:'POST',body});
      accepted += result.accepted.length; rejected.push(...result.rejected); state.active = result.event;
    }
    if (!state.photo) state.photo = state.active.photos[0]?.id;
    toast(`${accepted} photo${accepted === 1 ? '' : 's'} added. Originals are preserved in RAW.`);
    if (rejected.length) showInfo('Some files could not be imported', `<p>${accepted} imported; ${rejected.length} skipped.</p><ul>${rejected.map(file => `<li><strong>${escapeHTML(file.name)}</strong>: ${escapeHTML(file.reason)}</li>`).join('')}</ul>`);
  } finally {
    state.busy = false; renderWorkspace(); await refreshEvents();
  }
}

async function uploadWatermark(file) {
  if (!file || state.busy) return;
  await flushPhoto(); const body = new FormData(); body.append('file',file);
  state.busy = true; renderWorkspace();
  try {
    const result = await api(eventURL('/watermark'), {method:'POST',body});
    state.active = result.event; state.revision++;
    toast(`DMM watermark loaded (${result.width} × ${result.height}). It will also be used for new events.`);
  } finally { state.busy = false; renderWorkspace(); }
}

function renderJob() {
  if (!$('#job-status') || !state.job) return;
  const job = state.job;
  if (job.status === 'running') {
    $('#job-status').innerHTML = `<div class="export-progress"><div class="progress-heading"><span>Preparing your photos…</span><span>${job.done} / ${job.total}</span></div><div class="progress-track"><div id="progress-fill"></div></div></div>`;
    $('#progress-fill').style.width = `${Math.round(job.done/job.total*100)}%`;
  } else {
    $('#job-status').innerHTML = `<p class="export-result ${job.errors.length ? 'error-result' : ''}">${job.succeeded} photo${job.succeeded === 1 ? '' : 's'} exported to EDITED.${job.errors.length ? ` ${job.errors.length} failed. Re-export to retry.` : ' Your originals are unchanged.'}</p>`;
  }
}

async function exportPhotos() {
  if (state.busy) return;
  await flushPhoto(); await exportSettingsWrites;
  state.busy = true;
  try {
    state.job = await api(eventURL('/export'), {method:'POST'}); renderWorkspace();
    while (state.job.status === 'running') {
      await new Promise(resolve => setTimeout(resolve, 450));
      state.job = await api(`/jobs/${state.job.id}`); renderJob();
    }
    state.active = await api(eventURL());
    if (state.job.errors.length) showInfo('Export report', `<p>${state.job.succeeded} photos saved; ${state.job.errors.length} failed.</p><ul>${state.job.errors.map(error => `<li>${escapeHTML(error.name)}: ${escapeHTML(error.reason)}</li>`).join('')}</ul>`);
    else toast('Your watermarked photos are ready in EDITED.');
  } finally { state.busy = false; renderWorkspace(); await refreshEvents(); }
}

async function togglePhoto(id, key) {
  if (state.busy) return;
  const eventId = state.active.id;
  const photo = state.active.photos.find(item => item.id === id);
  await flushPhoto();
  if (state.active?.id !== eventId) return;
  const settings = {[key]:!photo[key]};
  const previous = photo[key]; photo[key] = settings[key];
  photoWrites = photoWrites.catch(() => {}).then(() => api(`/events/${eventId}/photos/${id}`, {method:'PATCH',body:JSON.stringify(settings)}));
  try { await photoWrites; }
  catch (error) { if (photo[key] === settings[key]) photo[key] = previous; throw error; }
  // A full server snapshot could predate a slider edit made during this PATCH.
  if (state.active?.id === eventId) renderWorkspace();
}

async function selectAll() {
  await flushPhoto();
  const value = !state.active.photos.every(photo => photo.selected);
  state.busy = true; renderWorkspace();
  try {
    for (const photo of state.active.photos) {
      await api(eventURL(`/photos/${photo.id}`), {method:'PATCH',body:JSON.stringify({selected:value})});
      photo.selected = value;
    }
  } finally { state.busy = false; renderWorkspace(); }
}

async function saveFacts(event) {
  event.preventDefault();
  const form = event.target, button = $('button[type="submit"]',form); button.disabled = true;
  const eventId = state.active.id;
  try {
    const fields = Object.fromEntries(new FormData(form));
    const {name,date,venue,organizer,theme,photographer} = state.active;
    const updated = await api(`/events/${eventId}`, {method:'PUT',body:JSON.stringify({name,date,venue,organizer,theme,photographer,...fields})});
    if (state.active?.id !== eventId) return;
    state.active = updated;
    state.facts = {...fields}; state.factsDirty = false;
    state.caption.stale = Boolean(state.caption.text);
    $('#caption-notice').innerHTML = captionNotice(); toast('Confirmed event facts saved.');
  } finally { button.disabled = false; }
}

async function generateCaption() {
  if (state.busy) return;
  if (state.caption.mode === 'ai' && !state.ai?.configured) return showAISettings();
  if (state.caption.text && !confirm('Replace the current caption draft with a new draft from your event facts?')) return;
  // Lock the workspace before the first await to avoid duplicate paid requests
  // or switching events between saving facts and generating the caption.
  const eventId = state.active.id;
  const fields = Object.fromEntries(new FormData($('#facts-form')));
  const {name,date,venue,organizer,theme,photographer} = state.active;
  const {mode,style,photo_caption,include_footer,include_credit,length,instructions} = state.caption;
  state.busy = true; state.generatingCaption = true; state.caption.error = ''; renderWorkspace();
  try {
    state.active = await api(`/events/${eventId}`, {method:'PUT',body:JSON.stringify({name,date,venue,organizer,theme,photographer,...fields})});
    state.facts = {...fields}; state.factsDirty = false;
    const result = await api(`/events/${eventId}/captions/generate`, {method:'POST',body:JSON.stringify({mode,style,photo_caption,include_footer,include_credit,length,instructions})});
    Object.assign(state.caption,{text:result.text, missing:result.missing, dirty:true, stale:false, generatedMode:result.mode});
    toast(mode === 'ai' ? 'AI caption created. Review its facts and wording before posting.' : 'Offline draft created from your event facts.');
  } catch (error) {
    state.caption.error = error.message;
    toast(error.message,true);
  } finally { state.busy = false; state.generatingCaption = false; renderWorkspace(); }
}

async function saveCaption() {
  if (!state.caption.text.trim()) { toast('Write or create a caption first.',true); return; }
  await api(eventURL('/captions'), {method:'PUT',body:JSON.stringify({text:state.caption.text})});
  state.caption.saved = state.caption.text; state.caption.dirty = false;
  $('#caption-save-state').textContent = 'Saved to CAPTIONS'; toast('Caption saved to CAPTIONS/caption.txt.');
}

async function copyCaption() {
  if (!state.caption.text.trim()) { toast('Write or create a caption first.',true); return; }
  await navigator.clipboard.writeText(state.caption.text); toast('Caption copied.');
}

function showInfo(title, content) { $('#info-title').textContent=title; $('#info-content').innerHTML=content; if (!$('#info-dialog').open) $('#info-dialog').showModal(); }
function showHelp() {
  showInfo('Your local workspace', `<p>Event projects are saved here:</p><code>${escapeHTML(state.settings.data_dir)}</code>
    <p>Each event has these folders:</p><ul><li><strong>RAW</strong> — untouched copies of imported JPG, PNG, and WebP photos. Camera RAW and HEIC files are not supported yet.</li><li><strong>EDITED</strong> — your exported, watermarked photos.</li><li><strong>CAPTIONS</strong> — the caption you saved as a text file.</li></ul>
    <p>Load your original transparent PNG watermark inside an event. It is remembered for new events; existing events keep their own template.</p>
    <p>All photo editing and watermarking happen here. Local AI uses Ollama on the computer running this app. OpenAI mode sends event text to your API account. The offline template also remains available. API keys stay in memory until the app closes.</p><p>Back up the entire workspace folder to preserve your events and settings.</p>`);
}

function bindDropzone() {
  const zone = $('#dropzone'); if (!zone) return;
  zone.addEventListener('click',()=>{if(!state.busy) $('#photo-input').click();});
  zone.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();if(!state.busy)$('#photo-input').click();}});
  zone.addEventListener('dragover',event=>{event.preventDefault();zone.classList.add('drag-over');});
  zone.addEventListener('dragleave',()=>zone.classList.remove('drag-over'));
  zone.addEventListener('drop',event=>{event.preventDefault();zone.classList.remove('drag-over');importFiles([...event.dataTransfer.files]).catch(reportError);});
}

async function action(name) {
  const actions = {
    library, 'new-event':()=>showEventDialog(), 'edit-event':()=>showEventDialog(true), help:showHelp,
    'ai-settings':showAISettings, 'disconnect-ai':disconnectAI, 'check-ollama':checkLocalAI,
    'add-photos':()=>$('#photo-input').click(), watermark:()=>$('#watermark-input').click(),
    export:exportPhotos, 'select-all':selectAll, 'generate-caption':generateCaption,
    'save-caption':saveCaption, 'copy-caption':copyCaption,
    'open-folder':async()=>{const result=await api(eventURL('/open-folder'),{method:'POST'});if(!result.opened)showInfo('Event folder',`<p>Your event is saved at:</p><code>${escapeHTML(result.path)}</code>`);},
    'reset-framing':()=>transformPhoto({x:.5,y:.5,zoom:1}),
    'rotate-left':()=>transformPhoto({rotation:(selectedPhoto().rotation+270)%360}),
    'rotate-right':()=>transformPhoto({rotation:(selectedPhoto().rotation+90)%360}),
    'flip-horizontal':()=>transformPhoto({flip_horizontal:!selectedPhoto().flip_horizontal}),
    'flip-vertical':()=>transformPhoto({flip_vertical:!selectedPhoto().flip_vertical}),
    'reset-edits':()=>transformPhoto({...editDefaults}),
    'compare-original':()=>{state.compareOriginal=!state.compareOriginal;refreshPreviewImage();}
  };
  if (state.busy && !['help','open-folder','copy-caption','save-caption'].includes(name)) return;
  await actions[name]?.();
}

document.addEventListener('click',event=>{
  const target=event.target.closest('button, a, [data-photo]'); if(!target)return;
  (async()=>{
    if(target.dataset.close){$(`#${target.dataset.close}`).close();return;}
    if(target.dataset.action){event.preventDefault();return action(target.dataset.action);}
    if(target.dataset.event)return openEvent(target.dataset.event);
    if(target.dataset.select)return togglePhoto(target.dataset.select,'selected');
    if(target.dataset.favorite)return togglePhoto(target.dataset.favorite,'favorite');
    if(target.dataset.tab){if(state.generatingCaption)return;await flushPhoto();state.tab=target.dataset.tab;renderWorkspace();return;}
    if(target.dataset.filter){state.filter=target.dataset.filter;renderWorkspace();return;}
    if(target.dataset.photo){await flushPhoto();state.photo=target.dataset.photo;state.compareOriginal=false;renderGallery();renderPreview();return;}
    if(target.dataset.style){state.caption.style=target.dataset.style;renderWorkspace();}
    if(target.dataset.mode){if(state.busy)return;state.caption.mode=target.dataset.mode;renderWorkspace();}
  })().catch(reportError);
});

document.addEventListener('keydown',event=>{
  if((event.key==='Enter'||event.key===' ') && event.target.matches('[data-photo]')){event.preventDefault();event.target.click();}
});

document.addEventListener('input',event=>{
  const target=event.target;
  if(target.id==='event-search')renderEventCards(target.value);
  if(target.id==='caption-text'){state.caption.text=target.value;state.caption.dirty=target.value!==state.caption.saved;$('#caption-save-state').textContent=state.caption.dirty?'Unsaved changes':'Saved to CAPTIONS';}
  if(target.id==='photo-description')state.caption.photo_caption=target.value;
  if(target.id==='caption-instructions')state.caption.instructions=target.value;
  if(target.closest('#facts-form') && target.name){state.facts[target.name]=target.value;state.factsDirty=Object.keys(state.facts).some(key=>state.facts[key]!==state.active[key]);}
  if(target.dataset.slider){
    const key=target.dataset.slider,value=Number(target.value);
    $(`#output-${key}`).textContent=key==='zoom'?`${value.toFixed(2)}×`:`${Math.round(value*100)}%`;
    if(key==='opacity')return;
    state.compareOriginal=false;selectedPhoto()[key]=value;queuePhoto();
  }
});

document.addEventListener('change',event=>{
  const target=event.target;
  if(target.id==='ai-provider')changeAIProvider().catch(reportError);
  if(target.id==='include-footer')state.caption.include_footer=target.checked;
  if(target.id==='include-credit')state.caption.include_credit=target.checked;
  if(target.id==='caption-length')state.caption.length=target.value;
  if(target.id==='export-size'||target.id==='export-format')saveExportSettings().catch(reportError);
  if(target.dataset.slider==='opacity'){state.active.opacity=Number(target.value);saveExportSettings().catch(reportError);}
});

$('#event-form').addEventListener('submit',event=>submitEvent(event).catch(reportError));
$('#ai-form').addEventListener('submit',event=>submitAI(event).catch(reportError));
$('#ai-dialog').addEventListener('close',()=>{$('#ai-key').value='';});
document.addEventListener('submit',event=>{if(event.target.id==='facts-form')saveFacts(event).catch(reportError);});
$('#photo-input').addEventListener('change',event=>{const files=[...event.target.files];event.target.value='';importFiles(files).catch(reportError);});
$('#watermark-input').addEventListener('change',event=>{const file=event.target.files[0];event.target.value='';uploadWatermark(file).catch(reportError);});
window.addEventListener('beforeunload',event=>{if(state.busy||state.caption?.dirty||state.factsDirty||pendingPhoto){event.preventDefault();event.returnValue='';}});
document.addEventListener('dragover',event=>{if(event.dataTransfer.types.includes('Files'))event.preventDefault();});
document.addEventListener('drop',event=>event.preventDefault());

(async()=>{
  const [settings,events,ai]=await Promise.all([api('/settings'),api('/events'),api('/ai/settings')]);
  state.settings=settings;state.events=events;state.ai=ai;renderLibrary();
})().catch(error=>{
  $('#main').innerHTML=`<div class="empty-gallery"><h2>We couldn’t open your workspace.</h2><p>${escapeHTML(error.message)}</p><p>Check that Photo Desk is running, then refresh this page.</p></div>`;
  reportError(error);
});
