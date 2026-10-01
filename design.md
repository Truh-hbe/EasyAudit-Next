# EasyAudit-Next 前端设计规范

本文件是页面布局、主题、组件、图标和交互的统一依据。业务规则见 [docs/domain.md](docs/domain.md)，授权、错误与请求边界见 [docs/architecture.md](docs/architecture.md)，实施顺序见 [docs/roadmap.md](docs/roadmap.md)。其他文档引用本文件，不复制另一套视觉规范。

基线核对：2026-10-02（Asia/Shanghai），`main@e0d5a8490eb412fa75e8b308ec53317f46e2f41b`。**本次确立 V1 设计与整改方案，组件库尚未安装，页面迁移尚未完成。** 库接入、浏览器验证和各页实现通过后续普通 PR 交付。

## 1. 产品基调与现状

面向审查、整改、验证和管理人员，采用专业、克制、清晰的企业协作界面。先让用户看清“当前状态、我的责任、下一步操作”，再展示记录和技术细节。V1 固定浅色主题、青绿色主色、简体中文、适中的信息密度；暗色主题在有使用需求和完整验证后另做。

以下判断来自源码审查，未替代真实页面的视觉验收：

| 现状依据 | 问题 | 整改方向 |
|---|---|---|
| `web/package.json` 只有 React、React DOM、react-router 三个运行时依赖 | 原生控件与自定义样式缺少统一组件基线 | 接入固定组件库与配套图标 |
| `styles.css`、`final-polish.css` | 颜色、圆角与字号散落；全局元素样式和补丁叠加 | 统一 token，迁移后合并基础样式，移除失效补丁 |
| `ProductShell.tsx` | 页头、横向导航占据纵向空间 | 桌面侧栏、顶部账号区，移动端抽屉导航 |
| Case、Finding、Admin 详情页 | 概览、长记录、创建表单与流程命令堆叠 | 分区、标签页、按操作打开的表单；拆分功能组件 |
| `product/format.ts`、各页字段 | 状态、角色、UUID、开发阶段字样偏技术化 | 中文语义映射、授权范围内的名称、次级技术详情 |

保留 React、react-router、Vite、TypeScript、现有 API client 和场景适配器。重构集中在展示与交互层，逐页迁移，每个 PR 保持可运行。

## 2. 固定组件与图标选型

| 用途 | 固定选择 | 接入基线 | 许可证 |
|---|---|---|---|
| 通用组件 | Ant Design：`antd` | `6.6.5` | MIT |
| 图标 | Ant Design Icons：`@ant-design/icons` | `6.3.4` | MIT |
| 主题与反馈上下文 | `ConfigProvider` + Ant Design `App` | 随 `antd` | 同上 |
| 日期控件适配 | Ant Design DatePicker + Day.js | UI-1 核实并锁定直接依赖版本 | MIT |

选型理由：本项目的核心是表格、业务表单、详情、抽屉、确认与状态反馈。Ant Design 已提供这些组件、中文 locale 与统一图标，减少自建控件和跨库拼装。shadcn/ui 的开放组件源码适合需要高度定制和自行维护组件的项目；本项目优先降低组件维护量，因此选择 Ant Design。现有路由与构建继续沿用，不引入 Ant Design Pro、Umi 或第二套通用组件/图标体系。V1 不新增图表库。

版本策略：接入 PR 使用精确版本并提交 `package-lock.json`，不使用 `latest`、`^`、`~` 自动漂移；升级通过独立依赖 PR，说明变化并运行前端检查。DatePicker 直接 import Day.js 时，将其列为精确的直接依赖，不能依赖 npm 偶然提升的传递依赖。保留所用开源依赖的许可证声明；本仓库自身许可证状态另见 README。

兼容性：Ant Design 6 要求 React 18+ 和支持 CSS 变量的现代浏览器；当前 React 19 满足 peer 范围，但 TypeScript 6、Vite 8 与整套构建的兼容性仍需 UI-1 实测。试点默认使用受维护的 Edge、Chrome、Firefox、Safari，按官方支持范围和实际终端记录具体版本。IE、Win7 上已停止更新的浏览器不在本基线支持范围；若实际终端需要它们，先重新评估选型，不能以“编译通过”代替兼容验证。

