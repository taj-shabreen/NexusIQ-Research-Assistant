import React, { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Outlet, NavLink, useLocation } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { Brain, BarChart2, Bug, BookOpen, Github, Loader2 } from 'lucide-react'
import { readyApi, healthApi } from '../services/api'

/* ─── Backend Context ─────────────────────────────────── */
export const BackendContext = createContext({
  backendReady: false, backendStatus: 'checking',
  subsystems: {}, model: '', embedModel: '', chunksStored: -1,
})
export function useBackend() { return useContext(BackendContext) }

const NAV = [
  { to: '/',           label: 'Research',   icon: BookOpen,  desc: 'Ask & retrieve'  },
  { to: '/evaluation', label: 'Evaluation', icon: BarChart2, desc: 'RAGAS metrics'   },
  { to: '/debug',      label: 'Debug',      icon: Bug,       desc: 'Chunk inspector' },
]

/* ─────────────────────────────────────────────────────────
   VERY SLOW SONAR — rings expand over 4 seconds each
   Staggered every 1.3s — looks like calm radar, not flicker
───────────────────────────────────────────────────────── */
function SonarRings({ color }) {
  if (!color) return null
  return (
    <>
      {[0, 1, 2].map(i => (
        <motion.div
          key={i}
          style={{
            position: 'absolute',
            inset: -2,
            borderRadius: '50%',
            backgroundColor: color,
            zIndex: 0,
            pointerEvents: 'none',
          }}
          initial={{ scale: 1, opacity: 0.5 }}
          animate={{ scale: 5.5, opacity: 0 }}
          transition={{
            duration: 4.0,        // 4 seconds per ring — very slow
            repeat: Infinity,
            ease: 'easeOut',
            delay: i * 1.3,       // 0s, 1.3s, 2.6s — calm stagger
            repeatDelay: 0.2,
          }}
        />
      ))}
    </>
  )
}

/* ─────────────────────────────────────────────────────────
   STATUS DOT — very slow breathing, no flicker
───────────────────────────────────────────────────────── */
const DOT_CFG = {
  ready:    { color: '#3ecf8e', ring: 'rgba(62,207,142,0.45)'  },
  checking: { color: '#e09c43', ring: 'rgba(224,156,67,0.45)'  },
  partial:  { color: '#e09c43', ring: 'rgba(224,156,67,0.45)'  },
  error:    { color: '#e25c6a', ring: null                      },
}

function StatusDot({ status }) {
  const cfg = DOT_CFG[status] ?? DOT_CFG.checking
  return (
    <div style={{
      position: 'relative',
      width: 18, height: 18,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      flexShrink: 0,
    }}>
      {/* Slow sonar rings */}
      <SonarRings color={cfg.ring} />
      {/* Center dot — very slow smooth breathe, NO rapid blink */}
      <motion.div
        style={{
          width: 10, height: 10,
          borderRadius: '50%',
          backgroundColor: cfg.color,
          boxShadow: `0 0 6px ${cfg.color}bb, 0 0 14px ${cfg.color}44`,
          position: 'relative', zIndex: 1,
        }}
        animate={{
          scale:   [1, 1.18, 1],
          opacity: [0.88, 1, 0.88],
        }}
        transition={{
          duration: 3.2,        // 3.2 seconds — very slow, smooth
          repeat: Infinity,
          ease: 'easeInOut',
        }}
      />
    </div>
  )
}

