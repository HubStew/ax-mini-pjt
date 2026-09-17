# 미니 PJT: 헬스 트레이닝 코칭 에이전트

## 무엇을 푸나
웨이트 트레이닝을 하는 본인 1명이 그날 운동/식단 기록만 보고는 무게를
올려도 되는지, 조합이 괜찮은지 판단이 안 서는 문제를, 최근 3~4주 기록과
장기 추세를 도구로 직접 조회해 근거 있는 코칭으로 풀어준다.

## 활용한 패턴 (Day 1~7)
- Day2: 구조 기반 청킹(마크다운 `##`/`###` 헤더 분할) — `retriever.py`가
  가이드라인 문서를 섹션·서브섹션 단위로 쪼개 검색 정확도를 높이는 데 그대로 씀
- Day2: 벡터DB 구축·재사용 + 코사인 유사도 임계값 — Chroma에 영속 저장하고,
  임계값 이하 검색 결과는 "관련 원칙을 찾지 못했습니다"로 처리해 환각을 막음
- Day2: 멀티 쿼리 검색의 대응 — LLM 재작성 대신 고정 동의어 사전
  (`query_synonyms.json`)으로 쿼리를 확장해 표현이 달라도 검색되게 함
- Day4: 도구 메타데이터(`@tool` + 한국어 docstring), 예외 대신 에러 설명
  문자열 반환 — 잘못된 입력을 조용히 기본값으로 처리하지 않도록 `tools.py`
  전반에 적용
- Day6: `create_agent` 여러 개 + `create_supervisor`로 Supervisor·서브
  에이전트 조립 — workout_agent/diet_agent 골격을 그대로 씀
- Day6: 서브 에이전트 자체에도 "담당 범위 밖 거절"을 못 박는 이중 안전장치 —
  라우팅이 틀려도 에이전트 스스로 지키게 함
- Day6: 에이전트의 API 서비스화 — 컴파일된 그래프를 FastAPI `POST /query`로
  그대로 노출
- Day5/7: 프롬프트 가드레일(환각 방지·불확실성 표기) + 코드 레벨 후처리
  검증을 함께 적용 — 프롬프트만으로 못 막는 경우를 코드가 보완
- Day7: 규칙 기반 자동 채점(도구 호출 여부·금지 문구 대조) + 사람이 확인할
  정성 항목 병기 — `run_eval.py`가 이 방식을 그대로 씀

## 아키텍처
```
사용자 질문
   │
   ▼
Supervisor (라우팅만, 직접 답하지 않음 · 한 턴에 전이 도구 하나만 호출)
   ├── 운동/신체 질문 ──▶ workout_agent ──▶ retrieve_guideline / get_workout_history / get_diet_history(체지방·근육량)
   └── 식단/영양 질문 ──▶ diet_agent    ──▶ retrieve_guideline / get_diet_history / calc_macro / get_user_profile / update_user_profile
                                              │
                                              ▼
                                     data/dummy/*.json (장기 메모리 역할)
                                     data/*.md → Chroma 벡터DB (RAG)
```
장기 메모리는 LangGraph Store 대신 `data/dummy/*.json`을 도구가 직접 읽고
쓰는 방식으로 구현했다 (의도적 스코프 단순화, 이유는 CLAUDE.md 참고).

## 실행 방법
```bash
# 1. 의존성 설치 (langchain, langchain-aws, langgraph, langgraph-supervisor,
#    langchain-chroma, fastapi, uvicorn)

# 2. .env에 AWS 자격 증명 설정 (Bedrock 호출용)

# 3. 더미 데이터 생성 (최초 1회)
python scripts/generate_dummy_data.py

# 4. API 서버 실행
cd src && uvicorn api_server:api --port 8000

# 5. 웹 데모: http://localhost:8000/
# 6. API 직접 호출:
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d "{\"question\": \"벤치프레스 25kg으로 계속 반복수가 늘고 있는데 무게 올려도 될까?\"}"

# 7. 평가 스크립트
python scripts/run_eval.py evaluation/round1_report.md
```

## RAGAS 평가 결과
`ragas` 라이브러리는 붙이지 않았다 — `data/dummy/`가 실제 문서 코퍼스가 아니라
개인 기록 JSON이라, RAGAS가 전제하는 "정답 컨텍스트 집합" 구성이 이 도메인과
잘 안 맞는다고 판단했다. 대신 Day7 실습(`run_eval.py`)과 동일하게 **규칙 기반
자동 채점**(도구 호출 여부·금지 문구 대조)과 **사람이 직접 확인하는 정성 평가**
(`expected_traits`)를 병행했다. 아래 지표는 RAGAS 정의를 참고해 우리 방식으로
근사한 값이다 (`retrieve_guideline` 컨텍스트가 실제로 answer/trace에 쓰였는지
`round1_report.md`의 20문항을 수동 대조):
- context_recall (질문이 검색을 필요로 할 때 실제로 검색됨): 근사치, 수치화
  안 함 — negative/edge 카테고리에서 모델이 검색을 건너뛴 사례가 남아있어
  (트라이앤에러 참고) 신뢰할 수 있는 수치를 아직 못 냄
