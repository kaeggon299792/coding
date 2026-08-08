(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var COPY_ICON_PARTS = [
    ["rect", { x: "9", y: "9", width: "13", height: "13", rx: "2" }],
    ["path", { d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" }],
  ];

  function createCopyIcon() {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    COPY_ICON_PARTS.forEach(function (part) {
      var node = document.createElementNS(SVG_NS, part[0]);
      Object.keys(part[1]).forEach(function (key) { node.setAttribute(key, part[1][key]); });
      svg.appendChild(node);
    });
    return svg;
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var helper = document.createElement("textarea");
      helper.value = text;
      helper.setAttribute("readonly", "");
      helper.style.position = "fixed";
      helper.style.top = "0";
      helper.style.opacity = "0";
      document.body.appendChild(helper);
      helper.select();
      helper.setSelectionRange(0, text.length);
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (error) {
        ok = false;
      }
      helper.remove();
      if (ok) resolve();
      else reject(new Error("copy command failed"));
    });
  }

  function enhance(pre) {
    if (pre.dataset.codeCopyReady === "1") return;
    pre.dataset.codeCopyReady = "1";
    // Snapshot the code text before the button is appended so the button's
    // own label never becomes part of what gets copied.
    var text = pre.textContent;

    var button = document.createElement("button");
    button.type = "button";
    button.className = "code-copy-button";
    button.setAttribute("aria-label", "코드 복사");
    var label = document.createElement("span");
    label.textContent = "복사";
    button.append(createCopyIcon(), label);

    var resetTimer = null;
    button.addEventListener("click", function () {
      copyText(text).then(function () {
        window.clearTimeout(resetTimer);
        button.classList.remove("is-error");
        button.classList.add("is-copied");
        label.textContent = "복사됨";
        resetTimer = window.setTimeout(function () {
          button.classList.remove("is-copied");
          label.textContent = "복사";
        }, 1600);
      }).catch(function () {
        window.clearTimeout(resetTimer);
        button.classList.add("is-error");
        label.textContent = "복사 실패";
        resetTimer = window.setTimeout(function () {
          button.classList.remove("is-error");
          label.textContent = "복사";
        }, 1600);
      });
    });

    pre.appendChild(button);
  }

  function initialize() {
    document.querySelectorAll(".community-markdown pre, .tip-body pre").forEach(enhance);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
