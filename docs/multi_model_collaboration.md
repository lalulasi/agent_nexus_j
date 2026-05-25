# 多模型协作功能 · 技术设计文档

> AgentNexus-J v0.2 · 作者：Jude

---

## 一、功能概述

多模型协作功能允许用户将多个异构大语言模型（LLM）组合成一个协作团队，对同一问题进行多角度分析、交叉评审，最终输出经过多模型验证的高质量答案。

支持两种协作模式，最多同时调用 5 个模型：

| 模式 | 适用场景 | 核心特点 |
|------|----------|----------|
| **圆桌模式** | 分析类、创意类、有争议话题 | 多角色迭代辩论 + 综合归纳 |
| **主从模式** | 高准确性要求、答案质量校验 | 主模型作答 + 多评委评分改进 |

---

## 二、圆桌模式（Round Table）

### 2.1 算法来源

圆桌模式融合了两种经典算法：

- **方案 B（迭代辩论）**：多轮对话，每轮模型可见上轮所有答案，基于他人观点修正自己
- **方案 C（角色圆桌）**：每个模型被强制分配唯一角色，从该角色视角出发，产出差异化内容

两者结合后，既有迭代学习的深度，又有角色差异化保证内容不同质化。

### 2.2 角色系统

| 角色 | 标识 | 职责 |
|------|------|------|
| 提案者 Proposer | 🎯 | 给出最直接、最优化的答案，聚焦解决方案 |
| 批判者 Critic | 🔍 | 专门找漏洞、逻辑错误和不完整之处 |
| 创意者 Creative | 🌈 | 提出非传统的跳出框架的创新思路 |
| 验证者 Validator | 📊 | 用数据和逻辑验证或推翻各方观点 |
| 综合者 Synthesizer | 🔀 | 提炼共识，处理分歧，输出最终答案 |

**角色自动分配规则**（按模型数量）：

```
2 个模型：提案者 → 综合者
3 个模型：提案者 → 批判者 → 综合者
4 个模型：提案者 → 批判者 → 创意者 → 综合者
5 个模型：提案者 → 批判者 → 创意者 → 验证者 → 综合者
```

综合者始终是最后一个槽位，负责汇总全部过程。

### 2.3 执行流程

```
┌─────────────────────────────────────────────┐
│  用户提问                                     │
└──────────────────┬──────────────────────────┘
                   │
        ┌──────────▼──────────┐
        │   Round 1：独立作答  │
        │  （所有面板模型并行）  │
        │  模型 A, B, C 各自   │
        │  以角色 prompt 独立  │
        │  回答，互不可见       │
        └──────────┬──────────┘
                   │ 全部结果可见
        ┌──────────▼──────────┐
        │   Round 2：交叉审视  │
        │  （所有面板模型并行）  │
        │  每个模型看到所有     │
        │  R1 答案，从角色视角  │
        │  评述/补充/反驳       │
        └──────────┬──────────┘
                   │ 所有轮次结果
        ┌──────────▼──────────┐
        │   综合者汇总（流式）  │
        │  提炼共识，处理分歧   │
        │  输出最终答案         │
        └─────────────────────┘
```

### 2.4 并发设计

每轮内部所有非综合者模型通过 `asyncio.gather()` **并行调用**，不互相等待：

```python
results = await asyncio.gather(*[
    _call_one(slot, context_suffix) for slot in panel_slots
])
```

综合者在所有轮次结束后串行调用，并以流式（SSE）实时输出最终答案。

### 2.5 上下文构建策略

- **Round 1**：每个模型只接收用户原始问题 + 角色 Prompt，无任何他人信息
- **Round 2+**：在用户问题后追加所有先前轮次的结果摘要，模型基于此进行审视和补充
- **综合者**：接收所有轮次、所有角色的完整输出，进行最终归纳

---

## 三、主从模式（Master-Slave）

### 3.1 执行流程

