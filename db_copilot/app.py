"""
Aplicación Interactiva Streamlit — DB Copilot (RAG + Agente SQL).
Toma la configuración directamente desde las variables de entorno (.env).
Permite operar en Modo Documentación (RAG) o Modo Agente SQL,
visualizar el Diagrama Entidad-Relación (DER), el DDL completo,
explorar datos en vivo y tumbar/recrear la base con un clic.
"""

import os
import sys
from pathlib import Path
from datetime import datetime
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
from sqlalchemy import text

# Asegurar que la raíz del proyecto esté en PYTHONPATH
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db_copilot.config import (
    get_engine,
    get_llm,
    get_embeddings,
    DEFAULT_POSTGRES_URL,
    SQLITE_FALLBACK_URL,
)
from db_copilot.schema_introspection import (
    introspect_database,
    parse_ddl_schema,
    parse_json_schema,
    generate_natural_language_docs,
    generate_dbml,
    render_dbml_to_svg,
)
from db_copilot.rag import (
    index_schema_documents,
    answer_schema_question,
)
from db_copilot.agent import (
    DBCopilot,
    set_agent_engine,
    approve_pending_write,
    get_pending_approvals,
    get_audit_log,
)
from db_copilot.seed_enterprise import reset_and_seed_database

# Configuración de página
st.set_page_config(
    page_title="DB Copilot — RAG & SQL Enterprise",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Inicialización de estado de sesión
if "messages" not in st.session_state:
    st.session_state.messages = []
if "schema_meta" not in st.session_state:
    st.session_state.schema_meta = None
if "schema_docs" not in st.session_state:
    st.session_state.schema_docs = []
if "copilot" not in st.session_state:
    st.session_state.copilot = None
if "active_engine" not in st.session_state:
    st.session_state.active_engine = None
if "init_error" not in st.session_state:
    st.session_state.init_error = None
if "active_schema_name" not in st.session_state:
    st.session_state.active_schema_name = "sql/complex_enterprise_schema.sql (15 Tablas Empresariales)"


def initialize_system(custom_schema_file=None, custom_format=None):
    """
    Inicializa automáticamente el motor, LLM, RAG y Agente
    usando la configuración definida en .env sin requerir interacción manual.
    """
    try:
        engine = get_engine()
        st.session_state.active_engine = engine
        set_agent_engine(engine)

        # 1. Obtener metadatos de esquema
        if custom_schema_file:
            content = custom_schema_file.read().decode("utf-8")
            if custom_format == "sql":
                schema_meta = parse_ddl_schema(content, dialect_name=engine.dialect.name)
            else:
                schema_meta = parse_json_schema(content)
        else:
            schema_meta = introspect_database(engine)

        st.session_state.schema_meta = schema_meta

        # 2. Generar documentos NLP e indexar en Chroma
        docs = generate_natural_language_docs(schema_meta)
        st.session_state.schema_docs = docs

        emb = get_embeddings()
        llm = get_llm()

        index_schema_documents(docs, embeddings=emb)
        st.session_state.copilot = DBCopilot(engine=engine, llm=llm)
        st.session_state.init_error = None
        return True
    except Exception as exc:
        st.session_state.init_error = str(exc)
        return False


# Auto-inicializar en la primera carga
if st.session_state.copilot is None and st.session_state.init_error is None:
    initialize_system()


# -------------------------------------------------------------------------
# BARRA LATERAL: Estado, Configuración y Acciones Agresivas
# -------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ Entorno y Configuración")
    st.caption("Cargado automáticamente desde `.env`")

    # Leer variables de configuración activas
    provider_active = os.getenv("LLM_PROVIDER", "AUTO").upper()
    if provider_active == "AUTO":
        provider_active = "GEMINI" if os.getenv("GOOGLE_API_KEY") else "OPENAI"

    model_active = os.getenv("GEMINI_MODEL" if provider_active == "GEMINI" else "OPENAI_MODEL", "gemini-3.6-flash" if provider_active == "GEMINI" else "gpt-4o-mini")
    db_url_active = os.getenv("DATABASE_URL", DEFAULT_POSTGRES_URL)

    # Identificar motor y host
    if db_url_active.startswith("sqlite"):
        db_type = "SQLite (Local)"
        db_host = "data/ecommerce.db"
    else:
        db_type = "PostgreSQL"
        db_host = db_url_active.split("@")[-1].split("/")[0] if "@" in db_url_active else "localhost"

    # Tarjeta de estado de configuración
    with st.container(border=True):
        st.markdown(f"**🗄️ Motor:** `{db_type}`")
        st.caption(f"Host: `{db_host}`")
        st.markdown(f"**🤖 Proveedor:** `{provider_active}`")
        st.markdown(f"**🧠 Modelo:** `{model_active}`")
        if st.session_state.copilot is not None:
            st.success("🟢 Sistema Conectado e Indexado")
        else:
            st.error("🔴 Error de Conexión")

    if st.session_state.init_error:
        st.error(f"Error: {st.session_state.init_error}")

    st.markdown("---")

    # Botón Agresivo de Reinicio y Sembrado Completo
    st.subheader("🛠️ Administración de Datos")
    st.caption("Acción demo agresiva: tumba el esquema por completo (DROP SCHEMA CASCADE) y recrea 15 tablas con datos masivos.")

    if st.button("💥 Tumbar y Recrear Base Completa", type="primary", use_container_width=True):
        with st.spinner("Tumbando esquema, recreando 15 tablas y poblando datos masivos en PostgreSQL..."):
            try:
                engine = st.session_state.active_engine or get_engine()
                reset_and_seed_database(engine, num_orders=150, verbose=False)
                initialize_system()
                st.success("¡Base de datos recreada desde cero con 15 tablas e indexada!")
                st.rerun()
            except Exception as e:
                st.error(f"Fallo al recrear base: {e}")

    if st.button("🔄 Reindexar Esquema en Chroma", use_container_width=True):
        with st.spinner("Reindexando catálogo en Chroma..."):
            initialize_system()
            st.success("¡Esquema reindexado exitosamente!")
            st.rerun()

    # Carga de esquema alternativo estático
    with st.expander("📁 Cargar Esquema Estático (.sql / .json)"):
        st.caption("Carga un DDL o JSON en lugar de introspeccionar en vivo.")
        uploaded_file = st.file_uploader("Archivo de esquema", type=["sql", "json"])
        if uploaded_file and st.button("Cargar este archivo"):
            fmt = "sql" if uploaded_file.name.endswith(".sql") else "json"
            initialize_system(custom_schema_file=uploaded_file, custom_format=fmt)
            st.success("Esquema cargado e indexado.")
            st.rerun()


# -------------------------------------------------------------------------
# PANTALLA PRINCIPAL
# -------------------------------------------------------------------------
st.title("🛡️ DB Copilot — Copiloto RAG & Agente SQL Empresarial")
st.markdown("Sistema inteligente para exploración, análisis arquitectónico y consultas SQL seguras con guardrails y separación de canal de datos.")

# Métricas superiores
if st.session_state.schema_meta:
    meta = st.session_state.schema_meta
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Motor", meta.get("engine", "N/A").upper())
    c2.metric("Versión", meta.get("version", "N/A"))
    c3.metric("Tablas en Catálogo", len(meta.get("tables", {})))
    c4.metric("Documentos RAG", len(st.session_state.schema_docs))


# -------------------------------------------------------------------------
# BANDEJA DE APROBACIONES HUMAN-IN-THE-LOOP (UPDATE / DELETE)
# -------------------------------------------------------------------------
pending_list = get_pending_approvals()
if pending_list:
    st.markdown("---")
    st.error("🚨 **Consultas de Escritura Pendientes de Aprobación Humana**")
    for req in pending_list:
        with st.container(border=True):
            col_info, col_actions = st.columns([4, 1])
            with col_info:
                st.markdown(f"**ID:** `{req['id']}` | **Tipo:** `{req['classification']}` | **Fecha:** {req['created_at']}")
                st.code(req["sql"], language="sql")
                if req.get("warning"):
                    st.warning(req["warning"])
            with col_actions:
                st.write("")
                if st.button("✅ Aprobar", key=f"app_{req['id']}", type="primary"):
                    res = approve_pending_write(req["id"], approve=True, operator="Operador Streamlit")
                    if res.get("success"):
                        st.success(f"Ejecutado. Filas afectadas: {res.get('rows_affected')}")
                        st.rerun()
                    else:
                        st.error(res.get("error"))
                if st.button("❌ Rechazar", key=f"rej_{req['id']}"):
                    approve_pending_write(req["id"], approve=False, operator="Operador Streamlit")
                    st.info("Sentencia rechazada.")
                    st.rerun()


# -------------------------------------------------------------------------
# PESTAÑAS PRINCIPALES: CHAT, DER, DDL Y AUDITORÍA
# -------------------------------------------------------------------------
st.markdown("---")

tab_chat, tab_schema_mgr, tab_er, tab_ddl, tab_audit = st.tabs([
    "💬 Chat Inteligente (RAG / SQL)",
    "📁 Carga & Gestión de Esquema SQL",
    "📊 Diagrama Entidad-Relación (DBML)",
    "📜 Script DDL & Explorador de Tablas",
    "📋 Registro de Auditoría (Audit Log)",
])

# -------------------------------------------------------------------------
# TAB 1: CHAT INTERACTIVO CON OBSERVABILIDAD Y PROFILER DE FASES
# -------------------------------------------------------------------------
with tab_chat:
    col_mode, col_metrics_summary = st.columns([2, 1])
    with col_mode:
        mode_selection = st.radio(
            "Modo de Operación:",
            options=["🤖 Modo Agente SQL (Copilot Operacional)", "📖 Modo Documentación / Esquema (RAG Puro)"],
            horizontal=True,
        )
    with col_metrics_summary:
        st.caption(f"⚡ **Esquema activo:** `{st.session_state.get('active_schema_name', 'Esquema Empresarial')}`")

    current_mode = "agent" if "Agente" in mode_selection else "schema"

    if current_mode == "schema":
        st.caption("ℹ️ **Modo Documentación (RAG)**: Responde dudas conceptuales y arquitectónicas anclándose en Chroma sin tocar la base.")
    else:
        st.caption("ℹ️ **Modo Agente SQL**: Traduce a SQL, ejecuta SELECTs mostrando DataFrames embebidos y retiene UPDATE/DELETE para confirmación humana.")

    # Mostrar historial de mensajes con Thinking y Profiler
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

            # SQL ejecutado SIEMPRE visible y destacado
            sql_text = msg.get("sql")
            if sql_text:
                st.markdown("##### 💻 Consulta SQL Ejecutada:")
                st.code(sql_text, language="sql", line_numbers=True)
            elif msg.get("role") == "assistant" and msg.get("mode") == "schema":
                st.caption("ℹ️ *Consulta en Modo Documentación / RAG (no requirió ejecutar SQL en la base).*")

            if msg.get("dataframe") is not None:
                df = msg["dataframe"]
                st.markdown("##### 📊 Registros Obtenidos de la Base de Datos:")
                st.dataframe(df, use_container_width=True)
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="📥 Descargar CSV",
                    data=csv,
                    file_name=f"resultado_query_{datetime.now().strftime('%H%M%S')}.csv",
                    mime="text/csv",
                    key=f"dl_{msg.get('id', id(msg))}",
                )

            # Pensamiento del modelo (Thinking) en historial
            if msg.get("thinking"):
                with st.expander("🧠 Razonamiento del Modelo (Thinking)"):
                    st.markdown(msg["thinking"])

            # Profiler de fases en historial
            if msg.get("timeline"):
                with st.expander(f"⏱️ Desglose de Fases y Tiempos ({msg.get('total_duration', 0)}s totales | Inicio: {msg.get('launch_time', 'N/A')} | Fin: {msg.get('finish_time', 'N/A')})"):
                    total_d = max(msg.get("total_duration", 1.0), 0.001)
                    df_hist_prof = pd.DataFrame([
                        {
                            "Fase": item["phase"],
                            "Entorno / Target": item["target"],
                            "Duración (s)": item["duration"],
                            "% Total": f"{round((item['duration'] / total_d) * 100, 1)}%",
                            "Detalle": item.get("details", "")
                        }
                        for item in msg["timeline"]
                    ])
                    st.dataframe(df_hist_prof, use_container_width=True, hide_index=True)

    # Input del chat
    if user_prompt := st.chat_input("Escribe tu consulta... (ej: '¿Cómo se relaciona order_items con products?' o 'Dame las 10 órdenes con mayor monto')"):
        st.session_state.messages.append({"role": "user", "content": user_prompt})
        with st.chat_message("user"):
            st.markdown(user_prompt)

        with st.chat_message("assistant"):
            if not st.session_state.copilot:
                st.error("El sistema no está inicializado. Revisa la conexión en `.env`.")
            else:
                launch_time = datetime.now().strftime("%H:%M:%S")
                st.caption(f"🚀 **Hora de lanzamiento:** `{launch_time}` &nbsp;|&nbsp; Monitoreando fases en tiempo real...")

                # Contenedor de progreso en vivo paso a paso
                status_widget = st.status("⏳ Procesando consulta en vivo...", expanded=True)
                step_logs = []

                def on_step(step_info):
                    step_logs.append(step_info)
                    with status_widget:
                        st.markdown(
                            f"⏱️ **`{step_info['duration']}s`** &nbsp;|&nbsp; **{step_info['phase']}** ➔ `{step_info['target']}`"
                        )
                        if step_info.get("details"):
                            st.caption(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ {step_info['details']}")
                        # Mostrar SQL en vivo apenas esté disponible
                        if step_info.get("extra", {}).get("sanitized_sql"):
                            st.code(step_info["extra"]["sanitized_sql"], language="sql")
                        elif step_info.get("extra", {}).get("corrected_sql"):
                            st.code(step_info["extra"]["corrected_sql"], language="sql")

                try:
                    result = st.session_state.copilot.ask(
                        user_prompt,
                        mode=current_mode,
                        on_step_callback=on_step
                    )
                    total_dur = result.get("total_duration", 0.0)
                    status_widget.update(
                        label=f"✅ Consulta finalizada con éxito en {total_dur}s (Inicio: {result.get('launch_time')} | Fin: {result.get('finish_time')})",
                        state="complete",
                        expanded=False
                    )
                except Exception as ask_err:
                    status_widget.update(
                        label=f"❌ Error durante el procesamiento: {ask_err}",
                        state="error",
                        expanded=True
                    )
                    st.error(f"Ocurrió un error al procesar la consulta: {ask_err}")
                    result = {
                        "response": f"Ocurrió un error al procesar la consulta: {ask_err}",
                        "dataframe": None,
                        "sql": None,
                        "timeline": step_logs,
                        "total_duration": 0.0,
                        "launch_time": launch_time,
                        "finish_time": datetime.now().strftime("%H:%M:%S")
                    }
                    total_dur = 0.0

                response_text = result.get("response", "")
                st.markdown(response_text)

                # SQL ejecutado SIEMPRE visible y destacado
                sql_executed = result.get("sql")
                if sql_executed:
                    st.markdown("##### 💻 Consulta SQL Ejecutada:")
                    st.code(sql_executed, language="sql", line_numbers=True)
                elif current_mode == "schema":
                    st.caption("ℹ️ *Consulta en Modo Documentación / RAG (no requirió ejecutar SQL en la base).*")

                df = result.get("dataframe")
                if df is not None and not df.empty:
                    st.markdown("##### 📊 Registros Obtenidos de la Base de Datos:")
                    st.dataframe(df, use_container_width=True)
                    csv = df.to_csv(index=False).encode("utf-8")
                    st.download_button(
                        label="📥 Descargar CSV",
                        data=csv,
                        file_name=f"resultado_{datetime.now().strftime('%H%M%S')}.csv",
                        mime="text/csv",
                    )

                # Visualización de Thinking si está disponible
                thinking_text = result.get("thinking")
                if thinking_text:
                    with st.expander("🧠 Ver Proceso de Razonamiento del Modelo (Thinking Process)"):
                        st.markdown(thinking_text)

                # Tabla Profiler de tiempos y fases
                timeline_data = result.get("timeline", [])
                if timeline_data:
                    with st.expander(f"⏱️ Desglose Detallado de Tiempos ({total_dur}s totales | Inicio: {result.get('launch_time')} | Fin: {result.get('finish_time')})", expanded=True):
                        total_div = max(total_dur, 0.001)
                        df_prof = pd.DataFrame([
                            {
                                "Fase": item["phase"],
                                "Entorno / Target": item["target"],
                                "Duración (segundos)": item["duration"],
                                "% del Total": f"{round((item['duration'] / total_div) * 100, 1)}%",
                                "Detalle Técnico": item.get("details", "")
                            }
                            for item in timeline_data
                        ])
                        st.dataframe(df_prof, use_container_width=True, hide_index=True)

                if result.get("pending_write"):
                    st.warning("⚠️ Operación de escritura registrada. Requiere confirmación humana en el panel superior.")
                    st.rerun()

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": response_text,
                    "dataframe": df,
                    "sql": sql_executed,
                    "timeline": timeline_data,
                    "thinking": thinking_text,
                    "total_duration": total_dur,
                    "launch_time": result.get("launch_time"),
                    "finish_time": result.get("finish_time"),
                    "mode": current_mode,
                })


