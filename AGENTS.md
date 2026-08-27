# Favorites Hub API 项目约定

## 项目定位

Favorites Hub API 是收藏汇浏览器扩展的独立后端。它负责需要服务端可信边界的能力：

- 签发和校验收藏汇应用 Token。
- 管理试用账号、有效期、额度、限流和用量。
- 保管模型供应商密钥并代理模型请求。
- 提供模型摘要、标签和自动分类。
- 后续维护收藏派生索引并提供服务端搜索。

浏览器扩展仍是用户收藏原始数据的本地主存储。第一阶段后端不保存完整收藏库，也不负责媒体页面抓取。

## 当前实现状态

当前已实现：

- Python 3.11 项目环境。
- FastAPI 应用。
- `GET /health` 健康检查。
- PostgreSQL、SQLAlchemy 和 Alembic 迁移基础设施。
- 以邮箱为唯一标识的账户创建、查询、列表和撤销。
- 有效账户的幂等额度充值与充值流水。
- 管理员 API Key 鉴权、应用 Token 签发与 `GET /v1/account/me` 校验。
- 可通过 `CORS_ALLOWED_ORIGINS` 显式允许可信浏览器扩展来源。
- `POST /v1/ai/jobs` 创建统一整理任务，一次固定扣除 10 credit。
- `POST /v1/ai/classify` 分片生成候选目录并按最终目录归类，现有目录不可由模型修改但允许追加分类。
- `POST /v1/ai/classify/merge` 递归合并候选目录，支持超过 100 条的整个收藏夹分类。
- `POST /v1/ai/enrich` 每批最多 10 条生成摘要和标签。
- `PUT /v1/index/items` 全量替换账户隔离的搜索派生文档，`DELETE /v1/index/items/{item_id}` 删除单条文档。
- `POST /v1/search` 按每批 100 条调用模型执行语义检索，一次固定扣除 2 credit，并支持幂等重放。
- 可配置 OpenAI/DeepSeek 模型适配、LangChain Structured Output、最多三级目录校验、任务范围限制与幂等请求。
- `/admin` 同源简易账户管理页。
- 账户、AI 接口与健康检查测试，模型调用在普通测试中使用 Mock。

当前尚未实现：

- 每分钟、每日、并发与请求体总字节限流；当前只实现单次数量上限和试用总额度账本。
- Embedding、向量召回和混合检索；当前搜索使用分片模型筛选与合并排序。
- LangGraph 工作流。

不要把路线图中的能力描述成已经可用。

## 技术决策

### API 层

- 使用 FastAPI 和 Pydantic。
- API 层只负责协议、鉴权依赖、输入输出校验和错误映射。
- 业务规则不得写入路由函数。
- 对外接口统一使用 `/v1` 前缀；`/health` 除外。

### 模型层

- 当前默认使用 LangChain `ChatOpenAI`、OpenAI Responses API 与 `gpt-5.6-luna`，可通过服务端 `AI_PROVIDER`/`AI_MODEL` 切换允许的供应商和模型。
- 使用 Pydantic Schema 和 `with_structured_output` 生成摘要、标签和分类。
- 模型供应商密钥只从服务端环境变量或密钥管理服务读取。
- 客户端只能选择后端允许的模型或能力，不能传入任意模型、Base URL、提示词和输出上限。
- 模型调用必须设置超时、输出上限，并记录模型、Token 用量、耗时和请求 ID。

### LangGraph 引入条件

第一阶段不安装 LangGraph。出现下列真实需求之一时再引入：

- 多个模型或工具节点之间存在条件分支。
- 关键词和向量召回需要并行执行、合并与条件重排。
- 长任务需要 Checkpoint 和故障恢复。
- 需要人工审核后继续执行。
- 需要从指定步骤恢复，而不是重新执行整个请求。

普通 HTTP 重试、单次模型调用和 Pydantic 校验不使用 LangGraph。

### 数据库

- 开始实现试用账号和用量账本时使用 PostgreSQL。
- 额度预占、结算、撤销和幂等记录必须在事务中完成。
- 低流量限流先使用数据库原子更新；确认数据库成为瓶颈后再加 Redis。
- 数据访问集中在 Repository，不允许路由或模型层直接执行 SQL。
- Schema 变更必须通过迁移，禁止启动时静默改表。

## 目标架构

```text
Chrome 扩展
  → FastAPI Route
  → 应用 Token 鉴权
  → 额度预占与限流
  → Application Service
  → LangChain 模型调用 / Search Service
  → 额度结算与用量记录
  → 响应扩展
```

层级职责：

