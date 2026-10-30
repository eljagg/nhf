// "How to apply" walk-through: channel tabs and an auto-advancing stepper per channel.
// Without JavaScript every stage is shown in order (see the noscript-friendly fallback below).
(function () {
  "use strict";
  var STEP_MS = 7000;
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function Flow(root) {
    this.root = root;
    this.nodes = Array.prototype.slice.call(root.querySelectorAll(".flow-node"));
    this.stages = Array.prototype.slice.call(root.querySelectorAll("[data-stage]"));
    this.fill = root.querySelector(".flow-fill");
    this.bar = root.querySelector(".flow-progress");
    this.playBtn = root.querySelector("[data-flow-play]");
    this.index = 0;
    this.playing = !reduced;
    this.timer = null;
    var self = this;
    this.nodes.forEach(function (n, i) { n.addEventListener("click", function () { self.stop(); self.go(i); }); });
    root.querySelector("[data-flow-prev]").addEventListener("click", function () { self.stop(); self.go(self.index - 1); });
    root.querySelector("[data-flow-next]").addEventListener("click", function () { self.stop(); self.go(self.index + 1); });
    this.playBtn.addEventListener("click", function () { if (self.playing) { self.stop(); } else { self.playing = true; self.go(self.index + 1 >= self.stages.length ? 0 : self.index); } });
    root.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { self.stop(); self.go(self.index + 1); }
      if (e.key === "ArrowLeft") { self.stop(); self.go(self.index - 1); }
    });
    if (this.bar) this.bar.style.setProperty("--flow-ms", STEP_MS + "ms");
  }
  Flow.prototype.go = function (i) {
    var last = this.stages.length - 1;
    this.index = Math.max(0, Math.min(last, i));
    var idx = this.index;
    this.stages.forEach(function (s, k) { s.classList.toggle("active", k === idx); });
    this.nodes.forEach(function (n, k) {
      n.classList.toggle("active", k === idx);
      n.classList.toggle("done", k < idx);
      if (k === idx) { n.setAttribute("aria-current", "step"); } else { n.removeAttribute("aria-current"); }
    });
    if (this.fill) this.fill.style.width = (last ? (idx / last) * 100 : 0) + "%";
    this.schedule();
  };
  Flow.prototype.schedule = function () {
    var self = this;
    clearTimeout(this.timer);
    if (this.bar) { this.bar.classList.remove("run"); void this.bar.offsetWidth; }
    this.playBtn.textContent = this.playing ? "Pause" : "Play";
    this.playBtn.setAttribute("aria-pressed", this.playing ? "true" : "false");
    if (!this.playing || this.root.classList.contains("hidden")) return;
    if (this.index >= this.stages.length - 1) { this.playing = false; this.playBtn.textContent = "Replay"; this.playBtn.setAttribute("aria-pressed", "false"); return; }
    if (this.bar) this.bar.classList.add("run");
    this.timer = setTimeout(function () { self.go(self.index + 1); }, STEP_MS);
  };
  Flow.prototype.stop = function () { this.playing = false; clearTimeout(this.timer); if (this.bar) this.bar.classList.remove("run"); };

  var flows = {};
  document.querySelectorAll("[data-flow]").forEach(function (root) {
    flows[root.id.replace("flow-", "")] = new Flow(root);
  });
  Object.keys(flows).forEach(function (k) { flows[k].go(0); });

  var tabs = Array.prototype.slice.call(document.querySelectorAll("[data-flow-tab]"));
  function show(name) {
    tabs.forEach(function (t) {
      var on = t.getAttribute("data-flow-tab") === name;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      document.getElementById("flow-" + t.getAttribute("data-flow-tab")).classList.toggle("hidden", !on);
    });
    Object.keys(flows).forEach(function (k) { if (k !== name) flows[k].stop(); });
    var f = flows[name];
    f.playing = !reduced;
    f.go(0);
  }
  tabs.forEach(function (t, i) {
    t.addEventListener("click", function () { show(t.getAttribute("data-flow-tab")); });
    t.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
      next.focus(); show(next.getAttribute("data-flow-tab"));
    });
  });
  var fromHash = (location.hash || "").replace("#", "");
  if (flows[fromHash]) show(fromHash);
})();
