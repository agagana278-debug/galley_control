const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

let unauthorizedHandler = null;

export function registerUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

export function buildApiUrl(path) {
  return `${API_BASE}${path}`;
}

export function resolveImageUrl(url) {
  if (!url) return null;
  if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("data:")) {
    return url;
  }
  return buildApiUrl(url.startsWith("/") ? url : `/${url}`);
}

export class ApiError extends Error {
  constructor(message, status, detail = null) {
    super(message);
    this.status = status;
    this.detail = detail;
  }
}

export async function apiRequest(path, options = {}) {
  const { skipAuthClear = false, headers = {}, ...rest } = options;

  const res = await fetch(buildApiUrl(path), {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...headers,
    },
    ...rest,
  });

  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { detail: text };
  }

  if (res.status === 401 && !skipAuthClear && unauthorizedHandler) {
    unauthorizedHandler();
  }

  if (!res.ok) {
    const detail = data?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message || `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status, detail);
  }
  return data;
}

export async function streamAgentChat(payload, { onMeta, onToken, onDone }) {
  const res = await fetch(buildApiUrl("/api/agents/chat/stream"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (res.status === 401 && unauthorizedHandler) {
    unauthorizedHandler();
  }

  if (!res.ok) {
    const text = await res.text();
    let msg = `Request failed with status ${res.status}`;
    try {
      const parsed = JSON.parse(text);
      msg = parsed?.detail || msg;
    } catch {
      // Keep default error string
    }
    throw new ApiError(msg, res.status);
  }

  const reader = res.body?.getReader();
  if (!reader) {
    throw new Error("Streaming reader unavailable in this browser.");
  }

  const decoder = new TextDecoder();
  let buffer = "";
  let donePayload = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line.startsWith("data:")) continue;
      const jsonStr = line.slice(5).trim();
      if (!jsonStr) continue;
      let evt;
      try {
        evt = JSON.parse(jsonStr);
      } catch {
        continue;
      }
      if (evt.type === "meta" && onMeta) onMeta(evt);
      if (evt.type === "token" && onToken) onToken(evt.text || "");
      if (evt.type === "done") {
        donePayload = evt;
        if (onDone) onDone(evt);
      }
    }
  }
  return donePayload;
}

export const fetchAuthConfig = () =>
  apiRequest("/api/auth/config", { skipAuthClear: true });

export const registerStudent = (payload) =>
  apiRequest("/api/auth/register", {
    method: "POST",
    skipAuthClear: true,
    body: JSON.stringify(payload),
  });

export const loginUser = (identifier, password) =>
  apiRequest("/api/auth/login", {
    method: "POST",
    skipAuthClear: true,
    body: JSON.stringify({ identifier, password }),
  });

export const logoutUser = () =>
  apiRequest("/api/auth/logout", {
    method: "POST",
    skipAuthClear: true,
  });

export const getEmailStatus = () =>
  apiRequest("/api/auth/email-status", {
    method: "GET",
    skipAuthClear: true,
  });

export const forgotPassword = (email) =>
  apiRequest("/api/auth/forgot-password", {
    method: "POST",
    skipAuthClear: true,
    body: JSON.stringify({ email }),
  });

export const resetPasswordWithToken = (payload) =>
  apiRequest("/api/auth/reset-password", {
    method: "POST",
    skipAuthClear: true,
    body: JSON.stringify(payload),
  });

export const fetchCurrentUser = () =>
  apiRequest("/api/auth/me", { skipAuthClear: true });

export const fetchHealth = () =>
  apiRequest("/api/health", { skipAuthClear: true });

export const fetchCatalogOverview = () => apiRequest("/api/catalog/overview");
export const resetDemoData = () =>
  apiRequest("/api/demo/reset", { method: "POST" });

export const checkoutOrder = (payload) =>
  apiRequest("/api/orders/checkout", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchOrders = (includeSample = false, outletId = null) => {
  const params = new URLSearchParams({
    include_sample: includeSample ? "true" : "false",
  });
  if (outletId) params.set("outlet_id", String(outletId));
  return apiRequest(`/api/orders?${params.toString()}`);
};

export const fetchGroupOrders = (groupCode) =>
  apiRequest(`/api/orders/group/${encodeURIComponent(groupCode)}`);

export const cancelOrder = (orderId, reason) =>
  apiRequest(`/api/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });

