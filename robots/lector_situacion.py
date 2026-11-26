"""Lectura de las tablas de Cuentas Tributarias y Mis Facilidades (sin navegador).

El robot extrae las tablas tal cual las muestra ARCA (encabezados + filas de texto) y
este módulo las convierte en datos y alertas. Separado del navegador para poder probarlo
con tablas de ejemplo.

Formato visto en ARCA el 15/11/2026:
  SCT  Deudas : Establecimiento | Impuesto | Concepto | Subconcepto | Período | Ant/Cuota |
                Vencimiento | Saldo | Int. Resarcitorio | Int. Punitorio   (filas vencidas: clase "vencida")
  SCT  Vencim.: Impuesto | Concepto | Subconcepto | Período | Ant/Cuota | Fecha Vencimiento | Detalle
  SCT  DDJJ   : Establecimiento | Impuesto | Concepto | Subconcepto | Período | Ant/Cuota | Vencimiento
  MF   Lista  : Presentación | Número | Cuotas | Tipo | Consolidado($) | Estado | Situación
  MF   Plan de Pago: Cuota N° | Capital | Int. Financiero | Int. Resarcitorio | Total | Fecha Vencimiento
                fila con número = 1° vencimiento; fila siguiente sin número = 2° vencimiento
  MF   Ver Pagos  : ... | Fecha Venc. | Pago | Estado de Cuota ("Cuota Cancelada" / "Cuota Impaga" / vacío)
                filas sin número con "Pago" = fecha y monto efectivamente pagados
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta

DIAS_A_VENCER = 15          # "cuotas a vencer en 15 días"
MESES_ALERTA_CADUCO = 12    # alertar planes caducos presentados en los últimos N meses
TOLERANCIA = 1.0            # pesos de diferencia aceptados en los controles de totales


# ---------------------------------------------------------------- utilidades
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode()
    t = re.sub(r"\(click to sort.*?\)", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip().lower()


def importe(t) -> float | None:
    """'$ 1.008.784,40' -> 1008784.4 ; '900521,36' -> 900521.36 ; '-' / '' -> None"""
    if t is None:
        return None
    t = str(t).replace("$", "").replace("\xa0", "").strip()
    if t in ("", "-"):
        return None
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("-() ").replace(".", "").replace(",", ".")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def pesos(v) -> str:
    """1234567.8 -> '$ 1.234.567,80' (formato argentino)"""
    if v is None:
        return "-"
    t = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}$ {t}"


def fecha(t) -> date | None:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(t or ""))
    return date(int(m[3]), int(m[2]), int(m[1])) if m else None


def periodo_legible(p: str) -> str:
    """'202610' -> '10/2026' ; '20250000' -> 'Anual 2025' ; otro -> igual"""
    p = (p or "").strip()
    if re.fullmatch(r"\d{8}", p) and p.endswith("0000"):
        return f"Anual {p[:4]}"
    if re.fullmatch(r"\d{8}", p):
        return f"{p[4:6]}/{p[:4]}" + ("" if p[6:] == "00" else f" ({p[6:]})")
    if re.fullmatch(r"\d{6}", p):
        return f"{p[4:]}/{p[:4]}"
    return p


def tabla_a_dicts(tabla: dict, esperadas: list[str]) -> list[dict]:
    """tabla = {"encabezados": [...], "filas": [{"celdas": [...], "clase": "..."}]}
    Devuelve una lista de dicts con las columnas pedidas (busca por título, no por posición).
    Si falta alguna columna esperada, error: ARCA cambió la pantalla y no hay que adivinar."""
    enc = [_norm(e) for e in tabla.get("encabezados", [])]
    idx = {}
    for col in esperadas:
        n = _norm(col)
        pos = [i for i, e in enumerate(enc) if e == n] or [i for i, e in enumerate(enc) if e.startswith(n)]
        if not pos:
            raise ValueError(f"Falta la columna '{col}'. Columnas vistas: {tabla.get('encabezados')}")
        idx[col] = pos[0]
    out = []
    for f in tabla.get("filas", []):
        c = f.get("celdas", [])
        if len(c) != len(enc):          # "No se encontraron resultados", subtotales, etc.
            continue
        d = {col: (c[i] or "").strip() for col, i in idx.items()}
        d["_clase"] = f.get("clase", "")
        out.append(d)
    return out


# ---------------------------------------------------------------- Cuentas Tributarias
def leer_sct(crudo: dict, hoy: date | None = None) -> dict:
    """crudo = {"contadores": {"deudas": 36, "ddjj": 0}, "resumen_texto": "...",
                "deudas": tabla, "vencimientos": tabla, "ddjj": tabla}"""
    hoy = hoy or date.today()
    alertas, controles = [], []

    deudas = []
    for d in tabla_a_dicts(crudo["deudas"], ["Establecimiento", "Impuesto", "Concepto", "Subconcepto", "Período",
                                             "Ant/Cuota", "Vencimiento", "Saldo", "Int. Resarcitorio",
                                             "Int. Punitorio"]):
        v = fecha(d["Vencimiento"])
        deudas.append({
            "impuesto": d["Impuesto"], "concepto": d["Concepto"], "subconcepto": d["Subconcepto"],
            "periodo": d["Período"], "periodo_txt": periodo_legible(d["Período"]), "cuota": d["Ant/Cuota"],
            "establecimiento": d["Establecimiento"], "vencimiento": v,
            "capital": importe(d["Saldo"]) or 0.0, "int_resarcitorio": importe(d["Int. Resarcitorio"]) or 0.0,
            "int_punitorio": importe(d["Int. Punitorio"]) or 0.0,
            "vencida": "vencida" in d["_clase"] or (v is not None and v < hoy),
        })
    for d in deudas:
        d["total"] = round(d["capital"] + d["int_resarcitorio"] + d["int_punitorio"], 2)

    venc = [{"impuesto": d["Impuesto"], "concepto": d["Concepto"], "periodo": d["Período"],
             "periodo_txt": periodo_legible(d["Período"]), "cuota": d["Ant/Cuota"],
             "vencimiento": fecha(d["Fecha Vencimiento"]), "detalle": d["Detalle"]}
            for d in tabla_a_dicts(crudo["vencimientos"], ["Impuesto", "Concepto", "Período", "Ant/Cuota",
                                                           "Fecha Vencimiento", "Detalle"])]

    # Gaby 26/11/2026: con el 103 (Regímenes de información) hay muchísimos subregímenes: concepto y subconcepto
    cols = ["Establecimiento", "Impuesto", "Concepto", "Período", "Vencimiento"]
    extra = [c for c in ("Subconcepto", "Ant/Cuota") if any(_norm(e).startswith(_norm(c)) for e in crudo["ddjj"].get("encabezados", []))]
    ddjj = [{"impuesto": d["Impuesto"], "concepto": d["Concepto"], "subconcepto": d.get("Subconcepto", ""),
             "cuota": d.get("Ant/Cuota", ""), "periodo": d["Período"],
             "periodo_txt": periodo_legible(d["Período"]), "establecimiento": d["Establecimiento"],
             "vencimiento": fecha(d["Vencimiento"])}
            for d in tabla_a_dicts(crudo["ddjj"], cols + extra)]

    # Resumen que muestra ARCA arriba de la tabla de deudas
    txt = crudo.get("resumen_texto", "")
    def _r(etq):
        m = re.search(etq + r"\s*:?\s*\$?\s*([\d\.]+,\d{2})", txt, re.I)
        return importe(m[1]) if m else None
    resumen_arca = {"saldo_total": _r(r"Saldo total a pagar"), "capital_vencido": _r(r"Capital vencido"),
                    "capital_no_vencido": _r(r"Capital no vencido"),
                    "int_resarcitorios": _r(r"Int\. Resarcitorios"), "int_punitorios": _r(r"Int\. Punitorios")}

    # Controles: lo leído tiene que coincidir con lo que ARCA dice que hay
    cont = crudo.get("contadores", {})
    for clave, lista, nombre in (("deudas", deudas, "Deudas"), ("ddjj", ddjj, "DDJJ pendientes")):
        if cont.get(clave) is not None and cont[clave] != len(lista):
            controles.append(f"{nombre}: ARCA indica {cont[clave]} y se leyeron {len(lista)}")
    suma_cap = round(sum(d["capital"] for d in deudas), 2)
    suma_res = round(sum(d["int_resarcitorio"] for d in deudas), 2)
    if resumen_arca["capital_vencido"] is not None:
        cap_arca = resumen_arca["capital_vencido"] + (resumen_arca["capital_no_vencido"] or 0)
        if abs(cap_arca - suma_cap) > TOLERANCIA:
            controles.append(f"Capital: ARCA {pesos(cap_arca)} vs suma de filas {pesos(suma_cap)}")
    if resumen_arca["int_resarcitorios"] is not None and abs(resumen_arca["int_resarcitorios"] - suma_res) > TOLERANCIA:
        controles.append(f"Int. resarcitorios: ARCA {pesos(resumen_arca['int_resarcitorios'])} vs filas {pesos(suma_res)}")

    # Alertas
    vencidas = [d for d in deudas if d["vencida"] and d["total"] > 0]
    if vencidas:
        alertas.append({"prioridad": "ALTA", "tipo": "Deuda vencida",
                        "texto": f"{len(vencidas)} obligaciones vencidas impagas por "
                                 f"{pesos(sum(d['total'] for d in vencidas))} (capital + intereses)"})
    if ddjj:
        alertas.append({"prioridad": "ALTA", "tipo": "Falta de presentación",
                        "texto": f"{len(ddjj)} DDJJ pendientes: " +
                                 "; ".join(f"{d['impuesto']} {d['periodo_txt']}" for d in ddjj[:10])})
    for v in venc:
        if v["vencimiento"] and hoy <= v["vencimiento"] <= hoy + timedelta(days=DIAS_A_VENCER):
            alertas.append({"prioridad": "Media", "tipo": "Vencimiento próximo",
                            "texto": f"{v['impuesto']} {v['periodo_txt']} vence {v['vencimiento']:%d/%m/%Y} "
                                     f"({v['detalle']})"})
    for c in controles:
        alertas.append({"prioridad": "ALTA", "tipo": "Control de lectura", "texto": c})

    return {"deudas": deudas, "vencimientos": venc, "ddjj_pendientes": ddjj, "resumen_arca": resumen_arca,
            "totales_leidos": {"capital": suma_cap, "int_resarcitorio": suma_res,
                               "total": round(sum(d["total"] for d in deudas), 2),
                               "vencido": round(sum(d["total"] for d in vencidas), 2)},
            "controles": controles, "alertas": alertas}


# ---------------------------------------------------------------- Mis Facilidades
def leer_lista_planes(tabla: dict) -> list[dict]:
    return [{"presentacion": fecha(d["Presentación"]), "numero": d["Número"], "cuotas": int(re.sub(r"\D", "", d["Cuotas"]) or 0),
             "tipo": d["Tipo"], "consolidado": importe(d["Consolidado"]), "estado": d["Estado"],
             "situacion": d["Situación"]}
            for d in tabla_a_dicts(tabla, ["Presentación", "Número", "Cuotas", "Tipo", "Consolidado",
                                           "Estado", "Situación"])]


def _filas_crudas(tabla: dict) -> list[list[str]]:
    return [[(c or "").strip() for c in f.get("celdas", [])] for f in tabla.get("filas", [])]


def leer_plan_de_pago(tabla: dict) -> list[dict]:
    """Cronograma completo: una entrada por cuota con 1° y 2° vencimiento."""
    cuotas = []
    for c in _filas_crudas(tabla):
        if len(c) < 6 or _norm(c[0]).startswith(("totales", "cuota")):
            continue
        if re.fullmatch(r"\d+", c[0]):
            cuotas.append({"cuota": int(c[0]), "capital": importe(c[1]), "int_financiero": importe(c[2]),
                           "total_1": importe(c[4]), "venc_1": fecha(c[5]), "total_2": None, "venc_2": None})
        elif c[0] == "" and cuotas and cuotas[-1]["venc_2"] is None:
            cuotas[-1]["total_2"], cuotas[-1]["venc_2"] = importe(c[4]), fecha(c[5])
    return cuotas


def leer_pagos(tabla: dict) -> dict[int, dict]:
    """Estado de cada cuota vencida (o próxima) y los pagos registrados."""
    out, actual = {}, None
    for c in _filas_crudas(tabla):
        if len(c) < 8 or _norm(c[0]).startswith(("total", "cuota")):
            continue
        if re.fullmatch(r"\d+", c[0]):
            actual = int(c[0])
            out[actual] = {"estado": c[7], "pagos": []}
        elif actual is not None and _norm(c[6]) == "pago":
            out[actual]["pagos"].append({"fecha": fecha(c[5]), "importe": importe(c[4])})
    return out


def clasificar_cuota(c: dict, hoy: date) -> str:
    est = _norm(c.get("estado", ""))
    if "cancelad" in est:
        return "Pagada"
    if "impaga" in est:
        return "Vencida impaga"
    if c["venc_1"] and c["venc_1"] >= hoy:
        return "A vencer"
    # Estado vacío y vencida: PENDIENTE DE PAGO (todavía se puede pagar hasta el 2° vencimiento, o el banco
    # no informó el débito). Regla del estudio: Cancelada = bien; vacía = pendiente; Impaga = falta pagar.
    # Regla del estudio: estado vacío = PENDIENTE de pago (nunca "impaga"). Impaga es SOLO lo que ARCA marca así.
    return "Pendiente de pago"


def resumir_plan(plan: dict, cronograma: list[dict], pagos: dict[int, dict], hoy: date | None = None) -> dict:
    hoy = hoy or date.today()
    cuotas = []
    for c in cronograma:
        p = pagos.get(c["cuota"], {})
        c = {**c, "estado": p.get("estado", ""), "pagos": p.get("pagos", [])}
        c["situacion"] = clasificar_cuota(c, hoy)
        cuotas.append(c)
    pendientes = [c for c in cuotas if c["situacion"] != "Pagada"]
    impagas = [c for c in cuotas if c["situacion"] == "Vencida impaga"]
    pend_pago = [c for c in cuotas if c["situacion"] == "Pendiente de pago"]
    proximas = [c for c in pendientes if c["venc_1"] and hoy <= c["venc_1"] <= hoy + timedelta(days=DIAS_A_VENCER)]
    siguiente = next((c for c in cuotas if c["situacion"] == "A vencer"), None)
    valor = (siguiente or (cuotas[-1] if cuotas else {})).get("total_1")
    controles = []
    # Planes con anticipo (p. ej. RG 5711): la lista cuenta anticipo + cuotas, el cronograma solo las cuotas.
    con_anticipo = bool(plan.get("cuotas")) and plan["cuotas"] == len(cronograma) + 1
    if plan.get("cuotas") and len(cronograma) != plan["cuotas"] and not con_anticipo:
        controles.append(f"Plan {plan['numero']}: la lista dice {plan['cuotas']} cuotas y el cronograma tiene {len(cronograma)}")
    return {**plan, "con_anticipo": con_anticipo,
            "estado_anticipo": pagos.get(0, {}).get("estado", "") if con_anticipo else "",
            "valor_cuota": valor, "cuotas_total": len(cuotas), "cuotas_pagadas": len(cuotas) - len(pendientes),
            "cuotas_pendientes": len(pendientes), "vencidas_impagas": len(impagas),
            "cuotas_impagas_arca": sum(1 for c in cuotas if c["situacion"] == "Vencida impaga"),
            "pendientes_de_pago": len(pend_pago),
            "importe_pendiente_de_pago": round(sum((c["total_2"] or c["total_1"] or 0) for c in pend_pago), 2),
            "importe_vencido_impago": round(sum((c["total_2"] or c["total_1"] or 0) for c in impagas), 2),
            "a_vencer_15_dias": len(proximas),
            "importe_a_vencer_15_dias": round(sum(c["total_1"] or 0 for c in proximas), 2),
            "proximo_vencimiento": siguiente["venc_1"] if siguiente else None,
            "saldo_capital_pendiente": round(sum(c["capital"] or 0 for c in pendientes), 2),
            "detalle_cuotas": cuotas, "controles": controles}


def alertas_planes(planes: list[dict], resumenes: list[dict], hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    al = []
    for r in resumenes:
        n_impagas = sum(1 for c in r["detalle_cuotas"] if c["situacion"] == "Vencida impaga")
        if n_impagas >= 2:
            al.append({"prioridad": "ALTA", "tipo": "Plan con 2 o más cuotas impagas",
                       "texto": f"CRÍTICO — Plan {r['numero']}: tiene {n_impagas} cuotas impagas. Un plan nunca puede "
                                "tener dos impagas: riesgo inmediato de CADUCIDAD."})
        for c in r["detalle_cuotas"]:
            if c["situacion"] == "Pendiente de pago":
                al.append({"prioridad": "Media", "tipo": "Cuota pendiente de pago",
                           "texto": (f"Plan {r['numero']}: cuota {c['cuota']} venció el {c['venc_1']:%d/%m/%Y} sin pago; "
                                     f"se puede pagar hasta el 2° venc. {c['venc_2']:%d/%m/%Y}"
                                     + (f" por {pesos(c['total_2'])}" if c.get("total_2") else "") + "."
                                     if c.get("venc_2") and c["venc_2"] >= hoy else
                                     f"Plan {r['numero']}: cuota {c['cuota']} (venc. {c['venc_1']:%d/%m/%Y}) pendiente de pago: "
                                     "ARCA todavía no la marca pagada ni impaga. Verificar el débito.")})
            elif c["situacion"] == "Vencida impaga":
                al.append({"prioridad": "ALTA", "tipo": "Cuota impaga",
                           "texto": f"Plan {r['numero']}: cuota {c['cuota']} (venc. {c['venc_1']:%d/%m/%Y}) IMPAGA. "
                                    "No puede caer otra impaga: riesgo de caducidad."})
            elif c["situacion"] == "Vencida sin pago informado":
                al.append({"prioridad": "Media", "tipo": "Cuota sin pago informado",
                           "texto": f"Plan {r['numero']}: cuota {c['cuota']} venció el {c['venc_1']:%d/%m/%Y} y ARCA "
                                    "todavía no informa el pago. Verificar débito."})
            elif c["situacion"] == "A vencer" and c["venc_1"] <= hoy + timedelta(days=DIAS_A_VENCER):
                al.append({"prioridad": "Media", "tipo": "Cuota a vencer",
                           "texto": f"Plan {r['numero']}: cuota {c['cuota']} de {pesos(c['total_1'])} vence el "
                                    f"{c['venc_1']:%d/%m/%Y} (2° venc. {c['venc_2']:%d/%m/%Y})" if c["venc_2"] else
                                    f"Plan {r['numero']}: cuota {c['cuota']} de {pesos(c['total_1'])} vence el "
                                    f"{c['venc_1']:%d/%m/%Y}"})
        for t in r["controles"]:
            al.append({"prioridad": "ALTA", "tipo": "Control de lectura", "texto": t})
    limite = hoy - timedelta(days=30 * MESES_ALERTA_CADUCO)
    for p in planes:
        if "caduc" in _norm(p["situacion"]) and p["presentacion"] and p["presentacion"] >= limite:
            al.append({"prioridad": "ALTA", "tipo": "Plan caduco",
                       "texto": f"Plan {p['numero']} ({p['tipo']}, presentado {p['presentacion']:%d/%m/%Y}) está CADUCO"})
    return al


def es_vigente(plan: dict) -> bool:
    return _norm(plan["situacion"]) == "vigente"
