/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,ts,jsx,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          950: '#080c14',
          900: '#0d1320',
          800: '#121a2e',
          700: '#182236',
          600: '#1e2d45',
          500: '#253553',
          400: '#334466',
        },
        stone: {
          600: '#3a4a60',
          500: '#4a5e78',
          400: '#617590',
          300: '#7d93ac',
          200: '#a0b3c8',
          100: '#c8d8e8',
        },
        gold: {
          DEFAULT: '#c9a84c',
          light:   '#e4c77a',
          dark:    '#b8962a',
        },
        sapphire: {
          DEFAULT: '#4a90e2',
          dim:     '#2d6abf',
          light:   '#8bbef7',
        },
        nexus: {
          emerald:  '#3ecf8e',
          rose:     '#e25c6a',
          amber:    '#e09c43',
          lavender: '#9b87f5',
        },
      },
      fontFamily: {
        serif: ['Playfair Display', 'Georgia', 'serif'],
        sans:  ['Outfit', 'system-ui', 'sans-serif'],
        mono:  ['JetBrains Mono', 'monospace'],
      },
      borderRadius: {
        '2xl': '16px',
        '3xl': '20px',
        '4xl': '24px',
      },
      boxShadow: {
        'card':    '0 4px 24px rgba(0,0,0,.35), 0 1px 4px rgba(0,0,0,.2)',
        'glow-sm': '0 0 12px rgba(74,144,226,.25)',
        'glow-md': '0 0 24px rgba(74,144,226,.3)',
        'gold-sm': '0 0 12px rgba(201,168,76,.2)',
        'gold-md': '0 0 28px rgba(201,168,76,.25)',
      },
      backgroundImage: {
        'gradient-radial': 'radial-gradient(var(--tw-gradient-stops))',
        'gradient-conic':  'conic-gradient(from 180deg at 50% 50%, var(--tw-gradient-stops))',
        'shimmer': 'linear-gradient(90deg, transparent 0%, rgba(255,255,255,.06) 50%, transparent 100%)',
      },
      animation: {
        'shimmer':    'shimmer 1.8s ease-in-out infinite',
        'float':      'float-gentle 5s ease-in-out infinite',
        'spin-slow':  'spin-slow 12s linear infinite',
        'pulse-ring': 'pulse-ring 2s ease-in-out infinite',
        'blink':      'blink-cursor 1.1s step-end infinite',
      },
      keyframes: {
        shimmer: {
          '0%':   { backgroundPosition: '-800px 0' },
          '100%': { backgroundPosition: '800px 0' },
        },
        'float-gentle': {
          '0%, 100%': { transform: 'translateY(0) rotate(0deg)' },
          '50%':       { transform: 'translateY(-6px) rotate(.5deg)' },
        },
        'spin-slow': {
          to: { transform: 'rotate(360deg)' },
        },
        'pulse-ring': {
          '0%, 100%': { opacity: '.6', transform: 'scale(1)' },
          '50%':       { opacity: '1',  transform: 'scale(1.08)' },
        },
        'blink-cursor': {
          '0%, 100%': { opacity: '1' },
          '50%':       { opacity: '0' },
        },
      },
      spacing: {
        '18': '4.5rem',
        '22': '5.5rem',
        '26': '6.5rem',
        '30': '7.5rem',
      },
      transitionTimingFunction: {
        'spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
        'smooth': 'cubic-bezier(0.4, 0, 0.2, 1)',
      },
    },
  },
  plugins: [],
}