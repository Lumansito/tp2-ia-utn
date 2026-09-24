"""
Agente SQL observable, con LangGraph, guardrails y aprobacion humana (HITL).
"""

import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Literal, Callable

import pandas as pd
from sqlalchemy import text, Engine
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent
from langgraph.checkpoint.memory import InMemorySaver

from db_copilot.config import get_engine, get_llm
from db_copilot.sql_guard import validate_and_classify_sql
from db_copilot.rag import retrieve_schema_context, answer_schema_question
from db_copilot.schema_introspection import introspect_database
from db_copilot import audit_store

_engine: Optional[Engine] = None
_schema_meta_cache: Optional[Dict[str, Any]] = None
_session_context: Dict[str, Dict[str, Any]] = {}


def set_agent_engine(engine: Engine) -> None:
    global _engine
    _engine = engine


def get_agent_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = get_engine()
    return _engine


def set_schema_meta(meta: Dict[str, Any]) -> None:
    global _schema_meta_cache
    _schema_meta_cache = meta


def get_schema_meta() -> Dict[str, Any]:
    global _schema_meta_cache
    if _schema_meta_cache is None:
        _schema_meta_cache = introspect_database(get_agent_engine())
    return _schema_meta_cache


def _ctx(thread_id: str) -> Dict[str, Any]:
    return _session_context.setdefault(
        thread_id, {"last_dataframe": None, "last_sql": None, "pending_write": None}
    )


def _clean_llm_response(content: Any) -> tuple[str, str]:
    """
    Extrae texto limpio y bloques de pensamiento (thinking) de la respuesta del LLM,
    manejando cadenas simples o listas/diccionarios de bloques estructurados de Gemini.
    """
    if not content:
        return "", ""
    if isinstance(content, str):
        return content.strip(), ""
    if isinstance(content, list):
        text_parts = []
        thinking_parts = []
        for block in content:
            if isinstance(block, str):
                text_parts.append(block)
            elif isinstance(block, dict):
                b_type = block.get("type")
                if b_type == "text" and "text" in block:
                    text_parts.append(str(block["text"]))
                elif b_type == "thinking" and "thinking" in block:
                    thinking_parts.append(str(block["thinking"]))
                elif "text" in block:
                    text_parts.append(str(block["text"]))
            elif hasattr(block, "text"):
                text_parts.append(str(block.text))
        text_res = "\n\n".join(text_parts).strip() if text_parts else str(content)
        thinking_res = "\n\n".join(thinking_parts).strip()
        return text_res, thinking_res
    if isinstance(content, dict):
        if content.get("type") == "text" and "text" in content:
            return str(content["text"]).strip(), ""
        if "text" in content:
            return str(content["text"]).strip(), ""
    return str(content).strip(), ""


def get_last_dataframe(thread_id: str = "default_session") -> Optional[pd.DataFrame]:
    return _ctx(thread_id).get("last_dataframe")


def get_pending_approvals(thread_id: Optional[str] = None) -> List[Dict[str, Any]]:
    return audit_store.get_pending_writes(thread_id=thread_id)


