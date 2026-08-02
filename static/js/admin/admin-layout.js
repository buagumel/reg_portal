(function() {
    const hamburger = document.getElementById('adminHamburger');
    const sidebar = document.getElementById('adminSidebar');
    const profileBtn = document.getElementById('adminProfileBtn');
    const profileDropdown = document.getElementById('adminProfileDropdown');
    const themeBtn = document.getElementById('adminThemeBtn');

    if (hamburger && sidebar) {
        hamburger.addEventListener('click', () => sidebar.classList.toggle('mobile-open'));
    }

    if (profileBtn && profileDropdown) {
        profileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            profileDropdown.classList.toggle('open');
        });
        document.addEventListener('click', () => profileDropdown.classList.remove('open'));
    }

    if (themeBtn) {
        const stored = localStorage.getItem('adminTheme');
        if (stored === 'dark') {
            document.documentElement.setAttribute('data-admin-theme', 'dark');
        }
        themeBtn.addEventListener('click', () => {
            const isDark = document.documentElement.getAttribute('data-admin-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-admin-theme');
                localStorage.setItem('adminTheme', 'light');
            } else {
                document.documentElement.setAttribute('data-admin-theme', 'dark');
                localStorage.setItem('adminTheme', 'dark');
            }
        });
    }
})();
