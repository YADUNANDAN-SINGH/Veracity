import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // VITE_BACKEND_URL lets Docker point the proxy at the `backend` service;
  // locally it defaults to FastAPI on :8000.
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.VITE_BACKEND_URL || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      port: 5173,
      host: true, // listen on 0.0.0.0 so the dev container is reachable
      // Forward REST and WebSocket calls to FastAPI, so the app uses relative URLs
      proxy: {
        '/api': { target: backend, changeOrigin: true },
        '/ws': { target: backend, ws: true, changeOrigin: true },
      },
    },
  }
})
