"""Lectura (solo lectura) de lo que dejan los robots. No accede al almacén de claves."""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import date, timedelta

RAIZ = os.environ.get("ROBOTS_RAIZ", "/var/lib/robots")
DATOS = os.path.join(RAIZ, "datos")
INFORMES = os.path.join(RAIZ, "informes")
PUBLICO = os.path.join(RAIZ, "publico")
REGISTRO = os.path.join(RAIZ, "ejecuciones.jsonl")
CUIT_RE = re.compile(r"^\d{11}$")


def _leer(ruta):
    if not ruta:
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _ultimo(patron):
    r = sorted(glob.glob(patron))
    return r[-1] if r else None


def _fecha(v):
    if isinstance(v, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            return date.fromisoformat(v)
        m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", v)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1]))
    return None


def cuit_fmt(c):
    return f"{c[:2]}-{c[2:10]}-{c[10]}" if c and len(c) == 11 else c


def lista_clientes(solo: set | None = None) -> list[dict]:
    """Todos los clientes; con `solo` (CUITs que puede ver un colaborador), únicamente esos."""
    pub = _lista_clientes()
    return pub if solo is None else [c for c in pub if c["cuit"] in solo]


def _lista_clientes() -> list[dict]:
    pub = _leer(os.path.join(PUBLICO, "clientes.json")) or []
    vistos = {c["cuit"] for c in pub}
    for d in sorted(glob.glob(os.path.join(DATOS, "*"))):
        c = os.path.basename(d)
        if CUIT_RE.match(c) and c not in vistos:
            pub.append({"cuit": c, "razon_social": ""})
    try:
        from . import claves
        for p in claves.pendientes():
            if p["cuit"] not in {c["cuit"] for c in pub}:
                pub.append({"cuit": p["cuit"], "razon_social": p.get("razon_social") or ""})
    except Exception:
        pass
    return pub


_FINALIZADA = re.compile(r"finaliz|cerrad|conclu|archiv|cumplid|respondid|resuelt|anulad|sin efecto|baja", re.I)


def _abiertas(filas) -> list:
    """Fiscalizaciones/controles ABIERTOS: filas con columna de estado/situación no finalizada."""
    out = []
    for f in filas or []:
        if not isinstance(f, dict):
            continue
        est = next((str(v) for k, v in f.items() if re.search(r"estado|situaci", str(k), re.I)), "")
        if est.strip() and not _FINALIZADA.search(est):
            out.append(f)
    return out


def _fecha_txt(v) -> str:
    d = _fecha(v)
    return d.strftime("%d/%m/%Y") if d else str(v or "")


def _pesos_txt(x) -> str:
    return f"$ {x or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def revisiones(cuit: str, cm: dict | None, scth: dict | None, agip: dict | None = None, arba: dict | None = None) -> list[dict]:
    """Deuda histórica que el ENCARGADO tiene que revisar y marcar "visto, me ocupo" (Gaby, 17/11/2026):
    Convenio Multilateral (anticipo con saldo a favor del fisco y sin el pago; capital sin actualizar) y la deuda
    del estado de cumplimiento de Cuentas Tributarias. La clave cambia si aparece deuda nueva: vuelve a pedir revisión."""
    try:
        from . import usuarios
        vis = usuarios.vistos(cuit)
    except Exception:
        vis = {}
    out = []
    for j, v in ((cm or {}).get("jurisdicciones") or {}).items():
        imp = [a for a in v.get("anticipos") or [] if a.get("impago") and "reciente" not in a.get("estado", "")]
        if not imp:
            continue
        clave = f"cm:{cuit}:{j}:{imp[-1]['anticipo']}:{len(imp)}"
        out.append({"clave": clave, "tema": "Convenio Multilateral", "id_sec": "iibb",
                    "texto": f"{j} {v.get('nombre', '')}: {len(imp)} anticipo(s) con saldo a favor del fisco sin el pago "
                             f"({imp[0]['anticipo']} a {imp[-1]['anticipo']})",
                    "importe": v.get("deuda") or 0.0, "a_favor": v.get("saldo_contribuyente") or 0.0,
                    "visto": vis.get(clave)})
    if scth and scth.get("deudas"):
        n = len(scth["deudas"])
        clave = f"sct:{cuit}:{round(scth.get('deuda_total') or 0)}:{n}"
        out.append({"clave": clave, "tema": "Cuentas Tributarias", "id_sec": "historica",
                    "texto": f"Estado de cumplimiento: {n} período(s)/concepto(s) con deuda en "
                             f"{len(scth.get('por_impuesto') or {})} impuesto(s)",
                    "importe": scth.get("deuda_total") or 0.0, "a_favor": None, "visto": vis.get(clave)})
    for org, res in (("agip", agip), ("arba", arba)):  # deuda / saldo a favor en AGIP y ARBA (Gaby 20/11/2026)
        for a in (res or {}).get("alertas") or []:
            if not re.match(r"(AGIP|ARBA): (compensar|saldo a favor para recuperar|deuda en juicio)", a.get("tipo", "")):
                continue
            clave = f"{org}:{cuit}:" + re.sub(r"[^\w.:-]", "", (a["tipo"].split(":")[1] + ":" + "".join(re.findall(r"\d", a["texto"]))[:24]))[:58]
            out.append({"clave": clave, "tema": a["tipo"], "id_sec": "historica",
                        "texto": a["texto"], "importe": None, "a_favor": None, "visto": vis.get(clave)})
    if scth and scth.get("saldos_recuperar"):          # pagos mal hechos: reimputar con el F.399 (Gaby 19/11/2026)
        sr = scth["saldos_recuperar"]
        clave = f"sld:{cuit}:{round(scth.get('saldos_recuperar_total') or 0)}:{len(sr)}"
        out.append({"clave": clave, "tema": "Saldos a recuperar (F.399)", "id_sec": "historica",
                    "texto": "Pago en demasía, reimputable por F.399: "
                             + "; ".join(f"{x['impuesto']} {x.get('nombre', '')[:22]} {x['periodo'][4:6]}/{x['periodo'][:4]} "
                                         f"{_pesos_txt(x['sld'])}" for x in sr[:6]) + ("…" if len(sr) > 6 else "")
                             + (". Deuda en otros impuestos: " + "; ".join(f"{k} {_pesos_txt(v)}" for k, v in
                                sorted((scth.get("por_impuesto") or {}).items(), key=lambda x: -x[1])[:4] if v)
                                if any((scth.get("por_impuesto") or {}).values()) else ""),
                    "importe": None, "a_favor": scth.get("saldos_recuperar_total") or 0.0, "visto": vis.get(clave)})
    return out


def situacion(cuit: str) -> dict:
    """Todo lo último de un cliente + semáforo."""
    base = os.path.join(DATOS, cuit)
    sit = _leer(_ultimo(os.path.join(base, "situacion", "*", "resultado.json"))) or {}
    dfe = _leer(_ultimo(os.path.join(base, "dfe", "*", "resultado.json")))
    corrida = _leer(_ultimo(os.path.join(base, "corrida_todo_*.json")))
    cm = _leer(_ultimo(os.path.join(base, "sifere_deuda", "*.json")))
    arba = _leer(_ultimo(os.path.join(base, "arba_dfe", "[0-9]*", "resultado.json")))
    sct, mf = sit.get("sct"), sit.get("mis_facilidades")
    r = {"cuit": cuit, "fecha": sit.get("fecha"), "sct": sct, "mf": mf, "dfe": dfe, "corrida": corrida,
         "alertas": (sit.get("alertas") or []) + ((dfe or {}).get("alertas") or [])}
    r["deuda_vencida"] = (sct or {}).get("totales_leidos", {}).get("vencido") if sct else None
    r["ddjj"] = len(sct["ddjj_pendientes"]) if sct else None
    vig = (mf or {}).get("vigentes") or []
    r["planes"] = len(vig) if mf else None
    r["cuotas_impagas"] = sum(sum(1 for c in (p.get("detalle_cuotas") or []) if c.get("situacion") == "Vencida impaga")
                              if p.get("detalle_cuotas") is not None else p["vencidas_impagas"] for p in vig) if mf else None
    r["cuotas_15"] = sum(p["a_vencer_15_dias"] for p in vig) if mf else None
    r["caducos"] = sum(1 for a in (mf or {}).get("alertas", []) if a.get("tipo") == "Plan caduco")
    r["dfe_sin_abrir"] = dfe.get("sin_abrir") if dfe else None
    r["dfe_altas"] = dfe.get("altas_sin_abrir") if dfe else None
    r["errores"] = (corrida or {}).get("errores") or {}
    r["deuda_cm"] = (cm or {}).get("deuda_total") or 0.0
    r["arba_altas"] = len((arba or {}).get("alertas") or [])
    # traído de Radar fiscal (17/11/2026): AGIP, fiscalizaciones y relación débito/crédito
    from . import analisis
    agip = _leer(_ultimo(os.path.join(base, "agip", "[0-9]*", "resultado.json")))
    fisc = _leer(_ultimo(os.path.join(base, "fiscalizaciones", "*.json")))
    r["agip"], r["fisc"] = agip, fisc
    ccma = _leer(_ultimo(os.path.join(base, "ccma", "*.json")))   # autónomos / monotributo (17/11/2026)
    scth = _leer(_ultimo(os.path.join(base, "sct_historico", "*.json")))   # deuda histórica SCT (17/11/2026)
    r["cm"], r["scth"] = cm, scth
    r["revisiones"] = revisiones(cuit, cm, scth, agip, arba)
    r["revisar"] = [x for x in r["revisiones"] if not x["visto"]]
    r["ccma"] = ccma
    r["ccma_impagos"] = len((ccma or {}).get("impagos") or [])
    r["ccma_deuda"] = (ccma or {}).get("deuda_impaga") or 0.0
    r["agip_altas"] = (agip or {}).get("altas_sin_abrir") or 0
    r["agip_deuda"] = ((agip or {}).get("deuda") or {}).get("total") or 0.0
    _cct = (agip or {}).get("cct") or {}                # Nueva Cuenta Corriente Tributaria (20/11/2026)
    if _cct.get("saldo_deudor") is not None:
        r["agip_deuda"] = (_cct.get("saldo_deudor") or 0.0) + (_cct.get("intereses") or 0.0 if _cct.get("nominal") is not None else 0.0)
    # Solo filas con estado abierto (mismo criterio que el robot desde el 17/11; corrige datos ya bajados)
    if fisc:
        fisc = {**fisc, **{k: _abiertas(fisc.get(k) or []) for k in ("en_curso", "siace", "fiscalizacion_electronica")}}
        fisc["alertas"] = [a for a in (fisc.get("alertas") or []) if not (
            (a.get("tipo") == "Fiscalización en curso" and not fisc["en_curso"]) or
            (a.get("tipo") == "Control electrónico (SIACE)" and not fisc["siace"]) or
            (a.get("tipo") == "Fiscalización electrónica" and not fisc["fiscalizacion_electronica"]))]
        r["fisc"] = fisc
    agip_f = _abiertas((agip or {}).get("fiscalizacion") or [])
    r["fiscalizaciones"] = (len((fisc or {}).get("en_curso") or []) + len((fisc or {}).get("siace") or [])
                            + len((fisc or {}).get("fiscalizacion_electronica") or []) + len(agip_f))
    r["ratio"] = analisis.ratio_dc(analisis.iva_mensual(cuit))
    r["alertas"] += ((agip or {}).get("alertas") or []) + ((fisc or {}).get("alertas") or []) + ((ccma or {}).get("alertas") or [])
    _fu = _leer(os.path.join(base, "conciliacion", "fuentes.json")) or {}
    r["alertas"] += _fu.get("alertas") or []          # Libro IVA vs Mis Comprobantes (20/11/2026)
    try:                                              # F.931 con personal y sin remuneración leída (19/11/2026)
        from . import asientos
        pend = asientos.f931_pendientes(cuit)
    except Exception:
        pend = []
    r["f931_pendientes"] = pend
    if pend:
        r["alertas"].append({"prioridad": "ALTA", "tipo": "F.931 para completar",
                             "texto": f"{len(pend)} mes(es) con personal sin remuneración leída ("
                                      + ", ".join(f"{x['periodo'][5:]}/{x['periodo'][:4]}" for x in pend[-6:])
                                      + "): el encargado los completa en Asientos contables → Sueldos"})
    r["alertas"] += [{"prioridad": "ALTA", "tipo": f"Deuda histórica para revisar ({x['tema']})",
                      "texto": x["texto"] + f" — {_pesos_txt(x['importe'])} sin actualizar. El encargado tiene que marcarla vista."}
                     if x["importe"] is not None else
                     {"prioridad": "ALTA", "tipo": x["tema"],
                      "texto": x["texto"] + (f" — {_pesos_txt(x['a_favor'])} a recuperar." if x["a_favor"] else "")
                               + " El encargado tiene que marcarla vista."}
                     for x in r["revisar"]]
    ratio_mal = r["ratio"]["nivel"] if r["ratio"] and r["ratio"]["meses"] >= 6 else ""
    minima = analisis.REGLAS["deuda_minima"]
    if not sit and not dfe and not agip and not fisc and not ccma:
        r["semaforo"], r["motivo"] = "gris", "Sin datos todavía"
    elif (r["cuotas_impagas"] or r["ddjj"] or r["dfe_altas"] or r["caducos"] or r["revisar"] or r["arba_altas"]
          or r["agip_altas"] or r["fiscalizaciones"] or r["ccma_impagos"] or ratio_mal == "Crítico"):
        r["semaforo"] = "rojo"
        r["motivo"] = ", ".join(x for x in [
            f"{r['cuotas_impagas']} cuota(s) impaga(s)" if r["cuotas_impagas"] else "",
            f"{r['ddjj']} DDJJ pendiente(s)" if r["ddjj"] else "",
            f"{r['dfe_altas']} notificación(es) importante(s) sin abrir" if r["dfe_altas"] else "",
            f"{r['caducos']} plan(es) caduco(s)" if r["caducos"] else "",
            f"{len(r['revisar'])} deuda(s) histórica(s) para que revise el encargado" if r["revisar"] else "",
            f"{r['arba_altas']} aviso(s) de ARBA" if r["arba_altas"] else "",
            f"{r['agip_altas']} aviso(s) de AGIP" if r["agip_altas"] else "",
            f"{r['fiscalizaciones']} fiscalización(es)/control(es) abiertos" if r["fiscalizaciones"] else "",
            f"{r['ccma_impagos']} período(s) de autónomos/monotributo impago(s)" if r["ccma_impagos"] else "",
            f"relación D/C crítica ({r['ratio']['ratio']:.2f})".replace(".", ",") if ratio_mal == "Crítico" else ""] if x)
    elif ((r["deuda_vencida"] or 0) >= minima or r["agip_deuda"] >= minima or r["deuda_cm"] or r["cuotas_15"] or r["errores"]
          or ratio_mal == "Advertencia"):
        r["semaforo"] = "amarillo"
        r["motivo"] = ", ".join(x for x in [
            "deuda vencida" if (r["deuda_vencida"] or 0) >= minima else "",
            "deuda en AGIP" if r["agip_deuda"] >= minima else "",
            "deuda de Convenio (vista por el encargado)" if r["deuda_cm"] and not r["revisar"] else "",
            f"relación D/C baja ({r['ratio']['ratio']:.2f})".replace(".", ",") if ratio_mal == "Advertencia" else "",
            f"{r['cuotas_15']} cuota(s) vencen en 15 días" if r["cuotas_15"] else "",
            "la última corrida tuvo errores" if r["errores"] else ""] if x)
    else:
        r["semaforo"], r["motivo"] = "verde", "Sin novedades"
    return r


def informes(cuit: str) -> list[dict]:
    out = []
    for ruta in sorted(glob.glob(os.path.join(INFORMES, "*", f"*{cuit}*.xlsx")), reverse=True):
        nombre = os.path.basename(ruta)
        carpeta = os.path.basename(os.path.dirname(ruta))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", carpeta):
            continue
        tipo = ("Relación débito/crédito" if nombre.startswith("relacion_dc") else
                "Situación fiscal" if nombre.startswith("situacion_fiscal") else
                "Conciliación de compras" if nombre.startswith("conciliacion_compras") else
                "Consolidado del grupo" if nombre.startswith("consolidado") else "Informe")
        out.append({"fecha": carpeta, "archivo": nombre, "tipo": tipo, "ruta": f"{carpeta}/{nombre}"})
    return out


def ruta_informe_segura(ruta_rel: str) -> str | None:
    """Solo archivos .xlsx dentro de informes/<AAAA-MM-DD>/ (evita salir de la carpeta)."""
    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})/([\w\-\.]+\.xlsx)", ruta_rel or "")
    if not m:
        return None
    ruta = os.path.realpath(os.path.join(INFORMES, m[1], m[2]))
    if not ruta.startswith(os.path.realpath(INFORMES) + os.sep) or not os.path.isfile(ruta):
        return None
    return ruta


