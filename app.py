"""AgentNexus-J — Streamlit 控制台"""

import base64
import json
import re
from datetime import datetime
from pathlib import Path

import httpx
import streamlit as st
import streamlit.components.v1 as stcomp

# ── 自动主题：运行时写 config.toml，由 Streamlit 原生主题引擎渲染 ──────────────

_CONFIG_PATH = Path(".streamlit/config.toml")

_TOML = {
    "dark": """\
[theme]
base = "dark"
primaryColor = "#5B6EFF"
backgroundColor = "#0E1117"
secondaryBackgroundColor = "#1A1D27"
textColor = "#FAFAFA"

[server]
port = 8501
headless = true

[browser]
gatherUsageStats = false
""",
    "light": """\
[theme]
base = "light"
primaryColor = "#5B6EFF"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F0F2F6"
textColor = "#31333F"

[server]
port = 8501
headless = true

[browser]
gatherUsageStats = false
""",
}

# 品牌装饰条 + 亮色模式对比度修复（不依赖 base）
_BRAND_CSS = """
<style>
[data-testid="stDecoration"] {
    background-image: linear-gradient(90deg, #5B6EFF, #8B5CF6) !important;
}
</style>
"""

_LIGHT_FIX_CSS = """
<style>
/* 成功提示：深绿文字 + 薄荷底，提升对比度 */
div[data-testid="stAlert"][kind="success"],
div.stSuccess > div {
    background-color: #D1FAE5 !important;
    border-left-color: #059669 !important;
}
div[data-testid="stAlert"][kind="success"] p,
div[data-testid="stAlert"][kind="success"] span,
div.stSuccess > div p,
div.stSuccess > div span {
    color: #065F46 !important;
}
/* Caption 中 inline code */
[data-testid="stCaptionContainer"] code {
    background-color: #EFF6FF !important;
    color: #1E40AF !important;
    border-radius: 4px !important;
    padding: 1px 4px !important;
}
[data-testid="stCaptionContainer"] p {
    color: #4B5563 !important;
}
</style>
"""


def _apply_theme() -> None:
    """
    检查当前时间，将 config.toml 设置为对应主题。
    若配置与目标不符，更新文件后触发浏览器刷新（由 Streamlit 原生主题接管）。
    """
    hour = datetime.now().hour
    desired = "dark" if hour >= 18 or hour < 6 else "light"
    try:
        current = _CONFIG_PATH.read_text(encoding="utf-8")
    except OSError:
        current = ""

    if f'base = "{desired}"' not in current:
        try:
            _CONFIG_PATH.write_text(_TOML[desired], encoding="utf-8")
        except OSError:
            pass
        # 触发浏览器硬刷新，让 Streamlit 以新 config.toml 重新渲染
        stcomp.html('<script>window.parent.location.reload()</script>', height=0)
        st.stop()

    # 主题已正确，注入品牌 CSS
    st.markdown(_BRAND_CSS, unsafe_allow_html=True)
    if desired == "light":
        st.markdown(_LIGHT_FIX_CSS, unsafe_allow_html=True)


API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="AgentNexus-J",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded",
)
_apply_theme()

# ── HTTP 工具 ──────────────────────────────────────────────────────────────────

def api(method: str, path: str, silent: bool = False, **kwargs):
    try:
        resp = httpx.request(method, f"{API_BASE}{path}", timeout=120, **kwargs)
        resp.raise_for_status()
        return True if resp.status_code == 204 else resp.json()
    except httpx.HTTPStatusError as e:
        if not silent:
            try:
                detail = e.response.json().get("detail", e.response.text)
            except Exception:
                detail = e.response.text
            st.error(f"请求失败 ({e.response.status_code})：{detail}")
    except httpx.ConnectError:
        if not silent:
            st.error("无法连接后台服务，请确认 FastAPI 已启动（端口 8000）。")
    return None


def _iter_raw_chat_events(
    session_id: str,
    message: str,
    attachments: list[dict] | None = None,
    is_retry: bool = False,
    thinking: bool = False,
    search: bool = False,
):
    """底层生成器：逐个 yield 原始 SSE payload dict，供有 thinking 的手动渲染循环使用。"""
    with httpx.stream(
        "POST",
        f"{API_BASE}/chat/stream",
        json={
            "session_id": session_id,
            "message": message,
            "attachments": attachments or [],
            "is_retry": is_retry,
            "thinking": thinking,
            "search": search,
        },
        timeout=180,
    ) as resp:
        if resp.status_code != 200:
            yield {"type": "error", "message": f"请求失败 ({resp.status_code})"}
            return
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                return
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


def stream_chat(
    session_id: str,
    message: str,
    attachments: list[dict] | None = None,
    is_retry: bool = False,
    search: bool = False,
):
    """同步生成器，供 st.write_stream() 消费（普通会话）。"""
    with httpx.stream(
        "POST",
        f"{API_BASE}/chat/stream",
        json={
            "session_id": session_id,
            "message": message,
            "attachments": attachments or [],
            "is_retry": is_retry,
            "search": search,
        },
        timeout=180,
    ) as resp:
        if resp.status_code != 200:
            yield f"❌ 请求失败 ({resp.status_code})"
            return
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                return
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ptype = payload.get("type")
            if ptype == "text":
                yield payload["content"]
            elif ptype == "tool_start":
                tool_info = payload.get("tool_info", [])
                blocks: list[str] = []
                for ti in tool_info:
                    name = ti.get("name", "")
                    inp = ti.get("input", {})
                    if name == "execute_terminal":
                        cmd = inp.get("command", "")
                        wd = inp.get("working_dir", "")
                        header = f"🖥 **执行命令**" + (f"  `{wd}`" if wd else "")
                        blocks.append(f"{header}\n```shell\n{cmd}\n```")
                    elif name.startswith("mcp__"):
                        # mcp__{server_name}__{tool_name}
                        parts = name.split("__", 2)
                        srv = parts[1] if len(parts) > 1 else ""
                        tool = parts[2] if len(parts) > 2 else name
                        args_str = ", ".join(f"`{k}`={repr(v)}" for k, v in inp.items()) if inp else "无参数"
                        blocks.append(f"🔌 **MCP [{srv}]** · `{tool}`\n\n> {args_str}")
                    else:
                        label = {
                            "get_system_time": "🕐 获取系统时间",
                        }.get(name, f"🔧 {name}")
                        blocks.append(label)
                yield "\n\n" + "\n\n".join(blocks) + "\n\n"
            elif ptype == "tool_end":
                results = payload.get("results", [])
                if results:
                    combined = "\n---\n".join(str(r) for r in results)
                    yield f"```\n{combined}\n```\n\n"
            elif ptype == "rag_context":
                chunks = payload.get("chunks", [])
                if chunks:
                    lines = [f"📚 **已从知识库检索到 {len(chunks)} 条相关内容**\n"]
                    for c in chunks:
                        snippet = c["content"][:150].replace("\n", " ")
                        lines.append(f"> **{c['filename']}** · 相关度 {c['score']:.2f}\n> {snippet}…\n")
                    yield "\n".join(lines) + "\n---\n\n"
            elif ptype == "compression":
                st.session_state["_compression_happened"] = True
            elif ptype == "error":
                raw_err = payload.get("message", "未知错误")
                _vision_keywords = ("vision", "image", "BalanceError", "multimodal",
                                    "no suitable services", "不支持图片", "visual")
                if any(k.lower() in raw_err.lower() for k in _vision_keywords):
                    yield (
                        f"\n\n❌ 模型不支持图片（视觉功能）。\n\n"
                        f"> 请切换到视觉模型，例如：Claude 3+、GPT-4o、qwen-vl-max 等。\n\n"
                        f"原始错误：`{raw_err}`"
                    )
                else:
                    yield f"\n\n❌ {raw_err}"


def _iter_collab_events(session_id: str, message: str):
    """同步生成器：逐个 yield 协作 SSE 事件 dict，供 UI 实时消费。"""
    with httpx.stream(
        "POST",
        f"{API_BASE}/chat/stream",
        json={"session_id": session_id, "message": message},
        timeout=300,
    ) as resp:
        if resp.status_code != 200:
            yield {"type": "error", "message": f"请求失败 ({resp.status_code})"}
            return
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                return
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue


_ROLE_ICON = {
    "proposer":    "🎯",
    "critic":      "🔍",
    "creative":    "🌈",
    "validator":   "📊",
    "synthesizer": "🔀",
    "master":      "👑",
    "reviewer":    "⚖️",
}


def _render_round_table_process(process_events: list[dict]) -> None:
    """圆桌模式：在 expander 内渲染各轮次各角色的观点。"""
    round_entries: dict[int, list[dict]] = {}
    synthesis_info: dict = {}

    for ev in process_events:
        t = ev.get("type", "")
        if t == "collab_model_result":
            rnd = ev.get("round", 1)
            round_entries.setdefault(rnd, []).append(ev)
        elif t == "collab_synthesis_start":
            synthesis_info = ev
        elif t == "error":
            st.error(ev.get("message", "未知错误"))

    if not round_entries:
        st.caption("暂无过程数据。")
        return

    tab_labels = [f"Round {rnd}" for rnd in sorted(round_entries.keys())]
    if len(tab_labels) == 1:
        for entry in round_entries.get(1, []):
            icon = _ROLE_ICON.get(entry.get("role", ""), "🤖")
            label = entry.get("role_label", entry.get("role", ""))
            model = entry.get("model_name", "")
            st.markdown(f"**{icon} {label}** · `{model}`")
            st.markdown(entry.get("content", ""))
            st.divider()
    else:
        tabs = st.tabs(tab_labels)
        for tab, rnd in zip(tabs, sorted(round_entries.keys())):
            with tab:
                for entry in round_entries[rnd]:
                    icon = _ROLE_ICON.get(entry.get("role", ""), "🤖")
                    label = entry.get("role_label", entry.get("role", ""))
                    model = entry.get("model_name", "")
                    st.markdown(f"**{icon} {label}** · `{model}`")
                    st.markdown(entry.get("content", ""))
                    st.divider()

    if synthesis_info:
        st.success(f"✅ 综合者：**{synthesis_info.get('model_name', '')}**")


