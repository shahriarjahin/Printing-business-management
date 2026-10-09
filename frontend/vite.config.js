import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
  base:'/static/react/', plugins:[react()],
  build:{outDir:'../static/react',emptyOutDir:true,rollupOptions:{input:'src/main.tsx',output:{entryFileNames:'app.js',chunkFileNames:'chunks/[name]-[hash].js',assetFileNames:'assets/[name]-[hash][extname]'}}}
});
