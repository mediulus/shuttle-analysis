import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // MapLibre ships its own web worker; keep it out of Vite's dep pre-bundling.
  optimizeDeps: { exclude: ['maplibre-gl'] },
});