def agenda(dias: int = 15, solo: set | None = None) -> list[dict]:
    hoy = date.today()
    lim = hoy + timedelta(days=dias)
    nombres = {c["cuit"]: c.get("razon_social") or "" for c in lista_clientes(solo)}
    out = []
    for cuit, nom in nombres.items():
        s = situacion(cuit)
        for v in (s["sct"] or {}).get("vencimientos", []):
            f = _fecha(v.get("vencimiento"))
            if f and hoy <= f <= lim:
                out.append({"fecha": f, "cuit": cuit, "nombre": nom, "que": f"{v['impuesto']} {v['periodo_txt']}",
                            "detalle": v.get("detalle", ""), "importe": None, "tipo": "vencimiento"})
        for p in (s["mf"] or {}).get("vigentes", []):
            for c in p["detalle_cuotas"]:
                f = _fecha(c.get("venc_1"))
                if c["situacion"] == "Vencida impaga":
                    out.append({"fecha": f, "cuit": cuit, "nombre": nom, "que": f"Plan {p['numero']} cuota {c['cuota']}",
                                "detalle": "Impaga (ARCA)", "importe": c.get("total_2") or c.get("total_1"), "tipo": "impaga"})
                elif c["situacion"] in ("Pendiente de pago", "Vencida sin pago informado"):
                    f2 = _fecha(c.get("venc_2")) or f
                    out.append({"fecha": f2, "cuit": cuit, "nombre": nom, "que": f"Plan {p['numero']} cuota {c['cuota']}",
                                "detalle": "Pendiente de pago (2° vencimiento)" if c.get("venc_2") else "Pendiente de pago",
                                "importe": c.get("total_2") or c.get("total_1"), "tipo": "cuota"})
                elif c["situacion"] == "A vencer" and f and f <= lim:
                    out.append({"fecha": f, "cuit": cuit, "nombre": nom, "que": f"Plan {p['numero']} cuota {c['cuota']}",
                                "detalle": "Débito de cuota", "importe": c.get("total_1"), "tipo": "cuota"})
    out.sort(key=lambda x: (x["tipo"] != "impaga", x["fecha"] or date.min))
    return out


