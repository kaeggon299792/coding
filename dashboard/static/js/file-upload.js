(() => {
  const COPY = {
    ko: {button: "파일 선택", empty: "선택된 파일 없음", more: (count) => `외 ${count}개`},
    en: {button: "Choose file", empty: "No file selected", more: (count) => `and ${count} more`},
    ja: {button: "ファイルを選択", empty: "ファイルが選択されていません", more: (count) => `ほか${count}件`},
    "yue-hk": {button: "選擇檔案", empty: "未選擇檔案", more: (count) => `另有${count}個`},
  };

  const locale = (document.documentElement.lang || "ko").toLowerCase();
  const copy = COPY[locale] || COPY.ko;

  const filename = (input) => {
    const files = Array.from(input.files || []);
    if (!files.length) return input.dataset.fileEmptyLabel || copy.empty;
    if (files.length === 1) return files[0].name;
    return `${files[0].name} ${copy.more(files.length - 1)}`;
  };

  const update = (input) => {
    const output = input.closest(".file-upload-control")?.querySelector(".file-upload-name");
    if (!output) return;
    output.textContent = filename(input);
    output.title = Array.from(input.files || []).map((file) => file.name).join(", ");
    output.classList.toggle("has-file", Boolean(input.files?.length));
  };

  const enhance = (input, index) => {
    if (!(input instanceof HTMLInputElement) || input.type !== "file") return;
    if (input.dataset.fileUiReady === "true" || input.dataset.fileUiIgnore === "true") return;
    if (input.closest(".markdown-image-button")) return;

    input.dataset.fileUiReady = "true";
    input.id ||= `site-file-upload-${index + 1}`;

    const fieldLabel = input.closest("label");
    const control = document.createElement(fieldLabel ? "span" : "label");
    control.className = "file-upload-control";
    if (!fieldLabel) control.htmlFor = input.id;

    const display = document.createElement("span");
    display.className = "file-upload-display";

    const button = document.createElement("span");
    button.className = "btn btn-outline file-upload-button";
    button.dataset.uiIcon = "upload";
    button.textContent = input.dataset.fileButtonLabel || copy.button;

    const name = document.createElement("small");
    name.className = "file-upload-name";
    name.setAttribute("aria-live", "polite");

    input.parentNode.insertBefore(control, input);
    control.append(input, display);
    display.append(button, name);
    input.classList.add("file-upload-input");
    input.addEventListener("change", () => update(input));
    update(input);
  };

  const enhanceAll = (root = document) => {
    if (root.matches?.('input[type="file"]')) enhance(root, 0);
    root.querySelectorAll?.('input[type="file"]').forEach(enhance);
  };

  enhanceAll();
  document.addEventListener("reset", (event) => {
    window.setTimeout(() => enhanceAll(event.target), 0);
    window.setTimeout(() => event.target.querySelectorAll?.(".file-upload-input").forEach(update), 0);
  });

  const observer = new MutationObserver((records) => {
    records.forEach((record) => record.addedNodes.forEach((node) => {
      if (node.nodeType === Node.ELEMENT_NODE) enhanceAll(node);
    }));
  });
  observer.observe(document.body, {childList: true, subtree: true});
})();
