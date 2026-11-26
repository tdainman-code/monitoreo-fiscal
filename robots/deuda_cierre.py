"""Deuda fiscal al cierre de balance (Gaby, 26/11/2026). Primera parte: los PLANES DE PAGO en cualquier estado.

Para una fecha de cierre F, por cada plan de Mis Facilidades (robot_planes_todos):
  - Plan consolidado DESPUÉS de F: las obligaciones que incluye con vencimiento hasta F eran deuda a F
    (se toma el "Saldo a Cancelar" de cada obligación: lo que quedaba después de los pagos imputados).
  - Plan consolidado hasta F: la deuda a F es el capital de las cuotas no pagadas a F (sin pago registrado hasta F;
    si no hay fecha de pago, la cuota cancelada cuenta como pagada si venció hasta F). El interés financiero de esas
    cuotas va aparte (es interés futuro, no deuda a F).
Falta (cuando Gaby lo muestre): deuda de Cuentas Tributarias a F y los conceptos del F.931 de "estado de deuda".
Excel al repositorio permanente: DATOS/<cuit>/biblioteca/_conciliaciones/deuda_cierre/<AAAA-MM-DD>.xlsx
"""
from __future__ import annotations

import calendar
import glob
import json
import os
import re
from datetime import date

from . import lector_situacion as ls

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


def _dicts(tabla: dict) -> list[dict]:
    cab = tabla.get("encabezados") or []
    return [dict(zip(cab, f.get("celdas") or [])) for f in tabla.get("filas") or []]


def _g(d: dict, *claves) -> str:
    for k in d:
        if any(re.sub(r"\W", "", k).lower().startswith(re.sub(r"\W", "", c).lower()) for c in claves):
            return d[k]
    return ""


def mes_cierre(cuit: str) -> int | None:
    try:
        from . import avisos
        v = (avisos.contactos().get(cuit) or {}).get("mes_cierre") or ""
    except Exception:
        v = ""
    v = str(v).strip().lower()
    if v in MESES:
        return MESES.index(v) + 1
    if v.isdigit() and 1 <= int(v) <= 12:
        return int(v)
    r = sorted(glob.glob(os.path.join(DATOS, cuit, "sistema_registral", "*.json")))
    if r:
        try:
            mc = json.load(open(r[-1], encoding="utf-8")).get("mes_cierre")
            if str(mc).isdigit() and 1 <= int(mc) <= 12:
                return int(mc)
        except (OSError, ValueError):
            pass
    return None


def cierres(cuit: str, hoy: date | None = None, n: int = 2) -> list[date]:
    """Las n últimas fechas de cierre de balance ya pasadas."""
    hoy = hoy or date.today()
    m = mes_cierre(cuit) or 12                       # sin mes de cierre en la ficha: 31/12 (el más común)
    out, a = [], hoy.year
    while len(out) < n:
        f = date(a, m, calendar.monthrange(a, m)[1])
        if f < hoy:
            out.append(f)
        a -= 1
    return out


def _norm(t) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().lower()


def leer_cuotas(tabla: dict) -> dict[int, dict]:
    """Pantalla Ver Pagos (SeguimientoDetallePagos). Cada cuota puede ocupar 2 filas (1° y 2° vencimiento, con
    rowspan en Cuota N°, Capital y Estado). En la columna Pago dice "Pago" en la fila del vencimiento en que se pagó;
    si hay un botón (celda vacía) no se pagó en ese vencimiento. Caso Nabajuma T587743 (caduco): cuota 6 pagada al
    2° vencimiento, cuotas 1/5/7 impagas, cuotas posteriores a la caducidad sin estado."""
    out, actual = {}, None
    for f in tabla.get("filas") or []:
        c = [(x or "").strip() for x in f.get("celdas") or []]
        if not c or _norm(c[0]).startswith(("total", "cuota")):
            continue
        fechas = [ls.fecha(x) for x in c if ls.fecha(x)]
        pago = any(_norm(x) == "pago" for x in c)
        if re.fullmatch(r"\d+", c[0]) and len(c) >= 7:
            actual = int(c[0])
            est = c[-1] if not ls.fecha(c[-1]) and _norm(c[-1]) != "pago" and ls.importe(c[-1]) is None else ""
            out[actual] = {"cuota": actual, "capital": ls.importe(c[1]) or 0.0, "interes": ls.importe(c[2]) or 0.0,
                           "estado": est, "vencimientos": [], "pagada_el": None, "importe_pagado": None}
        elif actual is None:
            continue
        q = out[actual]
        if fechas:
            q["vencimientos"].append(fechas[0])
        if pago and fechas and not q["pagada_el"]:
            q["pagada_el"] = fechas[0]
            imps = [ls.importe(x) for x in c if ls.importe(x) is not None and not ls.fecha(x)]
            q["importe_pagado"] = imps[-1] if imps else None
    return out


