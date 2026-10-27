// Run the actual browser scripts with controlled DOM, storage and OS events.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const theme = fs.readFileSync(path.join(__dirname, '../static/theme.js'), 'utf8');
const session = fs.readFileSync(path.join(__dirname, '../static/session.js'), 'utf8');

function environment({saved = null, dark = false, blocked = false, loading = false} = {}) {
    const callbacks = {};
    const control = {value: '', addEventListener(name, callback) {callbacks['control:' + name] = callback;}};
    const root = {dataset: {}};
    const media = {matches: dark, addEventListener(name, callback) {callbacks['media:' + name] = callback;}};
    const document = {
        documentElement: root, readyState: loading ? 'loading' : 'complete',
        querySelectorAll() {return [control];},
        addEventListener(name, callback) {callbacks['document:' + name] = callback;},
    };
    let stored = saved;
    let reloads = 0;
    const window = {
        matchMedia() {return media;},
        localStorage: {
            getItem() {if (blocked) throw Error('storage unavailable'); return stored;},
            setItem(key, value) {assert.equal(key, 'studylog-theme'); if (blocked) throw Error('quota'); stored = value;},
        },
        addEventListener(name, callback) {callbacks['window:' + name] = callback;},
        location: {reload() {reloads++;}},
        confirm() {return false;},
    };
    const context = vm.createContext({window, document});
    vm.runInContext(theme, context);
    return {root, control, media, callbacks, window, context, stored: () => stored, reloads: () => reloads};
}

for (let run = 1; run <= 3; run++) {
    let env = environment();
    assert.equal(env.root.dataset.theme, 'light');
    env = environment({dark: true});
    assert.equal(env.root.dataset.theme, 'dark');
    assert.equal(env.root.dataset.themePreference, 'system');
    for (const preference of ['light', 'dark', 'system']) {
        env.control.value = preference;
        env.callbacks['control:change']();
        assert.equal(env.stored(), preference);
        assert.equal(env.root.dataset.theme, preference === 'system' ? 'dark' : preference);
        assert.equal(environment({saved: env.stored(), dark: true}).control.value, preference);
    }
    env.media.matches = false;
    env.callbacks['media:change']();
    assert.equal(env.root.dataset.theme, 'light');
    env.control.value = 'dark';
    env.callbacks['control:change']();
    env.callbacks['media:change']();
    assert.equal(env.root.dataset.theme, 'dark');
    env.callbacks['window:storage']({key: 'studylog-theme', newValue: 'light'});
    assert.equal(env.control.value, 'light');
    env.callbacks['window:storage']({key: 'studylog-theme', newValue: 'dark'});
    assert.equal(env.root.dataset.theme, 'dark');
    env.callbacks['window:storage']({key: null, newValue: null});
    assert.equal(env.control.value, 'system');
    env.callbacks['window:storage']({key: 'unrelated', newValue: 'dark'});
    assert.equal(env.control.value, 'system');
    assert.equal(environment({saved: 'corrupt', dark: true}).control.value, 'system');
    env = environment({blocked: true});
    env.control.value = 'dark';
    env.callbacks['control:change']();
    assert.equal(env.root.dataset.theme, 'dark');
    env = environment({saved: 'dark', loading: true});
    assert.equal(env.root.dataset.theme, 'dark'); // applies before DOMContentLoaded
    env.callbacks['document:DOMContentLoaded']();
    assert.equal(env.control.value, 'dark');

    vm.runInContext(session, env.context);
    env.callbacks['window:pageshow']({persisted: true});
    assert.equal(env.reloads(), 1);
    let cancelled = 0;
    const event = {target: {matches: () => true}, preventDefault() {cancelled++;}};
    env.callbacks['document:submit'](event);
    assert.equal(cancelled, 1);
    env.window.confirm = () => true;
    env.callbacks['document:submit'](event);
    assert.equal(cancelled, 1);
    console.log(`Theme/session JavaScript ${run}/3: PASS`);
}