# -------------------------------------------------------------------------
# TAB 2: CARGA & GESTIÓN DE ESQUEMA SQL (IMPORTACIÓN, VISOR Y RECREACIÓN)
# -------------------------------------------------------------------------
with tab_schema_mgr:
    st.subheader("📁 Carga, Inspección y Gestión de Esquema SQL")
    st.markdown("Módulo central para importar archivos DDL (`.sql`), examinar el código SQL cargado y sincronizar o recrear la base de datos y el RAG.")

    # Estado actual del esquema cargado
    col_state1, col_state2 = st.columns([1, 1])
    with col_state1:
        with st.container(border=True):
            st.markdown("### 📌 Esquema Activo en Memoria")
            schema_src = st.session_state.get("active_schema_name", "sql/complex_enterprise_schema.sql (15 Tablas)")
            st.markdown(f"**Archivo Fuente:** `{schema_src}`")
            if st.session_state.schema_meta:
                meta = st.session_state.schema_meta
                st.markdown(f"**Motor:** `{meta.get('engine', 'N/A').upper()}` &nbsp;|&nbsp; **Versión:** `{meta.get('version', 'N/A')}`")
                st.markdown(f"**Tablas:** `{len(meta.get('tables', {}))}` &nbsp;|&nbsp; **Documentos RAG:** `{len(st.session_state.schema_docs)}`")
            else:
                st.info("Sin esquema cargado")

    with col_state2:
        with st.container(border=True):
            st.markdown("### ⚡ Acciones Directas con 1 Clic")
            st.caption("Recreá la base de datos o sincronizá el catálogo RAG.")
            c_act1, c_act2 = st.columns(2)
            with c_act1:
                if st.button("💥 Recrear Base & RAG", type="primary", use_container_width=True, help="Ejecuta DROP SCHEMA CASCADE, crea las tablas y reindexa Chroma"):
                    with st.spinner("Recreando esquema completo y reindexando en Chroma..."):
                        try:
                            eng = st.session_state.active_engine or get_engine()
                            reset_and_seed_database(eng, num_orders=150, verbose=False)
                            initialize_system()
                            st.session_state.active_schema_name = "sql/complex_enterprise_schema.sql (15 Tablas)"
                            st.success("¡Base de datos recreada desde cero e indexada!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Fallo al recrear base: {e}")
            with c_act2:
                if st.button("🔄 Sincronizar solo RAG", use_container_width=True, help="Re-inspecciona el catálogo vivo e indexa en Chroma"):
                    with st.spinner("Reindexando catálogo en Chroma..."):
                        initialize_system()
                        st.success("¡RAG sincronizado exitosamente!")
                        st.rerun()

    st.markdown("---")

    # Importador y Presets de Esquema SQL
    st.markdown("### 📂 Seleccionar Esquema Predefinido o Subir Archivo SQL")

    schema_choice = st.radio(
        "Seleccioná la fuente del esquema DDL:",
        options=[
            "🏢 Esquema Empresarial Complejo (15 Tablas: ERP, Logística, Clientes, Facturación)",
            "🛒 Esquema E-commerce Sintético Básico (4 Tablas: Customers, Products, Orders, Items)",
            "📤 Subir Archivo SQL Personalizado (.sql)"
        ],
        horizontal=False
    )

    active_sql_content = ""
    active_filename = ""

    if "15 Tablas" in schema_choice:
        p = PROJECT_ROOT / "sql" / "complex_enterprise_schema.sql"
        if p.exists():
            active_sql_content = p.read_text(encoding="utf-8")
            active_filename = "complex_enterprise_schema.sql"
    elif "4 Tablas" in schema_choice:
        p = PROJECT_ROOT / "sql" / "schema_seed.sql"
        if p.exists():
            active_sql_content = p.read_text(encoding="utf-8")
            active_filename = "schema_seed.sql"
    else:
        uploaded_sql = st.file_uploader("Arrastrá o seleccioná tu archivo SQL DDL (.sql):", type=["sql"])
        if uploaded_sql:
            active_sql_content = uploaded_sql.read().decode("utf-8")
            active_filename = uploaded_sql.name

    if active_sql_content:
        st.markdown(f"**Archivo seleccionado:** `{active_filename}` ({len(active_sql_content.splitlines())} líneas)")

        col_btn1, col_btn2, col_btn3 = st.columns([1.5, 1.5, 1])
        with col_btn1:
            if st.button(f"🚀 Aplicar `{active_filename}` a la Base y RAG", type="primary", use_container_width=True):
                with st.spinner(f"Aplicando {active_filename} a la base de datos..."):
                    try:
                        eng = st.session_state.active_engine or get_engine()
                        with eng.begin() as conn:
                            for statement in active_sql_content.split(";"):
                                stmt_clean = statement.strip()
                                if stmt_clean:
                                    conn.execute(text(stmt_clean))
                        st.session_state.active_schema_name = active_filename
                        initialize_system()
                        st.success(f"¡Esquema '{active_filename}' aplicado exitosamente a la base de datos y RAG!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al ejecutar DDL: {e}")

        with col_btn2:
            if st.button(f"🔍 Cargar solo en RAG (Modo Documentación)", use_container_width=True):
                with st.spinner(f"Indexando metadatos de {active_filename} en Chroma..."):
                    try:
                        import io
                        mock_file = io.BytesIO(active_sql_content.encode("utf-8"))
                        st.session_state.active_schema_name = f"{active_filename} (Solo RAG)"
                        initialize_system(custom_schema_file=mock_file, custom_format="sql")
                        st.success(f"¡Esquema '{active_filename}' indexado en RAG (Modo Documentación)!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al indexar en RAG: {e}")

        with col_btn3:
            st.download_button(
                label="📥 Descargar este SQL",
                data=active_sql_content,
                file_name=active_filename or "schema.sql",
                mime="text/sql",
                use_container_width=True
            )

        # Visor de Código SQL Activo
        with st.container(border=True):
            st.markdown(f"#### 📄 Visor del Script DDL (`{active_filename}`)")
            st.code(active_sql_content, language="sql", line_numbers=True)
    else:
        st.info("Subí un archivo .sql o seleccioná uno de los esquemas predefinidos arriba para inspeccionarlo.")


