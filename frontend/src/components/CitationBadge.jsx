import React, { useState, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { FileText } from 'lucide-react'

export default function CitationBadge({ citation, index }) {
  const [open, setOpen] = useState(false)
  const ref             = useRef(null)
  const relevance       = Math.round((citation.relevance_score ?? 0) * 100)

  const tier =
    relevance >= 75
      ? { color: 'var(--emerald)', border: 'rgba(62,207,142,.35)',  bg: 'rgba(62,207,142,.09)'  }
      : relevance >= 48
      ? { color: 'var(--amber)',   border: 'rgba(224,156,67,.35)',  bg: 'rgba(224,156,67,.09)'  }
      : { color: 'var(--rose)',    border: 'rgba(226,92,106,.35)',  bg: 'rgba(226,92,106,.09)'  }

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative inline-block">

      {/* Citation chip */}
      <motion.button
        whileHover={{ scale: 1.1, y: -1 }}
        whileTap={{ scale: .93 }}
        onClick={() => setOpen(v => !v)}
        className="inline-flex items-center cursor-pointer rounded-full"
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '11px',
          letterSpacing: '.03em',
          padding: '3px 10px',
          border: `1px solid ${open ? 'rgba(74,144,226,.55)' : 'rgba(74,144,226,.28)'}`,
          background: open ? 'rgba(74,144,226,.16)' : 'rgba(74,144,226,.07)',
          color: open ? '#8bbef7' : 'rgba(139,190,247,.8)',
          boxShadow: open ? '0 0 12px rgba(74,144,226,.25)' : 'none',
          transition: 'all .16s ease',
        }}
      >
        <span style={{ opacity: .5 }}>[</span>
        {index}
        <span style={{ opacity: .5 }}>]</span>
      </motion.button>

      {/* Popover panel */}
      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: 10, scale: .96 }}
            animate={{ opacity: 1, y: 0,  scale: 1    }}
            exit={  { opacity: 0, y: 6,   scale: .97  }}
            transition={{ duration: .16, ease: 'easeOut' }}
            className="absolute z-50 bottom-full mb-3 left-0"
            style={{
              minWidth: 300,
              filter: 'drop-shadow(0 20px 48px rgba(0,0,0,.7))',
            }}
          >
            <div
              className="relative p-4 rounded-2xl overflow-hidden"
              style={{
                background: 'linear-gradient(145deg, rgba(16,24,44,.98) 0%, rgba(10,16,30,.99) 100%)',
                border: '1px solid var(--border-md)',
                backdropFilter: 'blur(24px)',
              }}
            >
              {/* Top shimmer accent */}
              <div
                className="absolute top-0 left-6 right-6 h-px"
                style={{
                  background: 'linear-gradient(90deg, transparent, rgba(74,144,226,.55), transparent)',
                }}
              />

              {/* Header row */}
              <div className="flex items-start gap-3 mb-3">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{
                    background: 'rgba(74,144,226,.12)',
                    border: '1px solid rgba(74,144,226,.22)',
                  }}
                >
                  <FileText size={14} style={{ color: '#8bbef7' }} />
                </div>

                <div className="flex-1 min-w-0">
                  <p
                    className="text-sm font-medium truncate"
                    style={{ color: 'var(--text-primary)', maxWidth: 180 }}
                  >
                    {citation.filename}
                  </p>
                  <p
                    className="text-xs mt-0.5"
                    style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}
                  >
                    Page {citation.page}
                  </p>
                </div>

                {/* Relevance badge */}
                <div
                  className="flex-shrink-0 flex flex-col items-center rounded-xl px-3 py-1.5"
                  style={{ background: tier.bg, border: `1px solid ${tier.border}` }}
                >
                  <span
                    className="text-base font-bold leading-none tabular-nums"
                    style={{ color: tier.color, fontFamily: 'var(--font-serif)' }}
                  >
                    {relevance}
                  </span>
                  <span
                    className="text-xs mt-0.5"
                    style={{ color: tier.color, opacity: .75, letterSpacing: '.06em', fontFamily: 'var(--font-mono)' }}
                  >
                    REL%
                  </span>
                </div>
              </div>

              <div className="divider mb-3" />

              {/* Relevance bar */}
              <div className="mb-3">
                <div className="flex items-center justify-between mb-1.5">
                  <span
                    className="text-xs uppercase tracking-widest"
                    style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
                  >
                    Relevance Score
                  </span>
                  <span
                    className="text-xs tabular-nums"
                    style={{ color: tier.color, fontFamily: 'var(--font-mono)' }}
                  >
                    {relevance}%
                  </span>
                </div>
                <div
                  className="rounded-full overflow-hidden"
                  style={{ height: 5, background: 'var(--ink-700)' }}
                >
                  <motion.div
                    initial={{ width: 0 }}
                    animate={{ width: `${relevance}%` }}
                    transition={{ duration: .55, ease: 'easeOut' }}
                    className="h-full rounded-full"
                    style={{ background: tier.color, boxShadow: `0 0 7px ${tier.color}55` }}
                  />
                </div>
              </div>

              {/* Chunk text preview */}
              <p
                className="text-sm leading-relaxed clamp-5"
                style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}
              >
                {citation.chunk_text}
              </p>

              {/* Doc ID footer */}
              <div
                className="mt-3 pt-2.5"
                style={{ borderTop: '1px solid var(--border)' }}
              >
                <span
                  className="text-xs"
                  style={{ color: 'var(--text-dim)', fontFamily: 'var(--font-mono)' }}
                >
                  doc_id: {citation.document_id}
                </span>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}