// Wires .quiz-q blocks. Markup contract:
// <div class="quiz-q" data-answer="IDX"><p class="stem">…</p>
//   <div class="options"><button>…</button>…</div>
//   <p class="explain" hidden>…</p></div>
document.querySelectorAll(".quiz-q").forEach((q) => {
  const answer = Number(q.dataset.answer);
  const explain = q.querySelector(".explain");
  q.querySelectorAll(".options button").forEach((btn, i) => {
    btn.addEventListener("click", () => {
      if (q.classList.contains("done")) return;
      if (i === answer) {
        btn.classList.add("correct");
        q.classList.add("done");
        q.querySelectorAll(".options button").forEach((b) => (b.disabled = true));
        if (explain) explain.hidden = false;
      } else {
        btn.classList.add("wrong");
        btn.disabled = true;
      }
    });
  });
});
