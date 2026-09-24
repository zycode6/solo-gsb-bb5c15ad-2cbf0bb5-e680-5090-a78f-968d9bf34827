# 直播导播口令编排 API

基于 **Python + FastAPI** 的导播口令编排服务：接收一组带锚点依赖的直播导播口令，
解析每条口令在时间轴上的起止毫秒，并列出同一通道内半开区间重叠的冲突口令对。

- 在线接口文档（Swagger UI）：<http://localhost:8000/docs>
- 健康检查：`GET /health`
- 编排接口：`POST /compile`
- 改动预演接口：`POST /preview`

## 一条命令启动

需要已安装 Docker（含 Compose 插件）。在本目录执行：

```bash
docker compose up --build -d
```

启动后访问 <http://localhost:8000/docs> 即可在线调试。停止服务：

```bash
docker compose down
```

> 镜像在构建阶段执行 `pip install -r requirements.txt`，**启动容器时依赖已安装完毕**，
> 无需进入容器手动安装。

## 必要配置

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| 容器监听端口 | 固定 `8000`（由 `uvicorn --port 8000` 指定） | `8000` |
| 宿主机映射端口 | Compose 读取环境变量 `PUBLISH_PORT`，映射为 `${PUBLISH_PORT}:8000` | `8000` |
| 依赖安装 | `Dockerfile` 构建时执行 `pip install -r requirements.txt` | 自动 |

如需改用宿主机 9000 端口：

```bash
PUBLISH_PORT=9000 docker compose up --build -d
```

服务无数据库、无外部依赖，不需要额外配置环境变量。

## 接口约定：`POST /compile`

请求体为口令数组，每一项字段：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `id` | string | 是 | 口令唯一 id；不能为空，不能使用保留锚点名 `START` |
| `channel` | string | 是 | 通道标识；只有同通道口令之间才检测冲突 |
| `anchor` | string | 否 | 锚点，缺省 `START`；可填 `START`（时间原点 0 ms）或另一条口令的 id |
| `offset_ms` | integer | 否 | 相对 **锚点结束时刻** 的偏移（毫秒），缺省 `0`，允许为负 |
| `duration_ms` | integer | 是 | 持续时长（毫秒），必须为正数 |

时间与冲突规则：

- 虚拟锚点 `START` 的起点和结束时刻均为 `0`。
- 口令 `x` 的起点 = 锚点口令的结束时刻 + `offset_ms`，结束时刻 = 起点 + `duration_ms`。
- 允许负偏移，但解析出的起点不得小于 `0`，否则返回 `NEGATIVE_START`。
- `timeline` 按 `(start_ms, id)` 升序排列。
- 同一通道内两个半开区间 `[start_ms, end_ms)` 发生重叠即为冲突；
  **首尾相接（前一个 end 等于后一个 start）不算冲突**；不同通道互不影响。
- 冲突对对内按 id 排序（`a < b`），所有冲突对之间按 `(a, b, channel)` 排序。

### 请求示例

```bash
curl -s http://localhost:8000/compile \
  -H 'Content-Type: application/json' \
  -d '[
    {"id": "a", "channel": "main", "anchor": "START", "offset_ms": 0,    "duration_ms": 1000},
    {"id": "b", "channel": "main", "anchor": "a",     "offset_ms": 0,    "duration_ms": 500},
    {"id": "c", "channel": "main", "anchor": "a",     "offset_ms": -200, "duration_ms": 500},
    {"id": "d", "channel": "sub",  "anchor": "START", "offset_ms": 0,    "duration_ms": 1000}
  ]'
```

对应时间：

- `a`：`[0, 1000)`
- `b`：相对 `a` 结束时刻（1000）+ 0 → `[1000, 1500)`，与 `a` 首尾相接，不冲突
- `c`：相对 `a` 结束时刻 -200 → `[800, 1300)`，与 `a`、`b` 均在 `main` 通道重叠
- `d`：`[0, 1000)`，但属于 `sub` 通道，不参与冲突

响应示例（`200`）：

```json
{
  "timeline": [
    {
      "id": "a",
      "channel": "main",
      "anchor": "START",
      "offset_ms": 0,
      "duration_ms": 1000,
      "start_ms": 0,
      "end_ms": 1000
    },
    {
      "id": "d",
      "channel": "sub",
      "anchor": "START",
      "offset_ms": 0,
      "duration_ms": 1000,
      "start_ms": 0,
      "end_ms": 1000
    },
    {
      "id": "c",
      "channel": "main",
      "anchor": "a",
      "offset_ms": -200,
      "duration_ms": 500,
      "start_ms": 800,
      "end_ms": 1300
    },
    {
      "id": "b",
      "channel": "main",
      "anchor": "a",
      "offset_ms": 0,
      "duration_ms": 500,
      "start_ms": 1000,
      "end_ms": 1500
    }
  ],
  "conflicts": [
    {
      "channel": "main",
      "a": "a",
      "b": "c",
      "a_interval": [0, 1000],
      "b_interval": [800, 1300]
    },
    {
      "channel": "main",
      "a": "b",
      "b": "c",
      "a_interval": [1000, 1500],
      "b_interval": [800, 1300]
    }
  ]
}
```

## 接口约定：`POST /preview`

