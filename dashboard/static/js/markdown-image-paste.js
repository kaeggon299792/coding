document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("textarea[data-image-paste]").forEach((textarea) => {
    const status = document.querySelector(`[data-image-paste-status="${textarea.id}"]`);
    const setStatus = (message, isError = false) => {
      if (!status) return;
      status.textContent = message;
      status.classList.toggle("is-error", isError);
    };
    const insertMarkdown = (url) => {
      const markdown = `![붙여넣은 이미지](${url})`;
      const start = textarea.selectionStart ?? textarea.value.length;
      const end = textarea.selectionEnd ?? start;
      const prefix = start > 0 && textarea.value[start - 1] !== "\n" ? "\n\n" : "";
      const suffix = end < textarea.value.length && textarea.value[end] !== "\n" ? "\n\n" : "";
      const inserted = `${prefix}${markdown}${suffix}`;
      if (textarea.maxLength > 0 && textarea.value.length - (end - start) + inserted.length > textarea.maxLength) {
        setStatus("본문 최대 길이를 초과해 이미지를 넣지 못했습니다.", true);
        return false;
      }
      textarea.setRangeText(inserted, start, end, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    };
    const uploadImage = async (image) => {
      setStatus("이미지를 업로드하고 있습니다…");
      const formData = new FormData();
      formData.append("image", image, image.name || "clipboard-image");
      formData.append("scope", textarea.dataset.imagePasteScope || "");
      formData.append("csrf_token", textarea.dataset.imagePasteCsrf || "");
      try {
        const response = await fetch(textarea.dataset.imagePasteEndpoint, {
          method: "POST", body: formData, credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.url) throw new Error(payload.error || "이미지를 업로드하지 못했습니다.");
        if (insertMarkdown(payload.url)) setStatus("이미지를 본문에 넣었습니다.");
      } catch (error) {
        setStatus(error.message || "이미지를 업로드하지 못했습니다.", true);
      }
    };
    textarea.addEventListener("paste", async (event) => {
      const image = [...(event.clipboardData?.items || [])]
        .find((item) => item.kind === "file" && item.type.startsWith("image/"))
        ?.getAsFile();
      if (!image) return;
      event.preventDefault();
      await uploadImage(image);
    });
    const fileInput = document.querySelector(
      `[data-image-upload-for="${textarea.id}"]`
    );
    fileInput?.addEventListener("change", async () => {
      const image = fileInput.files?.[0];
      if (!image) return;
      await uploadImage(image);
      fileInput.value = "";
    });
  });
});