# -------------------------------------------------------------------------
# TAB 2: DIAGRAMA ENTIDAD-RELACIÓN (DBML / DER)
# -------------------------------------------------------------------------
with tab_er:
    st.subheader("📊 Diagrama Entidad-Relación en DBML")
    st.caption("Generado dinámicamente en formato estándar DBML (Database Markup Language) y renderizado como gráfico vectorial interactivo.")

    if st.session_state.schema_meta:
        dbml_code = generate_dbml(st.session_state.schema_meta)
        svg_diagram = render_dbml_to_svg(dbml_code)

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                label="📥 Descargar Especificación DBML (.dbml)",
                data=dbml_code,
                file_name="esquema_base_de_datos.dbml",
                mime="text/plain",
                use_container_width=True,
            )
        with col_dl2:
            if svg_diagram:
                st.download_button(
                    label="📥 Descargar Diagrama en SVG (.svg)",
                    data=svg_diagram,
                    file_name="diagrama_entidad_relacion.svg",
                    mime="image/svg+xml",
                    use_container_width=True,
                )

        if svg_diagram:
            # Embeber SVG en un contenedor responsivo con fondo claro para legibilidad óptima de tablas y textos
            svg_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
              <meta charset="utf-8">
              <style>
                body {{
                  margin: 0;
                  padding: 10px;
                  background-color: #0e1117;
                  display: flex;
                  justify-content: center;
                }}
                .svg-container {{
                  overflow: auto;
                  max-height: 750px;
                  width: 100%;
                  text-align: center;
                  border: 1px solid #30363d;
                  border-radius: 8px;
                  background-color: #ffffff;
                  padding: 20px;
                }}
                svg {{
                  max-width: 100%;
                  height: auto;
                }}
              </style>
            </head>
            <body>
              <div class="svg-container">
                {svg_diagram}
              </div>
            </body>
            </html>
            """
            components.html(svg_html, height=790, scrolling=True)
        else:
            st.info("Generando vista previa del diagrama...")

        with st.expander("📄 Ver y Copiar Código Fuente DBML"):
            st.code(dbml_code, language="sql")
            st.markdown("💡 Podés copiar este código DBML y pegarlo en [dbdiagram.io](https://dbdiagram.io) para editarlo o compartirlo en la nube.")
    else:
        st.info("No hay información de esquema para renderizar el diagrama.")


# -------------------------------------------------------------------------
# TAB 3: SCRIPT DDL COMPLETO Y EXPLORADOR DE TABLAS
# -------------------------------------------------------------------------
with tab_ddl:
    st.subheader("📜 Definición DDL y Explorador de Tablas en Vivo")

    ddl_file_path = PROJECT_ROOT / "sql" / "complex_enterprise_schema.sql"
    if ddl_file_path.exists():
        ddl_text = ddl_file_path.read_text(encoding="utf-8")
        st.download_button(
            label="📥 Descargar Script DDL (.sql)",
            data=ddl_text,
            file_name="esquema_empresarial_complejo.sql",
            mime="text/sql",
        )
        with st.expander("📄 Ver Script SQL DDL Completo (15 Tablas)", expanded=False):
            st.code(ddl_text, language="sql", line_numbers=True)

    # Explorador interactivo por tabla
    if st.session_state.schema_meta:
        tables_dict = st.session_state.schema_meta.get("tables", {})
        if tables_dict:
            st.markdown("### 🔎 Explorador de Tablas y Datos en Vivo")
            selected_table = st.selectbox("Selecciona una tabla para inspeccionar:", options=list(tables_dict.keys()))

            if selected_table:
                t_info = tables_dict[selected_table]
                col_meta, col_preview = st.columns([1, 2])

                with col_meta:
                    st.markdown(f"**Tabla:** `{selected_table}`")
                    st.markdown(f"**Total Filas:** `{t_info.get('row_count', 'N/A')}`")
                    st.markdown(f"**Clave Primaria:** `{', '.join(t_info.get('primary_key', [])) or 'No definida'}`")

                    # Columnas
                    df_cols = pd.DataFrame(t_info.get("columns", []))
                    if not df_cols.empty:
                        st.dataframe(df_cols[["name", "type", "nullable"]], use_container_width=True, height=250)

                with col_preview:
                    st.markdown(f"**Primeros 10 registros en vivo de `{selected_table}`:**")
                    try:
                        eng = st.session_state.active_engine or get_engine()
                        with eng.connect() as conn:
                            q = f'SELECT * FROM "{selected_table}" LIMIT 10' if eng.dialect.name == "postgresql" else f'SELECT * FROM {selected_table} LIMIT 10'
                            df_sample = pd.read_sql_query(text(q), conn)
                        st.dataframe(df_sample, use_container_width=True, height=280)
                    except Exception as e:
                        st.error(f"Error al leer muestra de datos: {e}")


# -------------------------------------------------------------------------
# TAB 4: AUDIT LOG
# -------------------------------------------------------------------------
with tab_audit:
    st.subheader("📋 Registro de Operaciones y Decisiones (Audit Log)")
    audit_data = get_audit_log()
    if audit_data:
        df_audit = pd.DataFrame(audit_data)
        st.dataframe(df_audit, use_container_width=True)
    else:
        st.info("Aún no se registraron operaciones de base de datos en esta sesión.")