def _render_master_slave_review(process_events: list[dict]) -> None:
    """
    主从模式：整体放在可折叠 expander 内，内部紧凑排列。
    默认折叠，让最终答案保持首要位置。
    """
    master_parts = [
        e.get("content", "")
        for e in process_events
        if e.get("type") == "collab_model_text" and e.get("role") == "master"
    ]
    master_text     = "".join(master_parts)
    reviewer_events = [e for e in process_events if e.get("type") == "collab_reviewer_result"]
    synthesis_info  = next((e for e in process_events if e.get("type") == "collab_synthesis_start"), {})

    if not reviewer_events:
        return

    best_score = synthesis_info.get("score", 0)
    best_model = synthesis_info.get("model_name", "")
    n          = len(reviewer_events)

    with st.expander(f"📊 协作评审过程（{n} 位评委）", expanded=False):
        # 主模型原始答案（折叠）
        if master_text:
            with st.expander("👑 主模型原始答案", expanded=False):
                st.markdown(master_text)

        # 每位评委：紧凑卡片
        for res in reviewer_events:
            model_name = res.get("model_name", "")
            scores     = res.get("scores", {})
            total      = res.get("weighted_total", 0)
            critique   = res.get("critique", "")
            improved   = res.get("improved_answer", "")
            is_best    = bool(model_name == best_model and best_score)

            with st.container(border=True):
                # 名称 + 综合分（单行）
                badge = " 🏆" if is_best else ""
                c_name, c_total = st.columns([4, 1])
                c_name.markdown(f"⚖️ **{model_name}**{badge}")
                c_total.markdown(
                    f"<div style='text-align:right;font-size:1.1rem;font-weight:700'>"
                    f"{total} / 10</div>",
                    unsafe_allow_html=True,
                )

                # 四维分项（单行紧凑，用 caption）
                if scores:
                    acc  = scores.get("accuracy",     "—")
                    comp = scores.get("completeness",  "—")
                    clar = scores.get("clarity",       "—")
                    reas = scores.get("reasoning",     "—")
                    st.caption(
                        f"准确 **{acc}** · 完整 **{comp}** · 清晰 **{clar}** · 逻辑 **{reas}**"
                    )

                # 点评（小字）
                if critique:
                    st.caption(f"💬 {critique}")

                # 改进版本（折叠，最优默认展开）
                if improved and improved != master_text:
                    with st.expander("📝 改进版本", expanded=is_best):
                        st.markdown(improved)

        # 底部结论
        if best_model and best_score:
            st.success(f"✅ 采用 **{best_model}** 改进版（综合最高 {best_score} / 10）")


def _render_collab_process(process_events: list[dict]) -> None:
    """兼容入口：根据事件类型自动分派到对应渲染函数（供 expander 内调用）。"""
    has_reviewer = any(e.get("type") == "collab_reviewer_result" for e in process_events)
    if has_reviewer:
        _render_master_slave_review(process_events)
    else:
        _render_round_table_process(process_events)


# ── 多媒体下载辅助 ────────────────────────────────────────────────────────────

_MEDIA_RE = re.compile(r'!\[([^\]]*)\]\(data:([^;]+);base64,([A-Za-z0-9+/=\n]+)\)')

def _extract_media(content: str) -> list[tuple[str, str, bytes]]:
    """从消息内容中提取所有 data URI 媒体，返回 [(alt, mime, bytes), ...]。"""
    results = []
    for m in _MEDIA_RE.finditer(content):
        alt, mime, b64 = m.group(1), m.group(2), m.group(3).replace("\n", "")
        try:
            results.append((alt or "file", mime, base64.b64decode(b64)))
        except Exception:
            pass
    return results

def _media_download_buttons(content: str, msg_idx: int) -> None:
    """在消息下方渲染所有可下载媒体的下载按钮。"""
    media_list = _extract_media(content)
    if not media_list:
        return
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    cols = st.columns(len(media_list))
    for col_idx, (alt, mime, data) in enumerate(media_list):
        # 推断扩展名
        ext = mime.split("/")[-1].split("+")[0]   # "image/png" → "png"
        ext_map = {"jpeg": "jpg", "svg+xml": "svg", "plain": "txt"}
        ext = ext_map.get(ext, ext)
        filename = f"generated_{ts}_{col_idx}.{ext}"
        # 根据类型选择图标
        icon = "🖼️" if mime.startswith("image/") else ("📄" if "pdf" in mime else "💾")
        with cols[col_idx]:
            st.download_button(
                label=f"{icon} 下载{alt}",
                data=data,
                file_name=filename,
                mime=mime,
                key=f"dl_{msg_idx}_{col_idx}",
                use_container_width=True,
            )


# ── Session state 初始化 ──────────────────────────────────────────────────────

