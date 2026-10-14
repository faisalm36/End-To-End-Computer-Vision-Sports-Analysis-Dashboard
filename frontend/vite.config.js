import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The backend's CORS allow-list includes http://localhost:5173, so keep the
  // dev server there and fail loudly instead of silently moving to 5174.
  server: { port: 5173, strictPort: true },
  // Vitest (npm test): jsdom + React Testing Library, fetch/XHR mocked in src/test/.
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
    include: ['src/**/*.test.{js,jsx}'],
    restoreMocks: true,
    testTimeout: 10000,
  },
})
