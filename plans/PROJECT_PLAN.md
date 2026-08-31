# 智能设备云端管理与自动化测试平台

**Smart Device Cloud & Automation Platform**

- 文档版本：Version 1.0
- 状态：可执行基线
- 发布日期：2026-08-29
- 主线难度：约 1 年工作经验

> 核心决定：先做模块化单体的设备云端平台，再逐步加入异步、MQTT、自动化测试和 AWS。每个版本必须可运行、可测试、可演示，上一版完成后再进入下一版。

## 0. 如何使用

每个阶段都能独立开一个新聊天执行。只复制对应阶段的“新聊天启动提示词”，让新聊天先检查仓库现状，再实现、测试并回报。不要一次完成 V0-V6。每阶段完成后打 Git tag，并更新本文变更记录。

## 1. 为什么这个项目最适合当前方向

它以 Python Backend 为主干，用设备、遥测、告警、命令、MQTT、自动化测试和云部署形成一条连续业务故事，同时覆盖 IoT Backend、Device Platform Backend、智能硬件自动化、自动化测试平台和 Cloud Backend。重点不是技术名词数量，而是事务、状态、可靠性、协议、测试和运维证据。

## 2. 愿景、用户场景与边界

### 愿景

构建面向智能设备研发与测试团队的云端平台：统一管理设备、采集遥测与心跳、生成告警、远程发送命令，并把这些能力编排成可重复的自动化测试任务与报告。

### 核心场景

1. 注册设备 -> 接收心跳/遥测 -> 计算在线状态 -> 触发告警。
2. 用户发起命令 -> 平台下发 -> 设备确认/执行 -> 保存结果与超时。
3. 选择 TestCase 和设备 -> Runner 执行命令/等待遥测/断言 -> 生成报告。

### 边界

- 单团队、轻量多用户；不做商业 SaaS 计费和复杂租户隔离。
- 模拟设备优先；真实硬件只做小验证。
- 不做制造、供应链、售后和完整 OTA。
- 自动化测试只覆盖设备命令与遥测，不替代通用 CI。

## 3. 第一版明确不做

- 微服务、Kubernetes/EKS、Kafka。
- 复杂 DDD、CQRS、事件溯源。
- 完整多租户、计费、复杂 IAM。
- 复杂前端大屏、真实硬件矩阵、完整 OTA/PKI。

> 复杂度护栏：新技术如果不能解决当前版本已出现且可被测试证明的问题，就先不加入。

## 4. 推荐技术栈

- Python 3.12、FastAPI、Pydantic v2。
- PostgreSQL、SQLAlchemy 2.x、Alembic。
- Redis、Celery、WebSocket。
- MQTT、Mosquitto、paho-mqtt。
- pytest、Docker/Compose、GitHub Actions。
- AWS ECS/RDS/ElastiCache/IoT Core/S3/CloudWatch。

语言策略：主线只用 Python。Go 仅在主线完成后用于 Device Gateway 扩展。

## 5. 架构演进

```text
V0-V2: Client -> FastAPI modular monolith -> PostgreSQL
V3:    Client -> FastAPI -> PostgreSQL / Redis -> Celery -> WebSocket
V4:    Simulator <-> MQTT <-> Ingestion/Publisher -> Service -> DB/Redis
V5:    TestTask -> Queue -> Test Runner -> Command/Telemetry -> Report
V6:    AWS IoT Core + ECS + RDS + ElastiCache + S3 + CloudWatch
```

核心原则：模块化单体；PostgreSQL 为事实源；REST 快照 + WebSocket 增量；所有可靠性设计必须可测试演示。

## 6. 主线节奏

按每周 8-12 小时，主线约 7-10 个月，另留 1-2 个月补漏、准备面试材料和真实硬件/云端演示。


# V0 项目骨架与基础后端

- 建议周期：1-2 周
- 阶段定位：先证明你能把一个可运行、可迁移、可测试的 Python 后端从零搭起来。

## 阶段目标

- 建立单仓库、模块化单体项目骨架，形成以后所有版本都沿用的工程基线。
- 打通 FastAPI -> Service -> SQLAlchemy -> PostgreSQL 的最小链路。
- 让项目可以通过一条命令启动，并具备健康检查、配置、迁移和基础日志。

## 要实现的核心功能

- FastAPI 应用入口、/health 与 /api/v1/ping。
- 统一配置管理：开发、测试环境分离，敏感信息只从环境变量读取。
- PostgreSQL 连接、SQLAlchemy 2.x Session、Alembic 初始迁移。
- 统一响应错误结构、请求 ID、基础结构化日志。
- README：环境准备、启动、迁移、测试和目录说明。

## 数据模型 / 模块

