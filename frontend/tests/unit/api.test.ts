import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { apiFetch, fazerLogout } from "../../src/js/api";

describe("api module", () => {
  const originalLocation = window.location;

  beforeEach(() => {
    vi.restoreAllMocks();
    delete (window as unknown as Record<string, unknown>).location;
    window.location = {
      href: "",
      origin: "http://localhost:5173",
    } as unknown as Location;
  });

  afterEach(() => {
    window.location = originalLocation;
  });

  it("apiFetch redirects to /login on 401 response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      status: 401,
      ok: false,
    });

    await expect(apiFetch("/api/test")).rejects.toThrow("Sessão expirada. Redirecionando...");
    expect(window.location.href).toBe("/login");
  });

  it("apiFetch bubbles up network errors", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network failed"));

    await expect(apiFetch("/api/test")).rejects.toThrow("Network failed");
  });

  it("apiFetch passes same-origin credentials and custom headers", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
      json: async () => ({ ok: true }),
    });
    global.fetch = mockFetch;

    const res = await apiFetch("/api/custom", {
      headers: { "X-Test": "123" },
    });

    expect(res.status).toBe(200);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/custom",
      expect.objectContaining({
        credentials: "same-origin",
        headers: expect.objectContaining({
          Accept: "application/json",
          "X-Test": "123",
        }),
      })
    );
  });

  it("fazerLogout triggers /auth/logout and redirects to /login", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      status: 200,
      ok: true,
    });
    global.fetch = mockFetch;

    await fazerLogout();
    expect(mockFetch).toHaveBeenCalledWith(
      "/auth/logout",
      expect.objectContaining({ method: "POST", credentials: "same-origin" })
    );
    expect(window.location.href).toBe("/login");
  });

  it("handles 401 response and redirects to /login", async () => {
    const mockRes = new Response(JSON.stringify({ detail: "Unauthorized" }), {
      status: 401,
      headers: { "Content-Type": "application/json" },
    });
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockRes);

    await expect(apiFetch("/api/transactions")).rejects.toThrow(
      "Sessão expirada. Redirecionando..."
    );
    expect(window.location.href).toBe("/login");
  });

  it("handles 422 validation error", async () => {
    const mockRes = new Response(
      JSON.stringify({ detail: [{ loc: ["body", "valor"], msg: "Field required" }] }),
      {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }
    );
    vi.spyOn(globalThis, "fetch").mockResolvedValue(mockRes);

    const res = await apiFetch("/api/transactions", { method: "POST" });
    expect(res.status).toBe(422);
    const data = await res.json();
    expect(data.detail[0].msg).toBe("Field required");
  });
});
