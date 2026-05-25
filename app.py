"""AgentNexus-J — Streamlit 控制台"""

import json
from datetime import datetime

import httpx
import streamlit as st

# ── 自动主题（白天 < 18:00 用亮色，之后用暗色）────────────────────────────────

_NIGHT_CSS = """
<style>
/* ══ AgentNexus-J 夜间主题 ══ */

/* 主背景 */
.stApp {
    background-color: #0E1117 !important;
}

/* 顶部装饰条 */
[data-testid="stDecoration"] {
    background-image: linear-gradient(90deg, #5B6EFF, #8B5CF6) !important;
}

/* 侧边栏 */
section[data-testid="stSidebar"] > div:first-child {
    background-color: #1A1D27 !important;
}

/* 通用文字 */
.stApp p, .stApp span, .stApp label,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6,
.stMarkdown p, .stMarkdown li,
[data-testid="stText"] {
    color: #FAFAFA !important;
}
[data-testid="stCaptionContainer"] p,
.stCaption {
    color: #9095A5 !important;
}

/* 输入框 & 文本域 */
.stTextInput input,
.stTextArea textarea,
[data-baseweb="input"] input {
    background-color: #262730 !important;
    color: #FAFAFA !important;
    border-color: #3D4051 !important;
}
[data-baseweb="base-input"] {
    background-color: #262730 !important;
}

/* 下拉选择框 */
[data-baseweb="select"] > div:first-child {
    background-color: #262730 !important;
    border-color: #3D4051 !important;
    color: #FAFAFA !important;
}
[data-baseweb="select"] span,
[data-baseweb="select"] div {
    color: #FAFAFA !important;
}
[data-baseweb="menu"] {
    background-color: #262730 !important;
    border-color: #3D4051 !important;
}
[data-baseweb="menu"] li {
    color: #FAFAFA !important;
}
[data-baseweb="menu"] li:hover,
[data-baseweb="menu"] [aria-selected="true"] {
    background-color: #3A3D50 !important;
}

/* 普通按钮 */
.stButton > button {
    background-color: #262730 !important;
    color: #FAFAFA !important;
    border-color: #3D4051 !important;
}
.stButton > button:hover {
    background-color: #3A3D50 !important;
    border-color: #5B6EFF !important;
    color: #FFFFFF !important;
}

/* Primary 按钮保持品牌色 */
.stButton > button[kind="primary"] {
    background-color: #5B6EFF !important;
    border-color: #5B6EFF !important;
    color: #FFFFFF !important;
}
.stButton > button[kind="primary"]:hover {
    background-color: #4A5AE8 !important;
    border-color: #4A5AE8 !important;
}

/* 表单容器 */
[data-testid="stForm"] {
    border-color: #3D4051 !important;
    background-color: transparent !important;
}

/* Expander */
[data-testid="stExpander"] details {
    background-color: #1A1D27 !important;
    border-color: #3D4051 !important;
}
[data-testid="stExpander"] summary,
[data-testid="stExpander"] summary span {
    color: #FAFAFA !important;
}

/* Chat 消息气泡 */
[data-testid="stChatMessage"] {
    background-color: #1A1D27 !important;
}
[data-testid="stChatMessageContent"] p {
    color: #FAFAFA !important;
}

/* Radio & Checkbox */
[data-testid="stRadio"] label p,
[data-testid="stCheckbox"] label p {
    color: #FAFAFA !important;
}

/* 分割线 */
hr {
    border-color: #3D4051 !important;
}

/* 行内代码 */
code {
    background-color: #262730 !important;
    color: #C4A8FF !important;
}

/* 成功 / 错误 / 警告横幅 */
[data-testid="stNotification"][data-baseweb="notification"] {
    background-color: #1A1D27 !important;
}
div[data-testid="stAlert"][kind="success"] {
    background-color: #0B2318 !important;
    color: #6EE7B7 !important;
}
div[data-testid="stAlert"][kind="error"] {
    background-color: #2B0D0D !important;
    color: #FCA5A5 !important;
}
div[data-testid="stAlert"][kind="warning"] {
    background-color: #2B1D00 !important;
    color: #FCD34D !important;
}

/* 聊天输入框 */
[data-testid="stChatInput"] textarea {
    background-color: #262730 !important;
    color: #FAFAFA !important;
    border-color: #3D4051 !important;
}
[data-testid="stChatInputContainer"] {
    background-color: #1A1D27 !important;
    border-color: #3D4051 !important;
}
</style>
"""

_DAY_CSS = """
<style>
/* ══ AgentNexus-J 白天主题 ══ */

/* 顶部品牌装饰条 */
[data-testid="stDecoration"] {
    background-image: linear-gradient(90deg, #5B6EFF, #8B5CF6) !important;
}

/* 成功提示（已激活）— 深绿文字 + 浅薄荷底 */
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

/* Caption 中的 inline code（Key / URL 展示） */
[data-testid="stCaptionContainer"] code {
    background-color: #EFF6FF !important;
    color: #1E40AF !important;
    border-radius: 4px !important;
    padding: 1px 4px !important;
}

/* Caption 普通文字 */
[data-testid="stCaptionContainer"] p {
    color: #4B5563 !important;
}
</style>
"""


def _inject_theme() -> None:
    hour = datetime.now().hour
    st.markdown(_NIGHT_CSS if hour >= 18 else _DAY_CSS, unsafe_allow_html=True)

