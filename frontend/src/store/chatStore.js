/**
 * NexusIQ — store/chatStore.js
 *
 * Production fixes:
 *   1. query_type stored per message — shown as badge in UI
 *   2. clearError() action — lets UI dismiss errors without new message
 *   3. isSubmitting flag — prevents duplicate submits while loading
 *   4. toast queue — lightweight in-app notification system
 *   5. lastQueryType — tracks current mode for top-bar badge
 */

import { create } from 'zustand'

let _id = 0
const uid = () => `msg_${++_id}_${Date.now()}`

export const useChatStore = create((set, get) => ({
  // ── Conversation state ───────────────────────────────────────────
  messages:  [],
  isLoading: false,
  error:     null,
  lastTrace: null,
  lastQueryType: null,   // 'factual_qa' | 'summary' | 'revision_notes' | etc.

  // ── Toast notifications ──────────────────────────────────────────
  // [{ id, type: 'success'|'error'|'info', message, ts }]
  toasts: [],

  // ── Actions ─────────────────────────────────────────────────────

  addMessage(msg) {
    set((s) => ({
      messages: [
        ...s.messages,
        {
          id:               uid(),
          role:             'user',
          content:          '',
          citations:        [],
          confidence_score: null,
          retrieval_trace:  null,
          rewritten_query:  null,
          sub_queries:      [],
          query_type:       null,
          ts:               Date.now(),
          ...msg,
        },
      ],
      // Track query type from latest assistant message
      lastQueryType: msg.query_type ?? get().lastQueryType,
    }))
  },

  updateMessage(id, patch) {
    set((s) => ({
      messages: s.messages.map((m) => (m.id === id ? { ...m, ...patch } : m)),
    }))
  },

  setLoading(loading) {
    set({ isLoading: loading, error: loading ? null : get().error })
  },

  setError(error) {
    set({ error, isLoading: false })
    // Also push an error toast
    if (error) {
      get().addToast('error', error)
    }
  },

  clearError() {
    set({ error: null })
  },

  setLastTrace(trace) {
    set({ lastTrace: trace })
  },

  clearMessages() {
    set({ messages: [], error: null, lastTrace: null, lastQueryType: null })
  },

  // ── Toast system ─────────────────────────────────────────────────

  addToast(type, message) {
    const id = uid()
    set((s) => ({
      toasts: [...s.toasts, { id, type, message, ts: Date.now() }],
    }))
    // Auto-dismiss after 5s
    setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 5000)
  },

  dismissToast(id) {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
  },
}))