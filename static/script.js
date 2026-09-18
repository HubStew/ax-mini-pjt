const form = document.getElementById("query-form");
const questionInput = document.getElementById("question");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const answerEl = document.getElementById("answer");
const contextsEl = document.getElementById("contexts");
const traceEl = document.getElementById("trace");
const profileInfoEl = document.getElementById("profile-info");
const workoutHistoryEl = document.getElementById("workout-history");
const dietHistoryEl = document.getElementById("diet-history");

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// 날짜 줄과 운동명을 굵게 표시한다. tools.py가 반환하는 원본 텍스트는 순수
// 텍스트라 LLM 컨텍스트에도 그대로 들어가는데, 여기 마크업을 섞으면 모델이
// 태그를 그대로 보게 되니 굵게 처리와 최신순 정렬은 화면 렌더링 시 프론트에서만
// 한다 (도구가 반환하는 원본 순서 - 오래된 순 - 는 에이전트 추세 판단용으로
// 그대로 둬야 해서 건드리지 않는다).
function splitIntoDateBlocks(text, dateLineRegex) {
  const blocks = [];
  let current = null;
  for (const line of text.split("\n")) {
    if (dateLineRegex.test(line)) {
      current = [line];
      blocks.push(current);
    } else if (current) {
      current.push(line);
    }
  }
  return blocks;
}

function formatWorkoutHistory(text) {
  const blocks = splitIntoDateBlocks(text, /^\d{4}-\d{2}-\d{2}$/);
  blocks.reverse();
  return blocks
    .map((block) =>
      block
        .map((line) => {
          if (/^\d{4}-\d{2}-\d{2}$/.test(line)) {
            return `<strong>${escapeHtml(line)}</strong>`;
          }
          const m = line.match(/^(  - )(.+?)(\(.*)$/);
          if (m) {
            return `${escapeHtml(m[1])}<strong>${escapeHtml(m[2])}</strong>${escapeHtml(m[3])}`;
          }
          return escapeHtml(line);
        })
        .join("\n")
    )
    .join("\n");
}

function formatDietHistory(text) {
  const dateLineRegex = /^\d{4}-\d{2}-\d{2} \(총 .*\)$/;
  const blocks = splitIntoDateBlocks(text, dateLineRegex);
  blocks.reverse();
  return blocks
    .map((block) =>
      block
        .map((line) =>
          dateLineRegex.test(line)
            ? `<strong>${escapeHtml(line)}</strong>`
            : escapeHtml(line)
        )
        .join("\n")
    )
    .join("\n");
}

async function loadStatus() {
  try {
    const res = await fetch("/status", { cache: "no-store" });
    if (!res.ok) throw new Error(`서버 오류 (${res.status})`);
    const data = await res.json();
    profileInfoEl.textContent = data.profile || "정보 없음";
    workoutHistoryEl.innerHTML = data.recent_workouts
      ? formatWorkoutHistory(data.recent_workouts)
      : "기록 없음";
    dietHistoryEl.innerHTML = data.recent_diet
      ? formatDietHistory(data.recent_diet)
      : "기록 없음";
  } catch (err) {
    profileInfoEl.textContent = `불러오기 실패: ${err.message}`;
    workoutHistoryEl.textContent = "-";
    dietHistoryEl.textContent = "-";
  }
}

loadStatus();

questionInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = questionInput.value.trim();
  if (!question) return;

  submitBtn.disabled = true;
  statusEl.textContent = "답변 생성 중...";
  statusEl.classList.remove("error");
  resultEl.hidden = true;

  try {
    const res = await fetch("/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });

    if (!res.ok) {
      throw new Error(`서버 오류 (${res.status})`);
    }

    const data = await res.json();
    renderResult(data);
    statusEl.textContent = "";
    loadStatus();
  } catch (err) {
    statusEl.textContent = `오류가 발생했습니다: ${err.message}`;
    statusEl.classList.add("error");
  } finally {
    submitBtn.disabled = false;
  }
});

function renderResult(data) {
  answerEl.textContent = data.answer || "(답변 없음)";

  contextsEl.innerHTML = "";
  if (data.contexts && data.contexts.length > 0) {
    for (const ctx of data.contexts) {
      const div = document.createElement("div");
      div.className = "context-item";
      div.textContent = `[${ctx.source}] ${ctx.text}`;
      contextsEl.appendChild(div);
    }
  } else {
    contextsEl.textContent = "근거 문서 없음";
  }

  traceEl.innerHTML = "";
  if (data.trace && data.trace.length > 0) {
    for (const step of data.trace) {
      const div = document.createElement("div");
      div.className = "trace-item";
      div.textContent = `[${step.step}] ${step.tool}(${JSON.stringify(step.input)})`;
      traceEl.appendChild(div);
    }
  } else {
    traceEl.textContent = "도구 호출 없음";
  }

  resultEl.hidden = false;
}