```
用户提问
   │
   ▼
主模型作答（流式，用户实时可见）
   │
   ▼
评委模型并行评审（asyncio.gather）
   │  每位评委返回结构化 JSON：
   │  {scores, critique, improved_answer}
   │
   ▼
加权评分排名 → 取最高分改进版
   │
   ▼
输出最终答案（最优改进版）
```

### 3.2 评审评分体系

评委模型被要求以结构化 JSON 格式输出评审结果：

```json
{
  "scores": {
    "accuracy":     9,
    "completeness": 8,
    "clarity":      9,
    "reasoning":    8
  },
  "critique": "具体指出2-3个优缺点",
  "improved_answer": "改进后的完整答案"
}
```

**加权综合评分公式：**

```
综合分 = accuracy × 0.30
       + completeness × 0.25
       + clarity × 0.25
       + reasoning × 0.20
```

| 维度 | 权重 | 考察重点 |
|------|------|----------|
| 准确性 (accuracy) | 30% | 事实正确、无错误信息 |
| 完整性 (completeness) | 25% | 覆盖全面、无重要遗漏 |
| 清晰度 (clarity) | 25% | 表达清晰、结构合理 |
| 逻辑性 (reasoning) | 20% | 推理严密、论据充分 |

综合分最高的评委的 `improved_answer` 作为最终输出。

### 3.3 JSON 提取健壮性

评委模型返回格式不一（部分模型会加 markdown 围栏或前缀说明），使用双重提取策略：

```python
# Step 1: 移除 markdown 代码围栏
cleaned = re.sub(r"```(?:json)?\s*", "", raw_text).strip()

# Step 2: 正则定位 JSON 对象（兼容前后有额外文字）
m = re.search(r"\{[\s\S]*\}", cleaned)
raw_json = m.group() if m else cleaned

data = json.loads(raw_json)
```

---

## 四、架构设计

### 4.1 核心组件

```
CollaborationOrchestrator
├── stream_run()              # 入口，分发到对应模式
├── _stream_round_table()     # 圆桌 B+C 算法
├── _stream_master_slave()    # 主从评审算法
├── _load_tools()             # 工具集加载（复用现有工具）
├── _auto_title()             # 会话自动命名
└── _save_message()           # 消息持久化
```

与普通 `AgentOrchestrator` 完全隔离，通过 `chat.py` 路由分发：

```python
if session.collab_mode:
    collab = CollaborationOrchestrator(db)
    # SSE stream
else:
    orchestrator = AgentOrchestrator(db)
    # SSE stream
