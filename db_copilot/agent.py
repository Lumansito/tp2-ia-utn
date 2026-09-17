"""
Módulo del Agente SQL y Orquestador LangGraph (agent.py).
Implementa las herramientas @tool con guardrails, separación del canal de datos
(DataFrames a la UI, síntesis al LLM), Human-In-The-Loop para escrituras (UPDATE/DELETE),
y el controlador de doble modo: Modo Esquema (RAG) vs Modo Agente SQL.
"""

import uuid
import time
import re
from datetime import datetime
from typing import Dict, Any, Optional, List, Literal, Callable
import pandas as pd
from sqlalchemy import text, Engine
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

from db_copilot.config import get_engine, get_llm, SQLITE_FALLBACK_URL
from db_copilot.sql_guard import validate_and_classify_sql
from db_copilot.rag import retrieve_schema_context, answer_schema_question

# Almacén de contexto en memoria para la sesión activa
_context_store = {
    "engine": None,
    "last_dataframe": None,
    "last_sql": None,
    "pending_write": None,
}

# Cola de aprobación humana y registro de auditoría (Audit Logging)
_pending_writes: Dict[str, Dict[str, Any]] = {}
_audit_log: List[Dict[str, Any]] = []


def set_agent_engine(engine: Engine):
    """Establece el motor de base de datos para la ejecución de herramientas."""
    _context_store["engine"] = engine


def get_agent_engine() -> Engine:
    """Obtiene el motor configurado o recurre al fallback local."""
    if _context_store["engine"] is None:
        _context_store["engine"] = get_engine(SQLITE_FALLBACK_URL)
    return _context_store["engine"]


def get_last_dataframe() -> Optional[pd.DataFrame]:
    """Retorna el DataFrame generado por la última llamada a run_select."""
    return _context_store.get("last_dataframe")


def get_pending_approvals() -> List[Dict[str, Any]]:
    """Lista las consultas pendientes de revisión humana."""
    return [item for item in _pending_writes.values() if item["status"] == "PENDING"]


def get_audit_log() -> List[Dict[str, Any]]:
    """Retorna el registro completo de auditoría de sentencias ejecutadas y revisadas."""
    return list(_audit_log)


# -------------------------------------------------------------------------
# Herramientas del Agente (@tool)
# -------------------------------------------------------------------------

@tool
def retrieve_schema(query: str) -> str:
    """
    Busca información relevante del esquema de la base de datos (tablas, columnas, tipos de datos, claves foráneas e índices).
    DEBES invocar esta herramienta ANTES de generar cualquier consulta SQL para anclarte a la estructura real y no alucinar columnas.
    """
    return retrieve_schema_context(query, k=3)


@tool
def run_select(sql: str) -> str:
    """
    Valida y ejecuta una consulta de solo lectura SELECT contra la base de datos.
    Solo admite una única sentencia SELECT (agrega LIMIT de seguridad automático si falta).
    Devuelve un resumen técnico del resultado; el conjunto de datos completo (DataFrame)
    se redirige al canal de presentación visual del usuario.
    """
    engine = get_agent_engine()
    dialect = "postgres" if engine.dialect.name == "postgresql" else "sqlite"
    validation = validate_and_classify_sql(sql, default_limit=500, dialect=dialect)

    if not validation["is_valid"] or validation["classification"] != "SELECT":
        error_msg = validation.get("error") or f"Sentencia no autorizada para lectura. Clasificación: {validation['classification']}"
        _audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "sql": sql,
            "classification": validation["classification"],
            "status": "BLOCKED",
            "reason": error_msg,
        })
        return f"ERROR DE GUARDRAIL: {error_msg}"

    sanitized_sql = validation["sanitized_sql"]
    try:
        with engine.connect() as conn:
            df = pd.read_sql_query(text(sanitized_sql), conn)

        _context_store["last_dataframe"] = df
        _context_store["last_sql"] = sanitized_sql

        _audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "sql": sanitized_sql,
            "classification": "SELECT",
            "status": "EXECUTED",
            "rows": len(df),
        })

        # Resumen conciso para el LLM (separación del canal de datos vs texto)
        cols_summary = ", ".join(df.columns.tolist())
        head_sample = df.head(2).to_dict(orient="records") if len(df) > 0 else []
        return (
            f"Consulta ejecutada con éxito.\n"
            f"- Filas obtenidas: {len(df)}\n"
            f"- Columnas: [{cols_summary}]\n"
            f"- Muestra inicial (2 filas): {head_sample}\n"
            f"(Nota: Las filas completas han sido enviadas directamente como DataFrame a la interfaz interactiva. "
            f"Genera un resumen breve de 1 o 2 líneas de estos hallazgos; NO listes todas las filas en tu respuesta)."
        )
    except Exception as exc:
        return f"ERROR AL EJECUTAR SQL: {exc}"