def _pagada_al(q: dict, f: date) -> bool:
    if q["pagada_el"]:
        return q["pagada_el"] <= f
    # Cancelada sin la marca "Pago" (débito u otra forma): se toma pagada a su 1° vencimiento.
    return "cancelad" in _norm(q["estado"]) and bool(q["vencimientos"]) and min(q["vencimientos"]) <= f


def calcular(datos: dict, f: date) -> dict:
    """Deuda a la fecha f por los planes de pago.
    Las obligaciones originales del plan bajan por las cuotas pagadas; ARCA no siempre lo muestra en
    "Total Pagos Imputados" (en planes caducos suele quedar en 0 aunque se pagaron cuotas). Por eso:
      - plan consolidado hasta f: saldo a f = consolidado - capital de las cuotas pagadas hasta f
        (= capital de las cuotas no pagadas a f). Sirve igual para vigente, caduco o cancelado: una cuota pagada
        después de f no baja la deuda a f. El saldo se reparte entre las obligaciones del plan en proporción.
      - plan consolidado después de f: las obligaciones con vencimiento hasta f eran deuda a f, por su monto.
    """
    planes, oblig, cuotas = [], [], []
    for p in datos.get("planes") or []:
        d = (datos.get("detalle") or {}).get(p["numero"]) or {}
        cons = date.fromisoformat(p["presentacion"]) if p.get("presentacion") else None
        obs = _dicts(d.get("obligaciones") or {})
        fila = {"numero": p["numero"], "tipo": p.get("tipo"), "consolidacion": p.get("presentacion"),
                "situacion": p.get("situacion"), "cuotas": p.get("cuotas"), "consolidado": p.get("consolidado"),
                "capital_pagado_a_cierre": 0.0, "capital_a_cierre": 0.0, "interes_cuotas_pendientes": 0.0,
                "criterio": "", "nota": d.get("error", "")}
        if not cons:
            fila["criterio"] = "sin fecha de consolidación"
        elif cons > f:
            fila["criterio"] = "consolidado después del cierre: obligaciones vencidas hasta el cierre, por su monto"
            for o in obs:
                vto = ls.fecha(_g(o, "Fecha Vto"))
                monto = ls.importe(_g(o, "Monto Obligación")) or 0.0
                if vto and vto <= f:
                    oblig.append({"plan": p["numero"], "impuesto": _g(o, "Imp"), "concepto": _g(o, "Cpto"),
                                  "subconcepto": _g(o, "Subcpto"), "periodo": "/".join(x for x in (_g(o, "Mes"), _g(o, "Año")) if x),
                                  "vencimiento": vto.isoformat(), "monto": monto,
                                  "pagos_hoy": ls.importe(_g(o, "Total Pagos")) or 0.0, "saldo": monto})
                    fila["capital_a_cierre"] += monto
        else:
            qs = leer_cuotas(d.get("pagos") or {})
            if not qs and d.get("cronograma"):                   # sin pantalla de pagos: cronograma sin pagos
                qs = {c["cuota"]: {"cuota": c["cuota"], "capital": c["capital"] or 0.0, "interes": c["int_financiero"] or 0.0,
                                   "estado": "", "vencimientos": [x for x in (c["venc_1"], c["venc_2"]) if x],
                                   "pagada_el": None, "importe_pagado": None} for c in ls.leer_plan_de_pago(d["cronograma"])}
            base = p.get("consolidado") or sum(q["capital"] for q in qs.values())
            pagado = sum(q["capital"] for q in qs.values() if _pagada_al(q, f))
            for q in qs.values():
                if not _pagada_al(q, f):
                    cuotas.append({"plan": p["numero"], "cuota": q["cuota"],
                                   "vencimiento": min(q["vencimientos"]).isoformat() if q["vencimientos"] else "",
                                   "capital": q["capital"], "interes": q["interes"], "estado": q["estado"],
                                   "pagada_el": q["pagada_el"].isoformat() if q["pagada_el"] else ""})
                    fila["interes_cuotas_pendientes"] += q["interes"]
            fila["capital_pagado_a_cierre"] = pagado
            fila["capital_a_cierre"] = max(base - pagado, 0.0)
            fila["criterio"] = ("consolidado hasta el cierre: consolidado menos capital de cuotas pagadas hasta el cierre"
                                + (" (plan caduco: ARCA puede no mostrar los pagos imputados)" if "caduc" in _norm(p.get("situacion")) else ""))
            tot = sum(ls.importe(_g(o, "Monto Obligación")) or 0.0 for o in obs)
            for o in obs:
                monto = ls.importe(_g(o, "Monto Obligación")) or 0.0
                oblig.append({"plan": p["numero"], "impuesto": _g(o, "Imp"), "concepto": _g(o, "Cpto"),
                              "subconcepto": _g(o, "Subcpto"), "periodo": "/".join(x for x in (_g(o, "Mes"), _g(o, "Año")) if x),
                              "vencimiento": (ls.fecha(_g(o, "Fecha Vto")) or "") and ls.fecha(_g(o, "Fecha Vto")).isoformat(),
                              "monto": monto, "pagos_hoy": ls.importe(_g(o, "Total Pagos")) or 0.0,
                              "saldo": round(fila["capital_a_cierre"] * monto / tot, 2) if tot else 0.0})
        for k in ("capital_pagado_a_cierre", "capital_a_cierre", "interes_cuotas_pendientes"):
            fila[k] = round(fila[k], 2)
        planes.append(fila)
    return {"cierre": f.isoformat(), "planes": planes, "obligaciones": oblig, "cuotas": cuotas,
            "total_planes": round(sum(p["capital_a_cierre"] for p in planes), 2)}


