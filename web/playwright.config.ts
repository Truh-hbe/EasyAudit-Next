import { defineConfig, devices } from '@playwright/test'

const webPort = process.env.EASYAUDIT_WEB_PORT ?? '4173'
const webURL = `https://127.0.0.1:${webPort}`

export default defineConfig({
  testDir: './tests/browser',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'line' : 'list',
  use: {
    baseURL: webURL,
    ignoreHTTPSErrors: true,
    trace: 'on-first-retry',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
  webServer: {
    // 跑生产打包产物（vite build + preview），而不是按需编译的 dev server。
    // --mode e2e 只多注入 tests/e2e/e2eHook.ts，其余与生产构建一致；产物放独立目录，不覆盖 dist。
    command:
      'npx vite build --mode e2e --outDir dist-e2e --emptyOutDir && ' +
      `npx vite preview --mode e2e --outDir dist-e2e --host 127.0.0.1 --port ${webPort} --strictPort`,
    url: webURL,
    ignoreHTTPSErrors: true,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
  },
})