/* ─────────────────────────────────────────────────────────
   ANIMATED BRAIN LOGO — slow glow pulse + shimmer sweep
───────────────────────────────────────────────────────── */
function BrainLogo() {
  return (
    <motion.div
      style={{
        width: 40, height: 40, borderRadius: 12, flexShrink: 0,
        background: 'linear-gradient(135deg, rgba(74,144,226,.35), rgba(155,135,245,.3))',
        border: '1px solid rgba(74,144,226,.35)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        position: 'relative', overflow: 'hidden', cursor: 'pointer',
      }}
      animate={{
        boxShadow: [
          '0 0 8px rgba(74,144,226,.2)',
          '0 0 26px rgba(74,144,226,.5)',
          '0 0 8px rgba(74,144,226,.2)',
        ],
      }}
      transition={{ duration: 3.8, repeat: Infinity, ease: 'easeInOut' }}
      whileHover={{ scale: 1.1, rotate: 8 }}
      whileTap={{ scale: 0.92 }}
    >
      {/* Light sweep every ~5 seconds */}
      <motion.div
        style={{
          position: 'absolute', top: 0, width: '40%', height: '100%',
          background: 'linear-gradient(90deg, transparent, rgba(255,255,255,.22), transparent)',
          transform: 'skewX(-15deg)',
        }}
        initial={{ left: '-60%' }}
        animate={{ left: '160%' }}
        transition={{ duration: 1.8, repeat: Infinity, repeatDelay: 3.8, ease: 'easeInOut' }}
      />
      <Brain size={20} style={{ color: '#8bbef7', position: 'relative', zIndex: 1 }} />
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────
   NAV ITEM — clean, NO orbit animation on nav icons
   Spring-pop indicator dot on the right when active
───────────────────────────────────────────────────────── */
function NavItem({ item, isActive }) {
  const Icon = item.icon
  return (
    <motion.div
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '11px 16px',
        borderRadius: '0 12px 12px 0',
        cursor: 'pointer',
        borderLeft: isActive ? '2px solid #4a90e2' : '2px solid transparent',
        background: isActive
          ? 'linear-gradient(90deg, rgba(74,144,226,.13), rgba(74,144,226,.04))'
          : 'transparent',
      }}
      whileHover={!isActive ? {
        x: 3,
        backgroundColor: 'rgba(255,255,255,.04)',
        borderLeftColor: 'rgba(255,255,255,.15)',
      } : {}}
      transition={{ duration: .2 }}
    >
      {/* Plain icon box — no orbit, no rotation */}
      <motion.div
        style={{
          width: 32, height: 32, borderRadius: 10, flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          background: isActive ? 'rgba(74,144,226,.22)' : 'rgba(255,255,255,.045)',
          border: isActive ? '1px solid rgba(74,144,226,.4)' : '1px solid rgba(255,255,255,.08)',
        }}
        animate={isActive ? {
          boxShadow: [
            '0 0 4px rgba(74,144,226,.15)',
            '0 0 14px rgba(74,144,226,.38)',
            '0 0 4px rgba(74,144,226,.15)',
          ],
        } : { boxShadow: 'none' }}
        transition={{ duration: 2.8, repeat: Infinity, ease: 'easeInOut' }}
        whileHover={{ scale: 1.08 }}
      >
        <Icon size={15} color={isActive ? '#8bbef7' : '#5d7390'} />
      </motion.div>

      {/* Labels */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <p style={{
          fontSize: 14, fontWeight: 500, margin: 0, lineHeight: 1.3,
          color: isActive ? '#e8edf4' : '#9aacbf',
          fontFamily: 'var(--font-sans)',
        }}>
          {item.label}
        </p>
        <AnimatePresence>
          {!isActive && (
            <motion.p
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: .22 }}
              style={{ fontSize: 10, color: '#3a4f66', fontFamily: 'var(--font-mono)', margin: 0, marginTop: 2 }}
            >
              {item.desc}
            </motion.p>
          )}
        </AnimatePresence>
      </div>

      {/* Spring-pop dot on right when active */}
      <AnimatePresence>
        {isActive && (
          <motion.div
            key="dot"
            initial={{ scale: 0, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 420, damping: 20 }}
            style={{
              width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
              backgroundColor: '#4a90e2',
              boxShadow: '0 0 8px rgba(74,144,226,.9)',
            }}
          />
        )}
      </AnimatePresence>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────
   STATUS CARD
───────────────────────────────────────────────────────── */
function StatusCard({ status, subsystems, model, chunksStored, attempt }) {
  const cfg     = DOT_CFG[status] ?? DOT_CFG.checking
  const isReady = status === 'ready'
  const isError = status === 'error'

  const label = {
    ready:    'Backend ready',
    checking: 'Connecting…',
    partial:  'Initialising…',
    error:    'Backend error',
  }[status] ?? 'Connecting…'

  const sub = isReady
    ? `${model || 'llama3-8b'} · ${chunksStored >= 0 ? chunksStored + ' chunks' : 'no docs'}`
    : isError ? 'Check terminal logs'
    : status === 'partial'
    ? (Object.entries(subsystems || {}).filter(([, v]) => !v).map(([k]) => k).join(', ') || 'starting') + '…'
    : `attempt ${attempt}…`

  return (
    <motion.div
      layout
      style={{
        background: 'rgba(255,255,255,.03)',
        borderRadius: 14, padding: '10px 12px', marginBottom: 14,
        border: '1px solid rgba(255,255,255,.07)',
      }}
      animate={{
        borderColor: isReady
          ? ['rgba(62,207,142,.05)', 'rgba(62,207,142,.2)', 'rgba(62,207,142,.05)']
          : isError
          ? ['rgba(226,92,106,.05)', 'rgba(226,92,106,.2)', 'rgba(226,92,106,.05)']
          : ['rgba(224,156,67,.04)', 'rgba(224,156,67,.14)', 'rgba(224,156,67,.04)'],
      }}
      transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <StatusDot status={status} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <motion.p
            key={label}
            initial={{ opacity: 0, y: 3 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: .3 }}
            style={{ fontSize: 13, fontWeight: 500, color: '#9aacbf', margin: 0, lineHeight: 1.3 }}
          >
            {label}
          </motion.p>
          <p style={{
            fontSize: 10, color: '#3a4f66', fontFamily: 'var(--font-mono)',
            margin: 0, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>
            {sub}
          </p>
        </div>
        {!isReady && !isError && (
          <Loader2 size={12} className="animate-spin" style={{ color: '#3a4f66', flexShrink: 0 }} />
        )}
      </div>
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────
   SUBSYSTEM ROWS
───────────────────────────────────────────────────────── */
function SubsystemRows({ subsystems }) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: .28 }}
      style={{ overflow: 'hidden', marginBottom: 12 }}
    >
      {Object.entries(subsystems).map(([key, ready], i) => (
        <motion.div
          key={key}
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: i * .07 }}
          style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 5, paddingLeft: 4 }}
        >
          <div style={{ position: 'relative', width: 7, height: 7, flexShrink: 0 }}>
            {!ready && (
              <motion.span
                style={{ position: 'absolute', inset: 0, borderRadius: '50%', backgroundColor: 'rgba(224,156,67,.5)' }}
                animate={{ scale: [1, 2.4, 1], opacity: [.5, 0, .5] }}
                transition={{ duration: 2.2, repeat: Infinity, ease: 'easeInOut' }}
              />
            )}
            <div style={{
              position: 'absolute', inset: 0, borderRadius: '50%', zIndex: 1,
              backgroundColor: ready ? '#3ecf8e' : '#e09c43',
              boxShadow: ready ? '0 0 4px rgba(62,207,142,.7)' : '0 0 4px rgba(224,156,67,.7)',
            }} />
          </div>
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: ready ? '#5d7390' : '#e09c43' }}>
            {key}
          </span>
          {!ready && <Loader2 size={8} className="animate-spin" style={{ color: '#e09c43', marginLeft: 'auto' }} />}
        </motion.div>
      ))}
    </motion.div>
  )
}

