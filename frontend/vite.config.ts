import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    allowedHosts: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // The browser talks only to Vite's same-origin preview URL. Normalize
        // the development Origin before forwarding to the API's explicit CORS
        // allowlist; this also works behind remote preview proxies.
        headers: { origin: 'http://localhost:5173' },
      },
    },
  },
})
