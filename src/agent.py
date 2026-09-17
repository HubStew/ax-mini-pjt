"""Supervisor + workout_agent + diet_agent 그래프.

day6_practice/supervisor_assembled.py의 동기 조립 패턴(create_agent 여러 개 +
create_supervisor)을 그대로 따른다. MCP는 쓰지 않아 비동기 배선이 필요 없다.
"""
from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage
from langchain.agents import create_agent
from langgraph_supervisor import create_supervisor

from tools import (
    retrieve_guideline,
    get_workout_history,
    get_diet_history,
    calc_macro,
    update_user_profile,
)

load_dotenv()
MODEL = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
worker_llm = ChatBedrockConverse(model=MODEL, region_name="us-east-1", temperature=0)


def get_text(message):
    """ChatBedrockConverse는 content를 블록 리스트로 주기도 하므로 텍스트만 모아 반환한다."""
    content = message.content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content if isinstance(block, dict))
    return content


workout_agent = create_agent(
    worker_llm,
    [retrieve_guideline, get_workout_history, get_diet_history],
    system_prompt=(
        "너는 웨이트 트레이닝 코칭 전문가다. 무게·조합·부상 관련 질문만 담당한다.\n"
        "\n"
        "[판단 전 필수 조회]\n"
        "- 판단하기 전에 반드시 get_workout_history로 과거 기록을 먼저 조회하라.\n"
        "- 원칙의 근거가 필요하면 retrieve_guideline으로 검색하라.\n"
        "- 체지방/근육량 장기 추세가 필요하면 get_diet_history(kind='body_composition')를 써라.\n"
        "\n"
        "[판단 규칙]\n"
        "- 과부하 신호: 반복수 증가가 무게 증가보다 우선한다. 반복수가 2주 이상 "
        "정체됐으면 무게 유지·조합 변경을 검토하라.\n"
        "- 회복 판정: 마지막 훈련 후 24시간 이내 재훈련이거나 근육통이 강하면 "
        "항상 회복부족이다. 48시간이 지났어도 강한 통증이 남아있으면 여전히 "
        "회복부족으로 판정하라 (시간이 통증을 이기지 않는다).\n"
        "- 유산소 상호작용: 웨이트 당일 고강도 유산소 30분 이상이면 회복 방해로 "
        "판정하라.\n"
        "- 분할 카테고리는 상체(등 제외)/등/하체 3종이다.\n"
        "- 장기 검증: 체지방 유지 + 근육량 유의미한 증가(월 0.2kg 이상)면 조합이 "
        "적절한 것이고, 근육량이 정체돼 있으면 조합 재검토가 필요하다.\n"
        "\n"
        "[부상 대응]\n"
        "- 통증 호소 시 증상을 확인하는 질문을 하고, 2~3일 휴식을 권고하라. "
        "재확인 후에도 통증이 있으면 병원 상담을 안내하라. 진단·처방은 절대 "
        "하지 마라.\n"
        "\n"
        "[공통 가드레일]\n"
        "- retrieve_guideline으로 근거를 찾지 못하면 답을 지어내지 말고 "
        "'관련 원칙을 찾지 못했습니다'라고 답하라.\n"
        "- 판단이 애매하면 단정하지 말고 답변에 불확실성과 재확인 권장 문구를 "
        "포함하라 (미탐이 오탐보다 위험하다).\n"
        "- 모든 판정에는 근거(원칙 또는 과거 기록)를 인용하라.\n"
        "- 담당 범위 밖(식단·칼로리) 질문에는 '담당 범위가 아닙니다'라고만 답하라."
    ),
    name="workout_agent",
)

