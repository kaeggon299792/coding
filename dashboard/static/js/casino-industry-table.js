(() => {
  const table = document.querySelector("[data-sortable-casino-table]");
  if (!table?.tBodies?.length) return;

  const body = table.tBodies[0];
  const buttons = [...table.querySelectorAll(".casino-sort-button")];
  const collator = new Intl.Collator("ko", { numeric: true, sensitivity: "base" });
  const datasetKey = (key) => `sort${key[0].toUpperCase()}${key.slice(1)}`;

  const valueFor = (row, key, type) => {
    const value = row.dataset[datasetKey(key)] ?? "";
    if (type === "number") {
      const number = Number(value);
      return Number.isFinite(number) ? number : Number.POSITIVE_INFINITY;
    }
    return value.trim();
  };

  buttons.forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sortKey;
      const type = button.dataset.sortType;
      const direction = button.dataset.direction === "asc" ? "desc" : "asc";
      const multiplier = direction === "asc" ? 1 : -1;

      buttons.forEach((item) => {
        item.dataset.direction = "";
        item.closest("th")?.setAttribute("aria-sort", "none");
        const indicator = item.querySelector("span");
        if (indicator) indicator.textContent = "↕";
      });
      button.dataset.direction = direction;
      button.closest("th")?.setAttribute(
        "aria-sort",
        direction === "asc" ? "ascending" : "descending"
      );
      const indicator = button.querySelector("span");
      if (indicator) indicator.textContent = direction === "asc" ? "↑" : "↓";

      const rows = [...body.rows];
      rows.sort((left, right) => {
        const leftValue = valueFor(left, key, type);
        const rightValue = valueFor(right, key, type);
        const result = type === "number"
          ? leftValue - rightValue
          : collator.compare(leftValue, rightValue);
        if (result !== 0) return result * multiplier;
        return Number(left.dataset.originalIndex) - Number(right.dataset.originalIndex);
      });
      rows.forEach((row) => body.appendChild(row));
    });
  });
})();
