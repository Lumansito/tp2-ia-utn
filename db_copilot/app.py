"""
DB Copilot -- Interfaz Streamlit (Chat, Esquema, Diagrama ER, Auditoria).
"""

import html
import os
import sys
import uuid
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db_copilot.config import get_engine, get_llm, get_embeddings
from db_copilot.schema_introspection import (
    introspect_database,
    generate_natural_language_docs,
    generate_dbml,
    generate_ddl_preview,
    generate_single_table_ddl,
    render_dbml_to_svg,
    schema_fingerprint,
)
from db_copilot.rag import index_schema_documents
from db_copilot.agent import (
    DBCopilot,
    set_agent_engine,
    approve_pending_write,
    get_pending_approvals,
    get_audit_log,
)

st.set_page_config(
    page_title="DB Copilot",
    page_icon=":material/database:",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Estilos visuales. Todo usa colores translucidos (rgba) o heredados para
# verse bien tanto con el tema claro como con el oscuro de Streamlit.
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
  --dbc-accent: #6366F1;
  --dbc-accent-2: #8B5CF6;
  --dbc-accent-3: #0891B2;
  --dbc-grad: linear-gradient(135deg, #6366F1 0%, #8B5CF6 50%, #0891B2 100%);
  --dbc-ok: #10B981;
  --dbc-warn: #F59E0B;
  --dbc-err: #EF4444;
  --dbc-border: rgba(128, 128, 128, 0.22);
  --dbc-surface: rgba(128, 128, 128, 0.06);
  --dbc-surface-2: rgba(128, 128, 128, 0.11);
  --dbc-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 10px 28px -14px rgba(0, 0, 0, 0.25);
}

/* Tipografia */
.stApp, .stApp p, .stApp li, .stApp label, .stApp input, .stApp textarea,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, [data-testid^="stBaseButton"] {
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif !important;
}
.stApp code, .stApp pre, .stApp pre * {
  font-family: 'JetBrains Mono', ui-monospace, 'Cascadia Code', monospace !important;
}
.stApp h3 { font-weight: 700; letter-spacing: -0.015em; }

[data-testid="stMainBlockContainer"] { padding-top: 2.25rem; padding-bottom: 3rem; max-width: 1440px; }

/* Hero */
.dbc-hero {
  display: flex; align-items: center; gap: 1.25rem;
  padding: 1.4rem 1.6rem; margin-bottom: 0.75rem;
  border: 1px solid var(--dbc-border); border-radius: 20px;
  background:
    radial-gradient(110% 160% at 0% 0%, rgba(99, 102, 241, 0.18), transparent 55%),
    radial-gradient(110% 160% at 100% 100%, rgba(8, 145, 178, 0.14), transparent 55%),
    var(--dbc-surface);
  box-shadow: var(--dbc-shadow);
}
.dbc-logo {
  flex: none; display: grid; place-items: center;
  width: 56px; height: 56px; border-radius: 16px;
  background: var(--dbc-grad); color: #fff;
  box-shadow: 0 12px 26px -10px rgba(99, 102, 241, 0.75);
}
.dbc-logo svg { width: 30px; height: 30px; }
.dbc-eyebrow {
  font-size: 0.7rem; font-weight: 700; letter-spacing: 0.14em;
  text-transform: uppercase; opacity: 0.6;
}
.dbc-title {
  font-size: 2.1rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1.1;
  margin: 0.1rem 0 0.3rem;
  background: var(--dbc-grad); -webkit-background-clip: text; background-clip: text; color: transparent;
}
.dbc-sub { margin: 0; font-size: 0.95rem; opacity: 0.72; }
.dbc-chips { margin-left: auto; display: flex; flex-wrap: wrap; gap: 0.5rem; justify-content: flex-end; }
.dbc-chip {
  display: inline-flex; align-items: center; gap: 0.45rem;
  padding: 0.32rem 0.75rem; border-radius: 999px;
  font-size: 0.78rem; font-weight: 500; white-space: nowrap;
  border: 1px solid var(--dbc-border); background: var(--dbc-surface-2);
}
.dbc-chip b { font-weight: 600; opacity: 0.6; }
.dbc-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dbc-ok); animation: dbc-pulse 2s infinite; }
.dbc-dot.off { background: var(--dbc-err); animation: none; box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.2); }
@keyframes dbc-pulse {
  0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.55); }
  70% { box-shadow: 0 0 0 7px rgba(16, 185, 129, 0); }
  100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
}
@media (max-width: 860px) {
  .dbc-hero { flex-wrap: wrap; }
  .dbc-chips { margin-left: 0; justify-content: flex-start; }
}

