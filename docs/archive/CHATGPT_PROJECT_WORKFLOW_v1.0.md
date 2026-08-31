# Smart Device Cloud & Automation Platform：ChatGPT 项目操作指南

> 本文件回答：**我每次打开 ChatGPT 后，应该在哪里工作、发送什么、做到哪里结束。**  
> 项目范围以 `PROJECT_PLAN.md` 为准，协作规则以 `PROJECT_GUIDE.md` 为准；如三者冲突，先停止并指出冲突，不要擅自扩大范围。

## 1. 只使用一个 Local Project

- 整个 Smart Device Cloud & Automation Platform 只建 **一个 Local Project**，绑定同一个 WSL 仓库根目录。
- **不要**为 V0、V1、V2、V3、V4、V5、V6 分别创建 Project。
- V0-V6 是同一项目的连续演进，顺序固定：`V0 → V1 → V2 → V3 → V4 → V5 → V6`。
- 每个阶段建议新建一个独立 **Work 会话**，例如 `V0 - Foundation`、`V1 - Core Business`。
- 阶段很长时，可以拆成多个 Work，例如 `V2-1 - Architecture`、`V2-2 - Auth`，但它们仍属于同一个 Local Project，并操作同一个仓库。

这样既保留清晰的会话上下文，又不割裂代码、Git 历史和项目规则。

## 2. 什么时候用 Work，什么时候用 Chat

### 使用“工作 Work”

只要任务需要接触本地 WSL 仓库，就优先使用 Work，包括：

- 读取或修改源代码、配置、迁移、测试、README 或其他文档；
- 检查仓库现状、Git diff、阶段完成情况；
- 创建 Design Brief、Skeleton 或测试骨架；
- 运行测试、lint、迁移、容器或诊断命令；
- 对本地实现做 Code Review、Final Phase Review；
- 根据审查结果确认 PASS 或 CHANGES REQUIRED。

### 使用普通“聊天 Chat”

Chat 只用于**不依赖当前仓库**的纯概念学习，例如：

- “什么是数据库事务？”
- “JWT access token 和 refresh token 有什么区别？”
- “请用简单例子解释 SQLAlchemy relationship。”

如果回答必须知道“我这个项目现在写成什么样”，就不要用普通 Chat，改用 Work。

## 3. 根目录三个固定文件

仓库根目录长期保留：

| 文件 | 作用 | 一句话记忆 |
|---|---|---|
| `PROJECT_PLAN.md` | V0-V6 路线、阶段范围、技术边界、Definition of Done | **做什么** |
| `PROJECT_GUIDE.md` | 角色、协作方式、帮助等级、设计/骨架/评审规则 | **怎么协作** |
| `CHATGPT_PROJECT_WORKFLOW.md` | 何时开 Work、每次发什么、何时评审/提交/换阶段 | **我每次怎么操作** |

每个新 Work 的第一条消息都要求 ChatGPT 先读取这三个文件，并以当前仓库事实为准，不依赖旧聊天记忆。

## 4. 每个阶段开始：标准开场提示词

### V0 第一次启动

复制到 V0 的新 Work：

```text
我们现在开始 Smart Device Cloud & Automation Platform 的 V0。

请先读取仓库根目录的 PROJECT_PLAN.md、PROJECT_GUIDE.md 和 CHATGPT_PROJECT_WORKFLOW.md，再检查当前本地仓库、Git 状态和已有文件。以这三个文件和当前代码为事实来源，不依赖其他聊天的记忆，并保留我已有的改动。

请先：
1. 复述 V0 的目标、Scope、Definition of Done 和明确禁止提前加入的内容；
2. 根据依赖顺序把 V0 拆成小而可审查的 Tasks，并为每个 Task 给出完成条件；
3. 标出当前只应该开始的第一个 Task。

本项目用于学习：我是主要实现者，你担任 Tech Lead、Senior Python Backend Engineer、Mentor 和 Reviewer。默认帮助等级为 Level 2。不要替我完成核心业务逻辑，也不要一次实现整个阶段。

对第一个 Task，请按 Scope/Requirement → Design Brief → Skeleton → Acceptance Criteria → TODO 的顺序进行。完成 Skeleton 和 TODO 后停止，等待我实现。不要进入第二个 Task。
```

### 阶段内新开 Work 或长阶段续接

