// Theme: "auto" follows the OS; "light"/"dark" are stored per device.
(function () {
  const root = document.documentElement;
  const get = () => { try { return localStorage.getItem("theme") || "auto"; } catch (e) { return "auto"; } };
  function apply(theme) {
    try { theme === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", theme); } catch (e) {}
    if (theme === "auto") delete root.dataset.theme; else root.dataset.theme = theme;
    root.dataset.themeChoice = theme;
    const btn = document.querySelector("[data-theme-toggle]");
    if (btn) {
      const label = JSON.parse(btn.dataset.labels)[theme];
      btn.title = label;
      btn.setAttribute("aria-label", label);
    }
    document.querySelectorAll("[data-theme-seg] input").forEach((i) => (i.checked = i.value === theme));
  }
  apply(get());
  const order = ["auto", "light", "dark"];
  document.querySelector("[data-theme-toggle]")?.addEventListener("click", () => {
    apply(order[(order.indexOf(get()) + 1) % order.length]);
  });
  document.querySelector("[data-theme-seg]")?.addEventListener("change", (e) => apply(e.target.value));
})();

// Forms that read a listing take a second or two: say so and block double submits.
document.querySelectorAll("form[data-busy]").forEach((form) => {
  form.addEventListener("submit", () => {
    const btn = form.querySelector("button");
    if (!btn) return;
    btn.disabled = true;
    btn.classList.add("busy");
    btn.textContent = form.dataset.busy;
  });
});

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
      const bd = document.getElementById("breakdown");
      if (bd) {
        const sign = s.bonus >= 0 ? "+" : "−";
        bd.textContent = s.base === null ? "" :
          bd.dataset.tpl.replace("{base}", s.base.toFixed(1)).replace("{bonus}", sign + Math.abs(s.bonus).toFixed(1));
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
