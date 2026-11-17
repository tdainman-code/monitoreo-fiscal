"""Informes por cliente con el formato de los ejemplos armados a mano el 14/11/2026:

  relacion_dc_<CUIT>.xlsx       Relación débito/crédito, últimos 12 meses (columnas por mes, fórmulas vivas)
  situacion_fiscal_<CUIT>.xlsx  Resumen | Planes | Cronogramas | Deuda | Vencimientos 15 días | Notificaciones

Toma lo que bajaron los robots (no entra a ARCA):
  <CUIT>/libro_iva/<AAAA-MM>.json      Libro IVA del Portal IVA (meses presentados: fuente principal en RI)
  <CUIT>/<AAAA-MM>/resultado.json      Mis Comprobantes (emitidos / recibidos; mes en curso o monotributo)
  <CUIT>/f931/<AAAA-MM>.json           F931
  <CUIT>/sifere/<AAAA-MM>.json         SIFERE (impuesto determinado por jurisdicción)
  <CUIT>/situacion/<fecha>/resultado.json   Cuentas Tributarias + Mis Facilidades (la más reciente)
  <CUIT>/dfe/<fecha>/resultado.json    Domicilio Fiscal Electrónico (la más reciente)
"""
from __future__ import annotations

import glob
import json
import os
from datetime import date, timedelta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")

AZUL, AZUL_MES, CELESTE, GRIS, AMARILLO, ROSA = "1F4E78", "8EA9C1", "D9E1F2", "EDEDED", "FFEB9C", "FFC7CE"
NARANJA = "FCE4D6"      # mes tomado de Mis Comprobantes en un responsable inscripto: PROVISORIO
NUM = '#,##0.00;[Red]\\-#,##0.00;"-"'
PCT = "0.00%"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
JUR = {"901": "CABA", "902": "Buenos Aires", "903": "Catamarca", "904": "Córdoba", "905": "Corrientes",
       "906": "Chaco", "907": "Chubut", "908": "Entre Ríos", "909": "Formosa", "910": "Jujuy",
       "911": "La Pampa", "912": "La Rioja", "913": "Mendoza", "914": "Misiones", "915": "Neuquén",
       "916": "Río Negro", "917": "Salta", "918": "San Juan", "919": "San Luis", "920": "Santa Cruz",
       "921": "Santa Fe", "922": "Santiago del Estero", "923": "Tierra del Fuego", "924": "Tucumán"}


def _leer(ruta):
    if ruta and os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    return None


def _ultimo(patron):
    r = sorted(glob.glob(patron))
    return r[-1] if r else None


def _fill(c):
    return PatternFill("solid", fgColor=c)


def _f(v):
    if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-":
        return date.fromisoformat(v)
    if isinstance(v, str) and len(v) == 10 and v[2] == "/" and v[5] == "/":
        return date(int(v[6:]), int(v[3:5]), int(v[:2]))
    return v


# ================================================================ Relación débito / crédito
FILAS_VENTAS = [("Neto gravado 21%", "Neto gravado 21%"), ("Neto gravado 10,5%", "Neto gravado 10,5%"),
                ("Neto gravado 27%", "Neto gravado 27%"), ("Neto gravado otras alícuotas", "Neto gravado otras alícuotas")]
FILAS_F931 = [("Remuneraciones (Rem. 1)", "Remuneración total (Rem. 1)"),
              ("Contribuciones Seguridad Social", "Contribuciones S.S. (subtotal)"),
              ("Contribuciones Obra Social", "Contribuciones O.S. (subtotal)"),
              ("ART", "ART (L.R.T. total)"), ("Seguro de vida obligatorio", "Seguro de vida obligatorio"),
              ("RENATRE", "RENATRE")]


