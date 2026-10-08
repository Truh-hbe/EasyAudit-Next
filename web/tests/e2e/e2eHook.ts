// 仅在 `vite build --mode e2e` 的测试构建里由 vite.config.ts 注入（生产构建不含此文件）。
// 与应用共享同一批模块实例，让浏览器测试不必依赖 dev server 的源码路径。
import { sessionApiRequest } from '../../src/api/client'

declare global {
  interface Window {
    __easyauditE2E?: {
      // 页面处于 resolving、没有可点击入口时，发出一个与应用等价的会话请求。
      sessionApiRequest: typeof sessionApiRequest
      // 对比度断言用的主题探针；动态 import，只在被调用时才加载。
      loadThemeProbe: () => Promise<typeof import('../browser/fixtures/theme-probe')>
    }
  }
}

window.__easyauditE2E = {
  sessionApiRequest,
  loadThemeProbe: () => import('../browser/fixtures/theme-probe'),
}
