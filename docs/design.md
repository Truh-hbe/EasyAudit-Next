# 前端设计规范

本文规定 `web/` 的视觉、布局、组件、文案与迁移约束。选型理由见 [ADR-0006](adr/0006-ant-design-ui-stack.md)；前后端边界（权限、错误语义、幂等、证据协议）见 [architecture.md](architecture.md#前端边界)。

改动需要打破本文某条规则时，在 PR 里说明原因并同步修改本文。

## 基调

内部审查协作工作台。用户是跨部门的审查员、整改负责人和管理者，每天处理清单、表单和状态流转。

- **清晰优先**：先让用户看清"当前状态、我的责任、下一步操作"，再展示记录和细节。不做装饰性插图、渐变和动效。
- **克制**：一个主题色，语义色只用于表达状态。每个区域最多一个主按钮。
- **中文优先**：界面文案为中文，不出现开发术语。
- **浅色、桌面优先**：主要在 ≥1280px 的桌面浏览器上使用。375px 必须可用，不得出现横向溢出；320px 做冒烟检查。试点阶段不做暗色模式。

## 技术选型（固定）

| 用途 | 选型 |
|---|---|
| 组件库 | `antd` 6（[Ant Design](https://ant.design/)） |
| 图标 | `@ant-design/icons` 6，应用自选图标只用 Outlined |
| 日期 | `dayjs`（显式直接依赖），全局 `zh-cn` locale |
| 国际化 | `ConfigProvider locale={zhCN}`，只支持中文 |
| 路由 | `react-router` |

- 版本在 `web/package.json` 中精确固定。升级 antd 走独立 PR，并跑完整的浏览器测试。
- 不引入其他组件库、图标库、CSS 框架、CSS-in-JS 库和 Ant Design Pro Components。`web/.oxlintrc.json` 的 `no-restricted-imports` 拦截其中已列出的常见库；黑名单不是穷举，新增直接依赖仍由 review 按本条把关。
- 从 `'antd'` 根入口导入，不使用 `antd/es/*`、`antd/lib/*`（`antd/locale/*` 除外）。

## 主题

`web/src/app/theme.ts` 是唯一的主题来源，由 `main.tsx` 的 `ConfigProvider` 注入。

| Token | 值 | 说明 |
|---|---|---|
| `colorPrimary` / `colorInfo` | `#2f5fca` | 主题蓝，白底 5.8:1 |
| `colorTextBase` | `#172033` | 正文基色，其他文字层级由 antd 派生 |
| `colorBgLayout` | `#f5f7fb` | 页面底色 |
| `colorBorder` | `#8290a3` | 控件边框，白底 3.3:1，满足 WCAG 1.4.11（antd 默认 `#d9d9d9` 只有 1.4:1） |
| `colorTextPlaceholder` | `#667085` | placeholder，白底 5.0:1（antd 默认约 1.7:1） |
| `borderRadius` | `8` | 统一圆角 |
| `fontFamily` | 系统字体 + PingFang SC / Microsoft YaHei | 不加载 Web 字体 |

成功、警告、错误的种子色使用 antd 默认值，不覆盖：antd 由种子色派生整套背景、边框和悬停色，改种子色会连带改变它们。需要可读文字时使用色板中达标的档位（见[状态与颜色](#状态与颜色)）。

**文字层级**：可读信息（说明、时间、副标题）用 `--ant-color-text-secondary`（白底 5.1:1）。`--ant-color-text-tertiary`（2.8:1）不用于任何可读文字。

**placeholder**：只提供示例，不能替代 label；它的文字同样要满足 4.5:1。antd 默认 placeholder 色（25% 不透明度，约 1.7:1）不达标，已通过 `colorTextPlaceholder` 调整，认证页浏览器测试实测。

**字号**：页面标题 24px（`--ant-font-size-heading-3`），区块标题 16px（`--ant-font-size-lg`），正文 14px，辅助信息 12px（`--ant-font-size-sm`）。

**间距**：只用 4 / 8 / 12 / 16 / 24 / 32。页面内区块间距 16，内容区内边距 24（移动端 16）。

**CSS 变量**：antd 把 token 和色板输出为 `--ant-*` 变量（如 `--ant-color-primary`、`--ant-green-8`），挂在 `<App className="app-root">` 上，只在其内部可用。自定义 CSS 只能通过 `var(--ant-*)` 取色、取圆角、取字号，禁止硬编码颜色值。

**验收**：种子色达标不代表最终组合达标。新增颜色组合（Tag、说明文字、选中态、校验提示）时实测前景与背景的对比度，正文 ≥ 4.5:1，控件边界与焦点 ≥ 3:1。

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

- 实现见 `web/src/app/shell/ProductShell.tsx`。导航只渲染一次，由 CSS grid 按断点切换位置。窄屏不把导航收进抽屉或 "…" 菜单，链接保持可见、可用键盘操作；当前用户名始终可见，过长时截断。
- 主要导航用 `<nav aria-label="主要导航">` + `NavLink`，不用 antd `Menu`（`role="menu"` 不适合站点导航，水平模式会折叠导航项）。
- 一级导航：我的工作、审查活动、通知、管理视图，系统管理员额外有管理设置。管理设置可见只代表平台管理身份，不授予业务权限。新增一级导航需要先改本文。
- 断点沿用 antd：`sm` 576、`md` 768、`lg` 992、`xl` 1200。代码中用 `Grid.useBreakpoint()` 或 `Row`/`Col` 的响应式属性，不自写 `window.matchMedia`。
- 内容区默认最大宽 1280。密集的管理表格有实测依据时可以单页放宽。

### 页面骨架

每个页面结构固定：

1. **页头**（`PageHeader`）：`<h1>` 标题；可选的副信息（状态 Tag、数据时间、所属计划）；主操作在右侧。
2. **内容**：用 `Card` 分区，区块标题是 `<h2>`。

| 页面类型 | 结构 |
|---|---|
| 列表页 | 页头 → 筛选栏（`Form layout="inline"`）→ `Table`（含分页） |
| 详情页 | 页头（标题 + 状态 + 操作）→ `Descriptions` 概要 → 按区块分 `Card`，区块多时用 `Tabs` |
| 创建页 | 多步时用 `Steps`，单列 `Form layout="vertical"`，最大宽 720px |
| 工作台 | `Card` 网格（`Row gutter={16}`，`lg` 两列） |
| 认证页 | 居中 `Card`，宽 400px |

### 各页信息架构

| 页面 | 首屏重点 | 其余区块与交互 |
|---|---|---|
| 登录、修改密码 | 单列表单，密码要求与限流提示 | 支持密码管理器（保留 `autoComplete`） |
| 我的工作 | 待我验证、我的整改与执行责任 | 已逾期、即将到期、我参与的审查活动；每项给状态、责任与入口；统计只用后端投影 |
| 审查活动列表 | 可见的审查活动、后端支持的筛选与分页 | "新建计划"作为创建入口 |
| 新建计划 / 新建审查活动 | 计划 → 精确版本的场景 → 活动信息 | 场景字段由适配器提供；草稿与幂等键见[迁移约束](#迁移约束) |
| 审查活动详情 | 标题、场景、状态、排期、我的角色 | 概览、发现项、团队、操作记录；生命周期命令放单独操作区 |
| 发现项详情 | 状态、责任方、场景类型、当前可执行操作 | 概览、参与方、整改项、提交记录、操作记录；长表单按职责拆分 |
| 整改项详情 | 任务、执行人、截止时间、完成要求 | 执行操作、证据（选择文件与上传结果分开呈现）、操作记录 |
| 通知 | 未读/已读、时间、业务摘要与对象入口 | 标记已读不等于完成业务动作 |
| 管理视图、管理进度 | 筛选条件、数据时间（`as_of`）、后端指标 | 明细、分页、导出（与当前筛选一致） |
| 管理设置 | 当前组织与管理对象 | 部门、用户、场景分区；重置凭证等危险操作单独确认 |

- 当前没有独立的计划列表、全局发现项或整改项列表，不为它们预留空菜单。发现项、整改项和管理进度从上级页面、工作台和通知进入，现有深链接保持不变。
- 筛选、分页和可分享的标签页状态放在路由 query 里，只发送现有 API 支持的参数。不添加后端尚未支持的全局搜索、任意排序或筛选。

## 组件选用

先找 antd 组件，没有合适的再组合。不写 antd 的薄封装（如 `MyButton`）。

| 需求 | 用 | 不用 |
|---|---|---|
| 按钮 | `Button`；主操作 `type="primary"`，危险操作 `danger` | 原生 `<button>` |
| 站内跳转 | `react-router` 的 `Link`；需要按钮外观时用 `ButtonLink`，仍渲染为 `<a href>` | 用 `onClick` + `useNavigate` 的按钮做跳转（会丢失新标签页、修饰键等链接行为） |
| 表单 | `Form` + `Form.Item`（`label`、`rules`、`required`） | 手写 `<label>` 和校验状态 |
| 输入 | `Input`、`Input.TextArea`、`Input.Password`、`InputNumber` | |
| 选择 | 选项 ≤ 4 用 `Radio.Group`，否则用 `Select`；候选人用 `Select showSearch` + 服务端授权的候选接口 | 原生 `<select>` |
| 日期 | `DatePicker`（时区见[时间](#文案与术语)） | 原生 `datetime-local` |
| 表格数据 | `Table`（`size="middle"`，`rowKey="id"`，分页来自服务端 envelope） | 手写 grid 列表 |
| 简单条目 | `Listy`（antd 6.6+）或 `Table` | `List`（已弃用，下个主版本移除） |
| 字段展示 | `Descriptions`（`column={{ xs: 1, md: 2 }}`） | 手写 `<dl>` |
| 状态 | `StatusTag` | 自定义 pill、直接用 antd 预设状态色 |
| 历史 / 操作记录 | `Timeline` | |
| 分区 | `Card`；同页多区块切换用 `Tabs` | 卡片套卡片 |
| 多步骤 | `Steps` | "第 N 步" 文案 |
| 空状态 | `Empty`（`image={Empty.PRESENTED_IMAGE_SIMPLE}`） | 灰色文字段落 |
| 加载 | 首屏 `Skeleton`；刷新时用 `Spin` 包住区块；提交时 `Button loading` | "正在读取…" 文案 |
| 成功反馈 | `App.useApp().message.success` | `message` 静态方法（拿不到主题和 locale） |
| 页面级提示 | `Alert`（`showIcon`） | `<p role="alert">` |
| 无权访问 / 不存在 | `Result` | |
| 二次确认 | `App.useApp().modal.confirm`；需要原因时用 `Modal` + `Form` | `window.confirm` |
| 普通编辑 | `Drawer`（桌面约 480px，移动端全宽） | 塞进大号确认框 |
| 文件 | `Upload`（只作选择器，见[迁移约束](#迁移约束)） | `Upload.action` |
| 纯图标按钮提示 | `Tooltip` | `title` 属性 |
| 布局 | `Flex`、`Space`、`Row`/`Col` | 为一次性布局写新 CSS class |

**共享组件**放在 `web/src/ui/`，只放跨页面复用的展示组件：`PageHeader`、`StatusTag`、`ButtonLink`，以及确有重复时再抽取的错误/空状态组件。`ui/` 不调用 API、不推导权限、不解释场景。

**Scenario 适配器**（`web/src/scenarios/`）同样遵守本文。场景字段用 `Descriptions` 展示，场景表单字段用 `Form.Item`；场景相关的状态上下文文案由适配器提供，通用组件不按场景分支。

## 图标

- 应用自选图标只用 `@ant-design/icons` 的 Outlined，不混用 Filled / TwoTone；antd 组件内部自带的状态图标保留原样。大小和颜色继承文字。
- **与文字并列的图标加 `aria-hidden`**。antd 图标默认带 `role="img" aria-label="<英文名>"`，不加会让按钮的可访问名称变成 "bell 通知"。
- 纯图标按钮必须有中文 `aria-label`，并配 `Tooltip`。
- 同一概念全站用同一个图标：

| 概念 | 图标 | 概念 | 图标 |
|---|---|---|---|
| 我的工作 | `HomeOutlined` | 新建 | `PlusOutlined` |
| 审查活动 | `FileSearchOutlined` | 编辑 | `EditOutlined` |
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

生命周期一律用 `StatusTag` 显示中文和对应颜色，不显示原始枚举值。StatusTag 按"对象类型 + 状态"取文案，不能只按 `in_progress` 这类字符串统一翻译。

antd 预设的 `success` / `warning` / `error` 状态 Tag 文字对比度只有 1.8–3.0:1，**不直接使用**。StatusTag 用显式配色：背景 `--ant-<色>-1`，边框 `--ant-<色>-3`，文字用下表中已实测达标的档位：

| 语义 | 文字色 | 对比度 | 用于 |
|---|---|---|---|
| 未开始 / 中止 | `--ant-color-text` | 10.6 | 草稿、已排期、待处理、待开始、已取消、已作废 |
| 进行中 | `--ant-blue-7` | 5.5 | 审查中、整改中、执行中 |
| 等待他人 | `--ant-orange-8` | 5.1 | 待关闭、待验证 |
| 完成 | `--ant-green-8` | 5.4 | 已关闭、已完成 |
| 逾期 | `--ant-red-7` | 5.1 | 截止时间已过（来自读侧，不是生命周期） |

| 对象 | 枚举 → 文案 |
|---|---|
| 审查活动 | `draft` 草稿 · `scheduled` 已排期 · `in_progress` 审查中 · `awaiting_closure` 待关闭 · `closed` 已关闭 · `cancelled` 已取消 |
| 发现项 | `open` 待处理 · `rectifying` 整改中 · `verifying` 待验证 · `closed` 已关闭 · `voided` 已作废 |
| 整改项 | `todo` 待开始 · `in_progress` 执行中 · `done` 已完成 · `cancelled` 已取消 |
| 截止 | `overdue` 已逾期（逾期色）· `due_soon` 即将到期（等待色）；正常时只显示日期 |
| 严重度 | `low` 低（默认）· `medium` 中（`--ant-orange-8`）· `high` 高（`--ant-volcano-8`，6.4）· `critical` 严重（`--ant-red-8`，7.0） |

- `open` 叫"待处理"而不是"待下发"：合规场景的观察项可以直接 `open → closed`，不经过下发。需要更具体的说法（如"待确认观察项"）时，由精确版本的场景适配器提供。
- 未知状态显示"未知状态"，原始值放在次级信息里，不假定它能执行任何操作。未知场景版本按架构规则拒绝解释。
- 颜色不能是唯一的信息载体，Tag 中必须有文字。

## 文案与术语

- 界面不出现里程碑代号（`M3.5`）、实现用语（projection、payload、envelope、read side）和原始枚举值。精确场景版本、UUID 这类有排障价值的信息可以放在次级详情里，但不作为标题或主要文案。
- 按钮以动词开头，说清对象和结果：新建整改项、提交完成情况、通过验证、确认关闭。不用一排无上下文的"确认"。
- **名称**：只用已授权接口返回的名称（成员、参与人、指派对象和候选搜索接口）。接口只给 ID 时显示"名称暂不可用"，加次级短 ID。不借用管理员用户目录为普通用户补名；需要新名称时另开读侧设计 PR。
- **时间**：展示时区固定为 `Asia/Shanghai`（与导出和提醒一致），显示格式 `2026/08/28 18:00`，空值显示 `—`。日期输入也按该时区解析为 ISO 时间，不受设备时区影响。`zh-cn` locale 只决定语言，不决定时区。统一入口在 `web/src/product/format.ts`。

| 领域概念 | 界面用语 |
|---|---|
| ReviewPlan | 审查计划 |
| ReviewCase | 审查活动 |
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

- Case 的 `lead` 不叫"负责人"，以免与 Finding 的 `owner` 混淆。
- 术语只用于产品文案。接口类型、生命周期枚举和路由保持原名。

## 交互状态

与 [architecture.md](architecture.md#api-错误语义) 的错误语义对应。409 按原因区分；写入结果未知不属于 409，单独处理。

| 情况 | 表现 |
|---|---|
| 首次加载 | `Skeleton` |
| 刷新 | 保留仍有权访问的旧内容，区块上加 `Spin`。Session 失效或资源权限丢失时立即移除受保护内容 |
| 空数据 | 区分"尚无数据"和"筛选无结果"；如果用户有真实可做的操作，附主按钮或"清除筛选" |
| 401 | 沿用 Session 失效处理和安全的返回路径；不持久化草稿 |
| 403 / 404 | `Result`，文案统一为"内容不存在或无权访问"，不暴露对象是否存在 |
| 409 状态已变化 / 并发冲突 | 提示"数据已变化，正在获取最新状态"；**刷新成功后**再呈现最新状态，由用户重新确认操作；刷新失败按对应错误处理。不自动重放 |
| 409 幂等键被不同请求复用（`isIdempotencyKeyReuse`） | 说明当前内容与之前那次创建请求不一致，保留草稿，提示刷新后确认；不轮换键、不重放 |
| 409 唯一性或其他业务冲突 | 显示对应的业务提示；无法分类时显示中性的冲突消息 |
| 422 | 能对应字段的显示在 `Form.Item` 上并聚焦第一个错误，否则用 `Alert type="error"` 显示服务端 `detail`；保留已填内容 |
| 413 / 415（上传） | 说明文件大小或类型限制，保留可修改的表单内容 |
| 429 / 503 | 有 `Retry-After` 时按它提示等待时间；由用户手动重试 |
| 写入结果未知（网络中断、响应丢失、500） | 明确"未确认是否成功"；创建类请求复用原幂等键，由用户手动重试或先刷新核对，不自动重放；有 `request_id` 时可复制 |
| 写操作成功 | `message.success` 简短提示，并刷新相关查询 |
| 不可逆操作 | 二次确认（关闭活动、作废、取消、停用用户、重置密码）；领域要求原因时在确认框内填写 |

按钮是否显示只是提示，最终以服务端结果为准。弹层打开后焦点进入弹层，关闭后回到触发元素。

## 迁移约束

页面迁移只改变交互，不改变 API 协议和既有保护。

- **证据上传**：`Upload` 只负责选择文件、文件列表和反馈，传输必须经现有 `uploadActionEvidence`（原始字节、MIME、编码文件名、描述参数；大小、哈希和存储键由服务端决定）。二选一：
  1. `beforeUpload` 返回 `false` 阻止自动上传，由明确的"上传"按钮调用 `uploadActionEvidence`；
  2. 用 `customRequest` 调用 `uploadActionEvidence`，并把结果接到 `onSuccess` / `onError`。

  不要两者混用（`beforeUpload` 返回 `false` 后 `customRequest` 不会执行）。禁止使用 `Upload.action`。没有真实进度来源时不显示百分比；网络中断后不自动重传。
- **证据下载与导出**：下载保留同源附件链接 `/api/v1/evidences/{id}/content`，不读成 Blob；管理导出沿用现有下载适配器和筛选参数。
- **创建幂等**：一次创建尝试的草稿和 `Idempotency-Key` 由页面级业务状态持有，不随 `Modal`、`Drawer`、`Steps`、`Tabs` 的卸载而重建。只有明确成功后才结束这次尝试；结果未知时保留键和请求内容。不为此引入全局状态库，也不把草稿写入浏览器长期存储。
- **遗留样式隔离**：`styles.css` 中的遗留元素规则（`form`、`label`、`input`、`button`、`[role="alert"]` 等）只作用于旧页面容器 `.surface-page` / `.auth-card` / `.foundation` 内部，且不进入 `.ui-modern` 边界。
  - 混合页面中的新组件放在 `<div className="ui-modern">` 内。
  - 整页迁移后，根节点不再使用旧容器类，也就不需要这层包裹。
  - antd 弹层渲染到 `body`，本来就不受影响。
  - 浏览器测试 `legacy element styles stay inside legacy page containers…` 守护这条边界。

## 可访问性

- 每页一个 `<h1>`，区块标题用 `<h2>`。
- 表单控件必须有可见的 label（`Form.Item label`），测试依赖 `getByLabel`。placeholder 只给示例，不能替代 label，对比度要求同正文。
- 保留全局 `:focus-visible` 描边（`final-polish.css`）。
- 对比度目标为 WCAG 2.2 AA，按最终组合实测（见[主题](#主题)）。颜色不能是唯一的信息载体。
- 地标：`<nav aria-label="主要导航">`、`<main>`。
- 动效遵循 `prefers-reduced-motion`。

## 样式编写

优先级：antd 组件属性 → `theme.ts` 的 token / 组件 token → `classNames` / `styles` 语义接口 → `Flex`/`Space`/`Row`/`Col` → 最后才写 CSS。

- 全局布局 CSS 放在 `web/src/styles.css`。class 名用 kebab-case，Shell 用 `app-` 前缀。
- 不覆盖 `.ant-*` 内部 class，不用 `!important`。需要定制时用组件 token 或语义接口。
- 确需覆盖 antd 组件自带样式（如 `StatusTag` 的配色）时，选择器挂在 `.app-root` 下以提高优先级，例如 `.app-root .status-tag.status-tag--*`，不依赖样式注入顺序，也不用 `!important`。
- 不用内联 `style` 设置颜色和字号。
- **遗留样式**：`.surface-*`、`.command-*`、`.fact-grid`、`.status-pill`、`.eyebrow` 等 class 和上节的元素规则是迁移前的遗留，新代码不得使用。迁移一页就删除一页不再使用的规则，UI-7 做最后清理。

## 测试约定

- 浏览器测试用 `getByRole` / `getByLabel` / `getByText` 定位元素，不依赖 `.ant-*` class 或 DOM 层级。迁移页面时，同步把测试中的遗留 class 选择器（如 `.status-pill`）换成语义选择器。
- 已有覆盖，不得删除：375px 和 320px 无横向溢出；992px 断点切换导航布局；管理员五项导航可用 Tab 遍历、Enter 打开；遗留样式边界。
- 每个迁移 PR 的描述附同一数据状态下的桌面和 375px 截图，并检查 200% 缩放（相当于 640px 宽）。
- 新增颜色组合时附实测对比度。
- 浏览器项目目前只有 Chromium；试点终端的浏览器版本以实际设备为准并记录在 PR 中。