- app/main.py：应用创建和生命周期。
- app/core/config.py、logging.py、errors.py：横切基础能力。
- app/db/session.py、base.py：数据库连接和模型基类。
- app/api/v1/router.py：版本化路由。
- SystemInfo（可选只读响应模型）：version、environment、database_status。

## 核心 API 或事件流

- GET /health -> {status, version, database}
- GET /api/v1/ping -> {message: 'pong'}
- 启动 -> 加载配置 -> 建立数据库连接；请求 -> request_id -> 日志 -> 响应。

## 重点学习内容

- FastAPI 依赖注入与生命周期；Pydantic v2 Settings。
- SQLAlchemy 2.x Session、连接池和事务的最基本概念。
- Alembic migration、环境变量、HTTP 错误语义。

## 工程要求

- Python 3.12；使用 Ruff（lint/format）和静态类型检查（mypy 或 pyright 二选一）。
- pyproject.toml 统一管理依赖与工具配置；提交 .env.example，不提交真实 .env。
- 每次提交粒度小且信息清楚；主分支始终可启动。

## 测试要求

- health 与 ping 的 API 测试；数据库不可用时的健康检查测试。
- 配置加载单元测试；测试使用独立数据库或事务回滚隔离。
- 最低要求：pytest 一次通过，lint 一次通过。

## 完成标准（Definition of Done）

- 新机器按 README 可在 15 分钟内启动服务。
- 迁移可从空数据库升级到最新版本，也能回退最近一版。
- /health、/docs、pytest、lint 全部正常；日志中能看到 request_id。

## 常见风险

- 一开始追求完美目录，反复重构却没有业务。解决：只保留当前用得上的层。
- 把配置或密钥写进仓库。解决：环境变量 + .env.example + gitignore。
- 本地能跑但他人不能跑。解决：README 从空环境实测一次。

## 明确禁止提前加入

- 不要加入 Redis、Celery、MQTT、JWT、WebSocket。
- 不要做前端、微服务、Kubernetes、Kafka、复杂 DDD、通用框架封装。

## 下一阶段入口

当数据库迁移、测试和启动流程稳定后，进入 V1，用四个核心实体建立第一条真实业务闭环。

## 新聊天启动提示词

```text
我正在实现项目 Smart Device Cloud & Automation Platform 的 V0：项目骨架与基础后端。请先检查当前工作区/仓库现状，再按模块化单体方式完成 FastAPI、Pydantic Settings、SQLAlchemy 2.x、PostgreSQL、Alembic、统一错误、request_id、结构化日志、/health、/api/v1/ping、pytest、Ruff 和 README。请边实现边运行验证，保留我已有的改动。不要加入 Redis、Celery、MQTT、JWT、WebSocket、前端、微服务、Kubernetes、Kafka 或复杂 DDD。最后给出完成清单、运行命令、测试结果、目录说明和进入 V1 前仍需处理的问题。
```


# V1 Device / TestTask / Telemetry / Alert 基础业务

- 建议周期：3-4 周
- 阶段定位：建立“设备登记 -> 遥测写入 -> 告警产生 -> 测试任务跟踪”的最小业务闭环。

## 阶段目标

- 用清晰的数据模型表达设备平台最核心的业务对象。
- 完成可用的 CRUD、查询、分页、校验和基础业务规则。
- 通过 REST API 模拟设备和平台操作，为之后实时链路留出接口。

## 要实现的核心功能

- Device：注册、查询、更新、停用；记录型号、固件、逻辑状态和最后上报时间。
- Telemetry：通过 HTTP 接收温度、电量、信号等遥测；支持按设备和时间范围查询。
- Alert：按简单阈值规则产生 open 告警；支持 acknowledge/resolve。
- TestTask：创建人工/基础测试任务，记录目标设备、状态、开始结束时间和摘要。
- 统一分页、过滤、排序和 404/409/422 错误处理。

## 数据模型 / 模块

- Device(id, serial_number, name, model, firmware_version, status, last_seen_at, created_at)。
- Telemetry(id, device_id, metric, value, unit, recorded_at, received_at)。
- Alert(id, device_id, type, severity, status, message, triggered_at, resolved_at)。
- TestTask(id, device_id, name, status, requested_at, started_at, finished_at, summary)。
- 模块建议：devices、telemetry、alerts、test_tasks；暂时允许路由直接调用薄 Service。

## 核心 API 或事件流

- POST /api/v1/devices；GET /devices；GET/PATCH /devices/{id}。
- POST /api/v1/devices/{id}/telemetry；GET /devices/{id}/telemetry?metric=&from=&to=。
- GET /api/v1/alerts；POST /alerts/{id}/acknowledge；POST /alerts/{id}/resolve。
- POST /api/v1/test-tasks；GET/PATCH /test-tasks/{id}。
- 事件流（同步）：Telemetry API -> 保存遥测 -> 判断简单阈值 -> 必要时创建 Alert -> 返回结果。

