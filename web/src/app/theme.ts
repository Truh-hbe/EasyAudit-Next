import type { ThemeConfig } from 'antd'

// headerIconColor / headerIconHoverColor 是 antd 运行时支持的 Table 内部 token，但未进公开类型；
// 经变量展开以绕过字面量的多余属性检查。
const tableHeaderIconTokens = {
  headerIconColor: 'rgba(23, 32, 51, 0.55)',
  headerIconHoverColor: 'rgba(23, 32, 51, 0.88)',
}

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
    // antd 的说明文字（Typography secondary、Form extra、Card/List Meta、Steps、Empty 等）用
    // colorTextDescription，默认等于 tertiary（45% 不透明度，白底 2.8:1）。
    // 对齐 secondary（65%）：白底 5.1:1，#f5f7fb 上 5.0:1。
    colorTextDescription: 'rgba(23, 32, 51, 0.65)',
    // antd 内置交互图标（Input.Password 切换、各类关闭/清除按钮、Select 箭头）读 colorIcon，
    // 默认等于 tertiary（白底 2.8:1），低于 WCAG 1.4.11 的 3:1。55%：白底 3.7:1，#f5f7fb 上 3.7:1。
    // colorIconHover 沿用默认（colorText，更深），不需要覆盖。
    colorIcon: 'rgba(23, 32, 51, 0.55)',
    borderRadius: 8,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", "Helvetica Neue", Arial, sans-serif',
  },
  components: {
    // 清除按钮、下拉箭头、日期后缀常态读 colorTextQuaternary（25%，白底 1.7:1），hover 才读 colorIcon。
    // 只在这些组件内覆盖：全局 colorTextQuaternary 会连带加深 colorTextDisabled。
    // 组件级覆盖不重新派生 alias，disabled 文字不受影响。55%：白底 3.7:1。
    Input: { colorTextQuaternary: 'rgba(23, 32, 51, 0.55)' },
    Select: { colorTextQuaternary: 'rgba(23, 32, 51, 0.55)' },
    DatePicker: { colorTextQuaternary: 'rgba(23, 32, 51, 0.55)' },
    Mentions: { colorTextQuaternary: 'rgba(23, 32, 51, 0.55)' },
    // 表头排序/筛选图标默认在 colorIcon 上再乘 opacityLoading（约 0.357，表头底色上 2.2:1）。
    // 筛选图标 hover 读 colorIcon 且表头底色变深，沿用 0.55 会比常态更淡，所以 Table 内的 colorIcon 取 hover 档。
    Table: {
      colorIcon: 'rgba(23, 32, 51, 0.88)',
      ...tableHeaderIconTokens,
    },
    Descriptions: {
      // Descriptions 的 label 直接用 colorTextTertiary（2.8:1）。tertiary 同时是 colorIcon，
      // 全局调高会改变图标层级，所以只改这一个组件：同样 65%，白底 5.1:1。
      labelColor: 'rgba(23, 32, 51, 0.65)',
    },
  },
}
