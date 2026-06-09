import React, { useEffect, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useChatStore } from '../store/chatStore'
import CitationBadge from './CitationBadge'
import ConfidenceMeter from './ConfidenceMeter'
import {
  AlertCircle,
  Layers,
  Sparkles,
  ChevronRight,
} from 'lucide-react'

/* ── Typing indicator ────────────────────────────────────────────── */
function TypingIndicator() {
  return (
    <div className="flex items-center gap-2.5 px-5 py-4">
      <div className="flex gap-1.5 items-center">
        {[0, 1, 2].map(i => (
          <motion.span
            key={i}
            className="block rounded-full"
            style={{ width: 6, height: 6, background: 'var(--sapphire)' }}
            animate={{ y: [0, -5, 0], opacity: [.4, 1, .4] }}
            transition={{ duration: .8, repeat: Infinity, delay: i * .18, ease: 'easeInOut' }}
          />
        ))}
      </div>
      <span
        className="text-xs"
        style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
      >
        Reasoning & retrieving…
      </span>
    </div>
  )
}

/* ── Empty / welcome state ───────────────────────────────────────── */
const HINTS = [
  'Summarise the key findings across all uploaded documents.',
  'What methodology was used in the research?',
  'Compare and contrast conclusions across papers.',
  'What limitations do the authors acknowledge?',
  'Identify the main contributions of this work.',
]

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-8 px-8 py-14">

      {/* Animated icon */}
      <motion.div
        initial={{ scale: .8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: .5, ease: [0.34, 1.56, 0.64, 1] }}
        className="relative float"
      >
        <div
          className="rounded-2xl flex items-center justify-center noise"
          style={{
            width: 72, height: 72,
            background: 'linear-gradient(135deg, rgba(74,144,226,.22) 0%, rgba(155,135,245,.18) 100%)',
            border: '1px solid rgba(74,144,226,.28)',
            boxShadow: '0 0 48px rgba(74,144,226,.12)',
          }}
        >
          <Sparkles size={30} style={{ color: '#8bbef7', position: 'relative', zIndex: 1 }} />
        </div>

        {/* Orbiting gold dot */}
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 6, repeat: Infinity, ease: 'linear' }}
          className="absolute inset-0"
          style={{ pointerEvents: 'none' }}
        >
          <div
            className="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-1 rounded-full"
            style={{ width: 10, height: 10, background: 'var(--gold)', boxShadow: '0 0 10px rgba(201,168,76,.8)' }}
          />
        </motion.div>
      </motion.div>

      {/* Heading */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: .15, duration: .4 }}
        className="text-center"
      >
        <h2
          className="text-xl font-semibold mb-2"
          style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-serif)' }}
        >
          Begin Your Research Session
        </h2>
        <p
          className="text-sm max-w-sm leading-relaxed mx-auto"
          style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
        >
          Upload research PDFs, then ask anything. NexusIQ retrieves,
          reranks and cites every claim from your documents.
        </p>
      </motion.div>

      {/* Suggestion chips */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: .28, duration: .4 }}
        className="w-full max-w-lg space-y-2"
      >
        <p className="heading-sm text-center mb-3">Suggested Queries</p>
        {HINTS.map((h, i) => (
          <motion.div
            key={i}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: .35 + i * .06 }}
            whileHover={{ x: 5, borderColor: 'rgba(74,144,226,.3)' }}
            className="flex items-start gap-3 px-4 py-3 rounded-xl cursor-default"
            style={{ border: '1px solid var(--border)', background: 'rgba(8,12,20,.5)' }}
          >
            <ChevronRight size={14} style={{ color: 'var(--sapphire)', marginTop: 2, flexShrink: 0 }} />
            <span className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              {h}
            </span>
          </motion.div>
        ))}
      </motion.div>
    </div>
  )
}

/* ── NexusIQ assistant avatar ────────────────────────────────────── */
function NxAvatar() {
  return (
    <div
      className="rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5"
      style={{
        width: 32, height: 32,
        background: 'linear-gradient(135deg, rgba(74,144,226,.38) 0%, rgba(155,135,245,.32) 100%)',
        border: '1px solid rgba(74,144,226,.32)',
        boxShadow: '0 0 14px rgba(74,144,226,.18)',
      }}
    >
      <Sparkles size={14} style={{ color: '#8bbef7' }} />
    </div>
  )
}

