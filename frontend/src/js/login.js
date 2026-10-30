/**
 * frontend/src/js/login.js
 *
 * Script do formulário de login (servido como arquivo estático para conformidade com CSP script-src 'self').
 */
const form = document.getElementById('login-form');
const btn = document.getElementById('btn-login');
const errorBox = document.getElementById('error-box');

if (form) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (errorBox) errorBox.style.display = 'none';
    if (btn) {
      btn.disabled = true;
      btn.innerText = 'Autenticando...';
    }

    const passwordInput = document.getElementById('password');
    const password = passwordInput ? passwordInput.value : '';

    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ password })
      });

      if (res.ok) {
        window.location.href = '/';
      } else {
        const data = await res.json().catch(() => ({}));
        if (errorBox) {
          errorBox.innerText = data.detail || 'Senha incorreta. Tente novamente.';
          errorBox.style.display = 'block';
        }
        if (btn) {
          btn.disabled = false;
          btn.innerText = 'Entrar no Dashboard';
        }
        if (passwordInput) passwordInput.focus();
      }
    } catch (err) {
      if (errorBox) {
        errorBox.innerText = 'Falha ao conectar ao servidor.';
        errorBox.style.display = 'block';
      }
      if (btn) {
        btn.disabled = false;
        btn.innerText = 'Entrar no Dashboard';
      }
    }
  });
}
