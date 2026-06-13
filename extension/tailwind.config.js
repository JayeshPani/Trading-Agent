/** @type {import('tailwindcss').Config} */
export default {
  content: ["./src/**/*.{ts,tsx,html}"],
  theme: {
    extend: {
      colors: {
        ink: "#17201b",
        panel: "#f7f8f5",
        accent: "#1f7a5a",
        danger: "#b42318",
        warning: "#b54708"
      }
    }
  },
  plugins: []
};
