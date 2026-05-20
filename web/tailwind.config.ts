import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#102a43',
        paper: '#f6faff',
        moss: '#2563eb',
        copper: '#0ea5e9',
        slateblue: '#334e68'
      },
      fontFamily: {
        display: ['Georgia', 'Cambria', 'serif'],
        body: ['Alegreya Sans', 'Trebuchet MS', 'sans-serif']
      },
      boxShadow: {
        panel: '0 20px 55px rgba(37, 99, 235, 0.12)'
      }
    },
  },
  plugins: [],
} satisfies Config
