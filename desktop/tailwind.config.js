/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          bg: '#0d1117',
          card: '#161b22',
          inner: '#21262d',
          border: '#30363d',
          green: '#3fb950',
          red: '#f85149',
          blue: '#58a6ff',
          purple: '#bc8cff',
          gold: '#d29922',
        }
      }
    },
  },
  plugins: [],
}