/* Sidebar */
[data-testid="stSidebar"] { border-right: 1px solid var(--dbc-border); }
[data-testid="stSidebarContent"] {
  background-image: linear-gradient(180deg, rgba(99, 102, 241, 0.10) 0%, transparent 260px);
}
.dbc-brand { display: flex; align-items: center; gap: 0.75rem; margin: -0.5rem 0 0.25rem; }
.dbc-brand .dbc-logo { width: 40px; height: 40px; border-radius: 12px; }
.dbc-brand .dbc-logo svg { width: 22px; height: 22px; }
.dbc-brand-name { font-size: 1.15rem; font-weight: 800; letter-spacing: -0.02em; line-height: 1.1; }
.dbc-brand-tag { font-size: 0.75rem; opacity: 0.6; }
.dbc-label {
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.12em;
  text-transform: uppercase; opacity: 0.55; margin-bottom: 0.15rem;
}
.st-key-sb_env, .st-key-sb_status { border-radius: 14px !important; background: var(--dbc-surface); }
.st-key-sb_env [data-testid="stMarkdownContainer"] p { margin: 0; font-size: 0.86rem; }
.st-key-sb_env code {
  color: inherit !important; background: var(--dbc-surface-2) !important;
  border-radius: 6px; padding: 0.05rem 0.4rem; font-size: 0.78rem; word-break: break-all;
}

/* Botones */
[data-testid^="stBaseButton"] {
  border-radius: 10px !important; font-weight: 500;
  transition: transform 0.12s ease, box-shadow 0.12s ease, border-color 0.12s ease, filter 0.12s ease;
}
[data-testid="stBaseButton-primary"] {
  background: var(--dbc-grad) !important; border: none !important; color: #fff !important;
  box-shadow: 0 10px 22px -12px rgba(99, 102, 241, 0.9);
}
[data-testid="stBaseButton-primary"]:hover { transform: translateY(-1px); filter: brightness(1.07); }
[data-testid="stBaseButton-secondary"]:hover { border-color: var(--dbc-accent) !important; color: var(--dbc-accent) !important; }

/* Pestañas estilo "segmented control" */
[data-testid="stTabs"] [role="tablist"] {
  gap: 0.25rem; padding: 0.3rem; width: fit-content; max-width: 100%;
  border: 1px solid var(--dbc-border); border-radius: 14px; background: var(--dbc-surface);
}
[data-testid="stTabs"] [role="tab"] {
  height: auto; padding: 0.5rem 1.05rem; border-radius: 10px; border: none;
  transition: background 0.15s ease, color 0.15s ease;
}
[data-testid="stTabs"] [role="tab"] p { font-weight: 600; font-size: 0.92rem; }
[data-testid="stTabs"] [role="tab"]:hover { background: var(--dbc-surface-2); }
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  background: var(--dbc-grad); box-shadow: 0 8px 18px -10px rgba(99, 102, 241, 0.9);
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] * { color: #fff !important; }
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none; }
[data-testid="stTabPanel"] { padding-top: 1.25rem; }