API_BASE = "http://localhost:8000/api/v1"

st.set_page_config(
    page_title="AgentNexus-J",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded",
)
_inject_theme()

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


def stream_chat(session_id: str, message: str):
    """同步生成器，供 st.write_stream() 消费。"""
    with httpx.stream(
        "POST",
        f"{API_BASE}/chat/stream",
        json={"session_id": session_id, "message": message},
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
                tools = "、".join(payload.get("tools", []))
                yield f"\n\n> 🔧 调用工具：{tools}...\n\n"
            elif ptype == "tool_end":
                yield "\n\n"
            elif ptype == "error":
                yield f"\n\n❌ {payload.get('message', '未知错误')}"


# ── Session state 初始化 ──────────────────────────────────────────────────────

for _k, _v in [
    ("active_session_id", None),
    ("chat_history", []),
    ("editing_config_id", None),
    ("renaming_session_id", None),
    ("selected_sp_id", None),       # 当前侧边栏选中的 system prompt id
    ("editing_sp_id", None),        # 正在编辑的 system prompt id
]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# ── 侧边栏 ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("💠 AgentNexus-J")
    st.caption("企业级多智能体协作控制台")
    st.divider()

    # ── 模型配置区 ────────────────────────────────────────────────────────────
    st.subheader("🔧 外接大模型配置")

    configs: list[dict] = api("GET", "/llm-configs/", silent=True) or []
    active_config = next((c for c in configs if c["is_active"]), None)

    # 接入新模型（始终显示在顶部）
    with st.expander("＋ 接入新模型", expanded=not bool(configs)):
        with st.form("llm_config_form", clear_on_submit=True):
            n_name = st.text_input("配置名称 *", placeholder="例：DeepSeek 生产")
            n_model = st.text_input("模型名称 *", placeholder="例：deepseek-chat")
            n_key = st.text_input("API Key *", type="password", placeholder="sk-...")
            n_url = st.text_input("API URL（可选）", placeholder="留空使用 Anthropic 官方地址")
            submitted = st.form_submit_button("💾 保存并激活", use_container_width=True, type="primary")
        if submitted:
            if not n_name or not n_model or not n_key:
                st.error("配置名称、模型名称、API Key 为必填项。")
            else:
                result = api("POST", "/llm-configs/", json={
                    "display_name": n_name, "model": n_model,
                    "api_key": n_key, "base_url": n_url or None,
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

        # 编辑表单（行内展开）
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
                result = api("PATCH", f"/llm-configs/{selected['id']}", json=payload)
                if result:
                    st.session_state.editing_config_id = None
                    st.rerun()
            if cancel:
                st.session_state.editing_config_id = None
                st.rerun()

        st.caption(
            f"Key: `{selected['api_key_masked']}`"
            + (f"  ·  `{selected['base_url']}`" if selected.get("base_url") else "")
        )

    # ── System Prompt 库 ──────────────────────────────────────────────────────
    st.divider()
    st.subheader("📋 System Prompt 库")

    sp_list: list[dict] = api("GET", "/system-prompts/", silent=True) or []

    # 新建提示词
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
            # 预览内容
            st.caption(selected_sp["content"][:120] + ("…" if len(selected_sp["content"]) > 120 else ""))

            # 编辑 / 删除
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

        # 应用到当前会话
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

    # ── 会话列表区 ────────────────────────────────────────────────────────────
    st.divider()
    st.subheader("💬 会话列表")

    if st.button("＋ 新建会话", use_container_width=True, type="primary"):
        if not active_config:
            st.error("请先配置并激活一个模型。")
        else:
            sp_id = st.session_state.get("selected_sp_id")
            result = api("POST", "/sessions/", json={
                "title": "新会话",
                "system_prompt_id": sp_id,
            })
            if result:
                st.session_state.active_session_id = result["id"]
                st.session_state.chat_history = []
                st.rerun()

    sessions: list[dict] = api("GET", "/sessions/", silent=True) or []

    # 重命名弹出框（在列表上方）
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
        col_name, col_ren, col_del = st.columns([5, 1, 1])

        with col_name:
            label = ("▶ " if is_current else "") + s["title"]
            if st.button(label, key=f"s_{s['id']}", use_container_width=True):
                st.session_state.active_session_id = s["id"]
                st.session_state.selected_sp_id = s.get("system_prompt_id")
                st.session_state.chat_history = [
                    {"role": m["role"], "content": m["content"] or ""}
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
    col_title, col_model = st.columns([6, 1])
    with col_title:
        st.subheader(session_data["title"])
        sp_ref = session_data.get("system_prompt_ref")
        if sp_ref:
            st.caption(f"📋 System Prompt：`{sp_ref['name']}`")
    with col_model:
        model_label = active_config["model"] if active_config else "未配置"
        st.caption(f"`{model_label}`")

st.divider()

# 渲染历史消息
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── 对话输入 ──────────────────────────────────────────────────────────────────

if prompt := st.chat_input("发送消息给 AgentNexus-J..."):
    if not active_config:
        st.error("请先在左侧配置并激活一个模型。")
        st.stop()

    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        reply = st.write_stream(
            stream_chat(st.session_state.active_session_id, prompt)
        )

    if reply:
        st.session_state.chat_history.append({"role": "assistant", "content": reply})
    st.rerun()
