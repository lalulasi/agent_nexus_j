"""
创新点2：智能能力路由 Agent。

当前状态：占位文件。collab_mode="auto" 在会话接口已允许，
暂时 fallback 到普通单模型模式并提示用户。

目标行为（未来实现）：
  用户发送 Query → RoutingAgent 分析意图与所需能力
    → 匹配 CapabilityEntry.tags（已在 protocol.py 预留）
    → 自动选择最优模式和参与者组合
    → 执行并在 UI 展示「为您自动选择：圆桌模式 · Claude + 合同审查助手」

示例路由规则：
  Query 含代码关键词  → 选 code_reviewer (MCP) + 最强 LLM · 主从模式
  Query 含文档/检索   → 开启 RAG + 选 proposer/validator 圆桌
  Query 为开放讨论    → 3 模型圆桌，2 轮

实现入口：
  class RoutingAgent:
      async def route(
          self,
          query: str,
          available_llms: list[LLMConfig],
          available_mcp: list[CapabilityEntry],
      ) -> CollabConfig:
          ...
"""
