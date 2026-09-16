"""SERVICE.md/CLAUDE.md에 확정된 더미데이터 스펙대로 data/*.json을 생성한다.

사용자 프로필: 164cm/60kg/만 30세/여성/목표 maintain.
운동 9종목 x 1년(52주), 식단 1년치, 체지방/근육량 월 1회(12포인트)를 만들고
최근 구간에 벤치마크 패턴(정상진행/정체/회복부족위반/유산소위반/통증호소,
장기검증, 과식/저칼로리위반)을 명시적으로 심는다. 재현 가능하도록 시드를 고정한다.
"""
import json
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

END_DATE = date(2026, 9, 14)  # 최근 월요일
NUM_WEEKS = 52
START_DATE = END_DATE - timedelta(weeks=NUM_WEEKS - 1)

CATEGORIES = {
    "상체": {"벤치프레스": 20, "숄더프레스": 15, "머신컬": 10},
    "등": {"루마니안 데드리프트": 60, "바벨로우": 30, "렛풀다운": 35},
    "하체": {"스쿼트": 40, "힙스러스트": 50, "레그익스텐션": 25},
}
EXERCISE_CATEGORY = {ex: cat for cat, exs in CATEGORIES.items() for ex in exs}
WEEKDAY_TO_CATEGORY = {0: "상체", 2: "등", 4: "하체"}  # 월/수/금


def build_profile():
    return {
        "height_cm": 164,
        "weight_kg": 60,
        "age": 30,
        "gender": "female",
        "goal": "maintain",
        "target_muscle_mass_kg": 24,
    }


def base_reps_for_week(week_idx, weeks_since_last_increase):
    """주차 진행에 따라 반복수를 8~10 사이에서 완만히 늘리고 약간의 노이즈를 준다."""
    base = 8 + min(weeks_since_last_increase, 2)
    noise = random.choice([-1, 0, 0, 0, 1])
    return max(6, base + noise)


def build_workout_history():
    sessions = []
    # 종목별 진행 상태: 현재 무게, 마지막 증량 후 경과 주
    state = {ex: {"weight": w, "weeks_since_increase": 0} for cat in CATEGORIES.values() for ex, w in cat.items()}
    increment = {
        "벤치프레스": 2.5, "숄더프레스": 2.5, "머신컬": 1.0,
        "루마니안 데드리프트": 5.0, "바벨로우": 2.5, "렛풀다운": 2.5,
        "스쿼트": 5.0, "힙스러스트": 5.0, "레그익스텐션": 2.5,
    }

    d = START_DATE
    week_idx = 0
    last_session_by_category = {}  # category -> (date, weekday) 최근 훈련일 추적용

    while d <= END_DATE:
        weekday = d.weekday()
        if weekday in WEEKDAY_TO_CATEGORY:
            cat = WEEKDAY_TO_CATEGORY[weekday]
            for ex in CATEGORIES[cat]:
                st = state[ex]
                # 6주마다 무게 증량, 그 사이엔 반복수만 완만히 증가
                if st["weeks_since_increase"] >= 6:
                    st["weight"] += increment[ex]
                    st["weeks_since_increase"] = 0
                reps_base = base_reps_for_week(week_idx, st["weeks_since_increase"])
                reps = [reps_base, reps_base, max(6, reps_base - 1)]
                st["weeks_since_increase"] += 1 / 3  # 주 3회 훈련 기준으로 서서히 누적

                prev = last_session_by_category.get(cat)
                hours_since = 96 if prev is None else (d - prev).days * 24

                sessions.append({
                    "date": d.isoformat(),
                    "exercise": ex,
                    "category": cat,
                    "weight_kg": round(st["weight"], 1),
                    "sets": 3,
                    "reps": reps,
                    "soreness_before_session": "mild",
                    "hours_since_last_same_category": hours_since,
                    "same_day_cardio_minutes": 0,
                    "cardio_intensity": None,
                    "pain_reported": False,
                })
            last_session_by_category[cat] = d
            week_idx += 1
        d += timedelta(days=1)

    _inject_benchmarks(sessions)
    return sessions


def _find_last(sessions, exercise, before_date=None):
    matches = [s for s in sessions if s["exercise"] == exercise and (before_date is None or s["date"] < before_date)]
    return matches[-1] if matches else None


