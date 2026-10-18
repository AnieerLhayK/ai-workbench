import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './', plugins: [react()],
  build: { outDir: '../../src/ai_workbench/e_chatter/web', emptyOutDir: true, target: 'chrome120' },
  server: { host: '127.0.0.1' },
});
