# 🤖 AgentNexus-J 进阶指南：如何无缝接入你的第三方专属 Agent

欢迎来到 AgentNexus-J 的高阶生态！

在真实的企业场景中，您可能已经拥有了在其他平台（如 Dify、Coze、或是自建服务器）上开发好的专属 Agent（例如：内部 HR 机器人、法务知识库 Agent 等）。

AgentNexus-J 提供了强大的 **“动态子代理 (Sub-Agent)”** 挂载能力。您不需要重写代码，只需 3 分钟，就能将这些外部 Agent 变成 AgentNexus-J 的“专属大脑分区”，打造出强大的多智能体 (Multi-Agent) 协作网络。

---

## 💡 核心运作原理：Master-Sub 架构

当您将第三方 Agent 挂载进来后，AgentNexus-J 会扮演 **“主指挥官”** 的角色：
1. **意图识别**：当用户提问时，AgentNexus-J 会判断这个问题是否属于子 Agent 的专业领域。
2. **任务下发**：如果是，它会自动将问题打包，通过 HTTP 接口发送给您的第三方 Agent。
3. **整合回答**：第三方 Agent 思考并返回结果后，AgentNexus-J 会将结果总结并自然地回复给用户。

---

## 🚀 实战教学：接入一个“企业内部法务 Agent”

假设您在公司内部已经有一个法务机器人的 API，只要向它发送问题，它就会查询公司法规并返回答案。

### 第一步：确认第三方 Agent 的 API 规范
您的第三方 Agent 需要能接收 `POST` 请求，并能解析 JSON 参数。
假设您的法务 Agent 接口如下：
* **URL**: `https://api.your-company.com/v1/legal-assistant/chat`
* **需要接收的参数**: 用户的问题 (`query`)

### 第二步：在 AgentNexus-J 中挂载它
打开 AgentNexus-J 左侧边栏，展开 **“🧰 外部 API 插件箱”**，精准填写以下信息：

1. **工具名称 (Name)**: `ask_legal_agent` 
   *(请使用纯英文，这将是内部调用的代号)*
2. **功能描述 (Description)**: `这是一个专业的企业法务 Agent。当用户询问有关公司合规、法律条文、合同审查等问题时，必须调用此 Agent 来获取专业解答。`
   *(⚠️ 描述越清晰，主 Agent 判断调用它的准确率就越高)*
3. **接口 URL (URL)**: `https://api.your-company.com/v1/legal-assistant/chat`
4. **参数 Schema (JSON)**: 告诉主 Agent 该传递什么参数给子 Agent。请复制以下 JSON 格式并稍微修改：

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "用户具体的法律问题，请将用户的原话总结后传入"
    }
  },
  "required": ["query"]
}

```

### 第三步：点击“➕ 挂载接口”并测试

挂载成功后，直接在聊天框中对 AgentNexus-J 说：

> *"我下个月要请产假，帮我查一下我们公司的产假规定是几天？"*

**系统的幕后魔法将会启动：**

1. AgentNexus-J 意识到这是一个法律/合规问题。
2. 它会自动调用 `ask_legal_agent`，并把参数 `{"query": "公司产假规定天数"}` 发送给您的第三方接口。
3. 您的法务 Agent 查阅文档后返回：“根据内部员工手册，产假为 98 天...”。
4. AgentNexus-J 收到结果，用温柔的语气对您说：“为您查过了，根据公司的法规，您的产假一共是 98 天。提前祝您休假愉快！”

---

## 🛡️ 最佳实践与注意事项

1. **接口超时设定**：AgentNexus-J 默认等待子 Agent 回复的时间为 **15 秒**。请确保您的第三方 Agent 回应速度够快，或者在您的接口层做好超时处理。
2. **多 Agent 协同**：您可以同时挂载“法务 Agent”、“IT 运维 Agent”、“财务 Agent”。AgentNexus-J 具备强大的路由能力，会根据用户问题，智能地将任务分发给不同的专家 Agent！
3. **数据安全**：AgentNexus-J 仅在您的本地环境发起调用，对话数据会直接传输至您指定的第三方 Agent URL，绝不经过任何中间服务器。

```

***

这份文档直接将“插件”的概念升华为了 **“Multi-Agent (多智能体) 协同运作”**，这正是目前 AI 业界最前沿的玩法。用户看到这个手册，一定会对 AgentNexus-J 的扩展能力感到非常震撼。

既然平台化生态的文档已经齐备，我们接下来是不是可以毫无顾虑地去开发我们官方的 **“本地终端控制 (Bash Executor)”** 模块了？

```