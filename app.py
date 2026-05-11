import streamlit as st
import requests
import base64
import json

API_BASE_URL = "http://localhost:8000/api/v1"

st.set_page_config(page_title="AgentNexus-J", page_icon="🤖", layout="wide")

# ==========================================
# 🎨 注入自定义 CSS
# ==========================================
st.markdown("""
<style>
    footer {visibility: hidden;}
    [data-testid="stSidebar"] { border-right: 1px solid rgba(128, 128, 128, 0.2); }
    [data-testid="stChatMessage"] { background-color: transparent !important; }
    /* 缩小侧边栏操作按钮的间距 */
    /* 缩小侧边栏操作按钮的间距，并确保图标和文字垂直居中对齐 */
    div[data-testid="column"] { 
        display: flex; 
        align-items: center; 
        justify-content: center;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 初始化与辅助函数
# ==========================================
if "session_id" not in st.session_state: st.session_state.session_id = None
if "messages" not in st.session_state: st.session_state.messages = []
if "custom_tools" not in st.session_state: st.session_state.custom_tools = []


def refresh_messages():
    if st.session_state.session_id:
        res = requests.get(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/messages")
        if res.status_code == 200:
            st.session_state.messages = res.json()


# ==========================================
# 左侧边栏
# ==========================================
with st.sidebar:
    st.markdown("### 💠 AgentNexus-J")

    # 1. 配置区
    with st.expander("⚙️ 引擎配置 (BYOK)"):
        # ... (保留之前的 provider_tpl / user_api_key 等逻辑) ...
        provider_tpl = st.selectbox("预设模型", ["Qwen (通义千问)", "DeepSeek", "自定义"])
        default_url, default_text, default_vision = "", "", ""
        if provider_tpl == "Qwen (通义千问)":
            default_url = "https://dashscope.aliyuncs.com/compatible-mode/v1";
            default_text = "qwen-plus";
            default_vision = "qwen-vl-max"
        elif provider_tpl == "DeepSeek":
            default_url = "https://api.deepseek.com/v1";
            default_text = "deepseek-chat"
        user_base_url = st.text_input("Base URL", value=default_url)
        user_api_key = st.text_input("API Key", type="password")
        user_text_model = st.text_input("文本模型", value=default_text)
        user_vision_model = st.text_input("视觉模型", value=default_vision)

    if st.button("✨ 开启新工作流", use_container_width=True, type="primary"):
        res = requests.post(f"{API_BASE_URL}/sessions/", json={"title": "新会话", "model_provider": "byok"})
        if res.status_code == 200:
            st.session_state.session_id = res.json()["id"]
            st.session_state.messages = []
            st.rerun()

    # 2. 🕒 历史记录与管理 (修复假按钮 & 增加删除/改名)
    st.divider()
    st.markdown("🕒 **历史任务**")

    history_res = requests.get(f"{API_BASE_URL}/sessions/")
    if history_res.status_code == 200:
        for s in history_res.json():
            # 优化点 1：使用 gap="small" 收紧间距，调整比例
            col_btn, col_edit, col_del = st.columns([7.5, 1.2, 1.2], gap="small")

            with col_btn:
                is_active = (s['id'] == st.session_state.session_id)
                label = f"{'▶' if is_active else '💬'} {s['title'][:12] or '未命名'}"
                # 优化点 2：当前选中的会话用 primary 高亮
                btn_type = "primary" if is_active else "secondary"
                if st.button(label, key=f"sel_{s['id']}", use_container_width=True, type=btn_type):
                    st.session_state.session_id = s['id']
                    refresh_messages()
                    st.rerun()

            with col_edit:
                # 优化点 3：使用 type="tertiary" 彻底去掉按钮边框和背景，只保留悬浮效果
                if st.button("✏️", key=f"edit_{s['id']}", help="修改标题", type="tertiary", use_container_width=True):
                    st.session_state.rename_id = s['id']

            with col_del:
                if st.button("🗑️", key=f"del_{s['id']}", help="删除会话", type="tertiary", use_container_width=True):
                    requests.delete(f"{API_BASE_URL}/sessions/{s['id']}")
                    if st.session_state.session_id == s['id']:
                        st.session_state.session_id = None
                        st.session_state.messages = []
                    st.rerun()

    # 处理重命名弹窗逻辑
    if "rename_id" in st.session_state:
        with st.form("rename_form"):
            new_title = st.text_input("输入新标题")
            if st.form_submit_button("确定修改"):
                requests.patch(f"{API_BASE_URL}/sessions/{st.session_state.rename_id}?title={new_title}")
                del st.session_state.rename_id
                st.rerun()

# ==========================================
# 主区域
# ==========================================
if not st.session_state.session_id:
    st.info("👈 请开启新工作流或选择历史记录。")
    st.stop()

# 即使没填 Key，也要能显示历史消息
refresh_messages()
for msg in st.session_state.messages:
    if msg["role"] == "tool":
        with st.expander(f"🛠️ 执行结果: {msg.get('name')}"):
            st.code(msg["content"])
    else:
        avatar = "🧑‍💻" if msg["role"] == "user" else "✨"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

# 只有填了 Key 之后才显示输入框
if not user_api_key or not user_base_url or not user_text_model:
    st.warning("⚠️ 请先在侧边栏配置 API 引擎。")
    st.stop()

if prompt := st.chat_input("输入指令..."):
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    payload = {
        "user_input": prompt, "api_key": user_api_key, "base_url": user_base_url,
        "text_model": user_text_model, "vision_model": user_vision_model,
        "custom_tools": st.session_state.custom_tools
    }

    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Agent 思考中..."):
            res = requests.post(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/chat", json=payload)
            if res.status_code == 200:
                refresh_messages()
                st.rerun()