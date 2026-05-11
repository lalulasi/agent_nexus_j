import streamlit as st
import requests
import base64
import json

API_BASE_URL = "http://localhost:8000/api/v1"

st.set_page_config(page_title="AgentNexus-J", page_icon="🤖", layout="wide")

# ==========================================
# 🎨 注入自定義 CSS
# ==========================================
st.markdown("""
<style>
    footer {visibility: hidden;}
    [data-testid="stSidebar"] { border-right: 1px solid rgba(128, 128, 128, 0.2); }
    [data-testid="stChatMessage"] { background-color: transparent !important; }
    /* 縮小側邊欄操作按鈕的間距，並確保圖標和文字垂直居中對齊 */
    div[data-testid="column"] { 
        display: flex; 
        align-items: center; 
        justify-content: center;
    }
    /* 插件卡片样式 */
    .tool-card {
        border: 1px solid rgba(128, 128, 128, 0.2);
        padding: 10px;
        border-radius: 8px;
        margin-bottom: 10px;
        font-size: 0.9em;
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
        # 1. 恢复聊天记录
        res = requests.get(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/messages")
        if res.status_code == 200:
            st.session_state.messages = res.json()

        # 2. 恢复该会话专属的插件箱！
        session_res = requests.get(f"{API_BASE_URL}/sessions/")
        if session_res.status_code == 200:
            all_sessions = session_res.json()
            # 找到当前正在聊的这个会话的信息
            current_session = next((s for s in all_sessions if s['id'] == st.session_state.session_id), None)

            # 如果数据库里存了 custom_tools，就恢复到前端；否则清空插件箱
            if current_session and current_session.get("custom_tools"):
                st.session_state.custom_tools = current_session["custom_tools"]
            else:
                st.session_state.custom_tools = []


# ==========================================
# 左側邊欄
# ==========================================
with st.sidebar:
    st.markdown("### 💠 AgentNexus-J")

    # 1. 引擎配置區
    with st.expander("⚙️ 引擎配置 (BYOK)"):
        provider_tpl = st.selectbox("预设模型", ["Qwen (通义千问)", "DeepSeek", "自定义"])
        default_url, default_text, default_vision = "", "", ""
        if provider_tpl == "Qwen":
            default_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
            default_text = "qwen-plus"
            default_vision = "qwen-vl-max"
        elif provider_tpl == "DeepSeek":
            default_url = "https://api.deepseek.com/v1"
            default_text = "deepseek-v4-flash"
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

    # ==========================================
    # 🚀 補回來的：外部 API 插件箱
    # ==========================================
    st.divider()
    with st.expander("🧰 外部 API 插件箱", expanded=False):
        st.caption("让大模型调用你的私有接口。")

        with st.form("add_tool_form", clear_on_submit=True):
            t_name = st.text_input("工具名称", placeholder="如: get_weather (英文)")
            t_desc = st.text_input("功能描述", placeholder="如: 获取制定城市天气")
            t_url = st.text_input("接口 URL (POST)", placeholder="http://127.0.0.1:9000/weather")

            default_schema = '{\n  "type": "object",\n  "properties": {\n    "city": {"type": "string"}\n  },\n  "required": ["city"]\n}'
            t_params = st.text_area("参数 Schema (JSON)", value=default_schema, height=150)

            if st.form_submit_button("➕ 挂载接口", use_container_width=True):
                if not t_name or not t_url:
                    st.error("名称和 URL 不能为空")
                else:
                    try:
                        parsed_params = json.loads(t_params)
                        st.session_state.custom_tools.append({
                            "name": t_name,
                            "description": t_desc,
                            "url": t_url,
                            "parameters": parsed_params
                        })
                        st.success(f"插件 {t_name} 已就绪！")
                    except json.JSONDecodeError:
                        st.error("❌ 参数 Schema 必须是合法的 JSON 格式")

        if st.session_state.custom_tools:
            st.markdown("👉 **当前已挂载的插件：**")
            for i, tool in enumerate(st.session_state.custom_tools):
                st.markdown(f"""
                <div class="tool-card">
                    <b>🔌 {tool['name']}</b><br>
                    <span style='color:gray;font-size:0.8em'>{tool['url']}</span>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"🗑️ 卸载 {tool['name']}", key=f"del_tool_{i}"):
                    st.session_state.custom_tools.pop(i)
                    st.rerun()

    # ==========================================
    # 2. 🕒 歷史記錄與管理 (保留了你截圖中的優化樣式)
    # ==========================================
    st.divider()
    st.markdown("🕒 **历史任务**")

    history_res = requests.get(f"{API_BASE_URL}/sessions/")
    if history_res.status_code == 200:
        for s in history_res.json():
            # 使用 gap="small" 收緊間距
            col_btn, col_edit, col_del = st.columns([7.5, 1.2, 1.2], gap="small")

            with col_btn:
                is_active = (s['id'] == st.session_state.session_id)
                label = f"{'▶' if is_active else '💬'} {s['title'][:12] or '未命名'}"
                btn_type = "primary" if is_active else "secondary"
                if st.button(label, key=f"sel_{s['id']}", use_container_width=True, type=btn_type):
                    st.session_state.session_id = s['id']
                    refresh_messages()
                    st.rerun()

            with col_edit:
                if st.button("✏️", key=f"edit_{s['id']}", help="修改标题", type="tertiary", use_container_width=True):
                    st.session_state.rename_id = s['id']

            with col_del:
                if st.button("🗑️", key=f"del_{s['id']}", help="刪除会话", type="tertiary", use_container_width=True):
                    requests.delete(f"{API_BASE_URL}/sessions/{s['id']}")
                    if st.session_state.session_id == s['id']:
                        st.session_state.session_id = None
                        st.session_state.messages = []
                    st.rerun()

    # 處理重命名彈窗邏輯
    if "rename_id" in st.session_state:
        with st.form("rename_form"):
            new_title = st.text_input("输入新标题")
            if st.form_submit_button("确定修改"):
                requests.patch(f"{API_BASE_URL}/sessions/{st.session_state.rename_id}?title={new_title}")
                del st.session_state.rename_id
                st.rerun()

# ==========================================
# 主區域
# ==========================================
if not st.session_state.session_id:
    st.info("👈 请开启新工作流或选择历史记录。")
    st.stop()

# 即使沒填 Key，也要能顯示歷史消息
refresh_messages()
for msg in st.session_state.messages:
    if msg["role"] == "tool":
        with st.expander(f"🛠️ 执行结果: {msg.get('name')}"):
            st.code(msg["content"])
    else:
        avatar = "🧑‍💻" if msg["role"] == "user" else "✨"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

# 只有填了 Key 之後才顯示輸入框
if not user_api_key or not user_base_url or not user_text_model:
    st.warning("⚠️ 请现在侧边栏配置 语言模型 引擎。")
    st.stop()

if prompt := st.chat_input("输入指令..."):
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    payload = {
        "user_input": prompt, "api_key": user_api_key, "base_url": user_base_url,
        "text_model": user_text_model, "vision_model": user_vision_model,
        "custom_tools": st.session_state.custom_tools
    }
    print(f"🔥 [前端發送檢查] 準備發送的自定義工具數量: {len(payload['custom_tools'])}")
    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Agent 思考中..."):
            res = requests.post(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/chat", json=payload)
            if res.status_code == 200:
                refresh_messages()
                st.rerun()