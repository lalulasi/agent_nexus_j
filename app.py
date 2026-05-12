import streamlit as st
import requests
import base64
import json
import os

API_BASE_URL = "http://localhost:8000/api/v1"
CONFIG_FILE = ".agent_config.json"  # 隐藏的本地配置文件
SECRET_SALT = "NexusJ2026"  # 用于轻量级加密的盐值

st.set_page_config(page_title="AgentNexus-J", page_icon="🤖", layout="wide")

# ==========================================
# 🎨 注入自定义 CSS
# ==========================================
st.markdown("""
<style>
    footer {visibility: hidden;}
    [data-testid="stSidebar"] { border-right: 1px solid rgba(128, 128, 128, 0.2); }
    [data-testid="stChatMessage"] { background-color: transparent !important; }
    /* 缩小侧边栏操作按钮的间距，并确保图标和文字垂直居中对齐 */
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
# 🌟 新增：拦截弹窗状态
if "pending_action" not in st.session_state: st.session_state.pending_action = None


# ==========================================
# 🔐 轻量级加密/解密模块 (XOR + Base64)
# ==========================================
def encrypt_key(key: str) -> str:
    if not key: return ""
    xored = "".join(chr(ord(c) ^ ord(SECRET_SALT[i % len(SECRET_SALT)])) for i, c in enumerate(key))
    return base64.b64encode(xored.encode()).decode()[::-1]


def decrypt_key(encrypted: str) -> str:
    if not encrypted: return ""
    try:
        b64_decoded = base64.b64decode(encrypted[::-1]).decode()
        return "".join(chr(ord(c) ^ ord(SECRET_SALT[i % len(SECRET_SALT)])) for i, c in enumerate(b64_decoded))
    except Exception:
        return ""


# 读取本地配置
def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for provider, details in cfg.items():
                    if "api_key" in details:
                        details["api_key"] = decrypt_key(details["api_key"])
                return cfg
        except Exception:
            pass
    return {}


# 写入本地配置
def save_config(provider_name, base_url, api_key, text_model, vision_model):
    cfg = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    cfg[provider_name] = {
        "base_url": base_url,
        "api_key": encrypt_key(api_key),
        "text_model": text_model,
        "vision_model": vision_model
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


if "user_config" not in st.session_state:
    st.session_state.user_config = load_config()


def refresh_messages():
    if st.session_state.session_id:
        res = requests.get(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/messages")
        if res.status_code == 200:
            st.session_state.messages = res.json()

        session_res = requests.get(f"{API_BASE_URL}/sessions/")
        if session_res.status_code == 200:
            all_sessions = session_res.json()
            current_session = next((s for s in all_sessions if s['id'] == st.session_state.session_id), None)
            if current_session and current_session.get("custom_tools"):
                st.session_state.custom_tools = current_session["custom_tools"]
            else:
                st.session_state.custom_tools = []


# ==========================================
# 左侧边栏
# ==========================================
with st.sidebar:
    st.markdown("### 💠 AgentNexus-J")

    # 1. 引擎配置区
    with st.expander("⚙️ 引擎配置 (BYOK)", expanded=True):
        provider_tpl = st.selectbox("预设模型", ["Qwen (通义千问)", "DeepSeek", "自定义"])
        provider_saved_cfg = st.session_state.user_config.get(provider_tpl, {})

        if provider_tpl == "Qwen (通义千问)":
            def_url = provider_saved_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            def_txt = provider_saved_cfg.get("text_model", "qwen-plus")
            def_vis = provider_saved_cfg.get("vision_model", "qwen-vl-max")
        elif provider_tpl == "DeepSeek":
            def_url = provider_saved_cfg.get("base_url", "https://api.deepseek.com/v1")
            def_txt = provider_saved_cfg.get("text_model", "deepseek-v4-flash")
            def_vis = provider_saved_cfg.get("vision_model", "")
        else:
            def_url = provider_saved_cfg.get("base_url", "")
            def_txt = provider_saved_cfg.get("text_model", "")
            def_vis = provider_saved_cfg.get("vision_model", "")

        user_base_url = st.text_input("Base URL", value=def_url)
        user_api_key = st.text_input("API Key", type="password", value=provider_saved_cfg.get("api_key", ""))
        user_text_model = st.text_input("文本模型", value=def_txt)
        user_vision_model = st.text_input("视觉模型", value=def_vis)

        if st.button("💾 保存当前引擎配置", use_container_width=True):
            save_config(provider_tpl, user_base_url, user_api_key, user_text_model, user_vision_model)
            st.session_state.user_config[provider_tpl] = {
                "base_url": user_base_url, "api_key": user_api_key,
                "text_model": user_text_model, "vision_model": user_vision_model
            }
            st.toast(f"✅ {provider_tpl} 配置已加密并保存至本地！")

    if st.button("✨ 开启新工作流", use_container_width=True, type="primary"):
        res = requests.post(f"{API_BASE_URL}/sessions/", json={"title": "新会话", "model_provider": "byok"})
        if res.status_code == 200:
            st.session_state.session_id = res.json()["id"]
            st.session_state.messages = []
            st.session_state.pending_action = None  # 清空拦截状态
            st.rerun()

    # 外部 API 插件箱
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

    # 历史记录与管理
    st.divider()
    st.markdown("🕒 **历史任务**")
    history_res = requests.get(f"{API_BASE_URL}/sessions/")
    if history_res.status_code == 200:
        for s in history_res.json():
            col_btn, col_edit, col_del = st.columns([7.5, 1.2, 1.2], gap="small")
            with col_btn:
                is_active = (s['id'] == st.session_state.session_id)
                label = f"{'▶' if is_active else '💬'} {s['title'][:12] or '未命名'}"
                btn_type = "primary" if is_active else "secondary"
                if st.button(label, key=f"sel_{s['id']}", use_container_width=True, type=btn_type):
                    st.session_state.session_id = s['id']
                    st.session_state.pending_action = None  # 切换时清空拦截状态
                    refresh_messages()
                    st.rerun()
            with col_edit:
                if st.button("✏️", key=f"edit_{s['id']}", help="修改标题", type="tertiary", use_container_width=True):
                    st.session_state.rename_id = s['id']
            with col_del:
                if st.button("🗑️", key=f"del_{s['id']}", help="删除会话", type="tertiary", use_container_width=True):
                    requests.delete(f"{API_BASE_URL}/sessions/{s['id']}")
                    if st.session_state.session_id == s['id']:
                        st.session_state.session_id = None
                        st.session_state.messages = []
                        st.session_state.pending_action = None
                    st.rerun()

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

# 显示历史消息
refresh_messages()
for msg in st.session_state.messages:
    # 🌟 针对系统汇报的伪装消息进行特殊 UI 渲染
    if msg["role"] == "user" and ("[系统汇报" in msg["content"] or "🔧" in msg["content"]):
        with st.chat_message("system", avatar="⚙️"):
            with st.expander("🛠️ 查看系统工具执行详情"):
                st.code(msg["content"], language="bash")
    elif msg["role"] == "tool": # 兼容旧数据
        with st.expander(f"🛠️ 执行结果: {msg.get('name')}"):
            st.code(msg["content"])
    else:
        # 正常的聊天消息
        avatar = "🧑‍💻" if msg["role"] == "user" else "✨"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

if not user_api_key or not user_base_url or not user_text_model:
    st.warning("⚠️ 请先在侧边栏配置 语言模型 引擎。")
    st.stop()

# ==========================================
# 🚨 Human-in-the-Loop 拦截弹窗逻辑
# ==========================================
if st.session_state.pending_action:
    # 如果有被拦截的请求，则显示授权卡片，并在最底部禁用输入框
    with st.chat_message("assistant", avatar="✨"):
        st.error("🚨 **高危操作授权请求**")
        st.markdown("Agent 申请执行以下本地终端命令，请检查命令是否安全：")

        t_name = st.session_state.pending_action.get("name")
        t_args = st.session_state.pending_action.get("args")

        # 尝试美化 JSON 显示
        try:
            formatted_args = json.dumps(json.loads(t_args), indent=2, ensure_ascii=False)
        except:
            formatted_args = t_args

        st.code(formatted_args, language="json")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("✅ 允许执行 (Approve)", type="primary", use_container_width=True):
                # 尝试解析出具体的命令文字，用于 UI 提示
                try:
                    display_cmd = json.loads(t_args).get("command", "终端命令")
                except:
                    display_cmd = "终端命令"

                payload = {
                    "action": "approve_tool",
                    "user_input": "",
                    "pending_tool_name": t_name,
                    "pending_tool_args": t_args,
                    "api_key": user_api_key, "base_url": user_base_url,
                    "text_model": user_text_model, "vision_model": user_vision_model,
                    "custom_tools": st.session_state.custom_tools
                }
                # 🌟 修改这里：动态 Spinner
                with st.spinner(f"🚀 正在执行: {display_cmd} ..."):
                    res = requests.post(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/chat", json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state.pending_action = data.get("pending_action") if data.get(
                            "status") == "requires_action" else None
                        st.rerun()

        with col2:
            if st.button("🚫 拒绝执行 (Reject)", type="secondary", use_container_width=True):
                payload = {
                    "action": "reject_tool",
                    "user_input": "",  # 🌟 补上这行！防止后端报错
                    "pending_tool_name": t_name,
                    "pending_tool_args": t_args,
                    "api_key": user_api_key, "base_url": user_base_url,
                    "text_model": user_text_model, "vision_model": user_vision_model,
                    "custom_tools": st.session_state.custom_tools
                }
                with st.spinner("发送拒绝信号并重新规划中..."):
                    res = requests.post(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/chat", json=payload)
                    if res.status_code == 200:
                        data = res.json()
                        st.session_state.pending_action = data.get("pending_action") if data.get(
                            "status") == "requires_action" else None
                        st.rerun()

# 当存在 pending_action 时，通过 disabled 属性禁用聊天输入框
prompt = st.chat_input("输入指令...", disabled=bool(st.session_state.pending_action))

if prompt:
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    payload = {
        "action": "chat",  # 🌟 显式声明为普通聊天
        "user_input": prompt, "api_key": user_api_key, "base_url": user_base_url,
        "text_model": user_text_model, "vision_model": user_vision_model,
        "custom_tools": st.session_state.custom_tools
    }
    with st.chat_message("assistant", avatar="✨"):
        with st.spinner("Agent 思考中..."):
            res = requests.post(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/chat", json=payload)
            if res.status_code == 200:
                data = res.json()
                # 检查后端是否要求拦截
                if data.get("status") == "requires_action":
                    st.session_state.pending_action = data.get("pending_action")
                else:
                    st.session_state.pending_action = None
                refresh_messages()
                st.rerun()