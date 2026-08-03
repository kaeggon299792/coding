(() => {
  const button = document.querySelector("[data-community-share]");
  const status = document.querySelector("[data-community-share-status]");
  if (!button || !status) return;

  button.addEventListener("click", async () => {
    const shareData = {
      title: button.dataset.shareTitle || document.title,
      text: button.dataset.shareTitle || document.title,
      url: window.location.href,
    };
    try {
      if (navigator.share) {
        await navigator.share(shareData);
        status.textContent = "공유 창을 열었습니다.";
      } else {
        await navigator.clipboard.writeText(window.location.href);
        status.textContent = "주소를 복사했습니다.";
      }
    } catch (error) {
      if (error?.name !== "AbortError") status.textContent = "주소를 복사하지 못했습니다.";
    }
  });
})();
