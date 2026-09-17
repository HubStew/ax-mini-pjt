"""헬스 트레이닝 코칭 에이전트를 POST /query API로 노출한다.

제출 규약(CLAUDE.md): question 입력 -> answer/contexts/trace 출력.
MCP를 안 써서 그래프가 동기적으로 이미 만들어져 있으므로 lifespan/async
없이 agent.py의 컴파일된 app을 그대로 가져다 쓴다.
"""
from pathlib import Path

from botocore.exceptions import ClientError
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from agent import app as graph_app, get_text

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

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
    worker_answers = {}
    supervisor_answer = ""
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
                    if text and not m.tool_calls:
                        # tool_calls가 같이 붙은 메시지는 "확인하겠습니다"나
                        # "Transferring back to supervisor" 같은 안내용 텍스트이지
                        # 최종 답변이 아니다.
                        # workout_agent/diet_agent 자신의 답변과 Supervisor의
                        # 종합 답변을 분리해서 따로 저장한다 - 단일 에이전트
                        # 질문에서는 Supervisor가 뒤에 "위의 계산 결과가..."처럼
                        # 실제 내용 없이 참조만 하는 요약을 덧붙이는 경우가 있어,
                        # 그걸 그대로 최종 답으로 쓰면 진짜 답변(수치·근거)이
                        # 사라진다.
                        name = getattr(m, "name", None)
                        if name in ("workout_agent", "diet_agent"):
                            worker_answers[name] = text
                        else:
                            supervisor_answer = text
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

    if len(worker_answers) == 1:
        # 단일 에이전트 질문 - 실제 근거·수치가 담긴 그 에이전트의 답을 쓴다
        answer = next(iter(worker_answers.values()))
    elif len(worker_answers) >= 2:
        # 운동+식단 혼합 질문 - 두 에이전트 답을 하나로 묶는 건 Supervisor의
        # 역할이므로 Supervisor 종합 답변을 우선하고, 그마저 비어있으면
        # 두 에이전트 답을 이어붙인다
        answer = supervisor_answer or "\n\n".join(worker_answers.values())
    else:
        answer = supervisor_answer

    real_tools_called = any(
        t["tool"] not in ("transfer_to_workout_agent", "transfer_to_diet_agent", "transfer_back_to_supervisor")
        for t in trace
    )
    honest_refusal_markers = ("관련 원칙을 찾지 못했습니다", "담당 범위")
    if not real_tools_called and answer and not any(marker in answer for marker in honest_refusal_markers):
        # 프롬프트만으로는 "검색 없이 답 지어내기"를 100% 못 막는다 (모델이
        # 가드레일을 무시하는 경우가 실제로 관측됨) - 도구를 하나도 안 쓰고
        # 정직한 거절 문구도 없이 답했다면 환각으로 간주하고 강제로 덮어쓴다.
        answer = "관련 원칙을 찾지 못했습니다. (해당 주제는 저희가 조회할 수 있는 가이드라인/기록 범위 밖입니다.)"

    return {"answer": answer, "contexts": contexts, "trace": trace}


@api.post("/query", response_model=QueryResponse)
def query(req: QueryRequest) -> QueryResponse:
    try:
        result = run_query(req.question)
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ThrottlingException":
            raise HTTPException(
                status_code=503,
                detail="지금 요청이 많아 잠시 처리할 수 없습니다. 잠시 후 다시 시도해주세요.",
            )
        raise HTTPException(status_code=502, detail=f"모델 호출 중 오류가 발생했습니다: {error_code or e}")
    return QueryResponse(**result)


# /query 라우트 다음에 마운트해야 한다 - 먼저 마운트하면 StaticFiles가
# /query까지 흡수해버릴 수 있음
api.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

# 실행: uvicorn api_server:api --port 8000 (src/ 디렉터리에서)
# 웹 데모: http://localhost:8000/
# 테스트: curl -X POST http://localhost:8000/query -H "Content-Type: application/json" -d "{\"question\": \"벤치프레스 25kg으로 계속 반복수가 늘고 있는데 무게 올려도 될까?\"}"
