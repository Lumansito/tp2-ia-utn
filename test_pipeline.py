import time
from datetime import datetime
from dotenv import load_dotenv; load_dotenv()
from db_copilot.config import get_engine, get_llm
from db_copilot.rag import retrieve_schema_context
from db_copilot.sql_guard import validate_and_classify_sql
from db_copilot.agent import run_select, run_write, approve_pending_write
import pandas as pd
from sqlalchemy import text

def execute_copilot_step_by_step(query: str, engine, llm, on_step_callback=None):
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
            on_step_callback(step_info)
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
3. Si es solo una pregunta conceptual del modelo (sin datos), responde directamente explicando la arquitectura.

Escribe tu respuesta con este formato exacto:
TIPO: SELECT | WRITE | CONCEPTUAL
SQL: <sentencia sql aquí o NINGUNO si es conceptual>
EXPLICACION: <breve explicación en 1 o 2 líneas>
"""

    t1 = time.perf_counter()
    provider_name = "Google Gemini (gemini-3.6-flash)" if "ChatGoogleGenerativeAI" in type(llm).__name__ else "OpenAI (GPT)"
    llm_response = llm.invoke(prompt)
    dt_llm1 = time.perf_counter() - t1

    # Extraer thinking si viene en la respuesta de Gemini
    thinking_text = ""
    raw_content = ""
    if isinstance(llm_response.content, list):
        for part in llm_response.content:
            if isinstance(part, dict):
                if part.get("type") == "thinking":
                    thinking_text += part.get("thinking", "")
                elif part.get("type") == "text":
                    raw_content += part.get("text", "")
    else:
        raw_content = str(llm_response.content)

    record_step(
        phase_name="Generación de SQL y Razonamiento",
        target=f"API Cloud: {provider_name}",
        duration=dt_llm1,
        details="El modelo analizó el esquema RAG y determinó la sentencia requerida.",
        extra={"thinking": thinking_text, "raw": raw_content}
    )

    # Parsear tipo y SQL
    tipo = "SELECT"
    sql_candidate = ""
    explicacion = ""
    for line in raw_content.splitlines():
        if line.startswith("TIPO:"):
            tipo = line.replace("TIPO:", "").strip().upper()
        elif line.startswith("SQL:"):
            sql_candidate = line.replace("SQL:", "").strip()
        elif line.startswith("EXPLICACION:"):
            explicacion = line.replace("EXPLICACION:", "").strip()

    # Si no tiene el formato estricto, buscar SQL en bloques markdown
    if not sql_candidate or sql_candidate == "NINGUNO":
        import re
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
                "timeline": timeline,
                "thinking": thinking_text,
                "total_duration": time.perf_counter() - start_all,
                "launch_time": launch_time
            }

        # -------------------------------------------------------------
        # FASE 4: Ejecución en Base de Datos / Human-in-the-loop
        # -------------------------------------------------------------
        if val["classification"] == "SELECT":
            t3 = time.perf_counter()
            with engine.connect() as conn:
                df_result = pd.read_sql_query(text(sanitized_sql), conn)
            dt_db = time.perf_counter() - t3
            db_target = f"Base de Datos {engine.dialect.name.upper()} (Host: {str(engine.url).split('@')[-1].split('/')[0]})"
            record_step(
                phase_name="Ejecución de Consulta en Base de Datos",
                target=db_target,
                duration=dt_db,
                details=f"Retornadas {len(df_result)} filas x {len(df_result.columns)} columnas.",
                extra={"rows": len(df_result)}
            )

        elif val["classification"] == "WRITE":
            # Poner en cola de aprobación
            from db_copilot.agent import run_write
            res_write = run_write.invoke({"sql": sanitized_sql})
            from db_copilot.agent import get_pending_approvals
            pends = get_pending_approvals()
            pending_write = pends[-1] if pends else None
            record_step(
                phase_name="Retención Human-in-the-Loop",
                target="Cola de Seguridad Local",
                duration=0.01,
                details=f"Sentencia {sanitized_sql} retenida en espera de aprobación humana.",
                extra={"pending": pending_write}
            )

    # -------------------------------------------------------------
    # FASE 5: Síntesis Final
    # -------------------------------------------------------------
    final_text = explicacion
    if not final_text:
        if df_result is not None:
            final_text = f"Se obtuvieron {len(df_result)} filas de la base de datos. La tabla completa está disponible en la vista interactiva inferior."
        elif pending_write:
            final_text = f"La operación de modificación fue registrada (ID: `{pending_write['id']}`) y está pendiente de aprobación humana en el panel superior."
        else:
            final_text = raw_content

    total_duration = time.perf_counter() - start_all
    return {
        "response": final_text,
        "dataframe": df_result,
        "sql": sanitized_sql or sql_candidate,
        "pending_write": pending_write,
        "timeline": timeline,
        "thinking": thinking_text,
        "total_duration": round(total_duration, 2),
        "launch_time": launch_time,
        "finish_time": datetime.now().strftime("%H:%M:%S")
    }

if __name__ == "__main__":
    eng = get_engine()
    llm = get_llm()
    print("Testing step by step execution...")
    res = execute_copilot_step_by_step("Cuantos departamentos hay?", eng, llm, on_step_callback=lambda s: print(f"[{s['duration']}s] {s['phase']} -> {s['target']}"))
    print("\n--- RESUMEN FINAL ---")
    print(f"Duración total: {res['total_duration']}s")
    print("Respuesta:", res["response"])
    print("SQL:", res["sql"])
    print("DF:", len(res["dataframe"]) if res["dataframe"] is not None else 0)
    print("Thinking len:", len(res["thinking"]))
