// Counter conveniences. No inline scripts (CSP nonce policy).
(function () {
  "use strict";
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      var q = document.getElementById("q-top");
      if (q) { e.preventDefault(); q.focus(); q.select(); }
    }
  });
  // Light / dark mode: remembered per browser; first visit follows the system setting.
  document.addEventListener("click", function (e) {
    if (!e.target.closest("#theme-toggle")) return;
    var dark = document.documentElement.classList.toggle("dark");
    try { localStorage.setItem("nhf-theme", dark ? "dark" : "light"); } catch (err) { /* private mode: still switches for this page */ }
  });
  // Confirm buttons: <button data-confirm="...">
  document.addEventListener("click", function (e) {
    var el = e.target.closest("[data-confirm]");
    if (el && !window.confirm(el.getAttribute("data-confirm"))) { e.preventDefault(); e.stopPropagation(); }
  }, true);
  // Show/hide guardian block live when DOB is known (server rules are authoritative)
  document.addEventListener("change", function (e) {
    if (e.target.matches("[data-toggle-target]")) {
      var t = document.getElementById(e.target.getAttribute("data-toggle-target"));
      if (t) t.classList.toggle("hidden", !e.target.checked);
    }
  });
})();
