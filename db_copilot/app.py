"""
DB Copilot -- Interfaz Streamlit (Chat, Esquema, Diagrama ER, Auditoria).
"""

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
    layout="wide",
    initial_sidebar_state="expanded",
)

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
    initialize_system()

# Barra lateral
with st.sidebar:
    st.title("DB Copilot")

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
    with st.container(border=True):
        st.markdown("**Información del Entorno**")
        st.markdown(f":material/dns: **Motor:** `{db_type}`")
        st.markdown(f":material/info: **Versión:** `{server_version}`")
        st.markdown(f":material/lan: **Host:** `{db_host}`")
        st.markdown(f":material/storage: **Database:** `{db_name}`")
        st.markdown(f":material/api: **Proveedor:** `{provider_active}`")
        st.markdown(f":material/smart_toy: **Modelo:** `{model_active}`")

    # Estado del Sistema
    with st.container(border=True):
        st.markdown("**Estado del Sistema**")
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
                with st.spinner("Resincronizando esquema..."):
                    initialize_system(force_reindex=True)
                st.rerun()

st.title("DB Copilot")

if st.session_state.copilot is None:
    st.warning(
        "El sistema no está inicializado. Revisá `DATABASE_URL`, `LLM_PROVIDER`, `LLM_API_KEY` y `LLM_MODEL` "
        "en el `.env` y reintentá desde la barra lateral."
    )
    st.stop()

# Banner de aprobaciones pendientes (Human-in-the-Loop)
pending = get_pending_approvals(thread_id=st.session_state.thread_id)
if pending:
    st.markdown("### :material/warning: Aprobaciones pendientes")
    for req in pending:
        with st.container(border=True):
            st.code(req["sql"], language="sql")
            if req.get("warning"):
                st.warning(req["warning"])
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
    for step in timeline:
        st.markdown(f"**{step['phase']}** — `{step['target']}` ({step['duration']}s)")
        if step.get("details"):
            st.caption(step["details"])


with tab_chat:
    mode_label = st.radio("Modo", ["Agente SQL", "Documentación (RAG)"], horizontal=True)
    mode = "agent" if mode_label == "Agente SQL" else "schema"

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
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)

        with st.chat_message("assistant"):
            with st.spinner("Pensando..."):
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
    meta = st.session_state.schema_meta or {}

    tables = meta.get("tables", {})
    if not tables:
        st.info("No se detectaron tablas en el esquema configurado.")
    else:
        selected_table = st.selectbox("Seleccionar Tabla", options=list(tables.keys()))
        table_meta = tables[selected_table]

        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            pk_str = ", ".join(table_meta.get("primary_key", [])) or "No definida"
            st.metric("Clave Primaria", pk_str)
        with col_m2:
            st.metric("Total Columnas", len(table_meta.get("columns", [])))
        with col_m3:
            st.metric("Filas (estimadas)", table_meta.get("row_count", "N/A"))

        if table_meta.get("comment"):
            st.info(f"**Descripción:** {table_meta['comment']}")

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.markdown(f"**Estructura:**")
            
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
                st.markdown("**Índices:**")
                for idx in table_meta["indexes"]:
                    unique_label = "UNIQUE" if idx.get("unique") else "INDEX"
                    cols_str = ", ".join(idx.get("column_names", []))
                    st.markdown(f"- `{idx.get('name')}` ({unique_label}): `{cols_str}`")

        with col_right:
            st.markdown(f"**Definición SQL:**")
            table_ddl = generate_single_table_ddl(selected_table, table_meta)
            st.code(table_ddl, language="sql")

        with st.expander("SQL de todo el esquema", icon=":material/code:"):
            st.code(generate_ddl_preview(meta), language="sql")

with tab_er:
    st.subheader("Diagrama Entidad-Relación", icon=":material/account_tree:")

    meta = st.session_state.schema_meta or {}
    if not meta.get("tables"):
        st.info("No hay información de esquema para renderizar el diagrama.")
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
            st.info("No se pudo renderizar el SVG. Podés ver el código DBML abajo.")

        with st.expander("Ver código DBML", icon=":material/terminal:"):
            st.code(dbml_code, language="text")

with tab_audit:
    st.subheader("Registro de auditoría", icon=":material/history:")
    records = get_audit_log(thread_id=None, limit=300)
    if records:
        st.dataframe(pd.DataFrame(records), use_container_width=True)
    else:
        st.info("Todavía no hay operaciones registradas.")
