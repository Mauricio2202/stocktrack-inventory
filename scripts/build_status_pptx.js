// Genera docs/acceptance/StockTrack_Estatus_Pruebas.pptx a partir de docs/acceptance/results.json
// Uso: node scripts/build_status_pptx.js   (requiere pptxgenjs; el módulo apply_theme.js viene del skill pptx)
const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const ROOT = path.resolve(__dirname, "..");
const ASSETS = path.join(ROOT, "docs", "acceptance", "assets");
const OUT = path.join(ROOT, "docs", "acceptance", "StockTrack_Estatus_Pruebas.pptx");
const APPLY_THEME = process.env.APPLY_THEME_JS ||
  "/root/.claude/skills/synced/64ac577b-cf32-495b-adda-061c99e79aa5_d35e4186-4627-4b86-9273-5c85e589fa3f/pptx/scripts/apply_theme.js";

const data = JSON.parse(fs.readFileSync(path.join(ROOT, "docs", "acceptance", "results.json"), "utf8"));
const results = data.results;
const M = (id) => (results.find((r) => r.case_id === id) || { metrics: {} }).metrics;
const fmt = (n, d = 0) => Number(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });

// ---- conteos reales
const count = (pred) => results.filter(pred).length;
const total = results.length, passed = count((r) => r.outcome === "passed");
const failed = count((r) => r.outcome === "failed"), skipped = count((r) => r.outcome === "skipped");
const TOTAL_TESTS = 57; // total de pruebas de la última corrida de `pytest tests`
const CRITERIA = [
  ["PA-01", "Reportes", "PDF y Excel válidos, con totales y filtros correctos"],
  ["PA-02", "Alertas", "Correo SMTP, notificaciones por rol y sin duplicados"],
  ["PA-03", "Concurrencia", "10 usuarios, sin sobreventa ni datos corruptos"],
  ["RN-01", "Roles", "Administrador, gerente, almacenista y consulta"],
  ["RN-02", "Capacidad", "Tope de 100,000 registros y rendimiento a ese volumen"],
];
const per = CRITERIA.map(([id]) => {
  const rs = results.filter((r) => r.case_id.startsWith(id + "."));
  return [rs.filter((r) => r.outcome === "passed").length, rs.filter((r) => r.outcome === "failed").length,
          rs.filter((r) => r.outcome === "skipped").length];
});

// ---- tema (colores sobrios: azul noche dominante, verde azulado y ocre de apoyo)
const THEME = {
  name: "StockTrack Pruebas", headFontFace: "Cambria", bodyFontFace: "Calibri",
  colors: { dk1: "10243B", lt1: "FFFFFF", dk2: "0F2742", lt2: "EEF3F8", accent1: "0E7F8A", accent2: "B7791F",
            accent3: "5B6B7E", accent4: "8FB8C2", accent5: "9B1C1C", accent6: "2F6B4F", hlink: "0E7F8A", folHlink: "5B6B7E" },
};
const HEX = { navy: "0F2742", teal: "0E7F8A", ochre: "B7791F", slate: "5B6B7E", red: "9B1C1C", green: "2F6B4F", pale: "EEF3F8", line: "D5DDE6" };

const pres = new pptxgen();
pres.layout = "LAYOUT_16x9"; // 10" x 5.625"
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "StockTrack · Estado de las pruebas de aceptación";
pres.author = "StockTrack";
const C = pres.SchemeColor;

pres.defineSlideMaster({
  title: "TITULO_OSCURO", background: { color: C.text2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 1.75, w: 4.7, h: 1.3, fontFace: "Cambria", fontSize: 38, bold: true, color: C.background1, align: "left", valign: "top", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENIDO", background: { color: C.background1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.5, y: 0.35, w: 9, h: 0.75, fontFace: "Cambria", fontSize: 30, bold: true, color: C.text2, align: "left", valign: "middle", margin: 0 }, text: "" } },
    { text: { text: "StockTrack · Pruebas de aceptación", options: { x: 0.5, y: 5.2, w: 5, h: 0.25, fontSize: 10, color: C.accent3, margin: 0, fontFace: "Calibri" } } },
  ],
  slideNumber: { x: 9.0, y: 5.2, w: 0.5, h: 0.25, fontSize: 10, color: C.accent3, align: "right", fontFace: "Calibri" },
});

