"""
Agente SQL observable, con LangGraph, guardrails y aprobacion humana (HITL).

A diferencia de la version anterior, aca el "modo Agente" corre de verdad un
agente ReAct de LangGraph (`create_react_agent`): el LLM decide, en cada
paso, que herramienta usar (buscar en el esquema, describir una tabla,
ejecutar una lectura, proponer una escritura) en lugar de seguir un pipeline
fijo de 5 fases escrito a mano. La auto-correccion ante errores de SQL sale
del mismo mecanismo: si `run_select` devuelve un error como texto, el agente
lo lee y decide como corregirlo, sin un prompt especial de "fix" aparte.

El estado (ultimo DataFrame, ultima escritura pendiente) ya no es un
diccionario global compartido por todos los usuarios: vive por `thread_id`
(una sesion de Streamlit o de notebook). La cola de aprobaciones y la
auditoria se persisten en SQLite via `audit_store.py`.
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

from db_copilot.config import get_engine, get_readonly_engine, get_llm, get_fallback_llm
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
    Arma las herramientas del agente para una sesion (`thread_id`) puntual,
    de forma que `run_select`/`run_write` escriban en el contexto de esa
    sesion y no en un estado global compartido.
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
        para la interfaz por separado, no hace falta transcribirlas. Si la consulta falla,
        el error del motor se devuelve como texto para que puedas corregir el SQL y reintentar
        vos mismo con una nueva llamada a esta herramienta."""
        val = validate_and_classify_sql(sql, default_limit=500, dialect=_dialect())
        if not val["is_valid"] or val["classification"] != "SELECT":
            audit_store.log_event(
                thread_id=thread_id, sql=sql, classification=val["classification"],
                status="BLOCKED", error=val.get("error"),
            )
            return f"BLOQUEADO por guardrails: {val.get('error') or 'Sentencia no permitida para una lectura.'}"

        sanitized = val["sanitized_sql"]
        engine = get_readonly_engine(default_engine=get_agent_engine())
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
        queda encolada con un ID y espera aprobacion humana explicita en la interfaz antes
        de impactar la base de datos."""
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

        primary_llm = llm or get_llm()
        try:
            # `.with_fallbacks` es el mecanismo nativo de LangChain para
            # degradar a un modelo mas liviano si el principal devuelve un
            # error (por ejemplo 429/503 por cuota agotada), sin necesidad
            # de detectar codigos de error a mano en cada llamada.
            self.llm = primary_llm.with_fallbacks([get_fallback_llm()])
        except Exception:
            self.llm = primary_llm

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
                "Sintesis Conceptual con LLM", f"API Cloud: Gemini ({getattr(self.llm, 'model', '?')})",
                time.perf_counter() - t1,
                "Elaboracion de respuesta tecnica contextualizada en el esquema recuperado.",
            )

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

        # Modo Agente: LangGraph ReAct real, con stream de pasos para no
        # perder la observabilidad que tenia el pipeline fijo anterior.
        graph = self._graph_for(thread_id)
        config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 12}
        final_text = ""
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
                        final_text = str(m.content)
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
            "thinking": "",
            "tool_calls": tool_calls_seen,
            "total_duration": round(time.perf_counter() - start_all, 2),
            "launch_time": launch_time,
            "finish_time": datetime.now().strftime("%H:%M:%S"),
        }
