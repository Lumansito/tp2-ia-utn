"""
DB Copilot -- Interfaz Streamlit (Chat, Esquema, Diagrama ER, Auditoria).

Solo Google Gemini. El esquema se lee siempre en vivo de DATABASE_URL: no hay
carga manual de un .sql/.json ni botones que recreen o tumben el esquema de
la base (eso quedo en scripts/seed_demo.py, para correr a mano por consola).
"""

import os
import uuid

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from db_copilot.config import ConfigError, get_engine, get_llm, get_embeddings, get_embedding_model_name
from db_copilot.schema_introspection import (
    introspect_database,
    generate_natural_language_docs,
    generate_dbml,
    generate_ddl_preview,
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
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -------------------------------------------------------------------------
# Estado de sesion
# -------------------------------------------------------------------------
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
    """
    Arranca el sistema a partir de DATABASE_URL: conecta, introspecciona el
    esquema en vivo, y solo reindexa el RAG si el esquema cambio desde la
    ultima vez (comparando un fingerprint), para no gastar llamadas a la API
    de embeddings en cada recarga de la app.
    """
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
    except ConfigError as exc:
        st.session_state.init_error = str(exc)
        st.session_state.copilot = None
        return False
    except Exception as exc:
        st.session_state.init_error = f"Error inesperado al inicializar: {exc}"
        st.session_state.copilot = None
        return False


if st.session_state.copilot is None and st.session_state.init_error is None:
    initialize_system()

# -------------------------------------------------------------------------
# Barra lateral
# -------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Entorno")
    st.caption("Configuracion leida desde `.env`. Unico proveedor: Google Gemini.")

    db_url = os.getenv("DATABASE_URL", "")
    if db_url.startswith("sqlite"):
        db_type, db_host = "SQLite (local)", db_url.split("///")[-1]
    elif db_url:
        db_type = "PostgreSQL"
        db_host = db_url.split("@")[-1].split("/")[0] if "@" in db_url else "?"
    else:
        db_type, db_host = "Sin configurar", "-"

    with st.container(border=True):
        st.markdown(f"**🗄️ Motor:** `{db_type}`")
        st.caption(f"Host: `{db_host}`")
        st.markdown("**🤖 Proveedor:** `Google Gemini`")
        st.markdown(f"**🧠 Modelo:** `{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}`")
        st.markdown(f"**🧬 Embeddings:** `{get_embedding_model_name()}`")
        if st.session_state.copilot is not None:
            st.success("🟢 Sistema conectado e indexado")
        else:
            st.error("🔴 Sin inicializar")

    if st.session_state.init_error:
        st.error(st.session_state.init_error)
        if st.button("🔁 Reintentar inicializacion", use_container_width=True):
            initialize_system()
            st.rerun()

    st.markdown("---")
    st.caption(
        "Este panel no incluye acciones que modifiquen el esquema o los datos "
        "de la base (sembrado, recreacion, DDL). Eso se hace a proposito desde "
        "la consola con `scripts/seed_demo.py`, nunca desde un boton de la app."
    )
    if st.session_state.copilot is not None:
        if st.button("🔄 Resincronizar esquema", use_container_width=True,
                      help="Vuelve a leer el catalogo en vivo y reindexa el RAG si cambio."):
            with st.spinner("Resincronizando esquema..."):
                initialize_system(force_reindex=True)
            st.rerun()

st.title("🛡️ DB Copilot")
st.caption("Copiloto RAG + Agente SQL con guardrails y aprobacion humana — TP2 Sistemas Inteligentes, UTN")

if st.session_state.copilot is None:
    st.warning(
        "El sistema no esta inicializado. Revisa `DATABASE_URL` y `GOOGLE_API_KEY` "
        "en el `.env` y reintenta desde la barra lateral."
    )
    st.stop()

# -------------------------------------------------------------------------
# Banner de aprobaciones pendientes (Human-in-the-Loop)
# -------------------------------------------------------------------------
pending = get_pending_approvals(thread_id=st.session_state.thread_id)
if pending:
    st.markdown("### 🚨 Aprobaciones pendientes")
    for req in pending:
        with st.container(border=True):
            st.code(req["sql"], language="sql")
            if req.get("warning"):
                st.warning(req["warning"])
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Aprobar", key=f"app_{req['id']}", type="primary", use_container_width=True):
                    msg = approve_pending_write(req["id"], approve=True, operator="Operador Streamlit")
                    st.success(msg)
                    st.rerun()
            with col2:
                if st.button("❌ Rechazar", key=f"rej_{req['id']}", use_container_width=True):
                    msg = approve_pending_write(req["id"], approve=False, operator="Operador Streamlit")
                    st.info(msg)
                    st.rerun()

# -------------------------------------------------------------------------
# Pestanas
# -------------------------------------------------------------------------
tab_chat, tab_schema, tab_er, tab_audit = st.tabs(["💬 Chat", "📁 Esquema", "📊 Diagrama ER", "📋 Auditoria"])


def _render_timeline(timeline):
    for step in timeline:
        st.markdown(f"**{step['phase']}** — `{step['target']}` ({step['duration']}s)")
        if step.get("details"):
            st.caption(step["details"])


with tab_chat:
    mode_label = st.radio("Modo", ["Agente SQL", "Documentacion (RAG)"], horizontal=True)
    mode = "agent" if mode_label == "Agente SQL" else "schema"

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sql"):
                st.code(msg["sql"], language="sql")
            if msg.get("dataframe") is not None:
                st.dataframe(msg["dataframe"], use_container_width=True)
                st.download_button(
                    "📥 Descargar CSV", msg["dataframe"].to_csv(index=False),
                    file_name="resultado.csv", key=f"csv_hist_{i}",
                )
            if msg.get("timeline"):
                with st.expander("⏱️ Detalle de ejecucion"):
                    _render_timeline(msg["timeline"])

    if question := st.chat_input("Pregunta algo sobre la base de datos..."):
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
                result = st.session_state.copilot.ask(
                    question, mode=mode, thread_id=st.session_state.thread_id
                )
            st.markdown(result["response"])
            if result.get("sql"):
                st.code(result["sql"], language="sql")
            df = result.get("dataframe")
            if df is not None:
                st.dataframe(df, use_container_width=True)
                st.download_button(
                    "📥 Descargar CSV", df.to_csv(index=False),
                    file_name="resultado.csv", key=f"csv_new_{len(st.session_state.messages)}",
                )
            if result.get("pending_write"):
                st.info(
                    f"Escritura pendiente de aprobacion (ID `{result['pending_write']['id']}`). "
                    "Mira el panel de arriba."
                )
            with st.expander("⏱️ Detalle de ejecucion"):
                _render_timeline(result["timeline"])
                st.caption(f"Duracion total: {result['total_duration']}s")

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["response"],
            "sql": result.get("sql"),
            "dataframe": df,
            "timeline": result["timeline"],
        })

