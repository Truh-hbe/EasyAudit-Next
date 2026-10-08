# ADR-0006：前端固定使用 Ant Design 6 与 @ant-design/icons

- 状态：Accepted
- 日期：2026-10-02

## 背景

M3.5 到 M5 的前端全部手写：只依赖 React 和 react-router，约 45 个全局 CSS class，颜色和圆角硬编码，没有图标。每个页面各自拼表单、列表和状态展示，风格逐渐分叉。受控试点前需要统一 UI，后续开发也不应继续重复造轮子。

## 决策

- 组件库固定为 `antd` 6，图标固定为 `@ant-design/icons` 6（只用 Outlined），日期用 `dayjs`（显式声明为直接依赖）。版本精确固定。
- 主题只在 `web/src/app/theme.ts` 中配置。自定义 CSS 通过 antd 输出的 `--ant-*` CSS 变量取值。
- 不引入其他组件库、图标库、CSS 框架和 CSS-in-JS 库。`web/.oxlintrc.json` 的 `no-restricted-imports` 拦截已列出的常见库；黑名单不是穷举，新增直接依赖由 review 把关。
- 具体的视觉、布局、组件选用和文案规范写在 [docs/design.md](../design.md)。

## 理由

- 产品形态是中文企业内部工作台：表格、表单、详情描述、步骤条、时间线、上传，都是 antd 的强项，开箱即用。
- 自带 `zh_CN` locale 和中文排版习惯，用户对这套交互普遍熟悉。
- Design Token 和 CSS 变量让主题集中管理，自定义布局 CSS 也能跟随主题。
- 社区规模大、版本节奏稳定，对 React 19 有原生支持。

## 考虑过的替代方案

- **shadcn/ui + Tailwind + lucide-react**：组件代码拷进仓库，视觉自由度高。但需要引入 Tailwind，并由团队自己维护组件源码；Table、DatePicker 要另外组装，"固定组件库"的约束也弱。
- **Mantine 9 + Tabler Icons**：API 现代，CSS Modules 没有运行时开销。但中文生态和复杂表格能力不如 antd。
- **继续手写**：没有新依赖，但会持续重复造轮子，风格无法收敛。

## 后果

- 前端包体积增加：主 JS 从 352 kB（gzip 97 kB）增长到 660 kB（gzip 204 kB），Vite 会提示 chunk 过大。是否可以接受以试点终端的实测首屏时间为准（UI-3 记录），明显退化时提前做路由代码分割。代码分割无法消除根部 `ConfigProvider` / `App` 的公共成本。
- antd 在运行时注入 `<style>`。网关将来如果加 CSP，需要允许 `style-src 'unsafe-inline'`，或者通过 `ConfigProvider csp={{ nonce }}` 传入 nonce。
- 现有页面逐页迁移，期间新旧样式并存；遗留样式已在 UI-7 全部删除。
- antd 预设的状态色文字对比度不足，状态 Tag 使用显式的达标配色（见 design.md）。
- 升级 antd 主版本需要新的 ADR 或修订本文。
