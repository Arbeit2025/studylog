(function () {
    'use strict';
    var storageKey = 'studylog-theme';
    var root = document.documentElement;
    var media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    var preference = 'system';

    function valid(value) {
        return value === 'light' || value === 'dark' ? value : 'system';
    }
    function apply() {
        root.dataset.theme = preference === 'system' ? (media && media.matches ? 'dark' : 'light') : preference;
        root.dataset.themePreference = preference;
        document.querySelectorAll('[data-studylog-theme]').forEach(function (control) {
            control.value = preference;
        });
    }
    try { preference = valid(window.localStorage.getItem(storageKey)); } catch (error) {}
    apply();

    function bind() {
        document.querySelectorAll('[data-studylog-theme]').forEach(function (control) {
            control.addEventListener('change', function () {
                preference = valid(control.value);
                try { window.localStorage.setItem(storageKey, preference); } catch (error) {}
                apply();
            });
        });
        apply();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
    else bind();
    if (media) {
        if (media.addEventListener) media.addEventListener('change', apply);
        else if (media.addListener) media.addListener(apply);
    }
    window.addEventListener('storage', function (event) {
        if (event.key === storageKey || event.key === null) {
            preference = valid(event.newValue);
            apply();
        }
    });
    window.addEventListener('pageshow', apply);
}());