## 3. 主题与基础 token

主题集中定义于拟新增的 `web/src/ui/theme.ts`，通过 `ConfigProvider` 传入。全局 CSS 变量与组件 token 从同一组值派生；功能页不另定义品牌色。组件特例优先使用公开 token、`classNames` / `styles` 语义接口，避免依赖 `.ant-*` 内部 DOM 或 `!important` 覆盖。

| 语义 | V1 值 | 使用规则 |
|---|---|---|
| 主色 `colorPrimary` | `#0F766E` | 主操作、当前导航、链接和焦点；主按钮白字 |
| 页面底色 `colorBgLayout` | `#F4F6F8` | 页面背景 |
| 容器底色 `colorBgContainer` | `#FFFFFF` | 表单、表格、卡片 |
| 主文字 `colorText` | `#0F172A` | 标题、正文 |
| 次文字 `colorTextSecondary` | `#596579` | 说明、时间与元信息 |
| 结构分隔线 `colorBorderSecondary` | `#E2E8F0` | 非交互分隔，不作为唯一控件边界 |
| 控件边界 `colorBorder` | `#8290A3` | 输入、选择等必须可识别的边界 |
| 成功 `colorSuccess` | `#047857` | 操作成功、完成状态 |
| 警告 `colorWarning` | `#92400E` | 即将到期、需要注意 |
| 错误 `colorError` | `#B42318` | 失败、逾期、危险操作 |
| 信息 `colorInfo` | `#1D4ED8` | 信息提示、排期 |
| 验证状态 | `#6D28D9` | 待验证、待关闭；统一 StatusTag 配色 |

以上主色与语义文字在白底上的对比度均超过 4.5:1，控件边界对比度约 3.25:1。衍生的 hover、浅底标签、禁用、focus 与选中组合仍需按最终页面复核，不能只验证种子色。

| 类别 | 规范 |
|---|---|
| 字体 | 系统字体栈：`-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif`；私网部署不加载外部字体 |
| 字号 | 正文/表单 14px，辅助 12px，区块标题 18px，页面标题 24px；正文行高 1.6 |
| 间距 | 4、8、12、16、24、32、48px；同级区块 24px，字段间 16px |
| 控件 | 桌面默认高 36px；触屏可点击区域至少 44×44px；不以全局 compact 压缩主要业务操作 |
| 圆角 | 控件 6px、卡片 8px、对话框 12px、状态标签胶囊形；不用多套任意圆角 |
| 阴影 | 普通卡片用边框；浮层使用组件库阴影，避免每个区块都有悬浮效果 |
| 焦点 | 清晰可见，2px 主色轮廓、2px offset；不移除键盘焦点 |
| 动效 | 简短的组件反馈，遵循 `prefers-reduced-motion`；不增加装饰性循环动画 |

应用根设置简体中文 locale，日期控件同时设置 Day.js locale。`message`、`notification`、`modal` 使用 `App.useApp()` 的上下文实例，使主题、locale 和反馈一致。

## 4. 页面布局与导航

| 视口 | 导航与内容 |
|---|---|
| ≥1200px | 左侧导航 224px，顶部账号区 56px；内容左右留白 24px，最大宽度 1600px |
| 768–1199px | 左侧导航收起至 64px，提供完整可访问名称与焦点提示；内容留白 16px |
| <768px | 顶部菜单按钮打开导航 Drawer；宽度不超过 280px / 视口减 48px；内容留白 12px，单列布局 |

顶部只展示产品、当前账号与退出等全局信息。页面正文采用“面包屑 → 标题与状态 → 简短说明/主操作 → 内容区”。每个操作区域突出一个主操作，其他操作用次按钮或更多菜单。危险操作不与主操作相邻，原因必填的动作使用明确表单。

顶级导航固定为：我的工作 `/me/workbench`、审查活动 `/review-cases`、通知 `/me/notifications`、管理视图 `/management`；系统管理员另有管理设置 `/admin`。系统管理员导航可见只说明平台管理身份，不授予业务权限。

