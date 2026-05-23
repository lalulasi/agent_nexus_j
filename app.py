import streamlit as st
import requests
import base64
import json
import os

API_BASE_URL = "http://localhost:8000/api/v1"
CONFIG_FILE = ".agent_config.json"
SECRET_SALT = "NexusJ2026"

st.set_page_config(page_title="AgentNexus-J", page_icon="🤖", layout="wide")

st.markdown("""
<style>
    footer {visibility: hidden;}
    [data-testid="stSidebar"] { border-right: 1px solid rgba(128, 128, 128, 0.2); }
    .stChatMessage { animation: fadeIn 0.5s; }
    @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 💾 状态初始化
# ==========================================
if "session_id" not in st.session_state: st.session_state.session_id = None
if "messages" not in st.session_state: st.session_state.messages = []
if "custom_tools" not in st.session_state: st.session_state.custom_tools = []
if "pending_action" not in st.session_state: st.session_state.pending_action = None
if "rename_id" not in st.session_state: st.session_state.rename_id = None
if "pending_model_install" not in st.session_state: st.session_state.pending_model_install = None
if "interrupted_payload" not in st.session_state: st.session_state.interrupted_payload = None


def encrypt_key(key: str) -> str:
    if not key: return ""
    xored = "".join(chr(ord(c) ^ ord(SECRET_SALT[i % len(SECRET_SALT)])) for i, c in enumerate(key))
    return base64.b64encode(xored.encode()).decode()[::-1]


def decrypt_key(encrypted: str) -> str:
    if not encrypted: return ""
    try:
        b64_decoded = base64.b64decode(encrypted[::-1]).decode()
        return "".join(chr(ord(c) ^ ord(SECRET_SALT[i % len(SECRET_SALT)])) for i, c in enumerate(b64_decoded))
    except:
        return ""


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                for p, d in cfg.items():
                    if "api_key" in d: d["api_key"] = decrypt_key(d["api_key"])
                return cfg
        except:
            pass
    return {
        "DeepSeek (官方)": {"base_url": "https://api.deepseek.com/v1", "api_key": "", "text_model": "deepseek-chat",
                            "vision_model": ""},
        "Qwen (通义千问)": {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "",
                            "text_model": "qwen-plus", "vision_model": ""}
    }


def save_all_configs(configs):
    to_save = {}
    for p, d in configs.items():
        to_save[p] = {"base_url": d.get("base_url", ""), "api_key": encrypt_key(d.get("api_key", "")),
                      "text_model": d.get("text_model", ""), "vision_model": d.get("vision_model", "")}
    with open(CONFIG_FILE, "w", encoding="utf-8") as f: json.dump(to_save, f)


if "user_config" not in st.session_state: st.session_state.user_config = load_config()

PERSONA_FILE = ".agent_personas.json"


def load_personas():
    if os.path.exists(PERSONA_FILE):
        try:
            with open(PERSONA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {
        "🌐 原生模式 (无预设)": "",
        "🤖 通用助手": "你是一个有用的AI助手。回答简明扼要。",
        "🐧 Linux 运维专家": "你是一个资深的服务器运维专家。尽量不闲聊，遇到问题直接输出可执行的 Bash 命令或脚本，并对高危命令做出提醒。",
        "✍️ 毒舌代码审查员": "你是一个极其挑剔的资深程序员，专门做 Code Review。请用尖锐、幽默且一针见血的语气指出用户代码里的愚蠢错误，然后给出优雅的重构方案。"
    }


def save_all_personas(personas):
    with open(PERSONA_FILE, "w", encoding="utf-8") as f: json.dump(personas, f, ensure_ascii=False, indent=2)


if "personas" not in st.session_state: st.session_state.personas = load_personas()
if "active_persona" not in st.session_state: st.session_state.active_persona = "🌐 原生模式 (无预设)"


def refresh_messages():
    if st.session_state.session_id:
        res = requests.get(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/messages")
        if res.status_code == 200: st.session_state.messages = res.json()


# ==========================================
# 🎛️ 侧边栏：配置与历史
# ==========================================
with st.sidebar:
    st.markdown("### 💠 AgentNexus-J")

    # 1. 引擎配置
    with st.expander("⚙️ 引擎配置 (BYOK)", expanded=False):
        config_keys = list(st.session_state.user_config.keys())
        if not config_keys:
            config_keys = ["默认模型"]
            st.session_state.user_config = {"默认模型": {}}

        selected_provider = st.selectbox("选择配置", config_keys + ["➕ 新增模型配置..."], label_visibility="collapsed")
        st.divider()

        if selected_provider == "➕ 新增模型配置...":
            current_name = st.text_input("给新配置起名", value="")
            p_cfg = {}
        else:
            current_name = selected_provider
            p_cfg = st.session_state.user_config.get(selected_provider, {})

        user_base_url = st.text_input("Base URL", value=p_cfg.get("base_url", ""))
        user_api_key = st.text_input("API Key", type="password", value=p_cfg.get("api_key", ""))
        user_text_model = st.text_input("文本模型", value=p_cfg.get("text_model", ""))
        user_vision_model = st.text_input("视觉模型", value=p_cfg.get("vision_model", ""))

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 保存", use_container_width=True, type="primary"):
                if not current_name.strip():
                    st.error("不能为空！")
                else:
                    st.session_state.user_config[current_name] = {"base_url": user_base_url, "api_key": user_api_key,
                                                                  "text_model": user_text_model,
                                                                  "vision_model": user_vision_model}
                    save_all_configs(st.session_state.user_config)
                    st.toast("✅ 配置已保存")
                    if selected_provider == "➕ 新增模型配置...": st.rerun()
        with col2:
            if selected_provider != "➕ 新增模型配置...":
                if st.button("🗑️ 删除", use_container_width=True):
                    del st.session_state.user_config[selected_provider]
                    save_all_configs(st.session_state.user_config)
                    st.rerun()

    # 2. 角色面具
    with st.expander("🎭 角色面具 (System Prompts)", expanded=False):
        persona_keys = list(st.session_state.personas.keys())
        if not persona_keys:
            persona_keys = ["🌐 原生模式 (无预设)"]
            st.session_state.personas = {"🌐 原生模式 (无预设)": ""}

        c_psel, c_pdel = st.columns([5, 1])
        with c_psel:
            selected_persona = st.selectbox("选择当前角色", persona_keys + ["➕ 新增角色..."],
                                            label_visibility="collapsed")
        with c_pdel:
            if selected_persona not in ["➕ 新增角色...", "🌐 原生模式 (无预设)"] and st.button("🗑️", key="del_p",
                                                                                              help="删除角色"):
                del st.session_state.personas[selected_persona]
                save_all_personas(st.session_state.personas)
                st.rerun()
        st.divider()

        if selected_persona == "🌐 原生模式 (无预设)":
            st.info("💡 当前使用大模型官方原生设定，将不会向后端发送任何系统提示词。")
            st.session_state.active_persona = selected_persona
        elif selected_persona == "➕ 新增角色...":
            p_name = st.text_input("给新角色起名", value="")
            p_content = st.text_area("System Prompt", value="", height=100)
        else:
            p_name = selected_persona
            p_content = st.text_area("System Prompt", value=st.session_state.personas.get(selected_persona, ""),
                                     height=100)
            st.session_state.active_persona = selected_persona

        if selected_persona != "🌐 原生模式 (无预设)":
            if st.button("💾 保存角色", use_container_width=True):
                if not p_name.strip():
                    st.error("角色名不能为空！")
                elif not p_content.strip():
                    st.error("Prompt 不能为空！")
                else:
                    st.session_state.personas[p_name] = p_content
                    save_all_personas(st.session_state.personas)
                    st.toast(f"✅ 角色 [{p_name}] 已保存")
                    st.session_state.active_persona = p_name
                    if selected_persona == "➕ 新增角色...": st.rerun()

    # ==========================================
    # 🛸 智能体调度中心 (Orchestration)
    # ==========================================
    st.divider()
    st.markdown("### 🛸 智能体调度中心")

    config_keys = list(st.session_state.user_config.keys())
    if not config_keys: config_keys = ["未配置模型"]

    enable_swarm = st.toggle("🌌 启用多智能体协作网络", value=False, help="开启后可同时调度多个大模型进行深度逻辑博弈。")

    swarm_mode = None
    selected_providers = []
    node_tools_map = {}

    # 初始化测试工具
    if not st.session_state.custom_tools:
        st.session_state.custom_tools = [{
            "name": "get_system_time",
            "description": "获取当前服务器的精确时间和日期",
            "parameters": {"type": "object", "properties": {}},
            "url": ""
        }]

    if not enable_swarm:
        selected_single = st.selectbox("当前主脑 (单模型极速响应)", config_keys)
        selected_providers = [selected_single]
        st.caption("ℹ️ 单机直连：适合日常对话、代码补全与基础问答。")
    else:
        st.markdown("##### ⚙️ 舰队编排")
        selected_providers = st.multiselect(
            "选择出战模型 (1~5个，首个为裁判)", config_keys, default=[config_keys[0]] if config_keys else None,
            max_selections=5
        )

        if len(selected_providers) > 1:
            swarm_mode_label = st.radio("⚔️ 选择多智能体战术阵型",
                                        ["👑 主从迭代 (Maker-Checker)", "🎪 圆桌会议 (Roundtable)"])
            swarm_mode = "maker_checker" if "主从" in swarm_mode_label else "roundtable"

            if st.session_state.custom_tools:
                with st.expander("🧰 异构工具分配 (为不同模型配置专属能力)"):
                    st.caption("让专业模型做专业的事，传递纯文本工具名称以减轻网络负担。")
                    tool_names = [t.get("name") for t in st.session_state.custom_tools if t.get("name")]
                    for i, p_name in enumerate(selected_providers):
                        default_sel = tool_names if i == 0 else []
                        selected_t_names = st.multiselect(f"[{p_name}] 的专属工具箱", options=tool_names,
                                                          default=default_sel, key=f"tool_alloc_{p_name}")
                        node_tools_map[p_name] = selected_t_names
        elif len(selected_providers) == 1:
            st.warning("⚠️ 舰队目前仅有一艘船，将自动降级为单兵模式。")
        else:
            st.error("⚠️ 请至少编排一个模型！")

    if st.button("✨ 开启新工作流", use_container_width=True, type="primary"):
        active_provider = selected_providers[0] if selected_providers else "未知模型"
        res = requests.post(f"{API_BASE_URL}/sessions/", json={"title": "新会话", "model_provider": active_provider})
        if res.status_code == 200:
            st.session_state.session_id = res.json()["id"]
            st.session_state.messages = []
            st.session_state.pending_action = None
            st.rerun()

    st.divider()
    with st.expander("📄 投喂本地文档", expanded=True):
        uploaded_file = st.file_uploader("支持 TXT/MD/LOG/PY", type=["txt", "md", "log", "py", "csv", "json"],
                                         label_visibility="collapsed")
        if uploaded_file and st.session_state.get("last_sent_file_id") != uploaded_file.file_id:
            try:
                st.session_state.file_content = uploaded_file.read().decode("utf-8")
                st.session_state.file_name = uploaded_file.name
                st.success("✅ 文件就绪")
            except:
                st.error("编码错误")
        elif not uploaded_file:
            st.session_state.file_content = None

    st.divider()
    st.markdown("🕒 **历史任务**")
    h_res = requests.get(f"{API_BASE_URL}/sessions/")
    if h_res.status_code == 200:
        for s in h_res.json():
            is_active = (s['id'] == st.session_state.session_id)
            c_main, c_edit, c_del = st.columns([6, 2, 2])
            with c_main:
                if st.button(f"{'▶' if is_active else '💬'} {s['title'][:12]}", key=f"s_{s['id']}",
                             use_container_width=True):
                    st.session_state.session_id = s['id']
                    st.session_state.pending_action = None
                    refresh_messages()
                    st.rerun()
            with c_edit:
                if st.button("✏️", key=f"edit_{s['id']}"):
                    st.session_state.rename_id = s['id']
                    st.rerun()
            with c_del:
                if st.button("🗑️", key=f"del_{s['id']}"):
                    requests.delete(f"{API_BASE_URL}/sessions/{s['id']}")
                    if is_active: st.session_state.session_id = None
                    st.rerun()

    if st.session_state.rename_id:
        new_title = st.text_input("输入新名称并回车", key="rename_input")
        if new_title:
            requests.patch(f"{API_BASE_URL}/sessions/{st.session_state.rename_id}", params={"title": new_title})
            st.session_state.rename_id = None
            st.rerun()

# ==========================================
# 💬 主界面：对话与流式渲染
# ==========================================
if not st.session_state.session_id: st.info("👈 请从左侧边栏开启新工作流。"); st.stop()

refresh_messages()
for msg in st.session_state.messages:
    if msg["role"] == "user" and ("[系统汇报" in msg["content"] or "🔧" in msg["content"]):
        with st.chat_message("system", avatar="⚙️"):
            with st.expander("🛠️ 系统工具执行详情"): st.code(msg["content"], language="bash")
    else:
        avatar = "🧑‍💻" if msg["role"] == "user" else "✨"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

# 🛑 拦截器 1：高危操作授权请求
if st.session_state.pending_action:
    with st.chat_message("assistant", avatar="✨"):
        st.error("🚨 **高危操作授权请求**")
        t_name = st.session_state.pending_action.get("name")
        t_args = st.session_state.pending_action.get("args")
        st.code(t_args, language="json")
        col1, col2 = st.columns(2)

        btn_payload = st.session_state.interrupted_payload.copy() if st.session_state.interrupted_payload else {}
        if col1.button("✅ 允许", type="primary", use_container_width=True):
            btn_payload.update({"action": "approve_tool", "pending_tool_name": t_name, "pending_tool_args": t_args})
            st.session_state.run_stream = btn_payload
            st.session_state.pending_action = None
            st.rerun()
        if col2.button("🚫 拒绝", use_container_width=True):
            btn_payload.update({"action": "reject_tool", "pending_tool_name": t_name, "pending_tool_args": t_args})
            st.session_state.run_stream = btn_payload
            st.session_state.pending_action = None
            st.rerun()

# 🛑 拦截器 2：按需加载本地模型
if st.session_state.get("pending_model_install"):
    m_name = st.session_state.pending_model_install
    with st.chat_message("assistant", avatar="⚙️"):
        st.warning(
            f"💡 **系统提示：按需加载本地神经中枢**\n\n为激活高级多智能体记忆压缩特性，系统需要挂载轻量级本地大脑 `{m_name}`。这将占用少量本地资源。")
        c1, c2 = st.columns(2)
        if c1.button("✅ 同意并自动安装 (推荐)", type="primary", use_container_width=True):
            btn_payload = st.session_state.interrupted_payload.copy()
            btn_payload["action"] = "pull_local_model"
            st.session_state.run_stream = btn_payload
            st.session_state.pending_model_install = None
            st.rerun()
        if c2.button("🚫 暂不安装 (退回)", use_container_width=True):
            st.session_state.pending_model_install = None
            st.session_state.interrupted_payload = None
            st.rerun()


def handle_streaming_request(payload):
    full_response = ""
    with st.chat_message("assistant", avatar="✨"):
        status_placeholder = st.empty()
        text_placeholder = st.empty()
        progress_bar = st.empty()

        try:
            with requests.post(f"{API_BASE_URL}/sessions/{st.session_state.session_id}/chat", json=payload,
                               stream=True) as r:
                if r.status_code != 200:
                    st.error(f"后端报错 (HTTP {r.status_code}): {r.text}")
                    return
                for line in r.iter_lines():
                    if line:
                        decoded = line.decode('utf-8')
                        if decoded.startswith('data: '):
                            data = json.loads(decoded[6:])
                            if data['type'] == 'status':
                                status_placeholder.info(f"🌀 {data['content']}")
                            elif data['type'] == 'chunk':
                                full_response += data['content']
                                text_placeholder.markdown(full_response + "▌")
                            elif data['type'] == 'requires_action':
                                st.session_state.pending_action = {"name": data['name'], "args": data['args']}
                                st.session_state.interrupted_payload = payload
                                st.rerun()
                            elif data['type'] == 'error':
                                st.error(data['content'])
                                return
                            elif data['type'] == 'requires_local_model':
                                st.session_state.pending_model_install = data['model_name']
                                st.session_state.interrupted_payload = payload
                                st.rerun()
                            elif data['type'] == 'pull_progress':
                                total = data.get('total', 1)
                                completed = data.get('completed', 0)
                                if total > 1 and completed > 0:
                                    pct = min(completed / total, 1.0)
                                    progress_bar.progress(pct,
                                                          text=f"📥 正在挂载 {data.get('status')}... {int(pct * 100)}%")
                                else:
                                    status_placeholder.info(f"⏳ {data.get('status')}...")
                            elif data['type'] == 'pull_success':
                                progress_bar.empty()
                                status_placeholder.success("✅ 本地中枢挂载完毕！正在继续执行原任务...")
                                import time;
                                time.sleep(1)
                                st.session_state.run_stream = st.session_state.interrupted_payload
                                st.rerun()

            status_placeholder.empty()
            text_placeholder.markdown(full_response)
            if uploaded_file: st.session_state.last_sent_file_id = uploaded_file.file_id
            refresh_messages()
        except Exception as e:
            st.error(f"连接异常: {e}")


if "run_stream" in st.session_state:
    p = st.session_state.pop("run_stream")
    handle_streaming_request(p)
    st.rerun()

is_disabled = bool(st.session_state.get("pending_action")) or bool(st.session_state.get("pending_model_install"))

if prompt := st.chat_input("输入指令...", disabled=is_disabled):
    if not selected_providers:
        st.error("请先在侧边栏选择至少一个模型！")
        st.stop()

    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    # 🌟 精确组装 Swarm 节点，仅传递工具名称
    swarm_nodes = []
    for p_name in selected_providers:
        cfg = st.session_state.user_config.get(p_name, {})
        if not swarm_mode:
            assigned = [t.get("name") for t in st.session_state.custom_tools if t.get("name")]
        else:
            assigned = node_tools_map.get(p_name, [])
        swarm_nodes.append({
            "provider_name": p_name,
            "api_key": cfg.get("api_key", ""),
            "base_url": cfg.get("base_url", ""),
            "text_model": cfg.get("text_model", ""),
            "assigned_tools": assigned
        })

    primary = swarm_nodes[0]
    sys_prompt_val = st.session_state.personas.get(st.session_state.active_persona, "")

    # 🌟 严丝合缝的 payload 组装，不漏任何一个参数
    payload = {
        "action": "chat",
        "user_input": prompt,
        "api_key": primary["api_key"],
        "base_url": primary["base_url"],
        "text_model": primary["text_model"],
        "vision_model": st.session_state.user_config.get(primary["provider_name"], {}).get("vision_model", ""),
        "custom_tools": st.session_state.custom_tools,  # 这里必须传完整的工具对象列表，供后端全局注册
        "file_name": st.session_state.get("file_name"),
        "file_content": st.session_state.get("file_content"),
        "system_prompt": sys_prompt_val,
        "swarm_mode": swarm_mode,
        "swarm_nodes": swarm_nodes
    }

    handle_streaming_request(payload)
    st.rerun()