/* Selector de modo como pildoras */
.st-key-chat_mode [role="radiogroup"] { gap: 0.5rem; }
.st-key-chat_mode [role="radiogroup"] label {
  margin: 0; padding: 0.35rem 0.85rem; border-radius: 999px;
  border: 1px solid var(--dbc-border); background: var(--dbc-surface);
  transition: border-color 0.15s ease, background 0.15s ease;
}
.st-key-chat_mode [role="radiogroup"] label:has(input:checked) {
  border-color: rgba(99, 102, 241, 0.6); background: rgba(99, 102, 241, 0.12);
}

/* Chat */
[data-testid="stChatMessage"] {
  border: 1px solid var(--dbc-border); border-radius: 16px;
  padding: 1rem 1.15rem; background: var(--dbc-surface);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.13), rgba(139, 92, 246, 0.05));
  border-color: rgba(99, 102, 241, 0.32);
}
[data-testid="stChatMessageAvatarAssistant"] { background: var(--dbc-grad) !important; color: #fff !important; }
[data-testid="stChatInput"] { border-radius: 16px !important; box-shadow: var(--dbc-shadow); }
[data-testid="stChatInput"]:focus-within { box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25); }
[data-testid="stChatInputSubmitButton"]:not(:disabled) { background: var(--dbc-grad) !important; color: #fff !important; }

.dbc-empty {
  text-align: center; padding: 2.75rem 1.5rem; margin: 0.5rem 0 1rem;
  border: 1px dashed var(--dbc-border); border-radius: 18px; background: var(--dbc-surface);
}
.dbc-empty .dbc-logo { margin: 0 auto 0.9rem; width: 52px; height: 52px; }
.dbc-empty-title { font-size: 1.2rem; font-weight: 700; letter-spacing: -0.01em; }
.dbc-empty-sub { margin-top: 0.35rem; font-size: 0.92rem; opacity: 0.68; }

/* Timeline de ejecucion */
.dbc-tl { position: relative; margin: 0.25rem 0 0.5rem; }
.dbc-tl-step { position: relative; display: flex; gap: 0.8rem; padding-bottom: 0.9rem; }
.dbc-tl-step:not(:last-child)::before {
  content: ""; position: absolute; left: 5px; top: 16px; bottom: 0; width: 2px; background: var(--dbc-border);
}
.dbc-tl-dot {
  flex: none; width: 12px; height: 12px; margin-top: 4px; border-radius: 50%;
  background: var(--dbc-grad); box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.18);
}
.dbc-tl-head { display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem 0.55rem; font-size: 0.9rem; }
.dbc-tl-head b { font-weight: 600; }
.dbc-tl-head code { font-size: 0.76rem; }
.dbc-tl-dur {
  font-size: 0.72rem; font-weight: 600; padding: 0.08rem 0.5rem; border-radius: 999px;
  background: rgba(99, 102, 241, 0.13); color: var(--dbc-accent);
}
.dbc-tl-det { margin-top: 0.2rem; font-size: 0.82rem; opacity: 0.65; word-break: break-word; }

/* HITL */
.st-key-hitl_panel {
  padding: 1rem 1.25rem 1.1rem; margin-bottom: 1rem; border-radius: 18px;
  border: 1px solid rgba(245, 158, 11, 0.45);
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.12), rgba(245, 158, 11, 0.03));
}
.dbc-hitl-title { display: flex; align-items: center; gap: 0.6rem; font-size: 1.05rem; font-weight: 700; }
.dbc-hitl-title .dbc-hitl-icon {
  display: grid; place-items: center; width: 30px; height: 30px; border-radius: 9px;
  background: rgba(245, 158, 11, 0.2); color: var(--dbc-warn);
}
.dbc-hitl-title .dbc-hitl-icon svg { width: 18px; height: 18px; }
.dbc-hitl-count {
  font-size: 0.72rem; font-weight: 700; padding: 0.1rem 0.55rem; border-radius: 999px;
  background: var(--dbc-warn); color: #1f1300;
}
[class*="st-key-hitl_req_"] { border-radius: 14px !important; background: var(--dbc-surface); }

