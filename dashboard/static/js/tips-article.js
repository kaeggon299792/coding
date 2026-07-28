document.addEventListener("DOMContentLoaded", () => {
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