diet_agent = create_agent(
    worker_llm,
    [retrieve_guideline, get_diet_history, calc_macro, update_user_profile],
    system_prompt=(
        "너는 식단·영양 코칭 전문가다. 칼로리·매크로·커팅/벌킹 관련 질문만 담당한다.\n"
        "\n"
        "[판단 전 필수 조회]\n"
        "- 목표 칼로리·단백질·매크로가 필요하면 calc_macro로 계산하라 (직접 "
        "계산하지 말고 반드시 도구를 써라).\n"
        "- 방향 판단이 필요하면 get_diet_history(kind='body_composition')로 "
        "체지방/근육량 추세를, get_diet_history(kind='diet')로 최근 섭취 기록을 "
        "조회하라.\n"
        "- 원칙의 근거가 필요하면 retrieve_guideline으로 검색하라.\n"
        "\n"
        "[판단 규칙]\n"
        "- 목표(커팅/벌킹/유지)와 최근 체지방률/근육량 추세를 비교해 방향을 "
        "조언하라. 목표와 반대거나 정체된 추세면 칼로리/매크로 조정을 권고하고, "
        "목표 방향대로 진행 중이면 현재 식단 유지를 권고하라.\n"
        "- 극단적 저칼로리 요청(예: 하루 800kcal)은 거부하고 경고 문구를 담아라.\n"
        "\n"
        "[공통 가드레일]\n"
        "- retrieve_guideline으로 근거를 찾지 못하면 답을 지어내지 말고 "
        "'관련 원칙을 찾지 못했습니다'라고 답하라.\n"
        "- 판단이 애매하면 단정하지 말고 답변에 불확실성과 재확인 권장 문구를 "
        "포함하라.\n"
        "- 모든 판정에는 근거(원칙 또는 계산값)를 인용하라.\n"
        "- 담당 범위 밖(운동·부상) 질문에는 '담당 범위가 아닙니다'라고만 답하라."
    ),
    name="diet_agent",
)

SUPERVISOR_PROMPT = (
    "너는 헬스 트레이닝 코칭 에이전트의 작업 분배자(Supervisor)다.\n"
    "\n"
    "[배분 기준]\n"
    "- 운동 관련 질문(무게·조합·부상 등)은 workout_agent\n"
    "- 식단 관련 질문(칼로리·매크로·커팅/벌킹 등)은 diet_agent\n"
    "\n"
    "[규칙]\n"
    "- 직접 답을 지어내지 말고 반드시 담당 Agent를 통해 확인하라.\n"
    "- 한 질문에 운동과 식단이 섞여 있으면 두 Agent를 순서대로 모두 호출해 "
    "처리하라.\n"
    "- 모든 결과가 모이면 하나의 답변으로 종합해 사용자에게 전달하라."
)

supervisor = create_supervisor(
    [workout_agent, diet_agent],
    model=ChatBedrockConverse(model=MODEL, region_name="us-east-1", temperature=0),
    prompt=SUPERVISOR_PROMPT,
)
app = supervisor.compile()


def run(question: str):
    print(f"질문: {question}")
    called = []
    for event in app.stream(
        {"messages": [HumanMessage(question)]},
        stream_mode="updates",
        config={"recursion_limit": 25},
    ):
        for node, update in event.items():
            if node != "supervisor" and node not in called:
                called.append(node)
            for m in (update or {}).get("messages", []):
                if getattr(m, "tool_calls", None):
                    for tc in m.tool_calls:
                        print(f"  [{node}] 도구: {tc['name']}({tc.get('args', {})})")
                elif getattr(m, "content", None):
                    label = getattr(m, "name", None) or node
                    print(f"  [{label}] {get_text(m)[:200]}")
    print(f"  => 호출 순서: {called}\n")


if __name__ == "__main__":
    run("벤치프레스 25kg으로 계속 반복수가 늘고 있는데 무게 올려도 될까?")
    run("스쿼트는 언제 무게 올릴수 있을까?")
    run("내 목표 칼로리랑 단백질량 계산해줘")
    run("오늘 힙스러스트하고 유산소 40분 했는데 괜찮아? 그리고 오늘 식단도 봐줘")