计划从审查活动的新建入口进入，随后在计划上下文创建 Case。当前没有独立计划列表、全局 Finding 列表或全局 Action 列表路由，不为这些页面预留空白菜单。Finding、Action 和管理进度由上级上下文、工作台与通知进入，保留现有深链接。

详情页 ≥1200px 时允许“主内容 + 320px 上下文栏”，较窄时顺序堆叠。表单默认单列，≥992px 才将彼此独立的短字段排为两列，长说明仍占整行。移动端列表使用关键字段卡片或表格内部滚动；整页不横向溢出。返回路径保留用户原有筛选、页码和标签页。

## 5. 页面信息架构与整改范围

| 页面 / 现有路由 | V1 信息顺序与交互 | 实施阶段 |
|---|---|---|
| 登录 `/login`、首次改密 | 居中单列表单，明确密码要求、限流与 Session 失效反馈；支持密码管理器 | UI-2 |
| 我的工作 `/me/workbench` | 先待验证与我的整改/执行责任，再逾期、即将到期、参与活动；每项给出状态、责任与进入入口 | UI-2 |
| 审查活动 `/review-cases` | 可访问的活动集合、后端支持的筛选与分页；“新建计划”作为创建入口 | UI-2 |
| 新建计划 `/review-plans/new`、计划下新建 Case | 清晰的计划 → 场景精确版本 → 案例信息流程；场景字段按适配器呈现；保留表单草稿和幂等键 | UI-3 |
| Case `/review-cases/:caseId` | 概览、审查发现、团队、活动记录；生命周期命令单独操作区；管理进度保留授权上下文入口 | UI-3 |
| Finding `/findings/:findingId` | 页头状态/下一步；概览、整改项、提交与验证、参与人、活动记录分区；创建/编辑表单按需展开 | UI-3 |
| Action `/action-items/:actionItemId` | 任务说明、责任人、截止日期、证据列表、活动；上传与执行命令分别呈现 | UI-3 |
| 通知 `/me/notifications` | 未读/已读、发生时间、业务摘要与对象入口；标记已读不等同完成业务动作 | UI-2 |
| 管理视图 `/management`、案例进度详情 | 支持的筛选 → 快照时间 → 进度/逾期表格 → CSV/XLSX 导出；展示统计口径 | UI-2 |
| 管理设置 `/admin/*` | 部门、用户、场景分为标签页；新增/编辑用 Drawer；重置凭证单独确认并按现有规则处理结果 | UI-3 |

页面不展示开发里程碑、内部文件路径、权限键或存储键作为主要文案。UUID、SHA-256 等确有排障价值的字段置于可复制的次级详情；Evidence 存储键不在普通产品界面展示。无权限或不存在时不能暴露对象标题、负责人等信息。

名称只来自用户当前获授权的接口响应与候选集合。缺少名称时显示“名称暂不可用”及次级短 ID，不使用管理员用户目录给普通用户补名。名称选择器或计划查询缺少授权读接口时，另开读侧设计 PR；不得通过猜测接口或抓取当前一页数据伪装完整候选集。

管理视图当前支持 `review_plan_id`、`lifecycle`、`deadline_status` 和分页。计划 ID 优先来自授权上下文深链接；按名称选计划需要相应读接口，不能将 UUID 输入框作为常规主要操作。暂不添加后端尚未支持的全局文本搜索、任意排序与筛选。导出使用当前查询的相同筛选，不只导出当前页。工作台统计仅使用后端投影，不从分页条数推导全局 KPI。

## 6. 组件使用规则