/* Tarjetas, metricas, codigo, tablas, expanders, alertas */
[class*="st-key-card_"] { border-radius: 16px !important; background: var(--dbc-surface); }
.dbc-section-label {
  display: flex; align-items: center; gap: 0.5rem;
  font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; opacity: 0.6;
}
.dbc-section-label::before { content: ""; width: 14px; height: 3px; border-radius: 3px; background: var(--dbc-grad); }
[data-testid="stMetric"] {
  position: relative; overflow: hidden; border-radius: 16px !important; background: var(--dbc-surface);
}
[data-testid="stMetric"]::before {
  content: ""; position: absolute; inset: 0 0 auto 0; height: 3px; background: var(--dbc-grad);
}
[data-testid="stMetricLabel"] p {
  font-size: 0.72rem !important; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase; opacity: 0.65;
}
[data-testid="stMetricValue"] { font-weight: 700; letter-spacing: -0.02em; }
[data-testid="stMetricIcon"] { color: var(--dbc-accent); }
[data-testid="stCode"] pre { border-radius: 12px !important; border: 1px solid var(--dbc-border); }
[data-testid="stDataFrame"] { border-radius: 12px; overflow: hidden; }
[data-testid="stExpander"] details { border-radius: 12px !important; border-color: var(--dbc-border) !important; }
[data-testid="stExpander"] summary:hover { color: var(--dbc-accent); }
[data-testid="stAlertContainer"] { border-radius: 12px !important; }

