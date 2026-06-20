import React, { useState, useRef, useEffect } from 'react'
import {
  Send, Loader2, X, Upload, FileText, Trash2,
  Sparkles, BookOpen, Table2, FileSearch,
  GraduationCap, ClipboardList, AlignLeft,
  CheckCircle2, AlertCircle, XCircle, Info,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import DocumentUpload from '../components/DocumentUpload'
import ChatWindow from '../components/ChatWindow'
import { useChatStore } from '../store/chatStore'
import { useDocumentStore } from '../store/documentStore'
import { useDocuments } from '../hooks/useDocuments'
import { queryApi } from '../services/api'
import { useBackend } from '../components/Layout'

/* ─────────────────────────────────────────────────────────────────
   QUERY TYPE CONFIG — for badge display
───────────────────────────────────────────────────────────────── */
const QT_CFG = {
  factual_qa:      { label: 'Factual QA',       icon: FileSearch,    color: '#4a90e2', bg: 'rgba(74,144,226,.12)'  },
  summary:         { label: 'Summary',           icon: AlignLeft,     color: '#9b87f5', bg: 'rgba(155,135,245,.12)' },
  revision_notes:  { label: 'Revision Notes',    icon: ClipboardList, color: '#3ecf8e', bg: 'rgba(62,207,142,.12)'  },
  interview_guide: { label: 'Interview Guide',   icon: GraduationCap, color: '#e09c43', bg: 'rgba(224,156,67,.12)'  },
  table:           { label: 'Table',             icon: Table2,        color: '#e25c6a', bg: 'rgba(226,92,106,.12)'  },
  conclusion:      { label: 'Conclusion',        icon: BookOpen,      color: '#c9a84c', bg: 'rgba(201,168,76,.12)'  },
  long_synthesis:  { label: 'Deep Synthesis',    icon: Sparkles,      color: '#8bbef7', bg: 'rgba(139,190,247,.12)' },
}

/* ─────────────────────────────────────────────────────────────────
   QUERY TYPE BADGE
───────────────────────────────────────────────────────────────── */
function QueryTypeBadge({ queryType }) {
  if (!queryType) return null
  const cfg  = QT_CFG[queryType]
  if (!cfg) return null
  const Icon = cfg.icon
  return (
    <motion.div
      initial={{ opacity: 0, scale: .9 }}
      animate={{ opacity: 1, scale: 1 }}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs"
      style={{
        background: cfg.bg,
        border:     `1px solid ${cfg.color}35`,
        color:      cfg.color,
        fontFamily: 'var(--font-mono)',
      }}
    >
      <Icon size={11} />
      {cfg.label}
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   TOAST NOTIFICATION
───────────────────────────────────────────────────────────────── */
function Toast({ toast, onDismiss }) {
  const cfg = {
    success: { icon: CheckCircle2, color: 'var(--emerald)', bg: 'rgba(62,207,142,.07)',  border: 'rgba(62,207,142,.25)'  },
    error:   { icon: XCircle,      color: 'var(--rose)',    bg: 'rgba(226,92,106,.07)',  border: 'rgba(226,92,106,.25)'  },
    info:    { icon: Info,         color: '#8bbef7',        bg: 'rgba(74,144,226,.07)',  border: 'rgba(74,144,226,.25)'  },
  }
  const c    = cfg[toast.type] ?? cfg.info
  const Icon = c.icon

  return (
    <motion.div
      initial={{ opacity: 0, y: 20, scale: .95 }}
      animate={{ opacity: 1, y: 0,  scale: 1    }}
      exit={  { opacity: 0, y: 10,  scale: .97  }}
      transition={{ duration: .2 }}
      className="flex items-start gap-3 px-4 py-3 rounded-xl shadow-lg max-w-sm"
      style={{ background: c.bg, border: `1px solid ${c.border}`, backdropFilter: 'blur(16px)' }}
    >
      <Icon size={14} style={{ color: c.color, flexShrink: 0, marginTop: 1 }} />
      <p className="text-sm flex-1 leading-snug" style={{ color: c.color }}>
        {toast.message}
      </p>
      <button
        onClick={() => onDismiss(toast.id)}
        className="flex-shrink-0 opacity-60 hover:opacity-100 transition-opacity"
        style={{ color: c.color }}
      >
        <X size={12} />
      </button>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   TOAST CONTAINER
───────────────────────────────────────────────────────────────── */
function ToastContainer() {
  const { toasts, dismissToast } = useChatStore()
  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 pointer-events-none">
      <AnimatePresence>
        {toasts.map(t => (
          <div key={t.id} className="pointer-events-auto">
            <Toast toast={t} onDismiss={dismissToast} />
          </div>
        ))}
      </AnimatePresence>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   QUERY HINT CHIPS — shown when no messages yet
───────────────────────────────────────────────────────────────── */
const QUERY_HINTS = [
  { text: 'Summarize Unit3.pdf',                  type: 'summary'         },
  { text: 'Generate revision notes',              type: 'revision_notes'  },
  { text: 'Create interview preparation guide',   type: 'interview_guide' },
  { text: 'Compare design patterns in a table',   type: 'table'           },
  { text: 'What is merge sort?',                  type: 'factual_qa'      },
  { text: 'Give conclusion from Unit 4',          type: 'conclusion'      },
]

/* ─────────────────────────────────────────────────────────────────
   DOCUMENT LIST ITEM
───────────────────────────────────────────────────────────────── */
function DocItem({ doc, onDelete }) {
  const { isDocumentDeleting } = useDocumentStore()
  const docId = doc.filename
  const isDeleting = isDocumentDeleting(docId)

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0  }}
      exit={  { opacity: 0, x: -10, height: 0, marginBottom: 0 }}
      transition={{ duration: .2 }}
      className="group flex items-center gap-3 px-3 py-3 rounded-xl cursor-default"
      style={{ border: '1px solid var(--border)', background: 'rgba(8,12,20,.5)' }}
      whileHover={{ borderColor: 'rgba(74,144,226,.25)', backgroundColor: 'rgba(74,144,226,.04)' }}
    >
      <div
        className="w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: 'rgba(74,144,226,.1)', border: '1px solid rgba(74,144,226,.2)' }}
      >
        <FileText size={14} style={{ color: '#8bbef7' }} />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate leading-tight" style={{ color: 'var(--text-primary)' }}>
          {doc.filename}
        </p>
        <p className="text-xs mt-0.5" style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
          {doc.chunks ?? doc.chunks_created ?? '?'} chunks
        </p>
      </div>

      <motion.button
        whileHover={{ scale: 1.15 }}
        whileTap={{ scale: .9 }}
        onClick={() => onDelete(doc.filename)}
        disabled={isDeleting}
        className="opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-lg"
        style={{ color: 'var(--rose)' }}
        title="Remove document"
      >
        {isDeleting
          ? <Loader2 size={12} className="animate-spin" />
          : <Trash2 size={12} />
        }
      </motion.button>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   MAIN PAGE
───────────────────────────────────────────────────────────────── */
export default function ResearchPage() {
  const [input, setInput] = useState('')
  const inputRef          = useRef(null)
  const submitRef         = useRef(false)   // duplicate submit guard

  const { backendReady } = useBackend()

  const {
    messages, addMessage, isLoading,
    setLoading, setError, clearError,
    lastQueryType, addToast,
  } = useChatStore()

  const {
    documents, setDeleting,
  } = useDocumentStore()

  const { fetchDocuments, deleteDocument } = useDocuments()

  // ── Fetch docs on mount ────────────────────────────────────────
  useEffect(() => {
    if (backendReady) {
      fetchDocuments()
    }
  }, [backendReady])

  // ── Delete handler ─────────────────────────────────────────────
  const handleDelete = async (docId) => {
    setDeleting(docId, true)
    try {
      await deleteDocument(docId)
      addToast('success', 'Document removed successfully.')
    } catch (err) {
      addToast('error', `Delete failed: ${err.message}`)
    } finally {
      setDeleting(docId, false)
    }
  }

  // ── Submit handler ─────────────────────────────────────────────
  const submit = async () => {
    if (!input.trim() || isLoading || submitRef.current) return
    if (!backendReady) {
      addToast('error', 'Backend is not ready yet. Please wait.')
      return
    }

    submitRef.current = true   // lock duplicate submits
    const question    = input.trim()
    setInput('')
    clearError()
    if (inputRef.current) inputRef.current.style.height = 'auto'
    inputRef.current?.focus()

    addMessage({ role: 'user', content: question })
    setLoading(true)

    try {
      const history = messages
        .slice(-8)
        .map(m => ({ role: m.role, content: m.content }))

      const { data } = await queryApi.ask({
        question,
        conversation_history: history,
        enable_reranking:     true,
        enable_multi_query:   false,
      })

      addMessage({
        role:             'assistant',
        content:          data.answer,
        citations:        data.citations        ?? [],
        confidence_score: data.confidence_score ?? 0,
        retrieval_trace:  data.retrieval_trace  ?? {},
        rewritten_query:  data.rewritten_query  ?? null,
        sub_queries:      data.sub_queries      ?? [],
        query_type:       data.query_type       ?? null,
      })

    } catch (err) {
      // Map error types to user-friendly messages
      let msg = err.message || 'Query failed.'
      if (msg.includes('timed out'))      msg = 'Request timed out. The document may be large — try a more specific question.'
      if (msg.includes('not ready'))      msg = 'Backend is still starting. Please wait a moment.'
      if (msg.includes('413'))            msg = 'Query too complex. Try asking about a specific section or topic.'
      if (msg.includes('rate limit'))     msg = 'API rate limit reached. Please wait 30 seconds and try again.'
      if (msg.includes('Cannot reach'))   msg = 'Cannot reach backend. Check that the server is running on port 8000.'

      setError(msg)
    } finally {
      setLoading(false)
      submitRef.current = false   // unlock
    }
  }

  // ── Query hint click ───────────────────────────────────────────
  const applyHint = (text) => {
    setInput(text)
    inputRef.current?.focus()
  }

  /* ─────────────────────────────────────────────────────────────
     RENDER
  ───────────────────────────────────────────────────────────── */
  return (
    <>
      <div className="flex h-full overflow-hidden">

        {/* ── Document sidebar ──────────────────────────────────── */}
        <div
          className="w-72 flex-shrink-0 flex flex-col overflow-hidden"
          style={{ background: 'rgba(8,12,20,.5)', borderRight: '1px solid var(--border)' }}
        >
          {/* Header */}
          <div className="px-4 pt-6 pb-3">
            <div className="flex items-center justify-between">
              <p className="heading-sm">Documents</p>
              <span className="badge badge-sapphire">{documents.length} indexed</span>
            </div>
          </div>

          {/* Upload zone */}
          <div className="px-4 pb-3">
            <DocumentUpload onUploaded={fetchDocuments} />
          </div>

          <div className="mx-4 divider mb-3" />

          {/* Document list */}
          <div className="flex-1 overflow-y-auto px-4 pb-4 space-y-2">
            <AnimatePresence>
              {documents.length === 0 ? (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="flex flex-col items-center justify-center py-12 gap-4 text-center"
                >
                  <div
                    className="w-12 h-12 rounded-2xl flex items-center justify-center"
                    style={{
                      background: 'rgba(255,255,255,.03)',
                      border: '1px dashed rgba(255,255,255,.12)',
                    }}
                  >
                    <Upload size={18} style={{ color: 'var(--text-dim)' }} />
                  </div>
                  <div>
                    <p className="text-sm font-medium" style={{ color: 'var(--text-muted)' }}>
                      No documents yet
                    </p>
                    <p className="text-xs mt-1" style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
                      Upload a PDF to begin
                    </p>
                  </div>
                </motion.div>
              ) : (
                documents.map(doc => (
                  <DocItem
                    key={doc.filename}
                    doc={doc}
                    onDelete={handleDelete}
                  />
                ))
              )}
            </AnimatePresence>
          </div>
        </div>

        {/* ── Chat panel ─────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden min-w-0">

          {/* Top bar */}
          <div
            className="flex items-center justify-between px-6 py-4 flex-shrink-0 flex-wrap gap-2"
            style={{
              background: 'rgba(8,12,20,.75)',
              borderBottom: '1px solid var(--border)',
              backdropFilter: 'blur(12px)',
            }}
          >
            <div>
              <h1
                className="text-xl font-semibold"
                style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}
              >
                Research Assistant
              </h1>
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Hybrid RAG · BM25 + Semantic · Cross-encoder reranking
              </p>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              {/* Query type badge — shows last detected mode */}
              <AnimatePresence mode="wait">
                {lastQueryType && (
                  <QueryTypeBadge key={lastQueryType} queryType={lastQueryType} />
                )}
              </AnimatePresence>
              <span className="badge badge-sapphire">llama3-8b</span>
              <span className="badge badge-lavender">bge-small-en</span>
              <span className="badge badge-emerald">
                <span
                  className="w-1.5 h-1.5 rounded-full inline-block"
                  style={{ background: 'var(--emerald)', boxShadow: '0 0 5px rgba(62,207,142,.7)' }}
                />
                Live
              </span>
            </div>
          </div>

          {/* Messages + empty state with hints */}
          {messages.length === 0 && !isLoading ? (
            <div className="flex-1 overflow-y-auto flex flex-col items-center justify-center px-8 py-10 gap-6">
              <div
                className="rounded-2xl flex items-center justify-center"
                style={{
                  width: 64, height: 64,
                  background: 'linear-gradient(135deg, rgba(74,144,226,.2) 0%, rgba(155,135,245,.16) 100%)',
                  border: '1px solid rgba(74,144,226,.25)',
                  boxShadow: '0 0 40px rgba(74,144,226,.1)',
                }}
              >
                <Sparkles size={26} style={{ color: '#8bbef7' }} />
              </div>
              <div className="text-center">
                <h2 className="text-xl font-semibold mb-2"
                  style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}>
                  Begin Your Research Session
                </h2>
                <p className="text-sm max-w-md mx-auto"
                  style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                  Upload PDFs then ask anything — the assistant detects your intent and
                  adjusts its retrieval and generation strategy automatically.
                </p>
              </div>

              {/* Query hints */}
              <div className="w-full max-w-lg">
                <p className="heading-sm text-center mb-3">Try asking…</p>
                <div className="grid grid-cols-1 gap-2">
                  {QUERY_HINTS.map((hint, i) => {
                    const cfg  = QT_CFG[hint.type]
                    const Icon = cfg?.icon ?? Sparkles
                    return (
                      <motion.button
                        key={i}
                        initial={{ opacity: 0, x: -6 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: .1 + i * .05 }}
                        whileHover={{ x: 4 }}
                        onClick={() => applyHint(hint.text)}
                        className="flex items-center gap-3 px-4 py-3 rounded-xl text-left transition-colors"
                        style={{
                          border: '1px solid var(--border)',
                          background: 'rgba(8,12,20,.5)',
                        }}
                      >
                        <div
                          className="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0"
                          style={{ background: cfg?.bg, border: `1px solid ${cfg?.color}35` }}
                        >
                          <Icon size={12} style={{ color: cfg?.color }} />
                        </div>
                        <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>
                          {hint.text}
                        </span>
                      </motion.button>
                    )
                  })}
                </div>
              </div>
            </div>
          ) : (
            <ChatWindow />
          )}

          {/* Input bar */}
          <div
            className="px-6 py-4 flex-shrink-0"
            style={{
              background: 'rgba(8,12,20,.88)',
              borderTop: '1px solid var(--border)',
              backdropFilter: 'blur(16px)',
            }}
          >
            <div className="flex gap-3 items-end max-w-4xl mx-auto">
              <div className="flex-1 relative">
                <textarea
                  ref={inputRef}
                  value={input}
                  onChange={e => {
                    setInput(e.target.value)
                    e.target.style.height = 'auto'
                    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
                  }}
                  onKeyDown={e => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault()
                      submit()
                    }
                  }}
                  placeholder={
                    !backendReady
                      ? 'Waiting for backend…'
                      : 'Ask a question, request a summary, generate revision notes…'
                  }
                  rows={1}
                  disabled={isLoading || !backendReady}
                  className="nx-input resize-none overflow-hidden"
                  style={{ minHeight: '52px', maxHeight: '160px', lineHeight: '1.6' }}
                />
              </div>
              <motion.button
                whileHover={{ scale: 1.03 }}
                whileTap={{ scale: .95 }}
                onClick={submit}
                disabled={isLoading || !input.trim() || !backendReady}
                className="btn btn-primary flex-shrink-0 px-6"
                style={{ height: '52px' }}
              >
                {isLoading
                  ? <Loader2 size={17} className="animate-spin" />
                  : <><Send size={16} /><span>Send</span></>
                }
              </motion.button>
            </div>
            <p className="text-center text-xs mt-2"
              style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}>
              Enter to send · Shift+Enter for newline · Auto-detects: QA · Summary · Notes · Table · Guide
            </p>
          </div>
        </div>
      </div>

      {/* Global toast notifications */}
      <ToastContainer />
    </>
  )
}