## 重点学习内容

- 关系建模、外键、唯一约束、索引、时间字段与枚举状态。
- REST 资源设计、分页、过滤、幂等性与业务校验。
- Schema 与 ORM Model 分离；N+1、批量查询和基本查询性能。

## 工程要求

- 每个业务模块包含 model/schema/router/service（只在确实需要时拆分）。
- 所有时间统一使用 UTC；serial_number 唯一；数据库约束与应用校验双保险。
- OpenAPI 示例和错误响应可读；为后续版本保留 /api/v1。

## 测试要求

- 四类资源的正常、边界、冲突和不存在场景。
- 遥测触发/不触发告警；告警状态转换；非法 TestTask 状态转换。
- 数据库唯一约束、外键和时间范围查询；目标覆盖核心业务，不追求数字漂亮。

## 完成标准（Definition of Done）

- Swagger 中可完整演示：注册设备 -> 上传遥测 -> 产生并处理告警 -> 创建并完成 TestTask。
- 模型、迁移、索引、API 与测试一致；无手工改数据库步骤。
- README 增加业务演示脚本和示例请求。

## 常见风险

- Telemetry 表无限增长。当前只做索引和分页，不提前做时序数据库。
- 状态字段随意修改。使用明确状态机校验，但不引入状态机框架。
- 把 TestTask 做成 V5 的完整测试平台。当前只保存基础任务生命周期。

## 明确禁止提前加入

- 不要提前加入 JWT/RBAC、Repository/Unit of Work、Redis、后台任务或 MQTT。
- 不要引入 TimescaleDB、Elasticsearch、规则引擎、复杂多租户和前端大屏。

## 下一阶段入口

当业务闭环和测试稳定后进入 V2，补齐分层、事务、安全、容器化，使项目从“能用”变成“像真实团队工程”。

## 新聊天启动提示词

```text
请继续 Smart Device Cloud & Automation Platform 的 V1。先检查 V0 是否通过，再实现 Device、Telemetry、Alert、TestTask 四个基础业务模块，以及迁移、索引、分页、过滤、状态校验和完整 pytest。演示闭环必须是：注册设备 -> HTTP 上传遥测 -> 简单阈值产生 Alert -> acknowledge/resolve -> 创建并完成 TestTask。所有时间用 UTC，serial_number 唯一，API 使用 /api/v1。请运行迁移、测试和 lint。不要提前加入 JWT/RBAC、Repository、Unit of Work、Redis、后台任务、MQTT、TimescaleDB、规则引擎、复杂多租户或前端大屏。最后报告 API、模型、测试结果和 V2 入口。
```


# V2 工程化分层、安全、测试与容器化

- 建议周期：4-5 周
- 阶段定位：把 V1 的业务代码整理成可维护、可协作、可部署的真实后端工程。

## 阶段目标

- 建立清楚但不过度抽象的 Router -> Service -> Repository 分层。
- 用事务边界保证跨表业务一致性，并实现 JWT 与 RBAC。
- 完善 pytest 分层测试、Docker Compose 和自动质量检查。

## 要实现的核心功能

- Repository 封装业务所需查询；Service 承担规则；Transaction/Unit of Work 管理一次用例的提交与回滚。
- User、Role 与登录；JWT access token；admin/operator/viewer 三种角色。
- 设备、告警、任务 API 按权限控制；写操作记录 audit log。
- Dockerfile + Docker Compose：api、postgres；测试可在容器或本地一致运行。
- pytest fixtures、factory、覆盖率报告；CI 先做 lint + test（可在本阶段末加入）。

## 数据模型 / 模块

- User(id, email, password_hash, is_active, created_at)。
- Role 与 user_roles（若只做固定角色，也可先用 enum）。
- AuditLog(id, actor_id, action, resource_type, resource_id, metadata, created_at)。
- Repository：只为 Device/Telemetry/Alert/TestTask/User 提供实际查询，不做万能 BaseRepository。
- UnitOfWork/transaction context：一个业务用例一次 commit，异常自动 rollback。

## 核心 API 或事件流

- POST /api/v1/auth/login；GET /auth/me。
- admin：用户和设备管理；operator：设备操作、告警和任务；viewer：只读。
- 用例流：请求 -> JWT 校验 -> RBAC -> Service -> Repository(同一事务) -> AuditLog -> commit。

## 重点学习内容

- 依赖倒置的实用边界、事务隔离、并发更新和异常回滚。
- 密码哈希、JWT 过期、鉴权与授权的区别、最小权限原则。
- pytest fixture scope、mock 的边界、集成测试与单元测试的取舍。
- Docker 镜像分层、容器网络、健康检查和启动依赖。

## 工程要求

