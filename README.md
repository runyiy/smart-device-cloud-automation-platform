# Smart Device Cloud & Automation Platform

- 用于练习 Python 后端开发的模块化单体项目；V0 已完成，V1-T1 已增加 Device 持久化模型与迁移，尚无设备业务 API。
- 已实现：FastAPI 应用工厂、配置管理、SQLAlchemy Session 边界、Alembic 基线迁移、健康检查、请求 ID、统一错误响应和 JSON 请求日志。
- 尚不包含设备业务、用户认证、CRUD、自动化规则、消息队列或前端。
- 分工：学习者负责功能代码；助手负责 README、操作说明以及 pytest 的编写、维护和验证。

## 1. 前置条件

- 以下命令使用 Ubuntu / WSL 的 Bash，并从仓库根目录执行。
- 准备 Python 3.12（不支持 3.13）、对应的 venv 模块、Git、curl，以及可用的 PostgreSQL 服务。
- PostgreSQL 需事先准备两个数据库和登录账号：
  - 开发：`smart_device_cloud`，账号具有连接和迁移所需的 schema 权限。
  - 测试：`smart_device_cloud_test`，仅存放可丢弃测试数据；破坏性迁移测试还需删除、重建其 `public` 的权限。
  - 当前项目使用已经建立的数据库，不要重新创建数据库，也不要使用 `music_ai_db` 或其他数据库。
- 新机器的 PostgreSQL 安装、账号和数据库创建属于前置准备；本指南不会自动执行这些管理操作。
- “15 分钟启动”目标从上述条件和仓库就绪后开始，包含虚拟环境、依赖安装、配置、迁移、启动和接口验证；不包含操作系统、Python 和 PostgreSQL 安装。实际复演范围与计时见末尾验证记录。

## 2. 安装

- 尚未下载仓库时执行；已有本地仓库则直接进入原目录：

```bash
git clone https://github.com/runyiy/smart-device-cloud-automation-platform.git
cd smart-device-cloud-automation-platform
```

- 首次运行时创建虚拟环境；已有可用的 Python 3.12 虚拟环境则跳过创建：

```bash
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pip check
```

- 后续新终端只需重新进入仓库并激活 `.venv`。
- 依赖以 `pyproject.toml` 为准，目前没有锁文件；不同时间安装可能解析到不同的兼容版本。
- dev 依赖暂将 AnyIO 限制在 `>=4.14.2,<4.15`：实测 Starlette 1.6 的 TestClient 在 AnyIO 4.15 下触发弃用警告，导致严格测试无法收集。此约束不关闭警告；上游兼容后可重新验证并解除。

## 3. 配置

- 仅为缺失文件复制模板，不覆盖现有配置：

```bash
test -e .env || cp .env.example .env
test -e .env.test || cp .env.example .env.test
```

- 在本地编辑两个文件，使用已有账号的真实密码；不要把密码粘贴到日志、提交或截图中。
- `.env` 的数据库配置示例（占位密码必须替换）：

```dotenv
ENVIRONMENT=development
DATABASE_URL=postgresql+psycopg://smart_device_user:YOUR_PASSWORD@localhost:5432/smart_device_cloud
```

- `.env.test` 的数据库配置示例：

```dotenv
ENVIRONMENT=test
DATABASE_URL=postgresql+psycopg://smart_device_user:YOUR_PASSWORD@localhost:5432/smart_device_cloud_test
```

- 密码中的 URL 特殊字符需要百分号编码；不要把完整连接字符串输出用于排错。
- 支持的配置：
  - `APP_NAME`：默认 `Smart Device Cloud & Automation Platform`。
  - `APP_VERSION`：默认 `0.1.0`。
  - `ENVIRONMENT`：`development` 或 `test`，默认前者。
  - `DEBUG`：默认 `false`。
  - `DATABASE_URL`：必填，使用 `postgresql+psycopg` 驱动。
- 进程环境变量优先于 env 文件；代码显式传入的 Settings 字段优先级更高。文件修改后重启服务，以免继续使用缓存配置。
- 应用工厂默认读取 `.env`；Alembic 才使用 `SETTINGS_FILE` 选择配置文件。仅设置 `ENVIRONMENT=test` 不会切换到 `.env.test`。
- `.env`、`.env.test` 已被 Git 忽略；只提交不含真实凭据的 `.env.example`。

## 4. 迁移

- 查看仓库迁移记录，不连接数据库：

```bash
python -m alembic heads
python -m alembic history
```

- 当前唯一 head 为 `f4502b63c0be`，新增 `devices` 表；其前驱 `0001_v0_baseline` 是无业务表的 V0 基线。
- 以下第一条读取开发数据库版本，第二条会修改 `.env` 指向的开发数据库。先确认该文件指向已有的 `smart_device_cloud`；这里只允许正常升级，不要对开发数据库执行重置或降级：

