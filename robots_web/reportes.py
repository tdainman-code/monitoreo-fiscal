"""Reportes en Excel desde la web (20/11/2026): falta de presentación de DDJJ de todos los clientes."""
from __future__ import annotations

import io
from datetime import date


def _fecha(v):
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def faltas_excel(filas: list[dict], titulo_filtro: str, hoy: date | None = None) -> bytes:
    """filas: [{cuit, nombre, encargado, d: {impuesto, concepto, periodo_txt, vencimiento, establecimiento}, fecha}]."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    hoy = hoy or date.today()
    azul, rojo = PatternFill("solid", fgColor="1F4E78"), PatternFill("solid", fgColor="FFC7CE")
    wb = Workbook()

    def hoja(ws, titulo, columnas, datos, anchos, marcar=None):
        ws["A1"] = titulo
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = f"Generado el {hoy.strftime('%d/%m/%Y')} · {titulo_filtro}"
        ws["A2"].font = Font(italic=True, color="595959")
        for j, c in enumerate(columnas, 1):
            cel = ws.cell(4, j, c)
            cel.font, cel.fill = Font(bold=True, color="FFFFFF"), azul
            cel.alignment = Alignment(horizontal="center", wrap_text=True)
            ws.column_dimensions[get_column_letter(j)].width = anchos[j - 1]
        for i, fila in enumerate(datos, 5):
            for j, v in enumerate(fila, 1):
                cel = ws.cell(i, j, v)
                if isinstance(v, date):
                    cel.number_format = "DD/MM/YYYY"
                if marcar and marcar(fila):
                    cel.fill = rojo
        if not datos:
            ws.cell(5, 1, "Sin faltas de presentación").font = Font(italic=True, color="595959")
        ws.freeze_panes = "A5"
        if datos:
            ws.auto_filter.ref = f"A4:{get_column_letter(len(columnas))}{4 + len(datos)}"

    det = []
    for f in sorted(filas, key=lambda x: (x["nombre"].upper(), str(x["d"].get("vencimiento") or ""))):
        d = f["d"]
        v = _fecha(d.get("vencimiento"))
        det.append([f["nombre"], f"{f['cuit'][:2]}-{f['cuit'][2:10]}-{f['cuit'][10]}", f.get("encargado") or "",
                    d.get("impuesto") or "", d.get("concepto") or "", d.get("periodo_txt") or d.get("periodo") or "", v,
                    (hoy - v).days if v and v < hoy else 0, _fecha(f.get("fecha"))])
    ws = wb.active
    ws.title = "Faltas de presentación"
    hoja(ws, "Falta de presentación de declaraciones juradas", ["Cliente", "CUIT", "Encargado", "Impuesto", "Concepto",
         "Período", "Vencimiento", "Días de atraso", "Datos de ARCA al"], det, [40, 15, 16, 34, 26, 12, 13, 10, 13],
         marcar=lambda r: r[7] > 30)
    por_cli = {}
    for r in det:
        x = por_cli.setdefault(r[1], [r[0], r[1], r[2], 0, None, set()])
        x[3] += 1
        x[4] = min(filter(None, [x[4], r[6]]), default=None)
        x[5].add(r[3])
    hoja(wb.create_sheet("Por cliente"), "Faltas de presentación por cliente",
         ["Cliente", "CUIT", "Encargado", "DDJJ sin presentar", "Vencimiento más antiguo", "Impuestos"],
         sorted(([*x[:5], ", ".join(sorted(x[5]))] for x in por_cli.values()), key=lambda r: -r[3]), [40, 15, 16, 12, 14, 60])
    por_imp = {}
    for r in det:
        x = por_imp.setdefault(r[3], [r[3], 0, set()])
        x[1] += 1
        x[2].add(r[1])
    hoja(wb.create_sheet("Por impuesto"), "Faltas de presentación por impuesto", ["Impuesto", "DDJJ sin presentar", "Clientes"],
         sorted(([x[0], x[1], len(x[2])] for x in por_imp.values()), key=lambda r: -r[1]), [40, 14, 10])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
