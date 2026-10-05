import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: {
    '/api': { target: process.env.VITE_API_TARGET ?? 'http://localhost:4000', changeOrigin: true },
    '/assistant': { target: process.env.VITE_ASSISTANT_TARGET ?? 'http://localhost:8100', changeOrigin: true },
  } },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], globals: true, css: false },
});
