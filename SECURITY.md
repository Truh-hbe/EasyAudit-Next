# Security Policy

本仓库当前指引的使用范围是 **Development（开发）与 Controlled private-network pilot（经维护者批准的受控私网试点）**。试点开放由维护者决定，见 [路线](docs/roadmap.md)。这不是 GA、Production Ready 或通用生产支持声明。

仓库已提供私网 HTTPS 部署拓扑、备份/恢复工具、恢复演练、健康检查与结构化日志，操作入口为 [deploy/README.md](deploy/README.md)。这些是 repository capabilities；CI 上的结果不能证明任何特定部署已经取得资格。

**General production support：NOT ESTABLISHED。** 目标机器仍需以实际版本、数据量、存储、备份新鲜度、恢复演练及升级失败处理证据完成 operational qualification，并由维护者决定是否开放。目标机 RPO/RTO 达标、异地备份、备份加密及外部告警接收情况在没有现场证据时均为 UNVERIFIED，不预填“达标”。

配置与凭证生效、轮换和未建立的服务端轮换流程见 [配置参考](docs/operations/configuration.md)。不要把替换宿主机 secret 文件视为已经完成 PostgreSQL/Garage 凭证轮换。

请不要在公开 Issue 中提交账号、访问令牌、审查证据、附件或其他敏感数据。安全问题应通过仓库维护者的私密联系方式报告。
