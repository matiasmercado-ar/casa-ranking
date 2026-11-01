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

// /houses/new#manual opens the manual form directly.
if (location.hash === "#manual") document.getElementById("manual")?.setAttribute("open", "");

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
        bd.textContent = s.base === null ? "" :
          bd.dataset.tpl.replace("{base}", s.base.toFixed(1)).replace("{q}", (s.questions ?? 0).toFixed(1));
      }
      document.querySelectorAll("#people .person").forEach((el) => {
        const v = s.people[el.dataset.uid];
        el.classList.toggle("missing", v === undefined);
        el.querySelector(".person-val").textContent = v === undefined ? "–" : v.toFixed(1);
      });
      const amen = document.getElementById("amen");
      if (amen) amen.textContent = amen.textContent.replace(/\d+\/\d+/, `${s.amenities_yes}/${s.amenities_total}`);
      state.textContent = "✓ " + form.dataset.saved;
    } catch (e) {
      if (e.name !== "AbortError") state.textContent = "⚠ " + e.message;
    }
  }

  function changed(e) {
    if (e.target.matches(".stars input")) paintRow(e.target);
    clearTimeout(timer);
    timer = setTimeout(save, 250);
  }
  form.addEventListener("change", changed);
  // Fields of this form placed elsewhere on the page (form="scores"), like Activa / Favorita / Descartada.
  document.querySelectorAll('[form="scores"]').forEach((el) => el.addEventListener("change", changed));
})();

// Stage buttons (next step) and the "Cambiar estado" menu: change it in place, keeping the scroll position.
// Without JS they are plain POST forms. The server answers {stage} or, for a visit with no day yet, {redirect}.
document.querySelectorAll(".stage-form").forEach((form) => {
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = e.submitter || form.querySelector("button");
    const body = new FormData(form);
    if (btn && btn.name) body.set(btn.name, btn.value);
    if (btn) btn.disabled = true;
    try {
      const res = await fetch(form.action, { method: "POST", body, headers: { Accept: "application/json" } });
      if (!res.ok) throw new Error(res.status);
      const s = await res.json();
      if (s.redirect) { location.href = s.redirect; return; }
      const holder = form.closest("[data-stage]") || document.querySelector("[data-stage]");
      // Every stage widget on the house page follows (photo label, stage bar).
      (holder.classList.contains("card") ? [holder] : document.querySelectorAll("[data-stage]"))
        .forEach((el) => (el.dataset.stage = s.stage));
      form.closest("details")?.removeAttribute("open");
      if (holder.classList.contains("card")) {
        // On a filtered tab, a house that no longer belongs there is dimmed until the next reload.
        const old = { visitadas: "visitada", sin_visitar: "ninguna" };
        let tab = new URLSearchParams(location.search).get("tab") || "todas";
        tab = old[tab] || tab;
        const inTab = tab === "todas" || tab === s.stage || (tab === "ir" && ["a_visitar", "contactada", "agendada"].includes(s.stage));
        holder.classList.toggle("left-tab", !inTab);
      }
    } catch (err) {
      // Fall back to a normal POST, keeping which menu item was picked.
      if (btn && btn.name) {
        const keep = document.createElement("input");
        Object.assign(keep, { type: "hidden", name: btn.name, value: btn.value });
        form.append(keep);
      }
      HTMLFormElement.prototype.submit.call(form);
    } finally {
      if (btn) btn.disabled = false;
    }
  });
});
// Close an open stage menu when clicking elsewhere.
document.addEventListener("click", (e) => {
  document.querySelectorAll(".stage-menu[open]").forEach((d) => { if (!d.contains(e.target)) d.removeAttribute("open"); });
});

// Comments: switch between all / online / in person without reloading.
(function () {
  const box = document.getElementById("comments");
  if (!box) return;
  box.querySelectorAll(".ctabs a").forEach((a) => {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const kind = a.dataset.show;
      box.dataset.show = kind;
      box.querySelectorAll(".ctabs a").forEach((x) => x.toggleAttribute("aria-current", x === a));
      const radio = box.querySelector(`.kind-toggle input[value="${kind}"]`);
      if (radio) radio.checked = true;
      history.replaceState(null, "", a.getAttribute("href"));
    });
  });
  // Stored in UTC; show in the viewer's local time.
  box.querySelectorAll("time[datetime]").forEach((el) => {
    const d = new Date(el.getAttribute("datetime"));
    if (!isNaN(d)) el.textContent = d.toLocaleString(document.documentElement.lang, { dateStyle: "short", timeStyle: "short" });
  });
})();