def ultimas_corridas(n: int = 60) -> list[dict]:
    try:
        with open(REGISTRO, encoding="utf-8") as f:
            lineas = f.readlines()[-n:]
    except OSError:
        return []
    out = []
    for l in reversed(lineas):
        try:
            e = json.loads(l)
        except ValueError:
            continue
        e.pop("traza", None)
        e["detalle"] = str(e.get("detalle") or e.get("errores") or "")[:200]
        out.append(e)
    return out


# ---------------------------------------------------------------- ficha por botones (16/11/2026)
def _notificaciones(base: str, dfe: dict | None) -> list[dict]:
    """ARCA (e-ventanilla) + ARBA (Domicilio Fiscal Electrónico) en un solo formato, importantes primero."""
    out = []
    for c in (dfe or {}).get("comunicaciones", []):
        out.append({"origen": "ARCA", "fecha": c.get("fecha"), "organismo": c.get("organismo"), "asunto": c.get("asunto"),
                    "importancia": c.get("importancia"), "para": c.get("para", ""), "motivo": c.get("motivo", ""),
                    "responsable": c.get("responsable", ""),
                    "estado": (f"NOTIFICADA{' DE OFICIO' if c.get('de_oficio') else ''} el {c.get('notificado')} — SIN LEER"
                               if c.get("notificada_sin_leer") else c.get("notificado") or "SIN ABRIR"),
                    "notificada_sin_leer": bool(c.get("notificada_sin_leer")),
                    "pendiente": not c.get("leida"), "plazo": "", "resumen": ""})
    arba = _leer(_ultimo(os.path.join(base, "arba_dfe", "[0-9]*", "resultado.json")))
    for c in (arba or {}).get("comunicaciones", []):
        out.append({"origen": "ARBA", "fecha": c.get("fecha"), "organismo": "ARBA", "asunto": c.get("asunto"),
                    "importancia": c.get("importancia"), "para": c.get("para", ""), "motivo": c.get("motivo", ""),
                    "responsable": c.get("responsable", ""), "estado": c.get("estado_robot") or f"notificada {c.get('notificado') or ''}",
                    "pendiente": False, "plazo": c.get("plazo") or "", "resumen": c.get("resumen") or ""})
    agip = _leer(_ultimo(os.path.join(base, "agip", "[0-9]*", "resultado.json")))
    for c in (agip or {}).get("comunicaciones", []):
        out.append({"origen": "AGIP", "fecha": c.get("fecha"), "organismo": "AGIP", "asunto": c.get("asunto"),
                    "importancia": c.get("importancia"), "para": "", "motivo": c.get("clasificacion", ""),
                    "responsable": "", "estado": c.get("estado") or ("SIN ABRIR" if not c.get("leida") else ""),
                    "pendiente": not c.get("leida"), "plazo": "", "resumen": c.get("impuesto") or ""})
    orden = {"ALTA": 0, "Media": 1, "Baja": 2}

    def clave(n):
        f = _fecha((n["fecha"] or "").replace("-", "/")) or date.min
        return (not n.get("notificada_sin_leer"), orden.get(n["importancia"], 1), -f.toordinal())
    for n in out:                                     # prioridad para el tablero (17/11/2026)
        n["prioridad"] = (1 if n.get("notificada_sin_leer") else 2 if n["importancia"] == "ALTA" and n["pendiente"]
                          else 3 if n["importancia"] == "ALTA" else 4 if n["importancia"] == "Media" else 5)
    import hashlib
    for n in out:
        n["id"] = hashlib.sha1(f"{base}|{n['origen']}|{n['fecha']}|{n['asunto']}".encode()).hexdigest()[:16]
    return sorted(out, key=clave), arba


