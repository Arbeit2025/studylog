const adminLogin = document.querySelector('[data-admin-login-url]');
if (adminLogin) {
    // Clear the selector on history restoration; selecting it never grants a role.
    window.addEventListener('pageshow', function () { adminLogin.checked = false; });
    adminLogin.addEventListener('change', function () {
        if (adminLogin.checked) window.location.assign(adminLogin.dataset.adminLoginUrl);
    });
}
