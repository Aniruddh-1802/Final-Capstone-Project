import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server on :5173 (the origin the API's CORS list allows). /api is proxied to FastAPI and the prefix is stripped,
// so the browser sees one origin; VITE_API_BASE_URL can point the app at a different API instead.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',  // Node 24 resolves "localhost" to IPv6 (::1) only, which 127.0.0.1 clients cannot reach
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true, rewrite: (path) => path.replace(/^\/api/, '') },
    },
  },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.js', globals: true, css: false },
})