| 场景 | 标准组件 / 语义封装 |
|---|---|
| 应用框架 | `Layout`、`Menu`、`Breadcrumb`；`PageHeader` 语义封装（非依赖旧版同名组件） |
| 数据集合 | `Table`、`Pagination`；移动端关键字段卡片；后端分页与查询状态受控 |
| 表单 | `Form`、`Input`、`Input.Password`、`Input.TextArea`、`Select`、`DatePicker`；有明确 label |
| 详情组织 | `Tabs`、`Card`、`Descriptions`、`Collapse`；不重复用卡片嵌套卡片 |
| 状态 / 期限 | `Tag` / `Badge`；统一 `StatusTag`、`DeadlineText` |
| 加载 / 空 / 失败 | `Skeleton`、`Empty`、`Result`、`Alert`；统一 `QueryState` |
| 普通编辑 | `Drawer`，桌面宽约 480px、移动端全宽；关闭前处理未保存内容 |
| 正式确认 | `Modal`；简单无输入确认可用 `Popconfirm`；驳回/取消/重开原因使用表单 |
| 操作反馈 | `Button` + loading、上下文 message / notification；重要错误保留在当前区域 |
| Evidence 选择 | `Upload` 仅负责受控选择和文件列表；网络传输按第 9 节适配 |

优先直接使用组件库，只有重复的业务语义需要薄封装。`PageHeader`、`StatusTag`、`QueryState`、`NameLabel`、`DeadlineText`、`EvidenceList` 是拟新增语义组件，不是新建通用 UI 框架。功能专属组件和数据 hooks 放在对应 `features/` 中，页面负责组合；共享组件不依赖某个场景的角色或命令。

新增主题/图标/语义组件集中于 `web/src/ui/`。Finding 页按概览、参与人、整改项、提交、活动和命令拆分；Case 与 Admin 同样按信息区拆分。沿用 `web/src/api/`、精确版本的场景适配层与现有 Session 流程，不为本次视觉迁移新增全局状态框架。

CSS 保留 reset、布局、可访问性和少量功能样式。迁移页停止使用泛化的全局 `button`、`input`、`select` 等规则覆盖组件库；已迁移的重复规则及时删除，全部迁移后移除 `final-polish.css` 的补丁层。未迁移页的临时旧样式必须限定作用域，避免影响新组件。

## 7. 图标规范

应用自选图标以 Outlined 为主，16px 用于行内操作、18px 用于导航、20px 用于页头。图标颜色继承文字或语义色；同一动作全项目使用同一图标。组件库内部的状态图标沿用默认，不为统一轮廓而破坏其语义。

| 语义 | 图标 |
|---|---|
| 我的工作 / 审查活动 | `DashboardOutlined` / `AuditOutlined` |
| 管理视图 / 通知 / 管理设置 | `BarChartOutlined` / `BellOutlined` / `SettingOutlined` |
| 计划 / 团队 / 人员 | `ScheduleOutlined` / `TeamOutlined` / `UserOutlined` |
| 新建 / 编辑 / 更多 | `PlusOutlined` / `EditOutlined` / `MoreOutlined` |
| 上传 / 下载 | `UploadOutlined` / `DownloadOutlined` |
| 查询 / 刷新 / 返回 | `SearchOutlined` / `ReloadOutlined` / `ArrowLeftOutlined` |
| 确认 / 取消 | `CheckOutlined` / `CloseOutlined` |

在 `web/src/ui/icons.ts` 中用具名 import/export 管理选用图标，不整体导入图标包、不使用外部 iconfont CDN。品牌标识可独立维护；一般操作不混用 emoji、其他图标库或手绘 SVG。图标与文字并用时作为装饰隐藏于辅助技术；纯图标按钮必须有准确的 `aria-label` 和可聚焦的说明，不能只依赖鼠标 hover。

## 8. 业务文案、状态与时间

产品文案使用“审查计划、审查活动、审查发现、整改项、证据、正式提交、验证、活动记录”。接口类型保留 ReviewPlan、ReviewCase、Finding、ActionItem 等名称；UI 不直接用去掉下划线的英文枚举作为状态标签。

| 对象 | 接口状态 → 中文标签 / 语义色 |
|---|---|
| Case | `draft` → 草稿/灰；`scheduled` → 已排期/蓝；`in_progress` → 审查中/青；`awaiting_closure` → 待关闭/紫；`closed` → 已关闭/绿；`cancelled` → 已取消/灰 |
| Finding | `open` → 待处理/蓝；`rectifying` → 整改中/青；`verifying` → 待验证/紫；`closed` → 已关闭/绿；`voided` → 已作废/灰 |
| Action | `todo` → 待开始/蓝；`in_progress` → 执行中/青；`done` → 已完成/绿；`cancelled` → 已取消/灰 |
| 截止日期 | `overdue` → 逾期/红；`due_soon` → 即将到期/警告色；正常显示日期，无需绿色徽标 |