- `app/api/`：路由、依赖和 HTTP 错误映射。
- `app/schemas/`：请求、响应和模型 Structured Output。
- `app/services/`：鉴权、额度、整理和搜索用例。
- `app/repositories/`：数据库访问。
- `app/integrations/`：LangChain、模型供应商和未来向量存储。
- `app/workflows/`：仅在引入 LangGraph 后创建。
- `tests/`：按用例覆盖最小关键路径。

目录只在出现实际文件时创建，不预建空包。

## 应用 Token

收藏汇后端签发的是应用 Token，不是模型供应商 API Key。

Token 建议使用不可预测的随机值并带环境前缀：

```text
fh_trial_...
fh_live_...
```

必须遵守：

- 数据库只保存 Token 哈希，明文只在签发时返回一次。
- Token 包含类型、状态、有效期、总额度和最后使用时间。
- 支持撤销、过期和额度耗尽。
- 管理员接口与普通业务接口使用不同权限。
- 模型供应商密钥不得返回客户端、写入日志或进入收藏导出。

## 额度、限流与用量

至少支持：

- 单次请求收藏数量上限。
- 单个 Token 的每分钟请求上限。
- 每日额度。
- 试用期总额度。
- 模型白名单和最大输出 Token。
- 请求体大小、并发数和执行超时。

用量以供应商返回的实际输入/输出 Token 为准。请求需要幂等键，避免客户端重试导致重复调用。

推荐状态流转：

```text
验证 Token → 幂等创建整理任务并原子扣除 10 credit
  → 任务内按受限调用次数执行分类、合并和整理，不重复扣费
```

每次用户搜索固定扣除 2 credit；相同幂等键重放不得重复扣费或重复调用模型。

## 整理接口

当前接口：

```text
POST /v1/ai/jobs
POST /v1/ai/classify
POST /v1/ai/classify/merge
POST /v1/ai/enrich
```

输入只包含整理所需的最小数据，例如收藏 ID、来源、标题、作者和有限的来源文本。

输出至少包含：

- `summary`
- `tags`
- `category`
- `model`
- `prompt_version`
- `usage`

模型输出必须通过 Pydantic 校验。不能把缺乏证据的推测写成来源事实。模型失败不得覆盖客户端已有的人工摘要和标签。

## 搜索接口

当前提供：

```text
PUT    /v1/index/items
DELETE /v1/index/items/{item_id}
POST   /v1/search
```

服务端只保存必要的派生搜索文档，使用 `account_id + item_id` 隔离。搜索结果返回收藏 ID、分数和命中原因，由扩展映射本地完整记录。当前实现按每批 100 条调用模型并合并排序，尚未使用 Embedding 或向量数据库。

后续引入的 Embedding 仍应是可重建的派生数据，必须记录内容指纹、模型和版本。删除收藏时必须同步删除服务端索引，或在下一次全量替换索引时清除。

## 安全与隐私

- 不保存模型原始响应和完整提示词；只为幂等重放保存通过校验的结构化响应。
- 日志只记录请求 ID、用户/Token ID、模型、Token 用量、耗时、状态和错误码。
- 禁止记录应用 Token 明文、模型供应商密钥、Cookie 和登录态。
- 所有生产请求必须使用 HTTPS。
- CORS 只允许明确配置的扩展来源或管理端来源。
- `CORS_ALLOWED_ORIGINS` 禁止使用 `*`，且 CORS 不能代替管理员或应用 Token 鉴权。
- 输入长度、列表大小和所有枚举值必须在可信边界校验。
- 错误响应不得包含供应商密钥、数据库连接串或内部堆栈。

## 依赖原则

- 依赖随实际功能加入，禁止为路线图提前安装。
- 优先使用标准库和现有依赖。
- LangChain 仅用于当前模型调用和 Structured Output。
- LangGraph、Redis、任务队列和向量扩展必须由真实需求触发。
- 新增依赖必须说明解决的问题，并留下最小可运行测试。

## 开发流程

1. 从一个完整的垂直用例开始，不同时铺开账号、模型和搜索。
2. 先定义请求、响应、失败行为和安全边界。
3. 实现最小业务逻辑和 Repository。
4. 为成功、鉴权失败、额度不足和外部依赖失败留下测试。
5. 运行格式、静态检查和最相关测试。
6. 架构边界变化时同步更新本文件和 README。

## 验证

每次修改至少运行相关命令：

```bash
uv run pytest
uv run python -m compileall -q app tests
```

新增模型调用时必须使用 Mock 覆盖外部服务，不在普通测试中消耗真实额度。

交付时必须说明：

- 修改了什么。
- 运行了哪些验证及结果。
- 哪些路线图能力仍未实现。
- 是否存在无法执行的外部集成验证。
