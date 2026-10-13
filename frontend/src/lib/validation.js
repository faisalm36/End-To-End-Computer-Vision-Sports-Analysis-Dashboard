export const MIN_PASSWORD = 8;

export function validateEmail(v) {
  if (!v.trim()) return 'Enter your email address.';
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v.trim())) return 'Enter a valid email, like name@example.com.';
  return '';
}

export function validatePassword(v, { signup = false } = {}) {
  if (!v) return 'Enter your password.';
  if (signup && v.length < MIN_PASSWORD) return `Use at least ${MIN_PASSWORD} characters.`;
  return '';
}

// Rough strength hint: 0-4.
export function passwordStrength(v) {
  if (!v) return { score: 0, label: '' };
  let score = 0;
  if (v.length >= MIN_PASSWORD) score += 1;
  if (v.length >= 12) score += 1;
  if (/[a-z]/.test(v) && /[A-Z]/.test(v)) score += 1;
  if (/\d/.test(v) && /[^A-Za-z0-9]/.test(v)) score += 1;
  const labels = ['Too short', 'Weak', 'Okay', 'Good', 'Strong'];
  return { score, label: v.length < MIN_PASSWORD ? labels[0] : labels[score] };
}
