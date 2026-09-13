import { svelte } from '@sveltejs/vite-plugin-svelte';
import { defineConfig } from 'vite';

// Builds into ../static/marea, served by FastAPI's StaticFiles mount at
// /marea (app/main.py) — the same pattern static/voice/ already uses for
// /voice-ui, so both can coexist until /marea reaches parity (Fase 4 plan).
export default defineConfig({
  plugins: [svelte()],
  base: '/marea/',
  build: {
    outDir: '../static/marea',
    emptyOutDir: true,
  },
  server: {
    // Local dev proxy so `npm run dev` can hit the FastAPI server without
    // CORS config — same-origin API_BASE assumption as static/voice/app.js.
    proxy: {
      '/agent': 'http://localhost:8000',
      '/interactions': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
      '/voice': 'http://localhost:8000',
      '/sync': 'http://localhost:8000',
      '/briefing': 'http://localhost:8000',
      '/commitments': 'http://localhost:8000',
    },
  },
});