def veps_deuda(cuit: str) -> dict:
    """VEPs de deuda generados desde el sistema (20/11/2026): los ya generados (con su captura) y los pedidos en curso o fallidos."""
    gen = []
    for r in sorted(glob.glob(os.path.join(DATOS, cuit, "vep", "*_deuda_*.json")), reverse=True):
        v = _leer(r)
        if isinstance(v, dict) and v.get("vep"):
            v["archivo"] = os.path.basename(r)[:-5]
            v["captura"] = os.path.exists(r[:-5] + ".png")
            gen.append(v)
    hechos = {str(v["vep"]) for v in gen}
    ped = []
    for p in _leer(os.path.join(PUBLICO, "pedidos_estado.json")) or []:
        if not isinstance(p, dict) or p.get("cuit") != cuit or p.get("robot") != "vep_deuda":
            continue
        m = re.search(r"VEP (\d+)", p.get("detalle") or "")
        if p.get("estado") == "terminado" and m and m[1] in hechos:
            continue                                   # ya figura con todo su detalle
        ped.append(p)
    return {"generados": gen, "pedidos": ped[:10]}


def ficha(cuit: str) -> dict:
    """Situación + todo lo nuevo, y los botones de la ficha (cada uno con un número y un color)."""
    s = situacion(cuit)
    base = os.path.join(DATOS, cuit)
    notif, arba = _notificaciones(base, s["dfe"])
    cm = _leer(_ultimo(os.path.join(base, "sifere_deuda", "*.json")))
    obs = _leer(os.path.join(base, "observados", "observados.json"))
    cat = (_leer(os.path.join(base, "categoria.json")) or {}).get("categoria", "")
    meses_liva = len(glob.glob(os.path.join(base, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")))
    hoy = date.today()
    proximos = []
    for v in (s["sct"] or {}).get("vencimientos", []):
        f = _fecha(v.get("vencimiento"))
        if f and hoy <= f <= hoy + timedelta(days=15):
            proximos.append({"fecha": f, "que": f"{v['impuesto']} {v['periodo_txt']}", "detalle": v.get("detalle")})
    inf = informes(cuit)
    organismos = []
    for org, titulo in (("ARCA", "ARCA (e-ventanilla)"), ("ARBA", "ARBA"), ("AGIP", "AGIP")):
        lista = [n for n in notif if n["origen"] == org]
        if not lista:
            continue
        nuevas = [n for n in lista if n["importancia"] == "ALTA" and (n["pendiente"] or "HOY" in n["estado"])]
        altas = [n for n in lista if n["importancia"] == "ALTA"]
        organismos.append({"id": org, "titulo": titulo, "nuevas": len(nuevas), "altas": len(altas), "total": len(lista),
                           "color": "rojo" if nuevas else "amarillo" if altas else "verde"})
    s.update(notificaciones=notif, arba_dfe=arba, organismos=organismos, cm=cm, observados=obs, categoria=cat, meses_liva=meses_liva,
             proximos=sorted(proximos, key=lambda x: x["fecha"]), informes_lista=inf)

    def color(rojo, amarillo=False, hay=True):
        return "gris" if not hay else "rojo" if rojo else "amarillo" if amarillo else "verde"
    b = []
    sct, mf = s["sct"], s["mf"]
    # 20/11/2026: "Deuda" muestra solo lo VENCIDO; lo que está por vencer va a su propia pantalla
    deudas_ = (sct or {}).get("deudas") or []
    s["deudas_vencidas"] = [d for d in deudas_ if d.get("vencida") and (d.get("total") or 0) > 0]
    s["deudas_por_vencer"] = [d for d in deudas_ if not d.get("vencida") and (d.get("total") or 0) > 0]
    n_obl = len(s["deudas_vencidas"])
    s["veps_deuda"] = veps_deuda(cuit)
    # 20/11/2026 (Benavidez): si Cuentas Tributarias no se pudo leer, no decir "sin datos" cuando hay deuda conocida
    # por otras consultas (autónomos/monotributo de CCMA, estado de cumplimiento).
    otras = []
    if not sct:
        if s.get("ccma_deuda"):
            otras.append(("autónomos / monotributo impagos", s["ccma_deuda"]))
        if (s.get("scth") or {}).get("deuda_total"):
            otras.append(("estado de cumplimiento", s["scth"]["deuda_total"]))
    valor_deuda = s["deuda_vencida"] if sct else (max(v for _, v in otras) if otras else None)
    b.append({"id": "deuda", "titulo": "Deuda ARCA", "valor": valor_deuda, "pesos": True,
              "sub": (f"{n_obl} obligación(es) vencida(s)" if sct else
                      "Cuentas Tributarias sin leer (la corrida falló) · " + " · ".join(f"{t} {_pesos_txt(v)}" for t, v in otras)
                      if otras else "sin datos (Cuentas Tributarias sin leer)"),
              "color": color((valor_deuda or 0) > 0, hay=bool(sct) or bool(otras)),
              # crédito a recuperar con el F.399 (S.L.D. fuera del IVA), pedido de Gaby 20/11/2026
              "sub2": (f"crédito a recuperar (F.399): {_pesos_txt((s.get('scth') or {}).get('saldos_recuperar_total') or 0)}"
                       if "saldos_recuperar" in (s.get("scth") or {}) else
                       "crédito a recuperar (F.399): se calcula en la próxima corrida de Deuda histórica" if s.get("scth") else "")})
    if sct:
        pv = s["deudas_por_vencer"]
        prox = min((d.get("vencimiento") or "" for d in pv if d.get("vencimiento")), default="")
        b.append({"id": "por_vencer", "titulo": "Por vencer", "valor": round(sum(d.get("total") or 0 for d in pv), 2) if pv else 0,
                  "pesos": bool(pv),
                  "sub": (f"{len(pv)} obligación(es) · próxima {_fecha_txt(prox)}" if pv else "nada por vencer en Cuentas Tributarias"),
                  "color": "amarillo" if pv else "verde"})
    b.append({"id": "planes", "titulo": "Planes de pago", "valor": s["planes"],
              "sub": (f"{s['cuotas_impagas'] or 0} cuotas impagas · {s['caducos']} caducos · {s['cuotas_15'] or 0} vencen en 15 días"
                      if mf else "sin datos"),
              "color": color(bool(s["cuotas_impagas"] or s["caducos"]), bool(s["cuotas_15"]), hay=bool(mf))})
    b.append({"id": "vencimientos", "titulo": "Vencimientos", "valor": len(proximos), "sub": "en los próximos 15 días",
              "color": color(False, bool(proximos), hay=bool(sct))})
    b.append({"id": "ddjj", "titulo": "DDJJ / faltas de presentación", "valor": s["ddjj"], "sub": "pendientes",
              "color": color(bool(s["ddjj"]), hay=bool(sct))})
    imp = [n for n in notif if n["importancia"] == "ALTA" and (n["pendiente"] or "HOY" in n["estado"])]
    altas = [n for n in notif if n["importancia"] == "ALTA"]
    b.append({"id": "notificaciones", "titulo": "Notificaciones", "valor": len(imp),
              "sub": f"importantes nuevas · {len(altas)} importantes en total · ARCA, ARBA y AGIP",
              "color": color(bool(imp), bool(altas), hay=bool(notif))})
    if cm or arba:
        jur = (cm or {}).get("jurisdicciones") or {}
        b.append({"id": "iibb", "titulo": "Ingresos Brutos", "valor": (cm or {}).get("deuda_total"), "pesos": True,
                  "sub": (f"Convenio: {sum(1 for v in jur.values() if v['deuda'])} jurisdicción(es) con deuda"
                          if cm else "ARBA"),
                  "color": "rojo" if any(x["tema"] == "Convenio Multilateral" for x in s["revisar"])
                           else "amarillo" if (cm or {}).get("deuda_total") else color(False, hay=bool(cm))})
    if meses_liva or obs:
        n_obs = len((obs or {}).get("comprobantes") or [])
        b.append({"id": "compras", "titulo": "Compras y APOC", "valor": n_obs if obs else None,
                  "sub": "comprobantes observados por ARCA" if obs else "conciliación con el Libro IVA",
                  "color": color(False, bool(n_obs), hay=True) if obs else "gris"})
    from . import analisis
    iva = analisis.iva_mensual(cuit)
    s["iva"], s["proyeccion"] = iva, analisis.proyectar_iva(iva)
    if iva:
        rt = s["ratio"]
        # 20/11/2026: es débito fiscal ÷ crédito fiscal de IVA, NO la utilidad (la utilidad está en "Relación débito
        # crédito": ventas sin IVA − erogaciones). Mostrarla acá como "utilidad" contradecía a la otra tarjeta.
        b.append({"id": "iva", "titulo": "IVA: débito / crédito fiscal", "valor": f"{rt['ratio']:.2f}".replace(".", ",") if rt and rt["credito"] else None,
                  "sub": f"débito fiscal ÷ crédito fiscal, {rt['meses']} meses · {rt['nivel']} · proyección" if rt else "",
                  "color": {"Crítico": "rojo", "Advertencia": "amarillo"}.get((rt or {}).get("nivel"), "verde")})
    res = analisis.resultado_mensual(cuit)
    s["resultado"] = analisis.analizar_resultado(res)
    if res or meses_liva or any(i["tipo"] == "Relación débito/crédito" for i in inf):
        tot = (s["resultado"] or {}).get("total") or {"resultado": None}
        inc = (s["resultado"] or {}).get("incompletos") or []
        fu = _leer(os.path.join(DATOS, cuit, "conciliacion", "fuentes.json")) or {}
        s["fuentes"] = fu
        dif = [f for f in fu.get("meses") or [] if f.get("estado") == "DIFERENCIA"]
        r_pct = lambda x: f"{x * 100:.2f}%".replace(".", ",") if x is not None else "—"
        if inc:                                            # 20/11/2026: sin números engañosos si faltan datos
            b.append({"id": "relacion", "titulo": "Relación débito crédito", "valor": "datos incompletos",
                      "sub": f"{len(inc)} de {len(res)} meses sin alguna fuente (" + ", ".join(sorted({x for m in inc for x in m.get('faltantes', [])}))
                             + ") · ver detalle", "color": "amarillo"})
        else:
            b.append({"id": "relacion", "titulo": "Relación débito crédito", "valor": tot["resultado"], "pesos": True,
                      "sub": f"{len(res)} meses · índice erogaciones/ventas {r_pct(tot.get('indice'))} · margen {r_pct(tot.get('margen'))}"
                             + (f" · {len(dif)} mes(es) no coinciden con Mis Comprobantes" if dif else ""),
                      "color": "gris" if tot["resultado"] is None else "rojo" if tot["resultado"] < 0 or dif else "verde"})
    if s["fisc"] or (s["agip"] or {}).get("fiscalizacion") is not None:
        b.append({"id": "fiscalizaciones", "titulo": "Fiscalizaciones", "valor": s["fiscalizaciones"],
                  "sub": "ARCA (OI, SIACE) y AGIP", "color": "rojo" if s["fiscalizaciones"] else "verde"})
    if s["scth"] or s["revisiones"]:
        h_ = s["scth"] or {}
        b.append({"id": "historica", "titulo": "Deuda histórica", "valor": h_.get("deuda_total") if h_ else None, "pesos": bool(h_),
                  "sub": (f"{len(s['revisar'])} para revisar (encargado)" if s["revisar"] else "revisada por el encargado"
                          if s["revisiones"] else "sin deuda") + " · estado de cumplimiento",
                  "color": "rojo" if s["revisar"] else "amarillo" if s["revisiones"] else "verde"})
    if s["ccma"]:
        cm_ = s["ccma"]
        b.append({"id": "ccma", "titulo": "Autónomos / Monotributo", "valor": s["ccma_deuda"] or (0 if not cm_.get("sin_ccma") else None),
                  "pesos": bool(s["ccma_deuda"]),
                  "sub": (f"{s['ccma_impagos']} período(s) impago(s)" if s["ccma_impagos"] else
                          "sin deuda" if cm_.get("sin_ccma") else "pagos al día") + f" · CCMA {cm_.get('fecha', '')[8:10]}/{cm_.get('fecha', '')[5:7]}",
                  "color": "rojo" if s["ccma_impagos"] else "amarillo" if (cm_.get("totales") or {}).get("deudor_accesorios") else "verde"})
    if s["agip"]:
        b.append({"id": "agip", "titulo": "AGIP (Ciudad)", "valor": s["agip_deuda"] or None, "pesos": True,
                  "sub": f"{(s['agip'] or {}).get('sin_abrir') or 0} comunicaciones sin abrir · deuda",
                  "color": "rojo" if s["agip_altas"] else "amarillo" if s["agip_deuda"] >= analisis.REGLAS["deuda_minima"] else "verde"})
    if meses_liva:
        b.append({"id": "ventas_bancos", "titulo": "Ventas para bancos", "valor": None,
                  "sub": "reporte mensual desde el Portal IVA (Excel / PDF)", "color": "gris"})
    b.append({"id": "informes", "titulo": "Informes Excel", "valor": len(inf), "sub": "para bajar", "color": "gris"})
    s["botones"] = b
    return s


def alertas_del_dia(solo: set | None = None) -> list[dict]:
    """Lo urgente (ALTA) de todos los clientes, para la pantalla 'Alertas del día'."""
    out = []
    for c in lista_clientes(solo):
        f = ficha(c["cuit"])
        al = [a for a in f["alertas"] if a.get("prioridad") == "ALTA"]
        al += [a for a in ((f["arba_dfe"] or {}).get("alertas") or []) if a.get("prioridad") == "ALTA"]
        # Convenio: ya va como "Deuda histórica para revisar" mientras el encargado no la marque vista
        if f.get("ratio") and f["ratio"]["nivel"] == "Crítico" and f["ratio"]["meses"] >= 6:
            al.append({"prioridad": "ALTA", "tipo": "Relación débito/crédito crítica",
                       "texto": f"D/C {f['ratio']['ratio']:.2f} en {f['ratio']['meses']} meses (menos de 0,8)".replace(".", ",", 1)})
        al = [{**a, "tipo": a.get("tipo") or a.get("Tipo de alerta", ""), "texto": a.get("texto") or a.get("Acción", "")}
              for a in al]
        if al:
            out.append({"cuit": c["cuit"], "nombre": c.get("razon_social") or "", "semaforo": f["semaforo"], "alertas": al})
    out.sort(key=lambda x: ({"rojo": 0, "amarillo": 1, "verde": 2, "gris": 3}[x["semaforo"]], -len(x["alertas"])))
    return out


# ---------------------------------------------------------------- vistas de toda la cartera (Radar fiscal, 17/11/2026)
def cartera(solo: set | None = None) -> list[dict]:
    """Ficha completa de cada cliente (para las pantallas que listan a todos)."""
    out = []
    for c in lista_clientes(solo):
        try:
            f = ficha(c["cuit"])
        except Exception:                                    # un cliente con datos rotos no tira abajo la pantalla
            continue
        out.append({"cuit": c["cuit"], "nombre": c.get("razon_social") or cuit_fmt(c["cuit"]), "f": f})
    return out
