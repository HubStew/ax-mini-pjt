const form = document.getElementById("query-form");
const questionInput = document.getElementById("question");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const resultEl = document.getElementById("result");
const answerEl = document.getElementById("answer");
const contextsEl = document.getElementById("contexts");
const traceEl = document.getElementById("trace");

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