F931 = {"28", "301", "302", "312", "351", "352", "360"}


def cuentas_tributarias(scth: dict | None, f: date) -> dict:
    """Deuda de Cuentas Tributarias a la fecha f (Gaby 26/11/2026): del estado de cumplimiento, el mismo lugar de donde
    salen los saldos para el F.399, pero la columna DEUDA; solo las DDJJ, no los intereses (a la fecha del cierre eran
    menores). Incluye los conceptos del F.931 que la pantalla de deuda no muestra (obras sociales, ART, seguro de vida).
    Período mensual AAAAMM00: hasta el mes del cierre; anual AAAA0000: hasta el año del cierre. Los del mes (o año) del
    cierre vencen después: se marcan."""
    filas = []
    for d in (scth or {}).get("deudas") or []:
        if not re.search(r"DDJJ|DECLARACI", str(d.get("concepto") or ""), re.I) or re.search(r"INTER", str(d.get("concepto") or ""), re.I):
            continue
        per = str(d.get("periodo") or "")
        if not re.fullmatch(r"\d{8}", per):
            continue
        anio, mes = int(per[:4]), int(per[4:6])
        clave = anio * 100 + (mes or 12)
        if clave > f.year * 100 + f.month:
            continue
        filas.append({"impuesto": f"{d.get('impuesto')} - {d.get('nombre', '')}".strip(" -"), "periodo": per,
                      "periodo_txt": f"{mes:02d}/{anio}" if mes else f"Anual {anio}", "concepto": d.get("concepto") or "",
                      "cuota": d.get("cuota") or "", "deuda": round(d.get("deuda") or 0.0, 2),
                      "f931": str(d.get("impuesto")) in F931 or bool(d.get("f931")),
                      "vence_despues": clave == f.year * 100 + f.month or (not mes and anio == f.year)})
    filas.sort(key=lambda x: (x["impuesto"], x["periodo"]))
    return {"filas": filas, "total": round(sum(x["deuda"] for x in filas), 2),
            "total_f931": round(sum(x["deuda"] for x in filas if x["f931"]), 2), "leido": (scth or {}).get("fecha", ""),
            "hay": bool(scth)}