@tool
def run_write(sql: str) -> str:
    """
    Propone una modificación en la base de datos mediante sentencias UPDATE o DELETE.
    NUNCA se ejecuta de forma directa: queda en estado PENDIENTE DE APROBACIÓN HUMANA
    para que el operador confirme o rechace la acción de manera explícita.
    """
    engine = get_agent_engine()
    dialect = "postgres" if engine.dialect.name == "postgresql" else "sqlite"
    validation = validate_and_classify_sql(sql, dialect=dialect)

    if not validation["is_valid"] or validation["classification"] != "WRITE":
        error_msg = validation.get("error") or f"Operación no permitida: {validation['classification']}"
        _audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "sql": sql,
            "classification": validation["classification"],
            "status": "BLOCKED",
            "reason": error_msg,
        })
        return f"ERROR DE GUARDRAIL: {error_msg}"

    action_id = str(uuid.uuid4())[:8]
    sanitized_sql = validation["sanitized_sql"]
    warning = validation.get("warning")

    req_data = {
        "id": action_id,
        "sql": sanitized_sql,
        "classification": "WRITE",
        "status": "PENDING",
        "warning": warning,
        "created_at": datetime.now().isoformat(),
    }
    _pending_writes[action_id] = req_data
    _context_store["pending_write"] = req_data

    _audit_log.append({
        "timestamp": datetime.now().isoformat(),
        "action_id": action_id,
        "sql": sanitized_sql,
        "classification": "WRITE",
        "status": "PENDING_APPROVAL",
        "warning": warning,
    })

    warn_text = f"\nAdvertencia: {warning}" if warning else ""
    return (
        f"SOLICITUD DE ESCRITURA REGISTRADA [ID: {action_id}]:\n"
        f"Sentencia propuesta: {sanitized_sql}{warn_text}\n"
        f"ESTADO: PENDIENTE DE APROBACIÓN HUMANA. No se impactará en la base hasta que un operador la apruebe."
    )


def approve_pending_write(
    action_id: str,
    approve: bool,
    operator: str = "Operador Humano"
) -> Dict[str, Any]:
    """
    Ejecuta o rechaza una consulta UPDATE/DELETE previamente retenida en la cola de aprobación.
    """
    if action_id not in _pending_writes:
        return {"success": False, "error": f"No existe la solicitud con ID '{action_id}'."}

    item = _pending_writes[action_id]
    if item["status"] != "PENDING":
        return {"success": False, "error": f"La solicitud '{action_id}' ya fue procesada ({item['status']})."}

    if not approve:
        item["status"] = "REJECTED"
        item["resolved_at"] = datetime.now().isoformat()
        item["resolved_by"] = operator
        _audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "action_id": action_id,
            "sql": item["sql"],
            "status": "REJECTED_BY_USER",
            "operator": operator,
        })
        return {
            "success": True,
            "action_id": action_id,
            "status": "REJECTED",
            "message": f"La sentencia con ID '{action_id}' fue RECHAZADA por {operator}. No se modificó la base de datos.",
        }

    # Si fue aprobada, procedemos a ejecutarla
    engine = get_agent_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(text(item["sql"]))
            rows_affected = result.rowcount

        item["status"] = "EXECUTED"
        item["rows_affected"] = rows_affected
        item["resolved_at"] = datetime.now().isoformat()
        item["resolved_by"] = operator

        _audit_log.append({
            "timestamp": datetime.now().isoformat(),
            "action_id": action_id,
            "sql": item["sql"],
            "status": "APPROVED_AND_EXECUTED",
            "rows_affected": rows_affected,
            "operator": operator,
        })
        return {
            "success": True,
            "action_id": action_id,
            "status": "EXECUTED",
            "rows_affected": rows_affected,
            "message": f"Sentencia '{action_id}' APROBADA y ejecutada exitosamente. Filas afectadas: {rows_affected}.",
        }
    except Exception as exc:
        item["status"] = "FAILED"
        item["error"] = str(exc)
        return {"success": False, "error": f"Fallo al ejecutar la sentencia aprobada: {exc}"}


