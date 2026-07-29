export function showToast(message, isError = false) {
    const toast = document.getElementById('toastMsg');
    if (!toast) return;
    toast.textContent = message;
    toast.style.backgroundColor = isError ? '#b13e3e' : '#1f4d6e';
    toast.style.display = 'block';
    clearTimeout(showToast._timer);
    showToast._timer = setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}
