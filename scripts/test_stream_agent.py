#!/usr/bin/env python3
"""
Script manual (no es un test de pytest) para ver en vivo, por consola, los
pasos que va tomando el agente ReAct de LangGraph ante una pregunta. Requiere
DATABASE_URL y GOOGLE_API_KEY configurados en el .env.

Uso: python scripts/test_stream_agent.py "Cuantos empleados hay?"
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from db_copilot.config import get_engine, get_llm
from db_copilot.agent import DBCopilot

question = sys.argv[1] if len(sys.argv) > 1 else "Cuantos empleados hay?"

cop = DBCopilot(engine=get_engine(), llm=get_llm())
graph = cop._graph_for("test_stream_1")

print(f"Pregunta: {question}\n")
config = {"configurable": {"thread_id": "test_stream_1"}}
start = time.perf_counter()

for step in graph.stream({"messages": [{"role": "user", "content": question}]}, config=config, stream_mode="updates"):
    elapsed = time.perf_counter() - start
    node = list(step.keys())[0]
    print(f"[{elapsed:.2f}s] Nodo ejecutado: {node}")
    for m in step[node].get("messages", []):
        print(f"   Tipo de mensaje: {type(m).__name__}")
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            print(f"   Llamadas a herramientas: {[tc['name'] for tc in tool_calls]}")
            for tc in tool_calls:
                print(f"      Args: {tc.get('args')}")
        elif getattr(m, "content", None):
            print(f"   Contenido: {str(m.content)[:200]}")