def pagos_posteriores(pagos_sct: dict | None, f: date) -> dict:
    """Pagos con fecha posterior al cierre e imputados a períodos hasta el cierre (Gaby 26/11/2026: "no tomaste en
    cuenta los pagos posteriores"): eran deuda a la fecha del cierre. El F.800 se separa: suele ser de intereses."""
    filas = []
    from datetime import timedelta
    # los pagos leídos tienen que arrancar a más tardar el día siguiente al cierre
    if pagos_sct and date.fromisoformat(pagos_sct.get("desde") or "1900-01-01") <= f + timedelta(days=1):
        for p in pagos_sct.get("pagos") or []:
            per = str(p.get("periodo") or "")
            if not re.fullmatch(r"\d{8}", per) or date.fromisoformat(p["fecha"]) <= f:
                continue
            anio, mes = int(per[:4]), int(per[4:6])
            if anio * 100 + (mes or 12) > f.year * 100 + f.month:
                continue
            filas.append({**p, "periodo_txt": f"{mes:02d}/{anio}" if mes else f"Anual {anio}",
                          "posible_interes": str(p.get("formulario")) == "800"})
    filas.sort(key=lambda x: (x["impuesto"], x["periodo"], x["fecha"]))
    return {"filas": filas, "total": round(sum(x["importe"] for x in filas if not x["posible_interes"]), 2),
            "total_f800": round(sum(x["importe"] for x in filas if x["posible_interes"]), 2),
            "hay": bool(pagos_sct) and date.fromisoformat(pagos_sct.get("desde") or "1900-01-01") <= f + timedelta(days=1),
            "desde": (pagos_sct or {}).get("desde", "")}


