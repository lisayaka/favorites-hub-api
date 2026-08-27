# Favorites Hub API

Favorites Hub 的独立 Python 后端，负责应用 Token、试用额度、限流、模型整理和服务端搜索能力。

当前提供账户与应用 Token 管理，以及基于可配置模型适配器、LangChain Structured Output 的两阶段分类和整理接口。默认使用 OpenAI `gpt-5.6-luna`、Responses API 和原生 Structured Outputs；也可通过服务端配置切换 DeepSeek。一次“整理全部/整理已选”先创建统一任务并固定扣除 10 credit，任务内请求使用幂等键记录实际 Token 用量；LangGraph 暂不使用。

## 本地开发

项目使用 Python 3.11 和 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync
cp .env.example .env
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

应用不会自动读取 `.env`。启动前请把其中变量注入进程环境；除 `DATABASE_URL`、`ADMIN_API_KEY` 和 `CORS_ALLOWED_ORIGINS` 外，默认模型调用还需要 `OPENAI_API_KEY`。供应商、模型、地址、推理强度、超时和输出上限可用 `.env.example` 中对应变量调整。浏览器扩展不能选择供应商、模型或传入模型密钥。

模型调用默认只记录模型、Schema、输入规模、耗时和 Token 用量。排查本地模型问题时可设置 `AI_LOG_MODEL_PAYLOADS=true`，额外打印完整模型消息、结构化响应和原始响应元数据；这些日志可能包含收藏标题、作者和来源文本，生产环境应保持关闭。日志会清洗已配置的 API Key、数据库连接串、管理员密钥和 Bearer Token。

本地加载插件后，可在扩展管理页复制 Extension ID，并配置显式来源：

```text
CORS_ALLOWED_ORIGINS=chrome-extension://<extension-id>
```

多个可信插件来源使用逗号分隔。禁止配置 `*`；Bearer Token 才是身份凭据，CORS 只限制浏览器来源，不能代替鉴权。

启动后访问 `http://127.0.0.1:8000/admin` 可使用简易账户管理页。页面通过同源 API 创建、查看、充值和撤销账户；管理员密钥仅保存在当前浏览器标签页。

健康检查：

```text
GET http://127.0.0.1:8000/health
```

## 账户接口

管理员接口通过 `X-Admin-Key` 请求头鉴权：

```text
POST /v1/admin/accounts
GET  /v1/admin/accounts
GET  /v1/admin/accounts/{account_id}
POST /v1/admin/accounts/{account_id}/revoke
POST /v1/admin/accounts/{account_id}/credits
```

创建账户时会返回一次 `fh_trial_...` 或 `fh_live_...` 应用 Token，数据库只保存哈希。客户端通过 Bearer Token 查询当前账户：

```text
GET /v1/account/me
Authorization: Bearer fh_trial_...
```

充值接口通过 `Idempotency-Key` 防止重复入账，只增加总额度并保留已使用额度和充值流水；已撤销或已过期账户不能充值。缺失、无效、过期或已撤销的 Token 返回 `401 invalid_app_token`。额度耗尽不影响读取账户状态，AI 接口会返回 `402 quota_exhausted`。

## AI 接口

```text
POST /v1/ai/jobs            # 创建一次整理任务并扣除 10 credit
POST /v1/ai/classify        # 每批最多 100 条：候选目录或按最终目录归类
POST /v1/ai/classify/merge  # 合并最多 10 套候选目录
POST /v1/ai/enrich          # 确认分类后，每批最多 10 条生成摘要和标签
PUT  /v1/index/items        # 全量替换当前账户的搜索派生文档
DELETE /v1/index/items/{id} # 删除单条搜索派生文档
POST /v1/search             # AI 语义搜索，一次固定扣除 2 credit
```

所有接口都需要 Bearer Token。整理和搜索请求还需要长度为 8～64 的 `Idempotency-Key`；分类、合并和整理还必须携带创建任务时返回的 `AI-Job-Id`。同一 Token、操作和幂等键重复提交相同请求会返回已保存结果；请求体不同则返回 `409 idempotency_key_conflict`。

插件对整个收藏夹分片生成候选目录，递归合并为统一的最多三级目录，再将全部待分类收藏按最终目录重新归类。首次分类以全量收藏为输入；增量分类传现有目录与全部未分类收藏，已有目录不可修改，但允许追加分类。100 条只是单次内部调用上限，不限制收藏夹总量。

模型阶段使用最小 Structured Output：`candidate` 只生成 `categories`，`assign` 只生成 `assignments`。后端在统一 HTTP 响应中为最终归类附回请求中的目录，避免模型重复输出无用数据。

创建整理任务时可附带最多 300 字的 `organization_instruction`，例如“风格活泼；新分类名称可适量添加颜文字”。该偏好在任务内固定，仅影响新分类显示名称、说明、摘要和标签表达，不得改变已有目录、分类归属、证据约束与输出结构。创建任务时原子扣除 10 credit；同一任务内无论发生多少次候选生成、目录合并、最终归类和摘要分片，都不再扣费。搜索按一次用户请求固定扣除 2 credit，并将整个账户索引按每批 100 条交给模型筛选后合并排序。幂等重放不会重复扣费或重复调用模型。搜索索引只保存收藏 ID、来源、标题、摘要、标签和最多三级分类路径，不保存完整收藏正文。

运行验证：

```bash
uv run pytest
uv run python -m compileall -q app tests
```

## 演进顺序

1. 增加每分钟、每日和并发限流；当前只实现试用总额度的原子预占与结算。
2. 评估 Embedding 与向量召回，替换当前按 100 条分片的模型检索。
3. 只有出现服务端多步骤分支或服务端断点恢复时才引入 LangGraph。

详细边界与开发约定见 `AGENTS.md`。