def relacion_dc(cuit: str, nombre: str, periodos: list[str], ruta: str) -> dict:
    # Pedido del estudio (17/11/2026): la relación débito/crédito se arma SOLO con Portal IVA (Libro IVA de las DJ
    # presentadas) y el F.931. Mis Comprobantes NO se usa acá (un mes sin DJ presentada queda vacío).
    mc = {p: None for p in periodos}
    # Libro IVA (Portal IVA): en responsables inscriptos es la fuente de los meses ya presentados
    # (incluye despachos de importación, servicios públicos y tiques que no están en Mis Comprobantes).
    liva = {p: _leer(os.path.join(DATOS, cuit, "libro_iva", f"{p}.json")) for p in periodos}
    from .lector_libro_iva import TIPOS_C
    for d_ in liva.values():                    # facturas B de compra: no se toman jamás (Gaby, 17/11/2026)
        if d_ and d_.get("comprobantes_compras") is not None and d_.get("compras"):
            d_["compras"]["Comprobantes B/C (sin IVA discriminado)"] = round(sum(
                c["total"] for c in d_["comprobantes_compras"] if c.get("b_c") and int(c.get("tipo") or 0) in TIPOS_C), 2)
    es_ri = any(liva.values()) or bool(glob.glob(os.path.join(DATOS, cuit, "libro_iva", "*.json")))
    provisorio = [p for p in periodos if es_ri and not liva.get(p) and mc.get(p)]
    f931 = {p: _leer(os.path.join(DATOS, cuit, "f931", f"{p}.json")) for p in periodos}
    sif = {p: _leer(os.path.join(DATOS, cuit, "sifere", f"{p}.json")) for p in periodos}
    arba = {p: _leer(os.path.join(DATOS, cuit, "arba", f"{p}.json")) for p in periodos}
    tiene_arba = any(arba.values())
    tiene_sifere = any(sif.values()) or os.path.isdir(os.path.join(DATOS, cuit, "sifere"))
    tiene_f931 = any(f931.values())
    jurs = sorted({j for d in sif.values() if d for j in d.get("jurisdicciones", {})})
    combustible_estimado = {}
    for p, d in mc.items():
        if liva.get(p):
            continue
        rec = ((d or {}).get("archivos") or {}).get("recibidos") or {}
        combustible_estimado[p] = (rec.get("resumen") or {}).get("  de ello estimado a confirmar", 0) or 0

    def val(p, tipo, concepto):
        if liva.get(p):
            return (liva[p].get("ventas" if tipo == "emitidos" else "compras") or {}).get(concepto, 0.0)
        d = mc.get(p)
        if not d:
            return None
        info = (d.get("archivos") or {}).get(tipo) or {}
        if not info.get("resumen") and info.get("registros") == 0:
            return 0.0
        return (info.get("resumen") or {}).get(concepto, 0.0)

    wb = Workbook()
    ws = wb.active
    ws.title = "Relación DC"
    n = len(periodos)
    ult = get_column_letter(n + 1)
    ws["A1"] = f"RELACIÓN DÉBITO / CRÉDITO — {nombre} — CUIT {cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A2"] = f"Últimos {n} meses: {periodos[0]} a {periodos[-1]}"
    ws["A2"].font = Font(color="595959")
    ws.cell(4, 1, "Concepto")
    for j, p in enumerate(periodos, 2):
        a, m = p.split("-")
        ws.cell(4, j, f"{MESES[int(m) - 1]}-{a[2:]}")
    for j in range(1, n + 2):
        c = ws.cell(4, j)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = _fill(AZUL if j == 1 else AZUL_MES)
        c.alignment = Alignment(horizontal="center")

    fila = [5]
    estilos = {}

    def seccion(titulo):
        r = fila[0]
        ws.cell(r, 1, titulo).font = Font(bold=True)
        for j in range(1, n + 2):
            ws.cell(r, j).fill = _fill(CELESTE)
        fila[0] += 1
        return r

    def datos(titulo, fn, fmt=NUM):
        r = fila[0]
        ws.cell(r, 1, titulo)
        for j, p in enumerate(periodos, 2):
            v = fn(p)
            if v is not None:
                ws.cell(r, j, v).number_format = fmt
        fila[0] += 1
        return r

    def formula(titulo, plantilla, fmt=NUM, total=True):
        r = fila[0]
        ws.cell(r, 1, titulo).font = Font(bold=total)
        for j in range(2, n + 2):
            col = get_column_letter(j)
            c = ws.cell(r, j, "=" + plantilla.format(c=col))
            c.number_format = fmt
            c.font = Font(bold=total)
        if total:
            for j in range(1, n + 2):
                ws.cell(r, j).fill = _fill(GRIS)
        fila[0] += 1
        return r

    # FUENTE de los datos de IVA de cada mes
    def fuente(p):
        if liva.get(p):
            s_ = liva[p].get("secuencia_portal") or 0
            return "Libro IVA" + (f" (rect. {s_})" if s_ else "")
        return "sin DJ presentada"
    r_fte = datos("Fuente de ventas y compras", fuente, "@")
    for j, p in enumerate(periodos, 2):
        c = ws.cell(r_fte, j)
        c.alignment = Alignment(horizontal="center")
        c.font = Font(italic=True, size=9, bold=p in provisorio, color="9C5700" if p in provisorio else "595959")
        if p in provisorio:
            c.fill = _fill(NARANJA)
    ws.cell(r_fte, 1).font = Font(italic=True, color="595959")
    # VENTAS
    seccion("VENTAS (Libro IVA – Portal IVA)")
    r_v0 = fila[0]
    rv = [datos(t, lambda p, k=k: val(p, "emitidos", k)) for t, k in FILAS_VENTAS]
    r_vng = formula("Neto gravado total", f"SUM({{c}}{rv[0]}:{{c}}{rv[-1]})")
    r_vnog = datos("No gravado", lambda p: val(p, "emitidos", "No gravado"))
    r_vex = datos("Exento", lambda p: val(p, "emitidos", "Exento"))
    r_vtot = formula("TOTAL VENTAS NETAS", f"{{c}}{r_vng}+{{c}}{r_vnog}+{{c}}{r_vex}")
    r_deb = datos("IVA Débito fiscal", lambda p: val(p, "emitidos", "Total IVA"))
    # COMPRAS
    seccion("COMPRAS (Libro IVA – Portal IVA)")
    rc = [datos(t, lambda p, k=k: val(p, "recibidos", k)) for t, k in FILAS_VENTAS]
    r_cng = formula("Neto gravado total", f"SUM({{c}}{rc[0]}:{{c}}{rc[-1]})")
    r_cnog = datos("No gravado", lambda p: val(p, "recibidos", "No gravado"))
    r_cex = datos("Exento", lambda p: val(p, "recibidos", "Exento"))
    r_cbc = datos("Facturas C (sin IVA discriminado; las B no se toman)",
                  lambda p: val(p, "recibidos", "Comprobantes B/C (sin IVA discriminado)"))
    r_comb = datos("Impuesto a los combustibles / otros tributos" if es_ri else "Impuesto a los combustibles",
                   lambda p: val(p, "recibidos", "Impuesto a los combustibles"))
    for j, p in enumerate(periodos, 2):
        if combustible_estimado.get(p):
            ws.cell(r_comb, j).fill = _fill(AMARILLO)
    _bcmc = (_leer(os.path.join(DATOS, cuit, "conciliacion", "compras_bc_fuera_libro.json")) or {}).get("por_mes") or {}
    r_bcmc = datos("Facturas C de Mis Comprobantes no cargadas en el Libro IVA",
                   lambda p: (_bcmc.get(p) or 0.0) if liva.get(p) else None)
    r_ctot = formula("TOTAL COMPRAS NETAS",
                     f"{{c}}{r_cng}+{{c}}{r_cnog}+{{c}}{r_cex}+{{c}}{r_cbc}+{{c}}{r_comb}+N({{c}}{r_bcmc})")
    r_cred = datos("IVA Crédito fiscal", lambda p: val(p, "recibidos", "Total IVA"))
    r_perc = datos("Percepciones / otros tributos (informativo)", lambda p: val(p, "recibidos", "Otros tributos / percepciones"))
    for j, p in enumerate(periodos, 2):            # meses provisorios: todo el bloque de IVA en naranja
        if p in provisorio:
            for r_ in range(r_v0, r_perc + 1):
                if ws.cell(r_, j).value is not None and ws.cell(r_, 1).fill.fgColor.rgb in (None, "00000000"):
                    ws.cell(r_, j).fill = _fill(NARANJA)
    # IVA
    seccion("IVA")
    formula("Saldo técnico (Débito − Crédito)", f"{{c}}{r_deb}-{{c}}{r_cred}")
    # F931
    seccion("SUELDOS Y CARGAS SOCIALES (F931)")
    g = lambda p, k: (f931.get(p) or {}).get(k) if f931.get(p) else None
    datos("Empleados en nómina", lambda p: g(p, "Empleados"), "0")
    r_rem = datos(FILAS_F931[0][0], lambda p: g(p, FILAS_F931[0][1]))
    rcs = [datos(t, lambda p, k=k: g(p, k)) for t, k in FILAS_F931[1:]]
    r_cs = formula("Total cargas sociales", f"SUM({{c}}{rcs[0]}:{{c}}{rcs[-1]})")
    r_sue = formula("TOTAL SUELDOS + CARGAS", f"{{c}}{r_rem}+{{c}}{r_cs}")
    # IIBB
    seccion("INGRESOS BRUTOS – Impuesto determinado (SIFERE y ARBA)")
    rj = []
    if tiene_arba:
        rj.append(datos("ARBA – Buenos Aires (contribuyente local)",
                        lambda p: (arba.get(p) or {}).get("impuesto_determinado") if arba.get(p) else None))
    for j_ in (jurs or ([] if tiene_sifere else [])):
        rj.append(datos(f"{j_} – {JUR.get(j_, '')}",
                        lambda p, j_=j_: ((sif.get(p) or {}).get("jurisdicciones", {}).get(j_) or {}).get("determinado")
                        if sif.get(p) else None))
    if rj:
        r_iibb = formula("Total determinado", f"SUM({{c}}{rj[0]}:{{c}}{rj[-1]})")
    else:
        r_iibb = datos("Total determinado", lambda p: None)
        ws.cell(r_iibb, 1).font = Font(bold=True)
    sin_iibb, locales = [], []
    # Alta en Convenio Multilateral = primer anticipo con DDJJ en SIFERE. Antes de eso el cliente pudo
    # tributar como local (ARBA / AGIP): esos meses no son "No presentada" sino otra fuente.
    con_dj = [p for p in periodos if sif.get(p)]
    alta_cm = min(con_dj) if con_dj else None
    for j, p in enumerate(periodos, 2):
        hay_ventas = val(p, "emitidos", "Neto gravado total")
        if not tiene_sifere or sif.get(p) or arba.get(p) or hay_ventas is None:
            continue
        if alta_cm and p < alta_cm:
            c = ws.cell(r_iibb, j, "ARBA s/dato")
            locales.append(p)
            c.font = Font(italic=True, color="595959")
            c.fill = _fill(GRIS)
        else:
            c = ws.cell(r_iibb, j, "No presentada")
            c.font = Font(bold=True)
            c.fill = _fill(AMARILLO)
            sin_iibb.append(p)
        c.alignment = Alignment(horizontal="center")
    # RESULTADO
    seccion("RESULTADO BRUTO")
    r_ero = formula("Total erogaciones (compras + sueldos y cargas + IIBB)",
                    f'IF({{c}}{r_vtot}=0,"",{{c}}{r_ctot}+{{c}}{r_sue}+N({{c}}{r_iibb}))')
    r_sal = formula("SALDO MENSUAL (Ventas − erogaciones)", f'IF({{c}}{r_vtot}=0,"",{{c}}{r_vtot}-{{c}}{r_ero})')
    # acumulado: el primer mes y después se le va sumando el de cada columna (pedido del 15/11)
    r_salac = formula("Saldo acumulado", f'IF({{c}}{r_vtot}=0,"",SUM($B${r_sal}:{{c}}{r_sal}))', total=False)
    r_ind = formula("Índice erogaciones / ventas", f'IF({{c}}{r_vtot}=0,"",{{c}}{r_ero}/{{c}}{r_vtot})', PCT, total=False)
    r_indac = formula("Índice acumulado (erogaciones / ventas acumuladas)",
                      f'IF({{c}}{r_vtot}=0,"",SUM($B${r_ero}:{{c}}{r_ero})/SUM($B${r_vtot}:{{c}}{r_vtot}))', PCT, total=False)
    for r_ in (r_salac, r_indac):
        for j in range(1, n + 2):
            ws.cell(r_, j).font = Font(italic=True, bold=(j == 1))
    r_mar = formula("Margen de utilidad bruto (1 − índice)", f'IF({{c}}{r_vtot}=0,"",1-{{c}}{r_ind})',
                    "0.00%;[Red]\\-0.00%")
    # rojo: mes con ventas o compras netas NEGATIVAS (notas de crédito mayores a lo facturado/comprado).
    # Puede ser real (movimiento no ordinario) pero distorsiona el saldo y los acumulados: hay que mirarlo.
    from openpyxl.formatting.rule import FormulaRule
    for r_tot in (r_vtot, r_ctot):
        rango = f"B{r_tot}:{ult}{r_tot}"
        ws.conditional_formatting.add(rango, FormulaRule(formula=[f"AND(ISNUMBER(B{r_tot}),B{r_tot}<0)"],
                                                         fill=_fill(ROSA), font=Font(bold=True, color="9C0006")))
    # amarillo: mes con alguna fuente faltante
    faltas = {}
    for j, p in enumerate(periodos, 2):
        f = []
        if mc.get(p) is None and liva.get(p) is None:
            continue
        if tiene_f931 and not f931.get(p):
            f.append("F931")
        if p in sin_iibb:
            f.append("IIBB")
        if p in locales:
            f.append("IIBB local (ARBA) sin dato")
        if f:
            faltas[p] = f
            for r in (r_sal, r_salac, r_ind, r_indac, r_mar):
                ws.cell(r, j).fill = _fill(AMARILLO)
    # notas
    r = fila[0] + 1
    ws.cell(r, 1, "Notas").font = Font(bold=True)
    notas = ["Ventas y compras: SOLO del Libro IVA de las DJ presentadas (Portal IVA). Sueldos y cargas sociales: F.931. "
             "No se usa Mis Comprobantes: un mes sin DJ de IVA presentada queda vacío.",
             "Facturas C de compra: se suman como gasto por el total (sin crédito fiscal). Las facturas B de compra no "
             "se toman nunca (no son computables)."] + ["Amarillo: impuesto a los combustibles ESTIMADO a confirmar (ver alertas del mes en Mis Comprobantes).",
             "'No presentada': anticipo sin DDJJ en SIFERE a la fecha de consulta (posterior al alta en Convenio Multilateral).",
             "'ARBA s/dato': mes anterior al alta en Convenio Multilateral sin DJ local leída en ARBA (falta la CIT o la DJ).",
             "Resultado bruto en amarillo: falta alguna fuente del mes (F931 o IIBB); el saldo se calcula sin ese concepto.",
             "Columnas en blanco: meses todavía no descargados por el robot.",
             "Rojo en TOTAL VENTAS/COMPRAS NETAS: el mes da negativo (notas de crédito mayores a lo facturado/comprado); revisar si es un movimiento no ordinario.",
             "Saldo e índice acumulados: muestran si la falencia del cliente se va corrigiendo o empeorando mes a mes.",
             "Indicadores de la relación débito/crédito: a definir."]
    for i, t in enumerate(notas, 1):
        ws.cell(r + i, 1, t).font = Font(color="595959")
    ws.column_dimensions["A"].width = 46
    for j in range(2, n + 2):
        ws.column_dimensions[get_column_letter(j)].width = 15
    ws.freeze_panes = "B5"
    ws.page_setup.orientation = "landscape"
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_setup.fitToHeight = 0
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    wb.save(ruta)
    return {"meses_mc": sum(1 for v in mc.values() if v), "meses_libro_iva": sum(1 for v in liva.values() if v),
            "provisorios": provisorio, "meses_f931": sum(1 for v in f931.values() if v),
            "meses_sifere": sum(1 for v in sif.values() if v), "faltas": faltas}