预演一项单点改动：分别编译**原编排**与**改动后编排**，输出两者差异。
`items` 为与 `POST /compile` 完全相同的口令数组（校验规则、错误码一致），
`change` 描述对某条现有口令的改动：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `items` | array | 是 | 口令数组，格式与 `POST /compile` 请求体相同 |
| `change` | object | 是 | 单点改动，见下方三个字段 |
| `change.id` | string | 是 | 要改动的现有口令 `id`；不存在时返回 `UNKNOWN_CHANGE_ID` |
| `change.offset_ms` | integer | 否 | 新的偏移（毫秒），允许为负；与 `duration_ms` **至少提供一个** |
| `change.duration_ms` | integer | 否 | 新的持续时长（毫秒），必须为正数；与 `offset_ms` **至少提供一个** |

差异规则：

- 改动只作用于目标口令的 `offset_ms` / `duration_ms`，**其余字段保持原值**，
  且请求中的 `items` 不会被修改；`change` 不允许携带其他字段。
- 原编排与改动后编排各自完整执行 `/compile` 的全部校验，任一失败即返回
  对应的 `422` 错误（如改动后时长非正返回 `INVALID_DURATION`）。
- `changed_ids`：时间起止（`start_ms` / `end_ms`）发生变化的口令 id，
  **含锚点依赖传导**（被改动口令的下游依赖一并计入），按 id 排序。
- 冲突对以 `(channel, a, b)` 判定身份：改动后出现的计入 `added_conflicts`
  （区间取自改动后版本），改动后消失的计入 `removed_conflicts`
  （区间取自改动前版本）；两个版本都存在的对（即使区间平移）不计入差异。
  两个列表各自按 `(a, b, channel)` 排序。

### 请求示例

```bash
curl -s http://localhost:8000/preview \
  -H 'Content-Type: application/json' \
  -d '{
    "items": [
      {"id": "a", "channel": "main", "anchor": "START", "offset_ms": 0,    "duration_ms": 1000},
      {"id": "b", "channel": "main", "anchor": "a",     "offset_ms": 0,    "duration_ms": 500},
      {"id": "e", "channel": "main", "anchor": "b",     "offset_ms": 0,    "duration_ms": 100},
      {"id": "f", "channel": "main", "anchor": "START", "offset_ms": 1400, "duration_ms": 200},
      {"id": "c", "channel": "main", "anchor": "START", "offset_ms": 2000, "duration_ms": 500}
    ],
    "change": {"id": "b", "duration_ms": 1500}
  }'
```

改动前：`b[1000,1500)`、`e[1500,1600)`，冲突对为 `(b,f)`、`(e,f)`。
将 `b` 的时长改为 `1500` 后：`b[1000,2500)`，锚定 `b` 的 `e` 随动为 `[2500,2600)`；
`b` 与 `c[2000,2500)` 新产生重叠，`e` 与 `f` 不再重叠。

响应示例（`200`）：

```json
{
  "changed_ids": ["b", "e"],
  "added_conflicts": [
    {
      "channel": "main",
      "a": "b",
      "b": "c",
      "a_interval": [1000, 2500],
      "b_interval": [2000, 2500]
    }
  ],
  "removed_conflicts": [
    {
      "channel": "main",
      "a": "e",
      "b": "f",
      "a_interval": [1500, 1600],
      "b_interval": [1400, 1600]
    }
  ]
}
```

## 错误处理

所有业务错误均返回 HTTP `422`，响应体统一为：

```json
{
  "code": "DEPENDENCY_CYCLE",
  "message": "检测到依赖环: a -> b -> a",
  "details": { "cycle": ["a", "b", "a"] }
}
```

错误码：

| `code` | 触发条件 |
| --- | --- |
| `INVALID_REQUEST` | 请求体不是合法的口令数组（字段缺失、类型错误、多余字段等） |
| `DUPLICATE_ID` | 数组中出现重复 `id` |
| `INVALID_ID` | `id` 为空，或使用了保留锚点名 `START` |
| `INVALID_CHANNEL` | `channel` 为空 |
| `INVALID_DURATION` | `duration_ms` 不是正数 |
| `MISSING_ANCHOR` | `anchor` 指向一个不存在的口令 id |
| `DEPENDENCY_CYCLE` | 锚点依赖构成环 |
| `NEGATIVE_START` | 解析出的口令起点小于 `0`（起点不允许为负） |
| `INVALID_CHANGE` | `/preview` 的改动未指定口令 id，或 `offset_ms` / `duration_ms` 均未提供新值 |
| `UNKNOWN_CHANGE_ID` | `/preview` 的改动指定的口令 id 在原编排中不存在 |

## 本地开发（不使用 Docker）

要求 Python 3.11+：

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

核心编排逻辑位于 `app/compiler.py`，仅使用标准库，可直接运行单元测试：

```bash
python3 -m unittest discover -s tests
```

## 项目结构

```
.
├── app/
│   ├── __init__.py
│   ├── compiler.py      # 纯标准库的依赖解析 / 时间计算 / 冲突检测 / 改动预演
│   ├── schemas.py       # Pydantic 请求与响应模型
│   └── main.py          # FastAPI 入口（/compile、/preview、/health、统一错误处理）
├── tests/
│   └── test_compiler.py # 核心逻辑单元测试（标准库 unittest）
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```
