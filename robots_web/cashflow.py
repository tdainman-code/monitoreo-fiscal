"""Cash flow proyectado de un cliente (Gaby, 26/11/2026: "a veces se lo piden los bancos o compañías de seguro").

Se arma con lo que el sistema ya tiene del cliente y con unos supuestos que el encargado puede cambiar:
  Base (promedio de los últimos meses completos de resultado_mensual: Libro IVA + F.931 + IIBB):
    ventas netas, compras netas, sueldos, cargas sociales, IIBB, débito y crédito fiscal.
  Cobranzas      = ventas + IVA débito, desplazadas según los días de cobro.
  Proveedores    = compras + IVA crédito, desplazadas según los días de pago.
  Sueldos        = se pagan el mes siguiente al devengado.  Cargas sociales (F.931) = mes siguiente.
  IVA            = saldo técnico del mes anterior (débito − crédito); el saldo a favor se arrastra.
  IIBB           = determinado del mes anterior.
  Anticipos y otras obligaciones por vencer = de Cuentas Tributarias, con su vencimiento e importe.
  Planes de pago = cuotas de los planes vigentes de Mis Facilidades, en el mes en que vencen.
  Autónomos / monotributo = última obligación mensual de la CCMA.
  Otros ingresos y egresos fijos (alquiler, servicios, préstamos…) = los carga el encargado.
  Inflación mensual = ajusta ventas, compras, sueldos y gastos fijos mes a mes.
Supuestos guardados en ROBOTS_WEB_DATOS/cashflow/<cuit>.json.

Gaby (26/11/2026): "el proyectado es imaginario: tiene que ganar plata para poder cubrir lo que va a pedir y tiene que
tener la explicación de la inflación y del crecimiento (motivos de por qué crecería)". Por eso:
  - crecimiento real mensual de las ventas (además de la inflación), con sus motivos por escrito;
  - explicación de la inflación tomada (fuente / criterio);
  - el financiamiento que se pide (monto, tasa, cuotas, mes, destino): entra el desembolso y salen las cuotas
    (sistema francés), y se mide la COBERTURA: flujo operativo del período / cuotas (los bancos piden 1,2 o más);
  - resultado operativo de cada mes (ventas − compras − sueldos − cargas − IIBB − gastos fijos).
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import date

from . import analisis, datos

DEFECTO = {"saldo_inicial": 0.0, "meses": 12, "dias_cobro": 30, "dias_pago": 30, "inflacion": 2.0,
           "meses_base": 6, "fijos": [], "ingresos": [], "notas": "",
           "crecimiento": 0.0, "motivos_crecimiento": "", "explicacion_inflacion": "",
           # como el "Presupuesto Financiero" de Gaby: costos con su propia inflación, nómina aparte, impuesto al
           # débito y crédito y gastos bancarios como % de lo que se mueve en el banco
           "inflacion_costos": 2.0, "aumento_nomina": 2.0, "impuesto_dc": 1.2, "gastos_bancarios": 0.5,
           "prestamo": {"monto": 0.0, "tasa_anual": 0.0, "cuotas": 12, "mes": 1, "destino": "", "entidad": ""}}


def cuota_francesa(monto: float, tasa_anual: float, cuotas: int) -> float:
    i = tasa_anual / 100 / 12
    if not monto or not cuotas:
        return 0.0
    return monto / cuotas if not i else monto * i / (1 - (1 + i) ** -cuotas)


def _ruta(cuit: str) -> str:
    return os.path.join(os.environ.get("ROBOTS_WEB_DATOS", "/var/lib/robots-web"), "cashflow", f"{cuit}.json")


def supuestos(cuit: str) -> dict:
    try:
        with open(_ruta(cuit), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return {**DEFECTO, **{k: v for k, v in d.items() if k in DEFECTO}}


def guardar(cuit: str, s: dict) -> None:
    os.makedirs(os.path.dirname(_ruta(cuit)), exist_ok=True)
    tmp = _ruta(cuit) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({k: s.get(k, DEFECTO[k]) for k in DEFECTO}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, _ruta(cuit))


def _mes(per: str, n: int) -> str:
    a, m = int(per[:4]), int(per[5:7]) + n
    a += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{a}-{m:02d}"


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _fecha(v) -> date | None:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(v or ""))
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", str(v or ""))
    return date(int(m[3]), int(m[2]), int(m[1])) if m else None


def base(cuit: str, meses_base: int) -> dict:
    res = [m for m in analisis.resultado_mensual(cuit) if m.get("completo") and (m.get("ventas") or m.get("erogaciones"))]
    ult = res[-meses_base:]
    if not ult:
        return {"meses": [], "n": 0}
    prom = lambda k: sum(_f(m.get(k)) for m in ult) / len(ult)
    b = {k: prom(k) for k in ("ventas", "compras", "compras_bc_mc", "sueldos", "cargas", "iibb", "debito", "credito")}
    b["compras"] += b.pop("compras_bc_mc")
    b.update(meses=[m["periodo"] for m in ult], n=len(ult), ultimo=ult[-1]["periodo"])
    return b


def calcular(cuit: str, s: dict | None = None, hoy: date | None = None) -> dict:
    s = {**DEFECTO, **(s or supuestos(cuit))}
    hoy = hoy or date.today()
    b = base(cuit, int(s["meses_base"]))
    n = max(1, min(int(s["meses"]), 24))
    inicio = f"{hoy.year}-{hoy.month:02d}"
    pers = [_mes(inicio, i) for i in range(n)]
    infl = _f(s["inflacion"]) / 100
    crec = _f(s.get("crecimiento")) / 100
    lag_c, lag_p = round(_f(s["dias_cobro"]) / 30), round(_f(s["dias_pago"]) / 30)
    f = datos.ficha(cuit)
    filas = {k: [0.0] * n for k in ("cobranzas", "otros_ingresos", "prestamo_ingreso", "proveedores", "sueldos", "cargas",
                                    "iva", "iibb", "anticipos", "planes", "autonomos", "fijos", "variables", "bancarios",
                                    "prestamo_cuotas")}
    infl_c = _f(s.get("inflacion_costos", s["inflacion"])) / 100
    nom = _f(s.get("aumento_nomina", s["inflacion"])) / 100
    resultado_op = [0.0] * n
    detalle = {"anticipos": [], "planes": []}
    if b["n"]:
        # el devengado de cada mes (con inflación desde el último mes de la base) se cobra / paga con su desplazamiento
        meses_dev = max(lag_c, lag_p, 1) + n
        dev0 = _mes(inicio, -max(lag_c, lag_p, 1))
        saldo_iva = 0.0
        for j in range(meses_dev):
            per = _mes(dev0, j)
            t = max(0, j - max(lag_c, lag_p, 1) + 1)            # meses desde el último de la base
            k_inf = (1 + nom) ** t                              # sueldos y cargas: aumento de nómina
            k_vol = (1 + infl) ** t * (1 + crec) ** t           # ventas: precios + crecimiento real
            k_cmp = (1 + infl_c) ** t * (1 + crec) ** t         # compras: costos + el mismo volumen
            ventas, compras = b["ventas"] * k_vol, b["compras"] * k_cmp
            deb, cred = b["debito"] * k_vol, b["credito"] * k_cmp
            if per in pers:                                     # resultado operativo devengado del mes
                resultado_op[pers.index(per)] = (ventas - compras - (b["sueldos"] + b["cargas"]) * k_inf
                                                 - b["iibb"] * k_vol)
            for col, val, lag in (("cobranzas", ventas + deb, lag_c), ("proveedores", compras + cred, lag_p),
                                  ("sueldos", b["sueldos"] * k_inf, 1), ("cargas", b["cargas"] * k_inf, 1),
                                  ("iibb", b["iibb"] * k_inf, 1)):
                destino = _mes(per, lag)
                if destino in pers:
                    filas[col][pers.index(destino)] += val
            saldo_iva += deb - cred
            pagar = max(0.0, saldo_iva)
            saldo_iva -= pagar
            destino = _mes(per, 1)
            if destino in pers:
                filas["iva"][pers.index(destino)] += pagar
    # obligaciones por vencer de Cuentas Tributarias (anticipos, cuotas, etc.) con su vencimiento
    for d in ((f.get("sct") or {}).get("deudas") or []):
        v = _fecha(d.get("vencimiento"))
        if d.get("vencida") or not v:
            continue
        per = f"{v.year}-{v.month:02d}"
        imp = _f(d.get("total") or d.get("capital"))
        if per in pers and imp > 0:
            filas["anticipos"][pers.index(per)] += imp
            detalle["anticipos"].append({"periodo": per, "concepto": f"{d.get('impuesto')} · {d.get('concepto')} "
                                         f"{d.get('periodo_txt') or ''} {('cuota ' + str(d.get('cuota'))) if d.get('cuota') not in (None, '', '0', 0) else ''}".strip(),
                                         "vencimiento": v.isoformat(), "importe": imp})
    # cuotas de planes de pago vigentes
    for p in ((f.get("mf") or {}).get("vigentes") or []):
        for c in p.get("detalle_cuotas") or []:
            if c.get("situacion") == "Pagada":
                continue
            v = _fecha(c.get("venc_1"))
            if not v:
                continue
            per = f"{v.year}-{v.month:02d}"
            if per in pers:
                imp = _f(c.get("total_1"))
                filas["planes"][pers.index(per)] += imp
                detalle["planes"].append({"periodo": per, "plan": p.get("numero"), "cuota": c.get("cuota"),
                                          "vencimiento": v.isoformat(), "importe": imp})
    # autónomos / monotributo: última obligación mensual
    cc = f.get("ccma") or {}
    ult_ob = 0.0
    for pr in reversed(cc.get("periodos") or []):
        if _f(pr.get("obligacion")):
            ult_ob = _f(pr.get("obligacion"))
            break
    for i in range(n):
        filas["autonomos"][i] = ult_ob
        k_inf = (1 + infl_c) ** i
        filas["fijos"][i] = sum(_f(x.get("importe")) for x in s["fijos"] if not _f(x.get("pct_ventas"))) * k_inf
        # gastos que van con las ventas (comisiones, fletes…): % de las cobranzas del mes
        filas["variables"][i] = sum(_f(x.get("pct_ventas")) for x in s["fijos"]) / 100 * filas["cobranzas"][i]
        filas["otros_ingresos"][i] = sum(_f(x.get("importe")) for x in s["ingresos"]) * (1 + infl) ** i
    pr = {**DEFECTO["prestamo"], **(s.get("prestamo") or {})}
    cuota = cuota_francesa(_f(pr["monto"]), _f(pr["tasa_anual"]), int(_f(pr["cuotas"])))
    if _f(pr["monto"]) > 0:
        m0 = max(1, int(_f(pr["mes"]))) - 1
        if m0 < n:
            filas["prestamo_ingreso"][m0] = _f(pr["monto"])
        for k in range(int(_f(pr["cuotas"]))):
            if m0 + 1 + k < n:
                filas["prestamo_cuotas"][m0 + 1 + k] = cuota
    for i in range(n):
        mov = filas["cobranzas"][i] + filas["otros_ingresos"][i]
        # impuesto al débito y crédito (0,6 % + 0,6 %) y comisiones bancarias, sobre lo que entra al banco
        filas["bancarios"][i] = mov * (_f(s.get("impuesto_dc")) + _f(s.get("gastos_bancarios"))) / 100
        resultado_op[i] -= filas["fijos"][i] + filas["variables"][i] + filas["bancarios"][i] + filas["autonomos"][i]
    ingresos = [filas["cobranzas"][i] + filas["otros_ingresos"][i] + filas["prestamo_ingreso"][i] for i in range(n)]
    egresos_k = ("proveedores", "sueldos", "cargas", "iva", "iibb", "anticipos", "planes", "autonomos", "fijos",
                 "variables", "bancarios", "prestamo_cuotas")
    egresos = [sum(filas[k][i] for k in egresos_k) for i in range(n)]
    saldo, ini, fin = _f(s["saldo_inicial"]), [], []
    for i in range(n):
        ini.append(saldo)
        saldo += ingresos[i] - egresos[i]
        fin.append(saldo)
    operativo = [ingresos[i] - filas["prestamo_ingreso"][i] - (egresos[i] - filas["prestamo_cuotas"][i]) for i in range(n)]
    tot_cuotas = sum(filas["prestamo_cuotas"])
    cobertura = (sum(operativo[i] for i in range(n) if filas["prestamo_cuotas"][i]) / tot_cuotas) if tot_cuotas else None
    return {"periodos": pers, "filas": {k: [round(x, 2) for x in v] for k, v in filas.items()},
            "resultado_operativo": [round(x, 2) for x in resultado_op], "flujo_operativo": [round(x, 2) for x in operativo],
            "cuota_prestamo": round(cuota, 2), "cobertura": round(cobertura, 2) if cobertura is not None else None,
            "prestamo": pr, "gana_plata": sum(resultado_op) > 0,
            "ingresos": [round(x, 2) for x in ingresos], "egresos": [round(x, 2) for x in egresos],
            "neto": [round(ingresos[i] - egresos[i], 2) for i in range(n)],
            "saldo_inicial": [round(x, 2) for x in ini], "saldo_final": [round(x, 2) for x in fin],
            "base": b, "supuestos": s, "detalle": detalle,
            "meses_negativos": [pers[i] for i in range(n) if fin[i] < 0]}


RENGLONES = [("cobranzas", "Cobranzas de ventas (con IVA)"), ("otros_ingresos", "Otros ingresos"),
             ("prestamo_ingreso", "Desembolso del financiamiento solicitado")]
EGRESOS = [("proveedores", "Pagos a proveedores (con IVA)"), ("sueldos", "Sueldos"), ("cargas", "Cargas sociales (F.931)"),
           ("iva", "IVA (saldo a pagar)"), ("iibb", "Ingresos Brutos"), ("anticipos", "Anticipos y obligaciones por vencer (ARCA)"),
           ("planes", "Cuotas de planes de pago"), ("autonomos", "Autónomos / monotributo"), ("fijos", "Gastos fijos"),
           ("variables", "Gastos que van con las ventas (comisiones, fletes…)"),
           ("bancarios", "Impuesto al débito y crédito y gastos bancarios"),
           ("prestamo_cuotas", "Cuotas del financiamiento solicitado")]


def excel(cuit: str, nombre: str, r: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter as L
    wb = Workbook()
    ws = wb.active
    ws.title = "Cash flow"
    azul, gris = PatternFill("solid", fgColor="1F4E78"), PatternFill("solid", fgColor="F2F2F2")
    neg = Font(bold=True)
    pers = r["periodos"]
    n = len(pers)
    ws.append([f"{nombre} — CUIT {datos.cuit_fmt(cuit)} — Cash flow proyectado (en pesos)"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append([f"Armado el {date.today():%d/%m/%Y} con los datos fiscales del cliente y los supuestos de la hoja 'Supuestos'"])
    ws.append([])
    ws.append(["Concepto"] + [f"{p[5:]}/{p[:4]}" for p in pers])
    for c in ws[4]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
    fila = 5
    ws.cell(fila, 1, "Saldo inicial de caja y bancos").font = neg
    ws.cell(fila, 2, r["supuestos"]["saldo_inicial"])
    f_ini = fila
    fila += 1
    ws.cell(fila, 1, "INGRESOS").font = neg
    fila += 1
    f_i0 = fila
    for k, t in RENGLONES:
        ws.cell(fila, 1, t)
        for i in range(n):
            ws.cell(fila, i + 2, r["filas"][k][i])
        fila += 1
    f_ti = fila
    ws.cell(fila, 1, "Total ingresos").font = neg
    for i in range(n):
        ws.cell(fila, i + 2, f"=SUM({L(i + 2)}{f_i0}:{L(i + 2)}{fila - 1})").font = neg
    fila += 2
    ws.cell(fila, 1, "EGRESOS").font = neg
    fila += 1
    f_e0 = fila
    for k, t in EGRESOS:
        ws.cell(fila, 1, t)
        for i in range(n):
            ws.cell(fila, i + 2, r["filas"][k][i])
        fila += 1
    f_te = fila
    ws.cell(fila, 1, "Total egresos").font = neg
    for i in range(n):
        ws.cell(fila, i + 2, f"=SUM({L(i + 2)}{f_e0}:{L(i + 2)}{fila - 1})").font = neg
    fila += 2
    f_neto = fila
    ws.cell(fila, 1, "Flujo neto del mes").font = neg
    for i in range(n):
        ws.cell(fila, i + 2, f"={L(i + 2)}{f_ti}-{L(i + 2)}{f_te}").font = neg
    fila += 1
    f_fin = fila
    ws.cell(fila, 1, "Saldo final").font = neg
    for i in range(n):
        ws.cell(fila, i + 2, f"={L(i + 2)}{f_ini}+{L(i + 2)}{f_neto}").font = neg
        ws.cell(fila, i + 2).fill = gris
        if i:
            ws.cell(f_ini, i + 2, f"={L(i + 1)}{f_fin}")
    fila += 2
    ws.cell(fila, 1, "Resultado operativo devengado del mes").font = neg
    for i in range(n):
        ws.cell(fila, i + 2, r["resultado_operativo"][i])
    if r.get("cobertura") is not None:
        fila += 1
        ws.cell(fila, 1, "Cobertura del financiamiento (flujo operativo / cuotas)").font = neg
        ws.cell(fila, 2, r["cobertura"]).number_format = "0.00"
    for row in ws.iter_rows(min_row=5, max_row=fila, min_col=2):
        for c in row:
            c.number_format = '#,##0;[Red]-#,##0'
    ws.column_dimensions["A"].width = 44
    for i in range(n):
        ws.column_dimensions[L(i + 2)].width = 14
    ws.freeze_panes = "B5"
    s, b = r["supuestos"], r["base"]
    w2 = wb.create_sheet("Supuestos")
    filas_s = [("Saldo inicial de caja y bancos", s["saldo_inicial"]), ("Días de cobro a clientes", s["dias_cobro"]),
               ("Días de pago a proveedores", s["dias_pago"]), ("Inflación de precios mensual (%)", s["inflacion"]),
               ("Inflación de costos mensual (%)", s.get("inflacion_costos")), ("Aumento de nómina mensual (%)", s.get("aumento_nomina")),
               ("Crecimiento real de ventas mensual (%)", s.get("crecimiento")),
               ("Impuesto al débito y crédito (% de lo que entra)", s.get("impuesto_dc")),
               ("Gastos bancarios (% de lo que entra)", s.get("gastos_bancarios")),
               ("Meses tomados como base", f"{b.get('n', 0)} ({', '.join(b.get('meses') or [])})"),
               ("Ventas netas promedio por mes (base)", round(b.get("ventas", 0), 2)),
               ("Compras netas promedio por mes (base)", round(b.get("compras", 0), 2)),
               ("Sueldos promedio por mes (F.931)", round(b.get("sueldos", 0), 2)),
               ("Cargas sociales promedio por mes (F.931)", round(b.get("cargas", 0), 2)),
               ("IIBB promedio por mes", round(b.get("iibb", 0), 2)),
               ("IVA débito / crédito promedio", f"{b.get('debito', 0):,.0f} / {b.get('credito', 0):,.0f}")]
    filas_s += [(f"Gasto: {x.get('concepto')}", f"{x.get('pct_ventas')} % de las ventas" if _f(x.get("pct_ventas")) else x.get("importe"))
                for x in s["fijos"]]
    filas_s += [(f"Otro ingreso: {x.get('concepto')}", x.get("importe")) for x in s["ingresos"]]
    if s.get("notas"):
        filas_s.append(("Notas", s["notas"]))
    w2.append(["Supuesto", "Valor"])
    for c in w2[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
    for x in filas_s:
        w2.append(list(x))
    w2.column_dimensions["A"].width = 44
    w2.column_dimensions["B"].width = 40
    w4 = wb.create_sheet("Fundamentos", 1)
    pr = r["prestamo"]
    textos = [("Inflación", f"{s['inflacion']} % mensual. " + (s.get("explicacion_inflacion") or "Falta explicar de dónde sale (REM del BCRA, presupuesto, etc.).")),
              ("Crecimiento real de las ventas", f"{s.get('crecimiento', 0)} % mensual además de la inflación. "
               + (s.get("motivos_crecimiento") or ("Sin crecimiento real." if not _f(s.get("crecimiento")) else "Falta explicar los motivos."))),
              ("Base histórica", f"Promedio de {b.get('n', 0)} meses completos ({', '.join(b.get('meses') or [])}) del Libro IVA, F.931 e IIBB presentados."),
              ("Resultado operativo proyectado", f"{sum(r['resultado_operativo']):,.0f} en {n} meses".replace(",", ".")
               + (" (gana plata)" if r["gana_plata"] else " (NO gana plata: revisar supuestos)"))]
    if _f(pr.get("monto")):
        textos += [("Financiamiento solicitado", f"{_f(pr['monto']):,.0f} en {int(_f(pr['cuotas']))} cuotas al {pr['tasa_anual']} % anual "
                    f"(cuota {r['cuota_prestamo']:,.0f}), desembolso en el mes {int(_f(pr['mes']))}"
                    + (f", {pr['entidad']}" if pr.get("entidad") else "") + ".".replace(",", ".")),
                   ("Destino de los fondos", pr.get("destino") or "Falta indicar el destino."),
                   ("Cobertura", f"{r['cobertura']:.2f} veces: el flujo operativo de los meses con cuota cubre las cuotas "
                    + ("holgadamente." if (r["cobertura"] or 0) >= 1.2 else "con poco margen (los bancos suelen pedir 1,2 o más).")
                    if r.get("cobertura") is not None else "—")]
    w4.append(["Fundamento", "Explicación"])
    for c in w4[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
    from openpyxl.styles import Alignment
    for t in textos:
        w4.append(list(t))
        w4.cell(w4.max_row, 2).alignment = Alignment(wrap_text=True, vertical="top")
    w4.column_dimensions["A"].width = 34
    w4.column_dimensions["B"].width = 100
    w3 = wb.create_sheet("Vencimientos fiscales")
    w3.append(["Mes", "Concepto", "Vencimiento", "Importe"])
    for c in w3[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), azul
    for x in sorted(r["detalle"]["anticipos"], key=lambda x: x["vencimiento"]):
        w3.append([x["periodo"], x["concepto"], x["vencimiento"], x["importe"]])
    for x in sorted(r["detalle"]["planes"], key=lambda x: x["vencimiento"]):
        w3.append([x["periodo"], f"Plan {x['plan']} cuota {x['cuota']}", x["vencimiento"], x["importe"]])
    for i, w in enumerate((10, 60, 14, 16), 1):
        w3.column_dimensions[L(i)].width = w
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
