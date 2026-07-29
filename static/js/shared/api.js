function getCsrfToken() {
    const el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

export async function postJson(url, body) {
    let response;
    try {
        response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(body)
        });
    } catch (err) {
        return { success: false, message: 'Network error. Please check your connection and try again.' };
    }
    try {
        return await response.json();
    } catch (err) {
        return { success: false, message: 'Unexpected server response.' };
    }
}

export async function postForm(url, formData) {
    let response;
    try {
        response = await fetch(url, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
            body: formData
        });
    } catch (err) {
        return { success: false, message: 'Network error. Please check your connection and try again.' };
    }
    try {
        return await response.json();
    } catch (err) {
        return { success: false, message: 'Unexpected server response.' };
    }
}
