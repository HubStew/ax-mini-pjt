"""evaluation/test_queries.csv를 읽어 에이전트를 실행하고 채점한다.

- expected_tools: 명시돼 있으면 trace에 그 도구들이 실제로 호출됐는지 확인한다
- forbidden: 답변 문자열에 그대로 포함돼 있으면 실패로 본다. 다만 이 필드는
  "무조건 안 된다고만 답변"처럼 행동을 서술한 문구가 많아 답변에 문자 그대로
  나타나지 않는 경우가 많다 - 이 자동 검사는 우연히 문자열이 일치하는 경우만
  잡아내는 보조 수단이고, forbidden 위반 여부도 결국 expected_traits와 함께
  사람이 답변을 읽고 최종 판단해야 한다
- expected_traits: 자동 채점하지 않고, 사람이 보기 쉽도록 답변과 나란히
  결과 파일에 남긴다

사용법: python scripts/run_eval.py [출력파일경로]
  (기본 출력: evaluation/eval_result.md)
"""
import csv
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "src"))

from api_server import run_query  # noqa: E402

CSV_PATH = BASE_DIR / "evaluation" / "test_queries.csv"


def split_field(value: str) -> list[str]:
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def evaluate_row(row: dict) -> dict:
    expected_tools = split_field(row.get("expected_tools", ""))
    forbidden = split_field(row.get("forbidden", ""))

    try:
        result = run_query(row["input"])
        answer = result["answer"]
        called_tools = {t["tool"] for t in result["trace"]}
        error = None
    except Exception as e:  # 쓰로틀링 등으로 한 문항이 실패해도 나머지는 계속 진행
        answer = ""
        called_tools = set()
        error = f"{type(e).__name__}: {e}"

    missing_tools = [t for t in expected_tools if t not in called_tools]
    found_forbidden = [f for f in forbidden if f and f in answer]

    passed = error is None and not missing_tools and not found_forbidden

    return {
        **row,
        "answer": answer,
        "called_tools": sorted(called_tools),
        "missing_tools": missing_tools,
        "found_forbidden": found_forbidden,
        "error": error,
        "passed": passed,
    }


def main(out_path: Path):
    with CSV_PATH.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []
    for row in rows:
        print(f"[{row['id']}] {row['category']} 실행 중: {row['input'][:40]}...")
        r = evaluate_row(row)
        results.append(r)
        status = "PASS" if r["passed"] else ("ERROR" if r["error"] else "FAIL")
        print(f"  -> {status}")

    by_category = {}
    for r in results:
        by_category.setdefault(r["category"], []).append(r)

    print("\n=== 카테고리별 통과율 ===")
    lines = [
        f"# 평가 결과 ({datetime.now():%Y-%m-%d %H:%M})",
        "",
        "> forbidden 자동 검사는 답변에 해당 문구가 **문자 그대로** 포함됐을 때만",
        "> 잡아낸다. forbidden 필드 상당수는 행동을 서술한 문구라 자동으로는 안",
        "> 걸릴 수 있으니, expected_traits와 함께 아래 답변을 사람이 직접 확인할 것.",
        "",
    ]
    total_pass = sum(r["passed"] for r in results)
    for cat, items in by_category.items():
        passed = sum(r["passed"] for r in items)
        rate = passed / len(items) * 100
        line = f"{cat}: {passed}/{len(items)} ({rate:.0f}%)"
        print(line)
        lines.append(f"- {line}")
    overall = f"전체: {total_pass}/{len(results)} ({total_pass/len(results)*100:.0f}%)"
    print(overall)
    lines.append(f"\n**{overall}**\n")

    lines.append("## 상세 결과\n")
    for r in results:
        status = "PASS" if r["passed"] else ("ERROR" if r["error"] else "FAIL")
        lines.append(f"### [{r['id']}] {r['category']} — {status}")
        lines.append(f"- 질문: {r['input']}")
        lines.append(f"- 기대 도구: {r['expected_tools'] or '(없음)'}")
        lines.append(f"- 실제 호출 도구: {', '.join(r['called_tools']) or '(없음)'}")
        if r["missing_tools"]:
            lines.append(f"- ⚠️ 호출 안 된 기대 도구: {', '.join(r['missing_tools'])}")
        if r["found_forbidden"]:
            lines.append(f"- ⚠️ 발견된 forbidden 문구: {', '.join(r['found_forbidden'])}")
        if r["error"]:
            lines.append(f"- ❌ 에러: {r['error']}")
        lines.append(f"- expected_traits (사람이 확인): {r['expected_traits']}")
        answer_indented = (r["answer"] or "(응답 없음)").replace("\n", "\n  ")
        lines.append(f"- 답변:\n\n  {answer_indented}\n")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else BASE_DIR / "evaluation" / "eval_result.md"
    main(out)
