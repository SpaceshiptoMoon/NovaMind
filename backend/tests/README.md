# backend/tests

测试按**被测对象所在分层**组织，镜像 `src/` 的目录结构。分类判据是测试文件 import 的被测模块，不是文件名前缀。

## 目录结构

```text
tests/
├── conftest.py        # sys.path 引导、tmp_db fixture、integration 跳过逻辑（对子目录自动生效）
├── fixtures/          # 共享测试数据（openapi_baseline.json、test_set.csv/json）
├── architecture/      # 全局结构门禁与 API 契约快照（AST 扫描、openapi 逐键比对、跨层接缝不变式）
├── core/              # 被测对象在 src/core/（database、middleware、auth、authorization、ws）
├── shared/            # 被测对象在 src/shared/（ai_models 等）
├── engines/           # 被测对象在 src/engines/，子目录镜像其结构
│   ├── agent/
│   ├── deep_research/
│   ├── document/      # pipeline / splitters 层测试
│   │   ├── deepdoc/   # vendored DeepDoc（含 page_filter）
│   │   └── media/     # audio / video / vlm
│   ├── eval/
│   ├── rag/
│   └── resume/
├── features/          # 被测对象在 src/features/<domain>/，子目录镜像其结构
│   ├── agent/
│   ├── knowledge_space/
│   ├── qa/
│   ├── skill/
│   └── user/
└── integration/       # pytest.mark.integration：需 :8100 运行服务，默认跳过
```

## 新测试放哪里（决策树）

1. **全局结构门禁 / 契约 / 跨层接缝**（AST 扫描、openapi 快照、"X 层不得 import Y"）→ `architecture/`
2. **需运行中的 :8100 服务**（TestClient 打真实 HTTP、跨服务端到端）→ `integration/`，并标 `pytest.mark.integration`
3. 被测模块在 `src/core/...` → `core/`
4. 被测模块在 `src/shared/...` → `shared/`
5. 被测模块在 `src/engines/<x>...` → `engines/<x>/`（document 引擎下属 deepdoc / media 再进一层）
6. 被测模块在 `src/features/<domain>...` → `features/<domain>/`
7. **回归测试优先跟被测对象走**，即使它由某次业务 bug 触发（如 `zombie_job_purge` 测的是 knowledge_space 任务流，就放 `features/knowledge_space/`）

拿不准时看文件顶部 `from novamind.<area>...` import 的第一被测模块。

## 标记体系

| 标记 | 用途 | 默认是否运行 |
|---|---|---|
| `pytest.mark.unit` | 纯单测（CI 跑的就是它们） | 是 |
| `pytest.mark.integration` | 需 :8100 服务 | **否**（conftest 自动跳过，`--run-integration` 才跑） |
| `pytest.mark.slow` | 慢速测试（预留） | 是 |

CI（`.github/workflows/ci.yml`）执行 `pytest -m unit -q`，所以新增测试要么标 `unit`，要么标 `integration`，否则默认全量 `pytest` 才会跑到。

## 惯例与陷阱

- **SQLite 定向建表**：`Base.metadata.create_all` 全量建表在 SQLite 会因跨 feature 同名 Index 报错。用 conftest 的 `tmp_db` fixture，或仿照现有测试 `create_all(conn, tables=[...])` 定向建表。
- **`Path(__file__).resolve().parents[N]` 深度随目录层级变化**：`parents[N]` 从测试文件出发，N = 到目标目录的层级数。文件在 `tests/x/y/` 里比在 `tests/` 根里深 2 层，`BACKEND_ROOT` 就要多退 2 级。移动测试文件时务必同步调整。
- **fixture 数据**放 `tests/fixtures/`，引用用相对测试文件的路径常量；仓库级样例（音视频等大文件）放 repo 根 `test_data/`，用 `parents[N]` 回退到仓库根引用。
- **conftest.py 只放真正全局的东西**（sys.path、跳过逻辑、跨目录 fixture）。某目录专属的 helper 留在该目录测试文件内，或建该目录自己的 conftest.py。
- **openapi baseline 重新生成**（改路由后必须）：

  ```bash
  cd backend
  PYTHONPATH=src .venv/Scripts/python.exe -c "
  import json; from novamind.core.middleware.app_factory import create_app
  json.dump(create_app().openapi(), open('tests/fixtures/openapi_baseline.json','w',encoding='utf-8',newline=''), ensure_ascii=False, indent=2, sort_keys=True)"
  ```

## 常用命令

```bash
cd backend

pytest                                   # 全量（integration 默认跳过）
pytest -m unit -q                        # 与 CI 一致
pytest tests/features/knowledge_space    # 只跑某域
pytest --run-integration                 # 需先启动 :8100 服务
pytest --collect-only -q | tail -3       # 检查收集数（重组/改名后核对）
```