def _inject_benchmarks(sessions):
    """최근 3~4주 구간에 5개 벤치마크 패턴을 명시적으로 덮어쓴다."""
    recent_cutoff = (END_DATE - timedelta(weeks=4)).isoformat()

    # 1) 정상 진행: 벤치프레스 최근 3세션 반복수 지속 증가
    bench_sessions = [s for s in sessions if s["exercise"] == "벤치프레스" and s["date"] >= recent_cutoff]
    for i, s in enumerate(bench_sessions[-3:]):
        base = 8 + i
        s["reps"] = [base, base, base - 1]
        s["soreness_before_session"] = "mild"

    # 2) 정체: 스쿼트 최근 3세션 무게 동일 + 반복수 그대로
    squat_sessions = [s for s in sessions if s["exercise"] == "스쿼트" and s["date"] >= recent_cutoff]
    if squat_sessions:
        fixed_weight = squat_sessions[0]["weight_kg"]
        for s in squat_sessions[-3:]:
            s["weight_kg"] = fixed_weight
            s["reps"] = [8, 8, 7]
            s["soreness_before_session"] = "mild"

    # 3) 회복부족 위반: 등 세션 다음날 같은 카테고리(바벨로우) 추가 세션 삽입, 24시간 미만
    back_last = _find_last(sessions, "바벨로우", before_date=None)
    if back_last:
        violation_date = (date.fromisoformat(back_last["date"]) + timedelta(days=1)).isoformat()
        sessions.append({
            "date": violation_date,
            "exercise": "바벨로우",
            "category": "등",
            "weight_kg": back_last["weight_kg"],
            "sets": 3,
            "reps": [8, 7, 7],
            "soreness_before_session": "mild",
            "hours_since_last_same_category": 20,  # 24시간 미만 -> 회복부족 위반
            "same_day_cardio_minutes": 0,
            "cardio_intensity": None,
            "pain_reported": False,
        })

    # 4) 유산소 상호작용 위반: 최근 하체 세션에 당일 고강도 유산소 40분 추가
    squat_recent = [s for s in sessions if s["exercise"] == "스쿼트"]
    if squat_recent:
        target = squat_recent[-4] if len(squat_recent) >= 4 else squat_recent[0]
        target["same_day_cardio_minutes"] = 40
        target["cardio_intensity"] = "high"

    # 5) 통증 호소: 최근 상체(벤치프레스) 세션 중 하나에 통증 플래그
    if len(bench_sessions) >= 4:
        pain_session = bench_sessions[-4]
        pain_session["pain_reported"] = True
        pain_session["note"] = "어깨 앞쪽 통증 호소"

    sessions.sort(key=lambda s: (s["date"], s["exercise"]))


def build_body_composition():
    points = []
    d = date(START_DATE.year, START_DATE.month, 1)
    body_fat = 24.0
    muscle = 22.0
    month_count = 12

    for i in range(month_count):
        # 4~6번째 달: 정체 구간 (변화 없음)
        if 3 <= i <= 5:
            pass
        # 마지막 3개월: 근육량 증가 + 체지방 유지 (장기 검증 정상 사례)
        elif i >= month_count - 3:
            muscle += 0.3
        else:
            muscle += random.choice([0.0, 0.05, 0.1])
            body_fat += random.choice([-0.1, 0.0, 0.1])

        points.append({
            "date": d.isoformat(),
            "body_fat_pct": round(body_fat, 1),
            "muscle_mass_kg": round(muscle, 1),
        })
        # 다음 달 1일로 이동
        month = d.month + 1
        year = d.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        d = date(year, month, 1)

    return points


MEAL_POOL = {
    "breakfast": [("계란 2개 + 토스트", 350), ("그릭요거트 + 그래놀라", 300), ("바나나 + 두유", 250)],
    "lunch": [("닭가슴살 샐러드", 450), ("현미밥 + 제육볶음", 700), ("연어 포케", 550)],
    "dinner": [("두부 김치찌개 + 밥", 600), ("소고기 야채볶음", 650), ("고등어구이 + 나물", 500)],
    "snack": [("아몬드 한줌", 150), ("사과 1개", 100), ("프로틴 쉐이크", 180)],
}


def _random_meals(target_kcal):
    meals = []
    total = 0
    for slot in ("breakfast", "lunch", "dinner", "snack"):
        name, kcal = random.choice(MEAL_POOL[slot])
        meals.append({"name": name, "kcal": kcal})
        total += kcal
    return meals, total


def build_diet_log():
    logs = []
    d = START_DATE
    overeating_start = END_DATE - timedelta(weeks=2)
    overeating_end = END_DATE - timedelta(weeks=1)
    lowcal_start = END_DATE - timedelta(days=5)
    lowcal_end = END_DATE - timedelta(days=2)

    while d <= END_DATE:
        if overeating_start <= d <= overeating_end:
            # 과식 패턴: 목표(유지) 대비 지속적으로 초과 섭취
            meals, total = _random_meals(target_kcal=None)
            meals.append({"name": "야식 치킨", "kcal": 600})
            total += 600
        elif lowcal_start <= d <= lowcal_end:
            # 저칼로리 위반: 극단적으로 적게 섭취 (guardrail 트리거용)
            meals = [{"name": "샐러드 소량", "kcal": 200}, {"name": "블랙커피", "kcal": 0}]
            total = 200
        else:
            meals, total = _random_meals(target_kcal=None)

        logs.append({"date": d.isoformat(), "meals": meals, "total_kcal": total})
        d += timedelta(days=1)

    return logs


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    profile = build_profile()
    workouts = build_workout_history()
    body_comp = build_body_composition()
    diet = build_diet_log()

    (DATA_DIR / "user_profile.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "workout_history.json").write_text(
        json.dumps(workouts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "body_composition.json").write_text(
        json.dumps(body_comp, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "diet_log.json").write_text(
        json.dumps(diet, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"user_profile.json: {profile}")
    print(f"workout_history.json: 총 {len(workouts)}건 세션")
    print("  최근 8건:")
    for s in workouts[-8:]:
        print(f"    {s}")
    print(f"body_composition.json: 총 {len(body_comp)}포인트")
    for p in body_comp:
        print(f"    {p}")
    print(f"diet_log.json: 총 {len(diet)}일치")
    print("  최근 10일:")
    for d_ in diet[-10:]:
        print(f"    {d_['date']} total_kcal={d_['total_kcal']}")


if __name__ == "__main__":
    main()