`open` 使用“待处理”，兼容合规场景的 observation 直接确认关闭；具体下一步由精确场景适配器描述。状态色必须配文字，未知状态显式显示“未知状态”及次级原值，不假定它可执行某个动作。未知场景版本按架构规则拒绝解释。

角色名称由精确场景适配器统一映射，保留多重身份；部门成员的可见性不解释成整改写权限。按钮使用“新建整改项”“提交完成情况”“通过验证”等明确动词，按对应命令和输入区分提交，不用一排无上下文的“确认”。

日期统一使用简体中文格式。V1 展示时区固定为 `Asia/Shanghai`，管理快照和日期表单显式标注；API 传输保持原有 ISO 时间语义，日期控件输入也按该时区解析，不默默采用设备时区。若部署调整导出/提醒时区，前端展示配置同步调整并由部署文档说明。统计标明后端 `as_of`，期限判定使用后端结果；不添加 `Finding.due_at`，不自算百分比进度或伪造指标。

## 9. 表单、请求与交互状态

表单 label 常驻，必填与输入提示靠近字段；placeholder 只给示例。服务端 422 能定位字段时就地展示，否则使用表单级 Alert；保留已填内容，聚焦第一个错误。Scenario 字段与校验来自精确版本适配器，不能把页面样式迁移变成通用表单构建器。

| 状态 / 响应 | UI 行为 |
|---|---|
| 首次加载 / 刷新 | 首次用 Skeleton；普通刷新保留已授权内容并提示刷新中；Session 或权限失效立即移除受保护内容 |
| 无数据 / 筛选无结果 | 分别解释尚无业务数据与筛选无结果，提供有权限且真实可用的入口或清除筛选 |
| 写入中 / 成功 | 只锁定相关操作区，防重复提交；成功后刷新相关查询，再呈现最终业务状态 |
| 401 | 沿用 Session 失效处理和安全的站内返回路径；不持久化敏感草稿 |
| 403 / 404 | 根据现有错误语义显示当前资源不可访问或不存在；不透露对象存在性或猜测身份 |
| 409 | 刷新只读数据，说明数据已变化；用户重新确认后手动操作，不自动重放写请求 |
| 422 | 显示字段或业务规则反馈，不改写服务器规则 |
| 上传 413 / 415 | 显示文件大小/类型限制，保留可修正的表单内容 |
| 登录 429 / 暂时不可用 503 | 有 `Retry-After` 时据此提示；由用户手动重试，不自动发送写请求 |
| 网络错误 / 500 / 结果未知 | 清楚说明未确认成功；提供人工核对/重试路径，必要时显示可复制 request_id；不显示内部堆栈 |

新建 Plan/Case 的 `Idempotency-Key` 与表单生命周期保持一致。迁移到 Form、Drawer 或 Modal 后，重复点击、网络失败与用户手动重试仍复用同一键，不因组件关闭/重新挂载自动生成新键并重放结果未知的创建。确需改变请求内容时按现有冲突语义提示，不能无提示轮换键。

Evidence Upload 不能直接配置 Ant Design `Upload.action` 发 multipart 请求。采用 `beforeUpload` 阻止自动传输、受控文件列表和明确“上传”操作，经现有 `uploadActionEvidence` / API client 发送文件原始字节，保留 MIME、编码文件名与描述协议；服务器生成存储键、大小和哈希。文件白名单与 25 MiB 默认值以部署配置为准，前端预校验只是辅助；不能编造上传百分比。网络中断后不自动重传。

Evidence 下载沿用同源 `GET /api/v1/evidences/{id}/content` 附件链接，不为展示控件把文件全文读入 JS Blob，也不暴露对象存储路径。管理 CSV/XLSX 导出沿用现有下载适配器和筛选。页面反馈区的临时提示与通知中心的持久投递记录是两类信息，不能混用。

