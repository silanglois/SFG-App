// Render pymdownx.arithmatex "generic" output with locally-vendored KaTeX.
// generic mode emits inline  \( ... \)  and block  \[ ... \]  delimiters.
// Everything here runs from file:// with no network access.
(function () {
  function render() {
    if (typeof renderMathInElement !== "function") return;
    renderMathInElement(document.body, {
      delimiters: [
        { left: "\\(", right: "\\)", display: false },
        { left: "\\[", right: "\\]", display: true }
      ],
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code"],
      throwOnError: false
    });
  }
  // Material exposes document$ when instant navigation is on. Instant nav is
  // disabled here (it needs XHR, which breaks under file://), but subscribe to
  // it too so re-enabling it later doesn't silently stop math from rendering
  // on client-side page loads.
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(render);
  } else {
    document.addEventListener("DOMContentLoaded", render);
  }
})();
