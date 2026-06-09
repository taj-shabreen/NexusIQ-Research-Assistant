import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * NexusIQ — vite.config.js
 *
 * Production-ready Vite configuration.
 *
 * Environment variables:
 *   VITE_API_URL      — backend URL (default: http://127.0.0.1:8000)
 *   VITE_GA_ID        — Google Analytics measurement ID (optional)
 *   VITE_APP_VERSION  — app version string (optional)
 *
 * Deployment targets:
 *   Vercel  — set VITE_API_URL to your Render backend URL
 *   Render  — static site build from /frontend
 *   Local   — proxy /api → localhost:8000
 */
export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const apiUrl = env.VITE_API_URL || 'http://127.0.0.1:8000'
  const isProd = mode === 'production'

  return {
    plugins: [react()],

    // ── Dev server ─────────────────────────────────────────────────
    server: {
      port: 5173,
      host: true,   // listen on 0.0.0.0 for Docker/codespaces
      proxy: {
        '/api': {
          target:       apiUrl,
          changeOrigin: true,
          rewrite:      (path) => path,
        },
        '/health': {
          target:       apiUrl,
          changeOrigin: true,
        },
        '/ready': {
          target:       apiUrl,
          changeOrigin: true,
        },
      },
    },

    // ── Build ──────────────────────────────────────────────────────
    build: {
      outDir:         'dist',
      sourcemap:      !isProd,          // source maps in dev/staging, not prod
      minify:         isProd ? 'esbuild' : false,
      chunkSizeWarningLimit: 600,

      rollupOptions: {
        output: {
          // Split vendor chunks for better caching
          manualChunks: {
            'vendor-react':    ['react', 'react-dom', 'react-router-dom'],
            'vendor-motion':   ['framer-motion'],
            'vendor-charts':   ['recharts'],
            'vendor-markdown': ['react-markdown', 'remark-gfm'],
            'vendor-misc':     ['axios', 'zustand', 'lucide-react'],
          },
        },
      },
    },

    // ── Preview server (after build) ───────────────────────────────
    preview: {
      port: 4173,
      host: true,
      proxy: {
        '/api': {
          target:       apiUrl,
          changeOrigin: true,
        },
        '/health': { target: apiUrl, changeOrigin: true },
        '/ready':  { target: apiUrl, changeOrigin: true },
      },
    },

    // ── Global constants injected at build time ────────────────────
    define: {
      __APP_VERSION__: JSON.stringify(env.VITE_APP_VERSION || '1.0.0'),
      __BUILD_TIME__:  JSON.stringify(new Date().toISOString()),
    },
  }
})