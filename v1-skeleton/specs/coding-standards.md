# AI 知识库 · 编码规范 v0.2

## 1. 通用约定

- **缩进**：Python 4 空格，TypeScript 2 空格
- **行尾**：LF（Unix），禁止 CRLF
- **文件末尾**：保留一个空行
- **行宽**：Python 88（Black 默认），TypeScript 100（Prettier 默认）
- **错误处理**：禁止 `pass` / 空 `catch`，必须记录日志或重新抛出
- **日志**：Python 用 `logging` 模块，TS 用统一 logger 工具，禁止 `print()` / `console.log()`
- **凭据**：严禁硬编码，必须通过环境变量注入

## 2. Python 规范

| 工具 | 职责 |
|------|------|
| Black | 自动格式化（行宽 88） |
| ruff | 代码 lint、import 排序、最佳实践检测 |
| mypy | 静态类型检查 |

- 命名：变量/函数/方法 `snake_case`，类 `PascalCase`，常量 `UPPER_CASE`
- 文档：**所有**公开函数必须写 Google 风格 docstring（含 `__init__`、`@property`、`@overload` 重载、一行简单函数）
- 类型：函数参数和返回值必须标注 type hints
- 导入：stdlib → 3rd-party → local，三段式字母序

## 3. TypeScript 规范

```jsonc
// tsconfig.json strict: true
// 不额外开启 noUncheckedIndexedAccess / exactOptionalPropertyTypes / noPropertyAccessFromIndexSignature
```

| 工具 | 职责 |
|------|------|
| Prettier | 自动格式化（行宽 100，单引号，尾随逗号） |
| ESLint | 代码 lint，配合 `typescript-eslint` |
| vitest | 单元测试 |

- 命名：变量/函数/方法 `camelCase`，类/接口/类型 `PascalCase`，常量 `UPPER_CASE`，文件名 `kebab-case`
- 类型：禁用 `any`，优先 `interface` 而非 `type`
- 文档：所有公开函数写 JSDoc（含 `@param` / `@returns`），含 `get` / 简单函数 / 重载声明
- 导入：external → internal，字母序，禁止 `import *`
- 异步：优先 `async/await`，并行请求用 `Promise.all()`

## 4. 魔法字符串

- 同一字面量在代码中出现 ≥2 处 → 提取为**模块级常量**
- 不强制使用 Enum，常量即可
- 示例：

```diff
- if lang == "Python":
+ PYTHON = "Python"
+ if lang == PYTHON:
```

## 5. TODO 管理

- 本地拦截：**pre-commit hook**（`git commit` 前 grep 拦截）
- 拦截关键词：`TODO` / `FIXME` / `HACK` / `XXX`
- 放行规则：`TODO(#issue-number)` 带 issue 引用的不拦截
- 白名单：一旦关联 issue，允许进入 main

## 6. 单测与覆盖率

| 维度 | Python | TypeScript |
|------|--------|------------|
| 框架 | pytest + coverage.py | vitest |
| 测试目录 | `tests/` | `tests/` |
| line | ≥80% | ≥80% |
| branch | ≥80% | ≥80% |
| function | ≥80% | ≥80% |

## 7. CI（GitHub Actions）

- Python / TypeScript 串行执行
- 流程：`lint → typecheck → test`
- Python：`ruff check` → `mypy` → `pytest --cov`
- TypeScript：`eslint` → `tsc --noEmit` → `vitest --coverage`
- 额外：`pre-commit run --all-files` 确保本地与 CI 一致

## 8. 提交规范

采用 Conventional Commits，格式：

```
<type>(<scope>): <description>
```

scope 可选，允许的 type：

| type | 说明 |
|------|------|
| `feat` | 新功能 |
| `fix` | 修复 bug |
| `refactor` | 重构（非功能、非修复） |
| `chore` | 杂项（CI、依赖、配置） |
| `docs` | 文档变更 |
| `test` | 测试变更 |

示例：

```
feat(collector): add hacker news source adapter
fix(analyzer): handle None summary from LLM response
chore: pin ruff to 0.9.x in CI
```

## 9. pre-commit 钩子

- 配置入口：`.pre-commit-config.yaml`
- 必须包含：
  - ruff check + ruff format
  - prettier（针对 TS/JSON/MD）
  - eslint
  - TODO 拦截检查（自定义 hook）
- CI 中 `pre-commit run --all-files` 验证全部文件
