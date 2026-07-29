export const PASSWORD_RULES = [
    { key: 'length', test: (p) => p.length >= 8, label: 'At least 8 characters' },
    { key: 'uppercase', test: (p) => /[A-Z]/.test(p), label: 'An uppercase letter' },
    { key: 'lowercase', test: (p) => /[a-z]/.test(p), label: 'A lowercase letter' },
    { key: 'number', test: (p) => /[0-9]/.test(p), label: 'A number' },
    { key: 'special', test: (p) => /[^A-Za-z0-9]/.test(p), label: 'A special character' }
];

export function checkPasswordRules(password) {
    return PASSWORD_RULES.map((rule) => ({ key: rule.key, met: rule.test(password) }));
}

export function isPasswordValid(password) {
    return PASSWORD_RULES.every((rule) => rule.test(password));
}

export function isValidEmail(email) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}
