"""
创新点1：AgentNexus-J 平台双身份 — 作为 MCP Server 暴露平台能力。

当前状态：占位文件，/mcp 路由返回 501 Not Implemented。

未来计划暴露的工具：
  collaborate(messages, mode)  → 触发多模型协作
  query_knowledge(question)    → RAG 向量检索
  run_tool(tool_name, args)    → 调用平台已注册工具

实现方向：
  1. 在此文件实现 MCPHostServer 类，使用 HTTP+SSE 服务端逻辑
  2. 在 main.py 的 /mcp 路由下挂载 SSE endpoint
  3. MCPClientManager 增加 accept_reverse_connection() 接口存根（已预留）

参考：connection.py 中的客户端 SSE 通信逻辑，服务端为其镜像。
"""