- 不允许 Router 直接写数据库；Service 不依赖 FastAPI Request/Response。
- 事务由用例边界控制，Repository 不自行 commit。
- 密码不得明文存储；日志不得打印 token/密码；依赖版本锁定。
- docker compose up 后自动可用，迁移有明确执行方式。

## 测试要求

- Repository 集成测试、Service 单元/集成测试、API 端到端测试。
- JWT 过期/伪造/缺失；三种角色的允许与拒绝矩阵。
- 事务中途失败时所有写入回滚；审计日志只在成功动作后形成。
- 容器启动 smoke test；CI 中 lint 和 pytest 通过。

## 完成标准（Definition of Done）

- 关键业务没有跨层泄漏；权限矩阵有文档和自动测试。
- 一次命令启动 API + PostgreSQL；新开发者按 README 可复现。
- 故意制造异常能够证明事务回滚；安全日志检查通过。

## 常见风险

- 为了“架构”创建大量接口和空类。解决：每个抽象必须有两个以上真实用例或明确测试收益。
- JWT 做得过大。当前只做 access token；refresh token 可延后。
- mock 过多导致测试不可信。核心数据链路必须有真实 PostgreSQL 集成测试。

## 明确禁止提前加入

- 不要做 OAuth2 第三方登录、完整 IAM、动态策略引擎、复杂多租户。
- 不要加入 Redis/Celery/WebSocket/MQTT，也不要拆微服务。

## 下一阶段入口

V2 的接口和事务边界稳定后进入 V3，把耗时工作移到后台，并建立可解释的在线状态和实时推送。

## 新聊天启动提示词

```text
请继续 Smart Device Cloud & Automation Platform 的 V2。先审查 V1 的耦合点，再用务实的 Router -> Service -> Repository 分层和统一事务边界重构；实现 User、JWT access token、admin/operator/viewer RBAC、AuditLog、pytest 分层测试、Dockerfile、Docker Compose 和 CI 的 lint/test。Repository 不得自行 commit，不要创建万能 BaseRepository；核心链路用真实 PostgreSQL 集成测试，密码和 token 不得进入日志。不要加入 Redis、Celery、WebSocket、MQTT、微服务、OAuth 第三方登录、复杂 IAM/多租户。请直接修改并验证，最后给出权限矩阵、事务回滚证据、容器启动方式和 V3 入口。
```


# V3 Redis / Background Tasks / WebSocket / 设备状态

- 建议周期：4-5 周
- 阶段定位：学习设备平台最常见的异步、缓存和实时状态问题，同时仍保持模块化单体。

## 阶段目标

- 引入 Redis 与后台任务，把非即时工作从 API 请求中剥离。
- 建立设备 online/offline/unknown 状态的可解释计算规则。
- 通过 WebSocket 推送设备状态和告警变化。

## 要实现的核心功能

- Redis 存储短期状态、分布式锁/幂等键（只在需要处使用）。
- Celery worker 执行告警评估、离线扫描、通知模拟和周期清理。
- 设备状态：最近心跳/上报时间 + 超时阈值推导 online/offline/unknown。
- WebSocket：订阅设备状态与告警事件；断线重连后通过 REST 补齐快照。
- 任务状态查询和失败重试；死信以数据库失败记录代替复杂消息系统。

## 数据模型 / 模块

- DeviceStatusSnapshot(device_id, status, last_seen_at, reason, calculated_at) 可存 Redis，关键变化落库。
- BackgroundJob(id, type, status, attempts, error, started_at, finished_at)（只跟踪重要任务）。
- 模块：app/tasks、app/realtime、app/cache；Celery 与 API 复用同一 Service。
- Redis key 规范：device:{id}:presence、idempotency:{key}、ws:events。

## 核心 API 或事件流

- GET /api/v1/devices/{id}/status；POST /devices/{id}/status/recalculate（管理员调试）。
- GET /api/v1/jobs/{id}；WS /api/v1/ws/events?token=...。
- 流：遥测写入 -> 提交事务 -> 投递 alert_evaluation -> worker -> Alert -> 发布 Redis event -> WebSocket fan-out。
- 周期流：scheduler -> scan_offline_devices -> 比较 last_seen_at -> 状态变化 -> 落库/事件。

## 重点学习内容

- 请求-响应与异步任务的边界；at-least-once、幂等、重试和退避。
- Redis 数据结构、TTL、缓存失效；为什么缓存不能成为唯一事实来源。
- WebSocket 连接管理、鉴权、心跳、重连和背压的基本处理。

## 工程要求

- 先提交数据库事务，再投递依赖该数据的任务；任务必须可重复执行。
- 所有任务有超时、最大重试和错误日志；不能无限重试。
- 在线状态必须能从 last_seen_at 重建；Redis 丢失不导致业务事实丢失。
- Compose 增加 redis、worker、scheduler；健康检查齐全。

## 测试要求