# ================================================================ Situación fiscal
def _hoja_tabla(wb, titulo, columnas, filas, anchos=None, formatos=None, color_fila=None):
    ws = wb.create_sheet(titulo)
    for j, c in enumerate(columnas, 1):
        cel = ws.cell(1, j, c)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = _fill(AZUL)
        cel.alignment = Alignment(horizontal="center", wrap_text=True)
    for i, f in enumerate(filas, 2):
        color = color_fila(f) if color_fila else None
        for j, c in enumerate(columnas, 1):
            v = _f(f.get(c))
            cel = ws.cell(i, j, v)
            if isinstance(v, float):
                cel.number_format = NUM
            elif isinstance(v, date):
                cel.number_format = "dd/mm/yyyy"
            if formatos and c in formatos:
                cel.number_format = formatos[c]
            if color:
                cel.fill = _fill(color)
    for j, c in enumerate(columnas, 1):
        ws.column_dimensions[get_column_letter(j)].width = (anchos or {}).get(c, max(12, min(55, len(c) + 4)))
    ws.freeze_panes = "A2"
    return ws


def situacion_fiscal(cuit: str, nombre: str, ruta: str, hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    sit = _leer(_ultimo(os.path.join(DATOS, cuit, "situacion", "*", "resultado.json"))) or {}
    dfe = _leer(_ultimo(os.path.join(DATOS, cuit, "dfe", "*", "resultado.json")))
    dfe_arba = _leer(_ultimo(os.path.join(DATOS, cuit, "arba_dfe", "[0-9]*", "resultado.json")))
    cm = _leer(_ultimo(os.path.join(DATOS, cuit, "sifere_deuda", "*.json")))
    sct, mf = sit.get("sct"), sit.get("mis_facilidades")
    wb = Workbook()
    ws = wb.active
    ws.title = "Resumen"
    filas = [("Concepto", "Valor")]
    filas.append((f"Datos al {_f(sit.get('fecha')):%d/%m/%Y}" if sit.get("fecha") else "SIN DATOS DE SITUACIÓN", ""))
    filas.append(("DEUDA (Sistema de Cuentas Tributarias)", None))
    if sct:
        cap_v = sum(d["capital"] for d in sct["deudas"] if d["vencida"])
        cap_nv = sum(d["capital"] for d in sct["deudas"] if not d["vencida"])
        intr = sum(d["int_resarcitorio"] + d["int_punitorio"] for d in sct["deudas"])
        filas += [("Capital vencido", cap_v), ("Intereses (resarcitorios + punitorios)", intr),
                  ("Total deuda vencida", sct["totales_leidos"]["vencido"]), ("Capital a vencer", cap_nv),
                  ("Obligaciones con deuda (cantidad)", len(sct["deudas"]))]
    else:
        filas.append(("Sin datos", "—"))
    filas += [("", None), ("FALTAS DE PRESENTACIÓN", None)]
    if sct:
        filas.append(("DDJJ pendientes de presentación (SCT)", len(sct["ddjj_pendientes"])))
        for d in sct["ddjj_pendientes"][:15]:
            filas.append((f"  {d['impuesto']} {d['periodo_txt']}", f"venció {_f(d['vencimiento']):%d/%m/%Y}" if d.get("vencimiento") else ""))
    if os.path.isdir(os.path.join(DATOS, cuit, "sifere")):
        ant = (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        if not _leer(os.path.join(DATOS, cuit, "sifere", f"{ant}.json")):
            filas.append((f"IIBB CM {ant[5:]}/{ant[:4]}", "No presentada"))
    filas += [("", None), ("PLANES DE FACILIDADES", None)]
    if mf:
        v = mf["vigentes"]
        imp15 = sum(p["importe_a_vencer_15_dias"] for p in v)
        filas += [("Planes vigentes", len(v)),
                  ("Consolidado total planes vigentes", sum(p.get("consolidado") or 0 for p in v)),
                  ("Saldo pendiente (cuotas)", sum(p["saldo_capital_pendiente"] for p in v)),
                  ("Cuotas vencidas impagas", sum(p["vencidas_impagas"] for p in v)),
                  ("Importe cuotas vencidas impagas", sum(p["importe_vencido_impago"] for p in v)),
                  ("Cuotas que vencen en 15 días", sum(p["a_vencer_15_dias"] for p in v)),
                  ("Importe cuotas que vencen en 15 días", imp15),
                  ("Planes caducos (últimos 12 meses)", sum(1 for a in mf["alertas"] if a["tipo"] == "Plan caduco"))]
    else:
        filas.append(("Sin datos", "—"))
    filas += [("", None), ("NOTIFICACIONES (DFE, últimos 60 días)", None)]
    if dfe:
        filas += [("Total comunicaciones", dfe["total"]),
                  ("Prioridad ALTA (por asunto)", sum(1 for c in dfe["comunicaciones"] if c["importancia"] == "ALTA")),
                  ("Pendientes de notificar (no abiertas)", dfe["sin_abrir"]),
                  ("  de ellas prioridad ALTA", dfe["altas_sin_abrir"])]
    else:
        filas.append(("Sin datos", "—"))
    if cm:
        filas += [("", None), (f"IIBB CONVENIO MULTILATERAL – DEUDA POR JURISDICCIÓN (SIFERE, {cm['desde']} a {cm['hasta']}, "
                               f"consulta {cm['fecha']})", None),
                  ("Deuda total (anticipos impagos)", cm.get("deuda_total", 0.0))]
        for j, v in cm["jurisdicciones"].items():
            imp = [a for a in v["anticipos"] if a["impago"]]
            filas.append((f"  {j} {v['nombre']}: {v['impagos']} anticipos impagos", v["deuda"]))
            for a in imp[-12:]:
                filas.append((f"      {a['anticipo']}  {a['estado']}", a["impago"]))
    if dfe_arba:
        filas += [("", None), ("NOTIFICACIONES ARBA (Domicilio Fiscal Electrónico)", None),
                  ("Total comunicaciones", dfe_arba["total"]),
                  ("Prioridad ALTA", sum(1 for c in dfe_arba["comunicaciones"] if c["importancia"] == "ALTA")),
                  ("Sin notificar (no se abrieron)", dfe_arba["sin_abrir"])]
        for c in [c for c in dfe_arba["comunicaciones"] if c["importancia"] == "ALTA"][:15]:
            filas.append((f"  {c['fecha']} {c['clasificacion']}: {c['asunto'][:70]}",
                          (c.get("plazo") or "") + (" — " if c.get("plazo") and c.get("resumen") else "") + (c.get("resumen") or "")[:250]))
    for i, (a, b) in enumerate(filas, 1):
        ws.cell(i, 1, a)
        if b is not None:
            c = ws.cell(i, 2, b)
            if isinstance(b, float):
                c.number_format = NUM
        if i == 1:
            for j in (1, 2):
                ws.cell(i, j).font = Font(bold=True, color="FFFFFF")
                ws.cell(i, j).fill = _fill(AZUL)
        elif b is None and a:
            for j in (1, 2):
                ws.cell(i, j).font = Font(bold=True)
                ws.cell(i, j).fill = _fill(CELESTE)
    ws.column_dimensions["A"].width = 48
    ws.column_dimensions["B"].width = 30

    # Planes
    planes = []
    if mf:
        for p in mf["vigentes"]:
            sig = next((c for c in p["detalle_cuotas"] if c["situacion"] == "A vencer"), None)
            planes.append({"Plan": p["numero"], "Tipo": p["tipo"], "Presentación": p["presentacion"],
                           "Cuotas": p["cuotas_total"] + (1 if p.get("con_anticipo") else 0),
                           "Consolidado": p.get("consolidado"), "Valor cuota": p["valor_cuota"],
                           "Cuotas pendientes": p["cuotas_pendientes"],
                           "Saldo pendiente (cuotas)": sum((c["total_1"] or 0) for c in p["detalle_cuotas"]
                                                           if c["situacion"] != "Pagada"),
                           "Cuotas vencidas impagas": p["vencidas_impagas"],
                           "Próximo vencimiento": sig["venc_1"] if sig else None,
                           "Importe próximo venc.": sig["total_1"] if sig else None,
                           "Vence en 15 días": "SÍ" if p["a_vencer_15_dias"] else "",
                           "Dato": "Con anticipo" if p.get("con_anticipo") else "Completo"})
    _hoja_tabla(wb, "Planes", ["Plan", "Tipo", "Presentación", "Cuotas", "Consolidado", "Valor cuota",
                               "Cuotas pendientes", "Saldo pendiente (cuotas)", "Cuotas vencidas impagas",
                               "Próximo vencimiento", "Importe próximo venc.", "Vence en 15 días", "Dato"],
                planes, {"Tipo": 55, "Saldo pendiente (cuotas)": 26, "Cuotas vencidas impagas": 25},
                color_fila=lambda f: ROSA if f["Cuotas vencidas impagas"] else (AMARILLO if f["Vence en 15 días"] else None))
    # Cronogramas
    wc = wb.create_sheet("Cronogramas")
    r = 1
    for p in (mf or {}).get("vigentes", []):
        wc.cell(r, 1, f"Plan {p['numero']} — {p['tipo']}").font = Font(bold=True)
        r += 1
        for j, c in enumerate(["Cuota", "Capital", "Int. financiero", "Total 1° venc.", "1° venc.", "Total 2° venc.",
                               "2° venc.", "Situación"], 1):
            cel = wc.cell(r, j, c)
            cel.font = Font(bold=True, color="FFFFFF")
            cel.fill = _fill(AZUL)
        r += 1
        for c in p["detalle_cuotas"]:
            vals = [c["cuota"], c["capital"], c.get("int_financiero"), c["total_1"], _f(c["venc_1"]), c["total_2"],
                    _f(c["venc_2"]), c["situacion"]]
            for j, v in enumerate(vals, 1):
                cel = wc.cell(r, j, v)
                if isinstance(v, float):
                    cel.number_format = NUM
                elif isinstance(v, date):
                    cel.number_format = "dd/mm/yyyy"
                if c["situacion"] == "Vencida impaga":
                    cel.fill = _fill(ROSA)
            r += 1
        r += 1
    for j, w in enumerate([14, 14, 17, 16, 12, 16, 12, 26], 1):
        wc.column_dimensions[get_column_letter(j)].width = w
    # Deuda
    wd = wb.create_sheet("Deuda")
    if sct:
        por_imp = {}
        for d in sct["deudas"]:
            x = por_imp.setdefault(d["impuesto"], [0.0, 0.0, 0.0])
            x[0] += d["capital"]
            x[1] += d["int_resarcitorio"] + d["int_punitorio"]
            x[2] += d["total"]
        cab = ["Impuesto", "Capital", "Intereses", "Total"]
        for j, c in enumerate(cab, 1):
            wd.cell(1, j, c).font = Font(bold=True)
        r = 2
        for imp, (a, b, t) in sorted(por_imp.items()):
            for j, v in enumerate([imp, a, b, t], 1):
                wd.cell(r, j, v).number_format = NUM if j > 1 else "General"
            r += 1
        wd.cell(r, 1, "TOTAL").font = Font(bold=True)
        for j in (2, 3, 4):
            c = wd.cell(r, j, f"=SUM({get_column_letter(j)}2:{get_column_letter(j)}{r - 1})")
            c.number_format = NUM
            c.font = Font(bold=True)
        r += 3
        cab = ["Impuesto", "Período", "Vencimiento", "Capital", "Int. resarcitorio", "Int. punitorio", "Total",
               "Situación", "Tipo"]
        for j, c in enumerate(cab, 1):
            wd.cell(r, j, c).font = Font(bold=True)
        r += 1
        for d in sct["deudas"]:
            vals = [d["impuesto"], d["periodo_txt"], _f(d["vencimiento"]), d["capital"], d["int_resarcitorio"],
                    d["int_punitorio"], d["total"], "Vencida" if d["vencida"] else "A vencer",
                    "Solo intereses" if not d["capital"] else "Capital + intereses"]
            for j, v in enumerate(vals, 1):
                c = wd.cell(r, j, v)
                if isinstance(v, float):
                    c.number_format = NUM
                elif isinstance(v, date):
                    c.number_format = "dd/mm/yyyy"
            r += 1
    else:
        wd["A1"] = "Sin datos de Cuentas Tributarias"
    for j, w in enumerate([29, 20, 20, 13, 19, 16, 20, 11, 21], 1):
        wd.column_dimensions[get_column_letter(j)].width = w
    # Vencimientos 15 días
    venc = []
    lim = hoy + timedelta(days=15)
    for v in (sct or {}).get("vencimientos", []):
        fv = _f(v["vencimiento"])
        if str(v.get("detalle", "")).startswith("Presentada"):
            continue
        if fv and hoy <= fv <= lim:
            venc.append({"Fecha": fv, "Obligación": f"{v['impuesto']} {v['periodo_txt']}",
                         "Tipo": v["detalle"], "Importe": None, "Fuente": "SCT - Vencimientos"})
    for p in (mf or {}).get("vigentes", []):
        for c in p["detalle_cuotas"]:
            fv = _f(c["venc_1"])
            if c["situacion"] == "A vencer" and fv and fv <= lim:
                venc.append({"Fecha": fv, "Obligación": f"Plan {p['numero']} - cuota {c['cuota']}/{p['cuotas_total']}",
                             "Tipo": "Débito cuota", "Importe": c["total_1"], "Fuente": "Mis Facilidades"})
    venc.sort(key=lambda x: x["Fecha"])
    _hoja_tabla(wb, "Vencimientos 15 días", ["Fecha", "Obligación", "Tipo", "Importe", "Fuente"], venc,
                {"Obligación": 45, "Tipo": 21, "Fuente": 35})
    # Notificaciones
    noti = [{"Recibida": c["fecha"], "Notificada": c["notificado"] or "Pendiente (no abierta)", "Asunto": c["asunto"],
             "Organismo": c["organismo"], "Prioridad (por asunto)": c["importancia"],
             "Clasificación": c["clasificacion"]} for c in (dfe or {}).get("comunicaciones", [])]
    _hoja_tabla(wb, "Notificaciones", ["Recibida", "Notificada", "Asunto", "Organismo", "Prioridad (por asunto)",
                                       "Clasificación"], noti,
                {"Notificada": 24, "Asunto": 55, "Organismo": 23, "Prioridad (por asunto)": 24, "Clasificación": 40},
                color_fila=lambda f: ROSA if f["Prioridad (por asunto)"] == "ALTA" and f["Notificada"].startswith("Pend") else None)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    wb.save(ruta)
    return {"situacion": bool(sit), "dfe": bool(dfe), "planes": len(planes)}