# -------------------------------------------------------------------------
# Orquestador del Copiloto (Doble Modo: RAG Esquema vs Agente SQL)
# -------------------------------------------------------------------------

SYSTEM_PROMPT = """Eres "DB Copilot", un asistente inteligente de ingeniería de datos y consultas SQL.
Tu objetivo es ayudar a los usuarios a consultar e interactuar con la base de datos relacional de manera segura y eficiente.

REGLAS DE OPERACIÓN OBLIGATORIAS:
1. ANTES de escribir cualquier consulta SQL, usa SIEMPRE la herramienta `retrieve_schema` para verificar los nombres exactos de tablas, columnas, tipos y relaciones. No inventes columnas.
2. Si el usuario pide leer datos, genera una única sentencia SELECT y ejecútala con `run_select`.
3. Si el usuario pide actualizar o borrar datos, genera un UPDATE o DELETE y proponlo con `run_write`. Explica que quedará pendiente de su confirmación.
4. NUNCA intentes ejecutar sentencias múltiples encadenadas con punto y coma (;) ni sentencias destructivas DDL (DROP, ALTER, TRUNCATE).
5. Cuando `run_select` devuelva resultados, NO transcribas todas las filas en tu mensaje de texto. El sistema ya envía el DataFrame completo a la pantalla del usuario. Tu respuesta conversacional debe limitarse a un resumen conciso de 1 o 2 líneas destacando los totales o aspectos principales.
6. Comunícate en español claro y profesional.
"""


