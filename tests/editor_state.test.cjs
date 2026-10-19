'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../dmm/static/app.js'), 'utf8');
const startup = source.lastIndexOf('\n(async()=>{');
assert.ok(startup >= 0, 'Find the application startup so tests can supply their own event.');

function editor(initial = {}) {
  const element = () => ({
    addEventListener() {}, classList: {toggle() {}}, setAttribute() {},
  });
  const elements = new Map();
  const getElement = selector => {
    if (!elements.has(selector)) elements.set(selector, element());
    return elements.get(selector);
  };
  const context = vm.createContext({
    console,
    document: {querySelector: getElement, querySelectorAll: () => [], addEventListener() {}},
    window: {addEventListener() {}},
    // Autosave is flushed explicitly so network ordering stays deterministic.
    setTimeout() { return 1; }, clearTimeout() {},
  });
  vm.runInContext(source.slice(0, startup), context, {filename: 'app.js'});
  const run = script => vm.runInContext(script, context);
  const server = {
    id: 'event', opacity: 1, long_edge: 2048, format: 'jpeg',
    photos: [{id: 'photo', x: .5, y: .5, zoom: 1, selected: true, favorite: false,
      rotation: 0, flip_horizontal: false, flip_vertical: false,
      brightness: 1, contrast: 1, saturation: 1, sharpness: 1, ...initial}],
  };
  context.initialEvent = structuredClone(server);
  run(`
    state.active = initialEvent; state.photo = 'photo';
    refreshPreviewImage = () => {}; updateDownload = () => {};
    renderGallery = () => {}; renderWorkspace = () => {};
  `);
  getElement('#export-size').value = '2048';
  getElement('#export-format').value = 'png';

  const requests = [];
  context.mockAPI = (url, options) => new Promise(resolve => {
    const body = JSON.parse(options.body);
    let snapshot;
    if (url === '/events/event/photos/photo') {
      Object.assign(server.photos[0], body);
      snapshot = structuredClone(server.photos[0]);
    } else if (url === '/events/event/export-settings') {
      Object.assign(server, body);
      snapshot = structuredClone(server);
    } else {
      throw new Error(`Unexpected API request: ${url}`);
    }
    // Capture the server's response before subsequent local edits, then delay delivery.
    requests.push({url, body, reply: () => resolve(snapshot)});
  });
  run('api = mockAPI;');

  async function request(index) {
    for (let attempt = 0; attempt < 20 && requests.length <= index; attempt++) {
      await new Promise(setImmediate);
    }
    assert.ok(requests[index], `Expected API request ${index + 1}`);
    return requests[index];
  }
  function adjustBrightness() {
    run('selectedPhoto().brightness = 1.5; queuePhoto();');
  }
  return {run, request, adjustBrightness, server};
}

for (const [key, initial, expected] of [
  ['favorite', {selected: true, favorite: false}, {selected: true, favorite: true}],
  ['selected', {selected: true, favorite: true}, {selected: false, favorite: true}],
]) {
  test(`delayed ${key} response preserves newer photo edits and both toggles`, async () => {
    const app = editor(initial);
    const toggle = app.run(`togglePhoto('photo', '${key}')`);
    const toggleRequest = await app.request(0);
    app.adjustBrightness();
    toggleRequest.reply();
    await toggle;

    const autosave = app.run('flushPhoto()');
    const editRequest = await app.request(1);
    editRequest.reply();
    await autosave;

    assert.equal(app.run('selectedPhoto().brightness'), 1.5, 'newer edit remains visible');
    assert.equal(app.server.photos[0].brightness, 1.5, 'newer edit remains saved');
    for (const field of ['selected', 'favorite']) {
      assert.equal(app.run(`selectedPhoto().${field}`), expected[field], `${field} remains visible`);
      assert.equal(app.server.photos[0][field], expected[field], `${field} remains saved`);
    }
  });
}

test('delayed export-settings response preserves newer visible and saved photo edits', async () => {
  const app = editor({favorite: true});
  const settings = app.run('saveExportSettings()');
  const settingsRequest = await app.request(0);
  app.adjustBrightness();
  settingsRequest.reply();
  await settings;

  const autosave = app.run('flushPhoto()');
  const editRequest = await app.request(1);
  editRequest.reply();
  await autosave;

  assert.equal(app.run('selectedPhoto().brightness'), 1.5, 'settings response cannot reset the slider');
  assert.equal(app.server.photos[0].brightness, 1.5, 'the preview and export use the displayed edit');
  assert.equal(app.run('state.active.format'), 'png', 'export format still updates');
  assert.equal(app.server.format, 'png');
  assert.equal(app.run('selectedPhoto().favorite'), true);
  assert.equal(app.run('selectedPhoto().selected'), true);
  assert.equal(app.server.photos[0].favorite, true);
  assert.equal(app.server.photos[0].selected, true);
});
