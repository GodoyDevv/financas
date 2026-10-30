/**
 * frontend/src/js/api.js
 *
 * Cliente HTTP para a API do FinTrack com tratamento centralizado
 * de erros de autenticação (401 -> redirecionamento seguro para /login).
 */

export const API_BASE = '/api';

export async function apiFetch(url, options = {}) {
  const defaultHeaders = {
    'Accept': 'application/json',
  };

  const config = {
    ...options,
    credentials: 'same-origin',
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
  };

  const response = await fetch(url, config);

  if (response.status === 401) {
    window.location.href = '/login';
    throw new Error('Sessão expirada. Redirecionando...');
  }

  return response;
}

export async function fazerLogout() {
  try {
    await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' });
  } catch (err) {
    console.error('Erro ao efetuar logout:', err);
  } finally {
    window.location.href = '/login';
  }
}