```text
请继续 Smart Device Cloud & Automation Platform 的 Vx（填写阶段）工作。

先读取 PROJECT_PLAN.md、PROJECT_GUIDE.md 和 CHATGPT_PROJECT_WORKFLOW.md，检查当前仓库、Git 状态、最近提交、测试结果和已有改动。请根据代码事实确认本阶段已 PASS、正在进行和尚未开始的 Tasks；不要仅凭我的描述猜测进度，也不要覆盖现有改动。

当前要继续的 Task 是：<填写 Task 名称；不确定则写“请先识别”>。

如果该 Task 尚未设计，请按固定 Task 流程从 Scope/Requirement 开始；如果我已有实现，请先告诉我当前处于哪个步骤，再只做下一步。默认帮助等级 Level 2。不要扩大 Vx 的范围，不要提前实现后续阶段，也不要自动 commit 或 push。
```

## 5. 每个 Task 的固定流程

```text
Scope / Requirement
        ↓
Design Brief
        ↓
Skeleton
        ↓
Acceptance Criteria
        ↓
TODO
        ↓
用户实现核心代码
        ↓
Local Code Review
        ↓
PASS / CHANGES REQUIRED
        ↓
仅 PASS 后 commit / push
```

关键规则：

- 一次只推进一个 Task；当前 Task 未 PASS，不开始下一个。
- ChatGPT 先解释设计，再搭骨架；用户完成核心实现。
- 默认帮助等级 Level 2：指出问题、解释原因并给提示，不直接交付完整答案。
- 只有用户明确要求提高帮助等级时，才给伪代码、局部实现或完整参考实现。
- 所有审查优先读取本地代码和 diff，并实际运行与风险相称的验证。

## 6. Design Brief 必须覆盖什么

按 Task 相关性覆盖以下内容；不适用的项目应明确写“本 Task 不适用”，不要静默漏掉：

1. **业务**：目的、输入/输出、业务规则、状态与生命周期、失败行为。
2. **数据库**：表、字段、类型、PK、FK、`unique`、`index`、`nullable`、约束、级联/`ON DELETE` 及理由。
3. **ORM relationship**：关系方向、基数、`back_populates`、加载/删除行为及理由。
4. **Pydantic Schemas**：Create、Update、Read、List/Detail、Request/Response 的边界及为何分离。
5. **API**：路径、HTTP method、请求、响应、状态码、错误格式、权限和幂等性（如相关）。
6. **分层职责**：Router、Service、Repository，以及数据库/后台任务等组件分别做什么、不做什么。
7. **事务**：事务边界、何处 `commit`/`rollback`、失败时一致性；Repository 不应自行随意提交。
8. **测试**：happy path、校验、边界、冲突、not found、失败、回滚及必要的集成测试。
9. **Trade-offs**：为何选当前方案、有哪些替代方案、为什么现阶段不需要替代方案。
10. **Out of Scope**：本 Task 和当前阶段明确不实现什么。

Design Brief 的目标不是写长文，而是让实现前的关键决定都可见、可检查。

## 7. Skeleton：允许和禁止

### 允许生成

- 当前 Task 必需的目录和文件；
- 类、函数/方法签名、类型提示、接口和依赖注入入口；
- ORM 与 Pydantic 的结构声明；
- Router、Service、Repository 的结构；
- 测试文件、测试函数名称、fixtures 入口和 Arrange/Act/Assert 骨架；
- 必要的基础配置、占位异常、docstring 和明确的 `TODO`；
- 为使骨架可导入/可启动所需的最小胶水代码。

### 不允许默认实现

- 完整业务逻辑、完整 CRUD、完整 Service/Repository；
- 能直接照抄即完成 Task 的 TODO 答案；
- 已写完断言和数据准备的完整测试；
- 当前 Task 或当前阶段之外的“顺便重构”；
- 后续版本的空目录、空类或预留架构；
- 未经要求自动 commit、push、tag、发布或部署。

Skeleton 完成后，ChatGPT 应列出文件变化、Acceptance Criteria 和按推荐顺序排列的 TODO，然后**停止等待用户实现**。

## 8. 用户写完一个 Task：标准 Code Review 提示词

```text
我已完成 Vx 的 Task：<Task 名称>。现在请做 Local Code Review。

请先重新读取 PROJECT_PLAN.md、PROJECT_GUIDE.md 和 CHATGPT_PROJECT_WORKFLOW.md，再检查当前本地仓库、Git diff 和本 Task 的 Acceptance Criteria。请运行与本 Task 相关的测试、lint、迁移或其他必要验证；保留我的改动。

审查至少覆盖：正确性、阶段 Scope、架构与职责边界、命名和类型、错误处理、SQLAlchemy 用法、数据库约束与 relationship、事务边界、安全性、相关并发问题、测试完整性、边界情况、可维护性和不必要复杂度。

本轮只审查，不要直接替我重写实现，不要 commit 或 push。

结论必须严格为以下之一：
- PASS
- CHANGES REQUIRED

若为 CHANGES REQUIRED，请按优先级逐项给出：文件和位置、问题、为什么重要、必须达到的结果；默认只给 Level 2 提示。若为 PASS，请说明验证证据，并确认是否可以进入 commit/push 和下一个 Task。
```