const shadow = () => ({ type: "outer", color: "000000", opacity: 0.25, blur: 10, offset: 3, angle: 90 });
const chartText = { catAxisLabelFontFace: "+mn-lt", valAxisLabelFontFace: "+mn-lt", dataLabelFontFace: "+mn-lt",
                    legendFontFace: "+mn-lt", titleFontFace: "+mn-lt" };

function card(slide, x, y, w, h, big, label, color, name) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h, rectRadius: 0.08, fill: { color: C.background2 },
    line: { color: HEX.line, width: 0.75 }, objectName: `${name} fondo` });
  slide.addText(big, { x: x + 0.15, y, w: Math.min(1.7, w * 0.42), h, fontFace: "Cambria", fontSize: 32, bold: true, color,
    valign: "middle", margin: 0, isTextBox: true, objectName: `${name} cifra` });
  const lx = x + 0.15 + Math.min(1.7, w * 0.42) + 0.1;
  slide.addText(label, { x: lx, y, w: x + w - lx - 0.15, h, fontSize: 12, color: C.text1, valign: "middle", margin: 0,
    isTextBox: true, objectName: `${name} texto` });
}

// ============================================================ 1 · Portada
pres.addSection({ title: "Resumen" });
let s = pres.addSlide({ masterName: "TITULO_OSCURO", sectionTitle: "Resumen" });
s.addImage({ path: path.join(ASSETS, "logo-white.png"), x: 0.6, y: 0.5, w: 2.6, h: 0.65, altText: "Logo StockTrack, control total de inventarios" });
s.addText("Pruebas de aceptación", { placeholder: "title" });
s.addText("Estado de la ejecución · 14 de noviembre de 2026", { x: 0.6, y: 3.05, w: 4.6, h: 0.4, fontSize: 16, color: C.background2, margin: 0, isTextBox: true, objectName: "Subtítulo" });
s.addText(`${passed}/${total}`, { x: 0.6, y: 3.7, w: 2.1, h: 0.9, fontFace: "Cambria", fontSize: 50, bold: true, color: C.accent4, margin: 0, valign: "middle", isTextBox: true, objectName: "Cifra principal" });
s.addText("casos de aceptación aprobados", { x: 2.75, y: 3.7, w: 2.5, h: 0.9, fontSize: 14, color: C.background2, margin: 0, valign: "middle", isTextBox: true, objectName: "Etiqueta cifra" });
s.addImage({ path: path.join(ASSETS, "dashboard.png"), x: 5.5, y: 0.7, w: 4.0, h: 2.49, shadow: shadow(), altText: "Panel de inventario de StockTrack con indicadores y productos en escasez" });
s.addImage({ path: path.join(ASSETS, "alertas.png"), x: 6.1, y: 3.0, w: 3.4, h: 2.12, shadow: shadow(), altText: "Pantalla de alertas de escasez de StockTrack" });
s.addNotes(`Estado de las pruebas de aceptación de StockTrack. ${passed} de ${total} casos automatizados aprobados; la aceptación formal del cliente sigue pendiente.`);

// ============================================================ 2 · Estatus general
s = pres.addSlide({ masterName: "CONTENIDO", sectionTitle: "Resumen" });
s.addText("Estatus general de las pruebas", { placeholder: "title" });
const slices = [["Aprobado", passed, HEX.green], ["Fallido", failed, HEX.red], ["Omitido", skipped, HEX.ochre]].filter((x) => x[1] > 0);
s.addChart(pres.charts.DOUGHNUT, [{ name: "Casos", labels: slices.map((x) => x[0]), values: slices.map((x) => x[1]) }], {
  x: 0.4, y: 1.25, w: 4.4, h: 3.8, holeSize: 64, chartColors: slices.map((x) => x[2]), showLegend: true, legendPos: "b",
  legendFontSize: 12, legendColor: HEX.navy, showValue: true, showPercent: false, dataLabelColor: "FFFFFF", dataLabelFontSize: 14,
  dataLabelFontBold: true, showTitle: true, title: "Resultado de los casos de aceptación", titleFontSize: 13, titleColor: HEX.navy, ...chartText,
});
s.addText([{ text: `${passed}`, options: { fontSize: 34, bold: true, color: HEX.navy, breakLine: true } }, { text: `de ${total} casos`, options: { fontSize: 12, color: HEX.slate } }],
  { x: 1.6, y: 2.45, w: 2.0, h: 1.0, align: "center", valign: "middle", margin: 0, fontFace: "Cambria", isTextBox: true, objectName: "Centro del doughnut" });
