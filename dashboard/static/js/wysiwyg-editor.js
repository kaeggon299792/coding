(function () {
  "use strict";

  var Editor = window.toastui && window.toastui.Editor;
  if (!Editor) return;

  var GROUP_LABELS = {
    basic: "기본",
    list: "목록",
    media: "미디어",
    advanced: "고급",
    work: "업무",
  };

  var COMMANDS = [
    { id: "text", group: "basic", icon: "T", label: "기본 텍스트", description: "일반 문단을 추가합니다", aliases: "text paragraph 본문 문단" },
    { id: "h1", group: "basic", icon: "H1", label: "제목 1", description: "큰 제목을 추가합니다", aliases: "heading title h1 대제목" },
    { id: "h2", group: "basic", icon: "H2", label: "제목 2", description: "중간 제목을 추가합니다", aliases: "heading subtitle h2 소제목" },
    { id: "h3", group: "basic", icon: "H3", label: "제목 3", description: "작은 제목을 추가합니다", aliases: "heading h3 소제목" },
    { id: "date", group: "basic", icon: "◫", label: "날짜", description: "오늘 날짜를 삽입합니다", aliases: "date today 날짜 오늘" },
    { id: "bullet", group: "list", icon: "•", label: "글머리 목록", description: "순서 없는 목록을 만듭니다", aliases: "bullet list ul 목록 리스트" },
    { id: "ordered", group: "list", icon: "1.", label: "번호 목록", description: "순서가 있는 목록을 만듭니다", aliases: "number ordered list ol 번호 리스트" },
    { id: "check", group: "list", icon: "☑", label: "체크리스트", description: "완료 상태를 저장하는 할 일을 만듭니다", aliases: "check checklist task todo 체크 할일" },
    { id: "image", group: "media", icon: "▧", label: "이미지", description: "이미지를 업로드해 현재 위치에 넣습니다", aliases: "image photo picture 이미지 사진" },
    { id: "file", group: "media", icon: "↥", label: "파일 첨부", description: "게시글 첨부파일을 선택합니다", aliases: "file attachment upload 파일 첨부 업로드", requiresFile: true },
    { id: "link", group: "media", icon: "↗", label: "링크", description: "웹 링크를 추가합니다", aliases: "link url 링크 주소" },
    { id: "quote", group: "advanced", icon: "❝", label: "인용문", description: "인용 블록을 추가합니다", aliases: "quote blockquote 인용" },
    { id: "divider", group: "advanced", icon: "—", label: "구분선", description: "내용 사이에 구분선을 넣습니다", aliases: "divider hr line separator 구분" },
    { id: "code", group: "advanced", icon: "</>", label: "코드 블록", description: "여러 줄 코드를 입력합니다", aliases: "code block 코드" },
    { id: "table", group: "advanced", icon: "▦", label: "표", description: "3열 × 3행 표를 추가합니다", aliases: "table grid 표 테이블" },
    { id: "meeting", group: "work", icon: "M", label: "회의록", description: "회의 기록 템플릿을 삽입합니다", aliases: "meeting minutes 회의 회의록", workOnly: true },
    { id: "task", group: "work", icon: "W", label: "업무", description: "업무 정리 템플릿을 삽입합니다", aliases: "work task 업무 작업", workOnly: true },
    { id: "status", group: "work", icon: "S", label: "상태", description: "현재 업무 상태를 선택합니다", aliases: "status state 상태 진행", workOnly: true },
    { id: "priority", group: "work", icon: "!", label: "중요도", description: "현재 업무 중요도를 선택합니다", aliases: "priority importance 중요도 우선", workOnly: true },
    { id: "reminder", group: "work", icon: "◷", label: "알림", description: "이 업무의 알림일과 시간을 설정합니다", aliases: "reminder alarm notification 알림", workOnly: true },
  ];

  // Beyond this many CSS pixels of pointer travel, a press on a command
  // item is treated as the start of a menu scroll rather than a tap.
  var SLASH_TAP_MAX_MOVEMENT = 10;

  function normalize(value) {
    return String(value || "").trim().toLocaleLowerCase();
  }

  function todayFor(source) {
    return source.dataset.editorToday || new Date().toISOString().slice(0, 10);
  }

  function createMenu() {
    var menu = document.createElement("div");
    menu.className = "wysiwyg-slash-menu";
    menu.setAttribute("role", "listbox");
    menu.setAttribute("aria-label", "블록 명령");
    menu.hidden = true;
    document.body.appendChild(menu);
    return menu;
  }

  function viewportBox() {
    // window.innerHeight/innerWidth stay at the layout viewport size even
    // while an on-screen keyboard is open on mobile Safari/Chrome, so a menu
    // positioned against them can render (and accept touches) underneath the
    // keyboard. visualViewport tracks the actually-visible area instead.
    var vv = window.visualViewport;
    if (!vv) return { left: 0, top: 0, right: window.innerWidth, bottom: window.innerHeight };
    return {
      left: vv.offsetLeft,
      top: vv.offsetTop,
      right: vv.offsetLeft + vv.width,
      bottom: vv.offsetTop + vv.height,
    };
  }

  function caretRect(editable) {
    var selection = window.getSelection();
    if (selection && selection.rangeCount && editable.contains(selection.anchorNode)) {
      var range = selection.getRangeAt(0).cloneRange();
      range.collapse(false);
      var rect = range.getBoundingClientRect();
      if (rect && (rect.width || rect.height)) return rect;
    }
    return editable.getBoundingClientRect();
  }

  function textBeforeCaret(editable) {
    var selection = window.getSelection();
    if (!selection || !selection.rangeCount || !editable.contains(selection.anchorNode)) return "";
    var node = selection.anchorNode.nodeType === Node.ELEMENT_NODE
      ? selection.anchorNode
      : selection.anchorNode.parentElement;
    var block = node && node.closest("p,h1,h2,h3,h4,li,blockquote,pre,td,th");
    if (!block || !editable.contains(block)) block = editable;
    try {
      var range = document.createRange();
      range.selectNodeContents(block);
      range.setEnd(selection.anchorNode, selection.anchorOffset);
      return range.toString();
    } catch (error) {
      return "";
    }
  }

  function uploadImage(source, editor, image, status, callback) {
    if (!image || !String(image.type || "").startsWith("image/")) {
      status("이미지 파일만 업로드할 수 있습니다.", true);
      return Promise.resolve(false);
    }
    status("이미지를 업로드하고 있습니다…");
    var payload = new FormData();
    payload.append("image", image, image.name || "editor-image");
    payload.append("scope", source.dataset.imagePasteScope || "");
    payload.append("csrf_token", source.dataset.imagePasteCsrf || "");
    return fetch(source.dataset.imagePasteEndpoint, {
      method: "POST",
      body: payload,
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (body) {
        if (!response.ok || !body.url) throw new Error(body.error || "이미지를 업로드하지 못했습니다.");
        if (callback) callback(body.url, image.name || "이미지");
        else editor.exec("addImage", { imageUrl: body.url, altText: image.name || "이미지" });
        status("이미지를 본문에 넣었습니다.");
        return true;
      });
    }).catch(function (error) {
      status(error.message || "이미지를 업로드하지 못했습니다.", true);
      return false;
    });
  }

  function enhance(source) {
    if (source.dataset.wysiwygReady === "1") return;
    source.dataset.wysiwygReady = "1";

    var form = source.closest("form");
    var field = source.closest("label") || source.parentElement;
    // A rich contenteditable must not live inside a <label>. Browsers forward
    // clicks anywhere in a label to its labelled control; TOAST UI can then
    // receive that synthetic click on the heading control instead of placing
    // the caret. Preserve the field wrapper and its classes, but remove the
    // native label semantics before mounting the editor.
    if (field && field.tagName === "LABEL" && field.parentNode) {
      var fieldWrapper = document.createElement("div");
      Array.from(field.attributes).forEach(function (attribute) {
        if (attribute.name !== "for") fieldWrapper.setAttribute(attribute.name, attribute.value);
      });
      while (field.firstChild) fieldWrapper.appendChild(field.firstChild);
      field.parentNode.replaceChild(fieldWrapper, field);
      field = fieldWrapper;
    }
    // Grid/flex form layouts give items an "auto" minimum size equal to their
    // content's min-content width, so a wide toolbar can force the whole
    // field (and with it the page) past the viewport on narrow screens even
    // though the toolbar itself already scrolls internally. Without this the
    // field never shrinks below the toolbar's natural width.
    if (field) field.classList.add("wysiwyg-editor-field");
    var statusNode = document.querySelector('[data-image-paste-status="' + source.id + '"]');
    var required = source.required;
    var maxLength = source.maxLength > 0 ? source.maxLength : 0;
    var context = source.dataset.editorContext || "board";
    var attachmentInput = form && form.querySelector('input[type="file"][name="attachments"]');
    var host = document.createElement("div");
    host.className = "wysiwyg-editor-host";
    source.before(host);

    var editor = new Editor({
      el: host,
      initialValue: source.value || "",
      initialEditType: "wysiwyg",
      previewStyle: "vertical",
      height: "auto",
      minHeight: source.dataset.editorMinHeight || "360px",
      hideModeSwitch: true,
      language: "ko-KR",
      usageStatistics: false,
      autofocus: false,
      useCommandShortcut: true,
      toolbarItems: [
        ["heading", "bold", "italic", "strike"],
        ["hr", "quote"],
        ["ul", "ol", "task"],
        ["table", "image", "link"],
        ["code", "codeblock"],
      ],
      hooks: {
        addImageBlobHook: function (blob, callback) {
          uploadImage(source, editor, blob, setStatus, callback);
          return false;
        },
      },
    });

    source.classList.add("wysiwyg-editor-source");
    source.required = false;
    source.hidden = true;
    source.tabIndex = -1;
    source.setAttribute("aria-hidden", "true");
    host._casinoEditor = editor;
    var editableElement = host.querySelector(".toastui-editor-ww-container .ProseMirror");
    var fieldCaption = field && field.querySelector(":scope > span");
    if (editableElement && fieldCaption) {
      editableElement.setAttribute("aria-label", fieldCaption.textContent.trim());
      field.addEventListener("click", function (event) {
        if (event.target !== field && event.target !== fieldCaption) return;
        event.preventDefault();
        editor.focus();
      });
    }

    var menu = createMenu();
    var slashPointer = null;

    function resetSlashPointer() {
      slashPointer = null;
    }

    // Distinguishes a tap on a command item from the start of a menu-scroll
    // drag. The item is never activated on pointerdown (that would fire
    // before any movement could be observed); it only runs on pointerup, and
    // only if the pointer never traveled beyond the tap threshold. This lets
    // touch-action: pan-y drive a natural scroll while the gesture is still
    // being tracked, and pointercancel (fired when the browser takes the
    // gesture over as a scroll) simply drops the tracked pointer instead of
    // executing anything.
    menu.addEventListener("pointerdown", function (event) {
      if (event.pointerType === "mouse" && event.button !== 0) return;
      var item = event.target.closest(".wysiwyg-slash-item");
      if (!item) return;
      slashPointer = {
        id: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        moved: false,
        item: item,
      };
      // Safe with touch-action: pan-y already on the menu: this only
      // suppresses the item's default focus/click behavior, it does not
      // block the browser's native vertical pan.
      event.preventDefault();
    });
    menu.addEventListener("pointermove", function (event) {
      if (!slashPointer || event.pointerId !== slashPointer.id) return;
      var dx = event.clientX - slashPointer.startX;
      var dy = event.clientY - slashPointer.startY;
      if (Math.sqrt(dx * dx + dy * dy) > SLASH_TAP_MAX_MOVEMENT) {
        slashPointer.moved = true;
      }
    });
    menu.addEventListener("pointerup", function (event) {
      if (!slashPointer || event.pointerId !== slashPointer.id) return;
      var gesture = slashPointer;
      slashPointer = null;
      if (gesture.moved) return;
      var index = Number(gesture.item.dataset.commandIndex);
      var command = visibleCommands[index];
      if (!command) return;
      event.preventDefault();
      executeCommand(command);
    });
    menu.addEventListener("pointercancel", resetSlashPointer);

    var imagePicker = document.createElement("input");
    imagePicker.type = "file";
    imagePicker.accept = "image/png,image/jpeg,image/gif,image/webp";
    imagePicker.className = "wysiwyg-image-picker";
    imagePicker.tabIndex = -1;
    host.appendChild(imagePicker);

    var open = false;
    var activeIndex = 0;
    var visibleCommands = [];
    var slashRange = null;
    var applyingInlineShortcut = false;

    function setStatus(message, isError) {
      if (!statusNode) return;
      statusNode.textContent = message || "";
      statusNode.classList.toggle("is-error", Boolean(isError));
    }

    function syncSource() {
      source.value = editor.getMarkdown();
      source.dispatchEvent(new Event("input", { bubbles: true }));
    }

    editor.on("change", function () {
      syncSource();
      window.requestAnimationFrame(function () {
        applyInlineMarkdownShortcut();
        updateSlashMenu();
      });
    });
    editor.on("keydown", function (editorType, event) {
      if (editorType !== "wysiwyg") return;
      var editable = host.querySelector(".toastui-editor-ww-container .ProseMirror");
      if (editable) applyBlockMarkdownShortcut(event, editable);
    });

    function availableCommands(query) {
      var needle = normalize(query);
      return COMMANDS.filter(function (command) {
        if (command.workOnly && context !== "work-note") return false;
        if (command.requiresFile && !attachmentInput) return false;
        if (!needle) return true;
        return normalize(command.label + " " + command.aliases).includes(needle);
      });
    }

    function positionMenu() {
      var editable = host.querySelector(".toastui-editor-ww-container .ProseMirror");
      if (!editable) return;
      var rect = caretRect(editable);
      var view = viewportBox();
      var gap = 7;
      var width = Math.min(330, view.right - view.left - 16);
      menu.style.width = width + "px";
      var left = Math.max(view.left + 8, Math.min(rect.left, view.right - width - 8));
      var desiredTop = rect.bottom + gap;
      var maxHeight = Math.min(380, view.bottom - view.top - 16);
      menu.style.maxHeight = maxHeight + "px";
      menu.hidden = false;
      var measured = menu.getBoundingClientRect().height;
      var top = desiredTop;
      if (top + measured > view.bottom - 8) {
        top = Math.max(view.top + 8, rect.top - measured - gap);
      }
      menu.style.left = left + "px";
      menu.style.top = top + "px";
    }

    function renderMenu(query) {
      visibleCommands = availableCommands(query);
      activeIndex = Math.min(activeIndex, Math.max(0, visibleCommands.length - 1));
      menu.replaceChildren();
      if (!visibleCommands.length) {
        var empty = document.createElement("p");
        empty.className = "wysiwyg-slash-empty";
        empty.textContent = "일치하는 명령이 없습니다.";
        menu.appendChild(empty);
        positionMenu();
        return;
      }
      var lastGroup = "";
      visibleCommands.forEach(function (command, index) {
        if (command.group !== lastGroup) {
          var group = document.createElement("span");
          group.className = "wysiwyg-slash-group";
          group.textContent = GROUP_LABELS[command.group];
          menu.appendChild(group);
          lastGroup = command.group;
        }
        var button = document.createElement("button");
        button.type = "button";
        button.className = "wysiwyg-slash-item" + (index === activeIndex ? " is-active" : "");
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", index === activeIndex ? "true" : "false");
        button.dataset.commandIndex = String(index);
        var icon = document.createElement("i");
        icon.textContent = command.icon;
        var copy = document.createElement("span");
        var title = document.createElement("strong");
        title.textContent = command.label;
        var description = document.createElement("small");
        description.textContent = command.description;
        copy.append(title, description);
        button.append(icon, copy);
        menu.appendChild(button);
      });
      positionMenu();
    }

    function closeMenu() {
      open = false;
      slashRange = null;
      menu.hidden = true;
      menu.replaceChildren();
    }

    function hideEditorPopups() {
      host.querySelectorAll(".toastui-editor-popup").forEach(function (popup) {
        popup.style.display = "none";
      });
    }

    function clearSlash(restoreEditorFocus) {
      if (!slashRange) return;
      var current = editor.getSelection();
      var end = current[1];
      var start = slashRange.start;
      editor.setSelection(start, end);
      editor.replaceSelection("");
      closeMenu();
      if (restoreEditorFocus !== false) editor.focus();
      syncSource();
    }

    function insertMarkdownTemplate(markdown) {
      if (!slashRange) return;
      var current = editor.getSelection();
      var marker = "CASINOEDITORINSERT" + Date.now() + Math.floor(Math.random() * 10000);
      editor.setSelection(slashRange.start, current[1]);
      editor.replaceSelection(marker);
      var documentMarkdown = editor.getMarkdown();
      editor.setMarkdown(documentMarkdown.replace(marker, "\n" + markdown + "\n"), true);
      closeMenu();
      editor.focus();
      hideEditorPopups();
      syncSource();
    }

    function focusWorkField(name) {
      clearSlash(false);
      var control = form && form.querySelector('[name="' + name + '"]');
      if (!control) return;
      var selectTrigger = control.closest("[data-vega-select]") &&
        control.closest("[data-vega-select]").querySelector(".vega-select-trigger");
      if (selectTrigger) {
        selectTrigger.focus();
        selectTrigger.click();
        return;
      }
      control.focus();
      if (typeof control.showPicker === "function") {
        try { control.showPicker(); } catch (error) {}
      }
      window.setTimeout(function () {
        control.focus({ preventScroll: true });
      }, 120);
    }

    function executeCommand(command) {
      var date = todayFor(source);
      if (command.id === "image") {
        clearSlash();
        imagePicker.click();
      } else if (command.id === "file") {
        clearSlash();
        attachmentInput.click();
      } else if (command.id === "status") {
        focusWorkField("status");
      } else if (command.id === "priority") {
        focusWorkField("priority");
      } else if (command.id === "reminder") {
        focusWorkField("reminder_date");
      } else if (command.id === "meeting") {
        insertMarkdownTemplate("## 회의명\n\n일시: " + date + "\n참석자:\n\n### 주요 논의사항\n\n### 결정사항\n\n### 후속 조치\n\n- [ ] 할 일");
      } else if (command.id === "task") {
        insertMarkdownTemplate("## 업무명\n\n목적:\n\n진행사항:\n\n확인사항:\n\n다음 조치:\n\n- [ ] 할 일");
      } else {
        clearSlash();
        if (command.id === "h1" || command.id === "h2" || command.id === "h3") {
          editor.exec("heading", { level: Number(command.id.slice(1)) });
          editor.insertText("제목");
        } else if (command.id === "bullet") {
          editor.exec("bulletList");
          editor.insertText("항목");
        } else if (command.id === "ordered") {
          editor.exec("orderedList");
          editor.insertText("항목");
        } else if (command.id === "check") {
          editor.exec("taskList");
          editor.insertText("할 일");
        } else if (command.id === "quote") {
          editor.exec("blockQuote");
          editor.insertText("인용문");
        } else if (command.id === "divider") {
          editor.exec("hr");
        } else if (command.id === "code") {
          editor.exec("codeBlock");
          editor.insertText("코드를 입력하세요");
        } else if (command.id === "table") {
          editor.exec("addTable", { rowCount: 3, columnCount: 3 });
        } else if (command.id === "link") {
          editor.exec("addLink", { linkUrl: "https://", linkText: "링크 텍스트" });
        } else if (command.id === "date") {
          editor.insertText(date);
        }
        hideEditorPopups();
        syncSource();
      }
    }

    function updateSlashMenu() {
      var editable = host.querySelector(".toastui-editor-ww-container .ProseMirror");
      if (!editable) return;
      var before = textBeforeCaret(editable);
      var match = before.match(/(?:^|\s)\/([^\s/]*)$/u);
      if (!match) {
        closeMenu();
        return;
      }
      var selection = editor.getSelection();
      var end = selection[1];
      slashRange = { start: Math.max(1, end - match[1].length - 1) };
      open = true;
      activeIndex = 0;
      renderMenu(match[1]);
    }

    function applyInlineMarkdownShortcut() {
      if (applyingInlineShortcut) return;
      var editable = host.querySelector(".toastui-editor-ww-container .ProseMirror");
      if (!editable) return;
      var match = textBeforeCaret(editable).match(/\*\*([^*\n]+)\*\*$/u);
      if (!match) return;
      var selection = editor.getSelection();
      var end = selection[1];
      var start = end - match[0].length;
      applyingInlineShortcut = true;
      editor.setSelection(start, end);
      editor.replaceSelection(match[1]);
      editor.setSelection(start, start + match[1].length);
      editor.exec("bold");
      editor.setSelection(start + match[1].length, start + match[1].length);
      applyingInlineShortcut = false;
      syncSource();
    }

    function applyBlockMarkdownShortcut(event, editable) {
      if (event.key !== " " || event.isComposing) return false;
      var marker = textBeforeCaret(editable);
      var shortcut = {
        "#": ["heading", { level: 1 }],
        "##": ["heading", { level: 2 }],
        "###": ["heading", { level: 3 }],
        "-": ["bulletList"],
        "1.": ["orderedList"],
        ">": ["blockQuote"],
      }[marker];
      if (!shortcut) return false;
      event.preventDefault();
      event.stopPropagation();
      var selection = editor.getSelection();
      var end = selection[1];
      editor.setSelection(end - marker.length, end);
      editor.replaceSelection("");
      editor.exec(shortcut[0], shortcut[1]);
      hideEditorPopups();
      syncSource();
      return true;
    }

    host.addEventListener("input", function (event) {
      if (event.target && event.target.closest(".toastui-editor-ww-container .ProseMirror")) {
        window.requestAnimationFrame(updateSlashMenu);
      }
    }, true);
    host.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          closeMenu();
          hideEditorPopups();
          return;
        }
        var editable = event.target && event.target.closest(".toastui-editor-ww-container .ProseMirror");
        if (!editable) return;
        if (applyBlockMarkdownShortcut(event, editable)) return;
        if (!open || event.isComposing) return;
        if (event.key === "ArrowDown" || event.key === "ArrowUp") {
          event.preventDefault();
          event.stopPropagation();
          if (!visibleCommands.length) return;
          var direction = event.key === "ArrowDown" ? 1 : -1;
          activeIndex = (activeIndex + direction + visibleCommands.length) % visibleCommands.length;
          var query = (textBeforeCaret(editable).match(/\/([^\s/]*)$/u) || ["", ""])[1];
          renderMenu(query);
          var active = menu.querySelector(".is-active");
          if (active) active.scrollIntoView({ block: "nearest" });
        } else if (event.key === "Enter" && visibleCommands.length) {
          event.preventDefault();
          event.stopPropagation();
          executeCommand(visibleCommands[activeIndex]);
        } else if (event.key === "Backspace") {
          window.requestAnimationFrame(updateSlashMenu);
        }
    }, true);

    host.addEventListener("pointerdown", function (event) {
      if (event.target && event.target.closest(".toastui-editor-ww-container .ProseMirror")) {
        closeMenu();
        hideEditorPopups();
      } else if (event.target && event.target.closest(".toastui-editor-toolbar button")) {
        hideEditorPopups();
      }
    }, true);

    imagePicker.addEventListener("change", function () {
      var image = imagePicker.files && imagePicker.files[0];
      if (image) uploadImage(source, editor, image, setStatus);
      imagePicker.value = "";
    });

    var externalImage = form && form.querySelector('[data-image-upload-for="' + source.id + '"]');
    if (externalImage) {
      externalImage.addEventListener("change", function (event) {
        event.stopImmediatePropagation();
        var image = externalImage.files && externalImage.files[0];
        if (image) uploadImage(source, editor, image, setStatus);
        externalImage.value = "";
      }, true);
    }

    form && form.addEventListener("submit", function (event) {
      syncSource();
      var value = source.value.trim();
      if (required && !value) {
        event.preventDefault();
        setStatus("본문 내용을 입력해주세요.", true);
        editor.focus();
      } else if (maxLength && source.value.length > maxLength) {
        event.preventDefault();
        setStatus("본문은 최대 " + maxLength.toLocaleString() + "자까지 입력할 수 있습니다.", true);
        editor.focus();
      }
    });

    document.addEventListener("pointerdown", function (event) {
      if (open && !menu.contains(event.target) && !host.contains(event.target)) closeMenu();
      if (!host.contains(event.target) && !menu.contains(event.target)) hideEditorPopups();
    });
    window.addEventListener("resize", function () { if (open) positionMenu(); }, { passive: true });
    document.addEventListener("scroll", function () { if (open) positionMenu(); }, true);
    if (window.visualViewport) {
      // Repositions the menu when the on-screen keyboard opens/closes/resizes,
      // since window.innerHeight alone doesn't reflect that on mobile.
      window.visualViewport.addEventListener("resize", function () { if (open) positionMenu(); }, { passive: true });
    }

    source.dispatchEvent(new CustomEvent("wysiwyg:ready", {
      bubbles: true,
      detail: { editor: editor },
    }));
  }

  function initialize() {
    document.querySelectorAll("textarea[data-wysiwyg-editor]").forEach(enhance);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
})();
