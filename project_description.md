# AgentNexus-J：多智能體協作系統 (A2A) 專案開發計畫書

## 1. 專案概述 (Project Overview)
**AgentNexus-J** 是一個基於 **Jude** 個人特色打造的企業級多智能體 (Multi-Agent) 協作樞紐。本系統核心理念是透過「大腦調度」與「執行沙箱」的分離，實現一個安全、高性能且具備自我演化能力的 AI 助理系統。

### 核心願景
- **意圖解耦**：Planner 負責思考，Actor 負責執行。
- **環境隔離**：所有高危動作（代碼、瀏覽器）在 Docker 沙箱中運行。
- **標準接入**：全面擁抱 MCP (Model Context Protocol) 協議與 A2A 協作模式。

---

## 2. 技術選型與選型理由 (Tech Stack & Rationale)

| 領域 | 技術選型 | 選型理由 |
| :--- | :--- | :--- |
| **後端核心** | FastAPI (Python 3.12) | 原生非同步 (Async) 支援，完美處理 LLM 長時間 I/O 等待。 |
| **包管理** | `uv` | Rust 編寫，極速解決複雜 AI 依賴衝突。 |
| **持久化** | PostgreSQL (asyncpg) | 儲存會話、記憶、任務狀態，保證資料一致性。 |
| **消息/隊列** | Redis (Redis-Stream) | 異步削峰填谷，解決 Agent 長時間任務導致的 HTTP 超時問題。 |
| **隔離沙箱** | Docker (Ubuntu 22.04) | 提供硬隔離環境，防止 RCE 攻擊，確保宿主機安全。 |
| **執行末梢** | Playwright + VNC | 讓 Agent 透過 CDP 協議接管瀏覽器，並實現畫面視覺化。 |
| **前端互動** | Next.js + Tailwind CSS | 高性能 SSR 與元件化開發，處理複雜的非同步狀態流轉。 |

---

## 3. 系統架構設計 (System Architecture)

### 3.1 核心模組拆解
1. **大腦引擎 (Core Engine)**：負責 LLM 調度、Prompt 管理、記憶裁剪與會話持久化。
2. **協作工作流 (Plan & Act Workflow)**：
   - **Planner**：分解任務目標，生成 DAG 執行計畫。
   - **Actor**：調用 MCP 工具進入沙箱執行具體指令。
   - **Critic**：審查執行結果，負責錯誤回滾與計畫重組。
3. **沙箱微服務 (Sandbox)**：獨立運行的 API 容器，封裝 Shell、文件系統與瀏覽器控制。
4. **任務調度器 (TaskRunner)**：基於 Redis-Stream 的後端 Worker，負責消費長耗時任務。

### 3.2 數據與控制流 (Case Walkthrough)
**場景案例**：「幫我下載此程序並安裝到默認目錄」
1. **API 層**：接收請求，存入 PG，生成任務 ID 寫入 Redis-Stream，立即返回前端。
2. **Planner**：消費任務，分析需要 `wget` 與 `tar` 命令，生成步驟流推送到 SSE。
3. **Actor**：自動檢查/拉起 Docker 沙箱，發送 HTTP 指令到沙箱 API。
4. **Sandbox**：在隔離容器內執行 Shell 命令，回傳 stdout 實時日誌。
5. **Output**：Planner 匯總結果，回傳最終語音回答，關閉或保留沙箱 Session。

---

## 4. 實施路線圖 (Roadmap)

### Sprint 1: 基礎設施與架構底座 (當前階段)
- [x] 環境初始化 (Docker, uv, Node)
- [x] 啟動 PostgreSQL & Redis 基礎設施
- [ ] 搭建 FastAPI DDD 目錄結構與強類型配置管理 (`pydantic-settings`)
- [ ] 實現非同步資料庫連線池與自動遷移 (SQLAlchemy + Alembic)
- [ ] 定義全局異常攔截與統一 API 回應標準

### Sprint 2: LLM 核心與異步任務調度
- [ ] 封裝 LLM Router（支援 DeepSeek/OpenAI 接口切換）
- [ ] 實現基於 Redis-Stream 的 TaskRunner 核心消費者
- [ ] 開發 SSE (Server-Sent Events) 流式數據接口

### Sprint 3: 沙箱環境與執行末梢 (核心挑戰)
- [ ] 構建 `agent-nexus-sandbox` 鏡像（內置 Chrome, Python, VNC）
- [ ] 實現主後端對 Docker 容器的動態生命週期管理 (SDK 調用)
- [ ] 打通 Playwright 對沙箱內瀏覽器的 CDP 接管邏輯

### Sprint 4: MCP 協議接入與 UI 聯調
- [ ] 封裝標準化 MCP 工具集
- [ ] Next.js 頁面開發：對話框、CoT 思考鏈展示、內嵌 noVNC 畫面

---

## 5. 工程化規範 (Engineering Standards)
- **代碼質量**：強制執行 `ruff` (Linter) 與 `mypy` (類型檢查)。
- **安全防護**：Sandbox 嚴禁直接連接宿主機資料庫；所有 API Key 使用 `SecretStr` 脫敏。
- **可擴展性**：遵守 DDD 領域驅動設計，基礎設施層與領域業務層物理隔離。
- **高併發**：全鏈路 `async/await`，不佔用任何阻塞式執行緒。

---

**Document Status**: *Draft - Phase 1*
**Owner**: *Jude (Lead Architect)*