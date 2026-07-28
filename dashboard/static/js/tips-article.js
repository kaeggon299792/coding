document.addEventListener("DOMContentLoaded", () => {
  const shareButton = document.getElementById("share-tip-link");
  if (shareButton) {
    shareButton.addEventListener("click", async () => {
      const originalLabel = shareButton.dataset.label || "공유";
      try {
        await navigator.clipboard.writeText(window.location.href);
        shareButton.textContent = "링크 복사됨";
      } catch (_) {
        const temporary = document.createElement("textarea");
        temporary.value = window.location.href;
        temporary.setAttribute("readonly", "");
        temporary.style.position = "fixed";
        temporary.style.opacity = "0";
        document.body.appendChild(temporary);
        temporary.select();
        const copied = document.execCommand("copy");
        temporary.remove();
        shareButton.textContent = copied ? "링크 복사됨" : "복사 실패";
      }
      setTimeout(() => { shareButton.textContent = originalLabel; }, 1600);
    });
  }

  document.querySelectorAll(".tip-body pre").forEach((block) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "code-copy";
    button.textContent = "복사";
    button.setAttribute("aria-label", "코드 블록 복사");
    button.addEventListener("click", async () => {
      const code = block.querySelector("code");
      try {
        await navigator.clipboard.writeText((code || block).innerText);
        button.textContent = "복사됨";
      } catch (_) {
        button.textContent = "복사 실패";
      }
      setTimeout(() => { button.textContent = "복사"; }, 1400);
    });
    block.appendChild(button);
  });
});
