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
  // Signature pad: <canvas data-signature-pad="hidden-input-id">. Mouse, pen tablet or touch screen.
  function initPad(canvas) {
    var input = document.getElementById(canvas.getAttribute("data-signature-pad"));
    if (!input) return;
    var ctx = canvas.getContext("2d"), drawing = false, drawn = false, last = null;
    function size() {
      var ratio = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
      canvas.width = w * ratio; canvas.height = h * ratio;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.lineWidth = 2.2; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = "#0f172a";
      ctx.fillStyle = "#ffffff"; ctx.fillRect(0, 0, w, h);
    }
    function pos(e) { var r = canvas.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; }
    size();
    canvas.addEventListener("pointerdown", function (e) { drawing = true; last = pos(e); canvas.setPointerCapture(e.pointerId); e.preventDefault(); });
    canvas.addEventListener("pointermove", function (e) {
      if (!drawing) return;
      var p = pos(e);
      ctx.beginPath(); ctx.moveTo(last.x, last.y); ctx.lineTo(p.x, p.y); ctx.stroke();
      last = p; drawn = true;
    });
    function end() {
      if (!drawing) return;
      drawing = false;
      if (drawn) { input.value = canvas.toDataURL("image/png"); input.disabled = false; }
      var status = document.getElementById(canvas.id + "-status");
      if (status && drawn) status.textContent = "Signature captured — it is saved when you press Save and check.";
    }
    canvas.addEventListener("pointerup", end);
    canvas.addEventListener("pointercancel", end);
    canvas.addEventListener("pointerleave", end);
    var clear = document.querySelector('[data-signature-clear="' + canvas.id + '"]');
    if (clear) clear.addEventListener("click", function (e) {
      e.preventDefault(); size(); drawn = false; input.value = ""; input.disabled = true;
      var status = document.getElementById(canvas.id + "-status");
      if (status) status.textContent = "Cleared.";
    });
  }
  document.querySelectorAll("canvas[data-signature-pad]").forEach(initPad);
  // Section B / JCPD blocks follow their tick-boxes (server rules are authoritative)
  document.querySelectorAll("[data-show-when]").forEach(function (block) {
    var names = block.getAttribute("data-show-when").split(" ");
    function update() {
      var on = names.some(function (n) {
        var el = document.getElementById(n);
        return el && (el.type === "checkbox" ? el.checked : !!el.value);
      });
      block.classList.toggle("opacity-60", !on);
    }
    names.forEach(function (n) { var el = document.getElementById(n); if (el) el.addEventListener("change", update); });
    update();
  });
  // Report pages: print button and auto-submit selects (no inline handlers under the CSP).
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-print]")) { e.preventDefault(); window.print(); }
  });
  document.addEventListener("change", function (e) {
    var el = e.target.closest("[data-autosubmit]");
    if (el && el.form) {
      el.form.querySelectorAll("[name=col],[name=group],[name^=f]").forEach(function (x) { if (x !== el) x.disabled = true; });
      el.form.submit();
    }
  });
})();