## 9. 收到 CHANGES REQUIRED 后

1. 不开始新 Task，不 commit/push。
2. 用户逐项修复；不明白时只针对某一项提问，可请求更高帮助等级。
3. 修复后在**同一个 Work** 发送：

```text
我已根据上次 CHANGES REQUIRED 修复以下项目：
- <修复 1>
- <修复 2>

请检查当前本地 diff，先复核上次所有问题是否关闭，再运行相关验证，并确认修复是否引入回归。不要改代码、不要 commit 或 push。

结论仍只能是 PASS 或 CHANGES REQUIRED；若仍需修改，请继续给出文件和位置、问题、原因及必须达到的结果。
```

重复“用户修复 → 复审”，直到 PASS。不要为了赶进度跳过未解决项。

## 10. Task PASS 后 commit / push

PASS 后先确认变更只属于当前 Task、没有密钥/生成物/无关文件，并记录已经通过的验证。推荐由用户执行：

```bash
git status
git diff
git add <本 Task 的文件>
git commit -m "<type>: <简洁描述>"
git push
```

提交信息示例：`feat: add device registration model`、`test: cover telemetry validation`、`refactor: introduce service transaction boundary`。

如果需要 ChatGPT 协助，使用：

```text
本 Task 已 PASS。请只检查当前 Git 状态和 diff，建议本 Task 应暂存的文件清单与一条 Conventional Commit 风格的 commit message，并提醒我任何不应提交的文件。不要修改代码，也不要替我 commit/push；等我确认后再继续。
```

用户完成 push 后，把 Task 标为 PASS，再开始下一个 Task。

## 11. 当前阶段所有 Tasks 通过：Final Phase Review

Task PASS 只证明一个局部完成；进入下一阶段前必须再做一次阶段级审查。发送：

```text
Vx 的所有计划 Tasks 均已逐项 PASS。现在请进行 Vx Final Phase Review。

请重新读取 PROJECT_PLAN.md、PROJECT_GUIDE.md 和 CHATGPT_PROJECT_WORKFLOW.md，检查当前本地仓库与 Git 历史，并逐条核对 PROJECT_PLAN.md 中 Vx 的：阶段目标、要实现的功能、工程要求、测试要求、Definition of Done、禁止提前加入项和下一阶段入口。

请运行足以证明阶段完成的完整测试、lint、迁移/启动检查和必要的端到端验证；同时检查跨 Task 集成、文档、配置、错误处理、安全、事务、一致性、回归和是否存在超出 Scope 的复杂度。

本轮只审查，不要自动修复、commit、push 或 tag。

最终结论必须严格为以下之一：
- Vx FINAL PASS
- Vx FINAL CHANGES REQUIRED

若未通过，请按优先级列出：对应 Definition of Done、文件和位置、问题、风险、必须达到的结果以及复验方式。若通过，请给出验证证据、阶段完成清单、仍可接受的非阻塞事项，以及结束阶段所需的 docs/tag/push 清单。
```

如果结果是 `Vx FINAL CHANGES REQUIRED`，按 Task 的修复—复审方式处理，但复审提示词改为“复核全部阶段级问题”，直到得到 `Vx FINAL PASS`。

## 12. FINAL PASS 后结束当前阶段

只有 `Vx FINAL PASS` 后才进行：

1. 更新 README、运行方式、API/协议/架构说明、阶段状态和必要的变更记录。
2. 再跑一次受影响验证，确认文档更新未夹带代码回归。
3. 检查 `git status`/`git diff`，提交阶段收尾文档并 push。
4. 建议打带注释 tag：`v0.0`、`v1.0`……`v6.0`（若仓库已有版本规则，以已有规则为准）。
5. push tag；需要作品集发布时再在 GitHub 创建 release。
6. 保留当前 Work 作为阶段记录，回到**同一个 Local Project** 新建下一阶段 Work。

可发送给 ChatGPT：

```text
Vx 已获得 FINAL PASS。请先检查仓库现状，只给出本阶段收尾所需的 docs 更新清单、建议 tag、建议 commit message 和最终验证命令。不要添加新功能，不要进入 Vx+1，也不要自动 commit、push、tag 或发布。等我完成并确认远端已同步后，本 Work 即结束。
```

结束时记录四件事：`FINAL PASS`、最终 commit SHA、tag、远端 push 成功。然后不要在旧 Work 里继续下一阶段。

## 13. V1-V6 新阶段标准启动提示词

