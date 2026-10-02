import type { ThemeConfig } from 'antd'

// 唯一的主题来源。新增或调整 token 前先改 docs/design.md。
export const appTheme: ThemeConfig = {
  token: {
    colorPrimary: '#2f5fca',
    colorInfo: '#2f5fca',
    colorTextBase: '#172033',
    colorBgLayout: '#f5f7fb',
    borderRadius: 8,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif',
  },
}
