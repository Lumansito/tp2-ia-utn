import time
from dotenv import load_dotenv
load_dotenv()
from db_copilot.config import get_engine, get_llm
from db_copilot.agent import DBCopilot

cop = DBCopilot(engine=get_engine(), llm=get_llm())
print('Testing streaming step by step...')
config = {'configurable': {'thread_id': 'test_stream_1'}}
start = time.perf_counter()

for step in cop.agent_graph.stream({'messages': [{'role': 'user', 'content': 'Cuantos empleados hay?'}]}, config=config, stream_mode='updates'):
    elapsed = time.perf_counter() - start
    node = list(step.keys())[0]
    print(f'[{elapsed:.2f}s] Node executed: {node}')
    msgs = step[node].get('messages', [])
    for m in msgs:
        print(f'   Msg type: {type(m).__name__}')
        if hasattr(m, 'tool_calls') and m.tool_calls:
            print(f'   Tool calls: {[tc["name"] for tc in m.tool_calls]}')
            for tc in m.tool_calls:
                print(f'      Args: {tc.get("args")}')
        if hasattr(m, 'content') and m.content and not (hasattr(m, 'tool_calls') and m.tool_calls):
            print(f'   Content: {str(m.content)[:100]}...')
