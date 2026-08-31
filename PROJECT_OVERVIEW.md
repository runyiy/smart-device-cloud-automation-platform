# PROJECT OVERVIEW

**Smart Device Cloud & Automation Platform**

- 文档定位：V0-V6 共同读取的跨阶段架构与依赖摘要
- 主线难度：约 1 年后端工程经验
- 使用方式：每个新阶段 Work 读取一次；阶段内 Task 不重复读取；Final Review 再读取一次
- 详细范围：见当前 `plans/Vx.md`

## 1. 项目最终目标与岗位覆盖

构建面向智能设备研发与测试团队的云端平台：统一管理设备，采集心跳与遥测，生成告警，远程发送命令，并将这些能力编排为可重复的自动化测试任务与报告，最终部署到成本可控的 AWS 演示环境。

主线以 Python Backend 为核心，覆盖：

- Python Backend Engineer
- IoT Backend / IoT Platform Backend Engineer
- Device Platform Backend Engineer
- 智能硬件自动化 / Test Development Engineer
- Automation Test Platform Engineer
- 初级 Cloud Backend Engineer

项目证据重点是事务、状态、可靠性、协议、测试和运维，而不是技术名词数量。

## 2. V0-V6 超简路线

- V0：FastAPI、配置、PostgreSQL、SQLAlchemy、Alembic、日志和测试基线。
- V1：Device、Telemetry、Alert、TestTask 的同步业务闭环。
- V2：Service/Repository/事务边界、JWT/RBAC、AuditLog、Docker 与 CI 基线。
- V3：Redis、Celery、幂等重试、设备状态和 WebSocket。
- V4：MQTT、Device Simulator、心跳/遥测接入和命令闭环。
- V5：TestCase、Test Runner、执行结果和报告。
- V6：AWS、CI/CD、Observability、回滚与恢复演练。

## 3. 整体架构演进

```text
V0-V2  Client -> FastAPI modular monolith -> PostgreSQL
V3     Client -> FastAPI -> PostgreSQL / Redis -> Celery -> WebSocket
V4     Simulator <-> MQTT <-> Ingestion/Publisher -> Service -> DB/Redis
V5     TestTask -> Queue -> Test Runner -> Command/Telemetry -> Report
V6     AWS IoT Core + ECS + RDS + ElastiCache + S3 + CloudWatch
```

阶段只增加当前问题需要的能力；不为未来版本预建空模块，也不为云部署重写业务架构。

## 4. Architecture Invariants / 全局架构不变量

1. **模块化单体优先。** V0-V6 主线保持单仓库、清晰模块边界和可独立运行进程，不拆微服务。
2. **PostgreSQL 是事实源。** 业务实体、命令状态、执行证据和关键变化必须可从数据库恢复。
3. **Redis 不是唯一事实源。** Redis 只承载缓存、短期状态、锁、幂等键和事件传递；丢失后可重建。
4. **MQTT 不是业务数据库。** Broker 只负责设备消息传递；可靠业务状态必须落库。
5. **WebSocket 不是唯一读取渠道。** REST 返回当前快照，WebSocket 只推送增量；断线后可补齐。
6. **Service 不依赖 FastAPI。** Service 不接收或返回 FastAPI Request/Response，可被 HTTP、Celery、MQTT ingestion 与 Test Runner 复用。
7. **Repository 不自行 commit。** Repository 只执行查询与持久化操作；一次业务用例由统一事务边界 commit/rollback。
8. **入口与执行机制不拥有业务规则。** Router、worker、scheduler、MQTT consumer/publisher、Runner 负责适配与调度，业务规则仍在 Service。
9. **先提交再投递。** 依赖数据库数据的异步任务只在事务成功后发布；重复投递必须安全。
10. **所有时间统一 UTC。** API、数据库、日志、消息和报告使用时区明确的 UTC 时间。
11. **状态转换显式。** Device、Alert、Command、TestTask、Execution 等状态只允许定义过的转换，并测试非法转换。
12. **可靠性必须可测试。** 幂等、重试、超时、乱序、掉线、回滚、恢复与资源竞争都要有自动测试或可重复演示。
13. **关联 ID 贯穿链路。** request_id、message_id、command_id、execution_id 按场景跨 API、任务、MQTT、日志和报告传播。
14. **配置与密钥外置。** 环境差异通过配置解决；真实密钥不进仓库、不进日志。
15. **迁移是唯一数据库演进路径。** 不依赖手工改库；部署迁移独立、失败可停止、必要时可回退。
16. **用户实现核心代码。** ChatGPT 负责 Design Brief、Skeleton、Acceptance Criteria、TODO 与严格 Review，默认不代写完整业务实现。

