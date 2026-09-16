# 프로젝트 규칙

## 기술 스택
- Python, LangChain, LangGraph
- 모델은 Amazon Bedrock (ChatBedrockConverse) — `us.anthropic.claude-sonnet-4-5-20250929-v1:0`, region `us-east-1`
- 임베딩은 BedrockEmbeddings — `amazon.titan-embed-text-v2:0`
- 벡터DB는 Chroma
- Agent 생성은 `langchain.agents`의 `create_agent`, Supervisor 조립은
  `langgraph_supervisor`의 `create_supervisor`를 쓴다
- API 서버는 FastAPI

## 폴더 구조 (제출 규약. 바꾸지 않는다)
```
src/agent.py       Supervisor + workout_agent + diet_agent 그래프
src/tools.py        도메인 도구 (retrieve_guideline, get_workout_history,
                    get_diet_history, calc_macro 등)
src/retriever.py    RAG 파이프라인 (Chroma + BedrockEmbeddings)
data/               training_guidelines.md, nutrition_guidelines.md, 더미 데이터
evaluation/         test_queries.csv, round1_report.md, round2_report.md
```

## 주고받는 형식 (제출 규약)
- `POST /query`로 받고 `question` 필드를 읽는다
- 답은 `answer`, `contexts`, `trace` 세 키로 돌려준다

## 코드 규칙
- 파일 하나에 한 가지 역할만 둔다
- 함수와 도구에는 한국어 docstring을 쓴다
- 비밀 값은 `.env`에서 읽고 코드에 적지 않는다

## 골격 코드 (day6_practice 재사용)
- `day6_practice/supervisor_assembled.py`의 동기 조립 패턴(`create_agent` +
  `create_supervisor`)을 뼈대로 쓴다
- `day6_practice/final_scenario.py`의 RAG 배선(Chroma + `retrieve_docs`류 도구)만
  가져와 `retrieve_guideline`으로 재사용한다 — MCP(비동기) 부분은 가져오지 않는다
- `day5_practice/guards.py`, `guards_input.py`, `guards_output.py`, `hitl_flow.py` —
  가드레일 로직 참고
- `day7_practice/` — 장기 메모리(LangGraph Store), 평가(RAGAS·LLM-as-Judge) 패턴 참고

## Supervisor 라우팅 규칙
- 운동 관련 질문(무게·조합·부상 등) → `workout_agent`
- 식단 관련 질문(칼로리·매크로·커팅/벌킹 등) → `diet_agent`
- 둘 다 섞인 질문 → 두 에이전트를 순서대로 모두 호출해 하나의 답변으로 종합

## workout_agent 판단 규칙
- 과부하 신호: **반복수 증가가 무게 증가보다 우선.** 반복수가 2주 이상 정체면
  무게 조정 또는 조합 변경 검토
- 회복 판정 순서
  1. 마지막 훈련 후 24시간 이내 재훈련 → 항상 회복부족
  2. 근육통이 강함 → 경과 시간 무관 항상 회복부족 (48시간 지나도 강한 통증이면 회복부족)
  3. 근육통 약함/없음 + 24~48시간 → 회복부족
  4. 근육통 약함/없음 + 48시간 이상 → 회복 완료
- 유산소 상호작용: 웨이트 당일 고강도 유산소 30분 이상 → 회복 방해로 판정.
  다른 날이면 문제 없음
- 분할 카테고리: 상체(등 제외) / 등 / 하체 3종으로 분류
- 부상 호소: 증상(근육/힘줄 등) 확인 질문 → 2~3일 휴식 권고 → 재확인 후 지속 시
  병원 안내. **진단·처방은 절대 하지 않는다**
- 장기 검증: 체지방률/근육량(월 1회) 추세로 프로그램 효과 검증 — 체지방 유지+근육량
  증가면 조합 적절, 반대면 조합 재검토

## diet_agent 판단 규칙
- BMR은 Mifflin-St Jeor 공식 사용
  - 남성: `10×체중(kg) + 6.25×키(cm) - 5×나이 + 5`
  - 여성: `10×체중(kg) + 6.25×키(cm) - 5×나이 - 161`
  - TDEE = BMR × 활동계수, 목표별 조정: 커팅 -15~20% / 벌킹 +10~15% / 유지 동일
- 단백질 기준(체중 kg당): 벌킹 1.4~2.2g(고강도 시 1.6g 이상) · 유지 1.2~1.6g ·
  커팅 1.8~2.4g(근손실 방지 위해 벌킹보다 높게) · 가벼운 운동만 할 때 1.0~1.4g
- 목표(커팅/벌킹/유지)와 체지방률/근육량 추세를 비교해 방향(칼로리 조정 필요 vs 유지)을 조언
- 극단적 저칼로리 요청은 **거부하고 경고 문구를 포함**한다

## 공통 가드레일
- 판단이 애매하면 단정하지 않고, 답변에 불확실성·재확인 권장 문구를 반드시 포함한다
  (미탐이 오탐보다 위험 — 애매하면 안전한 쪽으로)
- `retrieve_guideline`으로 찾은 근거가 없으면 답을 지어내지 않고 "관련 원칙을
  찾지 못했다"고 답한다
- 개인 신체정보(키·몸무게·나이·운동/식단 기록 등)는 외부로 전송·공유하지 않는다

## 장기 메모리
- LangGraph Store에 운동/식단 기록, 체지방률/근육량, 프로필을 저장 (서버 재시작 후에도 유지)
- 오래된 기록 중 같은 무게가 반복되는 구간은 주간 요약으로 압축해 저장 부담을 줄인다

## 데이터
- `data/training_guidelines.md` — 운동 가이드라인 (RAG 소스)
- `data/nutrition_guidelines.md` — 영양 가이드라인 (RAG 소스)
- 운동 기록(9종목 × 1년치, 더미) · 식단 기록(1년치, 더미) · 체지방률/근육량(월 1회, 더미)
  · 사용자 프로필(키·몸무게·나이·성별·목표·활동수준) — 전부 더미로 진행, 실제 데이터 연동은
  이번 스코프 밖

## 반드시 해야 할 것
- 모든 판정 답변에는 근거(어떤 원칙 문서 또는 어떤 과거 기록)를 인용한다
- 모든 도구 호출은 `trace`에 기록해 어떤 도구를 거쳤는지 남긴다
- 애매한 판단에는 반드시 불확실성·재확인 권장 문구를 포함한다
- 새 세션 기록이 들어오면 판단 전에 반드시 `get_workout_history`/`get_diet_history`로
  과거 이력을 먼저 조회한다 (장기 메모리 없이 이번 기록만 보고 판단하지 않는다)

## 웹 데모 페이지 (선택)
- FastAPI 서버에 정적 페이지 하나(`static/index.html` 또는 동일 위치)를 붙여
  `POST /query`를 호출하는 최소한의 입력창+결과창만 만든다
- 디자인 스킬(예: hallmark류)은 쓰지 않는다 — 채점 기준에 UI 디자인 항목이 없고
  개발 시간을 에이전트 로직·데이터·RAG에 우선 써야 하므로, 기능만 되는 기본 UI로 충분

## 하지 말 것
- 요청하지 않은 파일을 새로 만들지 않는다
- 기존 파일을 통째로 다시 쓰지 않는다. 바뀐 부분만 고친다
- `read_workout_log`(세션 텍스트 파싱 도구)는 만들지 않는다 — 더미데이터를 미리
  DB/Store에 시딩하는 방식이라 불필요
- 실제 사용자 데이터 연동, 진단/처방, HITL 인터럽트(단발성 API 구조에 안 맞음)는
  이번 스코프에 넣지 않는다
