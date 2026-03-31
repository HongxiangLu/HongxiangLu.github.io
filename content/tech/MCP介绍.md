---
title: "MCP介绍"
date: 2026-03-31T10:00:00+08:00
slug: mcp-intro
draft: false
categories:
    - "技术"
---

## 1. 什么是 MCP？

Model Context Protocol（模型上下文协议）是由 Anthropic 推出的一种开放标准。它允许大语言模型（LLM）通过标准化的方式访问外部工具、数据和上下文，而无需为每个模型编写特定的插件。其核心优势在于：

- **解耦工具与模型**：工具运行在独立的服务器中，模型只需执行协议指令。
- **动态发现**：LLM 启动时会自动「询问」服务器有哪些可用工具（如 `list_tools`）。
- **跨平台兼容**：一套 MCP 服务可以同时给 Claude Desktop、Cursor等所有支持协议的客户端使用。

## 2. MCP 的三层架构

- **Host (宿主)**：如 `m1gan` 机器人项目，负责加载并协调 MCP 客户端。
- **Client (客户端)**：项目内部的 `ServerMCPClient`，负责与服务端通信。
- **Server (服务端)**：具体的工具提供者。
    - **Stdio 服务器**：通过本地命令行（如 `npx`）运行。
    - **HTTP/SSE 服务器**：通过 URL 远程连接（如 PageIndex Cloud）。

## 3. 配置文件指南
这是 MCP 的「指挥中心」，通常存放在 `.mcp_server_settings.json` 等文件下。

```json
{
  "mcpServers": {
    "pageindex": {
      "transport": "http",
      "url": "https://api.pageindex.ai/mcp",
      "headers": {
        "Authorization": "Bearer 你的_API_KEY"
      }
    }
  }
}
```

*注：`transport` 必须严格设置为 `http` 或 `sse` 以兼容底层库。*

## 4. PageIndex RAG 实战集成

PageIndex 是一种「无向量、基于推理」的 RAG 方案，它通过构建文档树（Tree Index）让 LLM 像人类一样翻阅文档。集成步骤如下：

1. **环境准备**：确认系统已安装 Node.js（用于运行 npx）和 Python 环境（安装 `pip install pageindex`）。
2. **文档索引 (Indexing)**：
   - **核心限制**：PageIndex 的 Cloud MCP 工具目前专注于「检索」，不支持直接通过 MCP 接口上传本地文件。
   - **解决方案**：使用 Python SDK 编写一个简单的上传脚本（如 `upload_docs.py`），通过 API Key 手动将本地文档提交至云端并生成 Tree Index。
3. **提示词增强 (Prompt Engineering)**：
   在模型系统提示词（Prompt）中加入上下文指引。例如：「你拥有 PageIndex 深度检索工具，可以查阅相关专业文档，请根据检索结果进行事实问答。」

常用工具说明：

- **`recent_documents`**：列出云端当前已加载并可供检索的文档。
- **`find_relevant_documents`**：针对用户问题进行树状搜索，返回文档结构和关键篇章。
- **`get_page_content`**：根据索引建议，精准读取特定页面的文本内容进行推理。