## 5. Future Dependency Map / 跨阶段依赖图

```text
V0 工程基线
 └─> V1 领域模型与同步闭环
      └─> V2 可复用 Service + Repository + Transaction + Auth
           └─> V3 Worker/Redis/WebSocket 复用 Service
                └─> V4 MQTT 适配层 + Command/Telemetry 闭环
                     └─> V5 Runner 编排 Command/Telemetry
                          └─> V6 原架构云端部署与运维证据
```

关键兼容关系：

- V1 的实体标识、UTC 时间和状态语义是 V3-V5 的基础。
- V2 的 Service/事务边界必须同时服务 HTTP、worker、MQTT 和 Runner。
- V3 的幂等任务、可重建状态与实时事件被 V4/V5 直接复用。
- V4 的协议、命令生命周期和模拟器是 V5 自动化执行的底座。
- V5 的不可变执行证据、报告 URI 和关联日志进入 V6 的 S3、CloudWatch 与故障演练。

## 6. Complexity Guardrails

- 每个版本必须可运行、可测试、可演示；上一阶段 Final Pass 后再进入下一阶段。
- 新技术必须解决当前版本已出现、且能通过测试证明的问题。
- 抽象必须服务真实用例；不创建万能 BaseRepository、空接口或后续版本占位目录。
- 默认目标为单团队、轻量多用户、1-100 台模拟设备的可信演示，不做商业 SaaS 或百万设备优化。
- 模拟设备优先；真实硬件只做小验证，不让硬件采购与调试阻塞主线。
- 自动化测试只服务设备命令与遥测，不演变为通用 CI/Jenkins 平台。
- 云端只部署一套成本受控的 dev 环境，先证明部署、监控、回滚和恢复。

主线禁止提前加入：

- 微服务、Kubernetes/EKS、Service Mesh
- Kafka/MSK、复杂流处理
- CQRS、Event Sourcing、复杂 DDD
- 完整多租户、计费、复杂 IAM/策略引擎
- 可视化拖拽编排、任意脚本执行、插件市场
- 完整 OTA、PKI、Device Shadow、真实硬件矩阵
- 多区域主动-主动、企业级蓝绿平台、过早性能优化

## 7. 长期验证与交付原则

- 测试分层：Service/Repository/API/worker/协议/e2e 按风险选择真实边界，核心数据链路使用 PostgreSQL 集成测试。
- 每个 Task 只在 Local Code Review 得到 `PASS` 后 commit/push。
- 每个阶段以当前 `plans/Vx.md` 的 Definition of Done 做 Final Phase Review。
- Final Review 结果只能是 `Vx FINAL PASS` 或 `Vx FINAL CHANGES REQUIRED`。
- GitHub 主要用于远端备份、历史、portfolio、CI、tags 与 releases；本地仓库是开发和审查主场。
- 任何简历性能数字必须来自真实测量，不写无条件的“高并发”。

## 8. 项目边界与后续扩展

主线不覆盖商业计费、制造/供应链/售后、完整 OTA、通用 CI 或复杂前端大屏。

V6 完成后只选一个 4-8 周扩展分支：Industrial IoT、Smart Home/AIoT、Device Lab，或 Go Device Gateway。扩展不得破坏 V0-V6 稳定主干。
