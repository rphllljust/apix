/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#f4efe7',
        ink: '#1a2f2f',
        panel: '#fffaf2',
        line: '#d2c9bb',
        brand: '#0f766e',
        accent: '#c2410c',
        ok: '#14532d',
        warn: '#92400e',
        bad: '#991b1b',
      },
      borderRadius: {
        lg: '0.75rem',
        md: '0.5rem',
        sm: '0.375rem',
      },
      boxShadow: {
        paper: '0 10px 30px -16px rgba(26, 47, 47, 0.35)',
      },
    },
  },
  plugins: [],
}
