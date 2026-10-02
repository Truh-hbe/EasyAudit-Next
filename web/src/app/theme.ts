import type { ThemeConfig } from 'antd'

// 唯一的主题来源。新增或调整 token 前先改 docs/design.md。
export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#2f5fca',
    colorInfo: '#2f5fca',
    colorTextBase: '#172033',
    colorBgLayout: '#f5f7fb',
    // 控件边框需满足 WCAG 1.4.11 非文本对比度 ≥ 3:1（antd 默认 #d9d9d9 约 1.4:1）。
    colorBorder: '#8290a3',
    // antd 默认 placeholder 色（25% 不透明度）约 1.7:1；#667085 白底 5.0:1。
    colorTextPlaceholder: '#667085',
    borderRadius: 8,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif',
  },
}
