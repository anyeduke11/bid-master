/* ============================================================
   Duke / Portfolio — Interactions
   - One-time fade-in + slide-up on scroll (IntersectionObserver)
   - Toast on placeholder actions
   - Respects prefers-reduced-motion
   ============================================================ */

(function () {
  "use strict";

  var prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* --- Scroll reveal --- */
  (function () {
    var targets = Array.prototype.slice.call(document.querySelectorAll("[data-reveal]"));

    if (prefersReducedMotion || !("IntersectionObserver" in window)) {
      targets.forEach(function (el) { el.classList.add("is-visible"); });
      return;
    }

    document.documentElement.classList.add("motion-ready");

    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.08 }
    );

    targets.forEach(function (el) { observer.observe(el); });
  })();

  /* --- Toast on data-toast clicks --- */
  (function () {
    var toast = document.querySelector(".toast");
    var msg = toast ? toast.querySelector("p") : null;
    var timer = null;

    function showToast(text) {
      if (!toast || !msg) return;
      if (timer) clearTimeout(timer);
      msg.textContent = text || "该项内容正在整理中。";
      toast.classList.add("is-visible");
      timer = setTimeout(function () {
        toast.classList.remove("is-visible");
      }, 2800);
    }

    document.addEventListener("click", function (event) {
      var target = event.target && event.target.closest ? event.target.closest("[data-toast]") : null;
      if (!target) return;
      event.preventDefault();
      showToast(target.getAttribute("data-toast"));
    });
  })();

  /* --- Subtle parallax on hero identity scene (mouse-driven) --- */
  (function () {
    if (prefersReducedMotion) return;

    var scene = document.querySelector(".identity-scene");
    if (!scene) return;

    var raf = null;
    var tx = 0, ty = 0;

    function update() {
      var svg = scene.querySelector(".scene-svg");
      if (svg) {
        svg.style.transform = "translate(" + tx.toFixed(2) + "px, " + ty.toFixed(2) + "px) scale(1)";
      }
      raf = null;
    }

    scene.addEventListener("mousemove", function (e) {
      var rect = scene.getBoundingClientRect();
      var dx = (e.clientX - (rect.left + rect.width / 2)) / rect.width;
      var dy = (e.clientY - (rect.top + rect.height / 2)) / rect.height;
      tx = dx * -6;
      ty = dy * -4;
      if (!raf) raf = requestAnimationFrame(update);
    });

    scene.addEventListener("mouseleave", function () {
      tx = 0; ty = 0;
      var svg = scene.querySelector(".scene-svg");
      if (svg) {
        svg.style.transition = "transform 600ms cubic-bezier(0.22, 1, 0.36, 1)";
        svg.style.transform = "translate(0, 0) scale(1)";
        setTimeout(function () { svg.style.transition = ""; }, 700);
      }
    });
  })();

  /* --- Mark year in footer meta dynamically --- */
  (function () {
    var yearEl = document.querySelector("[data-year]");
    if (yearEl) yearEl.textContent = String(new Date().getFullYear());
  })();
})();
