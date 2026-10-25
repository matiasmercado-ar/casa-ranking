// Progressive enhancement: the scores form works without JS (submit button in <noscript>);
// with JS every change is autosaved and the averages refresh in place.
(function () {
  const form = document.getElementById("scores");
  if (!form) return;
  const state = form.querySelector(".save-state");
  const fmt = (v) => (v === null || v === undefined ? "–" : v.toFixed(1));
  let timer, controller;

  function paintRow(input) {
    const row = input.closest(".rate-row");
    if (row) row.querySelector(".rate-val").textContent = input.value === "" ? "–" : input.value;
  }

  async function save() {
    if (controller) controller.abort();
    controller = new AbortController();
    state.textContent = "…";
    try {
      const res = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
      if (!res.ok) throw new Error(res.status);
      const s = await res.json();
      form.querySelectorAll(".topic-avg").forEach((el) => (el.textContent = fmt(s.topics[el.dataset.topic])));
      const badge = document.querySelector("#overall .badge");
      if (badge) {
        badge.textContent = fmt(s.overall);
        badge.classList.toggle("none", s.overall === null);
        badge.style.setProperty("--s", s.overall ?? 0);
      }
      const amen = document.getElementById("amen");
      if (amen) amen.textContent = amen.textContent.replace(/\d+\/\d+/, `${s.amenities_yes}/${s.amenities_total}`);
      state.textContent = "✓ " + form.dataset.saved;
    } catch (e) {
      if (e.name !== "AbortError") state.textContent = "⚠ " + e.message;
    }
  }

  form.addEventListener("change", (e) => {
    if (e.target.matches(".stars input")) paintRow(e.target);
    clearTimeout(timer);
    timer = setTimeout(save, 250);
  });
})();
