document.addEventListener("DOMContentLoaded", () => {
  const primaryCommentEditor = document.querySelector(
    ".community-comment-form textarea[data-image-paste]"
  );
  if (primaryCommentEditor) {
    document.querySelectorAll(
      ".community-comment-list form textarea[name='content']:not([data-image-paste])"
    ).forEach((textarea, index) => {
      textarea.id ||= `comment-reply-${index + 1}`;
      textarea.dataset.imagePaste = "";
      ["Scope", "Purpose", "Target", "Endpoint", "Csrf"].forEach((suffix) => {
        textarea.dataset[`imagePaste${suffix}`] = primaryCommentEditor.dataset[`imagePaste${suffix}`] || "";
      });
      const picker = document.createElement("label");
      picker.className = "comment-image-picker";
      picker.innerHTML = `<span>사진 첨부</span><input type="file" accept="image/png,image/jpeg,image/gif,image/webp" data-image-upload-for="${textarea.id}">`;
      const status = document.createElement("small");
      status.className = "image-paste-status";
      status.dataset.imagePasteStatus = textarea.id;
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      textarea.insertAdjacentElement("afterend", picker);
      picker.insertAdjacentElement("afterend", status);
    });
  }
  document.querySelectorAll("textarea[data-image-paste]").forEach((textarea) => {
    if (textarea.dataset.wysiwygReady === "1") return;
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
        return null;
      }
      textarea.setRangeText(inserted, start, end, "end");
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
      return { markdown, inserted };
    };
    const showPreview = (url, insertion) => {
      if (!status || !insertion) return;
      status.parentElement?.querySelector(".comment-image-preview")?.remove();
      const preview = document.createElement("div");
      preview.className = "comment-image-preview";
      const image = document.createElement("img");
      image.src = url;
      image.alt = "첨부 이미지 미리보기";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-ghost btn-small";
      remove.textContent = "이미지 제거";
      remove.addEventListener("click", () => {
        const index = textarea.value.indexOf(insertion.markdown);
        if (index >= 0) {
          textarea.setRangeText("", index, index + insertion.markdown.length, "end");
          textarea.dispatchEvent(new Event("input", { bubbles: true }));
        }
        preview.remove();
        setStatus("첨부 이미지를 댓글에서 제거했습니다.");
      });
      preview.append(image, remove);
      status.insertAdjacentElement("afterend", preview);
    };
    const uploadImage = async (image) => {
      setStatus("이미지를 업로드하고 있습니다…");
      const formData = new FormData();
      formData.append("image", image, image.name || "clipboard-image");
      formData.append("scope", textarea.dataset.imagePasteScope || "");
      formData.append("purpose", textarea.dataset.imagePastePurpose || "");
      formData.append("target_id", textarea.dataset.imagePasteTarget || "");
      formData.append("csrf_token", textarea.dataset.imagePasteCsrf || "");
      try {
        const response = await fetch(textarea.dataset.imagePasteEndpoint, {
          method: "POST", body: formData, credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.url) throw new Error(payload.error || "이미지를 업로드하지 못했습니다.");
        const insertion = insertMarkdown(payload.url);
        if (insertion) {
          showPreview(payload.url, insertion);
          setStatus("이미지를 본문에 넣었습니다.");
        }
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
