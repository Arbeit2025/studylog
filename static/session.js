window.addEventListener('pageshow', function (event) {
    if (event.persisted) window.location.reload();
});

document.addEventListener('submit', function (event) {
    if (event.target.matches('form[data-confirm-delete]') && !window.confirm('このログを削除しますか？')) {
        event.preventDefault();
    }
});
