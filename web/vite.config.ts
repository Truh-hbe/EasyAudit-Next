import basicSsl from '@vitejs/plugin-basic-ssl'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig(({ mode }) => ({
  plugins: [
    basicSsl({ name: 'easyaudit-next-dev' }),
    react(),
    // 只有浏览器测试专用的 `--mode e2e` 构建会带上 client 暴露钩子；生产构建不受影响。
    ...(mode === 'e2e'
      ? [
          {
            name: 'easyaudit-e2e-hook',
            transformIndexHtml: {
              order: 'pre' as const,
              handler: () => [
                {
                  tag: 'script',
                  attrs: { type: 'module', src: '/tests/e2e/e2eHook.ts' },
                  injectTo: 'body' as const,
                },
              ],
            },
          },
        ]
      : []),
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
}))