```bash
env -u DATABASE_URL -u ENVIRONMENT SETTINGS_FILE=.env python -m alembic current
env -u DATABASE_URL -u ENVIRONMENT SETTINGS_FILE=.env python -m alembic upgrade head
```

- 测试数据库的 `upgrade head -> downgrade base -> upgrade head` 由第 7 节的两个迁移验收测试覆盖。
- `downgrade base` 会撤销全部迁移；它不是修复任意数据库状态的通用命令。仅在明确授权的可丢弃测试库中执行，不要直接复制到开发环境。

## 5. 启动与接口验证

- 开发服务默认使用 `.env`。清除可能遗留的数据库进程覆盖值后启动；`--no-access-log` 关闭独立的 Uvicorn 访问日志，应用自己的 JSON 请求日志仍保留：

```bash
env -u DATABASE_URL -u ENVIRONMENT python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

- 在另一个终端运行：

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
curl -i -H 'X-Request-ID: local-check-001' http://127.0.0.1:8000/api/v1/ping
curl -i http://127.0.0.1:8000/ping
curl -i http://127.0.0.1:8000/docs
curl -i http://127.0.0.1:8000/openapi.json
```

- 预期结果：
  - `/health`：200，`{"status":"ok"}`；不代表数据库可用。
  - `/ready`：真实执行数据库探测；可用时 200、`{"status":"ready"}`，不可用时 503、`{"status":"not_ready"}`。
  - `/api/v1/ping`：200，`{"message":"pong"}`；响应头回传 `local-check-001`。
  - `/ping`：404；接口只挂载在版本化路径下。
  - `/docs`：200 HTML；浏览器打开可查看 Swagger UI，其前端资源加载可能需要网络。
  - `/openapi.json`：200 OpenAPI JSON。
- 停止服务：在启动终端按 Ctrl+C，让 lifespan 释放数据库引擎。
- 开发时可自行添加 `--reload`；不要把自动重载模式当成生产部署配置。

## 6. 请求 ID、错误和日志

- 传入的 `X-Request-ID` 必须只有一个，长度为 1–64，只允许 ASCII 字母、数字、点、下划线、短横线，即 `[A-Za-z0-9._-]{1,64}`。
- 合格示例：`demo-001`、`abc_DEF.9`。空值、空格、中文、逗号、重复请求头或超长值不合格。
- 缺失或不合格时不会拒绝请求，而是生成新的 UUID 十六进制 ID；响应头、错误体和请求日志使用同一 ID。
- 404 错误示例（ID 每次可能不同）：

```json
{"error":{"code":"HTTP_404","message":"Not Found","request_id":"local-check-001"}}
```

- HTTP 错误保留状态码，但不直接回显异常详情；验证错误使用 `VALIDATION_ERROR`，未预期异常使用 `INTERNAL_ERROR`。健康检查的 503 保持专门的 readiness 响应。
- `app.requests` 每个请求输出一行 JSON，包含 `timestamp`、`level`、`event`、`request_id`、`method`、`route`、`status_code`、`duration_ms`。
- `route` 使用路由模板，未匹配请求记为 `<unmatched>`；日志不收集查询参数、请求体、认证头、数据库 URL 或异常堆栈。
- 该约束仅覆盖应用请求日志，不代表 Uvicorn 或其他库的独立日志也经过同一处理。

## 7. 验证

- 日常安全检查不会启用数据库 schema 重置；始终显式取消破坏性测试开关：

```bash
env -u RUN_MIGRATION_TESTS -u RUN_POSTGRES_SMOKE python -m pytest -q -W error
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pip check
```

- 默认跳过两个真实 PostgreSQL 迁移测试、四个 Device 数据库验收测试和一个只读 PostgreSQL smoke，共七项；日志、Docs/OpenAPI 及 Device metadata 检查默认执行。
- 以下单独启用只读检查：从 `.env.test` 读取配置，要求 test 环境、本机地址、精确库名 `smart_device_cloud_test`、psycopg 驱动及无 URL 查询参数；连接强制只读并设置超时，不重置 schema：

```bash
env -u RUN_MIGRATION_TESTS RUN_POSTGRES_SMOKE=1 python -m pytest -q -W error tests/integration/test_v0_smoke.py
```
- 下面是单独的、破坏性的迁移验收入口：只授权删除并重建本机 `smart_device_cloud_test.public`，其中所有对象和数据会丢失。不要并发运行服务、其他迁移或使用该测试库的测试。
- 迁移和 Device 验收共用保护：要求本机地址、test 环境、精确库名 `smart_device_cloud_test`、psycopg 驱动及无 URL 查询参数；重置前核对实际库名并拒绝其他已连接会话。请确保独占测试库运行，不使用并行测试，也不要把开关永久导出。
- 确认测试数据可丢弃后，再执行以下命令；它不会操作开发数据库：

