import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies /api/* to the FastAPI backend on :8000.
// host: true makes Vite listen on 0.0.0.0 so a phone on the same Wi-Fi can
// load the app from the laptop's LAN IP (needed for the Capacitor Android
// build with live reload).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