def get_audit_log(thread_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    return audit_store.get_audit_log(thread_id=thread_id, limit=limit)


def _dialect() -> str:
    return "postgres" if get_agent_engine().dialect.name == "postgresql" else "sqlite"


def make_tools(thread_id: str):
    """
    Arma las herramientas del agente para una sesion (`thread_id`) puntual.
    """
    ctx = _ctx(thread_id)

    @tool
    def list_tables() -> str:
        """Lista los nombres de todas las tablas disponibles en la base de datos."""
        meta = get_schema_meta()
        names = list(meta.get("tables", {}).keys())
        return ", ".join(names) if names else "No hay tablas en el esquema."

    @tool
    def describe_table(table_name: str) -> str:
        """Devuelve columnas, tipos, clave primaria y claves foraneas EXACTAS de una tabla.
        Usala antes de escribir SQL sobre una tabla si no estas seguro de los nombres reales
        de sus columnas: nunca asumas nombres de memoria."""
        meta = get_schema_meta()
        table = meta.get("tables", {}).get(table_name)
        if not table:
            candidates = ", ".join(meta.get("tables", {}).keys())
            return f"No existe la tabla '{table_name}'. Tablas disponibles: {candidates}"

        pk = table.get("primary_key", [])
        cols = "\n".join(
            f"- {c['name']} ({c['type']}){' [PK]' if c['name'] in pk else ''}"
            for c in table.get("columns", [])
        )
        fks = "\n".join(
            f"- {table_name}.{','.join(fk['constrained_columns'])} -> {fk['referred_table']}.{','.join(fk['referred_columns'])}"
            for fk in table.get("foreign_keys", [])
        ) or "Sin claves foraneas."
        comment = f"\nComentario de la tabla: {table['comment']}" if table.get("comment") else ""
        return f"Tabla '{table_name}':{comment}\nColumnas:\n{cols}\nClaves foraneas:\n{fks}"

    @tool
    def retrieve_schema(query: str) -> str:
        """Busca en el indice semantico del esquema (RAG) las tablas y relaciones relevantes
        para una pregunta en lenguaje natural. Usala siempre antes de generar SQL nuevo."""
        return retrieve_schema_context(query, k=4)

    @tool
    def run_select(sql: str) -> str:
        """Ejecuta una sentencia SELECT de solo lectura, previa validacion con los guardrails
        de seguridad (sqlglot). Devuelve un resumen: las filas completas quedan disponibles
        para la interfaz por separado."""
        val = validate_and_classify_sql(sql, default_limit=500, dialect=_dialect())
        if not val["is_valid"] or val["classification"] != "SELECT":
            audit_store.log_event(
                thread_id=thread_id, sql=sql, classification=val["classification"],
                status="BLOCKED", error=val.get("error"),
            )
            return f"BLOQUEADO por guardrails: {val.get('error') or 'Sentencia no permitida para una lectura.'}"

        sanitized = val["sanitized_sql"]
        engine = get_agent_engine()
        try:
            with engine.connect() as conn:
                df = pd.read_sql_query(text(sanitized), conn)
        except Exception as exc:
            audit_store.log_event(
                thread_id=thread_id, sql=sanitized, classification="SELECT",
                status="ERROR", error=str(exc),
            )
            return (
                f"ERROR al ejecutar la consulta en la base de datos: {exc}\n"
                f"Revisa los nombres reales de columnas y tablas (usa describe_table) "
                f"y reintenta con un SQL corregido."
            )

        ctx["last_dataframe"] = df
        ctx["last_sql"] = sanitized
        audit_store.log_event(
            thread_id=thread_id, sql=sanitized, classification="SELECT",
            status="EXECUTED", rows=len(df),
        )
        head_sample = df.head(2).to_dict(orient="records")
        return (
            f"Consulta ejecutada con exito.\n"
            f"- Filas obtenidas: {len(df)}\n"
            f"- Columnas: {list(df.columns)}\n"
            f"- Muestra (2 filas): {head_sample}\n"
            f"(Nota: las filas completas ya se enviaron a la interfaz como DataFrame. "
            f"No las transcribas: genera un resumen de 1-2 lineas.)"
        )

    @tool
    def run_write(sql: str) -> str:
        """Propone una sentencia INSERT, UPDATE o DELETE. Nunca se ejecuta directamente:
        queda encolada con un ID y espera aprobacion humana explicita en la interfaz."""
        val = validate_and_classify_sql(sql, default_limit=500, dialect=_dialect())
        if not val["is_valid"] or val["classification"] != "WRITE":
            audit_store.log_event(
                thread_id=thread_id, sql=sql, classification=val["classification"],
                status="BLOCKED", error=val.get("error"),
            )
            return f"BLOQUEADO por guardrails: {val.get('error') or 'Sentencia no permitida para una escritura.'}"

        action_id = str(uuid.uuid4())[:8]
        audit_store.add_pending_write(
            action_id=action_id, thread_id=thread_id, sql=val["sanitized_sql"],
            classification="WRITE", warning=val.get("warning"),
        )
        ctx["pending_write"] = {"id": action_id, "sql": val["sanitized_sql"], "warning": val.get("warning")}
        audit_store.log_event(
            thread_id=thread_id, action_id=action_id, sql=val["sanitized_sql"],
            classification="WRITE", status="PENDING_APPROVAL", warning=val.get("warning"),
        )
        warning_txt = f" Advertencia: {val['warning']}" if val.get("warning") else ""
        return (
            f"Sentencia retenida para aprobacion humana (ID: {action_id}).{warning_txt} "
            f"Todavia NO se ejecuto: informale al usuario que queda pendiente de confirmacion "
            f"en el panel de aprobaciones."
        )

    return [list_tables, describe_table, retrieve_schema, run_select, run_write]


def approve_pending_write(action_id: str, approve: bool, operator: str = "Operador Streamlit") -> str:
    """Aprueba o rechaza una escritura pendiente. Solo aca se toca la base para mutarla."""
    pending = audit_store.get_pending_write(action_id)
    if not pending:
        return f"No se encontro la solicitud pendiente '{action_id}'."

    if not approve:
        audit_store.resolve_pending_write(action_id, status="REJECTED", operator=operator)
        audit_store.log_event(
            thread_id=pending["thread_id"], action_id=action_id, sql=pending["sql"],
            classification="WRITE", status="REJECTED", operator=operator,
        )
        return f"Solicitud {action_id} rechazada por {operator}."

    engine = get_agent_engine()
    try:
        with engine.begin() as conn:
            result = conn.execute(text(pending["sql"]))
            affected = result.rowcount
        audit_store.resolve_pending_write(action_id, status="EXECUTED", operator=operator)
        audit_store.log_event(
            thread_id=pending["thread_id"], action_id=action_id, sql=pending["sql"],
            classification="WRITE", status="APPROVED_AND_EXECUTED", rows=affected, operator=operator,
        )
        return f"Solicitud {action_id} aprobada y ejecutada por {operator}. Filas afectadas: {affected}."
    except Exception as exc:
        audit_store.resolve_pending_write(action_id, status="EXECUTION_FAILED", operator=operator)
        audit_store.log_event(
            thread_id=pending["thread_id"], action_id=action_id, sql=pending["sql"],
            classification="WRITE", status="EXECUTION_FAILED", operator=operator, error=str(exc),
        )
        return f"La solicitud {action_id} fue aprobada pero fallo al ejecutarse: {exc}"


SYSTEM_PROMPT = """Eres DB Copilot, un asistente experto en bases de datos relacionales.

Herramientas disponibles: list_tables, describe_table, retrieve_schema, run_select, run_write.

Reglas obligatorias:
1. Antes de escribir cualquier SQL, invoca `retrieve_schema` con la pregunta del usuario
   (y, si necesitas precision sobre columnas o FKs exactas de una tabla puntual, `describe_table`).
   Nunca asumas nombres de columnas de memoria.
2. Para consultar datos, genera una unica sentencia SELECT valida y ejecutala con `run_select`.
3. Para modificar datos (INSERT/UPDATE/DELETE), genera la sentencia y proponela con `run_write`.
   Aclarale siempre al usuario que la modificacion queda pendiente de aprobacion humana.
4. Nunca generes sentencias multiples encadenadas con ';' ni DDL (DROP, ALTER, CREATE, TRUNCATE):
   las herramientas las van a rechazar de todas formas, pero no las intentes.
5. Si `run_select` devuelve un error, leelo con atencion, corregi el SQL (por ejemplo con los
   nombres de columnas reales que te da describe_table) y reintenta vos mismo antes de responder.
6. Cuando `run_select` devuelva resultados, NO transcribas las filas: el sistema ya las muestra
   en pantalla. Limitate a un resumen de 1-2 lineas con los totales o hallazgos principales.
7. Responde siempre en espanol claro y profesional.
"""


class DBCopilot:
    """
    Controlador principal. Expone dos modos:
    - 'schema': RAG puro sobre metadatos y arquitectura (nunca toca la base).
    - 'agent' : agente ReAct de LangGraph con herramientas, guardrails y HITL.
    """

    def __init__(self, engine: Optional[Engine] = None, llm=None, schema_meta: Optional[Dict[str, Any]] = None):
        self.engine = engine or get_agent_engine()
        set_agent_engine(self.engine)
        if schema_meta is not None:
            set_schema_meta(schema_meta)

        self.llm = llm or get_llm()
        self.checkpointer = InMemorySaver()
        self._graphs: Dict[str, Any] = {}

    def _graph_for(self, thread_id: str):
        if thread_id not in self._graphs:
            tools = make_tools(thread_id)
            self._graphs[thread_id] = create_react_agent(
                model=self.llm,
                tools=tools,
                prompt=SYSTEM_PROMPT,
                checkpointer=self.checkpointer,
            )
        return self._graphs[thread_id]

    def ask(
        self,
        question: str,
        mode: Literal["schema", "agent"] = "agent",
        thread_id: str = "default_session",
        on_step_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        ctx = _ctx(thread_id)
        ctx["last_dataframe"] = None
        ctx["last_sql"] = None
        ctx["pending_write"] = None

        start_all = time.perf_counter()
        launch_time = datetime.now().strftime("%H:%M:%S")
        timeline: List[Dict[str, Any]] = []

        def record_step(phase_name, target, duration, details="", extra=None):
            step_info = {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "phase": phase_name,
                "target": target,
                "duration": round(duration, 3),
                "details": details,
                "extra": extra or {},
            }
            timeline.append(step_info)
            if on_step_callback:
                try:
                    on_step_callback(step_info)
                except Exception:
                    pass
            return step_info

        if mode == "schema":
            t0 = time.perf_counter()
            retrieve_schema_context(question, k=4)
            record_step(
                "Recuperacion RAG de Esquema", "RAG Local (Chroma Vector Store)",
                time.perf_counter() - t0,
                "Busqueda semantica en el vector store del catalogo de base de datos.",
            )

            t1 = time.perf_counter()
            rag_res = answer_schema_question(question, llm=self.llm)
            record_step(
                "Sintesis Conceptual con LLM", f"API Cloud: LLM ({getattr(self.llm, 'model', getattr(self.llm, 'model_name', '?'))})",
                time.perf_counter() - t1,
                "Elaboracion de respuesta tecnica contextualizada en el esquema recuperado.",
            )

            answer_text, answer_thinking = _clean_llm_response(rag_res["answer"])
            return {
                "mode": "schema",
                "response": answer_text,
                "context": rag_res.get("context", ""),
                "dataframe": None,
                "sql": None,
                "pending_write": None,
                "timeline": timeline,
                "thinking": answer_thinking,
                "total_duration": round(time.perf_counter() - start_all, 2),
                "launch_time": launch_time,
                "finish_time": datetime.now().strftime("%H:%M:%S"),
            }

        graph = self._graph_for(thread_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}
        final_text = ""
        final_thinking = ""
        tool_calls_seen: List[str] = []

        try:
            for step in graph.stream(
                {"messages": [{"role": "user", "content": question}]},
                config=config,
                stream_mode="updates",
            ):
                node = list(step.keys())[0]
                msgs = step[node].get("messages", [])
                for m in msgs:
                    t_now = time.perf_counter() - start_all
                    tool_calls = getattr(m, "tool_calls", None)
                    if tool_calls:
                        names = [tc["name"] for tc in tool_calls]
                        tool_calls_seen.extend(names)
                        record_step(
                            "Decision del Agente", f"Nodo LangGraph: {node}", t_now,
                            f"El agente decidio invocar: {', '.join(names)}.",
                            {"tool_calls": [{"name": tc["name"], "args": tc.get("args")} for tc in tool_calls]},
                        )
                    elif type(m).__name__ == "ToolMessage":
                        record_step(
                            "Resultado de Herramienta", f"Herramienta: {getattr(m, 'name', '?')}", t_now,
                            str(getattr(m, "content", ""))[:200],
                            {"content": getattr(m, "content", "")},
                        )
                    elif getattr(m, "content", None):
                        clean_txt, clean_thk = _clean_llm_response(m.content)
                        if clean_txt:
                            final_text = clean_txt
                        if clean_thk:
                            final_thinking = clean_thk
                        record_step(
                            "Respuesta del Agente", f"Nodo LangGraph: {node}", t_now,
                            "El agente genero una respuesta final en lenguaje natural.",
                        )
        except Exception as exc:
            final_text = f"El agente no pudo completar la solicitud: {exc}"

        ctx_after = _ctx(thread_id)
        return {
            "mode": "agent",
            "response": final_text or "El agente no genero una respuesta de texto.",
            "dataframe": ctx_after.get("last_dataframe"),
            "sql": ctx_after.get("last_sql"),
            "pending_write": ctx_after.get("pending_write"),
            "timeline": timeline,
            "thinking": final_thinking,
            "tool_calls": tool_calls_seen,
            "total_duration": round(time.perf_counter() - start_all, 2),
            "launch_time": launch_time,
            "finish_time": datetime.now().strftime("%H:%M:%S"),
        }
