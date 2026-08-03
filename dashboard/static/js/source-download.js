(() => {
  "use strict";
  const dataNode = document.getElementById("source-download-data");
  if (!dataNode) return;
  let payload;
  try { payload = JSON.parse(dataNode.textContent); } catch (_) { return; }

  const status = document.getElementById("source-copy-status");
  const announce = (message) => {
    if (!status) return;
    status.textContent = message;
    window.setTimeout(() => { if (status.textContent === message) status.textContent = ""; }, 2500);
  };
  const copy = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (_) {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    announce("클립보드에 복사했습니다. Excel에 바로 붙여넣을 수 있습니다.");
  };

  const matrixRows = () => {
    const rows = [["데이터 종류", "단위", ...(payload.periods || [])]];
    (payload.rows || []).forEach((row) => {
      rows.push([row.label, row.unit, ...row.values.map((value) => value == null ? "" : value)]);
    });
    return rows;
  };
  const tsv = (rows) => rows.map((row) => row.join("\t")).join("\r\n");
  document.getElementById("copy-source-matrix")?.addEventListener("click", () => copy(tsv(matrixRows())));
  document.getElementById("copy-source-raw")?.addEventListener("click", () => {
    const rows = [["일자", "분류", "데이터 종류", "값", "단위", "출처"]];
    (payload.rawRows || []).forEach((row) => rows.push([row.date, row.category, row.label, row.value, row.unit, row.source]));
    copy(tsv(rows));
  });
  document.getElementById("download-source-csv")?.addEventListener("click", () => {
    const escape = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = matrixRows().map((row) => row.map(escape).join(",")).join("\r\n");
    const blob = new Blob(["\ufeff", csv], {type: "text/csv;charset=utf-8"});
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `casino-in-source-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
    announce("CSV 파일을 다운로드했습니다.");
  });

  document.querySelectorAll("[data-source-select]").forEach((button) => {
    button.addEventListener("click", () => {
      const checked = button.dataset.sourceSelect === "all";
      document.querySelectorAll('.source-series-options input[type="checkbox"]').forEach((input, index) => {
        input.checked = checked && index < 30;
      });
    });
  });

  const chart = document.getElementById("source-chart");
  const chartSelect = document.getElementById("source-chart-series");
  const svgElement = (name, attrs = {}) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", name);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  };
  const renderChart = (seriesKey) => {
    if (!chart) return;
    chart.replaceChildren();
    const row = (payload.rows || []).find((item) => item.series_key === seriesKey);
    if (!row) return;
    const entries = row.values.map((value, index) => ({value, index})).filter((item) => item.value != null && Number.isFinite(Number(item.value)));
    if (entries.length < 2) {
      const empty = document.createElement("p"); empty.textContent = "그래프를 그리려면 두 개 이상의 값이 필요합니다."; chart.appendChild(empty); return;
    }
    const width = 1000, height = 320, padX = 54, padY = 34;
    const values = entries.map((item) => Number(item.value));
    const min = Math.min(...values), max = Math.max(...values), spread = max - min || 1;
    const x = (index) => padX + index / Math.max(1, row.values.length - 1) * (width - padX * 2);
    const y = (value) => height - padY - (Number(value) - min) / spread * (height - padY * 2);
    const points = entries.map((item) => `${x(item.index).toFixed(1)},${y(item.value).toFixed(1)}`).join(" ");
    const svg = svgElement("svg", {viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", "aria-hidden": "true"});
    const defs = svgElement("defs");
    const gradient = svgElement("linearGradient", {id: "source-chart-gradient", x1: "0", y1: "0", x2: "0", y2: "1"});
    gradient.append(svgElement("stop", {offset: "0%", "stop-color": "currentColor", "stop-opacity": ".28"}), svgElement("stop", {offset: "100%", "stop-color": "currentColor", "stop-opacity": "0"}));
    defs.appendChild(gradient); svg.appendChild(defs);
    svg.appendChild(svgElement("polygon", {points: `${x(entries[0].index)},${height-padY} ${points} ${x(entries.at(-1).index)},${height-padY}`, fill: "url(#source-chart-gradient)"}));
    svg.appendChild(svgElement("polyline", {points, fill: "none", stroke: "currentColor", "stroke-width": "3", "vector-effect": "non-scaling-stroke"}));
    entries.forEach((item) => {
      const circle = svgElement("circle", {cx: x(item.index), cy: y(item.value), r: "5", tabindex: "0"});
      const title = svgElement("title"); title.textContent = `${payload.periods[item.index]}: ${Number(item.value).toLocaleString()} ${row.unit}`; circle.appendChild(title); svg.appendChild(circle);
    });
    chart.appendChild(svg);
    const caption = document.createElement("p"); caption.textContent = `${row.label} · ${row.unit} · ${row.source_name}`; chart.appendChild(caption);
  };
  chartSelect?.addEventListener("change", () => renderChart(chartSelect.value));
  if (chartSelect?.value) renderChart(chartSelect.value);
})();