- 任务重复执行不产生重复 Alert；失败重试达到上限后有可查询记录。
- 在线 -> 离线 -> 恢复在线的时间边界测试（使用可控时钟）。
- WebSocket 鉴权、事件接收、断线场景；Redis 清空后的状态重建。
- API/worker 并发更新同一设备时的一致性测试。

## 完成标准（Definition of Done）

- API 请求不等待告警评估完成；任务可查询、可重试、失败可诊断。
- 演示设备状态变化时 WebSocket 客户端立即收到事件。
- 停止 Redis 再恢复，系统可以重新计算状态且数据库数据不丢失。

## 常见风险

- 把 Redis 当数据库。解决：数据库为事实源，Redis 只承载短期状态和传递。
- 任务重复造成副作用。解决：业务唯一键/幂等键 + 状态检查。
- WebSocket 成为唯一读渠道。解决：REST 快照 + WebSocket 增量。

## 明确禁止提前加入

- 不要上 Kafka、RabbitMQ（Celery 使用 Redis 即可）、事件溯源或 CQRS。
- 不要做大规模连接优化、集群级 WebSocket 网关或微服务拆分。

## 下一阶段入口

当异步与状态模型稳定后进入 V4，用 MQTT 和设备模拟器替换 HTTP 模拟，形成真正的设备到云端链路。

## 新聊天启动提示词

```text
请继续 Smart Device Cloud & Automation Platform 的 V3。保持模块化单体，引入 Redis、Celery worker/scheduler、幂等重试、设备 online/offline/unknown 状态计算，以及带 JWT 鉴权的 WebSocket 事件推送。数据库仍是事实源；Redis 清空后状态必须可重建；REST 提供快照，WebSocket 只传增量。请补齐 Compose、健康检查、任务追踪和自动测试，重点证明重复任务不会产生重复 Alert、离线边界可控、断线后可恢复。不要加入 Kafka、RabbitMQ、CQRS、事件溯源、微服务或大规模网关优化。最后给出事件流、Redis key 规范、故障演示和 V4 入口。
```


# V4 MQTT 设备接入、模拟器、心跳、遥测与命令

- 建议周期：5-6 周
- 阶段定位：把项目从普通后台升级为真正可演示的 IoT Device Platform。

## 阶段目标

- 通过 MQTT 接入设备心跳、遥测和命令回执。
- 编写可配置 Device Simulator，稳定复现在线、离线、异常遥测和命令执行。
- 建立设备身份、Topic 规范、消息校验、幂等和命令生命周期。

## 要实现的核心功能

- 本地 Mosquitto broker；MQTT ingestion worker 订阅并调用应用 Service。
- Device Simulator：支持 N 台虚拟设备、随机遥测、心跳、掉线、固件版本和命令响应。
- Heartbeat 更新 last_seen；Telemetry ingestion 批量/异步入库并触发告警。
- Command：平台创建 -> MQTT 下发 -> device ack/result -> 状态更新。
- 消息 schema_version、message_id、device_id、sent_at；拒绝非法或过期消息。

## 数据模型 / 模块

- DeviceCredential/接入凭据（本地可先用户名密码；生产证书留到 V6）。
- DeviceCommand(id, device_id, type, payload, status, requested_by, created_at, sent_at, acknowledged_at, finished_at, error)。
- IngestionRecord(message_id, device_id, topic, received_at, status, error) 用于幂等与排错，可按需要精简。
- simulator/ 作为独立可运行包；ingestion 作为同仓库进程，不称为微服务。

## 核心 API 或事件流

- POST /api/v1/devices/{id}/commands；GET /commands/{id}；GET /devices/{id}/commands。
- Topic：devices/{device_id}/heartbeat、telemetry、commands/request、commands/result。
- 上行流：Simulator -> MQTT -> ingestion -> schema/identity/idempotency -> Service -> PostgreSQL/Redis -> WebSocket。
- 下行流：REST create command -> DB pending -> publisher -> MQTT -> simulator -> result -> ingestion -> DB completed/failed。

## 重点学习内容

- MQTT QoS 0/1、retain、clean session、last will、订阅通配符和重连。
- 设备身份与云端用户身份的区别；消息时间、重复、乱序和离线问题。
- 高频写入的批处理、背压和基础吞吐测量。

## 工程要求

- Topic 和 JSON schema 写入 docs/protocol.md；所有消息带 schema_version/message_id/sent_at。
- QoS 1 下消费者必须幂等；未知设备、非法 payload、过期消息进入可查询错误日志。
- 命令状态转换只允许 pending -> sent -> acknowledged -> succeeded/failed/timeout。
- 提供可重复 demo 脚本和小型负载测试，例如 100 台模拟设备、每 10 秒上报。

## 测试要求

