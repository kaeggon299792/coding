(() => {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";
  const ICONS = {
    "arrow-down": [["path", {d: "M12 5v14"}], ["path", {d: "m19 12-7 7-7-7"}]],
    "arrow-left": [["path", {d: "m12 19-7-7 7-7"}], ["path", {d: "M19 12H5"}]],
    "arrow-right": [["path", {d: "M5 12h14"}], ["path", {d: "m12 5 7 7-7 7"}]],
    "arrow-up": [["path", {d: "m5 12 7-7 7 7"}], ["path", {d: "M12 19V5"}]],
    calendar: [["path", {d: "M8 2v4"}], ["path", {d: "M16 2v4"}], ["rect", {x: "3", y: "4", width: "18", height: "18", rx: "2"}], ["path", {d: "M3 10h18"}]],
    check: [["path", {d: "m20 6-11 11-5-5"}]],
    "chevron-down": [["path", {d: "m6 9 6 6 6-6"}]],
    copy: [["rect", {x: "9", y: "9", width: "13", height: "13", rx: "2"}], ["path", {d: "M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"}]],
    download: [["path", {d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"}], ["path", {d: "m7 10 5 5 5-5"}], ["path", {d: "M12 15V3"}]],
    "external-link": [["path", {d: "M15 3h6v6"}], ["path", {d: "M10 14 21 3"}], ["path", {d: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"}]],
    filter: [["path", {d: "M22 3H2l8 9.46V19l4 2v-8.54z"}]],
    home: [["path", {d: "m3 11 9-8 9 8"}], ["path", {d: "M5 10v10h14V10"}], ["path", {d: "M9 20v-6h6v6"}]],
    images: [["path", {d: "M18 22H4a2 2 0 0 1-2-2V6"}], ["path", {d: "m22 13-3.3-3.3a2.4 2.4 0 0 0-3.4 0L9 16"}], ["rect", {x: "6", y: "2", width: "16", height: "16", rx: "2"}], ["circle", {cx: "14", cy: "8", r: "2"}]],
    "lock-keyhole": [["circle", {cx: "12", cy: "16", r: "1"}], ["rect", {x: "3", y: "10", width: "18", height: "12", rx: "2"}], ["path", {d: "M7 10V7a5 5 0 0 1 10 0v3"}]],
    "log-in": [["path", {d: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"}], ["path", {d: "m10 17 5-5-5-5"}], ["path", {d: "M15 12H3"}]],
    "log-out": [["path", {d: "M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"}], ["path", {d: "m16 17 5-5-5-5"}], ["path", {d: "M21 12H9"}]],
    pencil: [["path", {d: "M12 20h9"}], ["path", {d: "M16.5 3.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z"}]],
    pin: [["path", {d: "M12 17v5"}], ["path", {d: "M5 17h14"}], ["path", {d: "m6 3 1 7-2 3h14l-2-3 1-7z"}]],
    plus: [["path", {d: "M5 12h14"}], ["path", {d: "M12 5v14"}]],
    "refresh-cw": [["path", {d: "M21 12a9 9 0 0 0-15.5-6.2L3 8"}], ["path", {d: "M3 3v5h5"}], ["path", {d: "M3 12a9 9 0 0 0 15.5 6.2L21 16"}], ["path", {d: "M16 16h5v5"}]],
    save: [["path", {d: "M15.2 3a2 2 0 0 1 1.4.6l3.8 3.8a2 2 0 0 1 .6 1.4V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"}], ["path", {d: "M17 21v-7H7v7"}], ["path", {d: "M7 3v5h8"}]],
    search: [["circle", {cx: "11", cy: "11", r: "8"}], ["path", {d: "m21 21-4.3-4.3"}]],
    share: [["circle", {cx: "18", cy: "5", r: "3"}], ["circle", {cx: "6", cy: "12", r: "3"}], ["circle", {cx: "18", cy: "19", r: "3"}], ["path", {d: "m8.6 10.5 6.8-4"}], ["path", {d: "m8.6 13.5 6.8 4"}]],
    "shield-check": [["path", {d: "M20 13c0 5-3.5 7.5-8 9-4.5-1.5-8-4-8-9V5l8-3 8 3z"}], ["path", {d: "m9 12 2 2 4-4"}]],
    sparkles: [["path", {d: "m12 3-1.9 5.1L5 10l5.1 1.9L12 17l1.9-5.1L19 10l-5.1-1.9z"}], ["path", {d: "M5 3v4"}], ["path", {d: "M3 5h4"}], ["path", {d: "M19 17v4"}], ["path", {d: "M17 19h4"}]],
    sun: [["circle", {cx: "12", cy: "12", r: "4"}], ["path", {d: "M12 2v2"}], ["path", {d: "M12 20v2"}], ["path", {d: "m4.93 4.93 1.42 1.42"}], ["path", {d: "m17.66 17.66 1.41 1.41"}], ["path", {d: "M2 12h2"}], ["path", {d: "M20 12h2"}], ["path", {d: "m6.34 17.66-1.41 1.41"}], ["path", {d: "m19.07 4.93-1.41 1.41"}]],
    moon: [["path", {d: "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9"}]],
    "trash-2": [["path", {d: "M3 6h18"}], ["path", {d: "M8 6V4h8v2"}], ["path", {d: "m19 6-1 14H6L5 6"}], ["path", {d: "M10 11v5"}], ["path", {d: "M14 11v5"}]],
    upload: [["path", {d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"}], ["path", {d: "m17 8-5-5-5 5"}], ["path", {d: "M12 3v12"}]],
    user: [["path", {d: "M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"}], ["circle", {cx: "12", cy: "7", r: "4"}]],
    x: [["path", {d: "M18 6 6 18"}], ["path", {d: "m6 6 12 12"}]],
  };

  const RULES = [
    [/\b(log\s*out|logout)\b|로그아웃/i, "log-out"],
    [/\b(log\s*in|login)\b|로그인/i, "log-in"],
    [/삭제|제거|휴지통|delete|remove|trash/i, "trash-2"],
    [/다운로드|내보내기|download|export/i, "download"],
    [/업로드|가져오기|불러오기|upload|import/i, "upload"],
    [/복사|copy/i, "copy"],
    [/공유|share/i, "share"],
    [/새로고침|갱신|다시\s*불러|refresh|reload/i, "refresh-cw"],
    [/초기화|복원|reset|restore/i, "refresh-cw"],
    [/검색|조회|search/i, "search"],
    [/필터|filter/i, "filter"],
    [/달력|날짜|calendar/i, "calendar"],
    [/AI\s*(분석|제안)|자동\s*(분석|생성)|spark/i, "sparkles"],
    [/수정|편집|edit|rename/i, "pencil"],
    [/저장|변경사항|save/i, "save"],
    [/승인|적용|완료|확인|선택 항목 생성|approve|apply|confirm/i, "check"],
    [/등록|추가|새\s*(글|자료|언어)|글쓰기|작성하기|create|add|new/i, "plus"],
    [/보안|security/i, "shield-check"],
    [/회원정보|계정\s*관리|profile|account/i, "user"],
    [/공식\s*사이트|원문|외부\s*링크|external/i, "external-link"],
    [/맨\s*위|back\s*to\s*top|^\s*↑/i, "arrow-up"],
    [/^(이전|뒤로)|목록으로|돌아가기|previous|back|^\s*←/i, "arrow-left"],
    [/^(다음|앞으로)|열기\s*→|보기\s*→|next|^.*→\s*$/i, "arrow-right"],
    [/시작\s*화면|대시보드\s*홈|home/i, "home"],
  ];

  function createIcon(name) {
    const parts = ICONS[name];
    if (!parts) return null;
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.classList.add("ui-icon", `ui-icon-${name}`);
    parts.forEach(([tag, attributes]) => {
      const node = document.createElementNS(SVG_NS, tag);
      Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
      svg.appendChild(node);
    });
    return svg;
  }

  function cleanDirectionalGlyphs(element) {
    const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach((node) => {
      node.nodeValue = node.nodeValue
        .replace(/^\s*[←↑→↓＋]\s*/, "")
        .replace(/\s*[←↑→↓]\s*$/, "");
    });
  }

  function resolveIcon(element) {
    if (element.dataset.uiIcon) return element.dataset.uiIcon;
    const label = `${element.getAttribute("aria-label") || ""} ${element.textContent || ""}`.trim();
    const rule = RULES.find(([pattern]) => pattern.test(label));
    return rule ? rule[1] : null;
  }

  function decorate(element) {
    if (!element || element.dataset.uiIconReady === "true" || element.hasAttribute("data-no-ui-icon")) return;
    if (element.querySelector(":scope > .ui-icon, :scope > svg, :scope > img")) return;
    const name = resolveIcon(element);
    if (!name) return;
    const icon = createIcon(name);
    if (!icon) return;
    cleanDirectionalGlyphs(element);
    const position = element.dataset.uiIconPosition || (name === "arrow-right" || name === "external-link" ? "end" : "start");
    if (position === "end") element.append(icon);
    else element.prepend(icon);
    element.classList.add("has-ui-icon");
    element.dataset.uiIconReady = "true";
  }

  document.querySelectorAll([
    ".btn", ".button", ".login-button", ".login-home-link", ".guest-access-button",
    ".public-login-link", ".topbar-profile-popover > a", ".topbar-profile-popover button",
    ".topbar-search-link", ".back-to-top", "#tip-back-to-top", ".tips-back",
    ".community-detail-toolbar a", ".text-button", ".path-link", "button", "[data-ui-icon]",
  ].join(",")).forEach(decorate);

  document.querySelectorAll(".public-menu a").forEach((link) => {
    link.dataset.uiIcon = "arrow-right";
    link.dataset.uiIconPosition = "end";
    const oldArrow = link.querySelector("i");
    if (oldArrow) oldArrow.remove();
    decorate(link);
  });

  document.querySelectorAll("[aria-hidden='true']").forEach((element) => {
    if (element.children.length || element.closest("svg")) return;
    const symbol = (element.textContent || "").trim();
    const symbolIcons = {"←": "arrow-left", "↑": "arrow-up", "→": "arrow-right", "↓": "arrow-down", "＋": "plus", "+": "plus", "✦": "sparkles", "▧": "images", "⌁": "lock-keyhole"};
    const name = symbolIcons[symbol];
    if (!name) return;
    const icon = createIcon(name);
    if (!icon) return;
    element.replaceChildren(icon);
    element.classList.add("ui-symbol-icon");
  });

  document.querySelectorAll(".admin-portfolio-editor > summary").forEach((summary) => {
    summary.dataset.uiIcon = "chevron-down";
    summary.dataset.uiIconPosition = "end";
    decorate(summary);
  });

  const themeIcon = document.querySelector(".theme-toggle-icon");
  if (themeIcon) {
    const syncThemeIcon = () => {
      const name = document.documentElement.dataset.theme === "light" ? "moon" : "sun";
      if (themeIcon.querySelector(`.ui-icon-${name}`)) return;
      const icon = createIcon(name);
      if (!icon) return;
      themeIcon.replaceChildren(icon);
      themeIcon.classList.add("ui-symbol-icon");
    };
    syncThemeIcon();
    new MutationObserver(syncThemeIcon).observe(themeIcon, {childList: true});
  }
})();
