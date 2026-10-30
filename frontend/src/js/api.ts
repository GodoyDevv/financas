/**
 * frontend/src/js/api.ts
 *
 * Cliente HTTP tipado para a API do FinTrack (openapi-fetch)
 * com tratamento centralizado de erros de autenticação (401 -> /login).
 */

import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "../api-types";

export const API_BASE = "/api";

const authMiddleware: Middleware = {
  async onResponse({ response }) {
    if (response.status === 401) {
      if (typeof window !== "undefined") {
        window.location.href = "/login";
      }
      throw new Error("Sessão expirada. Redirecionando...");
    }
    return response;
  },
};

export const apiClient = createClient<paths>({
  credentials: "same-origin",
  headers: {
    Accept: "application/json",
  },
});

apiClient.use(authMiddleware);

export async function apiFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const defaultHeaders = {
    Accept: "application/json",
  };

  const config: RequestInit = {
    ...options,
    credentials: "same-origin",
    headers: {
      ...defaultHeaders,
      ...(options.headers || {}),
    },
  };

  const response = await fetch(url, config);

  if (response.status === 401) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Sessão expirada. Redirecionando...");
  }

  return response;
}

export async function fazerLogout(): Promise<void> {
  try {
    await fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
  } catch (err) {
    console.error("Erro ao efetuar logout:", err);
  } finally {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }
}
