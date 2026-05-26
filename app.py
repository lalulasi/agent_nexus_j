"""AgentNexus-J — Streamlit 控制台"""

import base64
import json
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


def stream_chat(
    session_id: str,
    message: str,
    attachments: list[dict] | None = None,
    is_retry: bool = False,
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


# ── Session state 初始化 ──────────────────────────────────────────────────────

for _k, _v in [
    ("active_session_id", None),
    ("chat_history", []),
    ("editing_config_id", None),
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

# ── 侧边栏 ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("💠 AgentNexus-J")
    st.caption("企业级多智能体协作控制台")

    configs: list[dict] = api("GET", "/llm-configs/", silent=True) or []
    active_config = next((c for c in configs if c["is_active"]), None)

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
                submitted = st.form_submit_button("💾 保存并激活", use_container_width=True, type="primary")
            if submitted:
                if not n_name or not n_model or not n_key:
                    st.error("配置名称、模型名称、API Key 为必填项。")
                else:
                    result = api("POST", "/llm-configs/", json={
                        "display_name": n_name, "model": n_model,
                        "api_key": n_key, "base_url": n_url or None,
                        "embedding_model": n_emb_model,
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

            col_act, col_edit = st.columns(2)
            if not selected["is_active"]:
                if col_act.button("⚡ 激活", use_container_width=True, type="primary"):
                    api("POST", f"/llm-configs/{selected['id']}/activate")
                    st.rerun()
            else:
                col_act.success("已激活 ✅")

            if col_edit.button("✏️ 编辑", use_container_width=True):
                st.session_state.editing_config_id = (
                    None if st.session_state.editing_config_id == selected["id"]
                    else selected["id"]
                )
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
                if len(configs) < 2:
                    st.warning("至少需要 2 个模型配置才能使用协作模式。")
                else:
                    collab_mode_sel = st.radio(
                        "协作模式",
                        ["🔀 圆桌模式（B+C 迭代辩论）", "👑 主从模式（主答 + 评委评分）"],
                        horizontal=True,
                        label_visibility="collapsed",
                    )
                    is_round_table = "圆桌" in collab_mode_sel

                    config_options = {f"{c['display_name']} · {c['model']}": c["id"] for c in configs}
                    config_labels = list(config_options.keys())

                    _ROLES_RT = ["proposer（提案者）", "critic（批判者）",
                                  "creative（创意者）", "validator（验证者）", "synthesizer（综合者）"]
                    _ROLE_KEYS = ["proposer", "critic", "creative", "validator", "synthesizer"]

                    if is_round_table:
                        n_models = st.slider("模型数量", min_value=2, max_value=min(5, len(configs)), value=min(3, len(configs)))
                        rounds_rt = st.radio("讨论轮次", [1, 2], index=1,
                                             format_func=lambda x: f"{x} 轮（{'仅独立作答' if x == 1 else '独立作答 + 交叉审视'}）",
                                             horizontal=True)
                        st.caption("最后一个槽位固定为综合者，其余按序自动分配角色。")
                        rt_model_ids = []
                        for i in range(n_models):
                            auto_role = _ROLES_RT[min(i, len(_ROLES_RT) - 1)] if i < n_models - 1 else _ROLES_RT[-1]
                            default_idx = min(i, len(config_labels) - 1)
                            sel = st.selectbox(
                                f"槽位 {i+1}：{auto_role}",
                                config_labels,
                                index=default_idx,
                                key=f"rt_slot_{i}",
                            )
                            rt_model_ids.append(config_options[sel])

                        sp_id_c = st.session_state.get("selected_sp_id")
                        if st.button("✅ 创建圆桌会话", use_container_width=True, type="primary"):
                            roles = [_ROLE_KEYS[min(i, len(_ROLE_KEYS) - 1)] if i < n_models - 1
                                     else "synthesizer" for i in range(n_models)]
                            collab_cfg = {
                                "mode": "round_table",
                                "rounds": rounds_rt,
                                "models": [{"config_id": str(cid), "role": r}
                                           for cid, r in zip(rt_model_ids, roles)],
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
                        st.caption("主模型负责作答，评委模型并行评审打分。")
                        master_sel = st.selectbox("主模型", config_labels, key="ms_master")
                        remaining = [l for l in config_labels if l != master_sel] or config_labels
                        max_rev = min(4, len(remaining))
                        n_rev = st.slider("评委数量", 1, max_rev, min(2, max_rev))
                        reviewer_ids = []
                        for i in range(n_rev):
                            default_idx = min(i, len(remaining) - 1)
                            sel = st.selectbox(f"评委 {i+1}", remaining, index=default_idx, key=f"ms_rev_{i}")
                            reviewer_ids.append(config_options[sel])

                        sp_id_c = st.session_state.get("selected_sp_id")
                        if st.button("✅ 创建主从会话", use_container_width=True, type="primary"):
                            collab_cfg = {
                                "mode": "master_slave",
                                "master_config_id": str(config_options[master_sel]),
                                "reviewer_config_ids": [str(rid) for rid in reviewer_ids],
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
if session_data:
    # 同步协作模式状态（切换会话时）
    if st.session_state.active_session_collab_mode != session_data.get("collab_mode"):
        st.session_state.active_session_collab_mode = session_data.get("collab_mode")

    col_title, col_model = st.columns([6, 1])
    with col_title:
        collab_mode = session_data.get("collab_mode")
        _rag_active = session_data.get("rag_enabled", False)
        title_prefix = {"round_table": "⚡ 圆桌 · ", "master_slave": "⚡ 主从 · "}.get(collab_mode or "", "")
        rag_prefix = "🔍 RAG · " if _rag_active else ""
        st.subheader(title_prefix + rag_prefix + session_data["title"])
        sp_ref = session_data.get("system_prompt_ref")
        if sp_ref:
            st.caption(f"📋 System Prompt：`{sp_ref['name']}`")
    with col_model:
        if collab_mode:
            cfg_data = session_data.get("collab_config") or {}
            n_models = len(cfg_data.get("models", [])) or (
                1 + len(cfg_data.get("reviewer_config_ids", []))
            )
            st.caption(f"⚡ 协作 · {n_models} 模型")
        else:
            model_label = active_config["model"] if active_config else "未配置"
            st.caption(f"`{model_label}`")

st.divider()

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
        st.markdown(msg["content"])

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

_is_collab = bool(st.session_state.get("active_session_collab_mode"))
_hint = "发送消息给协作团队..." if _is_collab else "发送消息给 AgentNexus-J..."

# 消费重试标志（在渲染 chat_input 之前）
_is_retry = st.session_state.pop("_retry_pending", False)
_effective_prompt: str | None = None
_effective_attachments: list[dict] = []

if _is_retry:
    _effective_prompt    = st.session_state.get("_last_prompt", "")
    _effective_attachments = st.session_state.get("_last_attachments", [])

# 文件上传器（协作模式不支持附件）
_uploaded_files: list = []
if not _is_collab and st.session_state.active_session_id:
    _uploaded_files = st.file_uploader(
        "附件",
        accept_multiple_files=True,
        key=f"file_up_{st.session_state._upload_generation}",
        type=["jpg", "jpeg", "png", "gif", "webp", "pdf",
              "docx", "doc", "xlsx", "xls", "txt", "md", "csv",
              "py", "js", "ts", "json", "yaml", "yml"],
        label_visibility="collapsed",
        help="支持图片 / PDF / Office / 文本文件。上传图片需要模型具备视觉能力（Vision），"
             "如 Claude 3+、GPT-4o、qwen-vl-max 等，文本类文件对所有模型适用。",
    ) or []

# 新消息输入
_input_prompt = st.chat_input(_hint)
if _input_prompt and not _is_retry:
    _effective_prompt = _input_prompt
    for _f in _uploaded_files:
        _f.seek(0)
        _effective_attachments.append({
            "filename": _f.name,
            "mime_type": _f.type or "application/octet-stream",
            "data": base64.b64encode(_f.read()).decode(),
        })
    if _effective_attachments:
        st.session_state["_upload_generation"] += 1

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
        with st.chat_message("assistant"):
            reply = st.write_stream(
                stream_chat(
                    st.session_state.active_session_id,
                    _effective_prompt,
                    _effective_attachments,
                    is_retry=_is_retry,
                )
            )
        if st.session_state.pop("_compression_happened", False):
            st.toast("✂️ 对话历史已自动压缩以节省上下文空间", icon="💡")

    if reply:
        st.session_state.chat_history.append({"role": "assistant", "content": reply})
    st.rerun()
