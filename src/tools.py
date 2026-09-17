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


@tool
def get_diet_history(kind: str = "diet", weeks: int = 4) -> str:
    """과거 식단 기록 또는 체지방률/근육량 추세를 조회한다.

    kind="diet"면 최근 weeks주치 일별 섭취 칼로리를, kind="body_composition"이면
    월 1회 측정한 체지방률/근육량 전체 이력을 직전 시점 대비 변화량과 함께
    반환한다 (workout_agent의 장기 검증, diet_agent의 방향 판단에 공용으로 쓰인다).
    """
    if kind == "diet":
        logs = _load_json("diet_log.json")
        if not logs:
            return "식단 기록이 없습니다."
        latest_date = max(date.fromisoformat(d["date"]) for d in logs)
        cutoff = latest_date - timedelta(weeks=weeks)
        recent = [d for d in logs if date.fromisoformat(d["date"]) > cutoff]
        if not recent:
            return "해당 기간의 식단 기록이 없습니다."
        return "\n".join(
            f"{d['date']} 총 {d['total_kcal']}kcal ({', '.join(m['name'] for m in d['meals'])})"
            for d in recent
        )

    if kind == "body_composition":
        points = _load_json("body_composition.json")
        if not points:
            return "체지방/근육량 측정 기록이 없습니다."
        lines = []
        prev = None
        for p in points:
            if prev is None:
                lines.append(f"{p['date']} 체지방 {p['body_fat_pct']}% · 근육량 {p['muscle_mass_kg']}kg")
            else:
                d_fat = round(p["body_fat_pct"] - prev["body_fat_pct"], 2)
                d_muscle = round(p["muscle_mass_kg"] - prev["muscle_mass_kg"], 2)
                lines.append(
                    f"{p['date']} 체지방 {p['body_fat_pct']}%(Δ{d_fat:+}) · "
                    f"근육량 {p['muscle_mass_kg']}kg(Δ{d_muscle:+})"
                )
            prev = p
        return "\n".join(lines)

    return "diet 또는 body_composition 중 하나를 지정하세요."


_ACTIVITY_FACTORS = {"light": 1.2, "moderate": 1.4, "active": 1.6}
_GOAL_CALORIE_ADJUST = {"cutting": -0.175, "bulking": 0.125, "maintain": 0.0}
_GOAL_PROTEIN_G_PER_KG = {"cutting": 2.1, "bulking": 1.8, "maintain": 1.4}
_FAT_RATIO = 0.25


@tool
def calc_macro(activity_level: str = "") -> str:
    """사용자 프로필로 BMR·TDEE·목표 칼로리와 매크로(단백질/지방/탄수화물)를 계산한다.

    activity_level을 지정하지 않으면 프로필에 저장된 값을 쓴다.
    """
    profile = _load_json("user_profile.json")
    weight = profile["weight_kg"]
    height = profile["height_cm"]
    age = profile["age"]
    gender = profile["gender"]
    goal = profile["goal"]
    activity = activity_level or profile.get("activity_level", "moderate")

    if gender == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    factor = _ACTIVITY_FACTORS.get(activity, _ACTIVITY_FACTORS["moderate"])
    tdee = bmr * factor

    goal_adjust = _GOAL_CALORIE_ADJUST.get(goal, 0.0)
    target_kcal = tdee * (1 + goal_adjust)

    protein_g_per_kg = _GOAL_PROTEIN_G_PER_KG.get(goal, _GOAL_PROTEIN_G_PER_KG["maintain"])
    protein_g = weight * protein_g_per_kg
    protein_kcal = protein_g * 4

    fat_kcal = target_kcal * _FAT_RATIO
    fat_g = fat_kcal / 9

    carb_kcal = target_kcal - protein_kcal - fat_kcal
    carb_g = carb_kcal / 4

    return (
        f"BMR {bmr:.0f}kcal · TDEE {tdee:.0f}kcal · 목표({goal}) 칼로리 {target_kcal:.0f}kcal | "
        f"단백질 {protein_g:.0f}g · 지방 {fat_g:.0f}g · 탄수화물 {carb_g:.0f}g"
    )


_PROFILE_FIELDS = {
    "height_cm", "weight_kg", "age", "gender", "goal",
    "target_muscle_mass_kg", "activity_level",
}
_PROFILE_NUMERIC_FIELDS = {"height_cm", "weight_kg", "age", "target_muscle_mass_kg"}


@tool
def update_user_profile(field: str, value: str) -> str:
    """사용자 프로필의 항목 하나를 갱신한다.

    field는 height_cm/weight_kg/age/gender/goal/target_muscle_mass_kg/
    activity_level 중 하나여야 한다.
    """
    if field not in _PROFILE_FIELDS:
        return f"지원하지 않는 항목입니다: {field}"

    profile = _load_json("user_profile.json")

    if field in _PROFILE_NUMERIC_FIELDS:
        try:
            value_to_store = float(value) if "." in value else int(value)
        except ValueError:
            return f"{field}에는 숫자를 입력해야 합니다: {value}"
    else:
        value_to_store = value

    profile[field] = value_to_store
    (DATA_DIR / "user_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return f"{field}를 {value}로 업데이트했습니다."


if __name__ == "__main__":
    print(retrieve_guideline.invoke("벌킹할 때 단백질 얼마나 먹어야 해?"))
    print("---")
    print(get_workout_history.invoke({"exercise": "벤치프레스"}))
    print(get_workout_history.invoke({"exercise": "스쿼트"}))
    print(get_workout_history.invoke({"exercise": "유산소"}))
    print("---")
    print(get_diet_history.invoke({"kind": "diet", "weeks": 2}))
    print("---")
    print(get_diet_history.invoke({"kind": "body_composition"}))
    print("---")
    print(calc_macro.invoke({}))