for _k, _v in [
    ("active_session_id", None),
    ("chat_history", []),
    ("editing_config_id", None),
    ("confirm_delete_config_id", None),
    ("renaming_session_id", None),
    ("selected_sp_id", None),         # 当前侧边栏选中的 system prompt id
    ("editing_sp_id", None),          # 正在编辑的 system prompt id
    ("editing_tool_id", None),        # 正在编辑的 HTTP 工具 id
    ("collab_show_form", False),           # 是否展开协作会话创建表单
    ("active_session_collab_mode", None),  # 当前活跃会话的协作模式
    ("last_collab_process", []),           # 最近一次协作过程事件，用于持久显示
    ("_upload_generation", 0),             # 递增以重置文件上传器
    ("_last_prompt", ""),                  # 最近一次用户消息（用于重试）
    ("_last_attachments", []),             # 最近一次附件（用于重试）
    ("_retry_pending", False),             # 是否触发重试
    ("_is_generating", False),            # 是否正在生成（用于锁定 UI）
    ("_collab_edit_open", False),         # 是否展开协作配置编辑面板
    ("_pending_prompt", None),
    ("_pending_attachments", []),
    ("_pending_is_retry", False),
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# fastembed 支持的嵌入模型列表（key=显示名, value=model_id）
_EMB_OPTIONS: dict[str, str | None] = {
    "🏠 默认：bge-small-zh-v1.5（512 维 · 中文 · 90 MB）":     None,
    "BAAI/bge-base-zh-v1.5（768 维 · 中文 · 210 MB）":         "BAAI/bge-base-zh-v1.5",
    "jinaai/jina-embeddings-v2-base-zh（768 维 · 中英 · 640 MB）": "jinaai/jina-embeddings-v2-base-zh",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2（384 维 · 50+ 语言 · 220 MB）":
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    "nomic-ai/nomic-embed-text-v1.5-Q（768 维 · 多语言量化 · 130 MB）":
        "nomic-ai/nomic-embed-text-v1.5-Q",
    "BAAI/bge-small-en-v1.5（384 维 · 英文 · 67 MB）":          "BAAI/bge-small-en-v1.5",
    "BAAI/bge-base-en-v1.5（768 维 · 英文 · 210 MB）":          "BAAI/bge-base-en-v1.5",
    "BAAI/bge-m3（1024 维 · 多语言 · 570 MB）":                 "BAAI/bge-m3",
}
_EMB_LABELS = list(_EMB_OPTIONS.keys())

def _emb_label(model_id: str | None) -> str:
    """根据 model_id 找到对应的显示名，找不到则返回第一项（默认）。"""
    if not model_id:
        return _EMB_LABELS[0]
    for label, mid in _EMB_OPTIONS.items():
        if mid == model_id:
            return label
    return _EMB_LABELS[0]

# ── 生成锁：streaming 期间冻结侧边栏所有交互 ──────────────────────────────────

_is_generating = st.session_state.get("_is_generating", False)
if _is_generating:
    st.markdown(
        "<style>section[data-testid='stSidebar']{pointer-events:none;opacity:.55}"
        ".stChatInput textarea{pointer-events:none}</style>",
        unsafe_allow_html=True,
    )

# ── 侧边栏 ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("💠 AgentNexus-J")
    st.caption("企业级多智能体协作控制台")

    configs: list[dict] = api("GET", "/llm-configs/", silent=True) or []
    active_config = next((c for c in configs if c["is_active"]), None)
    _mcp_servers: list[dict] = api("GET", "/mcp-servers/", silent=True) or []
    search_configs: list[dict] = api("GET", "/search-config/", silent=True) or []
    _active_search = next((s for s in search_configs if s["is_active"]), None)

    tab_chat, tab_model, tab_tools, tab_kb = st.tabs(["💬 会话", "⚙️ 模型", "🛠 工具", "📚 知识库"])

    # ── Tab: 模型 + System Prompt ────────────────────────────────────────────
    with tab_model:
        st.subheader("🔧 模型配置")

        with st.expander("＋ 接入新模型", expanded=not bool(configs)):
            with st.form("llm_config_form", clear_on_submit=True):
                n_name = st.text_input("配置名称 *", placeholder="例：DeepSeek 生产")
                n_model = st.text_input("模型名称 *", placeholder="例：deepseek-chat")
                n_key = st.text_input("API Key *", type="password", placeholder="sk-...")
                n_url = st.text_input("API URL（可选）", placeholder="留空使用 Anthropic 官方地址")
                n_emb_label = st.selectbox(
                    "嵌入模型（用于 RAG 知识库）",
                    options=_EMB_LABELS,
                    index=0,
                    help="首次选择非默认模型时，后端会从 HuggingFace 下载 ONNX 文件并缓存本地，之后离线可用。",
                )
                n_emb_model = _EMB_OPTIONS[n_emb_label]
                n_thinking_budget = st.slider(
                    "思考 Token 预算（Anthropic 扩展思考专用）",
                    min_value=1024, max_value=32000, value=8000, step=1024,
                    help="仅对 Anthropic Claude 系列的深度思考生效；DeepSeek 等模型由自身控制思考深度。",
                )
                submitted = st.form_submit_button("💾 保存并激活", use_container_width=True, type="primary")
            if submitted:
                if not n_name or not n_model or not n_key:
                    st.error("配置名称、模型名称、API Key 为必填项。")
                else:
                    result = api("POST", "/llm-configs/", json={
                        "display_name": n_name, "model": n_model,
                        "api_key": n_key, "base_url": n_url or None,
                        "embedding_model": n_emb_model,
                        "thinking_budget": n_thinking_budget,
                    })
                    if result:
                        st.success(f"✅ 已接入并激活：{result['display_name']}")
                        st.rerun()

        if configs:
            options_map = {
                f"{'✅ ' if c['is_active'] else '　 '}{c['display_name']}  ·  {c['model']}": c
                for c in configs
            }
            default_idx = next((i for i, c in enumerate(configs) if c["is_active"]), 0)
            selected_label = st.selectbox(
                "选择模型配置",
                options=list(options_map.keys()),
                index=default_idx,
                label_visibility="collapsed",
            )
            selected = options_map[selected_label]

            col_act, col_edit, col_del = st.columns([3, 2, 1])
            if not selected["is_active"]:
                if col_act.button("⚡ 激活", use_container_width=True, type="primary"):
                    api("POST", f"/llm-configs/{selected['id']}/activate")
                    st.session_state.confirm_delete_config_id = None
                    st.rerun()
            else:
                col_act.caption("✅ 已激活")

            if col_edit.button("✏️ 编辑", use_container_width=True):
                st.session_state.editing_config_id = (
                    None if st.session_state.editing_config_id == selected["id"]
                    else selected["id"]
                )
                st.session_state.confirm_delete_config_id = None
                st.rerun()

            _is_del_confirm = st.session_state.confirm_delete_config_id == selected["id"]
            if col_del.button(
                "🗑",
                use_container_width=True,
                help="删除此模型配置" if not selected["is_active"] else "请先激活其他模型再删除此配置",
                disabled=selected["is_active"],
            ):
                st.session_state.confirm_delete_config_id = selected["id"]
                st.rerun()

            if _is_del_confirm:
                st.warning(f"确认删除「{selected['display_name']}」？此操作不可撤销。")
                _dc1, _dc2 = st.columns(2)
                if _dc1.button("确认删除", type="primary", use_container_width=True):
                    api("DELETE", f"/llm-configs/{selected['id']}")
                    st.session_state.confirm_delete_config_id = None
                    st.session_state.editing_config_id = None
                    st.rerun()
                if _dc2.button("取消", use_container_width=True):
                    st.session_state.confirm_delete_config_id = None
                    st.rerun()

            if st.session_state.editing_config_id == selected["id"]:
                with st.form(f"edit_config_{selected['id']}"):
                    st.caption(f"编辑：{selected['display_name']}")
                    e_name = st.text_input("配置名称", value=selected["display_name"])
                    e_model = st.text_input("模型名称", value=selected["model"])
                    e_key = st.text_input("API Key（留空保持不变）", type="password", placeholder="留空则不修改")
                    e_url = st.text_input(
                        "API URL（留空清除）",
                        value=selected.get("base_url") or "",
                        placeholder="留空则使用官方地址",
                    )
                    _cur_emb_label = _emb_label(selected.get("embedding_model"))
                    e_emb_label = st.selectbox(
                        "嵌入模型",
                        options=_EMB_LABELS,
                        index=_EMB_LABELS.index(_cur_emb_label),
                        help="首次选择非默认模型时，后端从 HuggingFace 下载 ONNX 文件并缓存本地。",
                    )
                    e_emb_model = _EMB_OPTIONS[e_emb_label]
                    e_thinking_budget = st.slider(
                        "思考 Token 预算（Anthropic 扩展思考专用）",
                        min_value=1024, max_value=32000,
                        value=selected.get("thinking_budget", 8000), step=1024,
                    )
                    s_col, c_col = st.columns(2)
                    save = s_col.form_submit_button("💾 保存", use_container_width=True, type="primary")
                    cancel = c_col.form_submit_button("取消", use_container_width=True)

                if save:
                    payload: dict = {}
                    if e_name.strip():
                        payload["display_name"] = e_name
                    if e_model.strip():
                        payload["model"] = e_model
                    if e_key.strip():
                        payload["api_key"] = e_key
                    payload["base_url"] = e_url.strip() or ""
                    payload["embedding_model"] = e_emb_model or ""
                    payload["thinking_budget"] = e_thinking_budget
                    result = api("PATCH", f"/llm-configs/{selected['id']}", json=payload)
                    if result:
                        st.session_state.editing_config_id = None
                        st.rerun()
                if cancel:
                    st.session_state.editing_config_id = None
                    st.rerun()

            _cap_parts = [f"Key: `{selected['api_key_masked']}`"]
            if selected.get("base_url"):
                _cap_parts.append(f"`{selected['base_url']}`")
            if selected.get("embedding_model"):
                _cap_parts.append(f"Emb: `{selected['embedding_model']}`")
            st.caption("  ·  ".join(_cap_parts))

        st.divider()
        st.subheader("📋 System Prompt 库")

        sp_list: list[dict] = api("GET", "/system-prompts/", silent=True) or []

        with st.expander("＋ 新建提示词"):
            with st.form("new_sp_form", clear_on_submit=True):
                sp_new_name = st.text_input("名称 *", placeholder="例：客服助手")
                sp_new_content = st.text_area("内容 *", height=100,
                                              placeholder="在此输入 System Prompt 内容...")
                if st.form_submit_button("💾 保存", use_container_width=True, type="primary"):
                    if sp_new_name.strip() and sp_new_content.strip():
                        r = api("POST", "/system-prompts/",
                                json={"name": sp_new_name.strip(), "content": sp_new_content.strip()})
                        if r:
                            st.session_state.selected_sp_id = r["id"]
                            st.rerun()
                    else:
                        st.warning("名称和内容均为必填。")

        if sp_list:
            sp_options = {"（不使用）": None} | {sp["name"]: sp["id"] for sp in sp_list}
            current_sp_name = next(
                (sp["name"] for sp in sp_list if sp["id"] == st.session_state.selected_sp_id),
                "（不使用）",
            )
            selected_sp_name = st.selectbox(
                "选择提示词",
                options=list(sp_options.keys()),
                index=list(sp_options.keys()).index(current_sp_name),
                label_visibility="collapsed",
            )
            st.session_state.selected_sp_id = sp_options[selected_sp_name]

            selected_sp = next((sp for sp in sp_list if sp["id"] == st.session_state.selected_sp_id), None)

            if selected_sp:
                st.caption(selected_sp["content"][:120] + ("…" if len(selected_sp["content"]) > 120 else ""))

                col_sp_edit, col_sp_del = st.columns(2)
                if col_sp_edit.button("✏️ 编辑", key="sp_edit_btn", use_container_width=True):
                    st.session_state.editing_sp_id = (
                        None if st.session_state.editing_sp_id == selected_sp["id"]
                        else selected_sp["id"]
                    )
                    st.rerun()
                if col_sp_del.button("🗑 删除", key="sp_del_btn", use_container_width=True):
                    api("DELETE", f"/system-prompts/{selected_sp['id']}")
                    st.session_state.selected_sp_id = None
                    st.session_state.editing_sp_id = None
                    st.rerun()

                if st.session_state.editing_sp_id == selected_sp["id"]:
                    with st.form(f"edit_sp_{selected_sp['id']}"):
                        e_sp_name = st.text_input("名称", value=selected_sp["name"])
                        e_sp_content = st.text_area("内容", value=selected_sp["content"], height=100)
                        ec1, ec2 = st.columns(2)
                        if ec1.form_submit_button("💾 保存", use_container_width=True, type="primary"):
                            patch: dict = {}
                            if e_sp_name.strip():
                                patch["name"] = e_sp_name.strip()
                            if e_sp_content.strip():
                                patch["content"] = e_sp_content.strip()
                            if patch:
                                api("PATCH", f"/system-prompts/{selected_sp['id']}", json=patch)
                            st.session_state.editing_sp_id = None
                            st.rerun()
                        if ec2.form_submit_button("取消", use_container_width=True):
                            st.session_state.editing_sp_id = None
                            st.rerun()

            if st.session_state.active_session_id:
                if st.button("✅ 应用到当前会话", use_container_width=True, type="primary"):
                    sp_id = st.session_state.selected_sp_id
                    if sp_id:
                        api("PATCH", f"/sessions/{st.session_state.active_session_id}",
                            json={"system_prompt_id": sp_id})
                    else:
                        api("PATCH", f"/sessions/{st.session_state.active_session_id}",
                            json={"clear_system_prompt": True})
                    st.rerun()
        else:
            st.caption("暂无提示词，点击上方新建。")

    # ── Tab: 工具管理 ────────────────────────────────────────────────────────
    with tab_tools:
        st.subheader("🛠 工具管理")

        all_tools: list[dict] = api("GET", "/tools/", silent=True) or []

        with st.expander("＋ 接入新工具"):
            with st.form("new_tool_form", clear_on_submit=True):
                t_name = st.text_input("工具标识符 *", placeholder="snake_case，如 search_web")
                t_display = st.text_input("显示名称 *", placeholder="如 Web 搜索")
                t_desc = st.text_area("功能描述 *", height=70,
                                      placeholder="向大模型说明这个工具的用途和触发条件")
                t_url = st.text_input("接口地址 *", placeholder="https://your-api.com/endpoint")
                t_method = st.selectbox("请求方式", ["POST", "GET"])
                t_headers = st.text_area("请求头（JSON，可选）", height=50,
                                         placeholder='{"Authorization": "Bearer token"}')
                t_schema = st.text_area(
                    "参数定义（JSON Schema）",
                    height=100,
                    value='{\n  "type": "object",\n  "properties": {\n    "query": {"type": "string", "description": "查询内容"}\n  },\n  "required": ["query"]\n}',
                )
                if st.form_submit_button("💾 保存工具", use_container_width=True, type="primary"):
                    errors = []
                    if not t_name.strip():
                        errors.append("工具标识符不能为空")
                    if not t_display.strip():
                        errors.append("显示名称不能为空")
                    if not t_desc.strip():
                        errors.append("功能描述不能为空")
                    if not t_url.strip():
                        errors.append("接口地址不能为空")
                    headers_dict = None
                    if t_headers.strip():
                        try:
                            headers_dict = json.loads(t_headers)
                        except json.JSONDecodeError:
                            errors.append("请求头 JSON 格式错误")
                    schema_dict = {"type": "object", "properties": {}}
                    if t_schema.strip():
                        try:
                            schema_dict = json.loads(t_schema)
                        except json.JSONDecodeError:
                            errors.append("参数定义 JSON 格式错误")
                    if errors:
                        for e in errors:
                            st.error(e)
                    else:
                        r = api("POST", "/tools/", json={
                            "name": t_name.strip(),
                            "display_name": t_display.strip(),
                            "description": t_desc.strip(),
                            "http_url": t_url.strip(),
                            "http_method": t_method,
                            "http_headers": headers_dict,
                            "parameters_schema": schema_dict,
                        })
                        if r:
                            st.success(f"✅ 工具 '{t_display.strip()}' 已接入")
                            st.rerun()

        if all_tools:
            for t in all_tools:
                is_builtin = t["tool_type"] == "builtin"
                badge = "🔵 内置" if is_builtin else "🟠 HTTP"
                col_badge, col_name, col_toggle, *col_rest = st.columns(
                    [1.2, 4, 1.2] + ([1, 1] if not is_builtin else [])
                )
                col_badge.caption(badge)
                col_name.markdown(f"**{t['display_name']}**  \n`{t['name']}`")
                active = col_toggle.toggle(
                    "启用",
                    value=t["is_active"],
                    key=f"tool_toggle_{t['id']}",
                    label_visibility="collapsed",
                )
                if active != t["is_active"]:
                    api("PATCH", f"/tools/{t['id']}/toggle")
                    st.rerun()
                if not is_builtin and col_rest:
                    col_edit, col_del = col_rest
                    if col_edit.button("✏️", key=f"te_{t['id']}", help="编辑"):
                        st.session_state.editing_tool_id = (
                            None if st.session_state.get("editing_tool_id") == t["id"] else t["id"]
                        )
                        st.rerun()
                    if col_del.button("🗑", key=f"td_{t['id']}", help="删除"):
                        api("DELETE", f"/tools/{t['id']}")
                        st.rerun()
                if st.session_state.get("editing_tool_id") == t["id"]:
                    with st.form(f"edit_tool_{t['id']}"):
                        et_display = st.text_input("显示名称", value=t["display_name"])
                        et_desc = st.text_area("描述", value=t["description"], height=70)
                        et_url = st.text_input("接口地址", value=t.get("http_url") or "")
                        et_method = st.selectbox("请求方式", ["POST", "GET"],
                                                 index=0 if t.get("http_method", "POST") == "POST" else 1)
                        et_schema = st.text_area(
                            "参数定义（JSON Schema）",
                            value=json.dumps(t.get("parameters_schema") or {}, ensure_ascii=False, indent=2),
                            height=80,
                        )
                        ec1, ec2 = st.columns(2)
                        if ec1.form_submit_button("💾 保存", use_container_width=True, type="primary"):
                            patch: dict = {
                                "display_name": et_display.strip() or None,
                                "description": et_desc.strip() or None,
                                "http_url": et_url.strip() or None,
                                "http_method": et_method,
                            }
                            try:
                                patch["parameters_schema"] = json.loads(et_schema)
                            except json.JSONDecodeError:
                                st.error("参数定义 JSON 格式错误")
                                st.stop()
                            patch = {k: v for k, v in patch.items() if v is not None}
                            api("PATCH", f"/tools/{t['id']}", json=patch)
                            st.session_state.editing_tool_id = None
                            st.rerun()
                        if ec2.form_submit_button("取消", use_container_width=True):
                            st.session_state.editing_tool_id = None
                            st.rerun()
        else:
            st.caption("暂无工具，重启后端后内置工具将自动同步。")

        # ── 搜索引擎配置区块 ──────────────────────────────────────────────────
        st.divider()
        st.subheader("🔍 网络搜索")
        st.caption("配置搜索引擎后，在会话输入框旁可按消息开关搜索。DuckDuckGo 无需 API Key，开箱即用。")

        _provider_labels = {"ddgs": "DuckDuckGo（免费，无需 Key）", "tavily": "Tavily", "serper": "Serper.dev"}

        with st.expander("＋ 添加搜索配置"):
            with st.form("new_search_form", clear_on_submit=True):
                sc_provider = st.selectbox(
                    "搜索提供商 *",
                    options=["ddgs", "tavily", "serper"],
                    format_func=lambda x: _provider_labels.get(x, x),
                )
                sc_key = st.text_input(
                    "API Key",
                    type="password",
                    placeholder="DuckDuckGo 不需要；Tavily/Serper 必填",
                )
                sc_max = st.slider("最多返回结果数", min_value=1, max_value=10, value=5)
                if st.form_submit_button("💾 保存", use_container_width=True, type="primary"):
                    if sc_provider in ("tavily", "serper") and not sc_key.strip():
                        st.error(f"{sc_provider} 需要配置 API Key")
                    else:
                        r = api("POST", "/search-config/", json={
                            "provider": sc_provider,
                            "api_key": sc_key.strip() or None,
                            "max_results": sc_max,
                        })
                        if r:
                            st.success(f"✅ 搜索配置已保存：{_provider_labels.get(sc_provider, sc_provider)}")
                            st.rerun()

        if search_configs:
            # 顶部选择器：直接决定使用哪个引擎，无需手动激活
            _sc_options = {sc["id"]: _provider_labels.get(sc["provider"], sc["provider"]) for sc in search_configs}
            _sc_active_id = _active_search["id"] if _active_search else None
            _sc_sel_label = st.selectbox(
                "当前使用的搜索引擎",
                options=list(_sc_options.keys()),
                index=list(_sc_options.keys()).index(_sc_active_id) if _sc_active_id in _sc_options else 0,
                format_func=lambda x: _sc_options[x],
                key="search_engine_select",
            )
            if _sc_sel_label != _sc_active_id:
                api("POST", f"/search-config/{_sc_sel_label}/activate")
                st.rerun()

            st.caption(f"最多返回 {next(s['max_results'] for s in search_configs if s['id'] == _sc_sel_label)} 条结果")

            for sc in search_configs:
                _sc_label = _provider_labels.get(sc["provider"], sc["provider"])
                sc_col_info, sc_col_del = st.columns([6, 1])
                _key_info = f"`Key: {sc['api_key_masked']}`" if sc["api_key_masked"] else "`无需 Key`"
                sc_col_info.caption(f"**{_sc_label}** · {_key_info} · 最多 {sc['max_results']} 条")
                if sc_col_del.button("🗑", key=f"sc_del_{sc['id']}", help="删除",
                                     disabled=(sc["id"] == _sc_sel_label and len(search_configs) == 1)):
                    api("DELETE", f"/search-config/{sc['id']}")
                    st.rerun()
        else:
            st.caption("暂未配置搜索引擎。DuckDuckGo 无需任何 Key，可直接添加即用。")

        # ── MCP Agent 区块 ────────────────────────────────────────────────────
        st.divider()
        st.subheader("🔌 MCP Agent")

        with st.expander("＋ 接入 MCP Server"):
            with st.form("new_mcp_form", clear_on_submit=True):
                m_name = st.text_input(
                    "名称 *（小写字母+下划线，作工具前缀）",
                    placeholder="如 rag_agent",
                )
                m_display = st.text_input("显示名称 *", placeholder="如 合同审查助手")
                m_desc = st.text_area("描述", height=60,
                                      placeholder="告知 LLM 该 Agent 的用途与触发场景")
                m_url = st.text_input(
                    "URL *",
                    placeholder="http://your-server.com/sse",
                )
                m_auth = st.text_input("认证头（可选）", placeholder="Bearer sk-xxx",
                                       type="password")
                m_mode = st.selectbox("接入模式", [
                    "tool_provider（仅提供工具）",
                    "chat_agent（仅对话 Agent）",
                    "both（工具 + 对话 Agent）",
                ])
                m_mode_val = m_mode.split("（")[0]
                if st.form_submit_button("测试并注册", use_container_width=True, type="primary"):
                    errs = []
                    if not m_name.strip():
                        errs.append("名称不能为空")
                    if not m_display.strip():
                        errs.append("显示名称不能为空")
                    if not m_url.strip():
                        errs.append("URL 不能为空")
                    if errs:
                        for e in errs:
                            st.error(e)
                    else:
                        r = api("POST", "/mcp-servers/", json={
                            "name": m_name.strip(),
                            "display_name": m_display.strip(),
                            "description": m_desc.strip(),
                            "url": m_url.strip(),
                            "auth_header": m_auth.strip() or None,
                            "mode": m_mode_val,
                        })
                        if r:
                            st.success(f"✅ {m_display.strip()} 已注册，正在建立连接...")
                            st.rerun()

        _STATUS_ICON = {
            "connected":    "🟢",
            "connecting":   "🟡",
            "reconnecting": "🟡",
            "disconnected": "🔴",
            "disabled":     "⚫",
            "error":        "🔴",
        }
        _STATUS_TEXT = {
            "connected":    "已连接",
            "connecting":   "连接中…",
            "reconnecting": "重连中…",
            "disconnected": "已断开",
            "disabled":     "已禁用",
            "error":        "连接错误",
        }
        _MODE_LABEL = {
            "tool_provider": "工具",
            "chat_agent":    "Agent",
            "both":          "工具+Agent",
        }

        if _mcp_servers:
            for _ms in _mcp_servers:
                _icon        = _STATUS_ICON.get(_ms.get("status", ""), "⚫")
                _status_text = _STATUS_TEXT.get(_ms.get("status", ""), "未知")
                _tools_count = len(_ms.get("discovered_tools") or [])
                _mode_label  = _MODE_LABEL.get(_ms.get("mode", ""), _ms.get("mode", ""))

                with st.container(border=True):
                    # ── 主信息行 ──────────────────────────────────────────────
                    _info_col, _btn_col = st.columns([4, 3])
                    with _info_col:
                        st.markdown(f"{_icon} **{_ms['display_name']}**")
                        _meta = f"`{_ms['name']}` · {_mode_label}"
                        if _tools_count:
                            _meta += f" · {_tools_count} 🔧"
                        st.caption(f"{_status_text}　{_meta}")

                    # ── 操作按钮（全 emoji，不撑宽） ──────────────────────────
                    with _btn_col:
                        _b1, _b2, _b3 = st.columns(3)
                        if _b1.button("🔄", key=f"mcp_ref_{_ms['id']}",
                                      help="刷新工具列表", use_container_width=True):
                            _ref = api("POST", f"/mcp-servers/{_ms['id']}/refresh", silent=False)
                            if _ref:
                                st.rerun()
                        _tog      = "⏸" if _ms["is_active"] else "▶"
                        _tog_help = "禁用" if _ms["is_active"] else "启用"
                        if _b2.button(_tog, key=f"mcp_act_{_ms['id']}",
                                      help=_tog_help, use_container_width=True):
                            api("POST", f"/mcp-servers/{_ms['id']}/activate")
                            st.rerun()
                        if _b3.button("🗑", key=f"mcp_del_{_ms['id']}",
                                      help="删除", use_container_width=True):
                            api("DELETE", f"/mcp-servers/{_ms['id']}")
                            st.rerun()

                    # ── 工具列表（折叠） ──────────────────────────────────────
                    if _tools_count:
                        with st.expander(f"查看 {_tools_count} 个工具"):
                            for _t in (_ms.get("discovered_tools") or []):
                                _desc = _t.get("description", "")
                                _desc_short = _desc[:50] + "…" if len(_desc) > 50 else _desc
                                st.caption(f"🔧 `{_t['name']}`　{_desc_short}")
        else:
            st.caption("暂无 MCP Server，点击上方注册。")

    # ── Tab: 知识库 ──────────────────────────────────────────────────────────
    with tab_kb:
        st.subheader("📚 知识库")

        _ext_emb = active_config.get("embedding_model") if active_config else None
        if _ext_emb:
            st.caption(f"🔌 外部嵌入：`{_ext_emb}`")
        else:
            st.caption("🏠 内置本地模型：`bge-small-zh-v1.5`（中文优化，512 维，无需 API）")

        with st.expander("＋ 上传文档"):
            _kb_file = st.file_uploader(
                "选择文件",
                key="kb_file_upload",
                type=["pdf", "docx", "doc", "xlsx", "xls", "txt", "md", "csv", "py", "js", "ts", "json"],
                label_visibility="collapsed",
            )
            if _kb_file:
                if st.button("📤 上传到知识库", use_container_width=True, type="primary", key="kb_upload_btn"):
                    with st.spinner("正在处理并嵌入文档，请稍候..."):
                        _kb_file.seek(0)
                        _kb_result = api(
                            "POST", "/knowledge/upload",
                            files={"file": (_kb_file.name, _kb_file.read(), _kb_file.type or "application/octet-stream")},
                        )
                    if _kb_result:
                        st.success(f"✅ {_kb_result['filename']}（{_kb_result['chunk_count']} 块）")
                        st.rerun()

        _kb_docs: list[dict] = api("GET", "/knowledge/", silent=True) or []
        if _kb_docs:
            for _doc in _kb_docs:
                _dc1, _dc2, _dc3 = st.columns([5, 1.5, 1])
                _dc1.markdown(f"📄 **{_doc['filename']}**")
                _dc2.caption(f"{_doc['chunk_count']} 块")
                if _dc3.button("🗑", key=f"kb_del_{_doc['id']}", help="删除"):
                    api("DELETE", f"/knowledge/{_doc['id']}")
                    st.rerun()
        else:
            st.caption("知识库为空，上传文档后可在会话中启用 RAG。")

    # ── Tab: 会话 ────────────────────────────────────────────────────────────
    with tab_chat:
        # 快速切换当前激活模型
        if configs:
            _qs_labels = [f"{c['display_name']} · {c['model']}" for c in configs]
            _qs_active_idx = next((i for i, c in enumerate(configs) if c["is_active"]), 0)
            _qs_sel = st.selectbox(
                "🤖 使用模型",
                options=_qs_labels,
                index=_qs_active_idx,
                key="quick_model_switch",
            )
            _qs_cfg = configs[_qs_labels.index(_qs_sel)]
            if not _qs_cfg["is_active"]:
                api("POST", f"/llm-configs/{_qs_cfg['id']}/activate")
                st.rerun()
        else:
            st.caption("尚未配置模型 → 前往「⚙️ 模型」tab")

        col_new, col_collab = st.columns(2)
        _rag_new_toggle = st.checkbox(
            "🔍 启用 RAG",
            key="rag_new_session",
            value=False,
            help="新会话开启知识库检索（使用内置本地嵌入模型，无需额外配置）",
        )
        if col_new.button("＋ 普通会话", use_container_width=True, type="primary"):
            if not active_config:
                st.error("请先配置并激活一个模型。")
            else:
                sp_id = st.session_state.get("selected_sp_id")
                result = api("POST", "/sessions/", json={
                    "title": "新会话",
                    "system_prompt_id": sp_id,
                    "rag_enabled": _rag_new_toggle,
                })
                if result:
                    st.session_state.active_session_id = result["id"]
                    st.session_state.active_session_collab_mode = None
                    st.session_state.chat_history = []
                    st.rerun()

        if col_collab.button("⚡ 协作会话", use_container_width=True):
            st.session_state.collab_show_form = not st.session_state.collab_show_form
            st.rerun()

        if st.session_state.collab_show_form:
            with st.container(border=True):
                st.caption("⚡ 新建多模型协作会话")

                # Build unified slot options: LLM configs + active MCP chat agents
                _mcp_chat_agents = [
                    ms for ms in _mcp_servers
                    if ms.get("mode") in ("chat_agent", "both") and ms.get("is_active")
                ]
                # slot_meta: display_label → {type, ...}
                _IMG_KW = ("dall-e", "gpt-image", "image-generation")
                slot_meta: dict[str, dict] = {}
                for c in configs:
                    if any(kw in c["model"].lower() for kw in _IMG_KW):
                        continue   # 图像生成模型不支持多模型协作
                    slot_meta[f"{c['display_name']} · {c['model']}"] = {"type": "llm", "id": c["id"]}
                for ms in _mcp_chat_agents:
                    slot_meta[f"[MCP] {ms['display_name']}"] = {
                        "type": "mcp", "server_name": ms["name"], "display_name": ms["display_name"],
                    }
                all_slot_labels = list(slot_meta.keys())
                llm_labels = [l for l, v in slot_meta.items() if v["type"] == "llm"]

                if len(all_slot_labels) < 2:
                    st.warning("至少需要 2 个模型/Agent 才能使用协作模式。")
                else:
                    collab_mode_sel = st.radio(
                        "协作模式",
                        ["🔀 圆桌模式（B+C 迭代辩论）", "👑 主从模式（主答 + 评委评分）"],
                        horizontal=True,
                        label_visibility="collapsed",
                    )
                    is_round_table = "圆桌" in collab_mode_sel

                    _ROLES_RT = ["proposer（提案者）", "critic（批判者）",
                                  "creative（创意者）", "validator（验证者）", "synthesizer（综合者）"]
                    _ROLE_KEYS = ["proposer", "critic", "creative", "validator", "synthesizer"]

                    if is_round_table:
                        n_models = st.slider("槽位数量", min_value=2, max_value=min(5, len(all_slot_labels)), value=min(3, len(all_slot_labels)))
                        rounds_rt = st.radio("讨论轮次", [1, 2], index=1,
                                             format_func=lambda x: f"{x} 轮（{'仅独立作答' if x == 1 else '独立作答 + 交叉审视'}）",
                                             horizontal=True)
                        st.caption("最后一个槽位固定为综合者，其余按序自动分配角色。MCP Agent 标记 [MCP]。")
                        rt_slot_labels = []
                        for i in range(n_models):
                            auto_role = _ROLES_RT[min(i, len(_ROLES_RT) - 1)] if i < n_models - 1 else _ROLES_RT[-1]
                            default_idx = min(i, len(all_slot_labels) - 1)
                            sel = st.selectbox(
                                f"槽位 {i+1}：{auto_role}",
                                all_slot_labels,
                                index=default_idx,
                                key=f"rt_slot_{i}",
                            )
                            rt_slot_labels.append(sel)

                        sp_id_c = st.session_state.get("selected_sp_id")
                        if st.button("✅ 创建圆桌会话", use_container_width=True, type="primary"):
                            roles = [_ROLE_KEYS[min(i, len(_ROLE_KEYS) - 1)] if i < n_models - 1
                                     else "synthesizer" for i in range(n_models)]
                            models_cfg = []
                            for label, role in zip(rt_slot_labels, roles):
                                info = slot_meta[label]
                                if info["type"] == "mcp":
                                    models_cfg.append({"type": "mcp", "server_name": info["server_name"],
                                                       "display_name": info["display_name"], "role": role})
                                else:
                                    models_cfg.append({"type": "llm", "config_id": str(info["id"]), "role": role})
                            collab_cfg = {
                                "mode": "round_table",
                                "rounds": rounds_rt,
                                "models": models_cfg,
                            }
                            result = api("POST", "/sessions/", json={
                                "title": "新会话",
                                "system_prompt_id": sp_id_c,
                                "collab_mode": "round_table",
                                "collab_config": collab_cfg,
                            })
                            if result:
                                st.session_state.active_session_id = result["id"]
                                st.session_state.active_session_collab_mode = "round_table"
                                st.session_state.chat_history = []
                                st.session_state.collab_show_form = False
                                st.rerun()
                    else:
                        st.caption("主模型（LLM）负责流式作答，评委可混合 LLM 和 MCP Agent。")
                        master_sel = st.selectbox("主模型（LLM）", llm_labels or all_slot_labels, key="ms_master")
                        reviewer_pool = [l for l in all_slot_labels if l != master_sel] or all_slot_labels
                        max_rev = min(4, len(reviewer_pool))
                        n_rev = st.slider("评委数量", 1, max_rev, min(2, max_rev))
                        reviewer_sel_labels = []
                        for i in range(n_rev):
                            default_idx = min(i, len(reviewer_pool) - 1)
                            sel = st.selectbox(f"评委 {i+1}", reviewer_pool, index=default_idx, key=f"ms_rev_{i}")
                            reviewer_sel_labels.append(sel)

                        sp_id_c = st.session_state.get("selected_sp_id")
                        if st.button("✅ 创建主从会话", use_container_width=True, type="primary"):
                            reviewer_slots = []
                            for label in reviewer_sel_labels:
                                info = slot_meta[label]
                                if info["type"] == "mcp":
                                    reviewer_slots.append({"type": "mcp", "server_name": info["server_name"],
                                                           "display_name": info["display_name"]})
                                else:
                                    reviewer_slots.append({"type": "llm", "config_id": str(info["id"])})
                            master_info = slot_meta[master_sel]
                            collab_cfg = {
                                "mode": "master_slave",
                                "master_config_id": str(master_info["id"]),
                                "reviewer_slots": reviewer_slots,
                            }
                            result = api("POST", "/sessions/", json={
                                "title": "新会话",
                                "system_prompt_id": sp_id_c,
                                "collab_mode": "master_slave",
                                "collab_config": collab_cfg,
                            })
                            if result:
                                st.session_state.active_session_id = result["id"]
                                st.session_state.active_session_collab_mode = "master_slave"
                                st.session_state.chat_history = []
                                st.session_state.collab_show_form = False
                                st.rerun()

        sessions: list[dict] = api("GET", "/sessions/", silent=True) or []

        if st.session_state.renaming_session_id:
            rid = st.session_state.renaming_session_id
            target = next((s for s in sessions if s["id"] == rid), None)
            if target:
                with st.form("rename_form"):
                    new_title = st.text_input("新名称", value=target["title"])
                    rc1, rc2 = st.columns(2)
                    if rc1.form_submit_button("确认", use_container_width=True, type="primary"):
                        if new_title.strip():
                            api("PATCH", f"/sessions/{rid}", json={"title": new_title})
                        st.session_state.renaming_session_id = None
                        st.rerun()
                    if rc2.form_submit_button("取消", use_container_width=True):
                        st.session_state.renaming_session_id = None
                        st.rerun()

        for s in sessions:
            is_current = s["id"] == st.session_state.active_session_id
            collab_badge = "⚡ " if s.get("collab_mode") else ""
            rag_badge = "🔍 " if s.get("rag_enabled") else ""
            col_name, col_ren, col_del = st.columns([5, 1, 1])

            with col_name:
                label = ("▶ " if is_current else "") + collab_badge + rag_badge + s["title"]
                if st.button(label, key=f"s_{s['id']}", use_container_width=True):
                    st.session_state.active_session_id = s["id"]
                    st.session_state.active_session_collab_mode = s.get("collab_mode")
                    st.session_state.selected_sp_id = s.get("system_prompt_id")
                    st.session_state.chat_history = [
                        {
                            "role": m["role"],
                            "content": m["content"] or "",
                            "attachments": m.get("attachments") or [],
                        }
                        for m in s.get("messages", [])
                        if m["role"] in ("user", "assistant")
                    ]
                    st.rerun()

            with col_ren:
                if st.button("✏️", key=f"r_{s['id']}", help="重命名"):
                    st.session_state.renaming_session_id = (
                        None if st.session_state.renaming_session_id == s["id"] else s["id"]
                    )
                    st.rerun()

            with col_del:
                if st.button("🗑", key=f"d_{s['id']}", help="删除"):
                    api("DELETE", f"/sessions/{s['id']}")
                    if s["id"] == st.session_state.active_session_id:
                        st.session_state.active_session_id = None
                        st.session_state.active_session_collab_mode = None
                        st.session_state.chat_history = []
                    st.rerun()

# ── 主区域：对话界面 ───────────────────────────────────────────────────────────

if not st.session_state.active_session_id:
    st.markdown(
        """
        <div style='text-align:center;padding:80px 0'>
            <h1>💠 AgentNexus-J</h1>
            <p style='font-size:1.1rem;color:#888'>
                企业级多智能体协作系统<br>
                ← 先在左侧配置模型，再新建或选择会话
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# 顶部标题栏
session_data = api("GET", f"/sessions/{st.session_state.active_session_id}", silent=True)

# _is_collab 在标题栏渲染前确定（后续输入区也复用）
_is_collab = bool(st.session_state.get("active_session_collab_mode"))

if session_data:
    # 同步协作模式状态（切换会话时）
    if st.session_state.active_session_collab_mode != session_data.get("collab_mode"):
        st.session_state.active_session_collab_mode = session_data.get("collab_mode")
        _is_collab = bool(session_data.get("collab_mode"))

    collab_mode = session_data.get("collab_mode")
    _rag_active = session_data.get("rag_enabled", False)

    # 标题栏：标题(5) | 控制区(3) | 模型标签(2)
    _hc_title, _hc_controls, _hc_model = st.columns([5, 3, 2])

    with _hc_title:
        title_prefix = {"round_table": "⚡ 圆桌 · ", "master_slave": "⚡ 主从 · "}.get(collab_mode or "", "")
        rag_prefix = "🔍 RAG · " if _rag_active else ""
        st.subheader(title_prefix + rag_prefix + session_data["title"])
        sp_ref = session_data.get("system_prompt_ref")
        if sp_ref:
            st.caption(f"📋 System Prompt：`{sp_ref['name']}`")

    with _hc_controls:
        if not _is_collab:
            _ct1, _ct2 = st.columns(2)
            _thinking_on = _ct1.toggle(
                "🧠",
                value=st.session_state.get("thinking_mode", False),
                key="thinking_toggle",
                disabled=_is_generating,
                help="**深度思考**：开启后模型先进行内部推理再作答，适合复杂分析、数学推导等任务。DeepSeek-R1 / QwQ / Claude 扩展思考均支持。",
            )
            st.session_state["thinking_mode"] = _thinking_on
            _search_on = _ct2.toggle(
                "🔍",
                value=st.session_state.get("search_mode", False),
                key="search_toggle",
                disabled=_is_generating or not _active_search,
                help="**网络搜索**：开启后模型可主动调用搜索引擎获取实时信息。" if _active_search
                     else "**网络搜索**：请先在「🛠 工具 → 🔍 网络搜索」中配置搜索引擎。",
            )
            st.session_state["search_mode"] = _search_on
        else:
            _thinking_on = False
            _search_on   = False
            # 协作模式：显示参与模型摘要 + 编辑按钮
            _cfg_map = {str(c["id"]): c for c in configs}
            _ccfg = session_data.get("collab_config") or {}
            _cmode = _ccfg.get("mode", collab_mode)
            _model_chips: list[str] = []
            if _cmode == "master_slave":
                _m = _cfg_map.get(str(_ccfg.get("master_config_id", "")))
                _model_chips.append(f"👑 {_m['display_name'] if _m else '?'}")
                for _r in _ccfg.get("reviewer_slots", []):
                    if _r.get("type") == "mcp":
                        _model_chips.append(f"⚖️ [MCP]{_r.get('display_name','?')}")
                    else:
                        _rc = _cfg_map.get(str(_r.get("config_id", "")))
                        _model_chips.append(f"⚖️ {_rc['display_name'] if _rc else '?'}")
            elif _cmode == "round_table":
                for _mi, _mm in enumerate(_ccfg.get("models", [])):
                    if _mm.get("type") == "mcp":
                        _model_chips.append(f"[MCP]{_mm.get('display_name','?')}")
                    else:
                        _mc = _cfg_map.get(str(_mm.get("config_id", "")))
                        _model_chips.append(_mc["display_name"] if _mc else "?")
            st.caption("  ·  ".join(_model_chips) if _model_chips else "协作配置未知")
            if st.button("✏️ 编辑协作", key="btn_collab_edit", use_container_width=True):
                st.session_state["_collab_edit_open"] = not st.session_state.get("_collab_edit_open", False)
                st.rerun()

    with _hc_model:
        if collab_mode:
            cfg_data = session_data.get("collab_config") or {}
            n_models = len(cfg_data.get("models", [])) or (
                1 + len(cfg_data.get("reviewer_config_ids", []))
            )
            st.caption(f"⚡ 协作 · {n_models} 模型")
        else:
            model_label = active_config["model"] if active_config else "未配置"
            st.caption(f"`{model_label}`")
else:
    _thinking_on = False
    _search_on   = False

st.divider()

# ── 协作配置编辑面板 ──────────────────────────────────────────────────────────
if _is_collab and st.session_state.get("_collab_edit_open") and session_data:
    _ccfg_edit = session_data.get("collab_config") or {}
    _cmode_edit = _ccfg_edit.get("mode", collab_mode)
    _IMG_KW2 = ("dall-e", "gpt-image", "image-generation")
    _slot_meta_e: dict[str, dict] = {}
    for _c in configs:
        if not any(_kw in _c["model"].lower() for _kw in _IMG_KW2):
            _slot_meta_e[f"{_c['display_name']} · {_c['model']}"] = {"type": "llm", "id": _c["id"]}
    for _ms in _mcp_servers:
        if _ms.get("mode") in ("chat_agent", "both") and _ms.get("is_active"):
            _slot_meta_e[f"[MCP] {_ms['display_name']}"] = {
                "type": "mcp", "server_name": _ms["name"], "display_name": _ms["display_name"],
            }
    _all_e = list(_slot_meta_e.keys())
    _llm_e = [_l for _l, _v in _slot_meta_e.items() if _v["type"] == "llm"]
    _cfg_map_e = {str(_c["id"]): _c for _c in configs}

    with st.container(border=True):
        st.caption("✏️ 修改协作配置（保存后立即生效）")

        if _cmode_edit == "round_table":
            _cur_models = _ccfg_edit.get("models", [])
            _rounds_e = st.radio("讨论轮次", [1, 2],
                                 index=max(0, _ccfg_edit.get("rounds", 2) - 1),
                                 format_func=lambda x: f"{x} 轮", horizontal=True,
                                 key="edit_rounds")
            _ROLES_E = ["proposer", "critic", "creative", "validator", "synthesizer"]
            _n_e = st.slider("槽位数量", 2, min(5, len(_all_e)),
                             value=min(max(2, len(_cur_models)), 5), key="edit_n_slots")
            _new_slots_e = []
            for _i in range(_n_e):
                _auto_r = _ROLES_E[min(_i, len(_ROLES_E)-1)] if _i < _n_e-1 else "synthesizer"
                _cur_label = ""
                if _i < len(_cur_models):
                    _cm = _cur_models[_i]
                    if _cm.get("type") == "mcp":
                        _cur_label = f"[MCP] {_cm.get('display_name','')}"
                    else:
                        _cc = _cfg_map_e.get(str(_cm.get("config_id","")))
                        _cur_label = f"{_cc['display_name']} · {_cc['model']}" if _cc else ""
                _def_i = _all_e.index(_cur_label) if _cur_label in _all_e else min(_i, len(_all_e)-1)
                _sel_e = st.selectbox(f"槽位 {_i+1}：{_auto_r}", _all_e,
                                      index=_def_i, key=f"edit_slot_{_i}")
                _new_slots_e.append(_sel_e)
            if st.button("💾 保存圆桌配置", type="primary", key="save_rt_edit"):
                _roles_e = [_ROLES_E[min(_i, len(_ROLES_E)-1)] if _i < _n_e-1 else "synthesizer"
                            for _i in range(_n_e)]
                _models_e = []
                for _lbl, _role in zip(_new_slots_e, _roles_e):
                    _inf = _slot_meta_e[_lbl]
                    if _inf["type"] == "mcp":
                        _models_e.append({"type":"mcp","server_name":_inf["server_name"],
                                          "display_name":_inf["display_name"],"role":_role})
                    else:
                        _models_e.append({"type":"llm","config_id":str(_inf["id"]),"role":_role})
                _new_cfg = {"mode":"round_table","rounds":_rounds_e,"models":_models_e}
                api("PATCH", f"/sessions/{st.session_state.active_session_id}",
                    json={"collab_config": _new_cfg})
                st.session_state["_collab_edit_open"] = False
                st.rerun()

        else:  # master_slave
            _cur_master_id = str(_ccfg_edit.get("master_config_id",""))
            _cur_master_lbl = ""
            _mc_e = _cfg_map_e.get(_cur_master_id)
            if _mc_e:
                _cur_master_lbl = f"{_mc_e['display_name']} · {_mc_e['model']}"
            _master_def = _llm_e.index(_cur_master_lbl) if _cur_master_lbl in _llm_e else 0
            _master_sel_e = st.selectbox("主模型（LLM）", _llm_e or _all_e,
                                         index=_master_def, key="edit_master")
            _rev_pool_e = [_l for _l in _all_e if _l != _master_sel_e] or _all_e
            _cur_revs = _ccfg_edit.get("reviewer_slots", [])
            _n_rev_e = st.slider("评委数量", 1, min(4, len(_rev_pool_e)),
                                 value=min(max(1, len(_cur_revs)), 4), key="edit_n_rev")
            _new_revs_e = []
            for _i in range(_n_rev_e):
                _cur_rv_lbl = ""
                if _i < len(_cur_revs):
                    _rv = _cur_revs[_i]
                    if _rv.get("type") == "mcp":
                        _cur_rv_lbl = f"[MCP] {_rv.get('display_name','')}"
                    else:
                        _rvc = _cfg_map_e.get(str(_rv.get("config_id","")))
                        _cur_rv_lbl = f"{_rvc['display_name']} · {_rvc['model']}" if _rvc else ""
                _rv_def = _rev_pool_e.index(_cur_rv_lbl) if _cur_rv_lbl in _rev_pool_e else min(_i, len(_rev_pool_e)-1)
                _sel_rv = st.selectbox(f"评委 {_i+1}", _rev_pool_e,
                                       index=_rv_def, key=f"edit_rev_{_i}")
                _new_revs_e.append(_sel_rv)
            if st.button("💾 保存主从配置", type="primary", key="save_ms_edit"):
                _rev_slots_e = []
                for _lbl in _new_revs_e:
                    _inf = _slot_meta_e[_lbl]
                    if _inf["type"] == "mcp":
                        _rev_slots_e.append({"type":"mcp","server_name":_inf["server_name"],
                                             "display_name":_inf["display_name"]})
                    else:
                        _rev_slots_e.append({"type":"llm","config_id":str(_inf["id"])})
                _m_inf = _slot_meta_e[_master_sel_e]
                _new_cfg = {"mode":"master_slave",
                            "master_config_id":str(_m_inf["id"]),
                            "reviewer_slots":_rev_slots_e}
                api("PATCH", f"/sessions/{st.session_state.active_session_id}",
                    json={"collab_config": _new_cfg})
                st.session_state["_collab_edit_open"] = False
                st.rerun()

        if st.button("✖ 取消", key="cancel_collab_edit"):
            st.session_state["_collab_edit_open"] = False
            st.rerun()

# 渲染历史消息
_history = st.session_state.chat_history
_last_collab = st.session_state.get("last_collab_process", [])

_copy_content: str | None = None

for i, msg in enumerate(_history):
    _is_last_assistant = msg["role"] == "assistant" and i == len(_history) - 1
    with st.chat_message(msg["role"]):
        # 最后一条 assistant 消息：若有协作过程数据，显示在答案上方
        if _is_last_assistant and _last_collab:
            _has_reviewer    = any(e.get("type") == "collab_reviewer_result" for e in _last_collab)
            _has_round_table = any(e.get("type") == "collab_model_result"    for e in _last_collab)
            if _has_reviewer:
                _render_master_slave_review(_last_collab)
            elif _has_round_table:
                with st.expander("🔄 协作决策过程", expanded=False):
                    _render_round_table_process(_last_collab)
        # 附件预览
        for _att in (msg.get("attachments") or []):
            if _att.get("type") == "image":
                _img_bytes = base64.b64decode(_att["data"])
                st.image(_img_bytes, caption=_att.get("filename", ""), width=320)
            else:
                st.caption(f"📄 {_att.get('filename', '文件')}")
        if msg.get("thinking"):
            with st.expander(f"🧠 思考完毕（{len(msg['thinking'])} 字符）", expanded=False):
                st.markdown(msg["thinking"])
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            _media_download_buttons(msg["content"], i)

    # ── 最后一条 assistant 消息下方：重试 / 复制按钮 ──────────────────────────
    if _is_last_assistant:
        _ab1, _ab2, _ = st.columns([0.065, 0.065, 0.87])
        with _ab1:
            _retry_disabled = bool(st.session_state.get("active_session_collab_mode"))
            if st.button(
                "",
                icon=":material/replay:",
                key="btn_retry",
                help="重新生成" if not _retry_disabled else "协作模式暂不支持重试",
                disabled=_retry_disabled,
            ):
                if _history and _history[-1]["role"] == "assistant":
                    st.session_state.chat_history.pop()
                st.session_state.last_collab_process = []
                st.session_state._retry_pending = True
                st.rerun()
        with _ab2:
            if st.button(
                "",
                icon=":material/content_copy:",
                key="btn_copy",
                help="复制回答",
            ):
                _copy_content = msg["content"]

# 复制触发：通过 JS 写入剪贴板
if _copy_content:
    stcomp.html(
        f"<script>window.parent.navigator.clipboard.writeText("
        f"{json.dumps(_copy_content)});</script>",
        height=0,
    )
    st.toast("✅ 已复制到剪贴板")

# ── 对话输入 ──────────────────────────────────────────────────────────────────

_hint = "发送消息给协作团队..." if _is_collab else "发送消息给 AgentNexus-J..."

# 消费重试标志
_is_retry = st.session_state.pop("_retry_pending", False)
_effective_prompt: str | None = None
_effective_attachments: list[dict] = []

# 重试：进入预飞流程（锁 UI 后再执行）
if _is_retry and not _is_generating:
    st.session_state["_pending_prompt"]      = st.session_state.get("_last_prompt", "")
    st.session_state["_pending_attachments"] = st.session_state.get("_last_attachments", [])
    st.session_state["_pending_is_retry"]    = True
    st.session_state["_is_generating"]       = True
    st.rerun()

# 文件上传器（协作模式不支持附件，生成中隐藏）
_uploaded_files: list = []
if not _is_collab and not _is_generating and st.session_state.active_session_id:
    st.markdown(
        "<style>"
        "[data-testid='stFileUploader']{border:1px dashed #555;border-radius:8px;padding:2px 8px}"
        "[data-testid='stFileUploaderDropzone']{padding:6px 12px;min-height:0}"
        "[data-testid='stFileUploaderDropzone'] span{font-size:.8rem}"
        "[data-testid='stFileUploaderDropzone'] small{display:none}"
        "</style>",
        unsafe_allow_html=True,
    )
    _uploaded_files = st.file_uploader(
        "📎 添加附件",
        accept_multiple_files=True,
        key=f"file_up_{st.session_state._upload_generation}",
        type=["jpg", "jpeg", "png", "gif", "webp", "pdf",
              "docx", "doc", "xlsx", "xls", "txt", "md", "csv",
              "py", "js", "ts", "json", "yaml", "yml"],
        label_visibility="collapsed",
        help="支持图片 / PDF / Office / 文本文件。上传图片需要模型具备视觉能力（Vision），"
             "如 Claude 3+、GPT-4o、qwen-vl-max 等，文本类文件对所有模型适用。",
    ) or []

# 新消息输入（生成中禁用）
_input_prompt = st.chat_input(_hint, disabled=_is_generating)
if _input_prompt and not _is_generating:
    # 收集附件
    _atts: list[dict] = []
    for _f in _uploaded_files:
        _f.seek(0)
        _atts.append({
            "filename": _f.name,
            "mime_type": _f.type or "application/octet-stream",
            "data": base64.b64encode(_f.read()).decode(),
        })
    if _atts:
        st.session_state["_upload_generation"] += 1
    # 预飞：锁 UI 后再 streaming
    st.session_state["_pending_prompt"]      = _input_prompt
    st.session_state["_pending_attachments"] = _atts
    st.session_state["_pending_is_retry"]    = False
    st.session_state["_is_generating"]       = True
    st.rerun()

# 消费 pending（本轮真正执行生成）
if _is_generating and st.session_state.get("_pending_prompt") is not None:
    _effective_prompt      = st.session_state.pop("_pending_prompt")
    _effective_attachments = st.session_state.pop("_pending_attachments", [])
    _is_retry              = st.session_state.pop("_pending_is_retry", False)

if _effective_prompt:
    if not _is_collab and not active_config:
        st.error("请先在左侧配置并激活一个模型。")
        st.stop()

    reply: str = ""

    if not _is_retry:
        # 存储供下次重试使用
        st.session_state._last_prompt      = _effective_prompt
        st.session_state._last_attachments = _effective_attachments
        st.session_state.last_collab_process = []
        # 追加用户消息到历史并即时显示
        st.session_state.chat_history.append({
            "role": "user",
            "content": _effective_prompt,
            "attachments": _effective_attachments,
        })
        with st.chat_message("user"):
            for _att in _effective_attachments:
                if _att["mime_type"].startswith("image/"):
                    st.image(base64.b64decode(_att["data"]), caption=_att["filename"], width=320)
                else:
                    st.caption(f"📄 {_att['filename']}")
            st.markdown(_effective_prompt)

    _saved_thinking = ""   # 协作模式无 thinking，统一初始化避免 NameError

    if _is_collab:
        with st.chat_message("assistant"):
            # ── 实时展示区域 ──────────────────────────────────────────────────
            phase_ph   = st.empty()
            live_ph    = st.empty()
            score_ph   = st.empty()

            process_events: list[dict] = []
            final_text_parts: list[str] = []
            master_text_live = ""
            reviewer_live: list[str] = []

            for ev in _iter_collab_events(st.session_state.active_session_id, _effective_prompt):
                t = ev.get("type", "")

                if t == "collab_phase":
                    phase_ph.info(f"⚡ {ev.get('label', '')}...")
                    process_events.append(ev)

                elif t == "collab_model_text" and ev.get("role") == "master":
                    master_text_live += ev.get("content", "")
                    live_ph.markdown(master_text_live + "▌")
                    process_events.append(ev)

                elif t == "collab_model_end" and ev.get("role") == "master":
                    live_ph.markdown(master_text_live)
                    process_events.append(ev)

                elif t == "collab_model_result":
                    role_label = ev.get("role_label", ev.get("role", ""))
                    model_name = ev.get("model_name", "")
                    phase_ph.info(f"✅ {role_label}（{model_name}）完成")
                    process_events.append(ev)

                elif t == "collab_reviewer_result":
                    model_name = ev.get("model_name", "")
                    total      = ev.get("weighted_total", 0)
                    critique   = ev.get("critique", "")
                    reviewer_live.append(
                        f"**⚖️ {model_name}**  综合 **{total}/10**  \n💬 {critique}"
                    )
                    score_ph.markdown("\n\n---\n\n".join(reviewer_live))
                    process_events.append(ev)

                elif t == "collab_synthesis_start":
                    phase_ph.info(f"🔀 综合者（{ev.get('model_name','')}）正在输出最终答案...")
                    live_ph.empty()
                    process_events.append(ev)

                elif t == "text":
                    final_text_parts.append(ev.get("content", ""))
                    live_ph.markdown("".join(final_text_parts) + "▌")

                elif t == "error":
                    phase_ph.error(ev.get("message", "未知错误"))
                    process_events.append(ev)

                elif t == "done":
                    break

            phase_ph.empty()
            live_ph.empty()
            score_ph.empty()

            final_text = "".join(final_text_parts)
            st.session_state.last_collab_process = process_events

            has_reviewer    = any(e.get("type") == "collab_reviewer_result" for e in process_events)
            has_round_table = any(e.get("type") == "collab_model_result"    for e in process_events)

            if has_reviewer:
                _render_master_slave_review(process_events)
            elif has_round_table:
                with st.expander("🔄 协作决策过程", expanded=True):
                    _render_round_table_process(process_events)

            if final_text:
                st.markdown(final_text)
            else:
                st.warning("未收到最终答案，请检查协作配置。")

            reply = final_text
    else:
        st.session_state["_compression_happened"] = False
        _saved_thinking = ""
        with st.chat_message("assistant"):
            if _thinking_on:
                # ── Thinking 模式：手动 loop + st.status 展示思考过程 ─────────
                _thinking_buf = ""
                _text_buf = ""
                _status = None
                _thinking_ph = None
                _text_ph = st.empty()

                for _p in _iter_raw_chat_events(
                    st.session_state.active_session_id,
                    _effective_prompt,
                    _effective_attachments,
                    is_retry=_is_retry,
                    thinking=True,
                    search=_search_on,
                ):
                    _pt = _p.get("type")
                    if _pt == "thinking":
                        chunk = _p.get("content", "")
                        _thinking_buf += chunk
                        if _status is None:
                            _status = st.status("🧠 深度思考中...", expanded=True)
                            _thinking_ph = _status.empty()
                        _thinking_ph.markdown(_thinking_buf + "▌")
                    elif _pt == "text":
                        if _status is not None and not _text_buf:
                            # 首个 text chunk 到来时收起思考区域
                            _thinking_ph.markdown(_thinking_buf)
                            _status.update(
                                label=f"🧠 思考完毕（{len(_thinking_buf)} 字符）",
                                state="complete",
                                expanded=False,
                            )
                        _text_buf += _p.get("content", "")
                        _text_ph.markdown(_text_buf + "▌")
                    elif _pt == "tool_start":
                        _tool_info = _p.get("tool_info", [])
                        _blocks = []
                        for _ti in _tool_info:
                            _name = _ti.get("name", "")
                            _inp = _ti.get("input", {})
                            if _name == "execute_terminal":
                                _cmd = _inp.get("command", "")
                                _wd = _inp.get("working_dir", "")
                                _hdr = "🖥 **执行命令**" + (f"  `{_wd}`" if _wd else "")
                                _blocks.append(f"{_hdr}\n```shell\n{_cmd}\n```")
                            elif _name.startswith("mcp__"):
                                _parts = _name.split("__", 2)
                                _srv = _parts[1] if len(_parts) > 1 else ""
                                _tool = _parts[2] if len(_parts) > 2 else _name
                                _args = ", ".join(f"`{k}`={repr(v)}" for k, v in _inp.items()) if _inp else "无参数"
                                _blocks.append(f"🔌 **MCP [{_srv}]** · `{_tool}`\n\n> {_args}")
                            else:
                                _blocks.append({"get_system_time": "🕐 获取系统时间"}.get(_name, f"🔧 {_name}"))
                        _text_buf += "\n\n" + "\n\n".join(_blocks) + "\n\n"
                        _text_ph.markdown(_text_buf)
                    elif _pt == "tool_end":
                        _results = _p.get("results", [])
                        if _results:
                            _text_buf += f"```\n{chr(10).join(str(r) for r in _results)}\n```\n\n"
                            _text_ph.markdown(_text_buf)
                    elif _pt == "compression":
                        st.session_state["_compression_happened"] = True
                    elif _pt == "error":
                        _text_ph.markdown(_text_buf + f"\n\n❌ {_p.get('message', '未知错误')}")

                _text_ph.markdown(_text_buf)
                # 若模型只输出了思考但没有正文（罕见），关闭 status
                if _status is not None and not _text_buf:
                    _thinking_ph.markdown(_thinking_buf)
                    _status.update(label="🧠 思考完毕", state="complete", expanded=False)
                _saved_thinking = _thinking_buf
                reply = _text_buf
            else:
                # ── 普通模式：沿用 st.write_stream ───────────────────────────
                reply = st.write_stream(
                    stream_chat(
                        st.session_state.active_session_id,
                        _effective_prompt,
                        _effective_attachments,
                        is_retry=_is_retry,
                        search=_search_on,
                    )
                )
        if st.session_state.pop("_compression_happened", False):
            st.toast("✂️ 对话历史已自动压缩以节省上下文空间", icon="💡")

    if reply:
        entry: dict = {"role": "assistant", "content": reply}
        if _saved_thinking:
            entry["thinking"] = _saved_thinking
        st.session_state.chat_history.append(entry)
    st.session_state["_is_generating"] = False
    st.rerun()
