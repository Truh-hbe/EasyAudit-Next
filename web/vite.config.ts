import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [
    basicSsl({ name: 'easyaudit-next-dev' }),
    react(),
  ],
  server: {
    https: {},
    proxy: {
      '/api/v1': {
        target: process.env.EASYAUDIT_API_URL ?? 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
})