card(s, 5.1, 1.3, 4.4, 1.15, `${passed}/${total}`, "casos de aceptación aprobados en la ejecución automatizada", HEX.teal, "KPI casos");
card(s, 5.1, 2.6, 4.4, 1.15, `${TOTAL_TESTS}`, `pruebas automatizadas en total (${total} de aceptación, ${TOTAL_TESTS - total} unitarias y de seguridad)`, HEX.navy, "KPI pruebas");
card(s, 5.1, 3.9, 4.4, 1.15, `0/${total}`, "casos con aceptación formal del cliente; se registra en la hoja «Casos» del Excel", HEX.ochre, "KPI cliente");
s.addNotes("El doughnut muestra el resultado automatizado. La aceptación del cliente es un paso aparte y está pendiente.");

// ============================================================ 3 · Por criterio
s = pres.addSlide({ masterName: "CONTENIDO", sectionTitle: "Resumen" });
s.addText("Resultados por criterio de aceptación", { placeholder: "title" });
const cats = CRITERIA.map((c) => c[0]);
s.addChart(pres.charts.BAR, [
  { name: "Aprobado", labels: cats, values: per.map((p) => p[0]) },
  { name: "Fallido", labels: cats, values: per.map((p) => p[1]) },
  { name: "Omitido", labels: cats, values: per.map((p) => p[2]) },
], {
  x: 0.4, y: 1.25, w: 5.0, h: 3.85, barDir: "bar", barGrouping: "stacked", chartColors: [HEX.green, HEX.red, HEX.ochre],
  showValue: true, dataLabelPosition: "ctr", dataLabelColor: "FFFFFF", dataLabelFontSize: 12, dataLabelFontBold: true, dataLabelFormatCode: "#,##0;;;",
  catAxisLabelColor: HEX.navy, catAxisLabelFontSize: 12, catAxisOrientation: "maxMin", valAxisLabelColor: HEX.slate, valAxisLabelFontSize: 10,
  valAxisMajorUnit: 1, valAxisMinVal: 0, valGridLine: { color: HEX.line, size: 0.5 }, catGridLine: { style: "none" },
  showLegend: true, legendPos: "b", legendFontSize: 11, legendColor: HEX.navy, showTitle: true, title: "Casos por criterio", titleFontSize: 13, titleColor: HEX.navy, ...chartText,
});
const rows = [];
CRITERIA.forEach(([id, name, desc], i) => {
  rows.push({ text: `${id} · ${name}`, options: { bold: true, fontSize: 14, color: HEX.navy, breakLine: true, paraSpaceBefore: i ? 16 : 0 } });
  rows.push({ text: desc, options: { fontSize: 11, color: HEX.slate, breakLine: i < CRITERIA.length - 1 } });
});
s.addText(rows, { x: 5.7, y: 1.3, w: 3.8, h: 3.75, valign: "top", margin: 0, isTextBox: true, objectName: "Criterios" });
s.addNotes("PA-01 a PA-03 son las pruebas de aceptación pedidas por el cliente. RN-01 y RN-02 cubren el requerimiento de roles y la restricción de 100,000 registros.");

