import { execSync } from 'node:child_process'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Stamped into the bundle at build time so the page can say which commit it
// was built from. Paired with the API reporting its own commit, that catches
// the case this project has hit twice: a freshly built frontend talking to an
// API still running older code.
const buildCommit = (() => {
  try {
    return execSync('git rev-parse --short HEAD').toString().trim()
  } catch {
    return 'unknown'
  }
})()

export default defineConfig({
  define: {
    __BUILD_COMMIT__: JSON.stringify(buildCommit),
  },
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
