(() => {
  const numberFormatter = new Intl.NumberFormat("ko-KR", {
    maximumFractionDigits: 2,
  });

  document.querySelectorAll(".casino-interactive-chart").forEach((chart) => {
    const panel = chart.closest(
      ".casino-history-chart, .casino-share-chart, .casino-ms-trend-chart"
    );
    const tooltip = panel?.querySelector(".casino-chart-tooltip");
    if (!panel || !tooltip) return;

    const hide = () => {
      tooltip.classList.remove("is-visible");
      tooltip.setAttribute("aria-hidden", "true");
    };

    const show = (point, clientX, clientY) => {
      const value = Number(point.dataset.value);
      const year = document.createElement("b");
      const label = document.createElement("span");
      const formattedValue = document.createElement("strong");
      year.textContent = `${point.dataset.year}년`;
      label.textContent = point.dataset.label || "";
      formattedValue.textContent = `${numberFormatter.format(value)}${point.dataset.unit || ""}`;
      tooltip.replaceChildren(year, label, formattedValue);
      tooltip.classList.add("is-visible");
      tooltip.setAttribute("aria-hidden", "false");

      const panelRect = panel.getBoundingClientRect();
      const tooltipRect = tooltip.getBoundingClientRect();
      const left = Math.min(
        Math.max(clientX - panelRect.left + 12, 10),
        panelRect.width - tooltipRect.width - 10
      );
      const top = Math.max(clientY - panelRect.top - tooltipRect.height - 12, 10);
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    };

    chart.querySelectorAll(".casino-chart-hitpoint").forEach((point) => {
      point.addEventListener("pointerenter", (event) => {
        show(point, event.clientX, event.clientY);
      });
      point.addEventListener("pointermove", (event) => {
        show(point, event.clientX, event.clientY);
      });
      point.addEventListener("pointerleave", hide);
      point.addEventListener("focus", () => {
        const rect = point.getBoundingClientRect();
        show(point, rect.left + rect.width / 2, rect.top);
      });
      point.addEventListener("blur", hide);
      point.addEventListener("click", (event) => {
        show(point, event.clientX, event.clientY);
      });
    });

    chart.addEventListener("mouseleave", hide);
  });
})();
