"""workout_agent·diet_agent가 쓰는 도구들.

데이터는 전부 data/dummy/*.json을 직접 읽는다 (이번 스코프의 "장기 메모리"는 이
조회 함수들이 대신한다 — LangGraph Store 이관은 후순위).
"""
import json
import threading
from datetime import date, timedelta
from pathlib import Path

from langchain_core.tools import tool

from retriever import retrieve_guideline as _retrieve_guideline

BASE_DIR = Path(__file__).resolve().parent.parent
DUMMY_DIR = BASE_DIR / "data" / "dummy"

# LangGraph의 ToolNode는 한 턴에 여러 도구 호출이 있으면 스레드풀로 동시
# 실행한다 - 사용자가 "세 끼 먹었어"처럼 한 번에 여러 항목을 보고하면
# log_meal이 같은 파일에 동시에 읽기-수정-쓰기를 하면서 파일이 깨지는 게
# 실제로 재현됐다 (JSONDecodeError: Extra data). 쓰기 도구는 전부 이 락으로
# 감싸 직렬화한다.
_write_lock = threading.Lock()


def _load_json(name: str):
    return json.loads((DUMMY_DIR / name).read_text(encoding="utf-8"))


def _save_json(name: str, data) -> None:
    (DUMMY_DIR / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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
    filtered = sorted(
        (s for s in filtered if date.fromisoformat(s["date"]) > cutoff),
        key=lambda s: s["date"],
    )

    if not filtered:
        return "해당 조건의 운동 기록이 없습니다."

    # 같은 날짜에 여러 종목을 한 세션(예: 상체 3종목)에 몰아서 하는 경우가
    # 많아서, 날짜별로 묶어 보여준다 - 안 묶으면 같은 날짜가 줄마다 반복돼
    # 가독성이 떨어진다 (특히 /status 화면에서 두드러짐)
    lines = []
    current_date = None
    for s in filtered:
        if s["date"] != current_date:
            current_date = s["date"]
            lines.append(f"{current_date}")
        lines.append(
            f"  - {s['exercise']}({s['category']}) "
            f"{s['weight_kg']}kg x {s['sets']}세트 {s['reps']}회"
        )
        detail = (
            f"    · 통증:{s['soreness_before_session']} · "
            f"마지막훈련후 {s['hours_since_last_same_category']}시간 경과"
        )
        if s.get("same_day_cardio_minutes"):
            detail += f" · 당일 유산소 {s['same_day_cardio_minutes']}분({s.get('cardio_intensity')})"
        if s.get("pain_reported"):
            detail += f" · 통증호소: {s.get('note', '통증 있음')}"
        lines.append(detail)
    return "\n".join(lines)


_WORKOUT_CATEGORIES = {"상체", "등", "하체"}
_SORENESS_LEVELS = {"none", "mild", "strong"}


@tool
def log_workout_session(
    exercise: str,
    category: str,
    weight_kg: float,
    sets: int,
    reps: list[int],
    soreness_before_session: str = "none",
    pain_reported: bool = False,
    note: str = "",
    same_day_cardio_minutes: int = 0,
    cardio_intensity: str = "",
    date_str: str = "",
) -> str:
    """운동 세션 하나를 기록에 추가한다.

    category는 상체/등/하체 중 하나여야 한다. soreness_before_session은
    none/mild/strong 중 하나(세션 시작 전 근육통 정도 - 사용자가 언급하지
    않았으면 기본값 none을 쓴다). reps는 세트별 반복수 리스트로 sets 길이와
    같아야 한다. hours_since_last_same_category는 같은 category의 직전
    기록과 비교해 자동으로 계산한다 (같은 category 기록이 없으면 999시간으로
    표시 - "충분히 오래됨"을 의미). date_str을 비우면 오늘 날짜로 저장하고,
    사용자가 특정 날짜를 언급했으면(예: "9월 15일에 스쿼트 했었어") 'YYYY-MM-DD'
    형식으로 변환해서 넘겨라.
    """
    if category not in _WORKOUT_CATEGORIES:
        return f"category는 상체/등/하체 중 하나여야 합니다: {category}"
    if soreness_before_session not in _SORENESS_LEVELS:
        return f"soreness_before_session은 none/mild/strong 중 하나여야 합니다: {soreness_before_session}"
    if len(reps) != sets:
        return f"reps 리스트 길이({len(reps)})가 sets({sets})와 일치해야 합니다."

    if date_str:
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return f"date_str은 YYYY-MM-DD 형식이어야 합니다: {date_str}"
    else:
        target_date = date.today()

    with _write_lock:
        sessions = _load_json("workout_history.json")

        same_category_dates = [
            date.fromisoformat(s["date"])
            for s in sessions
            if s["category"] == category and date.fromisoformat(s["date"]) < target_date
        ]
        if same_category_dates:
            hours_since_last = int((target_date - max(same_category_dates)).total_seconds() // 3600)
        else:
            hours_since_last = 999

        sessions.append({
            "date": target_date.isoformat(),
            "exercise": exercise,
            "category": category,
            "weight_kg": weight_kg,
            "sets": sets,
            "reps": reps,
            "soreness_before_session": soreness_before_session,
            "hours_since_last_same_category": hours_since_last,
            "same_day_cardio_minutes": same_day_cardio_minutes,
            "cardio_intensity": cardio_intensity or None,
            "pain_reported": pain_reported,
            "note": note,
        })
        _save_json("workout_history.json", sessions)
    return (
        f"{target_date.isoformat()} {exercise}({category}) {weight_kg}kg x {sets}세트 "
        f"{reps}회 기록을 저장했습니다."
    )


@tool
def delete_workout_session(exercise: str, date_str: str = "") -> str:
    """이미 기록된 운동 세션 하나를 삭제한다.

    사용자가 "아까 벤치프레스 기록한 거 취소해줘"처럼 잘못 기록됐거나 실제로
    안 한 걸 지워달라고 하면 이 도구를 써라. date_str을 비우면 오늘 기록에서
    찾는다. exercise는 정확히 일치해야 하며, 그 날짜에 같은 종목이 여러 번
    기록돼 있으면(예: 같은 날 두 세트로 나눠 기록) 어느 것인지 특정할 수
    없으니 실패 메시지를 반환한다 - 그 경우 사용자에게 확인하라.
    """
    if date_str:
        try:
            target_date = date.fromisoformat(date_str).isoformat()
        except ValueError:
            return f"date_str은 YYYY-MM-DD 형식이어야 합니다: {date_str}"
    else:
        target_date = date.today().isoformat()

    with _write_lock:
        sessions = _load_json("workout_history.json")
        matches = [s for s in sessions if s["date"] == target_date and s["exercise"] == exercise]
        if not matches:
            return f"{target_date} 기록에서 '{exercise}'을 찾지 못했습니다."
        if len(matches) > 1:
            return f"{target_date}에 '{exercise}' 기록이 여러 개입니다. 삭제할 하나를 특정할 수 없습니다."

        sessions.remove(matches[0])
        _save_json("workout_history.json", sessions)
    return f"{target_date} 기록에서 '{exercise}' 세션을 삭제했습니다."


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
        recent = sorted(
            (d for d in logs if date.fromisoformat(d["date"]) > cutoff),
            key=lambda d: d["date"],
        )
        if not recent:
            return "해당 기간의 식단 기록이 없습니다."
        lines = []
        for d in recent:
            lines.append(f"{d['date']} (총 {d['total_kcal']}kcal)")
            for m in d["meals"]:
                lines.append(f"  - {m['name']}")
        return "\n".join(lines)

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


@tool
def log_meal(meal_name: str, kcal: int, date_str: str = "") -> str:
    """먹은 끼니 하나를 식단 기록에 추가한다.

    date_str을 비우면 오늘 날짜에 추가하고, 사용자가 특정 날짜를 언급했으면
    (예: "어제 저녁에 라면 먹었어") 'YYYY-MM-DD' 형식으로 변환해서 넘겨라.
    그 날짜 기록이 이미 있으면 끼니 목록에 추가하고 총 칼로리를 다시 계산하고,
    없으면 새 날짜 항목을 만든다. kcal은 사용자가 직접 말해주지 않았으면
    음식 종류로 대략 추정해서 넣어도 되지만, 추정값이라는 점을 답변에서
    밝혀야 한다.
    """
    if not meal_name.strip():
        return "meal_name이 비어 있습니다."
    if kcal <= 0:
        return f"kcal은 0보다 커야 합니다: {kcal}"

    if date_str:
        try:
            target_date = date.fromisoformat(date_str).isoformat()
        except ValueError:
            return f"date_str은 YYYY-MM-DD 형식이어야 합니다: {date_str}"
    else:
        target_date = date.today().isoformat()

    with _write_lock:
        logs = _load_json("diet_log.json")

        entry = next((d for d in logs if d["date"] == target_date), None)
        if entry is None:
            entry = {"date": target_date, "meals": [], "total_kcal": 0}
            logs.append(entry)

        entry["meals"].append({"name": meal_name, "kcal": kcal})
        entry["total_kcal"] = sum(m["kcal"] for m in entry["meals"])

        _save_json("diet_log.json", logs)
    return f"{target_date} 식단에 '{meal_name}'({kcal}kcal)을 추가했습니다. 그날 총 {entry['total_kcal']}kcal."


@tool
def update_meal(old_meal_name: str, new_meal_name: str, new_kcal: int, date_str: str = "") -> str:
    """이미 기록된 끼니 하나의 이름·칼로리를 새 값으로 바꾼다 (새로 추가하지 않음).

    사용자가 "아까 김치찌개 먹을 때 공깃밥도 같이 먹었어"처럼 이미 기록한
    끼니에 뭔가를 더했다고 말하면, log_meal로 별도 항목을 새로 추가하지 말고
    이 도구를 써라 - old_meal_name='김치찌개', new_meal_name='김치찌개 + 공깃밥',
    new_kcal은 기존 칼로리에 추가분을 더한 값으로 호출한다. date_str을 비우면
    오늘 기록에서 찾는다. old_meal_name은 부분 일치로 찾으며, 일치하는 끼니가
    없거나 여러 개면 실패 메시지를 반환한다 - 그 경우 사용자에게 확인하거나
    log_meal로 새로 추가할지 판단하라.
    """
    if not old_meal_name.strip() or not new_meal_name.strip():
        return "old_meal_name과 new_meal_name은 비어 있을 수 없습니다."
    if new_kcal <= 0:
        return f"new_kcal은 0보다 커야 합니다: {new_kcal}"

    if date_str:
        try:
            target_date = date.fromisoformat(date_str).isoformat()
        except ValueError:
            return f"date_str은 YYYY-MM-DD 형식이어야 합니다: {date_str}"
    else:
        target_date = date.today().isoformat()

    with _write_lock:
        logs = _load_json("diet_log.json")
        entry = next((d for d in logs if d["date"] == target_date), None)
        if entry is None:
            return f"{target_date} 기록이 없습니다."

        # 정확히 이름이 같은 게 있으면 그것만 고른다 - 부분 일치만 쓰면
        # "김치찌개"가 "김치찌개 + 공깃밥"에도 걸려서, 사용자가 아무리
        # 명확하게 말해도 항상 여러 개로 걸리는 문제가 있었다.
        matches = [m for m in entry["meals"] if m["name"] == old_meal_name]
        if not matches:
            matches = [m for m in entry["meals"] if old_meal_name in m["name"]]
        if not matches:
            return f"{target_date} 기록에서 '{old_meal_name}'을 찾지 못했습니다."
        if len(matches) > 1:
            names = ", ".join(m["name"] for m in matches)
            return f"'{old_meal_name}'과 일치하는 끼니가 여러 개입니다: {names}. 더 구체적으로 지정하세요."

        matches[0]["name"] = new_meal_name
        matches[0]["kcal"] = new_kcal
        entry["total_kcal"] = sum(m["kcal"] for m in entry["meals"])
        _save_json("diet_log.json", logs)
    return (
        f"{target_date} 식단의 '{old_meal_name}'을 '{new_meal_name}'({new_kcal}kcal)으로 "
        f"수정했습니다. 그날 총 {entry['total_kcal']}kcal."
    )


@tool
def delete_meal(meal_name: str, date_str: str = "") -> str:
    """이미 기록된 끼니 하나를 삭제한다.

    사용자가 "아까 라면 먹었다고 한 거 취소해줘"처럼 잘못 기록됐거나 실제로
    안 먹은 걸 지워달라고 하면 이 도구를 써라. date_str을 비우면 오늘
    기록에서 찾는다. meal_name은 부분 일치로 찾으며, 일치하는 끼니가 없거나
    여러 개면 실패 메시지를 반환하니 사용자에게 확인하라. 그날 마지막 끼니를
    지우면 그 날짜 항목 자체도 함께 삭제된다.
    """
    if date_str:
        try:
            target_date = date.fromisoformat(date_str).isoformat()
        except ValueError:
            return f"date_str은 YYYY-MM-DD 형식이어야 합니다: {date_str}"
    else:
        target_date = date.today().isoformat()

    with _write_lock:
        logs = _load_json("diet_log.json")
        entry = next((d for d in logs if d["date"] == target_date), None)
        if entry is None:
            return f"{target_date} 기록이 없습니다."

        # update_meal과 동일한 이유로 정확히 일치하는 걸 먼저 찾는다.
        matches = [m for m in entry["meals"] if m["name"] == meal_name]
        if not matches:
            matches = [m for m in entry["meals"] if meal_name in m["name"]]
        if not matches:
            return f"{target_date} 기록에서 '{meal_name}'을 찾지 못했습니다."
        if len(matches) > 1:
            names = ", ".join(m["name"] for m in matches)
            return f"'{meal_name}'과 일치하는 끼니가 여러 개입니다: {names}. 더 구체적으로 지정하세요."

        entry["meals"].remove(matches[0])
        if entry["meals"]:
            entry["total_kcal"] = sum(m["kcal"] for m in entry["meals"])
        else:
            logs.remove(entry)
        _save_json("diet_log.json", logs)
    return f"{target_date} 식단에서 '{matches[0]['name']}'을 삭제했습니다."


_ACTIVITY_FACTORS = {"light": 1.2, "moderate": 1.4, "active": 1.6}
_GOAL_CALORIE_ADJUST = {"cutting": -0.175, "bulking": 0.125, "maintain": 0.0}
_GOAL_PROTEIN_G_PER_KG = {"cutting": 2.1, "bulking": 1.8, "maintain": 1.4}
_FAT_RATIO = 0.25


@tool
def calc_macro(activity_level: str = "") -> str:
    """사용자 프로필로 BMR·TDEE·목표 칼로리와 매크로(단백질/지방/탄수화물)를 계산한다.

    activity_level을 지정하지 않으면 프로필에 저장된 값을 쓴다. 지정할 경우
    light/moderate/active 중 하나여야 한다.
    """
    if activity_level and activity_level not in _ACTIVITY_FACTORS:
        allowed = "/".join(sorted(_ACTIVITY_FACTORS))
        return f"activity_level에는 {allowed} 중 하나만 입력할 수 있습니다: {activity_level}"

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
# calc_macro가 이 값들을 딕셔너리 키로 찾아 쓰는데, 여기 없는 값이 들어오면
# 에러 없이 조용히 기본값(유지/moderate)으로 폴백해버려 계산이 틀려도 티가
# 안 난다. 그래서 저장 시점에 미리 막는다.
_PROFILE_ENUM_FIELDS = {
    "goal": {"cutting", "bulking", "maintain"},
    "gender": {"male", "female"},
    "activity_level": {"light", "moderate", "active"},
}


_GENDER_LABELS = {"male": "남성", "female": "여성"}
_GOAL_LABELS = {"cutting": "커팅", "bulking": "벌킹", "maintain": "유지"}
_ACTIVITY_LEVEL_LABELS = {"light": "가벼운 운동", "moderate": "중간 강도", "active": "고강도"}


@tool
def get_user_profile() -> str:
    """저장된 사용자 프로필(키·몸무게·나이·성별·목표·활동수준)을 그대로 보여준다."""
    profile = _load_json("user_profile.json")
    gender = _GENDER_LABELS.get(profile["gender"], profile["gender"])
    goal = _GOAL_LABELS.get(profile["goal"], profile["goal"])
    activity_level = _ACTIVITY_LEVEL_LABELS.get(profile["activity_level"], profile["activity_level"])
    return (
        f"키 {profile['height_cm']}cm · 몸무게 {profile['weight_kg']}kg · "
        f"나이 {profile['age']}세 · 성별 {gender} · "
        f"목표 {goal} · 목표 근육량 {profile['target_muscle_mass_kg']}kg · "
        f"활동수준 {activity_level}"
    )


@tool
def update_user_profile(field: str, value: str) -> str:
    """사용자 프로필의 항목 하나를 갱신한다.

    field는 height_cm/weight_kg/age/gender/goal/target_muscle_mass_kg/
    activity_level 중 하나여야 한다. gender는 male/female, goal은
    cutting/bulking/maintain, activity_level은 light/moderate/active 중
    하나여야 하며, 그 외 값은 저장을 거부하고 에러 메시지를 반환한다
    (calc_macro가 이 값들을 그대로 계산에 쓰기 때문).
    """
    if field not in _PROFILE_FIELDS:
        return f"지원하지 않는 항목입니다: {field}"

    if field in _PROFILE_ENUM_FIELDS and value not in _PROFILE_ENUM_FIELDS[field]:
        allowed = "/".join(sorted(_PROFILE_ENUM_FIELDS[field]))
        return f"{field}에는 {allowed} 중 하나만 입력할 수 있습니다: {value}"

    if field in _PROFILE_NUMERIC_FIELDS:
        try:
            value_to_store = float(value) if "." in value else int(value)
        except ValueError:
            return f"{field}에는 숫자를 입력해야 합니다: {value}"
    else:
        value_to_store = value

    with _write_lock:
        profile = _load_json("user_profile.json")
        profile[field] = value_to_store
        _save_json("user_profile.json", profile)
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