筛选、分页、可分享的标签页状态使用路由 query 参数，并只发送现有 API 支持的参数。Modal / Drawer 打开后正确管理焦点，关闭后返回触发点；复杂整改/验证内容保留在页面区，不塞入巨大确认框。

## 10. 可访问性、浏览器与验证

质量目标采用 WCAG 2.2 AA 的关键要求：正常文字对比度 ≥4.5:1、大文字 ≥3:1、控件边界和焦点 ≥3:1；操作可用键盘完成，状态不只靠颜色，表单有关联 label，页面有明确 main / nav、一个 h1 和顺序合理的标题。目标不等同于本次已获得认证。

UI-1 记录实际试点浏览器版本，验证组件安装、typecheck、lint、测试、production build、样式与图标、locale、弹层和日期输入。记录接入前后构建体积；发现首屏明显退化时再按路由拆包，不预先增加复杂框架。

逐页 PR 更新有变化的用户旅程测试，并在 PR 描述附同一数据状态下的前后截图。以 375、768、1280、1440px 和 200% 缩放复核布局、焦点、长标题、长文件名、空数据与错误状态；对比度按最终组合检查。截图属于 PR 评审材料，不新增阶段状态文件或审查证据包。

UI-4 运行现有 frontend / browser-acceptance 检查及真实 FastAPI + PostgreSQL 的浏览器旅程，覆盖两个场景、登录改密、计划/Case 幂等重试、团队与责任人、整改证据上传下载、正式提交、通过/驳回、通知、管理导出。对授权丢失、跨组织隐藏、409 冲突和上传失败保留有意义的回归测试。CI 中已有浏览器项目通过，不能代表未运行的所有浏览器都已验证。

受控试点前由代表性审查、整改、验证、管理人员走通自己的核心操作，确认文案和入口可理解；结论与未解决问题记录在 PR/Issue。实现、测试与实际终端验证完成后，才将 UI 整理标记为已完成。

## 11. 文档职责与维护

| 文档 | 维护内容 |
|---|---|
| 本文件 | 视觉、页面、组件、图标与交互；发生长期设计变化时随实现 PR 更新 |
| [README.md](README.md) | 已实现能力、仍待完成事项、快速开始与文档入口 |
| [docs/architecture.md](docs/architecture.md) | 请求、授权、场景、并发和前端技术边界 |
| [docs/domain.md](docs/domain.md) | 已实现的领域事实，视觉改版不改写业务模型 |
| [docs/roadmap.md](docs/roadmap.md) | UI-1 到 UI-4 的顺序、工作量假设与试点里程碑 |
| [CONTRIBUTING.md](CONTRIBUTING.md)、[AGENTS.md](AGENTS.md) | 开发前阅读、PR 与验证要求 |
| [deploy/README.md](deploy/README.md) | 部署、备份恢复、运维与真实开放条件 |

不以文档声明代替库安装、页面实现或真实环境验证。新依赖、读侧接口与设计调整在对应 PR 描述中说明问题、方案、替代选择及影响；一个 PR 保持单一关注点。

## 官方依据（2026-10-02 核对）

- [Ant Design 版本记录](https://ant.design/changelog/)、[package.json 与许可证](https://github.com/ant-design/ant-design/blob/master/package.json)：组件接入版本与 MIT。
- [Ant Design Icons package.json](https://github.com/ant-design/ant-design-icons/blob/master/packages/icons-react/package.json)、[图标文档](https://ant.design/components/icon/)：图标版本、MIT 与具名使用方式。
- [v6 兼容性说明](https://ant.design/docs/react/migration-v6/)、[主题](https://ant.design/docs/react/customize-theme/)、[国际化](https://ant.design/docs/react/i18n/)、[App 上下文](https://ant.design/components/app/)、[Upload](https://ant.design/components/upload/)、[DatePicker](https://ant.design/components/date-picker/)：接入边界。
- [Day.js 许可证](https://github.com/iamkun/dayjs/blob/dev/LICENSE)：日期适配依赖的 MIT 声明。
- [shadcn/ui 官方介绍](https://ui.shadcn.com/docs)：备选组件维护方式。选用 Ant Design 是针对本项目的维护成本判断。
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/)：可访问性质量依据。