/* ── Message bubble ──────────────────────────────────────────────── */
function MessageBubble({ msg }) {
  const isUser = msg.role === 'user'

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: .25, ease: [0.4, 0, 0.2, 1] }}
      className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}
    >
      {!isUser && <NxAvatar />}

      <div className={`min-w-0 ${isUser ? 'max-w-[72%]' : 'max-w-[80%]'}`}>

        {/* Chat bubble */}
        <div
          className="rounded-2xl px-5 py-4"
          style={isUser ? {
            background: 'linear-gradient(135deg, rgba(45,106,191,.78) 0%, rgba(37,82,147,.82) 100%)',
            border: '1px solid rgba(74,144,226,.3)',
            borderBottomRightRadius: 6,
            boxShadow: '0 4px 20px rgba(45,106,191,.2)',
          } : {
            background: 'linear-gradient(145deg, rgba(16,24,42,.93) 0%, rgba(12,19,34,.96) 100%)',
            border: '1px solid var(--border-md)',
            borderTopLeftRadius: 6,
            boxShadow: 'var(--shadow-card)',
          }}
        >
          {isUser ? (
            <p className="text-sm leading-relaxed" style={{ color: '#e8f0fc' }}>
              {msg.content}
            </p>
          ) : (
            <div className="prose-nx">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {/* Source citations */}
        {!isUser && msg.citations?.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 mt-3 px-1">
            <span
              className="text-xs uppercase tracking-widest"
              style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
            >
              Sources ·
            </span>
            {msg.citations.map((c, i) => (
              <CitationBadge key={i} citation={c} index={i + 1} />
            ))}
          </div>
        )}

        {/* Confidence + metadata */}
        {!isUser && msg.confidence_score != null && (
          <div className="mt-3 px-1 space-y-2">
            <ConfidenceMeter score={msg.confidence_score} />

            {msg.rewritten_query && msg.rewritten_query !== msg.content && (
              <div
                className="flex items-center gap-2 px-3 py-2 rounded-lg"
                style={{ background: 'rgba(155,135,245,.06)', border: '1px solid rgba(155,135,245,.15)' }}
              >
                <span
                  className="text-xs uppercase tracking-widest flex-shrink-0"
                  style={{ color: 'var(--lavender)', fontFamily: 'var(--font-mono)' }}
                >
                  Rewritten
                </span>
                <span
                  className="text-xs truncate"
                  style={{ color: '#c0b5f5', fontFamily: 'var(--font-mono)' }}
                >
                  "{msg.rewritten_query}"
                </span>
              </div>
            )}

            {msg.sub_queries?.length > 0 && (
              <details className="cursor-pointer">
                <summary
                  className="flex items-center gap-1.5 list-none select-none text-xs"
                  style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
                >
                  <Layers size={11} style={{ color: 'var(--text-dim)' }} />
                  {msg.sub_queries.length} sub-queries expanded
                </summary>
                <div
                  className="mt-2 space-y-1 pl-4 border-l"
                  style={{ borderColor: 'var(--border)' }}
                >
                  {msg.sub_queries.map((q, i) => (
                    <p
                      key={i}
                      className="text-xs"
                      style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
                    >
                      · {q}
                    </p>
                  ))}
                </div>
              </details>
            )}
          </div>
        )}

        {/* Timestamp */}
        <p
          className={`text-xs mt-2 px-1 ${isUser ? 'text-right' : ''}`}
          style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
        >
          {new Date(msg.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
        </p>
      </div>
    </motion.div>
  )
}

/* ── Error banner ────────────────────────────────────────────────── */
function ErrorBanner({ error }) {
  if (!error) return null
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex items-center gap-3 px-5 py-3 mx-4 rounded-xl"
      style={{ background: 'rgba(226,92,106,.07)', border: '1px solid rgba(226,92,106,.25)' }}
    >
      <AlertCircle size={15} style={{ color: 'var(--rose)', flexShrink: 0 }} />
      <p className="text-sm" style={{ color: 'var(--rose)', fontFamily: 'var(--font-mono)' }}>
        {error}
      </p>
    </motion.div>
  )
}

/* ── Main ChatWindow component ───────────────────────────────────── */
export default function ChatWindow() {
  const { messages, isLoading, error } = useChatStore()
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isLoading])

  if (messages.length === 0 && !isLoading) {
    return (
      <div className="flex-1 overflow-y-auto">
        <EmptyState />
      </div>
    )
  }

  return (
    <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
      <AnimatePresence initial={false}>
        {messages.map(msg => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
      </AnimatePresence>

      <ErrorBanner error={error} />

      {isLoading && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex gap-3 justify-start"
        >
          <NxAvatar />
          <div
            className="rounded-2xl"
            style={{
              background: 'linear-gradient(145deg, rgba(16,24,42,.92) 0%, rgba(12,19,34,.95) 100%)',
              border: '1px solid var(--border-md)',
              borderTopLeftRadius: 6,
              boxShadow: 'var(--shadow-card)',
            }}
          >
            <TypingIndicator />
          </div>
        </motion.div>
      )}

      <div ref={bottomRef} />
    </div>
  )
}