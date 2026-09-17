"""헬스 트레이닝 코칭 에이전트를 POST /query API로 노출한다.

제출 규약(CLAUDE.md): question 입력 -> answer/contexts/trace 출력.
MCP를 안 써서 그래프가 동기적으로 이미 만들어져 있으므로 lifespan/async
없이 agent.py의 컴파일된 app을 그대로 가져다 쓴다.
"""
from fastapi import FastAPI
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from agent import app as graph_app, get_text

api = FastAPI()


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    contexts: list[dict]
    trace: list[dict]


def run_query(question: str) -> dict:
    """그래프를 한 번 스트리밍하며 answer/contexts/trace를 동시에 채운다.

    subgraphs=True가 있어야 workout_agent/diet_agent 내부에서 실제로 어떤
    도구를 호출했는지(get_workout_history, retrieve_guideline 등)가 보인다
    (Supervisor 최상위 노드만 보면 서브 에이전트의 최종 응답만 보이고 내부
    도구 호출은 안 보임 - 직접 확인함). Supervisor가 상태를 재생하며 같은
    이벤트를 여러 경로로 중복 방출하므로 tool_call id로 중복을 제거한다.
    """
    answer = ""
    contexts = []
    trace = []
    seen_tool_call_ids = set()
    seen_tool_result_ids = set()

    for path, update in graph_app.stream(
        {"messages": [HumanMessage(question)]},
        stream_mode="updates",
        subgraphs=True,
        config={"recursion_limit": 25},
    ):
        for node, upd in (update or {}).items():
            for m in (upd or {}).get("messages", []):
                cls_name = m.__class__.__name__

                if cls_name == "AIMessage":
                    text = get_text(m)
                    if text:
                        answer = text
                    for tc in (m.tool_calls or []):
                        if tc["id"] in seen_tool_call_ids:
                            continue
                        seen_tool_call_ids.add(tc["id"])
                        trace.append({"step": node, "tool": tc["name"], "input": tc.get("args", {})})

                elif cls_name == "ToolMessage":
                    tool_call_id = getattr(m, "tool_call_id", None)
                    if tool_call_id in seen_tool_result_ids:
                        continue
                    seen_tool_result_ids.add(tool_call_id)
                    if getattr(m, "name", None) == "retrieve_guideline":
                        contexts.append({"source": "retrieve_guideline", "text": get_text(m)})

    return {"answer": answer, "contexts": contexts, "trace": trace}


@api.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    result = run_query(req.question)
    return QueryResponse(**result)


# 실행: uvicorn api_server:api --port 8000 (src/ 디렉터리에서)
# 테스트: curl -X POST http://localhost:8000/query -H "Content-Type: application/json" -d "{\"question\": \"벤치프레스 25kg으로 계속 반복수가 늘고 있는데 무게 올려도 될까?\"}"
