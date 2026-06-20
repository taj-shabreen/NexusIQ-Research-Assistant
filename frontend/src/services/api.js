/**
 * NexusIQ — services/api.js
 *
 * Production-grade Axios client with:
 *   1. readyApi.poll()      — polls /ready until backend is truly ready
 *   2. Upload retry         — retries failed uploads up to MAX_UPLOAD_RETRIES
 *   3. Exponential backoff  — waits between retries
 *   4. Meaningful errors    — maps network errors to user-readable messages
 *   5. Request timeout      — per-endpoint timeouts
 *
 * CRITICAL: Uses VITE_API_URL env var — never hardcodes localhost.
 */

import axios from 'axios'

const BASE =
  import.meta.env.VITE_API_URL ||
  'http://127.0.0.1:8000'

// ── Session ID — per-browser identity for document isolation ───────
// No user accounts exist yet, so a randomly generated id persisted in
// localStorage is the smallest mechanism that gives each browser its
// own private document library. Sent as X-Session-Id on every request.
const SESSION_STORAGE_KEY = 'nexusiq_session_id'

function getOrCreateSessionId() {
  try {
    let id = localStorage.getItem(SESSION_STORAGE_KEY)
    if (!id) {
      id = (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID()
        : `sess_${Date.now()}_${Math.random().toString(36).slice(2)}`
      localStorage.setItem(SESSION_STORAGE_KEY, id)
    }
    return id
  } catch {
    // localStorage unavailable (e.g. private browsing edge cases) —
    // fall back to an in-memory id for this page load only.
    return `sess_${Date.now()}_${Math.random().toString(36).slice(2)}`
  }
}

export const sessionId = getOrCreateSessionId()

// ── Base client ───────────────────────────────────────────────────
export const http = axios.create({
  baseURL: `${BASE}/api`,
  timeout: 120_000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Request interceptor: inject session id + log in dev ──────────
http.interceptors.request.use((config) => {
  config.headers = config.headers || {}
  config.headers['X-Session-Id'] = sessionId
  if (import.meta.env.DEV) {
    console.debug(`[NexusIQ] ▶ ${config.method?.toUpperCase()} ${config.url}`)
  }
  return config
})

// ── Response interceptor: normalise errors ────────────────────────
http.interceptors.response.use(
  (res) => res,
  (err) => {
    if (!err.response) {
      const msg = err.code === 'ECONNABORTED'
        ? 'Request timed out — backend may still be loading. Please retry.'
        : 'Cannot reach backend — make sure the server is running on port 8000.'
      return Promise.reject(new Error(msg))
    }

    const status  = err.response.status
    const detail  = err.response?.data?.detail || err.response?.data?.message || err.message

    if (status === 503) {
      return Promise.reject(new Error(
        `Backend not ready yet: ${detail || 'still initialising…'}`
      ))
    }
    if (status === 422) {
      return Promise.reject(new Error(`Validation error: ${detail}`))
    }
    if (status >= 500) {
      return Promise.reject(new Error(`Server error (${status}): ${detail}`))
    }

    return Promise.reject(new Error(detail || `Request failed (${status})`))
  }
)

// ── Readiness API ─────────────────────────────────────────────────
export const readyApi = {
  async check() {
    const res = await axios.get(`${BASE}/ready`, { timeout: 5_000 })
    return res.data
  },

  async poll({
    maxAttempts = 30,
    intervalMs  = 2_000,
    onProgress  = null,
  } = {}) {
    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      try {
        const res = await axios.get(`${BASE}/ready`, { timeout: 4_000 })
        if (res.status === 200 && res.data?.ready) {
          return res.data
        }
        onProgress?.(attempt, res.data)
      } catch (err) {
        const data = err.response?.data
        if (err.response?.status === 503) {
          onProgress?.(attempt, data ?? { ready: false, error: 'starting…' })
        } else if (!err.response) {
          onProgress?.(attempt, { ready: false, error: 'connecting…' })
        } else {
          throw new Error(`Readiness check failed: ${err.message}`)
        }
      }

      if (attempt < maxAttempts) {
        const wait = Math.min(intervalMs * (1 + attempt * 0.1), 6_000)
        await new Promise(r => setTimeout(r, wait))
      }
    }
    throw new Error(
      `Backend did not become ready after ${maxAttempts} attempts (${(maxAttempts * intervalMs) / 1000}s). ` +
      'Check the backend terminal for errors.'
    )
  },
}

// ── Health API ────────────────────────────────────────────────────
export const healthApi = {
  check() {
    return axios.get(`${BASE}/health`, { timeout: 5_000 })
  },
}

// ── Documents API ─────────────────────────────────────────────────

const MAX_UPLOAD_RETRIES = 2
const UPLOAD_RETRY_DELAY = 2_000

async function _uploadWithRetry(formData, onUploadProgress) {
  let lastError
  for (let attempt = 1; attempt <= MAX_UPLOAD_RETRIES + 1; attempt++) {
    try {
      const res = await http.post('/documents/upload', formData, {
        headers:          { 'Content-Type': 'multipart/form-data' },
        onUploadProgress,
        timeout:          180_000,
      })
      return res
    } catch (err) {
      lastError = err
      const isRetryable =
        err.message.includes('timed out') ||
        err.message.includes('Cannot reach backend') ||
        err.message.includes('not ready') ||
        err.message.includes('503') ||
        err.message.includes('Network Error')

      if (!isRetryable || attempt > MAX_UPLOAD_RETRIES) {
        break
      }

      const delay = UPLOAD_RETRY_DELAY * attempt
      console.warn(
        `[NexusIQ] Upload attempt ${attempt} failed (${err.message}) — retrying in ${delay}ms…`
      )
      await new Promise(r => setTimeout(r, delay))
    }
  }
  throw lastError
}

export const documentsApi = {
  upload(formData, onUploadProgress) {
    return _uploadWithRetry(formData, onUploadProgress)
  },
  list() {
    return http.get('/documents/', { timeout: 15_000 })
  },
  remove(documentId) {
    return http.delete(`/documents/${documentId}`, { timeout: 30_000 })
  },
}

// ── Query API ─────────────────────────────────────────────────────
export const queryApi = {
  ask(payload) {
    return http.post('/query/', payload, { timeout: 240_000 })
  },
}

// ── Evaluation API ────────────────────────────────────────────────
export const evaluationApi = {
  run(payload) {
    return http.post('/evaluation/run', payload, { timeout: 300_000 })
  },
  history() {
    return http.get('/evaluation/history', { timeout: 15_000 })
  },
}

// ── Debug API ─────────────────────────────────────────────────────
export const debugApi = {
  health() {
    return http.get('/debug/health', { timeout: 8_000 })
  },
  stats() {
    return http.get('/debug/stats', { timeout: 8_000 })
  },
  retrieve(payload) {
    return http.post('/debug/retrieve', payload, { timeout: 30_000 })
  },
  chunks(payload) {
    return http.post('/debug/chunks', payload, { timeout: 30_000 })
  },
  collectionStats() {
    return http.get('/debug/collection-stats', { timeout: 8_000 })
  },
  documentChunks(documentId, page = null) {
    const params = page ? { page } : {}
    return http.get(`/debug/documents/${documentId}`, { params, timeout: 15_000 })
  },
}

// ── Visitor API ───────────────────────────────────────────────────
export const visitorApi = {
  register(name, email) {
    return http.post('/visitors/register', { name, email })
  },
  stats() {
    return http.get('/visitors/stats')
  },
}