def execute_copilot_step_by_step(
    query: str,
    engine: Engine,
    llm,
    on_step_callback: Optional[Callable[[Dict[str, Any]], None]] = None
) -> Dict[str, Any]:
    """
    Ejecuta la consulta dividida en fases observables, midiendo tiempos segundo a segundo,
    capturando el thinking del modelo y evitando llamadas redundantes a la API.
    """
    timeline = []
    start_all = time.perf_counter()
    launch_time = datetime.now().strftime("%H:%M:%S")

    def record_step(phase_name: str, target: str, duration: float, details: str = "", extra: dict = None):
        step_info = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "phase": phase_name,
            "target": target,
            "duration": round(duration, 3),
            "details": details,
            "extra": extra or {}
        }
        timeline.append(step_info)
        if on_step_callback:
            try:
                on_step_callback(step_info)
            except Exception:
                pass
        return step_info

    # -------------------------------------------------------------
    # FASE 1: RAG Local en Chroma (Recuperación de tablas y claves)
    # -------------------------------------------------------------
    t0 = time.perf_counter()
    schema_context = retrieve_schema_context(query, k=4)
    dt_rag = time.perf_counter() - t0
    record_step(
        phase_name="Recuperación RAG de Esquema",
        target="RAG Local (Chroma Vector Store)",
        duration=dt_rag,
        details="Recuperando metadatos de tablas, tipos y relaciones foráneas relevantes."
    )

    # -------------------------------------------------------------
    # FASE 2: Llamada al LLM (Generación de SQL con Thinking)
    # -------------------------------------------------------------
    prompt = f"""Eres un ingeniero de datos experto. Basándote en el siguiente esquema relacional de la base de datos:
---
{schema_context}
---

El usuario solicita: "{query}"

Instrucciones:
1. Si la petición requiere consultar datos, genera una única sentencia SELECT válida y segura.
2. Si requiere modificar datos, genera una única sentencia UPDATE o DELETE.
3. Si es solo una pregunta conceptual o de esquema (sin datos), responde directamente explicando la arquitectura.

Escribe tu respuesta con este formato exacto:
TIPO: SELECT | WRITE | CONCEPTUAL
SQL: <sentencia sql aquí o NINGUNO si es conceptual>
EXPLICACION: <breve explicación en 1 o 2 líneas>
"""

    t1 = time.perf_counter()
    provider_name = "Google Gemini" if "Google" in type(llm).__name__ else "OpenAI GPT"
    model_name = getattr(llm, "model", getattr(llm, "model_name", "Desconocido"))
    
    try:
        llm_response = llm.invoke(prompt)
    except Exception as exc:
        err_str = str(exc)
        if "429" in err_str or "503" in err_str or "RESOURCE_EXHAUSTED" in err_str or "UNAVAILABLE" in err_str:
            # Fallback transparente a gemini-3.5-flash-lite
            fallback_llm = get_llm(model_name="gemini-3.5-flash-lite")
            llm_response = fallback_llm.invoke(prompt)
            provider_name = f"{provider_name} (Fallback automático)"
        else:
            raise exc

    dt_llm1 = time.perf_counter() - t1

    # Extraer thinking si viene en la respuesta de Gemini / OpenAI
    thinking_text = ""
    raw_content = ""
    if isinstance(llm_response.content, list):
        for part in llm_response.content:
            if isinstance(part, dict):
                if part.get("type") in ("thinking", "reasoning"):
                    thinking_text += part.get("thinking", part.get("reasoning", ""))
                elif part.get("type") == "text":
                    raw_content += part.get("text", "")
            else:
                raw_content += str(part)
    else:
        raw_content = str(llm_response.content)

    record_step(
        phase_name="Generación de SQL y Razonamiento",
        target=f"API Cloud: {provider_name} ({model_name})",
        duration=dt_llm1,
        details="El modelo analizó el esquema RAG y determinó la sentencia requerida.",
        extra={"thinking": thinking_text, "raw": raw_content}
    )

    # Parsear tipo y SQL
    tipo = "SELECT"
    sql_candidate = ""
    explicacion = ""
    for line in raw_content.splitlines():
        clean_line = line.strip()
        if clean_line.startswith("TIPO:"):
            tipo = clean_line.replace("TIPO:", "").strip().upper()
        elif clean_line.startswith("SQL:"):
            sql_candidate = clean_line.replace("SQL:", "").strip()
        elif clean_line.startswith("EXPLICACION:"):
            explicacion = clean_line.replace("EXPLICACION:", "").strip()

    # Si no tiene el formato estricto, buscar SQL en bloques markdown
    if not sql_candidate or sql_candidate == "NINGUNO":
        m = re.search(r"```sql\s*(.*?)\s*```", raw_content, re.DOTALL | re.IGNORECASE)
        if m:
            sql_candidate = m.group(1).strip()
            tipo = "WRITE" if sql_candidate.upper().startswith(("UPDATE", "DELETE")) else "SELECT"
        else:
            tipo = "CONCEPTUAL"

    df_result = None
    sanitized_sql = None
    pending_write = None

    # -------------------------------------------------------------
    # FASE 3: Validación con Guardrails sqlglot (Local)
    # -------------------------------------------------------------
    if tipo in ("SELECT", "WRITE") and sql_candidate and sql_candidate != "NINGUNO":
        t2 = time.perf_counter()
        dialect = "postgres" if engine.dialect.name == "postgresql" else "sqlite"
        val = validate_and_classify_sql(sql_candidate, default_limit=500, dialect=dialect)
        dt_guard = time.perf_counter() - t2
        sanitized_sql = val["sanitized_sql"]

        record_step(
            phase_name="Validación de Guardrails (sqlglot)",
            target="Motor Local (sqlglot AST Parser)",
            duration=dt_guard,
            details=f"Sentencia clasificada como {val['classification']}. LIMIT aplicado: {val['has_limit']}.",
            extra={"sanitized_sql": sanitized_sql}
        )

        if not val["is_valid"]:
            return {
                "response": f"❌ Consulta bloqueada por Guardrails: {val.get('error')}",
                "dataframe": None,
                "sql": sql_candidate,
                "pending_write": None,
                "timeline": timeline,
                "thinking": thinking_text,
                "total_duration": round(time.perf_counter() - start_all, 2),
                "launch_time": launch_time,
                "finish_time": datetime.now().strftime("%H:%M:%S")
            }

        # -------------------------------------------------------------
        # FASE 4: Ejecución en Base de Datos / Human-in-the-loop
        # -------------------------------------------------------------
        if val["classification"] == "SELECT":
            t3 = time.perf_counter()
            raw_url = str(engine.url)
            host_label = raw_url.split("@")[-1].split("/")[0] if "@" in raw_url else "localhost"
            db_target = f"Base de Datos {engine.dialect.name.upper()} (Host: {host_label})"

            db_error = None
            try:
                with engine.connect() as conn:
                    df_result = pd.read_sql_query(text(sanitized_sql), conn)
                dt_db = time.perf_counter() - t3
            except Exception as exc:
                db_error = str(exc)
                dt_db = time.perf_counter() - t3

            # --- AUTO-CORRECCIÓN INTELIGENTE SI FALLA LA CONSULTA ---
            if db_error:
                record_step(
                    phase_name="Detección de Error en Base de Datos",
                    target=db_target,
                    duration=dt_db,
                    details=f"Fallo de ejecución SQL: {db_error[:150]}... Solicitando auto-corrección reflexiva al modelo.",
                    extra={"error": db_error, "failed_sql": sanitized_sql}
                )

                fix_prompt = f"""La siguiente consulta SQL generó un error al ejecutarse en el motor de base de datos {engine.dialect.name.upper()}:
---
CONSULTA SQL EJECUTADA:
{sanitized_sql}
---
ERROR RETORNADO POR EL MOTOR:
{db_error}
---
ESQUEMA REAL DE TABLAS Y COLUMNAS:
{schema_context}
---

INSTRUCCIONES DE CORRECCIÓN:
1. Analiza el error específico reportado por el motor (por ejemplo, si falta una columna como 'c.name', revisa el esquema y reemplázala por las columnas reales de customers: 'c.first_name' y 'c.last_name', o 'c.company_name').
2. Corrige la cláusula GROUP BY para que coincida exactamente con todas las columnas proyectadas no agregadas.
3. Genera una consulta SQL válida y corregida.

Responde ÚNICAMENTE con este formato exacto:
TIPO: SELECT
SQL: <sentencia sql corregida aquí>
EXPLICACION: <breve explicación de qué columna o sintaxis se corrigió>
"""
                t_fix = time.perf_counter()
                try:
                    fix_response = llm.invoke(fix_prompt)
                    dt_fix = time.perf_counter() - t_fix
                    
                    fix_raw = ""
                    if isinstance(fix_response.content, list):
                        for p in fix_response.content:
                            if isinstance(p, dict) and p.get("type") == "text":
                                fix_raw += p.get("text", "")
                            else:
                                fix_raw += str(p)
                    else:
                        fix_raw = str(fix_response.content)

                    corrected_sql = ""
                    fix_explicacion = ""
                    for line in fix_raw.splitlines():
                        cl = line.strip()
                        if cl.startswith("SQL:"):
                            corrected_sql = cl.replace("SQL:", "").strip()
                        elif cl.startswith("EXPLICACION:"):
                            fix_explicacion = cl.replace("EXPLICACION:", "").strip()

                    if not corrected_sql:
                        m = re.search(r"```sql\s*(.*?)\s*```", fix_raw, re.DOTALL | re.IGNORECASE)
                        if m:
                            corrected_sql = m.group(1).strip()

                    if corrected_sql:
                        val_fix = validate_and_classify_sql(corrected_sql, default_limit=500, dialect=dialect)
                        if val_fix["is_valid"] and val_fix["classification"] == "SELECT":
                            sanitized_sql = val_fix["sanitized_sql"]
                            with engine.connect() as conn:
                                df_result = pd.read_sql_query(text(sanitized_sql), conn)
                            db_error = None
                            explicacion = fix_explicacion or "Consulta SQL auto-corregida exitosamente resolviendo la inconsistencia de columnas."
                            record_step(
                                phase_name="Auto-corrección y Re-ejecución Exitosa",
                                target=db_target,
                                duration=dt_fix,
                                details=f"Sentencia corregida ejecutada con éxito. Filas retornadas: {len(df_result)}.",
                                extra={"corrected_sql": sanitized_sql, "rows": len(df_result)}
                            )
                except Exception as exc2:
                    db_error = f"{db_error} | Intento de corrección falló: {exc2}"

            # Si el error persiste tras la auto-corrección, responder limpiamente sin crashear
            if db_error:
                record_step(
                    phase_name="Fallo No Recuperable en BD",
                    target=db_target,
                    duration=0.01,
                    details=f"No se pudo ejecutar tras reintento: {db_error[:150]}",
                    extra={"error": db_error}
                )
                return {
                    "response": f"⚠️ La consulta no pudo ejecutarse en la base de datos debido al siguiente error:\n\n`{db_error}`\n\nSentencia intentada:\n```sql\n{sanitized_sql}\n```\nSugerencia: Intenta reformular la pregunta especificando los atributos deseados.",
                    "dataframe": None,
                    "sql": sanitized_sql,
                    "pending_write": None,
                    "timeline": timeline,
                    "thinking": thinking_text,
                    "total_duration": round(time.perf_counter() - start_all, 2),
                    "launch_time": launch_time,
                    "finish_time": datetime.now().strftime("%H:%M:%S")
                }

            # Si la consulta fue exitosa
            _context_store["last_dataframe"] = df_result
            _context_store["last_sql"] = sanitized_sql
            _audit_log.append({
                "timestamp": datetime.now().isoformat(),
                "sql": sanitized_sql,
                "classification": "SELECT",
                "status": "EXECUTED",
                "rows": len(df_result),
            })

            record_step(
                phase_name="Ejecución de Consulta en Base de Datos",
                target=db_target,
                duration=dt_db,
                details=f"Retornadas {len(df_result)} filas x {len(df_result.columns)} columnas.",
                extra={"rows": len(df_result)}
            )

        elif val["classification"] == "WRITE":
            action_id = str(uuid.uuid4())[:8]
            warning = val.get("warning")
            req_data = {
                "id": action_id,
                "sql": sanitized_sql,
                "classification": "WRITE",
                "status": "PENDING",
                "warning": warning,
                "created_at": datetime.now().isoformat(),
            }
            _pending_writes[action_id] = req_data
            _context_store["pending_write"] = req_data
            _audit_log.append({
                "timestamp": datetime.now().isoformat(),
                "action_id": action_id,
                "sql": sanitized_sql,
                "classification": "WRITE",
                "status": "PENDING_APPROVAL",
                "warning": warning,
            })
            pending_write = req_data
            record_step(
                phase_name="Retención Human-in-the-Loop",
                target="Cola de Seguridad Local (Memoria)",
                duration=0.01,
                details=f"Sentencia {sanitized_sql} retenida en espera de confirmación humana.",
                extra={"pending": pending_write}
            )

    # -------------------------------------------------------------
    # FASE 5: Síntesis Final
    # -------------------------------------------------------------
    final_text = explicacion
    if not final_text:
        if df_result is not None:
            final_text = f"Se obtuvieron {len(df_result)} registros de la base de datos. La tabla completa está disponible en la vista interactiva inferior."
        elif pending_write:
            final_text = f"La operación de modificación fue registrada (ID: `{pending_write['id']}`) y requiere confirmación explícita en la bandeja de aprobación superior."
        else:
            final_text = raw_content

    total_duration = time.perf_counter() - start_all
    return {
        "response": final_text,
        "dataframe": df_result,
        "sql": sanitized_sql or (sql_candidate if sql_candidate != "NINGUNO" else None),
        "pending_write": pending_write,
        "timeline": timeline,
        "thinking": thinking_text,
        "total_duration": round(total_duration, 2),
        "launch_time": launch_time,
        "finish_time": datetime.now().strftime("%H:%M:%S")
    }


