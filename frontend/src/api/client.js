export const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
export const WS_BASE = API_BASE.replace(/^http/, 'ws');

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response body wasn't JSON; fall back to statusText
    }
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return null;
  return res.json();
}

// Multipart upload (video/image processing) -- no Content-Type header, the browser sets the
// multipart boundary itself. Separate from `request()` since that always sends JSON.
async function requestForm(path, formData) {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: formData });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // response body wasn't JSON; fall back to statusText
    }
    throw new ApiError(detail, res.status);
  }
  return res.json();
}

export const api = {
  get: (path) => request(path),
  post: (path, body) => request(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  postForm: (path, formData) => requestForm(path, formData),
  del: (path) => request(path, { method: 'DELETE' }),
};
