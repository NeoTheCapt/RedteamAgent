import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    proxy: {
      "/auth": "http://127.0.0.1:18000",
      "/projects": "http://127.0.0.1:18000",
      "/ws": {
        target: "ws://127.0.0.1:18000",
        ws: true,
      },
    },
  },
});