- 协议 schema 单元测试；重复 message_id、乱序时间、未知设备、非法签名/凭据。
- 命令成功、拒绝、超时、重复回执；broker 重启后的重连。
- 集成测试：启动 broker + API + ingestion + simulator，完成完整上下行闭环。
- 记录基准：目标负载下吞吐、延迟、错误率和数据库增长。

## 完成标准（Definition of Done）

- 一条命令启动整套本地环境；模拟器可配置 1-100 台设备。
- 可现场演示掉线检测、异常遥测告警、远程命令及 WebSocket 实时更新。
- 协议、Topic、QoS 选择、幂等策略和性能结果都有文档。

## 常见风险

- 只会“连上 MQTT”却没有可靠性设计。必须演示重复、断线、乱序和超时。
- 把 broker 当业务数据库。broker 只传消息，命令与业务状态落 PostgreSQL。
- 过早连接真实硬件拖慢主线。先把模拟器做稳定，再用一个简单设备验证即可。

## 明确禁止提前加入

- 不要引入 Kafka、复杂流处理、设备影子全量实现、OTA 平台或 PKI 管理系统。
- 不要为每种消息拆服务；不要追求百万设备压测。

## 下一阶段入口

具备稳定设备闭环后进入 V5，把命令和遥测能力编排为自动化测试执行、结果和报告。

## 新聊天启动提示词

```text
请继续 Smart Device Cloud & Automation Platform 的 V4。保持同仓库多进程而非微服务，引入 Mosquitto、MQTT ingestion/publisher 和可配置 Device Simulator。实现 heartbeat、telemetry ingestion、DeviceCommand 下发与 result 回执；定义 topic 与 JSON schema_version/message_id/sent_at；按 QoS 1 设计幂等，并测试重复、乱序、未知设备、broker 重启和命令超时。请提供 docs/protocol.md、Compose、demo 脚本和约 100 台模拟设备的小型基准。不要加入 Kafka、复杂流处理、完整 Device Shadow、OTA、PKI 管理系统、百万设备压测或真实硬件大工程。最后演示完整上下行链路并给出 V5 入口。
```


# V5 Automation Test Platform 自动化测试平台

- 建议周期：6-8 周
- 阶段定位：把设备云端能力转化为面向智能硬件研发/测试团队的自动化测试产品。

## 阶段目标

- 建立 TestCase -> TestTask -> TestExecution -> TestResult 的可追踪测试模型。
- 用 Test Runner 编排命令、等待遥测、断言和超时，生成可读报告。
- 展示设备平台、后端工程与自动化测试三条岗位能力的交集。

## 要实现的核心功能

- TestCase：名称、版本、步骤、期望、标签；先用受控 JSON DSL，不执行任意 Python。
- TestTask：选择设备和用例，排队执行，可取消；记录触发人和参数。
- TestExecution：一次实际运行，保存开始结束、环境、runner 版本和状态。
- TestResult/StepResult：每步输入、输出、断言、耗时、日志和错误。
- Test Runner 支持 send_command、wait_telemetry、assert_metric、sleep 四类基础步骤。
- Report：HTML/JSON（可选 PDF），显示摘要、步骤时间线、失败原因和设备信息。

## 数据模型 / 模块

- TestCase(id, name, version, definition_json, tags, is_active, created_by, created_at)。
- TestTask(id, test_case_id, device_id, parameters, priority, status, requested_by, requested_at)。
- TestExecution(id, task_id, attempt, runner_version, status, started_at, finished_at, error)。
- TestResult(id, execution_id, passed, summary, metrics_json, report_uri)；StepResult(id, execution_id, step_index, type, status, input, output, assertion, duration_ms, error)。
- 模块：automation/cases、tasks、runner、results、reports；Runner 复用 V4 Command/Telemetry Service。

## 核心 API 或事件流

- POST/GET/PATCH /api/v1/test-cases；POST /test-cases/{id}/versions（或复制新版本）。
- POST /api/v1/test-tasks；POST /test-tasks/{id}/cancel；GET /test-executions/{id}/results。
- GET /api/v1/reports/{execution_id}；WebSocket 推送 queued/running/step/succeeded/failed。
- 流：创建 Task -> Celery queue -> Runner 锁定设备 -> 执行步骤 -> Command/Telemetry -> StepResult -> Report -> 释放设备。

## 重点学习内容

- 任务编排、资源锁、超时、取消、重试、可复现性和失败诊断。
- 测试 DSL 的安全边界；测试用例版本化与结果不可变。
- 报告设计、日志关联、执行证据与 flaky test 的基本识别。

## 工程要求

- 同一设备默认只允许一个执行占用；锁必须有 TTL 和异常释放策略。
- TestCase 发布后版本不可就地修改；Execution/Result 作为历史证据不可覆盖。
- Runner 进程崩溃后任务可标记 interrupted 并由明确策略重试。
- 每个 execution_id 贯穿 API、worker、MQTT、日志和报告。