```bash
env -u DATABASE_URL -u ENVIRONMENT python - <<'PY'
import os
import subprocess
import sys

from sqlalchemy.engine import make_url

from app.core.config import Environment, Settings

settings = Settings(_env_file=".env.test")
url = make_url(settings.database_url.get_secret_value())
if (
    settings.environment is not Environment.TEST
    or url.drivername != "postgresql+psycopg"
    or url.host not in {"localhost", "127.0.0.1"}
    or url.database != "smart_device_cloud_test"
    or url.query
):
    raise SystemExit("STOP: test database target is outside the authorized scope")

environment = dict(os.environ, RUN_MIGRATION_TESTS="1", SETTINGS_FILE=".env.test")
subprocess.run(
    [
        sys.executable, "-m", "pytest", "-q", "-W", "error",
        "tests/integration/test_migrations.py",
        "tests/integration/test_devices.py",
    ],
    env=environment,
    check=True,
)
subprocess.run(
    [sys.executable, "-m", "alembic", "current"],
    env=environment,
    check=True,
)
PY
```

- 执行期间不要修改 `.env.test`。上述两个文件目前预期为 14 passed，覆盖目标保护、空库升级、head → V0 baseline → head、完整 base/head 往返，以及 Device 默认值、约束、时区、schema 一致性和并发唯一冲突。最终版本应为唯一 head `f4502b63c0be`，测试创建的 Device 行会清理。
- 测试失败时先保留错误并检查目标库和版本状态，不要对其他数据库进行重置补救。

## 8. 常见问题与证据边界

- Python 版本或驱动错误：确认激活的是 Python 3.12 的 `.venv`，重新执行项目的 dev 安装和 `pip check`；不要随意替换为其他 PostgreSQL 驱动。
- 缺少 `DATABASE_URL`：确认从仓库根目录执行、配置文件存在且字段已填写；不要把完整配置打印出来。
- 修改 env 文件不生效：检查进程环境变量覆盖和配置缓存，重启服务。不要用 `SETTINGS_FILE=.env.test` 启动应用并假设它会选择测试配置。
- `/health` 正常而 `/ready` 为 503：检查 PostgreSQL 服务、连接地址、账号、库名和权限；应用启动成功不意味着数据库连接已经成功。
- 迁移版本不匹配：比较正确目标的 `alembic current` 与仓库 `heads/history`；不要使用 `stamp` 或删除 schema 来掩盖未知差异。
- 默认迁移测试跳过：这是安全设计，不是数据库验证通过的证据；真实验证必须使用上面的独立入口。
- V1-T1 验证记录（2026-09-23）：
  - 安全回归 111 passed、7 skipped；单独启用迁移与 Device 验收为 14 passed。
  - 在独占授权测试库上同时启用数据库验收与只读 smoke，完整回归为 118 passed，无跳过。
  - Ruff lint/format、严格 mypy（33 个文件）、pip check 均通过；数据库与仓库最终 head 均为 f4502b63c0be。
  - 只重建 smart_device_cloud_test.public；其他数据库未操作。未修改应用模型或迁移实现。
- V0 历史验证记录：
  - 2026-09-18（本地日期）：Ubuntu/WSL、Python 3.12.3；使用全新临时 venv，禁用 pip 下载缓存，从项目 dev 依赖重新安装。
  - 首次复演发现 AnyIO 4.15 与 Starlette 1.6 的严格警告兼容问题；获得授权后增加上述 dev 约束，再新建 venv 重做安装，而非复用失败环境。
  - 第二次启动复演：UTC 2026-09-19 01:56:58 至 01:58:37.455，约 99.5 秒。包含环境创建、安装、配置加载、测试库升级、Uvicorn 启动、六个 HTTP 检查和优雅退出，也包含操作间隔。
  - 复用了已有仓库、env 文件、数据库和系统软件，未计入这些前置准备。为避免操作开发数据库，复演显式将应用连接覆盖为已验证的测试 URL，并使用临时本地端口；未修改 env 文件。
  - 干净环境安全回归：107 passed、3 skipped；只读 PostgreSQL 单独启用时 T6 文件为 9 passed；Ruff lint/format、严格 mypy 和 pip check 均通过。
  - 两个真实迁移验收测试均通过；执行前核对精确测试库且无其他连接，仅重建该库 public。数据库最终版本与仓库唯一 head 均为 `0001_v0_baseline`。
  - HTTP 结果：health、ready、版本化 ping、docs、OpenAPI 均为 200，未版本化 ping 为 404；随后正常退出。迁移往返验证独立执行，不计入上述第二次启动耗时。
  - 这是本地干净 Python 环境的复演证据，不声称已经在全新机器上验证；数据库内原有测试 schema 数据不保留。