- context_precision / faithfulness / answer_relevancy: 별도 산출 안 함 —
  `expected_traits` 기반 사람 확인으로 대체 (`round1_report.md`)

## 인-아웃 세트 통과율 (자체 평가)
- 1차 (Day9 종료, `evaluation/round1_report.md`): 13/20 통과 (65%) — positive 6/7,
  negative 1/4, edge 4/6, guardrail 2/3
- 2차 (Day10 개선 후): 예정 (진행 예정 — 결과 나오는 대로 갱신)
- 개선 예정 사항: Supervisor 동시 전이 금지, 서브 에이전트 영역 침범 방지,
  과도하게 엄격했던 expected_tools 기준 완화 — 원인 진단은 끝났고 2차에서
  적용해 통과율을 다시 측정할 예정

## 트라이앤에러 회고

**시도했지만 실패한 접근 · 왜 실패했는가**
- 검색 결과를 서버가 매번 먼저 가져와 대화에 미리 붙여주는 방식(RAG를 완전히
  코드로 강제) — Supervisor가 그 내용을 보고 라우팅 없이 직접 답하려는 새
  회귀(calc_macro 질문이 깨짐)를 만들어 포기함
- 문자열 마커("담당 범위", "관련 원칙을 찾지 못했습니다") 매칭으로 답변을
  강제 치환하는 코드 가드레일 — 모델이 같은 뜻을 다른 표현으로 정직하게 답한
  케이스까지 오탐해 좋은 답변을 지워버리는 회귀가 생겨 제거함
- 프롬프트에 실패 사례별 예시를 하나씩 추가하는 방식(짐볼, 케틀벨, 크레아틴
  각각) — 케이스가 계속 늘어나 끝이 없다고 판단해 일반화된 규칙 하나로
  되돌림

**최종 채택한 접근 · 왜 그것으로 갔는가**
- RAG 검색 여부 판단은 프롬프트 규칙(일반화된 한 문장)에만 맡기고, "검색
  없이 답을 지어내는 것"만 코드가 최소한으로 개입 — 프롬프트만으론 100%
  보장이 안 되지만, 정직한 답변까지 지우는 부작용보다는 낫다고 판단
- Supervisor는 "한 턴에 전이 도구 하나만 호출"하도록 명시 — 동시 전이가
  무한루프(`GraphRecursionError`)의 직접 원인으로 재현됐기 때문
- 환각 방지 기준을 "다른 영역은 거절 / 같은 영역의 낯선 주제는 일반 정보까지
  허용(수치 처방만 금지)"으로 완화 — 처음엔 전면 거절이었는데, 케틀벨처럼
  상식적인 질문까지 막는 게 과하다고 판단
- 모델은 여러 번 교체(Sonnet→Haiku→Sonnet→Nova Pro) — Bedrock 일일 토큰
  한도가 개발 중반 이후 거의 항상 소진돼 있어, 그때그때 쓸 수 있는 모델로
  넘어감. 최종 제출 직전까지 모델을 확정하지 않기로 함

**남은 한계 · 향후 개선 방향**
- 혼합 질문(운동+식단) 라우팅이 간헐적으로 여전히 루프에 빠짐 — 완전히
  해결하려면 순차 호출을 프롬프트가 아니라 그래프 구조로 강제해야 할 것
- Nova Pro가 한글 쿼리를 도구 호출 인자로 넘길 때 텍스트가 깨지는 경우가
  드물게 있음 (silent failure — 도구는 호출됐다고 집계되니 자동 채점으로
  못 잡음). 재현 빈도가 낮아 감수하고 진행
- Nova Pro의 Bedrock 콘텐츠 필터가 정상적인 프로필 조회 요청을 차단한 사례
  발견 — 프롬프트로 우회 불가한 모델 제공사 쪽 이슈라 별도 조치 안 함
- "오늘 저녁 뭐 먹을까?" 같은 미래형 추천 질문에서 diet_agent가 도구 호출
  없이 답하려는 경향 발견, 아직 미해결
- RAGAS 정식 지표 산출은 안 함 — 다음 개선 여지가 있다면 `ragas` 패키지를
  붙여 실제 context_recall/precision 수치화

## 핵심 코드 위치
- `src/agent.py:35` — workout_agent 조립 (`create_agent`)
- `src/agent.py:80` — diet_agent 조립
- `src/agent.py:127` — supervisor 조립 (`create_supervisor`)
- `src/prompts/__init__.py` — 공유 프롬프트 템플릿(검색 필수 규칙, 공통
  가드레일, SUPERVISOR_PROMPT)
- `src/tools.py` — 도메인 도구 5종(retrieve_guideline, get_workout_history,
  get_diet_history, calc_macro, get_user_profile, update_user_profile)
- `src/retriever.py` — RAG 파이프라인(청킹·임베딩·임계값 검색)
- `src/api_server.py:32` — `run_query` (answer/contexts/trace 조립,
  worker/supervisor 답변 분리 로직)
- `scripts/run_eval.py` — 평가 스크립트
- `evaluation/test_queries.csv` — 평가셋
- `evaluation/round1_report.md` — 1차(Day9) 평가 결과
