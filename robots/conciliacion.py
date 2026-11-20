"""Conciliación de compras: Mis Comprobantes (recibidos) contra Libro IVA (Portal IVA). Responsables inscriptos.

Pedido del 16/11/2026:
  - Facturas de compra (NO B) que están en Mis Comprobantes y NO figuran en el Libro IVA de ese mes ni de los
    siguientes -> para ver si fue una omisión o si no correspondía tomarlas.
  - Control APOC: si el emisor está en la base de facturas apócrifas, la fila va en rojo con alerta.
  - Al revés, informativo: comprobantes del Libro IVA que no están en Mis Comprobantes (despachos de
    importación, servicios públicos, etc.).
Solo se comparan meses con Libro IVA bajado (DJ presentada). No entra a ARCA: usa lo que bajaron los robots.

VENTAS (pedido de Gaby, 17/11/2026: "nunca debería haber diferencias, pero no está de más controlar"):
  Mis Comprobantes EMITIDOS contra las ventas del Libro IVA, comprobante por comprobante (tipo + punto de venta +
  número) y en totales del mes (neto gravado e IVA):
  - emitido en Mis Comprobantes que no está en el Libro IVA de ese mes  -> ALTA (débito no declarado),
    o declarado en otro mes -> se marca en qué mes;
  - en el Libro IVA y no en Mis Comprobantes -> informativo (comprobantes manuales / controlador fiscal);
  - mismo comprobante con distinto neto o IVA -> diferencia de importe.

APOC: los "Comprobantes electrónicos observados" que ARCA le informa a cada cliente en Nuestra Parte
(robot_observados -> DATOS/<cuit>/observados/observados.json). Cada observado se cruza con el Libro IVA:
si quedó COMPUTADO como crédito, riesgo ALTO (habría que rectificar). Opcional: DATOS/apoc/apoc.csv con
CUIT de emisores apócrifos de otras fuentes.

Uso:  python3 -m robots.conciliacion --cuit 20331162788
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from datetime import date

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
INFORMES = os.environ.get("ROBOTS_INFORMES", "/var/lib/robots/informes")
TIPOS_B = {6, 7, 8, 9, 10, 82}            # B: no se concilian (no dan crédito)
# B y C (y sus NC/ND): no dan crédito fiscal, así que no son "no tomadas". Las C que están en Mis Comprobantes y no en
# el Libro IVA son un GASTO que se suma a las erogaciones; las B no se toman jamás (pedido de Gaby, 17/11/2026).
from .lector_libro_iva import TIPOS_B_C, TIPOS_C  # noqa: E402
NOTAS_CREDITO = {3, 8, 13, 53, 110, 112, 113, 114, 203, 208, 213}
NOMBRES = {1: "Factura A", 2: "Nota de Débito A", 3: "Nota de Crédito A", 11: "Factura C", 12: "Nota de Débito C",
           13: "Nota de Crédito C", 17: "Liq. Servicios Públicos A", 51: "Factura M", 63: "Liquidación A",
           66: "Despacho de importación", 81: "Tique Factura A", 83: "Tique"}


def _leer_json(r):
    with open(r, encoding="utf-8") as f:
        return json.load(f)


def base_apoc() -> set[str] | None:
    ruta = os.path.join(DATOS, "apoc", "apoc.csv")
    if not os.path.exists(ruta):
        return None
    with open(ruta, encoding="utf-8", errors="replace") as f:
        return {m for linea in f for m in re.findall(r"(?<!\d)(\d{11})(?!\d)", linea.replace("-", ""))}


def _clave(cuit, tipo, pv, num):
    return (str(cuit).strip().lstrip("0"), int(tipo), int(pv), int(num))


def _mc_recibidos(cuit: str, periodo: str) -> list[dict]:
    ruta = os.path.join(DATOS, cuit, periodo, "recibidos.csv")
    if not os.path.exists(ruta):
        return []
    from .lector_mis_comprobantes import leer
    df = leer(ruta)
    out = []
    for _, x in df.iterrows():
        try:
            num = int(str(x.get("Número Desde", "0")).split(".")[0] or 0)
            pv = int(str(x.get("Punto de Venta", "0")).split(".")[0] or 0)
        except ValueError:
            continue
        out.append({"periodo": periodo, "fecha": x["Fecha"].date(), "tipo": int(x["Tipo"]), "punto_venta": pv,
                    "numero": num, "cuit": str(x["CUIT contraparte"]).strip(), "nombre": x["Contraparte"],
                    "neto": float(x["Imp. Neto Gravado Total"]), "iva": float(x["Total IVA"]),
                    "total": float(x["Imp. Total"])})
    return out


def _mc_emitidos(cuit: str, periodo: str) -> list[dict]:
    ruta = os.path.join(DATOS, cuit, periodo, "emitidos.csv")
    if not os.path.exists(ruta):
        return []
    from .lector_mis_comprobantes import leer
    df = leer(ruta)
    out = []
    for _, x in df.iterrows():
        try:
            num = int(str(x.get("Número Desde", "0")).split(".")[0] or 0)
            h_txt = str(x.get("Número Hasta", "") or "").split(".")[0]
            hasta = int(h_txt) if h_txt.isdigit() else num
            pv = int(str(x.get("Punto de Venta", "0")).split(".")[0] or 0)
        except ValueError:
            continue
        out.append({"periodo": periodo, "fecha": x["Fecha"].date(), "tipo": int(x["Tipo"]), "punto_venta": pv,
                    "numero": num, "hasta": hasta, "cuit": str(x["CUIT contraparte"]).strip(), "nombre": x["Contraparte"],
                    "neto": float(x["Imp. Neto Gravado Total"]), "iva": float(x["Total IVA"]),
                    "total": float(x["Imp. Total"])})
    return out


def _liva_ventas(cuit: str, per: str, d: dict) -> list[dict] | None:
    """Comprobantes de ventas del Libro IVA: del JSON (desde el 17/11/2026) o, si es anterior, del zip bajado."""
    if d.get("comprobantes_ventas") is not None:
        return d["comprobantes_ventas"]
    z = os.path.join(DATOS, cuit, "libro_iva", f"{per}.zip")
    if not os.path.exists(z):
        return None
    from .lector_libro_iva import leer_zip
    try:
        return leer_zip(z).get("comprobantes_ventas")
    except Exception:
        return None


TOL = 1.0      # pesos de tolerancia por redondeo


def conciliar_ventas(cuit: str) -> dict:
    liva = {}
    for r in sorted(glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        per = os.path.basename(r)[:7]
        v = _liva_ventas(cuit, per, _leer_json(r))
        if v is not None:
            liva[per] = v
    if not liva:
        return {"sin_libro_iva": True}
    clave = lambda c: (int(c["tipo"]), int(c["punto_venta"]), int(c["numero"]))
    en_liva = {}
    for per, comps in liva.items():
        for c in comps:
            en_liva.setdefault(clave(c), (per, c))
    no_declaradas, otro_mes, dif_importe, solo_liva, resumen = [], [], [], [], []
    vistos_mc, meses_mc = set(), []
    for per in sorted(liva):
        mc = _mc_emitidos(cuit, per)
        if not mc:
            resumen.append({"Período": per, "Mis Comprobantes": "sin bajar"})
            continue
        vistos = set()
        for c in mc:
            # Mis Comprobantes puede agrupar un rango (Número Desde/Hasta, típico de tiques B)
            claves = [(c["tipo"], c["punto_venta"], n) for n in range(c["numero"], max(c["numero"], c["hasta"]) + 1)][:500]
            vistos.update(claves)
            hallados = [en_liva.get(k) for k in claves]
            fila = {"Período MC": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                    "Pto. venta": c["punto_venta"], "Número": c["numero"] if c["hasta"] == c["numero"] else f"{c['numero']}-{c['hasta']}",
                    "CUIT receptor": c["cuit"], "Receptor": c["nombre"], "Neto MC": c["neto"], "IVA MC": c["iva"], "Total MC": c["total"]}
            if not any(hallados):
                fila["Observación"] = "Emitido y NO declarado en el Libro IVA (débito fiscal sin declarar)"
                no_declaradas.append(fila)
                continue
            meses = sorted({h[0] for h in hallados if h})
            if meses != [per]:
                fila["Declarado en"] = ", ".join(meses)
                otro_mes.append(fila)
            if c["hasta"] == c["numero"]:
                h = hallados[0][1]
                if abs(abs(h["neto"]) - abs(c["neto"])) > TOL or abs(abs(h["iva"]) - abs(c["iva"])) > TOL:
                    dif_importe.append({**fila, "Neto Libro IVA": h["neto"], "IVA Libro IVA": h["iva"],
                                        "Dif. neto": round(abs(c["neto"]) - abs(h["neto"]), 2),
                                        "Dif. IVA": round(abs(c["iva"]) - abs(h["iva"]), 2)})
        vistos_mc.update(vistos)
        meses_mc.append(per)
        neto_mc, iva_mc = round(sum(c["neto"] for c in mc), 2), round(sum(c["iva"] for c in mc), 2)
        neto_li, iva_li = round(sum(c["neto"] for c in liva[per]), 2), round(sum(c["iva"] for c in liva[per]), 2)
        resumen.append({"Período": per, "Mis Comprobantes": "OK", "Neto MC": neto_mc, "Neto Libro IVA": neto_li,
                        "Dif. neto": round(neto_mc - neto_li, 2), "IVA MC": iva_mc, "IVA Libro IVA": iva_li,
                        "Dif. IVA": round(iva_mc - iva_li, 2),
                        "No declarados": sum(1 for f in no_declaradas if f["Período MC"] == per)})
    for per in meses_mc:
        for c in liva[per]:
            if clave(c) not in vistos_mc:
                solo_liva.append({"Período": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                                  "Pto. venta": c["punto_venta"], "Número": c["numero"], "CUIT receptor": c["cuit"],
                                  "Receptor": c["nombre"], "Neto gravado": c["neto"], "IVA": c["iva"], "Total": c["total"]})
    alertas = []
    if no_declaradas:
        alertas.append({"prioridad": "ALTA", "tipo": "Ventas no declaradas",
                        "texto": f"{len(no_declaradas)} comprobante(s) emitido(s) en Mis Comprobantes que no están en el "
                                 f"Libro IVA (total {sum(f['Total MC'] for f in no_declaradas):,.2f})."})
    if dif_importe:
        alertas.append({"prioridad": "Media", "tipo": "Ventas con importe distinto",
                        "texto": f"{len(dif_importe)} comprobante(s) de venta con neto o IVA distinto entre Mis "
                                 "Comprobantes y el Libro IVA."})
    for f in resumen:
        if f.get("Mis Comprobantes") == "OK" and (abs(f["Dif. neto"]) > TOL or abs(f["Dif. IVA"]) > TOL):
            alertas.append({"prioridad": "Media", "tipo": "Ventas: totales del mes",
                            "texto": f"{f['Período']}: Mis Comprobantes vs Libro IVA — neto {f['Dif. neto']:,.2f}, "
                                     f"IVA {f['Dif. IVA']:,.2f}."})
    return {"no_declaradas": no_declaradas, "otro_mes": otro_mes, "dif_importe": dif_importe,
            "solo_libro_iva": solo_liva, "resumen": resumen, "alertas": alertas}


def conciliar(cuit: str) -> dict:
    liva = {}
    for r in sorted(glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        d = _leer_json(r)
        liva[os.path.basename(r)[:7]] = d.get("comprobantes_compras") or []
    if not liva:
        return {"sin_libro_iva": True}
    hasta = max(liva)
    apoc = base_apoc()
    ruta_obs = os.path.join(DATOS, cuit, "observados", "observados.json")
    obs_d = _leer_json(ruta_obs) if os.path.exists(ruta_obs) else None
    observados = (obs_d or {}).get("comprobantes") or []
    obs_claves = {_clave(o["cuit"], o["tipo"], o["punto_venta"], o["numero"]) for o in observados}
    obs_cuits = {o["cuit"].lstrip("0") for o in observados}
    if obs_d is not None:
        apoc = (apoc or set()) | obs_cuits

    def marca_apoc(c, k):
        if k in obs_claves:
            return "SÍ - OBSERVADO POR ARCA"
        if apoc is not None and c["cuit"].lstrip("0") in apoc:
            return "SÍ - EMISOR OBSERVADO/APÓCRIFO"
        return "no" if apoc is not None else "sin verificar"
    # índice del Libro IVA: clave completa y clave sin tipo (por si el tipo se cargó distinto)
    tomado, tomado_sin_tipo = {}, {}
    for per, comps in liva.items():
        for c in comps:
            k = _clave(c["cuit"], c["tipo"], c["punto_venta"], c["numero"])
            tomado.setdefault(k, per)
            tomado_sin_tipo.setdefault(k[:1] + k[2:], per)
    no_tomadas, otro_mes, vistos_mc = [], [], set()
    bc_fuera, bc_fuera_det = {}, []
    resumen = []
    for per in sorted(liva):
        mc = _mc_recibidos(cuit, per)
        if not mc:
            resumen.append({"Período": per, "Mis Comprobantes": "sin bajar", "Comprobantes MC (no B)": None,
                            "No tomados": None, "Importe no tomado": None, "En otro mes": None})
            continue
        n_nt = imp_nt = n_om = n = 0
        for c in mc:
            k = _clave(c["cuit"], c["tipo"], c["punto_venta"], c["numero"])
            vistos_mc.add(k)
            vistos_mc.add(k[:1] + k[2:])
            if c["tipo"] in TIPOS_B_C:
                # B: no se toman jamás (ni crédito ni gasto). C: si no está en el Libro IVA, se suma como gasto.
                if c["tipo"] in TIPOS_C and not (tomado.get(k) or tomado_sin_tipo.get(k[:1] + k[2:])):
                    bc_fuera[per] = round(bc_fuera.get(per, 0.0) + c["total"], 2)
                    bc_fuera_det.append({"Período MC": per, "Fecha": c["fecha"],
                                         "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                                         "Pto. venta": c["punto_venta"], "Número": c["numero"], "CUIT emisor": c["cuit"],
                                         "Emisor": c["nombre"], "Total": c["total"]})
                continue
            n += 1
            donde = tomado.get(k) or tomado_sin_tipo.get(k[:1] + k[2:])
            fila = {"Período MC": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                    "Pto. venta": c["punto_venta"], "Número": c["numero"], "CUIT emisor": c["cuit"],
                    "Emisor": c["nombre"], "Neto gravado": c["neto"], "IVA": c["iva"], "Total": c["total"],
                    "APOC": marca_apoc(c, k),
                    "Nota de crédito": "Sí" if c["tipo"] in NOTAS_CREDITO else ""}
            if not donde:
                fila["Libro IVA revisado hasta"] = hasta
                fila["Observación"] = ("Nota de crédito NO computada (debería restar crédito)" if c["tipo"] in NOTAS_CREDITO
                                       else "No tomada: ¿omisión o no correspondía?")
                if per == hasta:
                    fila["Observación"] += " — puede tomarse en la DJ del mes siguiente"
                no_tomadas.append(fila)
                n_nt += 1
                imp_nt += c["total"]
            elif donde != per:
                fila["Tomada en"] = donde
                otro_mes.append(fila)
                n_om += 1
        resumen.append({"Período": per, "Mis Comprobantes": "OK", "Comprobantes MC (no B)": n,
                        "No tomados": n_nt, "Importe no tomado": round(imp_nt, 2), "En otro mes": n_om})
    solo_liva = []
    for per, comps in liva.items():
        if not _mc_recibidos(cuit, per):
            continue
        for c in comps:
            k = _clave(c["cuit"], c["tipo"], c["punto_venta"], c["numero"])
            if k in vistos_mc or (k[:1] + k[2:]) in vistos_mc:
                continue
            solo_liva.append({"Período": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                              "Pto. venta": c["punto_venta"], "Número": c["numero"], "CUIT emisor": c["cuit"],
                              "Emisor": c["nombre"], "Neto gravado": c["neto"], "IVA": c["iva"], "Total": c["total"]})
    # Error de carga (caso real de Gaby, 17/11/2026: tique 8-27327 cargado en el Libro como 8-27227, misma fecha e
    # importe): una "no tomada" que tiene en el Libro IVA un comprobante del mismo emisor, misma fecha y mismo IVA y
    # total pero con otro número, se considera TOMADA CON OTRO NÚMERO (no es omisión: el crédito está computado).
    otro_numero = []
    for f in list(no_tomadas):
        par = next((s for s in solo_liva if s["CUIT emisor"].lstrip("0") == f["CUIT emisor"].lstrip("0")
                    and str(s["Fecha"])[:10] == str(f["Fecha"])[:10] and abs(s["IVA"] - f["IVA"]) <= 1
                    and abs(s["Total"] - f["Total"]) <= 1), None)
        if par:
            no_tomadas.remove(f)
            solo_liva.remove(par)
            f = dict(f, **{"Tomada en": par["Período"],
                           "Cargada como": f"{par['Comprobante']} {par['Pto. venta']}-{par['Número']}",
                           "Observación": "Tomada con otro número/tipo: posible error de carga en el Libro IVA"})
            otro_numero.append(f)
    # El mismo comprobante (emisor + punto de venta + número) cargado dos veces en el Libro IVA, aunque sea con
    # distinto tipo (ej.: como "Tique Factura A" y como "Factura A"): el crédito fiscal queda computado dos veces.
    grupos = {}
    for per, comps in liva.items():
        for c in comps:
            grupos.setdefault((str(c["cuit"]).lstrip("0"), int(c["punto_venta"]), int(c["numero"])), []).append((per, c))
    duplicados = []
    for (_, pv, num), v in grupos.items():
        if len(v) < 2 or num == 0:
            continue
        for per, c in v:
            duplicados.append({"Período": per, "Fecha": c["fecha"], "Comprobante": NOMBRES.get(c["tipo"], f"Tipo {c['tipo']}"),
                               "Pto. venta": pv, "Número": num, "CUIT emisor": c["cuit"], "Emisor": c["nombre"],
                               "Neto gravado": c["neto"], "IVA": c["iva"], "Total": c["total"],
                               "Veces en el Libro": len(v),
                               "Meses": ", ".join(sorted({p for p, _ in v}))})
    iva_duplicado = round(sum(sum(c["iva"] for _, c in v[1:]) for v in grupos.values() if len(v) > 1), 2)
    # Resumen: notas de crédito aparte (restan crédito) para no mezclarlas con las facturas no tomadas.
    for fila_res in resumen:
        p = fila_res["Período"]
        nc = [f for f in no_tomadas if f["Período MC"] == p and f["Nota de crédito"]]
        fa = [f for f in no_tomadas if f["Período MC"] == p and not f["Nota de crédito"]]
        if fila_res.get("Mis Comprobantes") == "OK":
            fila_res.update({"No tomados": len(fa), "Importe no tomado": round(sum(f["Total"] for f in fa), 2),
                             "IVA no tomado": round(sum(f["IVA"] for f in fa), 2),
                             "NC no computadas": len(nc), "IVA de NC a restar": round(sum(f["IVA"] for f in nc), 2),
                             "Con otro número": sum(1 for f in otro_numero if f["Período MC"] == p),
                             "Duplicados en Libro": sum(1 for d in duplicados if d["Período"] == p)})
    # Observados por ARCA cruzados con el Libro IVA
    desde = min(liva)
    obs_filas = []
    for o in observados:
        k = _clave(o["cuit"], o["tipo"], o["punto_venta"], o["numero"])
        donde = tomado.get(k) or tomado_sin_tipo.get(k[:1] + k[2:])
        f_txt = str(o.get("fecha") or "")
        per_cbte = f_txt[:7] if re.match(r"\d{4}-\d{2}", f_txt) else ""
        if donde:
            comp = f"COMPUTADO en Libro IVA {donde}"
        elif per_cbte and per_cbte < desde:
            comp = f"anterior a {desde}: no revisado"
        else:
            comp = "no computado"
        anul = o.get("anulada_con") or ""
        if not donde:
            riesgo = "Bajo (no computado)" if not comp.startswith("anterior") else "Revisar a mano"
        elif anul:
            par = next((x for x in observados if x is not o and x.get("anulada_con") and x["cuit"] == o["cuit"]
                        and abs(x["total"] - o["total"]) < 0.01 and x["nc"] != o["nc"]), None)
            k2 = _clave(par["cuit"], par["tipo"], par["punto_venta"], par["numero"]) if par else None
            par_comp = bool(par and (tomado.get(k2) or tomado_sin_tipo.get(k2[:1] + k2[2:])))
            riesgo = ("Neutro (factura y NC computadas)" if par_comp
                      else "ALTO: computado sin su anulación" if not o["nc"] else "Revisar: NC computada sin la factura")
        else:
            riesgo = "ALTO: crédito fiscal observado — evaluar rectificar"
        obs_filas.append({"Fecha": o.get("fecha"), "Comprobante": o.get("tipo_txt"), "Pto. venta": o["punto_venta"],
                          "Número": o["numero"], "CUIT emisor": o["cuit"], "Emisor": o["nombre"],
                          "IVA": o["iva"] * (-1 if o["nc"] else 1), "Total": o["total"] * (-1 if o["nc"] else 1),
                          "Anulación": anul, "En Libro IVA": comp, "Riesgo": riesgo})
    apoc_alertas = [f for f in no_tomadas + otro_mes if f["APOC"].startswith("SÍ")] + \
                   [f for f in obs_filas if f["Riesgo"].startswith("ALTO")]
    return {"no_tomadas": no_tomadas, "otro_mes": otro_mes, "solo_libro_iva": solo_liva, "resumen": resumen,
            "otro_numero": otro_numero, "duplicados_libro": duplicados, "iva_duplicado": iva_duplicado,
            "apoc": ("sin verificar (falta correr el robot de observados)" if obs_d is None
                     else f"{len(observados)} comprobantes observados por ARCA (consulta del {obs_d.get('fecha')})"),
            "alertas_apoc": apoc_alertas, "observados": obs_filas,
            "hasta": hasta, "bc_fuera_libro": bc_fuera, "bc_fuera_libro_detalle": bc_fuera_det}


def ajustes_por_mes(r: dict) -> dict:
    """Lo que la conciliación cambia en los saldos (pedido de Gaby, 17/11/2026: "el informe principal sale del
    Portal IVA, pero tomado 2 veces o no tomado cambia los saldos"). Por mes, en importes con signo:
      duplicados: copia de más en el Libro IVA (mes del Libro)          -> resta compras y crédito
      nc:         nota de crédito de Mis Comprobantes no computada        -> resta (importes ya negativos)
      no_tomadas: factura A de Mis Comprobantes que no está en el Libro   -> sumaría, si correspondía tomarla
    "neto" = total − IVA (lo que entra en compras netas)."""
    out = {}

    def sumar(per, clave, neto, iva):
        d = out.setdefault(per, {})
        d[f"{clave}_neto"] = round(d.get(f"{clave}_neto", 0.0) + neto, 2)
        d[f"{clave}_iva"] = round(d.get(f"{clave}_iva", 0.0) + iva, 2)
    vistos = set()
    for d in r.get("duplicados_libro") or []:
        k = (str(d["CUIT emisor"]).lstrip("0"), d["Pto. venta"], d["Número"])
        if k in vistos:                     # la primera copia es la buena; las siguientes son de más
            sumar(d["Período"], "duplicados", -(d["Total"] - d["IVA"]), -d["IVA"])
        vistos.add(k)
    for f in r.get("no_tomadas") or []:
        sumar(f["Período MC"], "nc" if f.get("Nota de crédito") else "no_tomadas", f["Total"] - f["IVA"], f["IVA"])
    return out


# ---------------------------------------------------------------- dos fuentes para la relación D/C (20/11/2026)
def _mc_totales(cuit: str, per: str) -> dict | None:
    """Ventas y compras SIN IVA del mes según Mis Comprobantes, con la MISMA fórmula que el Libro IVA:
    ventas = neto gravado + no gravado + exento (+ el total de los comprobantes sin desglose, p. ej. facturas C);
    compras = lo mismo sin las facturas B (no se toman) y con el total de las C. None = el mes no está bajado."""
    emi, rec = os.path.join(DATOS, cuit, per, "emitidos.csv"), os.path.join(DATOS, cuit, per, "recibidos.csv")
    if not os.path.exists(emi) or not os.path.exists(rec):
        return None
    from .lector_mis_comprobantes import leer

    def suma(ruta, compras):
        df = leer(ruta)
        t = 0.0
        for _, x in df.iterrows():
            tipo = int(x["Tipo"])
            if compras and tipo in TIPOS_B:
                continue
            neto = float(x["Imp. Neto Gravado Total"] or 0)
            ng = float(x.get("Imp. Neto No Gravado") or 0)
            ex = float(x.get("Imp. Op. Exentas") or 0)
            iva = float(x["Total IVA"] or 0)
            t += neto + ng + ex if (neto or ng or ex or iva) else float(x["Imp. Total"] or 0)
        return round(t, 2)
    return {"ventas": suma(emi, False), "compras": suma(rec, True)}


def _liva_totales(d: dict) -> dict:
    v, c = d.get("ventas") or {}, d.get("compras") or {}
    n = lambda r, k: float(r.get(k) or 0)
    ventas = n(v, "Neto gravado total") + n(v, "Exento") + n(v, "No gravado")
    if "Otras ventas sin IVA (sin desglose)" in v:
        ventas += n(v, "Otras ventas sin IVA (sin desglose)")
    else:
        comps = d.get("comprobantes_ventas") or []
        sin = sum(float(x.get("total") or 0) for x in comps if not x.get("neto") and not x.get("iva"))
        ventas += max(0.0, sin - n(v, "Exento") - n(v, "No gravado"))
    compras = (n(c, "Neto gravado total") + n(c, "Exento") + n(c, "No gravado")
               + n(c, "Comprobantes B/C (sin IVA discriminado)"))
    return {"ventas": round(ventas, 2), "compras": round(compras, 2)}


# Tiques de controlador fiscal (ticketeadoras): NO suben a Mis Comprobantes (Gaby 20/11/2026, caso Goncalves).
TIQUES = {81, 82, 83, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120}
# Cuentas de venta y líquido producto / liquidaciones (las emite el consignatario o acopiador por cuenta del cliente):
# tampoco figuran como emitidos del cliente en Mis Comprobantes (Gaby 20/11/2026).
LIQUIDO_PRODUCTO = {33, 58, 59, 60, 61, 63, 64, 331, 332}
NO_VAN_A_MC = TIQUES | LIQUIDO_PRODUCTO
# COMPRAS (Gaby 20/11/2026): en el Portal IVA están y en Mis Comprobantes no: despachos de importación, liquidaciones
# simplificadas (LPART / LMAN), líquido producto, etc. Criterio: todo comprobante de compra que NO sea un tipo
# electrónico común (facturas, notas de débito y crédito, recibos A/B/C/M y FCE MiPyME) no se busca en Mis Comprobantes.
ELECTRONICOS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 51, 52, 53, 54, 201, 202, 203, 206, 207, 208, 211, 212, 213}


def compras_fuera_mc(d: dict) -> tuple[float, dict]:
    """Compras del Libro IVA que no figuran en Mis Comprobantes: (importe sin IVA, {tipo: importe})."""
    tot, por = 0.0, {}
    for c in d.get("comprobantes_compras") or []:
        tipo = int(c.get("tipo") or 0)
        if tipo in ELECTRONICOS:
            continue
        v = float(c.get("total") or 0) - float(c.get("iva") or 0)
        tot += v
        k = NOMBRES.get(tipo, f"Tipo {tipo}")
        por[k] = round(por.get(k, 0.0) + v, 2)
    return round(tot, 2), por


def _neto_comp(c: dict) -> float:
    if "no_gravado" in c or "exento" in c:
        return float(c.get("neto") or 0) + float(c.get("no_gravado") or 0) + float(c.get("exento") or 0)
    return float(c.get("total") or 0) - float(c.get("iva") or 0)


def _pv_mc(cuit: str) -> set:
    """Puntos de venta que figuran en Mis Comprobantes (emitidos) en cualquier mes bajado."""
    pvs = set()
    for d in glob.glob(os.path.join(DATOS, cuit, "[0-9][0-9][0-9][0-9]-[0-9][0-9]")):
        try:
            pvs |= {c["punto_venta"] for c in _mc_emitidos(cuit, os.path.basename(d))}
        except Exception:
            continue
    return pvs


def tiques_del_mes(d: dict, pv_mc: set) -> tuple[float, list]:
    """Ventas del Libro IVA que no pueden estar en Mis Comprobantes: tiques de controlador fiscal (por tipo) o de un
    punto de venta que nunca aparece en Mis Comprobantes (ticketeadora). Devuelve (importe sin IVA, puntos de venta)."""
    tot, pvs = 0.0, set()
    for c in d.get("comprobantes_ventas") or []:
        tipo, pv = int(c.get("tipo") or 0), int(c.get("punto_venta") or 0)
        if tipo in NO_VAN_A_MC or (pv_mc and pv not in pv_mc):
            tot += _neto_comp(c)
            pvs.add(pv)
    return round(tot, 2), sorted(pvs)


def comparar_fuentes(cuit: str, ventas: dict | None = None, compras: dict | None = None) -> dict:
    """Mes a mes y por concepto (ventas, compras): Libro IVA (Portal IVA) contra Mis Comprobantes. Diferencia
    relevante = más del 2 % o de $25.000 en el mes (lo que sea mayor). Mes sin alguna de las dos fuentes completa =
    'no comparable'. Guarda DATOS/<cuit>/conciliacion/fuentes.json para la web."""
    meses, tiques, fuera_c = {}, {}, {}
    pv_mc = _pv_mc(cuit)
    for r in sorted(glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json"))):
        d_ = _leer_json(r)
        meses[os.path.basename(r)[:7]] = _liva_totales(d_)
        tiques[os.path.basename(r)[:7]] = tiques_del_mes(d_, pv_mc)
        fuera_c[os.path.basename(r)[:7]] = compras_fuera_mc(d_)
    for d in sorted(glob.glob(os.path.join(DATOS, cuit, "[0-9][0-9][0-9][0-9]-[0-9][0-9]"))):
        meses.setdefault(os.path.basename(d), None)
    filas = []
    for per in sorted(meses)[-12:]:
        li = meses[per]
        try:
            mc = _mc_totales(cuit, per)
        except Exception:
            mc = None
        tq, tq_pv = tiques.get(per, (0.0, []))
        fc, fc_det = fuera_c.get(per, (0.0, {}))
        f = {"periodo": per, "libro_iva": li, "mis_comprobantes": mc, "tiques": tq, "tiques_pv": tq_pv,
             "compras_fuera_mc": fc, "compras_fuera_mc_detalle": fc_det}
        if li is None or mc is None:
            f["estado"] = "no comparable: falta " + ("el Libro IVA" if li is None else "Mis Comprobantes")
        else:
            f["estado"] = "OK"
            for k in ("ventas", "compras"):
                base_li = li[k] - (tq if k == "ventas" else fc)        # tiques / despachos, LPART, etc. no están en MC
                dif = round(mc[k] - base_li, 2)
                umbral = max(0.02 * max(abs(base_li), abs(mc[k])), 25_000.0)
                f[f"dif_{k}"] = dif
                if abs(dif) > umbral:
                    f["estado"] = "DIFERENCIA"
        filas.append(f)
    det = {}
    for nombre, lista, campo in (("ventas emitidas que no están en el Libro IVA", (ventas or {}).get("no_declaradas"), "Período MC"),
                                 ("ventas del Libro IVA que no están en Mis Comprobantes", (ventas or {}).get("solo_libro_iva"), "Período"),
                                 ("compras de Mis Comprobantes que no están en el Libro IVA", (compras or {}).get("no_tomadas"), "Período MC"),
                                 ("compras del Libro IVA que no están en Mis Comprobantes", (compras or {}).get("solo_libro_iva"), "Período")):
        for x in lista or []:
            if "Libro IVA que no están" in nombre and nombre.startswith("ventas") and (
                    re.search(r"tique|l[ií]quido producto|liquidaci", str(x.get("Comprobante") or ""), re.I)
                    or (pv_mc and int(x.get("Pto. venta") or 0) not in pv_mc)):
                continue                                   # tiques de controlador fiscal: no van a Mis Comprobantes
            if nombre.startswith("compras del Libro IVA") and not re.search(r"factura|nota de|recibo", str(x.get("Comprobante") or ""), re.I):
                continue                                   # despachos de importación, LPART/LMAN...: no van a Mis Comprobantes
            per = str(x.get(campo) or x.get("Período") or "")[:7]
            det.setdefault(per, []).append({"que": nombre, **{k: (str(v) if not isinstance(v, (int, float)) else v)
                                                              for k, v in x.items()}})
    for f in filas:
        f["solo_en_una"] = det.get(f["periodo"], [])[:60]
    res = {"cuit": cuit, "fecha": date.today().isoformat(), "meses": filas,
           "alertas": [{"prioridad": "ALTA", "tipo": "Relación D/C: las dos fuentes no coinciden",
                        "texto": "; ".join(f"{f['periodo']}: ventas {f.get('dif_ventas', 0):,.2f}, compras {f.get('dif_compras', 0):,.2f}"
                                           for f in filas if f["estado"] == "DIFERENCIA")
                                 + " (Mis Comprobantes − Libro IVA, más del 2 % o $25.000)"}]
           if any(f["estado"] == "DIFERENCIA" for f in filas) else []}
    os.makedirs(os.path.join(DATOS, cuit, "conciliacion"), exist_ok=True)
    with open(os.path.join(DATOS, cuit, "conciliacion", "fuentes.json"), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)
    return res


def generar(cuit: str, nombre: str, ruta: str) -> dict | None:
    try:                                   # comparación de las dos fuentes de la relación D/C (20/11/2026)
        comparar_fuentes(cuit, conciliar_ventas(cuit), conciliar(cuit))
    except Exception:
        pass
    r = conciliar(cuit)
    if r.get("sin_libro_iva"):
        return None
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    AZUL, ROJO, ROJO_FUERTE, AMARILLO = "1F4E78", "FFC7CE", "FF7C80", "FFEB9C"
    NUM = '#,##0.00;[Red]\\-#,##0.00;"-"'
    wb = Workbook()
    wb.remove(wb.active)

    def hoja(titulo, sub, filas, columnas, color=None):
        ws = wb.create_sheet(titulo[:31])
        ws["A1"] = f"{titulo} — {nombre} — CUIT {cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
        ws["A1"].font = Font(bold=True, size=13)
        ws["A2"] = sub
        ws["A2"].font = Font(italic=True, color="595959")
        for j, c in enumerate(columnas, 1):
            cel = ws.cell(4, j, c)
            cel.font = Font(bold=True, color="FFFFFF")
            cel.fill = PatternFill("solid", fgColor=AZUL)
            cel.alignment = Alignment(wrap_text=True, horizontal="center")
        for i, f in enumerate(filas, 5):
            col = color(f) if color else None
            for j, c in enumerate(columnas, 1):
                v = f.get(c)
                cel = ws.cell(i, j, v)
                if isinstance(v, float):
                    cel.number_format = NUM
                elif isinstance(v, date):
                    cel.number_format = "DD/MM/YYYY"
                if col:
                    cel.fill = PatternFill("solid", fgColor=col)
        if not filas:
            ws.cell(5, 1, "Sin casos").font = Font(italic=True, color="595959")
        for j, c in enumerate(columnas, 1):
            largo = max([len(str(c))] + [len(str(f.get(c, ""))) for f in filas[:300]])
            ws.column_dimensions[get_column_letter(j)].width = min(48, max(10, largo + 2))
        ws.freeze_panes = "A5"
        if filas:
            ws.auto_filter.ref = f"A4:{get_column_letter(len(columnas))}{4 + len(filas)}"
        return ws

    cols = ["Período MC", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "Neto gravado",
            "IVA", "Total", "APOC", "Observación", "Libro IVA revisado hasta"]
    rojo = lambda f: ROJO_FUERTE if f["APOC"].startswith("SÍ") else ROJO
    hoja("No tomadas en Libro IVA",
         f"Compras de Mis Comprobantes (sin facturas B) que no figuran en el Libro IVA de ese mes ni de los siguientes "
         f"(revisado hasta {r['hasta']}). Base APOC: {r['apoc']}.", r["no_tomadas"], cols, rojo)
    hoja("Tomadas en otro mes", "Comprobantes de Mis Comprobantes computados en un Libro IVA de un mes distinto.",
         r["otro_mes"], cols[:11] + ["Tomada en"], lambda f: ROJO_FUERTE if f["APOC"].startswith("SÍ") else AMARILLO)
    hoja("Tomadas con otro número", "Comprobantes de Mis Comprobantes que en el Libro IVA figuran con otro número o "
         "tipo (mismo emisor, fecha, IVA y total): el crédito está computado, pero conviene corregir la carga.",
         r["otro_numero"], cols[:11] + ["Tomada en", "Cargada como"], lambda f: AMARILLO)
    hoja("Duplicados en Libro IVA", "El mismo comprobante (emisor, punto de venta y número) cargado más de una vez en "
         f"el Libro IVA: el crédito fiscal se computó dos veces. IVA computado de más: {r['iva_duplicado']:,.2f}.",
         r["duplicados_libro"], ["Período", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor",
                                 "Neto gravado", "IVA", "Total", "Veces en el Libro", "Meses"], lambda f: ROJO_FUERTE)
    hoja("Solo en Libro IVA", "Informativo: comprobantes del Libro IVA que no están en Mis Comprobantes "
         "(despachos de importación, servicios públicos, etc.).", r["solo_libro_iva"],
         ["Período", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "Neto gravado", "IVA", "Total"])
    hoja("Observados por ARCA (APOC)",
         "Comprobantes electrónicos observados (Nuestra Parte): proveedores sin capacidad técnico-económica según ARCA. "
         f"No deben computarse como crédito ni deducción. {r['apoc']}.", r["observados"],
         ["Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "IVA", "Total", "Anulación",
          "En Libro IVA", "Riesgo"],
         lambda f: ROJO_FUERTE if f["Riesgo"].startswith("ALTO") else AMARILLO if f["Riesgo"].startswith(("Revisar", "Neutro")) else None)
    os.makedirs(os.path.join(DATOS, cuit, "conciliacion"), exist_ok=True)
    with open(os.path.join(DATOS, cuit, "conciliacion", "compras_bc_fuera_libro.json"), "w", encoding="utf-8") as f:
        json.dump({"fecha": date.today().isoformat(), "por_mes": r["bc_fuera_libro"]}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATOS, cuit, "conciliacion", "ajustes_conciliacion.json"), "w", encoding="utf-8") as f:
        json.dump({"fecha": date.today().isoformat(), "por_mes": ajustes_por_mes(r)}, f, ensure_ascii=False, indent=1)
    hoja("Facturas C fuera del Libro", "Facturas C de compra (sin crédito fiscal) que están en Mis Comprobantes y no "
         "en el Libro IVA: se suman como gasto en la relación débito/crédito. Las facturas B no se toman nunca.", r["bc_fuera_libro_detalle"],
         ["Período MC", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT emisor", "Emisor", "Total"])
    # Impacto en los saldos (Gaby, 17-18/11/2026): va en ESTA planilla, no en la relación débito/crédito
    aj = ajustes_por_mes(r)
    impacto = []
    for per in sorted(aj):
        d = aj[per]
        lj = _leer_json(os.path.join(DATOS, cuit, "libro_iva", f"{per}.json")) if os.path.exists(
            os.path.join(DATOS, cuit, "libro_iva", f"{per}.json")) else {}
        deb = float(((lj.get("ventas") or {}).get("Total IVA")) or 0)
        cred = float(((lj.get("compras") or {}).get("Total IVA")) or 0)
        g = lambda k: round(d.get(k) or 0.0, 2)
        aj_iva = round(g("duplicados_iva") + g("nc_iva") + g("no_tomadas_iva"), 2)
        impacto.append({"Período": per, "Duplicados en Libro (neto)": g("duplicados_neto"), "NC no computadas (neto)": g("nc_neto"),
                        "Facturas A no tomadas (neto)": g("no_tomadas_neto"),
                        "Compras netas a corregir": round(g("duplicados_neto") + g("nc_neto") + g("no_tomadas_neto"), 2),
                        "Duplicados (IVA)": g("duplicados_iva"), "NC no computadas (IVA)": g("nc_iva"),
                        "No tomadas (IVA)": g("no_tomadas_iva"), "Ajuste al crédito fiscal": aj_iva,
                        "Saldo técnico Libro IVA": round(deb - cred, 2) if lj else None,
                        "Saldo técnico corregido": round(deb - cred - aj_iva, 2) if lj else None})
    r["impacto"] = impacto
    wi = hoja("Impacto en saldos", "Cómo cambian las compras y el saldo técnico de IVA si se corrige la carga del Libro IVA "
              "(duplicados restan, notas de crédito no computadas restan, facturas A no tomadas suman si correspondía "
              "tomarlas). El informe principal (relación débito/crédito) sale del Portal IVA sin estos ajustes.", impacto,
              ["Período", "Duplicados en Libro (neto)", "NC no computadas (neto)", "Facturas A no tomadas (neto)",
               "Compras netas a corregir", "Duplicados (IVA)", "NC no computadas (IVA)", "No tomadas (IVA)",
               "Ajuste al crédito fiscal", "Saldo técnico Libro IVA", "Saldo técnico corregido"],
              lambda f: ROJO if f["Ajuste al crédito fiscal"] < 0 else None)
    v = conciliar_ventas(cuit)
    r["ventas"] = v
    if not v.get("sin_libro_iva"):
        colv = ["Período MC", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT receptor", "Receptor", "Neto MC",
                "IVA MC", "Total MC"]
        hoja("Ventas no declaradas", "Comprobantes EMITIDOS en Mis Comprobantes que no figuran en el Libro IVA: "
             "débito fiscal sin declarar (nunca debería haber).", v["no_declaradas"], colv + ["Observación"],
             lambda f: ROJO_FUERTE)
        hoja("Ventas en otro mes", "Emitidos en un mes y declarados en el Libro IVA de otro.", v["otro_mes"],
             colv + ["Declarado en"], lambda f: AMARILLO)
        hoja("Ventas con importe distinto", "Mismo comprobante con neto o IVA distinto entre Mis Comprobantes y el "
             "Libro IVA.", v["dif_importe"], colv + ["Neto Libro IVA", "IVA Libro IVA", "Dif. neto", "Dif. IVA"],
             lambda f: ROJO)
        hoja("Ventas solo en Libro IVA", "Informativo: ventas declaradas que no están en Mis Comprobantes "
             "(comprobantes manuales o de controlador fiscal).", v["solo_libro_iva"],
             ["Período", "Fecha", "Comprobante", "Pto. venta", "Número", "CUIT receptor", "Receptor", "Neto gravado",
              "IVA", "Total"])
        wv = hoja("Resumen ventas", "Totales del mes: Mis Comprobantes emitidos contra Libro IVA ventas.", v["resumen"],
                  ["Período", "Mis Comprobantes", "Neto MC", "Neto Libro IVA", "Dif. neto", "IVA MC", "IVA Libro IVA",
                   "Dif. IVA", "No declarados"],
                  lambda f: ROJO if (f.get("No declarados") or abs(f.get("Dif. neto") or 0) > TOL
                                     or abs(f.get("Dif. IVA") or 0) > TOL) else None)
        wb.move_sheet(wv, offset=-(len(wb.sheetnames) - 1))
    ws = hoja("Resumen", "Por período con Libro IVA bajado.", r["resumen"],
              ["Período", "Mis Comprobantes", "Comprobantes MC (no B)", "No tomados", "Importe no tomado", "IVA no tomado",
               "NC no computadas", "IVA de NC a restar", "En otro mes", "Con otro número", "Duplicados en Libro"],
              lambda f: ROJO_FUERTE if (f.get("NC no computadas") or f.get("Duplicados en Libro"))
              else ROJO if f.get("No tomados") else None)
    wb.move_sheet(ws, offset=-(len(wb.sheetnames) - 1))
    wb.move_sheet(wi, offset=-(wb.sheetnames.index(wi.title) - 1))      # segunda hoja, después del Resumen
    wb.active = 0
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    wb.save(ruta)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--cuit", required=True)
    a = ap.parse_args(argv)
    from .informe import nombre
    ruta = os.path.join(INFORMES, date.today().isoformat(), f"conciliacion_compras_{a.cuit}.xlsx")
    r = generar(a.cuit, nombre(a.cuit, {}) or a.cuit, ruta)
    from .informe import dejar_solo_el_ultimo
    dejar_solo_el_ultimo(INFORMES)
    if r is None:
        print("Sin Libro IVA bajado para este CUIT (monotributista o falta correr el robot libro_iva)")
        return
    v = r.get("ventas") or {}
    print(f"COMPRAS  no tomadas: {len(r['no_tomadas'])}   en otro mes: {len(r['otro_mes'])}   "
          f"solo en Libro IVA: {len(r['solo_libro_iva'])}   APOC: {len(r['alertas_apoc'])}")
    if not v.get("sin_libro_iva"):
        print(f"VENTAS   no declaradas: {len(v['no_declaradas'])}   en otro mes: {len(v['otro_mes'])}   "
              f"importe distinto: {len(v['dif_importe'])}   solo en Libro IVA: {len(v['solo_libro_iva'])}")
    print(ruta)


if __name__ == "__main__":
    main()