## 测试要求

- DSL schema、非法步骤、参数替换、断言边界的单元测试。
- Runner 成功、断言失败、命令超时、遥测超时、取消、崩溃恢复。
- 两个任务争用同一设备；锁过期；重复 worker 消费的幂等测试。
- 端到端：模拟器执行至少 3 个 TestCase，生成一份成功和一份失败报告。

## 完成标准（Definition of Done）

- 用户无需改代码即可用 JSON DSL 创建用例并执行。
- 完整展示任务排队、实时步骤、失败定位、结果留存和报告下载。
- 至少有 5 个示例用例、稳定 e2e 测试和一段 3-5 分钟演示视频脚本。

## 常见风险

- 做成通用 CI 平台。解决：只服务设备命令与遥测测试。
- 允许任意代码导致安全和隔离问题。解决：受控 DSL + 白名单步骤。
- Runner 逻辑和 API 混在一起。解决：共享领域 Service，但执行器独立进程。

## 明确禁止提前加入

- 不要做可视化拖拽编排、任意脚本执行、插件市场、复杂调度算法。
- 不要复制 Jenkins/pytest 平台，不拆微服务，不引入 Kubernetes。

## 下一阶段入口

本地产品闭环完成后进入 V6，部署云端、建立 CI/CD、可观测性和故障处理证据。

## 新聊天启动提示词

```text
请继续 Smart Device Cloud & Automation Platform 的 V5，构建设备自动化测试平台。实现 TestCase、TestTask、TestExecution、TestResult、StepResult、Test Runner 和 Report；TestCase 使用受控 JSON DSL，只支持 send_command、wait_telemetry、assert_metric、sleep 等白名单步骤，不执行任意 Python。Runner 复用 V4 的命令/遥测能力，处理设备独占锁、TTL、取消、超时、崩溃恢复和幂等；execution_id 要贯穿日志和报告。补齐 API、WebSocket 进度、示例用例、成功/失败 HTML 报告和 e2e 测试。不要做拖拽编排、插件市场、复杂调度、Jenkins 克隆、微服务或 Kubernetes。最后给出演示脚本和 V6 入口。
```


# V6 AWS / Cloud / CI-CD / Observability

- 建议周期：6-8 周
- 阶段定位：把本地项目交付成可部署、可观测、可恢复的 Cloud Backend 作品。

## 阶段目标

- 在 AWS 上部署一个成本可控的演示环境。
- 建立从代码提交到测试、镜像、迁移和部署的 CI/CD。
- 用日志、指标、追踪、告警和 runbook 证明系统可运维。

## 要实现的核心功能

- AWS：ECR + ECS Fargate（或预算更低时单 EC2）运行 API/worker/ingestion；RDS PostgreSQL；ElastiCache Redis。
- MQTT：优先 AWS IoT Core；本地仍保留 Mosquitto 作为开发环境。
- S3 保存测试报告；CloudWatch Logs/Metrics/Alarms；Secrets Manager 或 SSM 管理密钥。
- GitHub Actions：lint/test -> build -> vulnerability scan -> push image -> migrate -> deploy -> smoke test。
- Observability：结构化日志、request_id/execution_id、关键指标、基础 tracing 和仪表盘。
- 备份、恢复演练、限流、CORS、安全组、HTTPS 和成本预算告警。

## 数据模型 / 模块

- 不新增大业务模型；增加 DeploymentVersion、系统健康指标或运维事件时保持轻量。
- IaC 可选 Terraform 基础模块：network、database、compute、storage、observability；只做 dev 一个环境。
- docs/runbooks：部署失败、数据库连接耗尽、Redis 不可用、MQTT 积压、worker 失败。

## 核心 API 或事件流

- GET /health/live 与 /health/ready；管理指标端点仅内网开放。
- 云端流：Device/Simulator -> AWS IoT Core -> ingestion -> RDS/Redis -> worker -> S3 report -> API/WebSocket。
- 部署流：PR -> CI -> main -> image -> migration job -> ECS deployment -> smoke test -> rollback on failure。

## 重点学习内容

- 容器云部署、网络边界、托管数据库、Secrets、IAM 最小权限。
- SLI/SLO 基础：可用性、API p95、ingestion lag、task success rate、offline detection delay。
- 日志/指标/追踪的区别；故障检测、回滚、备份恢复和成本意识。

## 工程要求

- 云资源有预算上限和自动清理说明；绝不把长期密钥提交到仓库。
- 数据库迁移独立于应用启动，且支持失败停止；部署必须有回滚路径。
- 每个告警关联 runbook；日志能按 device_id/command_id/execution_id 串联。
- 基础设施变更经过 review；README 区分 local 与 cloud。