def excel(cuit: str, r: dict, destino: str, leido: str = "") -> str:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    neg, cab = Font(bold=True), PatternFill("solid", fgColor="1F4E78")

    def hoja(ws, cols, filas, anchos):
        ws.append(cols)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = cab
        for f in filas:
            ws.append(f)
        for i, w in enumerate(anchos, 1):
            ws.column_dimensions[ws.cell(1, i).column_letter].width = w
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "Resumen"
    for k, v in (("CUIT", cuit), ("Deuda fiscal al", r["cierre"]), ("Planes leídos de Mis Facilidades el", leido),
                 ("Planes de pago: capital adeudado al cierre", r["total_planes"]),
                 ("Cuentas Tributarias: DDJJ impagas HOY de períodos hasta el cierre (sin intereses)",
                  r["ct"]["total"] if r.get("ct", {}).get("hay") else "falta correr Deuda histórica (Cuentas Tributarias)"),
                 ("   de las cuales F.931 (incluye obras sociales, ART, seguro de vida)", r.get("ct", {}).get("total_f931", 0.0)),
                 ("Pagos posteriores al cierre de períodos hasta el cierre (eran deuda al cierre)",
                  r["pp"]["total"] if r.get("pp", {}).get("hay") else "falta leer los pagos (pedir de nuevo la deuda al cierre)"),
                 ("TOTAL deuda fiscal al cierre", round(r["total_planes"] + (r.get("ct", {}).get("total") or 0.0)
                                                       + (r.get("pp", {}).get("total") or 0.0), 2)),
                 ("   aparte, pagos con F.800 posteriores (verificar: suelen ser intereses; no suman)", r.get("pp", {}).get("total_f800", 0.0)),
                 ("Estado de cumplimiento leído el", r.get("ct", {}).get("leido", ""))):
        ws.append([k, v])
    for fila in (4, 5, 6, 7, 8, 9):
        ws[f"B{fila}"].number_format = "#,##0.00"
    ws["A4"].font = ws["B4"].font = ws["A8"].font = ws["B8"].font = neg
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 52
    hoja(wb.create_sheet("Planes"), ["Plan", "Tipo", "Consolidación", "Situación hoy", "Cuotas", "Consolidado",
                                     "Capital pagado hasta el cierre", "Capital adeudado al cierre", "Interés de cuotas pendientes", "Criterio", "Nota"],
         [[p["numero"], p["tipo"], p["consolidacion"], p["situacion"], p["cuotas"], p["consolidado"],
           p["capital_pagado_a_cierre"], p["capital_a_cierre"], p["interes_cuotas_pendientes"], p["criterio"], p["nota"]]
          for p in r["planes"]],
         (11, 30, 13, 16, 8, 15, 18, 18, 18, 70, 30))
    hoja(wb.create_sheet("Obligaciones al cierre"),
         ["Plan", "Impuesto", "Concepto", "Subconcepto", "Período", "Vencimiento", "Monto obligación",
          "Pagos imputados (ARCA hoy)", "Saldo al cierre"],
         [[o["plan"], o["impuesto"], o["concepto"], o["subconcepto"], o["periodo"], o["vencimiento"], o["monto"],
           o["pagos_hoy"], o["saldo"]] for o in r["obligaciones"]], (11, 32, 20, 20, 10, 12, 16, 18, 16))
    hoja(wb.create_sheet("Cuotas pendientes al cierre"),
         ["Plan", "Cuota", "Vencimiento", "Capital", "Interés financiero", "Estado hoy", "Pagada el"],
         [[c["plan"], c["cuota"], c["vencimiento"], c["capital"], c["interes"], c["estado"], c["pagada_el"]]
          for c in r["cuotas"]], (11, 7, 12, 15, 16, 18, 12))
    ct = r.get("ct") or {}
    hoja(wb.create_sheet("Cuentas Tributarias"),
         ["Impuesto", "Período", "Concepto", "Anticipo / cuota", "Deuda (sin intereses)", "F.931", "Vence después del cierre"],
         [[x["impuesto"], x["periodo_txt"], x["concepto"], x["cuota"], x["deuda"], "Sí" if x["f931"] else "",
           "Sí" if x["vence_despues"] else ""] for x in ct.get("filas") or []], (38, 12, 26, 14, 18, 8, 14))
    pp = r.get("pp") or {}
    hoja(wb.create_sheet("Pagos posteriores al cierre"),
         ["Fecha de pago", "Formulario", "Impuesto", "Período", "Importe", "Observaciones", "Suma"],
         [[x["fecha"], x["formulario"], x["impuesto"], x["periodo_txt"], x["importe"], x["observaciones"],
           "no (F.800: verificar si es interés)" if x["posible_interes"] else "sí"] for x in pp.get("filas") or []],
         (13, 11, 38, 12, 16, 40, 30))
    for w in wb.worksheets[1:]:
        for row in w.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value, float):
                    c.number_format = "#,##0.00"
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    wb.save(destino)
    return destino


def _ultimo_json(cuit: str, carpeta: str) -> dict | None:
    r = sorted(glob.glob(os.path.join(DATOS, cuit, carpeta, "[0-9]*.json")))
    if not r:
        return None
    try:
        with open(r[-1], encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _ultimo_scth(cuit: str) -> dict | None:
    r = sorted(glob.glob(os.path.join(DATOS, cuit, "sct_historico", "[0-9]*.json")))
    if not r:
        return None
    try:
        with open(r[-1], encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def generar(cuit: str, hoy: date | None = None, fechas: list[date] | None = None) -> list[str]:
    """Excel de deuda al cierre para las últimas fechas de cierre (o las pedidas). Devuelve las fechas hechas."""
    r = sorted(glob.glob(os.path.join(DATOS, cuit, "planes_todos", "*.json")))
    if not r:
        return []
    with open(r[-1], encoding="utf-8") as fh:
        datos = json.load(fh)
    hechas = []
    for f in fechas or cierres(cuit, hoy):
        res = calcular(datos, f)
        res["ct"] = cuentas_tributarias(_ultimo_scth(cuit), f)
        res["pp"] = pagos_posteriores(_ultimo_json(cuit, "pagos_sct"), f)
        excel(cuit, res, os.path.join(DATOS, cuit, "biblioteca", "_conciliaciones", "deuda_cierre", f"{f.isoformat()}.xlsx"),
              datos.get("fecha", ""))
        hechas.append(f.strftime("%d/%m/%Y"))
    return hechas
