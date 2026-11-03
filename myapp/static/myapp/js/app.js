/* LearnMate AI shared helpers. Plain ES6, no build step. */
(function () {
  "use strict";
  const csrf = () => (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  window.LM = {
    csrf,
    async post(url, body, opts = {}) {
      const isForm = body instanceof FormData;
      const res = await fetch(url, {
        method: "POST", credentials: "same-origin",
        headers: Object.assign({ "X-CSRFToken": csrf() }, isForm ? {} : { "Content-Type": "application/json" }),
        body: isForm ? body : JSON.stringify(body || {}), signal: opts.signal,
      });
      let data = {};
      try { data = await res.json(); } catch (e) { data = { ok: false, error: "The server sent an unexpected reply." }; }
      data._status = res.status;
      return data;
    },
    toast(msg, kind = "dark") {
      const zone = document.getElementById("toastZone");
      if (!zone) return;
      const el = document.createElement("div");
      el.className = `toast align-items-center text-bg-${kind} border-0 show`;
      el.setAttribute("role", "status");
      el.innerHTML = '<div class="d-flex"><div class="toast-body"></div><button class="btn-close btn-close-white me-2 m-auto" aria-label="Close"></button></div>';
      el.querySelector(".toast-body").textContent = msg;
      el.querySelector("button").onclick = () => el.remove();
      zone.appendChild(el);
      setTimeout(() => el.remove(), 4500);
    },
    chart(id, type, labels, values, label, opts = {}) {
      const el = document.getElementById(id);
      if (!el || !window.Chart) return;
      return new Chart(el, {
        type, data: { labels, datasets: [{ label, data: values, backgroundColor: opts.color || "#4338CA", borderColor: opts.line || "#4338CA", borderRadius: 4, tension: .3, fill: false }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
          scales: { y: { beginAtZero: true, max: opts.max, grid: { color: "#E2E8F0" }, ticks: { color: "#64748B" } }, x: { grid: { display: false }, ticks: { color: "#64748B" } } } },
      });
    },
  };

  const app = document.querySelector(".app");
  const btn = document.getElementById("sidebarToggle");
  try { if (localStorage.getItem("lm.collapsed") === "1") app?.classList.add("collapsed"); } catch (e) {}
  btn?.addEventListener("click", () => {
    if (window.innerWidth < 992) { bootstrap.Offcanvas.getOrCreateInstance(document.getElementById("mobileNav")).show(); return; }
    app.classList.toggle("collapsed");
    try { localStorage.setItem("lm.collapsed", app.classList.contains("collapsed") ? "1" : "0"); } catch (e) {}
  });

  document.addEventListener("submit", (e) => {
    const msg = e.target.dataset.confirm;
    if (msg && !window.confirm(msg)) e.preventDefault();
  });
})();

/* Bootstrap classes for Django-rendered inputs */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("form input, form textarea, form select").forEach((el) => {
    const t = (el.type || "").toLowerCase();
    if (["hidden", "submit", "button"].includes(t) || el.classList.contains("no-style")) return;
    if (t === "checkbox" || t === "radio") el.classList.add("form-check-input");
    else if (el.tagName === "SELECT") el.classList.add("form-select");
    else el.classList.add("form-control");
  });
});