// ============================================================ 4 · Concurrencia
pres.addSection({ title: "Rendimiento" });
s = pres.addSlide({ masterName: "CONTENIDO", sectionTitle: "Rendimiento" });
const c1 = M("PA-03.1"), c2 = M("PA-03.2");
s.addText(`${c1.usuarios_concurrentes} usuarios simultáneos, ${c1.errores === 0 ? "sin errores" : c1.errores + " errores"}`, { placeholder: "title" });
s.addChart(pres.charts.BAR, [{ name: "Milisegundos", labels: ["Mediana páginas", "p95 páginas", "Máx. página", "p95 escrituras", "p95 reporte Excel"],
  values: [c1.paginas_mediana_ms, c1.paginas_p95_ms, c1.paginas_max_ms, c1.escrituras_p95_ms, c1.reporte_excel_p95_ms] }], {
  x: 0.4, y: 1.25, w: 5.5, h: 3.45, barDir: "col", chartColors: [HEX.teal], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "#,##0",
  dataLabelColor: HEX.navy, dataLabelFontSize: 11, catAxisLabelColor: HEX.navy, catAxisLabelFontSize: 10, valAxisLabelColor: HEX.slate, valAxisLabelFontSize: 10,
  valGridLine: { color: HEX.line, size: 0.5 }, catGridLine: { style: "none" }, showLegend: false, showTitle: true, title: "Tiempo de respuesta con 10 usuarios (ms)",
  titleFontSize: 13, titleColor: HEX.navy, valAxisTitle: "ms", showValAxisTitle: false, ...chartText,
});
s.addText(`Criterio: p95 de páginas ≤ 1,000 ms y reporte Excel ≤ 3,000 ms. La mediana de un solo usuario fue ${c1.base_un_usuario_mediana_ms} ms; con 10 usuarios, ${c1.paginas_mediana_ms} ms.`,
  { x: 0.5, y: 4.72, w: 5.4, h: 0.45, fontSize: 11, color: HEX.slate, margin: 0, valign: "top", isTextBox: true, objectName: "Nota criterio" });
const gx = 6.15, gw = 1.6, gh = 1.75;
const stat = (x, y, big, label, color, name) => {
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: gw, h: gh, rectRadius: 0.08, fill: { color: C.background2 }, line: { color: HEX.line, width: 0.75 }, objectName: `${name} fondo` });
  s.addText(big, { x, y: y + 0.2, w: gw, h: 0.8, align: "center", valign: "middle", fontFace: "Cambria", fontSize: 30, bold: true, color, margin: 0, isTextBox: true, objectName: `${name} cifra` });
  s.addText(label, { x: x + 0.1, y: y + 1.0, w: gw - 0.2, h: 0.65, align: "center", valign: "top", fontSize: 11, color: C.text1, margin: 0, isTextBox: true, objectName: `${name} texto` });
};
stat(gx, 1.3, fmt(c1.solicitudes), "solicitudes HTTP en la prueba mixta", HEX.navy, "Stat solicitudes");
stat(gx + gw + 0.15, 1.3, fmt(c1.errores), "errores de servidor o conexión", HEX.green, "Stat errores");
stat(gx, 1.3 + gh + 0.15, fmt(c1.rendimiento_solicitudes_por_s), "solicitudes por segundo", HEX.teal, "Stat rendimiento");
stat(gx + gw + 0.15, 1.3 + gh + 0.15, `${c2.aceptadas}/${c2.rechazadas}`, `salidas aceptadas / rechazadas de ${c2.intentos} intentos: sin sobreventa`, HEX.ochre, "Stat sobreventa");
s.addNotes("Servidor HTTP real con hilos y 10 usuarios con sesión propia, por loopback y en un solo equipo. El criterio aplicado fue absoluto; la mediana sí sube frente a un solo usuario.");

