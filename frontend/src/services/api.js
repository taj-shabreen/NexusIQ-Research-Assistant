/**
 * NexusIQ — services/api.js
 *
 * Production-grade Axios client with:
 *   1. readyApi.poll()      — polls /ready until backend is truly ready
 *   2. Upload retry         — retries failed uploads up to MAX_UPLOAD_RETRIES
 *   3. Exponential backoff  — waits between retries
 *   4. Meaningful errors    — maps network errors to user-readable messages
 *   5. Request timeout      — per-endpoint timeouts
 */

import axios from 'axios'

const BASE = 'http://127.0.0.1:8000'

// ── Base client ───────────────────────────────────────────────────
export const http = axios.create({
  baseURL: `${BASE}/api`,
  timeout: 120_000,
  headers: { 'Content-Type': 'application/json' },
})

// ── Request interceptor: log in dev ──────────────────────────────
http.interceptors.request.use((config) => {
  if (import.meta.env.DEV) {
    console.debug(`[NexusIQ] ▶ ${config.method?.toUpperCase()} ${config.url}`)
  }
  return config
})

// ── Response interceptor: normalise errors ────────────────────────
http.interceptors.response.use(
  (res) => res,
  (err) => {
    // Map common network failures to readable messages
    if (!err.response) {
      // No response at all — backend unreachable
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
  /**
   * Single readiness check.
   * Returns { ready, subsystems, model, embed_model } or throws.
   */
  async check() {
    const res = await axios.get(`${BASE}/ready`, { timeout: 5_000 })
    return res.data
  },

  /**
   * Poll /ready until the backend is fully ready.
   *
   * @param {object} options
   * @param {number} options.maxAttempts   Max poll attempts (default 30 = 60s)
   * @param {number} options.intervalMs    Base interval in ms (default 2000)
   * @param {function} options.onProgress  Called each attempt: (attempt, state) => void
   * @returns {Promise<object>}            Resolves with readiness data when ready
   * @throws {Error}                       If maxAttempts exceeded
   */
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
        // 200 but not ready (shouldn't happen per backend design, but guard)
        onProgress?.(attempt, res.data)
      } catch (err) {
        const data = err.response?.data
        if (err.response?.status === 503) {
          // Expected during startup — not ready yet
          onProgress?.(attempt, data ?? { ready: false, error: 'starting…' })
        } else if (!err.response) {
          // Backend not yet accepting connections
          onProgress?.(attempt, { ready: false, error: 'connecting…' })
        } else {
          // Unexpected error — stop polling
          throw new Error(`Readiness check failed: ${err.message}`)
        }
      }

      if (attempt < maxAttempts) {
        // Exponential backoff: 2s, 2.5s, 3s, 3.5s … capped at 6s
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
  /**
   * GET /health — always responds, returns per-subsystem status.
   * Use readyApi.poll() to wait for full readiness.
   * Use this for status display.
   */
  check() {
    return axios.get(`${BASE}/health`, { timeout: 5_000 })
  },
}

// ── Documents API ─────────────────────────────────────────────────

const MAX_UPLOAD_RETRIES = 2
const UPLOAD_RETRY_DELAY = 2_000  // ms

async function _uploadWithRetry(formData, onUploadProgress) {
  let lastError
  for (let attempt = 1; attempt <= MAX_UPLOAD_RETRIES + 1; attempt++) {
    try {
      const res = await http.post('/documents/upload', formData, {
        headers:          { 'Content-Type': 'multipart/form-data' },
        onUploadProgress,
        timeout:          180_000,   // 3 min for large PDFs
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
  /**
   * Upload one or more PDFs with automatic retry on network failures.
   * @param {FormData} formData
   * @param {function} onUploadProgress  Axios progress callback
   */
  upload(formData, onUploadProgress) {
    return _uploadWithRetry(formData, onUploadProgress)
  },

  /** List all indexed documents. */
  list() {
    return http.get('/documents/', { timeout: 15_000 })
  },

  /** Delete a document and all its chunks. */
  remove(documentId) {
    return http.delete(`/documents/${documentId}`, { timeout: 30_000 })
  },
}

// ── Query API ─────────────────────────────────────────────────────
export const queryApi = {
ask(payload) {
  return http.post('/query/', payload, { timeout: 240_000 })  // 4 minutes
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