export const markOrderPreparing = (orderId) =>
  apiRequest(`/api/orders/${orderId}/prepare`, { method: "POST" });

export const verifyQrToken = (token) =>
  apiRequest("/api/qr/verify", {
    method: "POST",
    body: JSON.stringify({ token }),
  });

export const fetchSecurityEvents = () => apiRequest("/api/qr/security-events");

export const chatWithOrchestrator = (payload) =>
  apiRequest("/api/agents/chat", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchConversations = () => apiRequest("/api/agents/conversations");
export const fetchConversationMessages = (id) =>
  apiRequest(`/api/agents/conversations/${id}`);
export const deleteConversation = (id) =>
  apiRequest(`/api/agents/conversations/${id}`, { method: "DELETE" });

export const submitReview = (payload) =>
  apiRequest("/api/reviews", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const resolveReview = (reviewId) =>
  apiRequest(`/api/reviews/${reviewId}/resolve`, { method: "POST" });

export const fetchOutletDashboard = (outletId = null) =>
  apiRequest(
    outletId
      ? `/api/dashboard/outlet?outlet_id=${encodeURIComponent(outletId)}`
      : "/api/dashboard/outlet"
  );

export const updateOutletStock = (itemId, stockQty) =>
  apiRequest(`/api/dashboard/outlet/menu/${itemId}/stock`, {
    method: "PATCH",
    body: JSON.stringify({ stock_qty: stockQty }),
  });

export const updateMenuItem = (itemId, payload) =>
  apiRequest(`/api/dashboard/outlet/menu/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const uploadMenuItemImage = async (itemId, file) => {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(buildApiUrl(`/api/dashboard/outlet/menu/${itemId}/image`), {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data?.detail || "Image upload failed", res.status);
  }
  return res.json();
};

export const deleteMenuItemImage = (itemId) =>
  apiRequest(`/api/dashboard/outlet/menu/${itemId}/image`, {
    method: "DELETE",
  });

export const fetchPublicOrganisations = () =>
  apiRequest("/api/organisations/public", { skipAuthClear: true });

export const registerOrganisation = (payload) =>
  apiRequest("/api/organisations/register", {
    method: "POST",
    skipAuthClear: true,
    body: JSON.stringify(payload),
  });

export const fetchOrgSummary = (organisationId = null) =>
  apiRequest(
    organisationId
      ? `/api/dashboard/org-summary?organisation_id=${encodeURIComponent(organisationId)}`
      : "/api/dashboard/org-summary"
  );

export const createOrgOutlet = (payload) =>
  apiRequest("/api/dashboard/outlets", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateOrgOutlet = (outletId, payload) =>
  apiRequest(`/api/dashboard/outlets/${outletId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const addOutletMenuItem = (payload) =>
  apiRequest("/api/dashboard/outlet/menu", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const createOrgManager = (payload) =>
  apiRequest("/api/dashboard/org/managers", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const fetchDashboardSummary = (organisationId = null) =>
  apiRequest(
    organisationId
      ? `/api/dashboard/summary?organisation_id=${encodeURIComponent(organisationId)}`
      : "/api/dashboard/summary"
  );

export const actOnRecommendation = (recId, status) =>
  apiRequest(`/api/dashboard/recommendations/${recId}`, {
    method: "POST",
    body: JSON.stringify({ status }),
  });

export const resolveSecurityEvent = (eventId) =>
  apiRequest(`/api/dashboard/security/${eventId}/resolve`, { method: "POST" });

export const fetchAdminOrganisations = () =>
  apiRequest("/api/admin/organisations");

export const updateOrganisationStatus = (orgId, status) =>
  apiRequest(`/api/admin/organisations/${orgId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });

export const fetchAdminOverview = (organisationId = null) =>
  apiRequest(
    organisationId
      ? `/api/admin/overview?organisation_id=${encodeURIComponent(organisationId)}`
      : "/api/admin/overview"
  );

export const createAdminOutlet = (payload) =>
  apiRequest("/api/admin/outlets", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateAdminOutlet = (outletId, payload) =>
  apiRequest(`/api/admin/outlets/${outletId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const createAdminUser = (payload) =>
  apiRequest("/api/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const updateAdminUser = (userId, payload) =>
  apiRequest(`/api/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
