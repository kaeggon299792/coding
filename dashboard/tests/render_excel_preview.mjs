import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const root = new URL("./_artifacts/", import.meta.url);
const xlsxPath = new URL("official_documents_excel_preview.xlsx", root);
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(fileURLToPath(xlsxPath)));
const inspection = await workbook.inspect({
  kind: "table",
  range: "DB!A1:O3",
  include: "values,formulas",
  tableMaxRows: 3,
  tableMaxCols: 15,
});
console.log(inspection.ndjson);
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);
for (const [sheetName, filename] of [["DB", "db_preview.png"], ["Metadata", "metadata_preview.png"]]) {
  const preview = await workbook.render({ sheetName, autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(new URL(filename, root), new Uint8Array(await preview.arrayBuffer()));
}
const exported = await SpreadsheetFile.exportXlsx(workbook);
await exported.save(fileURLToPath(new URL("official_documents_excel_verified.xlsx", root)));
