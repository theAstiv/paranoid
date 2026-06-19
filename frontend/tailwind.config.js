/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{svelte,js}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['IBM Plex Sans', 'system-ui', 'sans-serif'],
        mono: ['IBM Plex Mono', 'Menlo', 'monospace'],
      },
      colors: {
        c: {
          bg:             '#0A0E16',
          sidebar:        '#0C111A',
          panel:          '#111722',
          panel2:         '#0F1521',
          input:          '#0C111A',
          well:           '#0C1119',
          border:         '#1E2738',
          'border-soft':  '#1A2333',
          'border-strong':'#232C3D',
          divider:        '#161E2B',
          text:           '#E7EDF5',
          text2:          '#C6D0DE',
          text3:          '#B8C2D0',
          muted:          '#7A8699',
          faint:          '#5B6779',
          faint2:         '#46505F',
          accent:         '#2BD4C0',
          'accent-deep':  '#1B9C8E',
          blue:           '#4D9CFF',
          violet:         '#C084FC',
          green:          '#3FD0A8',
          critical:       '#FB6F84',
          high:           '#FFA552',
          medium:         '#F5D04E',
          low:            '#3FD0A8',
        },
      },
      borderRadius: {
        card:  '14px',
        panel: '10px',
        chip:  '6px',
        pill:  '20px',
      },
      keyframes: {
        'spin-k':  { '0%': { transform: 'rotate(0deg)' }, '100%': { transform: 'rotate(360deg)' } },
        blink:     { '0%, 100%': { opacity: '1' }, '50%': { opacity: '0.15' } },
        pulseDot:  {
          '0%, 100%': { boxShadow: '0 0 0 0 rgba(63,208,168,0.5)' },
          '50%':      { boxShadow: '0 0 0 4px rgba(63,208,168,0)' },
        },
        popIn:     {
          '0%':   { opacity: '0', transform: 'translateY(-6px) scale(0.98)' },
          '100%': { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
      },
      animation: {
        'spin-slow': 'spin-k 0.9s linear infinite',
        blink:       'blink 1.1s steps(2, end) infinite',
        'pulse-dot': 'pulseDot 2s ease-in-out infinite',
        'pop-in':    'popIn 0.16s ease-out',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}