/* ─────────────────────────────────────────────────────────
   MAIN LAYOUT
───────────────────────────────────────────────────────── */
export default function Layout() {
  const location  = useLocation()
  const polledRef = useRef(false)

  const [backendReady,  setBackendReady]  = useState(false)
  const [backendStatus, setBackendStatus] = useState('checking')
  const [subsystems,    setSubsystems]    = useState({})
  const [model,         setModel]         = useState('')
  const [chunksStored,  setChunksStored]  = useState(-1)
  const [pollAttempt,   setPollAttempt]   = useState(0)

  useEffect(() => {
    if (polledRef.current) return
    polledRef.current = true
    readyApi.poll({
      maxAttempts: 30, intervalMs: 2_000,
      onProgress: (attempt, state) => {
        setPollAttempt(attempt)
        setSubsystems(state?.subsystems ?? {})
        const all = state?.subsystems ? Object.values(state.subsystems).every(Boolean) : false
        setBackendStatus(all ? 'ready' : 'checking')
      },
    })
    .then(data => {
      setBackendReady(true); setBackendStatus('ready')
      setSubsystems(data.subsystems ?? {}); setModel(data.model ?? '')
      healthApi.check().then(r => setChunksStored(r.data?.chunks_stored ?? -1)).catch(() => {})
    })
    .catch(() => setBackendStatus('error'))
  }, [])

  const displayStatus = (() => {
    if (backendStatus === 'error') return 'error'
    if (backendReady) return 'ready'
    if (Object.keys(subsystems).length > 0) {
      const vals = Object.values(subsystems)
      if (vals.some(Boolean) && !vals.every(Boolean)) return 'partial'
    }
    return 'checking'
  })()

  return (
    <BackendContext.Provider value={{ backendReady, backendStatus: displayStatus, subsystems, model, chunksStored }}>
      <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }} className="app-bg">
        <div className="fixed inset-0 grid-overlay pointer-events-none" style={{ zIndex: 0 }} />

        {/* SIDEBAR */}
        <motion.aside
          initial={{ x: -256, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: .5, ease: [0.22, 1, 0.36, 1] }}
          style={{
            position: 'relative', zIndex: 20, width: 256, flexShrink: 0,
            display: 'flex', flexDirection: 'column', overflow: 'hidden',
            background: 'linear-gradient(180deg, rgba(10,15,28,.98) 0%, rgba(8,12,20,.99) 100%)',
            borderRight: '1px solid rgba(255,255,255,.07)',
          }}
        >
          <div style={{
            position: 'absolute', top: 0, left: 0, width: '100%', height: 220, pointerEvents: 'none',
            background: 'radial-gradient(ellipse 140% 90% at 0% 0%, rgba(74,144,226,.09) 0%, transparent 60%)',
          }} />

          {/* Logo */}
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: .2, duration: .38 }}
            style={{ padding: '28px 20px 18px' }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <BrainLogo />
              <div>
                <h1 style={{ fontSize: 18, fontWeight: 600, color: '#e8edf4', fontFamily: 'var(--font-serif)', lineHeight: 1, margin: 0 }}>
                  NexusIQ
                </h1>
                <p style={{ fontSize: 10, color: '#3a4f66', fontFamily: 'var(--font-mono)', letterSpacing: '.09em', margin: 0, marginTop: 4 }}>
                  RESEARCH RAG
                </p>
              </div>
            </div>
            <div className="divider" style={{ marginTop: 20 }} />
          </motion.div>

          {/* Nav label */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: .28 }}
            style={{ padding: '0 20px 8px' }}
          >
            <p className="heading-sm">Navigation</p>
          </motion.div>

          {/* Nav links */}
          <nav style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '0 8px 0 0' }}>
            {NAV.map((item, i) => (
              <motion.div
                key={item.to}
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: .32 + i * .1, duration: .32, ease: [0.22, 1, 0.36, 1] }}
              >
                <NavLink to={item.to} end={item.to === '/'} style={{ textDecoration: 'none' }}>
                  {({ isActive }) => <NavItem item={item} isActive={isActive} />}
                </NavLink>
              </motion.div>
            ))}
          </nav>

          <div style={{ flex: 1 }} />

          {/* Status + footer */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: .52, duration: .35 }}
            style={{ padding: '0 16px 20px' }}
          >
            <div className="divider" style={{ marginBottom: 16 }} />
            <StatusCard status={displayStatus} subsystems={subsystems} model={model} chunksStored={chunksStored} attempt={pollAttempt} />
            <AnimatePresence>
              {(displayStatus === 'checking' || displayStatus === 'partial') && Object.keys(subsystems).length > 0 && (
                <SubsystemRows key="subsys" subsystems={subsystems} />
              )}
            </AnimatePresence>

            <div style={{ borderTop: '1px solid rgba(255,255,255,.06)', paddingTop: 12, textAlign: 'center' }}>
              <p style={{ fontFamily: 'var(--font-serif)', fontSize: 11.5, fontStyle: 'italic', color: '#3a4f66', margin: 0, marginBottom: 6 }}>
                Developed by
                <span style={{ color: '#c9a84c', margin: '0 4px' }}>✦</span>
                <motion.a
                  href="https://github.com/taj-shabreen" target="_blank" rel="noopener noreferrer"
                  style={{ color: '#e4c77a', textDecoration: 'none', fontStyle: 'italic' }}
                  whileHover={{ color: '#ffffff' }} transition={{ duration: .2 }}
                >
                  Shabreen Taj
                </motion.a>
              </p>
              <motion.a
                href="https://github.com/taj-shabreen" target="_blank" rel="noopener noreferrer"
                style={{ display: 'inline-flex', alignItems: 'center', gap: 5, color: '#3a4f66', fontFamily: 'var(--font-mono)', fontSize: 11, textDecoration: 'none' }}
                whileHover={{ color: '#8bbef7' }} transition={{ duration: .2 }}
              >
                <Github size={11} />
                github/taj-shabreen
              </motion.a>
            </div>
          </motion.div>
        </motion.aside>

        {/* MAIN */}
        <main style={{ flex: 1, overflow: 'auto', position: 'relative', zIndex: 10, minWidth: 0 }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 14, scale: 0.99 }}
              animate={{ opacity: 1, y: 0,  scale: 1    }}
              exit={  { opacity: 0, y: -8,  scale: 0.99 }}
              transition={{ duration: .3, ease: [0.22, 1, 0.36, 1] }}
              style={{ height: '100%' }}
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </BackendContext.Provider>
  )
}