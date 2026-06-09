import React from 'react'
import { motion } from 'framer-motion'

const TIERS = [
  { min: 0.75, label: 'High',   color: 'var(--emerald)', glow: 'rgba(62,207,142,.45)'  },
  { min: 0.45, label: 'Medium', color: 'var(--amber)',   glow: 'rgba(224,156,67,.45)'  },
  { min: 0,    label: 'Low',    color: 'var(--rose)',    glow: 'rgba(226,92,106,.45)'  },
]

export default function ConfidenceMeter({ score, className = '' }) {
  if (score == null) return null
  const pct  = Math.round(score * 100)
  const tier = TIERS.find(t => score >= t.min) ?? TIERS[2]

  return (
    <div className={`flex items-center gap-3 ${className}`}>
      {/* Tier label */}
      <span
        className="text-xs uppercase tracking-widest flex-shrink-0 w-14 text-right tabular-nums"
        style={{ color: tier.color, fontFamily: 'var(--font-mono)' }}
      >
        {tier.label}
      </span>

      {/* Progress track */}
      <div
        className="flex-1 rounded-full overflow-hidden"
        style={{ height: 4, background: 'rgba(255,255,255,.07)' }}
      >
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: .75, ease: 'easeOut' }}
          className="h-full rounded-full"
          style={{ background: tier.color, boxShadow: `0 0 7px ${tier.glow}` }}
        />
      </div>

      {/* Numeric value */}
      <span
        className="text-xs flex-shrink-0 tabular-nums w-9 text-right"
        style={{ color: tier.color, fontFamily: 'var(--font-mono)' }}
      >
        {pct}%
      </span>
    </div>
  )
}