在同一 Local Project 中新建 Work，复制以下模板并把 `Vx` 和 `V(x-1)` 替换为实际版本：

```text
我们现在开始 Smart Device Cloud & Automation Platform 的 Vx。

请先读取仓库根目录的 PROJECT_PLAN.md、PROJECT_GUIDE.md 和 CHATGPT_PROJECT_WORKFLOW.md，再检查当前本地仓库、Git 状态、最近提交和版本 tag。以文件与代码事实为准，保留现有改动。

第一步请验证 V(x-1) 是否有 FINAL PASS 对应的代码、文档、测试证据和 tag，并核对 PROJECT_PLAN.md 中“下一阶段入口”。若入口不满足，请停止并列出阻塞项，不要开始 Vx。

若入口满足，请：
1. 复述 Vx 的目标、Scope、Definition of Done、常见风险和禁止提前加入项；
2. 说明它与上一阶段的衔接以及本阶段关键技术取舍；
3. 按依赖顺序将 Vx 拆成小而可审查的 Tasks，并给出每个 Task 的 Acceptance Criteria；
4. 只选择第一个 Task 开始。

我是主要实现者，你担任 Tech Lead、Senior Python Backend Engineer、Mentor 和 Reviewer。默认帮助等级 Level 2。对第一个 Task，严格按 Scope/Requirement → Design Brief → Skeleton → Acceptance Criteria → TODO 进行；Skeleton 后停止，等待我实现。不要一次实现整个阶段，不要提前实现 V(x+1)，不要自动 commit 或 push。
```

阶段的详细功能不要凭提示词记忆，始终从 `PROJECT_PLAN.md` 当前版本读取。

## 14. GitHub 在本项目中的定位

开发与 Review 的主场是本地 WSL 仓库。固定顺序是：

```text
本地设计 → 本地实现 → 本地验证 → Local Review → PASS → commit → push
```

GitHub 主要用于：

- 远端备份；
- 可追溯的 commit history；
- 求职 portfolio；
- CI；
- 阶段 tags / releases。

不要把“先 push 再让 GitHub 上的工具审查”作为默认流程；未经本地 PASS 的 Task 不应为了留记录而提交。也**不再使用**之前的 `codex-project-workflow` 或 `Guided Project Workflow Skills`：本仓库的三个 Markdown 文件就是协作与流程的事实来源。

## 15. 复杂度约束

目标难度约为**一年后端开发经验**：优先选择简单、可测试、可解释、可维护、与当前阶段相称的方案。

除非 `PROJECT_PLAN.md` 到了对应阶段并明确要求，否则不要提前加入：

- 微服务；
- Kubernetes / EKS / Service Mesh；
- Kafka / MSK；
- CQRS；
- Event Sourcing；
- 复杂 DDD；
- 万能抽象、过多设计模式、复杂多租户；
- 为“未来百万设备”而做的过早优化。

ChatGPT 如果建议新增架构或依赖，必须先说明：它解决的当前问题、最简单替代方案、引入成本、属于哪个阶段；若当前没有真实需要，则不加入。

## 16. 全流程 ASCII 图

```text
一个 Local Project
        |
   Vx 独立 Work
        |
读 3 个 MD + 检查仓库
        |
拆 Tasks → 只做 Task 1
        |
设计 → 骨架 → 我实现 → 本地审查
                    |          |
                    |     CHANGES REQUIRED ──→ 我修复 ──┐
                    |                                  │
                    └──────────── PASS ←───────────────┘
                                  |
                           commit / push
                                  |
                    全部 Task PASS？──否→ 下一个 Task
                                  |
                                 是
                                  |
                      Final Phase Review
                         |             |
            FINAL CHANGES             FINAL PASS
                  |                       |
                修复复审          docs / tag / push
                                          |
                               下一阶段新建 Work
```

## 17. 一次只记住这 8 步

1. 在**同一个 Local Project** 里为当前阶段新建 Work。
2. 开场要求先读三个 Markdown、检查仓库、确认阶段边界。
3. 把阶段拆成 Tasks，一次只开始一个。
4. 先做 Design Brief，再让 ChatGPT 只搭 Skeleton 和 TODO。
5. 自己实现核心代码；需要帮助时默认只要 Level 2 提示。
6. 发 Local Code Review；`CHANGES REQUIRED` 就修复复审，直到 `PASS`。
7. Task PASS 后再 commit/push；全部 Task PASS 后做 Final Phase Review。
8. `FINAL PASS` 后更新 docs、tag、push，并在同一 Project 新建下一阶段 Work。

> 最短记忆句：**一个 Project；阶段分 Work；Task 逐个做；先设计后骨架；我实现；本地审查；PASS 才提交；FINAL PASS 才换阶段。**
