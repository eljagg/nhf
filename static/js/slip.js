// Pick-up slip: Print button (no inline handlers under the CSP).
(function () {
  "use strict";
  var b = document.getElementById("print-slip");
  if (b) b.addEventListener("click", function () { window.print(); });
})();
