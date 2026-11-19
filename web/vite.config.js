import { defineConfig } from 'vite';

// base relativa: funciona igual en localhost y en https://<usuario>.github.io/<repo>/
export default defineConfig({
  base: './',
  build: { chunkSizeWarningLimit: 2500 },
});