// ============================================================ 5 · Capacidad
s = pres.addSlide({ masterName: "CONTENIDO", sectionTitle: "Rendimiento" });
const cap = M("RN-02.2");
s.addText(`${fmt(cap.registros_activos)} productos activos`, { placeholder: "title" });
card(s, 0.5, 1.3, 3.6, 1.15, `${fmt(cap.registros_activos / 1000)} mil`, `registros activos cargados en ${cap.carga_masiva_s} s; el 100,001 se rechaza`, HEX.navy, "KPI carga");
card(s, 0.5, 2.6, 3.6, 1.15, `${fmt(cap.excel_100k_s, 1)} s`, `para generar el Excel completo (${fmt(cap.excel_filas)} filas, ${fmt(cap.excel_bytes / 1048576, 1)} MB)`, HEX.teal, "KPI excel");
card(s, 0.5, 3.9, 3.6, 1.15, "PDF", "se limita a 5,000 filas y sugiere Excel o filtros", HEX.ochre, "KPI pdf");
const pg = [["Panel", cap.panel_ms], ["Listado", cap.listado_ms], ["Última página", cap.pagina_ultima_ms], ["Búsqueda", cap.busqueda_ms], ["Filtro categoría", cap.filtro_categoria_ms], ["Solo escasez", cap.escasez_ms]];
s.addChart(pres.charts.BAR, [{ name: "Milisegundos", labels: pg.map((p) => p[0]), values: pg.map((p) => p[1]) }], {
  x: 4.4, y: 1.25, w: 5.1, h: 3.8, barDir: "bar", chartColors: [HEX.teal], showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "#,##0",
  dataLabelColor: HEX.navy, dataLabelFontSize: 11, catAxisLabelColor: HEX.navy, catAxisLabelFontSize: 12, catAxisOrientation: "maxMin", valAxisLabelColor: HEX.slate, valAxisLabelFontSize: 10,
  valGridLine: { color: HEX.line, size: 0.5 }, catGridLine: { style: "none" }, valAxisMinVal: 0, valAxisMaxVal: 2000, showLegend: false, showTitle: true,
  title: "Tiempo de página con 100,000 productos (ms; límite 2,000)", titleFontSize: 13, titleColor: HEX.navy, ...chartText,
});
s.addNotes("Medido con un solo usuario sobre SQLite y 100,000 productos activos.");

// ============================================================ 6 · Alcance
pres.addSection({ title: "Alcance" });
s = pres.addSlide({ masterName: "CONTENIDO", sectionTitle: "Alcance" });
s.addText("Alcance y siguientes pasos", { placeholder: "title" });
s.addImage({ path: path.join(ASSETS, "productos.png"), x: 0.5, y: 1.3, w: 3.7, h: 2.3, shadow: shadow(), altText: "Listado de productos de StockTrack con filtros, estado de stock y precios" });
s.addText("Catálogo de productos con datos de demostración", { x: 0.5, y: 3.68, w: 3.7, h: 0.3, fontSize: 11, color: HEX.slate, margin: 0, isTextBox: true, objectName: "Pie de imagen" });
s.addText([
  { text: "Limitaciones de esta corrida", options: { bold: true, fontSize: 16, color: HEX.navy, breakLine: true, fontFace: "Cambria", paraSpaceAfter: 4 } },
  { text: "Base probada: SQLite; PostgreSQL sin ejecutar", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Correo probado con un servidor SMTP de prueba", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Carga medida en un solo equipo, por loopback", options: { bullet: true, breakLine: true, paraSpaceAfter: 20 } },
  { text: "Siguientes pasos", options: { bold: true, fontSize: 16, color: HEX.navy, breakLine: true, fontFace: "Cambria", paraSpaceAfter: 4 } },
  { text: "Correr la suite con PostgreSQL y SMTP real", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Prueba de carga en el servidor de despliegue", options: { bullet: true, breakLine: true, paraSpaceAfter: 8 } },
  { text: "Aceptación formal del cliente en el Excel", options: { bullet: true } },
], { x: 4.6, y: 1.3, w: 4.9, h: 3.75, fontSize: 14, color: C.text1, valign: "top", margin: 0, isTextBox: true, objectName: "Alcance" });
s.addNotes("Las limitaciones están detalladas en la hoja Alcance del Excel de pruebas de aceptación.");

(async () => {
  await pres.writeFile({ fileName: OUT });
  const { applyTheme } = require(APPLY_THEME);
  await applyTheme(OUT, THEME);
  console.log("Guardado:", OUT);
})();