with tab_schema:
    st.subheader("📁 Esquema de la base de datos (solo lectura)")
    st.caption(
        "Se lee directamente de `DATABASE_URL`. Para consultar otra base, cambia "
        "el `.env` y usa 'Resincronizar esquema' en la barra lateral."
    )
    meta = st.session_state.schema_meta or {}
    st.markdown(f"**Motor:** {meta.get('engine', '?')} — **Version:** {meta.get('version', '?')}")

    tables = meta.get("tables", {})
    if not tables:
        st.info("No se detectaron tablas en el esquema configurado.")
    else:
        selected_table = st.selectbox("Tabla", options=list(tables.keys()))
        table_meta = tables[selected_table]

        col_meta, col_preview = st.columns([1, 2])
        with col_meta:
            if table_meta.get("comment"):
                st.info(table_meta["comment"])
            st.markdown(f"**Filas (estimadas):** `{table_meta.get('row_count', 'N/A')}`")
            st.markdown(f"**Clave primaria:** `{', '.join(table_meta.get('primary_key', [])) or 'No definida'}`")
            cols_df = pd.DataFrame(table_meta.get("columns", []))
            if not cols_df.empty:
                st.dataframe(cols_df[["name", "type", "nullable", "comment"]], use_container_width=True, height=280)
            if table_meta.get("foreign_keys"):
                st.markdown("**Claves foraneas:**")
                for fk in table_meta["foreign_keys"]:
                    st.markdown(
                        f"- `{selected_table}.{','.join(fk['constrained_columns'])}` → "
                        f"`{fk['referred_table']}.{','.join(fk['referred_columns'])}`"
                    )

        with col_preview:
            st.markdown(f"**Muestra en vivo de `{selected_table}` (10 filas):**")
            try:
                engine = st.session_state.active_engine
                dialect = engine.dialect.name
                query = (
                    f'SELECT * FROM "{selected_table}" LIMIT 10'
                    if dialect == "postgresql" else f"SELECT * FROM {selected_table} LIMIT 10"
                )
                with engine.connect() as conn:
                    sample = pd.read_sql_query(query, conn)
                st.dataframe(sample, use_container_width=True, height=320)
            except Exception as exc:
                st.error(f"No se pudo leer una muestra: {exc}")

        with st.expander("📄 Ver DDL reconstruido de todo el esquema"):
            st.code(generate_ddl_preview(meta), language="sql")

