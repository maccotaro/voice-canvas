/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0b0d17', panel: '#141728', panel2: '#1b1f36', line: '#2a2f4d',
        accent: '#7c5cff', accent2: '#27e0c4', sub: '#9aa0c0',
      },
    },
  },
  plugins: [],
};
