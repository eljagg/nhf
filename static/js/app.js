// Counter conveniences. No inline scripts (CSP nonce policy).
(function () {
  "use strict";
  document.addEventListener("keydown", function (e) {
    if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) {
      var q = document.getElementById("q-top");
      if (q) { e.preventDefault(); q.focus(); q.select(); }
    }
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