```

### 4.2 数据模型扩展

在 `agent_sessions` 表新增两列（Alembic 迁移）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `collab_mode` | `VARCHAR(20)` | `NULL` / `round_table` / `master_slave` |
| `collab_config` | `JSONB` | 协作配置（模型列表、角色、轮次等） |

**圆桌模式配置结构：**
```json
{
  "mode": "round_table",
  "rounds": 2,
  "models": [
    {"config_id": "uuid", "role": "proposer"},
    {"config_id": "uuid", "role": "critic"},
    {"config_id": "uuid", "role": "synthesizer"}
  ]
}
```

**主从模式配置结构：**
```json
{
  "mode": "master_slave",
  "master_config_id": "uuid",
  "reviewer_config_ids": ["uuid1", "uuid2"]
}
```

### 4.3 SSE 流式事件协议

协作过程通过扩展的 SSE 事件类型实时推送：

| 事件类型 | 触发时机 | 携带数据 |
|----------|----------|----------|
| `collab_phase` | 进入新阶段 | `phase`, `label` |
| `collab_model_text` | 主模型流式输出 | `role`, `model_name`, `content` |
| `collab_model_end` | 主模型输出结束 | `role`, `usage` |
| `collab_model_result` | 某圆桌模型本轮完成 | `round`, `role`, `role_label`, `model_name`, `content` |
| `collab_reviewer_result` | 某评委评审完成 | `model_name`, `scores`, `weighted_total`, `critique`, `improved_answer` |
| `collab_synthesis_start` | 综合者开始输出 | `model_name`, `score`（主从）|
| `text` | 最终答案流式文字 | `content` |
| `done` | 全部完成 | `usage` |

---

## 五、前端展示设计

### 5.1 实时进度显示

使用三个 `st.empty()` 占位符实现流式更新，无需整页刷新：

| 占位符 | 圆桌模式 | 主从模式 |
|--------|----------|----------|
| `phase_ph` | `⚡ Round 1 · 独立作答...` → `✅ 提案者完成` | `⚡ 主模型作答...` → `⚡ 评委评审中...` |
| `live_ph` | — | 主模型流式文字（带 `▌` 光标） → 最终答案流式 |
| `score_ph` | — | 每位评委完成后追加一行评分摘要 |

流式结束后三个占位符清空，渲染正式的结果卡片。

### 5.2 协作过程持久化

过程数据存入 `st.session_state.last_collab_process`，在以下时机生效：

- **回复完成后**：过程卡片渲染在最终答案上方，刷新/rerun 后仍可见
- **下一条消息发送时**：`last_collab_process = []`，过程清除
- **历史渲染时**：检测最后一条 assistant 消息，若有 process 数据则恢复显示

### 5.3 评审 UI 层级

```
▼ 📊 协作评审过程（N 位评委）  [默认折叠]
  ▼ 👑 主模型原始答案          [默认折叠]
  ┌──────────────────────────────┐
  │ ⚖️ 模型 A         8.5 / 10  │
  │ 准确 9 · 完整 8 · 清晰 9 · 逻辑 8 │
  │ 💬 优点：... 缺点：...       │
  │ ▼ 📝 改进版本               │
  └──────────────────────────────┘
  ┌──────────────────────────────┐
  │ ⚖️ 模型 B 🏆     9.1 / 10  │
  │ ...                          │
  │ ▼ 📝 改进版本  [默认展开]    │  ← 最优者改进版默认展开
  └──────────────────────────────┘
  ✅ 采用 模型 B 改进版（综合最高 9.1/10）

[最终答案正文]
```

---

## 六、工具与 System Prompt 策略

| 配置项 | 策略 | 理由 |
|--------|------|------|
| **工具集** | 所有模型共享同一套激活工具 | 协作模型解决同一问题，工具需求一致；分别配置会增加复杂度且无实质收益 |
| **System Prompt** | 用户设置的基础 SP 自动注入所有模型 | 保持上下文一致性；圆桌模式的角色 Prompt 自动追加在 SP 之后 |
| **角色 Prompt** | 框架自动注入，用户无需干预 | 角色分工由框架管理，用户只需选模型 |

---

## 七、自动命名

协作会话使用 `stream()` 而非 `complete()` 调用命名模型，规避 DeepSeek 等推理模型 `reasoning_content` 污染标题的问题：

```python
async for item in naming_adapter.stream(msgs, system, 100):
    if isinstance(item, str):       # 只收集实际输出，过滤推理过程
        title_text += item

# 最终兜底：若模型输出为空，取用户消息前10字
if not title:
    title = user_message.strip()[:10]
```

---

## 八、设计决策记录

| 决策 | 选择 | 放弃的方案 | 原因 |
|------|------|-----------|------|
| 圆桌算法 | B+C 融合（迭代辩论 + 角色分工） | 纯并行聚合（A）、德尔菲法（D） | A 无真实交互，D 需要 embedding 相似度计算且实现复杂 |
| 评委评分 | 结构化 JSON + 加权综合 | 自然语言评审 | JSON 可解析、可排名、可可视化 |
| 并发策略 | `asyncio.gather()` 并行 | 串行顺序调用 | 大幅减少总等待时间（N 个模型耗时 ≈ 最慢那个） |
| 流式协议 | 扩展 SSE 事件类型 | WebSocket | 与现有普通对话复用同一 `/chat/stream` 端点，改动最小 |
| 过程持久化 | `st.session_state` | 存入数据库 | 过程数据是临时性展示内容，无需跨设备持久化，session state 足够 |
