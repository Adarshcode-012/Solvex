/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      colors: {
        bg:       '#08090e',
        surface:  '#0f1117',
        surface2: '#161821',
        surface3: '#1e2030',
        border:   '#252738',
        border2:  '#2f3347',
        accent:   '#818cf8',
        green:    '#34d399',
        red:      '#f87171',
        yellow:   '#fbbf24',
        blue:     '#60a5fa',
        purple:   '#c084fc',
        dim:      '#4a4d63',
        mid:      '#8b8fa8',
      },
      animation: {
        'pulse-slow': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'blink': 'blink 1.2s ease-in-out infinite',
      },
      keyframes: {
        blink: {
          '0%, 80%, 100%': { opacity: '0.2', transform: 'scale(0.7)' },
          '40%':            { opacity: '1',   transform: 'scale(1)' },
        },
      },
    },
  },
  plugins: [],
}
