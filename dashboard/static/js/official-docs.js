(() => {
  const category = document.querySelector("#official-category");
  const folder = document.querySelector("#official-folder-category");
  const video = document.querySelector("#video-exported");
  const pledge = document.querySelector("#export-pledge");
  const folderModeInputs = document.querySelectorAll('input[name="folder_handling_type"]');
  const existingFields = document.querySelector(".existing-folder-fields");
  const requestedPath = document.querySelector('input[name="requested_folder_path"]');
  const attachments = document.querySelector("#official-attachments");
  const pdfRequirement = document.querySelector("#pdf-requirement");
  const aiPrefillButton = document.querySelector("#official-ai-prefill");
  const aiStatus = document.querySelector("#official-ai-status");
  const aiWarnings = document.querySelector("#official-ai-warnings");
  const folderSearchButton = document.querySelector("#folder-index-search");
  const folderSearchQuery = document.querySelector("#folder-index-query");
  const folderSearchResults = document.querySelector("#folder-index-results");
  const folderBrowseButton = document.querySelector("#folder-browse-button");
  const folderBrowser = document.querySelector("#folder-browser");
  const folderBrowserClose = document.querySelector("#folder-browser-close");
  const folderBrowserPath = document.querySelector("#folder-browser-path");
  const folderBrowserList = document.querySelector("#folder-browser-list");
  const folderBrowserUp = document.querySelector("#folder-browser-up");
  const folderBrowserSelect = document.querySelector("#folder-browser-select");
  let browserPath = "";
  const browserHistory = [];
  const setupFieldSuggestions = (fieldName) => {
    const input = document.querySelector(`input[name="${fieldName}"]`);
    const list = document.querySelector(`#${fieldName}-suggestions`);
    if (!input || !list) return;
    let timer;
    let controller;
    const close = () => { list.hidden = true; list.replaceChildren(); };
    const search = () => {
      clearTimeout(timer);
      const term = input.value.trim();
      if (!term) { close(); return; }
      timer = setTimeout(async () => {
        controller?.abort();
        controller = new AbortController();
        try {
          const response = await fetch(
            `/official-docs/field-suggestions?field=${fieldName}&q=${encodeURIComponent(term)}`,
            {signal: controller.signal}
          );
          if (!response.ok) throw new Error("suggestion request failed");
          const data = await response.json();
          list.replaceChildren();
          if (!data.suggestions?.length) {
            const empty = document.createElement("div");
            empty.className = "field-suggestions-empty";
            empty.textContent = "기존 등록자료에서 같은 이름을 찾지 못했습니다.";
            list.append(empty);
          } else {
            data.suggestions.forEach((item) => {
              const button = document.createElement("button");
              button.type = "button";
              button.className = "field-suggestion";
              button.setAttribute("role", "option");
              const value = document.createElement("span");
              value.textContent = item.value;
              const count = document.createElement("small");
              count.textContent = `${item.use_count}건 등록`;
              button.append(value, count);
              button.addEventListener("mousedown", (event) => event.preventDefault());
              button.addEventListener("click", () => {
                input.value = item.value;
                close();
                input.focus();
              });
              list.append(button);
            });
          }
          list.hidden = false;
        } catch (error) {
          if (error.name !== "AbortError") close();
        }
      }, 220);
    };
    input.addEventListener("input", search);
    input.addEventListener("focus", search);
    input.addEventListener("blur", () => setTimeout(close, 120));
    input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") close();
    });
  };
  setupFieldSuggestions("manager");
  setupFieldSuggestions("organization");
  setupFieldSuggestions("registered_by");
  const excelDrive = document.querySelector("#excel-drive-letter");
  const applyExcelDrive = () => {
    if (!excelDrive) return;
    const drive = /^[A-Z]$/.test(excelDrive.value) ? excelDrive.value : "Y";
    localStorage.setItem("paradiseExcelDrive", drive);
    document.querySelectorAll(".excel-drive-value").forEach((input) => { input.value = drive; });
    document.querySelectorAll(".excel-export-link").forEach((link) => {
      const url = new URL(link.href, window.location.href);
      url.searchParams.set("drive_letter", drive);
      link.href = url.toString();
    });
  };
  if (excelDrive) {
    const savedDrive = (localStorage.getItem("paradiseExcelDrive") || "Y").toUpperCase();
    if (/^[A-Z]$/.test(savedDrive)) excelDrive.value = savedDrive;
    excelDrive.addEventListener("change", applyExcelDrive);
    applyExcelDrive();
  }
  const toggle = (select, selector, otherValue = "OTHER") => {
    const field = document.querySelector(selector);
    if (!field || !select) return;
    const visible = select.value === otherValue;
    field.hidden = !visible;
    const input = field.querySelector("input");
    if (input) input.required = visible;
  };
  const refresh = () => {
    toggle(category, ".conditional-other");
    toggle(folder, ".conditional-folder-other", "078");
    document.querySelector(".video-fields")?.classList.toggle("emphasized", category?.value === "04");
    const mode = document.querySelector('input[name="folder_handling_type"]:checked')?.value || "CREATE_NEW";
    if (existingFields) existingFields.hidden = mode !== "LINK_EXISTING";
    if (requestedPath) requestedPath.required = mode === "LINK_EXISTING";
    if (attachments) attachments.required = mode === "CREATE_NEW";
    if (pdfRequirement) pdfRequirement.textContent = mode === "CREATE_NEW" ? "PDF 파일 1개 이상 *" : "PDF 파일 (선택)";
  };
  category?.addEventListener("change", refresh);
  folder?.addEventListener("change", refresh);
  video?.addEventListener("change", () => {
    if (video.value === "예" && pledge.value === "해당없음") pledge.value = "미접수";
  });
  folderModeInputs.forEach((input) => input.addEventListener("change", refresh));
  refresh();
  aiPrefillButton?.addEventListener("click", async () => {
    const file = attachments?.files?.[0];
    if (!file) {
      aiStatus.textContent = "먼저 분석할 PDF를 선택해주세요.";
      attachments?.focus();
      return;
    }
    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
    const body = new FormData();
    body.append("csrf_token", csrfToken || "");
    body.append("document", file, file.name);
    aiPrefillButton.disabled = true;
    aiPrefillButton.textContent = "PDF 분석 중…";
    aiStatus.textContent = "텍스트와 이미지 페이지를 읽고 있습니다. 잠시 기다려주세요.";
    aiWarnings.hidden = true;
    aiWarnings.replaceChildren();
    try {
      const response = await fetch("/official-docs/analyze-upload", {
        method: "POST",
        body,
        credentials: "same-origin",
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "PDF 분석에 실패했습니다.");
      const suggestions = data.suggestions || {};
      const fillable = [
        "category_code", "folder_category_code", "manager", "receipt_date",
        "organization", "case_name", "request_content", "special_note",
        "requester", "contact", "email", "dispatch_number", "reply_date",
        "video_exported", "export_pledge",
      ];
      let filled = 0;
      fillable.forEach((name) => {
        const value = suggestions[name];
        const field = document.querySelector(`[name="${name}"]`);
        if (!field || value == null || String(value).trim() === "") return;
        field.value = value;
        field.classList.add("ai-filled");
        field.dispatchEvent(new Event("change", {bubbles: true}));
        filled += 1;
      });
      const warnings = suggestions.warnings || [];
      if (warnings.length) {
        const title = document.createElement("strong");
        title.textContent = "확인 필요";
        const list = document.createElement("ul");
        warnings.forEach((warning) => {
          const item = document.createElement("li");
          item.textContent = warning;
          list.append(item);
        });
        aiWarnings.append(title, list);
        aiWarnings.hidden = false;
      }
      aiStatus.textContent = `AI가 ${filled}개 항목을 입력했습니다 · 신뢰도 ${suggestions.confidence || "확인 필요"} · 저장 전 반드시 검토해주세요.`;
      document.querySelector('[name="category_code"]')?.focus();
    } catch (error) {
      aiStatus.textContent = error.message || "PDF 분석 중 오류가 발생했습니다.";
    } finally {
      aiPrefillButton.disabled = false;
      aiPrefillButton.textContent = "첫 번째 PDF 다시 분석하고 폼 채우기";
    }
  });
  document.querySelector("#official-document-form")?.addEventListener("submit", () => {
    const button = document.querySelector("#official-submit");
    if (button) { button.disabled = true; button.textContent = "등록 중…"; }
  });
  document.querySelectorAll(".copy-path").forEach((button) => button.addEventListener("click", async (event) => {
    event.preventDefault();
    await navigator.clipboard.writeText(button.dataset.path || "");
    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
    if (csrfToken && button.dataset.documentId) {
      const body = new URLSearchParams({
        csrf_token: csrfToken,
        document_id: button.dataset.documentId,
      });
      fetch("/official-docs/audit/path-copy", {
        method: "POST",
        body,
        credentials: "same-origin",
        keepalive: true,
      }).catch(() => {});
    }
    const old = button.textContent;
    button.textContent = "복사 완료";
    setTimeout(() => { button.textContent = old; }, 1600);
  }));
  const selectAll = document.querySelector("#select-all-documents");
  selectAll?.addEventListener("change", () => {
    document.querySelectorAll('input[name="document_ids"]').forEach((input) => {
      input.checked = selectAll.checked;
    });
  });
  folderSearchButton?.addEventListener("click", async () => {
    folderSearchButton.disabled = true;
    folderSearchResults.textContent = "검색 중…";
    try {
      const response = await fetch(`/official-docs/folder-index?q=${encodeURIComponent(folderSearchQuery.value)}`);
      const data = await response.json();
      folderSearchResults.replaceChildren();
      if (!data.folders?.length) {
        folderSearchResults.textContent = "검색 결과가 없습니다. UNC 경로를 직접 입력해주세요.";
      }
      data.folders?.forEach((folder) => {
        const label = document.createElement("label");
        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "indexed_folder";
        radio.value = folder.unc_path;
        radio.addEventListener("change", () => {
          requestedPath.value = folder.unc_path;
          document.querySelector('input[name="folder_display_name"]').value = folder.folder_name;
        });
        const text = document.createElement("span");
        text.textContent = `${folder.folder_name} · ${folder.folder_category || "-"} / ${folder.year || "-"} · 파일 ${folder.file_count}개 · 마지막 확인 ${folder.last_scanned_at}`;
        label.append(radio, text);
        folderSearchResults.append(label);
      });
    } catch {
      folderSearchResults.textContent = "폴더 목록을 불러오지 못했습니다. 경로를 직접 입력해주세요.";
    } finally {
      folderSearchButton.disabled = false;
    }
  });

  const loadFolderLevel = async (path = "", remember = true) => {
    if (!folderBrowserList) return;
    folderBrowserList.textContent = "폴더 목록을 불러오는 중…";
    try {
      const response = await fetch(`/official-docs/folder-tree?parent=${encodeURIComponent(path)}`);
      if (!response.ok) throw new Error("folder browser request failed");
      const data = await response.json();
      browserPath = path;
      if (remember && browserHistory.at(-1) !== path) browserHistory.push(path);
      folderBrowserPath.textContent = path || "동기화된 폴더";
      folderBrowserSelect.disabled = !path;
      folderBrowserUp.disabled = browserHistory.length < 2;
      folderBrowserList.replaceChildren();
      if (!data.folders?.length) {
        folderBrowserList.textContent = "하위 폴더가 없습니다. 현재 폴더를 선택할 수 있습니다.";
        return;
      }
      data.folders.forEach((folder) => {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "folder-browser-item";
        const icon = document.createElement("span");
        icon.textContent = folder.has_children ? "📁" : "📂";
        const name = document.createElement("span");
        name.textContent = folder.name;
        const detail = document.createElement("small");
        detail.textContent = folder.file_count == null ? "" : `파일 ${folder.file_count}개`;
        button.append(icon, name, detail);
        button.addEventListener("click", () => loadFolderLevel(folder.path));
        folderBrowserList.append(button);
      });
    } catch {
      folderBrowserList.textContent = "폴더 목록을 불러오지 못했습니다. 동기화 상태를 확인해주세요.";
    }
  };

  folderBrowseButton?.addEventListener("click", () => {
    folderBrowser.hidden = false;
    browserHistory.length = 0;
    loadFolderLevel("");
  });
  folderBrowserClose?.addEventListener("click", () => { folderBrowser.hidden = true; });
  folderBrowserUp?.addEventListener("click", () => {
    if (browserHistory.length < 2) return;
    browserHistory.pop();
    loadFolderLevel(browserHistory.at(-1) || "", false);
  });
  folderBrowserSelect?.addEventListener("click", () => {
    if (!browserPath) return;
    requestedPath.value = browserPath;
    const displayName = document.querySelector('input[name="folder_display_name"]');
    if (displayName) displayName.value = browserPath.split("\\").filter(Boolean).at(-1) || "";
    folderBrowser.hidden = true;
    requestedPath.focus();
  });
})();
