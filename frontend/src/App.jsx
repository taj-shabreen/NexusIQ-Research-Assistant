import React, { useEffect } from 'react'
import { BrowserRouter, Routes, Route, useLocation } from 'react-router-dom'
import Layout from './components/Layout'
import ResearchPage from './pages/ResearchPage'
import EvaluationPage from './pages/EvaluationPage'
import DebugPage from './pages/DebugPage'

/* ─────────────────────────────────────────────────────────────────
   GOOGLE ANALYTICS 4 — PAGE VIEW TRACKER
   Fires on every route change. Only active in production
   (non-localhost) and when a GA ID is configured.
───────────────────────────────────────────────────────────────── */

/** Load the GA4 gtag script once. */
function loadGtag(measurementId) {
  if (typeof window === 'undefined') return
  if (window.__gtag_loaded__) return
  window.__gtag_loaded__ = true

  const script = document.createElement('script')
  script.async = true
  script.src   = `https://www.googletagmanager.com/gtag/js?id=${measurementId}`
  document.head.appendChild(script)

  window.dataLayer = window.dataLayer || []
  window.gtag      = function () { window.dataLayer.push(arguments) }
  window.gtag('js', new Date())
  window.gtag('config', measurementId, {
    send_page_view: false,   // we send manually on route change
  })
}

/** Send a page_view event to GA4. */
function trackPageView(path, measurementId) {
  if (typeof window?.gtag !== 'function') return
  window.gtag('event', 'page_view', {
    page_path:  path,
    page_title: document.title,
    send_to:    measurementId,
  })
}

/** Hook: initialise GA4 once and track route changes. */
function useAnalytics() {
  const location = useLocation()

  // Resolve GA ID: from Vite env var or from index.html injection
  const gaId = (
    import.meta.env.VITE_GA_ID ||
    (typeof window !== 'undefined' ? window.__GA_ID__ : '')
  )?.trim()

  const isProd = typeof window !== 'undefined'
    ? (window.location.hostname !== 'localhost'
       && window.location.hostname !== '127.0.0.1')
    : false

  // Initialise GA4 on first render
  useEffect(() => {
    if (!gaId || gaId === '%VITE_GA_ID%' || !isProd) return
    loadGtag(gaId)
  }, [gaId, isProd])

  // Fire page_view on every route change
  useEffect(() => {
    if (!gaId || gaId === '%VITE_GA_ID%' || !isProd) return
    trackPageView(location.pathname + location.search, gaId)
  }, [location, gaId, isProd])
}

/* ─────────────────────────────────────────────────────────────────
   ANALYTICS WRAPPER — must be inside BrowserRouter to use useLocation
───────────────────────────────────────────────────────────────── */
function AnalyticsProvider({ children }) {
  useAnalytics()
  return children
}

/* ─────────────────────────────────────────────────────────────────
   ROOT APP
───────────────────────────────────────────────────────────────── */
export default function App() {
  return (
    <BrowserRouter>
      <AnalyticsProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/"           element={<ResearchPage />}   />
            <Route path="/evaluation" element={<EvaluationPage />} />
            <Route path="/debug"      element={<DebugPage />}      />
          </Route>
        </Routes>
      </AnalyticsProvider>
    </BrowserRouter>
  )
}