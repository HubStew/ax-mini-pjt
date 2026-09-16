"""workout_agent·diet_agent가 쓰는 도구들.

데이터는 전부 data/*.json을 직접 읽는다 (이번 스코프의 "장기 메모리"는 이
조회 함수들이 대신한다 — LangGraph Store 이관은 후순위).
"""
import json
from datetime import date, timedelta
from pathlib import Path

from langchain_core.tools import tool

from retriever import retrieve_guideline as _retrieve_guideline

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


def _load_json(name: str):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


@tool
def retrieve_guideline(query: str) -> str:
    """운동·영양 가이드라인 문서에서 질의와 관련된 원칙을 검색해 반환한다."""
    return _retrieve_guideline(query)


@tool
def get_workout_history(exercise: str = "", category: str = "", weeks: int = 4) -> str:
    """과거 운동 세션 기록을 조회한다.

    exercise(종목명)를 주면 해당 종목만, category(상체/등/하체)를 주면 해당
    카테고리 전체를, 둘 다 비우면 전체 기록을 조회한다. weeks는 최신 기록
    기준 최근 몇 주치를 볼지 정한다 (기본 4주). 유산소는 별도 종목이 아니라
    웨이트 세션에 딸린 부가 정보라서, exercise 또는 category에 "유산소"를
    주면 종목/카테고리와 무관하게 당일 유산소를 한 세션만 걸러서 보여준다.
    """
    sessions = _load_json("workout_history.json")
    if not sessions:
        return "운동 기록이 없습니다."

    latest_date = max(date.fromisoformat(s["date"]) for s in sessions)
    cutoff = latest_date - timedelta(weeks=weeks)

    filtered = sessions
    if exercise == "유산소" or category == "유산소":
        filtered = [s for s in filtered if s.get("same_day_cardio_minutes")]
    elif exercise:
        filtered = [s for s in filtered if s["exercise"] == exercise]
    elif category:
        filtered = [s for s in filtered if s["category"] == category]
    filtered = [s for s in filtered if date.fromisoformat(s["date"]) > cutoff]

    if not filtered:
        return "해당 조건의 운동 기록이 없습니다."

    lines = []
    for s in filtered:
        line = (
            f"{s['date']} {s['exercise']}({s['category']}) "
            f"{s['weight_kg']}kg x {s['sets']}세트 {s['reps']}회 · "
            f"통증:{s['soreness_before_session']} · "
            f"같은부위 마지막훈련후 {s['hours_since_last_same_category']}시간 경과"
        )
        if s.get("same_day_cardio_minutes"):
            line += f" · 당일 유산소 {s['same_day_cardio_minutes']}분({s.get('cardio_intensity')})"
        if s.get("pain_reported"):
            line += f" · 통증호소: {s.get('note', '통증 있음')}"
        lines.append(line)
    return "\n".join(lines)


if __name__ == "__main__":
    print(retrieve_guideline.invoke("벌킹할 때 단백질 얼마나 먹어야 해?"))
    print("---")
    print(get_workout_history.invoke({"exercise": "벤치프레스"}))
    print(get_workout_history.invoke({"exercise": "스쿼트"}))
    print(get_workout_history.invoke({"exercise": "유산소"}))