## 测试要求

- CI 单元/集成/e2e 分层；部署后 smoke test。
- 故障演练：worker 停止、Redis 短暂不可用、错误镜像、数据库连接压力。
- 备份恢复演练至少一次；记录恢复时间和数据丢失窗口。
- 安全检查：依赖/镜像扫描、公开端口、IAM 权限和 Secrets 泄漏扫描。

## 完成标准（Definition of Done）

- 公共 HTTPS 地址可演示主要 API，设备模拟器可从本地接入云端。
- 一次正常自动部署和一次失败回滚有日志/截图/说明。
- CloudWatch 仪表盘显示关键 SLI，至少 3 个可触发告警有 runbook。
- 作品集含架构图、成本说明、性能结果、故障复盘和安全清单。

## 常见风险

- AWS 资源过多导致成本和排错失控。解决：只部署一套 dev 环境，优先托管基础组件。
- 为了云而重写架构。解决：保持与本地相同的容器和配置边界。
- 只展示“部署成功”，没有运维证据。必须做故障演练和回滚。

## 明确禁止提前加入

- 不要上 Kubernetes/EKS、Service Mesh、多区域主动主动、复杂蓝绿平台。
- 不要追求企业级全套 Terraform 模块、Kafka/MSK 或十几个微服务。

## 下一阶段入口

V6 完成即形成求职主项目。随后按目标岗位只选一个扩展分支，并保持主干稳定。

## 新聊天启动提示词

```text
请继续 Smart Device Cloud & Automation Platform 的 V6。基于现有容器部署一个成本可控的 AWS dev 环境：ECR、ECS Fargate（若预算明显更低可提出单 EC2 方案）、RDS PostgreSQL、ElastiCache Redis、AWS IoT Core、S3、CloudWatch、Secrets Manager/SSM；建立 GitHub Actions 的 lint/test/build/scan/migrate/deploy/smoke/rollback。增加 live/ready、结构化日志、device_id/command_id/execution_id 关联、关键 SLI、告警和 runbook，并完成一次失败回滚、Redis/worker 故障与备份恢复演练。只做一个环境并给成本预算。不要使用 EKS/Kubernetes、Service Mesh、多区域、Kafka/MSK、复杂蓝绿平台或微服务重写。最后整理架构、部署、可观测性和作品集证据。
```


# 8. 主线完成后的可选扩展分支

V6 完成后只选一个分支做 4-8 周：

- Industrial IoT：Modbus TCP、OPC UA、Edge Gateway。
- Smart Home / AIoT：ESP32、BLE、Matter。
- Robot / Device Lab：设备预约、资源池、并发测试排队、日志附件。
- Go Device Gateway：用 Go 重写 MQTT ingestion/gateway 并做基准对比。

# 9. 对应求职岗位

- Python Backend Engineer。
- IoT Backend / IoT Platform Backend Engineer。
- Device Platform Backend Engineer。
- 智能硬件自动化 / Test Development Engineer。
- Automation Test Platform Engineer。
- Cloud Backend Engineer（初级）。

# 10. 简历可讲亮点

- 从零构建设备云端管理与自动化测试平台，覆盖设备接入、遥测、告警、远程命令和自动化测试闭环。
- 为 MQTT QoS 1 链路设计幂等、乱序/过期校验与断线重连，并用真实基准量化。
- 设计受控测试 DSL、设备独占锁、取消/超时/恢复和成功/失败报告。
- 以 PostgreSQL 为事实源、Redis 为短期状态，实现设备状态可重建。
- 在 AWS 建立 CI/CD、可观测性、失败回滚和备份恢复演练。

> 所有数字必须替换为真实测量结果，不写没有条件的“高并发”。

# 11. 面试故事线

1. 为什么这个问题值得解决。
2. 为什么先选模块化单体。
3. 如何处理 MQTT 重复/乱序、设备断线、命令超时和资源竞争。
4. 如何用事务、幂等、状态机、集成测试和故障注入证明可靠性。
5. 为什么当前不需要 Kafka/Kubernetes，以及何时才会需要。

# 12. 版本信息与变更记录

| 版本 | 日期 | 变更摘要 |
|---|---|---|
| 1.0 | 2026-08-29 | 首次建立 V0-V6 主线、复杂度护栏、扩展分支、求职与面试材料。 |
| 1.1 | 待填写 |  |

## 阶段状态

| 版本 | 状态 | 完成日期 | Tag / 证据 | 遗留问题 |
|---|---|---|---|---|
| V0 | 未开始 |  |  |  |
| V1 | 未开始 |  |  |  |
| V2 | 未开始 |  |  |  |
| V3 | 未开始 |  |  |  |
| V4 | 未开始 |  |  |  |
| V5 | 未开始 |  |  |  |
| V6 | 未开始 |  |  |  |
