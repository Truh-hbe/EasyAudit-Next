# 前端设计规范

本文规定 `web/` 的视觉、布局、组件与文案。选型理由见 [ADR-0006](adr/0006-ant-design-ui-stack.md)；前端与后端的边界（权限、409、幂等）见 [architecture.md](architecture.md#前端边界)。

改动需要打破本文某条规则时，在 PR 里说明原因并同步修改本文。

## 基调

内部审查协作工作台。用户是跨部门的审查员、整改负责人和管理者，每天处理清单、表单和状态流转。

- **清晰优先**：状态、责任人、截止日期一眼可见。不做装饰性插图、渐变、动效。
- **克制**：一个主题色，语义色只用于表达状态。每个区域最多一个主按钮。
- **中文优先**：界面文案全部为中文，不出现开发术语。
- **浅色、桌面优先**：主要在 ≥1280px 的桌面浏览器上使用。375px 必须可用，不得出现横向溢出；320px 做冒烟检查。试点阶段不做暗色模式。

## 技术选型（固定）

| 用途 | 选型 |
|---|---|
| 组件库 | `antd` 6（[Ant Design](https://ant.design/)） |
| 图标 | `@ant-design/icons` 6，只用 Outlined 风格 |
| 日期 | `dayjs`（antd 依赖），全局 `zh-cn` locale |
| 国际化 | `ConfigProvider locale={zhCN}`，只支持中文 |
| 路由 | `react-router` |

- 版本在 `web/package.json` 中精确固定。升级 antd 走独立 PR，并跑完整的浏览器测试。
- **禁止**引入其他组件库、图标库、CSS 框架（Tailwind 等）、CSS-in-JS 库（styled-components、emotion）和 Ant Design Pro Components。`web/.oxlintrc.json` 的 `no-restricted-imports` 强制。
- 从 `'antd'` 根入口导入，不使用 `antd/es/*`、`antd/lib/*`（`antd/locale/*` 除外）。

## 主题

`web/src/app/theme.ts` 是唯一的主题来源，由 `main.tsx` 的 `ConfigProvider` 注入。

| Token | 值 | 说明 |
|---|---|---|
| `colorPrimary` / `colorInfo` | `#2f5fca` | 主题蓝，白底对比度 > 4.5:1 |
| `colorTextBase` | `#172033` | 正文基色，其他文字层级由 antd 派生 |
| `colorBgLayout` | `#f5f7fb` | 页面底色 |
| `borderRadius` | `8` | 统一圆角 |
| `fontFamily` | 系统字体 + PingFang SC / Microsoft YaHei | 不加载 Web 字体 |

成功、警告、错误色使用 antd 默认值，不覆盖。

**字号**：页面标题 24px（`--ant-font-size-heading-3`），区块标题 16px（`--ant-font-size-lg`），正文 14px，辅助信息 12px（`--ant-font-size-sm`）。

**间距**：只用 4 / 8 / 12 / 16 / 24 / 32。页面内区块间距 16，内容区内边距 24（移动端 16）。

**CSS 变量**：antd 把 token 输出为 `--ant-*` 变量，挂在 `<App className="app-root">` 上。自定义 CSS 只能通过 `var(--ant-*)` 取色、取圆角、取字号，**禁止硬编码颜色值**。

## 布局

### App Shell

```text
≥ 992px                                   < 992px
┌──────────┬──────────────────────────┐   ┌──────────────────────┐
│ 品牌     │              用户 · 退出 │   │ 品牌        用户 退出│
├──────────┼──────────────────────────┤   ├──────────────────────┤
│ 主要导航 │ 内容区（最大宽 1280）    │   │ 主要导航（横向滚动） │
│ 224px    │                          │   ├──────────────────────┤
│          │                          │   │ 内容区               │
└──────────┴──────────────────────────┘   └──────────────────────┘
```

- 实现见 `web/src/app/shell/ProductShell.tsx`。导航只渲染一次，由 CSS grid 按断点切换位置。移动端不把导航收进抽屉或 "…" 菜单：链接必须可见、可用键盘操作（浏览器测试覆盖）。
- 主要导航用 `<nav aria-label="主要导航">` + `NavLink`，不用 antd `Menu`（`role="menu"` 不适合站点导航，水平模式会折叠导航项）。
- 一级导航：我的工作、审查活动、通知、管理视图，系统管理员额外有管理设置。新增一级导航需要先改本文。
- 断点沿用 antd：`sm` 576、`md` 768、`lg` 992、`xl` 1200。代码中用 `Grid.useBreakpoint()` 或 `Row`/`Col` 响应式属性，不自写 `window.matchMedia`。

### 页面骨架

每个页面结构固定：

1. **页头**：`<h1>` 标题；可选的副信息（状态 Tag、数据时间、所属计划）；主操作按钮放在右侧。
2. **内容**：用 `Card` 分区，区块标题是 `<h2>`。

| 页面类型 | 结构 | 现有页面 |
|---|---|---|
| 列表页 | 页头 → 筛选栏（`Form layout="inline"`）→ `Table`（含分页） | 审查活动、管理视图、通知 |
| 详情页 | 页头（标题 + 状态 Tag + 操作）→ `Descriptions` 概要 → 按区块分 `Card`，区块多时用 `Tabs` | 审查案例、发现项、整改项、管理进度 |
| 创建页 | 多步时用 `Steps`，单列 `Form layout="vertical"`，最大宽 720px，主按钮在表单底部左侧 | 新建计划、新建案例 |
| 工作台 | `Card` 网格（`Row gutter={16}`，`lg` 两列），必要时加 `Statistic` | 我的工作 |
| 认证页 | 居中 `Card`，宽 400px | 登录、修改密码 |

## 组件选用

先找 antd 组件，没有合适的再组合。不写 antd 的薄封装（如 `MyButton`）。

| 需求 | 用 | 不用 |
|---|---|---|
| 按钮 | `Button`；主操作 `type="primary"`，危险操作 `danger` | 原生 `<button>`、链接伪装成按钮 |
| 跳转 | `react-router` 的 `Link`；需要按钮外观时用 `<Button>` 包 `useNavigate` | 带 `href` 的 `Button` 做站内跳转 |
| 表单 | `Form` + `Form.Item`（`label`、`rules`、`required`） | 手写 `<label>` + 状态校验 |
| 输入 | `Input`、`Input.TextArea`、`Input.Password`、`InputNumber` | |
| 选择 | 选项 ≤ 4 用 `Radio.Group`，否则用 `Select`；搜索候选人用 `Select showSearch` + 服务端过滤 | 原生 `<select>` |
| 日期 | `DatePicker`（dayjs） | 原生 `<input type="date">` |
| 表格数据 | `Table`（`size="middle"`，`rowKey="id"`，分页数据来自服务端 envelope） | 手写 grid 列表 |
| 简单条目 | `List` | |
| 字段展示 | `Descriptions`（`column` 响应式：`{ xs: 1, md: 2 }`） | 手写 `<dl>` |
| 状态 | `StatusTag`（见下文） | 自定义 pill |
| 历史 / 活动 | `Timeline` | |
| 分区 | `Card`；同页多区块切换用 `Tabs` | |
| 多步骤 | `Steps` | "第 N 步" 文案 |
| 空状态 | `Empty`（`image={Empty.PRESENTED_IMAGE_SIMPLE}`） | 灰色文字段落 |
| 首屏加载 | `Skeleton` | "正在读取…" 文案 |
| 局部加载 / 刷新 | `Spin` 包住区块，保留旧内容 | 清空后再显示 |
| 提交中 | `Button loading` | 改按钮文案 |
| 成功反馈 | `App.useApp().message.success` | `message` 静态方法（拿不到主题和 locale） |
| 页面级错误 / 警告 | `Alert`（`showIcon`） | `<p role="alert">` |
| 无权访问 / 不存在 | `Result` | |
| 二次确认 | `App.useApp().modal.confirm`；需要原因时用 `Modal` + `Form` | `window.confirm` |
| 文件 | `Upload` | 原生 `<input type="file">` |
| 用户 | `Avatar` + 姓名 | |
| 纯图标按钮提示 | `Tooltip` | `title` 属性 |
| 布局 | `Flex`、`Space`、`Row`/`Col` | 为一次性布局写新 CSS class |

**共享组件**放 `web/src/ui/`，只放跨页面复用的展示组件，例如 `PageHeader`（渲染 `<h1>`，统一 24px 标题和右侧操作区）、`StatusTag`。业务逻辑不进 `ui/`。

**Scenario 适配器**（`web/src/scenarios/`）同样遵守本文。场景字段用 `Descriptions` 展示，场景表单字段用 `Form.Item`。

## 图标

- 只用 `@ant-design/icons` 的 Outlined 图标，不混用 Filled / TwoTone。大小和颜色继承文字，不单独设置。
- **与文字并列的图标加 `aria-hidden`**。antd 图标默认带 `role="img" aria-label="<英文名>"`，否则按钮的可访问名称会变成 "bell 通知"。
- 纯图标按钮必须有中文 `aria-label`，并配 `Tooltip`。
- 同一概念全站用同一个图标：

| 概念 | 图标 | 概念 | 图标 |
|---|---|---|---|
| 我的工作 | `HomeOutlined` | 新建 | `PlusOutlined` |
| 审查活动 / 案例 | `FileSearchOutlined` | 编辑 | `EditOutlined` |
| 审查计划 | `ScheduleOutlined` | 删除 / 移除 | `DeleteOutlined` |
| 发现项 | `FlagOutlined` | 搜索 | `SearchOutlined` |
| 整改项 | `CheckSquareOutlined` | 筛选 | `FilterOutlined` |
| 证据 | `PaperClipOutlined` | 刷新 | `ReloadOutlined` |
| 提交记录 | `SendOutlined` | 上传 / 下载 | `UploadOutlined` / `DownloadOutlined` |
| 操作记录 | `HistoryOutlined` | 导出 | `ExportOutlined` |
| 通知 | `BellOutlined` | 催办 | `NotificationOutlined` |
| 管理视图 | `BarChartOutlined` | 截止 / 逾期 | `ClockCircleOutlined` |
| 管理设置 | `SettingOutlined` | 重新打开 | `RollbackOutlined` |
| 用户 | `UserOutlined` | 作废 / 取消 | `StopOutlined` |
| 部门 | `ApartmentOutlined` | 成员 / 团队 | `TeamOutlined` |
| 退出登录 | `LogoutOutlined` | 密码 | `LockOutlined` |

## 状态与颜色

生命周期一律用 `StatusTag` 显示中文和对应颜色，不显示原始枚举值。颜色只表达语义，Tag 中必须有文字：

| 语义 | Tag `color` | 用于 |
|---|---|---|
| 未开始 / 中止 | `default` | 草稿、已排期、待下发、待办、已取消、已作废 |
| 进行中 | `processing` | 进行中、整改中 |
| 等待他人 | `warning` | 待关闭、待验证 |
| 完成 | `success` | 已关闭、已完成 |
| 逾期 | `error` | 截止日期已过（来自读侧，不是生命周期） |

| 对象 | 枚举 → 文案 |
|---|---|
| ReviewCase | `draft` 草稿 · `scheduled` 已排期 · `in_progress` 进行中 · `awaiting_closure` 待关闭 · `closed` 已关闭 · `cancelled` 已取消 |
| Finding | `open` 待下发 · `rectifying` 整改中 · `verifying` 待验证 · `closed` 已关闭 · `voided` 已作废 |
| ActionItem | `todo` 待办 · `in_progress` 进行中 · `done` 已完成 · `cancelled` 已取消 |
| 截止 | `overdue` 已逾期（`error`）· `due_soon` 即将到期（`warning`） |
| 严重度 | `low` 低（`default`）· `medium` 中（`gold`）· `high` 高（`orange`）· `critical` 严重（`red`） |

## 文案与术语

- 界面不出现：里程碑代号（`M3.5`）、实现用语（projection、payload、envelope、read side）、UUID、原始枚举值、`scenario_key@version`。
- 按钮以动词开头，2–4 个字：新建、保存、提交、取消、确认关闭、重新打开。
- 时间统一用 `web/src/product/format.ts` 的 `formatDateTime`，格式为 `2026/08/28 18:00`。空值显示 `—`。
- 用户和部门显示名称，不显示 ID。

| 领域概念 | 界面用语 |
|---|---|
| ReviewPlan | 审查计划 |
| ReviewCase | 审查案例（一级导航为"审查活动"） |
| Finding | 发现项 |
| ActionItem | 整改项 |
| Evidence | 证据 |
| Submission | 提交记录（整改计划、整改完成、验证结论） |
| Activity | 操作记录 |
| Scenario | 审查场景：`process_review` 过程审查，`compliance_review` 合规审查 |
| Case 角色 | `lead` 审查组长 · `auditor` 审查员 · `reviewer` 复核员 · `observer` 观察员 |
| Finding 参与方 | `owner` 整改负责人 · `collaborator` 协作者 · `responsible_department` 责任部门 |
| Action 指派 | `primary` 主要执行人 · `collaborator` 协作者 |
| 手动催办 | 催办 |

Case 的 `lead` 不叫"负责人"，以免与 Finding 的 `owner` 混淆。

## 交互状态

与 [architecture.md](architecture.md#前端边界) 的错误语义一一对应：

| 情况 | 表现 |
|---|---|
| 首次加载 | `Skeleton` |
| 刷新 | 保留旧内容，区块上加 `Spin` |
| 空数据 | `Empty`；如果当前用户有可做的操作，附主按钮 |
| 403 / 404 | `Result`，文案统一为"内容不存在或无权访问"，不区分两者 |
| 409 | `Alert type="warning"`："数据已被更新，已刷新为最新状态，请确认后重试。"同时刷新数据，不自动重放 |
| 422 | 能对应字段的显示在 `Form.Item` 上，否则用 `Alert type="error"` 显示服务端 `detail` |
| 503 | `Alert`："服务繁忙，请稍后重试。"附重试按钮，由用户触发 |
| 网络错误 | `Alert`："网络异常，请检查连接后重试。" |
| 写操作成功 | `message.success` 简短提示，并刷新相关查询 |
| 不可逆操作 | 二次确认（关闭案例、作废、取消、停用用户、重置密码）；领域要求原因时，在确认框内填写 |

按钮是否显示只是提示，最终以服务端结果为准。

## 可访问性

- 每页一个 `<h1>`，区块标题用 `<h2>`。
- 表单控件必须有可见的 label（`Form.Item label`），测试依赖 `getByLabel`。
- 保留全局 `:focus-visible` 描边（`final-polish.css`）。
- 文字对比度满足 WCAG AA。颜色不能是唯一的信息载体。
- 地标：`<nav aria-label="主要导航">`、`<main>`。

## 样式编写

优先级：antd 组件属性 → `theme.ts` 的 token / 组件 token → `Flex`/`Space`/`Row`/`Col` → 最后才写 CSS。

- 全局布局 CSS 放在 `web/src/styles.css`。class 名用 kebab-case，Shell 用 `app-` 前缀。
- 不覆盖 `.ant-*` 内部 class（升级时容易失效）。需要定制时用组件 token。
- 不用内联 `style` 设置颜色和字号。
- **遗留样式**：`styles.css` 中的 `.surface-*`、`.command-*`、`.fact-grid`、`.status-pill`、`.eyebrow` 等，以及 `button`/`input`/`label`/`form` 元素选择器，是迁移前的遗留。新代码不得使用。页面迁移完成后一并删除。

## 测试约定

- 浏览器测试用 `getByRole` / `getByLabel` / `getByText` 定位元素，不依赖 `.ant-*` class 或 DOM 层级。
- 迁移页面时，同步把测试中的遗留 class 选择器（如 `.status-pill`）换成语义选择器。
- 375px 无横向溢出、导航可用键盘操作，已有浏览器测试覆盖，不要删除。