class DBCopilot:
    """
    Controlador principal que expone los dos modos de uso con profiling temporal:
    - Modo 'schema': RAG directo sobre metadatos y arquitectura.
    - Modo 'agent': Agente observable con step-by-step, guardrails y Human-in-the-Loop.
    """

    def __init__(self, engine: Optional[Engine] = None, llm=None):
        self.engine = engine or get_agent_engine()
        set_agent_engine(self.engine)
        self.llm = llm or get_llm()
        self.tools = [retrieve_schema, run_select, run_write]
        self.checkpointer = InMemorySaver()

        # Grafo react de respaldo
        self.agent_graph = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=SYSTEM_PROMPT,
            checkpointer=self.checkpointer,
        )

    def ask(
        self,
        question: str,
        mode: Literal["schema", "agent"] = "agent",
        thread_id: str = "default_session",
        on_step_callback: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Ejecuta la consulta en el modo seleccionado con métricas de tiempo y desglose.
        """
        _context_store["last_dataframe"] = None
        _context_store["last_sql"] = None
        _context_store["pending_write"] = None

        if mode == "schema":
            timeline = []
            start_all = time.perf_counter()
            launch_time = datetime.now().strftime("%H:%M:%S")

            # 1. RAG Local en Chroma
            t0 = time.perf_counter()
            context = retrieve_schema_context(question, k=4)
            dt_rag = time.perf_counter() - t0
            step1 = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "phase": "Recuperación RAG de Esquema",
                "target": "RAG Local (Chroma Vector Store)",
                "duration": round(dt_rag, 3),
                "details": "Búsqueda semántica en el vector store del catálogo de base de datos.",
            }
            timeline.append(step1)
            if on_step_callback:
                try:
                    on_step_callback(step1)
                except Exception:
                    pass

            # 2. Síntesis Conceptual con LLM
            t1 = time.perf_counter()
            rag_res = answer_schema_question(question, llm=self.llm)
            dt_llm = time.perf_counter() - t1
            provider_name = "Google Gemini" if "Google" in type(self.llm).__name__ else "OpenAI GPT"
            model_name = getattr(self.llm, "model", getattr(self.llm, "model_name", "Desconocido"))
            step2 = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "phase": "Síntesis Conceptual con LLM",
                "target": f"API Cloud: {provider_name} ({model_name})",
                "duration": round(dt_llm, 3),
                "details": "Elaboración de respuesta técnica contextualizada en el esquema recuperado.",
            }
            timeline.append(step2)
            if on_step_callback:
                try:
                    on_step_callback(step2)
                except Exception:
                    pass

            return {
                "mode": "schema",
                "response": rag_res["answer"],
                "context": rag_res.get("context", ""),
                "dataframe": None,
                "sql": None,
                "pending_write": None,
                "timeline": timeline,
                "thinking": "",
                "total_duration": round(time.perf_counter() - start_all, 2),
                "launch_time": launch_time,
                "finish_time": datetime.now().strftime("%H:%M:%S"),
            }

        # Modo 2: Modo Agente SQL Observable
        result = execute_copilot_step_by_step(
            query=question,
            engine=self.engine,
            llm=self.llm,
            on_step_callback=on_step_callback
        )
        result["mode"] = "agent"
        return result
