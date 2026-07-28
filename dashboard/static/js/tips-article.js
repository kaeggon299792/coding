document.addEventListener("DOMContentLoaded", () => {
  const articleBody = document.getElementById("tip-body");
  if (!articleBody) return;
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const copyText = async (text) => {
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        return true;
      } catch (_) {
        // 보안 설정상 Clipboard API가 차단되면 기존 방식으로 폴백한다.
      }
    }
    const temporary = document.createElement("textarea");
    temporary.value = text;
    temporary.setAttribute("readonly", "");
    temporary.style.position = "fixed";
    temporary.style.opacity = "0";
    document.body.appendChild(temporary);
    temporary.select();
    const copied = document.execCommand("copy");
    temporary.remove();
    return copied;
  };

  const shareButton = document.getElementById("share-tip-link");
  const shareFeedback = document.getElementById("tip-share-feedback");
  shareButton?.addEventListener("click", async () => {
    const copied = await copyText(window.location.href);
    shareFeedback.textContent = copied ? "복사 완료" : "복사 실패";
    setTimeout(() => { shareFeedback.textContent = ""; }, 1800);
  });

  const nativeShare = document.getElementById("share-tip-native");
  if (nativeShare && navigator.share) {
    nativeShare.hidden = false;
    nativeShare.addEventListener("click", () => {
      navigator.share({
        title: document.title,
        url: window.location.href,
      }).catch(() => {});
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
      button.textContent = await copyText((code || block).innerText) ? "복사됨" : "복사 실패";
      setTimeout(() => { button.textContent = "복사"; }, 1400);
    });
    block.appendChild(button);
  });

  const headings = [...articleBody.querySelectorAll("h2, h3, h4")];
  const toc = document.getElementById("tip-toc");
  const tocSidebar = document.getElementById("tip-toc-sidebar");
  const links = [];
  const usedIds = new Set();
  const makeId = (heading, index) => {
    const base = (heading.id || heading.textContent)
      .trim()
      .toLowerCase()
      .replace(/[^\w가-힣]+/g, "-")
      .replace(/^-|-$/g, "") || `section-${index + 1}`;
    let candidate = base;
    let suffix = 2;
    while (usedIds.has(candidate)) candidate = `${base}-${suffix++}`;
    usedIds.add(candidate);
    return candidate;
  };

  headings.forEach((heading, index) => {
    heading.id = makeId(heading, index);
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = `#${heading.id}`;
    link.textContent = heading.textContent;
    link.dataset.level = heading.tagName.slice(1);
    link.dataset.target = heading.id;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      heading.scrollIntoView({
        behavior: reduceMotion ? "auto" : "smooth",
        block: "start",
      });
      history.replaceState(null, "", `#${heading.id}`);
    });
    item.appendChild(link);
    toc?.appendChild(item);
    links.push(link);
  });
  if (!headings.length && tocSidebar) tocSidebar.hidden = true;

  if (headings.length && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        links.forEach((link) => {
          link.classList.toggle("is-active", link.dataset.target === entry.target.id);
        });
      });
    }, {rootMargin: "-18% 0px -72% 0px"});
    headings.forEach((heading) => observer.observe(heading));
  }

  const desktopProgress = document.getElementById("tip-progress-fill");
  const mobileProgress = document.getElementById("tips-mobile-progress-fill");
  const updateProgress = () => {
    const top = articleBody.getBoundingClientRect().top + window.scrollY;
    const available = Math.max(articleBody.offsetHeight - window.innerHeight, 1);
    const progress = Math.max(0, Math.min(1, (window.scrollY - top + window.innerHeight * 0.35) / available));
    if (desktopProgress) desktopProgress.style.width = `${progress * 100}%`;
    if (mobileProgress) mobileProgress.style.width = `${progress * 100}%`;
  };
  window.addEventListener("scroll", updateProgress, {passive: true});
  window.addEventListener("resize", updateProgress);
  updateProgress();

  document.getElementById("tip-back-to-top")?.addEventListener("click", () => {
    window.scrollTo({top: 0, behavior: reduceMotion ? "auto" : "smooth"});
  });
});