.dbc-idx-list { display: flex; flex-direction: column; gap: 0.45rem; }
.dbc-idx {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.5rem;
  padding: 0.5rem 0.7rem; border-radius: 10px;
  border: 1px solid var(--dbc-border); background: var(--dbc-surface); font-size: 0.85rem;
}
.dbc-idx code { font-size: 0.78rem; }
.dbc-idx-kind {
  font-size: 0.66rem; font-weight: 700; letter-spacing: 0.08em; padding: 0.1rem 0.45rem; border-radius: 6px;
  background: rgba(128, 128, 128, 0.16);
}
.dbc-idx-kind.unique { background: rgba(99, 102, 241, 0.16); color: var(--dbc-accent); }
.dbc-idx-cols { margin-left: auto; opacity: 0.75; }
</style>
""",
    unsafe_allow_html=True,
)

_DB_ICON_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/>'
    '<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>'
)
_CHAT_ICON_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'
)
_WARN_ICON_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>'
    '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
)


def _section_label(text: str) -> None:
    st.markdown(f'<div class="dbc-section-label">{html.escape(text)}</div>', unsafe_allow_html=True)

# Estado de sesion
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "copilot" not in st.session_state:
    st.session_state.copilot = None
if "schema_meta" not in st.session_state:
    st.session_state.schema_meta = None
if "schema_fp" not in st.session_state:
    st.session_state.schema_fp = None
if "active_engine" not in st.session_state:
    st.session_state.active_engine = None
if "init_error" not in st.session_state:
    st.session_state.init_error = None


def initialize_system(force_reindex: bool = False) -> bool:
    try:
        engine = get_engine()
        st.session_state.active_engine = engine
        set_agent_engine(engine)

        schema_arg = os.getenv("DB_SCHEMA") if engine.dialect.name == "postgresql" else None
        schema_meta = introspect_database(engine, schema=schema_arg)
        st.session_state.schema_meta = schema_meta

        fingerprint = schema_fingerprint(schema_meta)
        if force_reindex or fingerprint != st.session_state.schema_fp:
            docs = generate_natural_language_docs(schema_meta)
            embeddings = get_embeddings()
            index_schema_documents(docs, embeddings=embeddings)
            st.session_state.schema_fp = fingerprint

        llm = get_llm()
        st.session_state.copilot = DBCopilot(engine=engine, llm=llm, schema_meta=schema_meta)
        st.session_state.init_error = None
        return True
    except Exception as exc:
        st.session_state.init_error = str(exc)
        st.session_state.copilot = None
        return False


if st.session_state.copilot is None and st.session_state.init_error is None:
    with st.spinner("Conectando con la base de datos e indexando el esquema...", show_time=True):
        initialize_system()

# Barra lateral
with st.sidebar:
    st.markdown(
        f'<div class="dbc-brand"><div class="dbc-logo">{_DB_ICON_SVG}</div>'
        '<div><div class="dbc-brand-name">DB Copilot</div>'
        '<div class="dbc-brand-tag">Tu base de datos, en lenguaje natural</div></div></div>',
        unsafe_allow_html=True,
    )

    provider_active = os.getenv("LLM_PROVIDER", "").upper() or "N/A"
    model_active = os.getenv("LLM_MODEL", "N/A")
    db_url = os.getenv("DATABASE_URL", "")

    db_type = "Sin configurar"
    db_host = "-"
    db_name = "-"

    if db_url:
        if db_url.startswith("sqlite"):
            db_type = "SQLite"
            db_host = "Local File"
            db_name = db_url.split("///")[-1]
        else:
            if "postgresql" in db_url:
                db_type = "PostgreSQL"
            elif "mysql" in db_url:
                db_type = "MySQL"
            elif "oracle" in db_url:
                db_type = "Oracle"
            elif "mssql" in db_url:
                db_type = "SQL Server"
            else:
                db_type = db_url.split("://")[0].upper()

            parts = db_url.split("@")
            if len(parts) > 1:
                host_port_db = parts[1]
                if "/" in host_port_db:
                    db_host = host_port_db.split("/")[0]
                    db_name = host_port_db.split("/")[1].split("?")[0]
                else:
                    db_host = host_port_db
            else:
                db_host = "localhost"

    meta_info = st.session_state.schema_meta or {}
    server_version = meta_info.get("version", "N/A")

    # Información del Entorno
    with st.container(border=True, key="sb_env", gap="small"):
        st.markdown('<div class="dbc-label">Información del Entorno</div>', unsafe_allow_html=True)
        st.markdown(f":material/dns: **Motor:** `{db_type}`")
        st.markdown(f":material/info: **Versión:** `{server_version}`")
        st.markdown(f":material/lan: **Host:** `{db_host}`")
        st.markdown(f":material/storage: **Database:** `{db_name}`")
        st.markdown(f":material/api: **Proveedor:** `{provider_active}`")
        st.markdown(f":material/smart_toy: **Modelo:** `{model_active}`")

    # Estado del Sistema
    with st.container(border=True, key="sb_status"):
        st.markdown('<div class="dbc-label">Estado del Sistema</div>', unsafe_allow_html=True)
        if st.session_state.copilot is not None:
            st.success("Conectado e Indexado", icon=":material/check_circle:")
        else:
            st.error("Sin Inicializar", icon=":material/error:")

        if st.session_state.init_error:
            st.error(f"Error: {st.session_state.init_error}")
            if st.button("Reintentar Inicialización", icon=":material/refresh:", use_container_width=True):
                initialize_system()
                st.rerun()

        if st.session_state.copilot is not None:
            if st.button("Resincronizar Esquema", icon=":material/sync:", use_container_width=True,
                          help="Vuelve a leer el catálogo en vivo y reindexa el RAG si cambió."):
                with st.spinner("Resincronizando esquema...", show_time=True):
                    initialize_system(force_reindex=True)
                st.rerun()

# Encabezado principal
_is_online = st.session_state.copilot is not None
st.markdown(
    f'<div class="dbc-hero"><div class="dbc-logo">{_DB_ICON_SVG}</div>'
    '<div><div class="dbc-eyebrow">Asistente de datos con IA</div>'
    '<div class="dbc-title">DB Copilot</div>'
    '<p class="dbc-sub">Consultá, explorá y auditá tu base de datos conversando en lenguaje natural.</p></div>'
    '<div class="dbc-chips">'
    f'<span class="dbc-chip"><span class="dbc-dot{"" if _is_online else " off"}"></span>'
    f'{"Conectado" if _is_online else "Sin inicializar"}</span>'
    f'<span class="dbc-chip"><b>DB</b>{html.escape(db_type)}</span>'
    f'<span class="dbc-chip"><b>LLM</b>{html.escape(model_active)}</span>'
    '</div></div>',
    unsafe_allow_html=True,
)

if st.session_state.copilot is None:
    st.warning(
        "El sistema no está inicializado. Revisá `DATABASE_URL`, `LLM_PROVIDER`, `LLM_API_KEY` y `LLM_MODEL` "
        "en el `.env` y reintentá desde la barra lateral.",
        icon=":material/power_off:",
    )
    st.stop()

# Banner de aprobaciones pendientes (Human-in-the-Loop)
pending = get_pending_approvals(thread_id=st.session_state.thread_id)
if pending:
    with st.container(key="hitl_panel"):
        st.markdown(
            f'<div class="dbc-hitl-title"><span class="dbc-hitl-icon">{_WARN_ICON_SVG}</span>'
            f'Aprobaciones pendientes<span class="dbc-hitl-count">{len(pending)}</span></div>',
            unsafe_allow_html=True,
        )
        for req in pending:
            with st.container(border=True, key=f"hitl_req_{req['id']}"):
                st.code(req["sql"], language="sql")
                if req.get("warning"):
                    st.warning(req["warning"], icon=":material/report:")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Aprobar", icon=":material/check:", key=f"app_{req['id']}", type="primary", use_container_width=True):
                        msg = approve_pending_write(req["id"], approve=True, operator="Operador Streamlit")
                        st.success(msg)
                        st.rerun()
                with col2:
                    if st.button("Rechazar", icon=":material/close:", key=f"rej_{req['id']}", use_container_width=True):
                        msg = approve_pending_write(req["id"], approve=False, operator="Operador Streamlit")
                        st.info(msg)
                        st.rerun()

# Pestañas
tab_chat, tab_schema, tab_er, tab_audit = st.tabs([
    ":material/chat: Chat",
    ":material/schema: Esquema",
    ":material/account_tree: Diagrama",
    ":material/history: Auditoría"
])


def _render_timeline(timeline):
    rows = []
    for step in timeline:
        details = (
            f'<div class="dbc-tl-det">{html.escape(str(step["details"]))}</div>'
            if step.get("details") else ""
        )
        rows.append(
            '<div class="dbc-tl-step"><span class="dbc-tl-dot"></span><div>'
            f'<div class="dbc-tl-head"><b>{html.escape(str(step["phase"]))}</b>'
            f'<code>{html.escape(str(step["target"]))}</code>'
            f'<span class="dbc-tl-dur">{html.escape(str(step["duration"]))}s</span></div>'
            f'{details}</div></div>'
        )
    st.markdown(f'<div class="dbc-tl">{"".join(rows)}</div>', unsafe_allow_html=True)


with tab_chat:
    mode_label = st.radio("Modo", ["Agente SQL", "Documentación (RAG)"], horizontal=True, key="chat_mode")
    mode = "agent" if mode_label == "Agente SQL" else "schema"

    empty_state = st.empty()
    if not st.session_state.messages:
        empty_state.markdown(
            f'<div class="dbc-empty"><div class="dbc-logo">{_CHAT_ICON_SVG}</div>'
            '<div class="dbc-empty-title">¿Qué querés saber de tu base de datos?</div>'
            '<div class="dbc-empty-sub">Usá <b>Agente SQL</b> para consultar datos o '
            '<b>Documentación (RAG)</b> para entender el esquema.</div></div>',
            unsafe_allow_html=True,
        )

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                if msg.get("timeline"):
                    with st.expander("Detalle de ejecución", icon=":material/schedule:"):
                        _render_timeline(msg["timeline"])
                        if msg.get("total_duration"):
                            st.caption(f"Duración total: {msg['total_duration']}s")
                if msg.get("sql"):
                    st.code(msg["sql"], language="sql")
                st.markdown(msg["content"])
                if msg.get("dataframe") is not None:
                    st.dataframe(msg["dataframe"], use_container_width=True)
                    st.download_button(
                        "Descargar CSV", msg["dataframe"].to_csv(index=False),
                        file_name="resultado.csv", key=f"csv_hist_{i}",
                        icon=":material/download:",
                    )

    if question := st.chat_input("Preguntá algo sobre la base de datos..."):
        empty_state.empty()
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Pensando...", show_time=True):
                result = st.session_state.copilot.ask(
                    question, mode=mode, thread_id=st.session_state.thread_id
                )

            if result.get("timeline"):
                with st.expander("Detalle de ejecución", icon=":material/schedule:"):
                    _render_timeline(result["timeline"])
                    st.caption(f"Duración total: {result['total_duration']}s")

            if result.get("sql"):
                st.code(result["sql"], language="sql")

            if result.get("pending_write"):
                st.info(
                    f"Escritura pendiente de aprobación (ID `{result['pending_write']['id']}`). "
                    "Mirá el panel superior."
                )

            st.markdown(result["response"])

            df = result.get("dataframe")
            if df is not None:
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "Descargar CSV", df.to_csv(index=False),
                    file_name="resultado.csv", key=f"csv_new_{len(st.session_state.messages)}",
                    icon=":material/download:",
                )

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["response"],
            "sql": result.get("sql"),
            "dataframe": df,
            "timeline": result["timeline"],
            "total_duration": result.get("total_duration"),
        })

with tab_schema:
    st.subheader("Esquema de la base de datos", icon=":material/schema:")
    st.caption("Explorá la estructura de cada tabla, sus restricciones e índices y su definición SQL.")
    meta = st.session_state.schema_meta or {}

    tables = meta.get("tables", {})
    if not tables:
        st.info("No se detectaron tablas en el esquema configurado.", icon=":material/table_view:")
    else:
        selected_table = st.selectbox("Seleccionar Tabla", options=list(tables.keys()))
        table_meta = tables[selected_table]

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            pk_str = ", ".join(table_meta.get("primary_key", [])) or "No definida"
            st.metric("Clave Primaria", pk_str, border=True, icon=":material/key:")
        with col_m2:
            st.metric("Total Columnas", len(table_meta.get("columns", [])), border=True, icon=":material/view_column:")
        with col_m3:
            st.metric("Filas (estimadas)", table_meta.get("row_count", "N/A"), border=True, icon=":material/table_rows:")

        if table_meta.get("comment"):
            st.info(f"**Descripción:** {table_meta['comment']}", icon=":material/description:")

        col_left, col_right = st.columns([1, 1])

        with col_left:
            with st.container(border=True, key="card_structure"):
                _section_label("Estructura")

                formatted_cols = []
                pk_set = set(table_meta.get("primary_key", []))

                fk_map = {}
                for fk in table_meta.get("foreign_keys", []):
                    for orig_col, ref_col in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                        fk_map[orig_col] = f"FK → {fk['referred_table']}({ref_col})"

                for col in table_meta.get("columns", []):
                    name = col["name"]
                    col_type = col["type"]

                    constraints = []
                    if name in pk_set:
                        constraints.append("PK")
                    if name in fk_map:
                        constraints.append(fk_map[name])
                    if not col.get("nullable", True) and name not in pk_set:
                        constraints.append("NOT NULL")

                    constraint_str = " | ".join(constraints) if constraints else "-"

                    row = {
                        "Columna": name,
                        "Tipo de Dato": col_type,
                        "Restricciones": constraint_str,
                    }
                    if any(c.get("comment") for c in table_meta.get("columns", [])):
                        row["Descripción"] = col.get("comment") or "-"
                    formatted_cols.append(row)

                st.dataframe(pd.DataFrame(formatted_cols), use_container_width=True, hide_index=True)

                if table_meta.get("indexes"):
                    _section_label("Índices")
                    idx_rows = []
                    for idx in table_meta["indexes"]:
                        unique_label = "UNIQUE" if idx.get("unique") else "INDEX"
                        cols_str = ", ".join(idx.get("column_names", []))
                        idx_rows.append(
                            f'<div class="dbc-idx"><code>{html.escape(str(idx.get("name")))}</code>'
                            f'<span class="dbc-idx-kind{" unique" if idx.get("unique") else ""}">{unique_label}</span>'
                            f'<code class="dbc-idx-cols">{html.escape(cols_str)}</code></div>'
                        )
                    st.markdown(f'<div class="dbc-idx-list">{"".join(idx_rows)}</div>', unsafe_allow_html=True)

        with col_right:
            with st.container(border=True, key="card_ddl"):
                _section_label("Definición SQL")
                table_ddl = generate_single_table_ddl(selected_table, table_meta)
                st.code(table_ddl, language="sql")

        with st.expander("SQL de todo el esquema", icon=":material/code:"):
            st.code(generate_ddl_preview(meta), language="sql")

with tab_er:
    st.subheader("Diagrama Entidad-Relación", icon=":material/account_tree:")
    st.caption("Vista de las tablas y sus relaciones, generada a partir del esquema en vivo.")

    meta = st.session_state.schema_meta or {}
    if not meta.get("tables"):
        st.info("No hay información de esquema para renderizar el diagrama.", icon=":material/account_tree:")
    else:
        dbml_code = generate_dbml(meta)
        svg_diagram = render_dbml_to_svg(dbml_code)

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "Descargar DBML (.dbml)", dbml_code,
                file_name="esquema_base_de_datos.dbml", mime="text/plain", use_container_width=True,
                icon=":material/download:",
            )
        with col_dl2:
            if svg_diagram:
                st.download_button(
                    "Descargar diagrama (.svg)", svg_diagram,
                    file_name="diagrama_entidad_relacion.svg", mime="image/svg+xml", use_container_width=True,
                    icon=":material/download:",
                )

        if svg_diagram:
            # Fondo transparente para integrarse con cualquier tema; el lienzo
            # del diagrama se mantiene blanco porque el SVG se dibuja para ese fondo.
            svg_html = f"""
            <!DOCTYPE html><html><head><meta charset="utf-8">
            <style>
              html, body {{ margin:0; background:transparent; }}
              body {{ padding:6px 4px 14px; display:flex; justify-content:center; }}
              .svg-container {{ overflow:auto; max-height:750px; width:100%; text-align:center; box-sizing:border-box;
                                 border:1px solid rgba(128,128,128,.28); border-radius:16px; background-color:#fff;
                                 padding:24px; box-shadow:0 12px 32px -18px rgba(0,0,0,.45);
                                 background-image:radial-gradient(rgba(99,102,241,.14) 1px, transparent 1px);
                                 background-size:18px 18px; }}
              svg {{ max-width:100%; height:auto; }}
            </style></head>
            <body><div class="svg-container">{svg_diagram}</div></body></html>
            """
            components.html(svg_html, height=790, scrolling=True)
        else:
            st.info("No se pudo renderizar el SVG. Podés ver el código DBML abajo.", icon=":material/image_not_supported:")

        with st.expander("Ver código DBML", icon=":material/terminal:"):
            st.code(dbml_code, language="text")

with tab_audit:
    st.subheader("Registro de auditoría", icon=":material/history:")
    st.caption("Historial de operaciones registradas sobre la base de datos.")
    records = get_audit_log(thread_id=None, limit=300)
    if records:
        st.dataframe(pd.DataFrame(records), use_container_width=True)
    else:
        st.info("Todavía no hay operaciones registradas.", icon=":material/inbox:")