with tab_er:
    st.subheader("📊 Diagrama Entidad-Relacion (DBML)")
    st.caption("Generado dinamicamente a partir del esquema en vivo y renderizado como SVG.")

    meta = st.session_state.schema_meta or {}
    if not meta.get("tables"):
        st.info("No hay informacion de esquema para renderizar el diagrama.")
    else:
        dbml_code = generate_dbml(meta)
        svg_diagram = render_dbml_to_svg(dbml_code)

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                "📥 Descargar DBML (.dbml)", dbml_code,
                file_name="esquema_base_de_datos.dbml", mime="text/plain", use_container_width=True,
            )
        with col_dl2:
            if svg_diagram:
                st.download_button(
                    "📥 Descargar diagrama (.svg)", svg_diagram,
                    file_name="diagrama_entidad_relacion.svg", mime="image/svg+xml", use_container_width=True,
                )

        if svg_diagram:
            svg_html = f"""
            <!DOCTYPE html><html><head><meta charset="utf-8">
            <style>
              body {{ margin:0; padding:10px; background-color:#0e1117; display:flex; justify-content:center; }}
              .svg-container {{ overflow:auto; max-height:750px; width:100%; text-align:center;
                                 border:1px solid #30363d; border-radius:8px; background-color:#fff; padding:20px; }}
              svg {{ max-width:100%; height:auto; }}
            </style></head>
            <body><div class="svg-container">{svg_diagram}</div></body></html>
            """
            components.html(svg_html, height=790, scrolling=True)
        else:
            st.info("No se pudo renderizar el SVG (¿esta Node.js instalado y `npm install` corrido?). Podes ver el codigo DBML abajo.")

        with st.expander("📄 Ver codigo DBML"):
            st.code(dbml_code, language="text")
            st.markdown("💡 Podes pegar este DBML en [dbdiagram.io](https://dbdiagram.io) para editarlo o compartirlo.")

with tab_audit:
    st.subheader("📋 Registro de auditoria")
    st.caption("Incluye todas las sesiones (persistido en `data/audit.sqlite`), no solo la sesion actual.")
    records = get_audit_log(thread_id=None, limit=300)
    if records:
        st.dataframe(pd.DataFrame(records), use_container_width=True)
    else:
        st.info("Todavia no hay operaciones registradas.")
