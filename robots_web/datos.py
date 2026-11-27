"""Lectura (solo lectura) de lo que dejan los robots. No accede al almacén de claves."""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import date, datetime, timedelta

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
    # 21/11/2026: los archivos de trabajo del robot empiezan con "_" (_parcial.json, _lista.json) y NO son una lectura:
    # "_" ordena después de los dígitos y se tomaba _parcial.json como la última deuda histórica (error 500 en la ficha)
    r = sorted(x for x in glob.glob(patron) if not os.path.basename(x).startswith("_"))
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
    try:                                               # razón social corregida por un admin (20/11/2026)
        from . import usuarios as _u
        corr = _u.razones_corregidas()
        pub = [{**c, "razon_social": corr[c["cuit"]]} if c.get("cuit") in corr else c for c in pub]
    except Exception:
        pass
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
        bajas = claves.bajas_pendientes()                  # dados de baja desde la web: desaparecen ya (25/11/2026)
        if bajas:
            pub = [c for c in pub if c["cuit"] not in bajas]
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


def rectificativas_iva(cuit: str) -> list[dict]:
    """Última presentación del Libro IVA de cada período (Gaby 26/11/2026): "Libro IVA rectificativa X y la fecha:
    cuándo se rectificó por última vez, para pescar lo viejo si hay una fiscalización y reclaman APOC"."""
    out = []
    for ruta in sorted(glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")), reverse=True):
        d = _leer(ruta) or {}
        if d.get("secuencia_portal") is None:
            continue
        out.append({"periodo": os.path.basename(ruta)[:7], "secuencia": int(d.get("secuencia_portal") or 0),
                    "secuencia_txt": d.get("secuencia_txt") or "", "fecha": d.get("fecha_presentacion") or ""})
    return out


def _fecha_txt(v) -> str:
    d = _fecha(v)
    return d.strftime("%d/%m/%Y") if d else str(v or "")


def _pesos_txt(x) -> str:
    return f"$ {x or 0:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _cod(t) -> str:
    m = re.match(r"\s*0*(\d+)", str(t or ""))
    return m[1] if m else ""


def _cuota(t) -> str:
    return str(int(re.sub(r"\D", "", str(t)) or 0)) if re.sub(r"\D", "", str(t or "")) else ""


def solo_vencido(scth: dict | None, sct: dict | None) -> dict | None:
    """Deuda histórica (estado de cumplimiento) SOLO con lo vencido (Gaby 26/11/2026: "me pone deuda histórica en
    urgente y son anticipos que aún no vencen"). El estado de cumplimiento no trae el vencimiento ni siempre el número
    de anticipo; la lectura diaria de Cuentas Tributarias sí. Cada renglón se cruza con su ítem de Cuentas Tributarias
    (mismo impuesto y período; por número de anticipo/cuota, o si no lo hay, por importe) y toma su número, su
    vencimiento y si está vencido. Lo que todavía no vence sale de la deuda y se muestra aparte."""
    if not scth or not scth.get("deudas"):
        return scth
    cands: dict[tuple, list] = {}
    for d in (sct or {}).get("deudas") or []:
        cands.setdefault((_cod(d.get("impuesto")), str(d.get("periodo") or "")), []).append(d)
    for v in cands.values():
        v.sort(key=lambda d: str(d.get("vencimiento") or "9"))
    usados = set()
    filas, nv = [], []
    for f in scth["deudas"]:
        lista = cands.get((_cod(f.get("impuesto")), str(f.get("periodo") or ""))) or []
        cu = _cuota(f.get("cuota"))
        libres = [d for d in lista if id(d) not in usados]
        m = None
        if cu:
            m = next((d for d in libres if _cuota(d.get("cuota")) == cu), None)
        if m is None:
            m = next((d for d in libres if abs((d.get("capital") or 0) - (f.get("deuda") or 0)) < 1), None)
        if m is None and not cu and len({_cuota(d.get("cuota")) for d in lista}) == 1 and libres:
            m = libres[0]
        g = dict(f)
        if m is not None:
            usados.add(id(m))
            g["cuota"] = g.get("cuota") or _cuota(m.get("cuota"))
            g["vencimiento"] = str(m.get("vencimiento") or "")[:10]
            if not m.get("vencida"):
                nv.append(g)
                continue
        filas.append(g)
    filas.sort(key=lambda f: (str(f.get("impuesto")), str(f.get("periodo")), f.get("vencimiento") or ""))
    nv.sort(key=lambda f: f.get("vencimiento") or "9")
    por_imp = {}
    for f in filas:
        k = f"{f['impuesto']} - {f['nombre']}"
        por_imp[k] = round(por_imp.get(k, 0.0) + f["deuda"], 2)
    tot = round(sum(f["deuda"] for f in filas), 2)
    ter = round(sum(f["deuda"] for f in filas if f.get("color") == "verde"), 2)
    return {**scth, "deudas": filas, "por_impuesto": por_imp, "deuda_total": tot, "deuda_terceros": ter,
            "deuda_arca": round(tot - ter, 2),
            "deuda_f931_otros": round(sum(f["deuda"] for f in filas if f.get("f931") and f.get("impuesto") not in ("301", "351")), 2),
            "no_vencido": nv, "no_vencido_total": round(sum(f["deuda"] for f in nv), 2)}


def revisiones(cuit: str, cm: dict | None, scth: dict | None, agip: dict | None = None, arba: dict | None = None,
               perc: dict | None = None, ccma: dict | None = None) -> list[dict]:
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
    mono = (ccma or {}).get("monotributo") or {}
    al_m = [a for a in (ccma or {}).get("alertas") or [] if a.get("tipo", "").startswith("Monotributo:")]
    if al_m:                                         # monotributo: superó / cerca del tope (Gaby 22/11/2026)
        clave = f"mono:{cuit}:{mono.get('categoria') or 'x'}:{round(mono.get('facturado') or 0)}"
        out.append({"clave": clave, "tema": al_m[0]["tipo"], "id_sec": "ccma", "texto": al_m[0]["texto"],
                    "importe": None, "a_favor": None, "visto": vis.get(clave)})
    if perc and perc.get("sin_comprobante"):         # percepciones sin factura en el Libro IVA (Gaby 21/11/2026)
        sc = perc["sin_comprobante"]
        clave = f"perc:{cuit}:{round(perc.get('total_sin_comprobante') or 0)}:{len(sc)}"
        out.append({"clave": clave, "tema": "Percepciones sin factura en el Libro IVA", "id_sec": "relacion",
                    "texto": f"{len(sc)} percepción(es) por {_pesos_txt(perc.get('total_sin_comprobante') or 0)} de "
                             f"{len({x['agente'] for x in sc})} agente(s): ni el gasto ni el crédito fiscal se computaron; buscar las facturas",
                    "importe": None, "a_favor": None, "visto": vis.get(clave)})
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
    r["ddjj_determinativas"] = ddjj_determinativas((sct or {}).get("ddjj_pendientes"))
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
    perc = _leer(os.path.join(base, "conciliacion", "percepciones.json"))   # percepciones vs Libro IVA (21/11/2026)
    scth = solo_vencido(scth, sct)
    r["cm"], r["scth"], r["percepciones"] = cm, scth, perc
    r["revisiones"] = revisiones(cuit, cm, scth, agip, arba, perc, ccma)
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
    _vistos_av = set()                                 # IVA diferido y anticipos: aviso 10 días antes (20/11/2026)
    for d in ((sct or {}).get("deudas") or []) + ((sct or {}).get("vencimientos") or []):
        es_iva = re.match(r"\s*0*30\b|.*\bIVA\b", str(d.get("impuesto") or ""), re.I) and "capital" in d
        es_ant = re.search(r"anticip|\b191\b", f"{d.get('concepto') or ''} {d.get('subconcepto') or ''}", re.I)
        if d.get("vencida") or not (es_iva or es_ant):
            continue
        v = _fecha(str(d.get("vencimiento") or "")[:10])
        k = (str(d.get("impuesto"))[:3], str(d.get("periodo")), str(d.get("cuota")), v)
        if not v or not 0 <= (v - date.today()).days <= 10 or k in _vistos_av:
            continue
        if "capital" in d and not (d.get("total") or d.get("capital")):
            continue
        _vistos_av.add(k)
        imp = d.get("total") or d.get("capital")
        r["alertas"].append({"prioridad": "ALTA", "tipo": "IVA diferido por vencer" if es_iva else "Anticipo por vencer",
                             "texto": (f"IVA {d.get('periodo_txt') or d.get('periodo')}" if es_iva else
                                       f"Anticipo {d.get('cuota') or ''} {d.get('impuesto') or ''} {d.get('periodo_txt') or ''}")
                                      + f" vence el {v:%d/%m/%Y}" + (f" ({_pesos_txt(imp)})" if imp else "")
                                      + ": avisarle al cliente"})
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
    r["agente_impago"] = agente_impago(sct, agip, arba)
    if r["agente_impago"]:
        r["alertas"].insert(0, {"prioridad": "URGENTE", "tipo": "Retenciones / percepciones NO depositadas",
                                "texto": "; ".join(f"{x['organismo']} {x['concepto']} {x['periodo']} {_pesos_txt(x['importe'])}".replace("  ", " ")
                                                   for x in r["agente_impago"])
                                         + ". Es plata retenida a terceros: depositar YA (riesgo de apropiación indebida)."})
    if r["ddjj_determinativas"]:
        # misma alerta "Falta de presentación" (así sigue funcionando el descarte), pero URGENTE y marcada
        for a_ in r["alertas"]:
            if str(a_.get("tipo", "")).startswith("Falta de presentaci"):
                a_["prioridad"] = "URGENTE"
                a_["grave"] = ("DDJJ que determina impuesto sin presentar (más grave que los informativos): "
                               + "; ".join(f"{d.get('impuesto')} {d.get('periodo_txt') or ''}".strip() for d in r["ddjj_determinativas"][:6]))
    ratio_mal = r["ratio"]["nivel"] if r["ratio"] and r["ratio"]["meses"] >= 6 else ""
    minima = analisis.REGLAS["deuda_minima"]
    if not sit and not dfe and not agip and not fisc and not ccma:
        r["semaforo"], r["motivo"] = "gris", "Sin datos todavía"
    elif (r["agente_impago"] or r["cuotas_impagas"] or r["ddjj"] or r["dfe_altas"] or r["caducos"] or r["revisar"] or r["arba_altas"]
          or r["agip_altas"] or r["fiscalizaciones"] or r["ccma_impagos"] or ratio_mal == "Crítico"):
        r["semaforo"] = "rojo"
        r["motivo"] = ", ".join(x for x in [
            "RETENCIONES/PERCEPCIONES NO DEPOSITADAS" if r["agente_impago"] else "",
            f"{len(r['ddjj_determinativas'])} DDJJ DETERMINATIVA(S) SIN PRESENTAR" if r["ddjj_determinativas"] else "",
            f"{r['cuotas_impagas']} cuota(s) impaga(s)" if r["cuotas_impagas"] else "",
            (f"{r['ddjj'] - len(r['ddjj_determinativas'])} DDJJ informativa(s) pendiente(s)"
             if r["ddjj"] and r["ddjj"] > len(r["ddjj_determinativas"]) else ""),
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
    """Solo el último de cada informe (20/11/2026): si quedó una copia vieja de otra fecha, no se lista."""
    out, vistos = [], set()
    for ruta in sorted(glob.glob(os.path.join(INFORMES, "*", f"*{cuit}*.xlsx")), reverse=True):
        nombre = os.path.basename(ruta)
        if nombre in vistos:
            continue
        vistos.add(nombre)
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
                               if c.get("notificada_sin_leer") else "abierta por el robot (sin importancia)"
                               if c.get("abierta_por_robot") else c.get("notificado") or "SIN ABRIR"),
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
    orden = {"URGENTE": -1, "ALTA": 0, "Media": 1, "Baja": 2}

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


JUR_CM = {"901": "CABA", "902": "Buenos Aires", "903": "Catamarca", "904": "Córdoba", "905": "Corrientes", "906": "Chaco",
          "907": "Chubut", "908": "Entre Ríos", "909": "Formosa", "910": "Jujuy", "911": "La Pampa", "912": "La Rioja",
          "913": "Mendoza", "914": "Misiones", "915": "Neuquén", "916": "Río Negro", "917": "Salta", "918": "San Juan",
          "919": "San Luis", "920": "Santa Cruz", "921": "Santa Fe", "922": "Santiago del Estero", "923": "Tierra del Fuego",
          "924": "Tucumán"}


def regimen_detectado(cuit: str) -> dict | None:
    """Régimen de IIBB que se deduce de lo bajado (25/11/2026): DDJJ en SIFERE = Convenio Multilateral (con las
    jurisdicciones de la última CM03); solo DJ de ARBA = local Buenos Aires. None si no se puede saber."""
    sif = sorted(glob.glob(os.path.join(DATOS, cuit, "sifere", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")))
    if sif:
        jur = (_leer(sif[-1]) or {}).get("jurisdicciones") or {}
        return {"regimen_iibb": "Convenio Multilateral", "jurisdicciones_iibb": ", ".join(JUR_CM.get(j, j) for j in sorted(jur))}
    if glob.glob(os.path.join(DATOS, cuit, "arba", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        return {"regimen_iibb": "Local", "jurisdicciones_iibb": "Buenos Aires"}
    return None


def registral(cuit: str) -> dict:
    """Último Sistema Registral leído por el robot (o {})."""
    return _leer(_ultimo(os.path.join(DATOS, cuit, "sistema_registral", "*.json"))) or {}


def apoc_salieron(cuit: str) -> dict:
    """APOC que dejaron de figurar en Nuestra Parte (Gaby 26/11/2026: "si sale en cero, ¿es porque se rectificó o
    porque no tiene? Si es por rectificado, la lista de APOC y la fecha de la rectificativa que devuelve al fisco el
    crédito fiscal indebido"). Se cruza cada uno con el Libro IVA de su período: si ya no está en la DJ vigente, la
    rectificativa (secuencia y fecha de presentación) es la que lo sacó."""
    h = _leer(os.path.join(DATOS, cuit, "observados", "observados_historial.json")) or {}
    out = []
    for c in (h.get("comprobantes") or {}).values():
        if not c.get("dejo_de_figurar") or c.get("nc"):
            continue
        per = str(c.get("fecha") or "")[:7]
        liva = _leer(os.path.join(DATOS, cuit, "libro_iva", f"{per}.json")) if per else None
        en_dj = None
        if liva:
            en_dj = any(re.sub(r"\D", "", str(x.get("cuit") or "")) == str(c.get("cuit")) and int(x.get("punto_venta") or 0) == int(c.get("punto_venta") or 0)
                        and int(x.get("numero") or 0) == int(c.get("numero") or 0) for x in liva.get("comprobantes_compras") or [])
        sec = (liva or {}).get("secuencia_portal")
        out.append({**c, "periodo": per, "en_dj_vigente": en_dj,
                    "dj_secuencia": (liva or {}).get("secuencia_txt") or (f"Rectificativa {sec}" if sec else ""),
                    "dj_fecha": (liva or {}).get("fecha_presentacion") or "",
                    "rectificado": en_dj is False and bool(sec)})
    out.sort(key=lambda x: (x["periodo"], x.get("nombre") or ""))
    return {"lista": out, "desde": h.get("desde") or "", "iva": round(sum(x.get("iva") or 0 for x in out), 2)}


def _fecha_txt(v) -> str:
    d = _fecha(str(v or "")[:10])
    return d.strftime("%d/%m/%Y") if d else str(v or "")


# Gaby y Tomás 26/11/2026: lo GRAVE va aparte.
# 1) DDJJ que determinan impuesto sin presentar (IVA, Ganancias, Bienes Personales, F.931, SICORE…) es mucho más grave
#    que un régimen informativo (103 y similares).
# 2) Retenciones / percepciones practicadas y no depositadas, y aportes retenidos al personal: puede ser apropiación
#    indebida (ley penal tributaria), no una deuda común.
INFORMATIVOS = re.compile(r"^\s*0*103\b|INFORMACI[OÓ]N|INFORMATIV", re.I)
AGENTE_ARCA = {"217": "SICORE Ganancias (retenciones)", "767": "SICORE IVA (retenciones / percepciones)",
               "301": "aportes personales retenidos al personal (F.931)", "302": "aportes de obra social retenidos (F.931)"}


def ddjj_determinativas(lista: list[dict]) -> list[dict]:
    return [d for d in lista or [] if not INFORMATIVOS.search(f"{d.get('impuesto') or ''} {d.get('concepto') or ''}")]


def agente_impago(sct: dict | None, agip: dict | None, arba: dict | None) -> list[dict]:
    """Lo que se retuvo o percibió y no se depositó, en ARCA, AGIP y ARBA."""
    out = []
    for d in (sct or {}).get("deudas") or []:
        cod = re.match(r"\s*0*(\d+)", str(d.get("impuesto") or ""))
        cod = cod[1] if cod else ""
        if cod in AGENTE_ARCA and d.get("vencida") and (d.get("total") or 0) > 0 \
                and not re.search(r"INTER", str(d.get("concepto") or ""), re.I):
            out.append({"organismo": "ARCA", "concepto": f"{d.get('impuesto')} — {AGENTE_ARCA[cod]}",
                        "periodo": d.get("periodo_txt") or d.get("periodo"), "importe": d.get("total") or 0.0})
    for i in ((agip or {}).get("cct") or {}).get("impuestos") or []:
        if re.search(r"recaudaci", i.get("impuesto") or "", re.I) and (i.get("adeudado") or 0) > 0:
            out.append({"organismo": "AGIP", "concepto": i["impuesto"], "periodo": "", "importe": i["adeudado"]})
    for i in ((arba or {}).get("cuenta") or {}).get("impuestos") or []:
        if re.search(r"agentes? de recaudaci", i.get("impuesto") or "", re.I) and (i.get("deuda") or 0) > 0:
            out.append({"organismo": "ARBA", "concepto": "Agentes de Recaudación", "periodo": "", "importe": i["deuda"]})
    return out


def tipo_actividad(codigo: str) -> str:
    """Código de actividad (CLAE/NAES de 6 dígitos): servicios desde la división 49 (transporte, gastronomía,
    profesionales, etc.); bienes la producción (01-33) y el comercio (45-47); mixta energía, agua y construcción."""
    c = re.sub(r"\D", "", str(codigo or ""))[:2]
    if not c:
        return ""
    n = int(c)
    return "Servicios" if n >= 49 else "Bienes (comercio)" if 45 <= n <= 47 else "Bienes (producción)" if n <= 33 else "Mixta"


def actividad_principal(cuit: str) -> dict:
    """Actividad principal según la inscripción (Gaby 26/11/2026): Sistema Registral (orden 1) o Padrón Web de COMARB."""
    r = registral(cuit)
    acts = sorted(r.get("actividades") or [], key=lambda a: int(re.sub(r"\D", "", str(a.get("orden") or "")) or 99))
    if not acts:
        cm = _leer(_ultimo(os.path.join(DATOS, cuit, "padron_cm", "*.json"))) or {}
        acts = [a for a in cm.get("actividades") or [] if a.get("tipo") == "Principal" and not a.get("baja")]
    if not acts:
        return {}
    a = acts[0]
    return {"codigo": a.get("codigo", ""), "descripcion": a.get("descripcion", ""), "tipo": tipo_actividad(a.get("codigo"))}


def completar_desde_registral(cuit: str) -> list[str]:
    """Completa en Datos del cliente lo que esté VACÍO con lo del Sistema Registral (nunca pisa lo cargado a mano).
    Devuelve los campos completados."""
    from . import usuarios as _u
    r = registral(cuit)
    nuevos = dict(r.get("ficha") or {})
    cm = _leer(_ultimo(os.path.join(DATOS, cuit, "padron_cm", "*.json"))) or {}
    nuevos.update(cm.get("ficha") or {})                # Padrón Web de COMARB: régimen y jurisdicciones de IIBB
    py = _leer(_ultimo(os.path.join(DATOS, cuit, "pyme", "*.json"))) or {}
    if py.get("iva_diferido") is not None:               # F.1272 PyME: pago diferido del IVA = IVA a 90 días
        nuevos["iva_90_dias"] = "Sí" if py["iva_diferido"] else "No"
    elif py and py.get("tiene_f1272") is False:
        nuevos["iva_90_dias"] = "No"
    ap = actividad_principal(cuit)
    if ap.get("tipo"):
        nuevos["actividad"] = f"{ap['tipo']}: {ap['codigo']} {ap['descripcion']}".strip()
    if not (cm.get("ficha") or {}):                     # constancias de ARBA / AGIP: local si no está en Convenio
        for org in ("arba_constancia", "agip_constancia"):
            ab = _leer(_ultimo(os.path.join(DATOS, cuit, org, "*.json"))) or {}
            for k, v in (ab.get("ficha") or {}).items():
                nuevos.setdefault(k, v)
    if not nuevos:
        return []
    d = _u.datos_cliente(cuit) or {}
    hechos = [k for k, v in nuevos.items() if v and not str(d.get(k) or "").strip()]
    if not hechos:
        return []
    nuevo = {k: v for k, v in d.items() if not k.startswith("_")}
    for k in hechos:
        nuevo[k] = nuevos[k]
    _u.guardar_datos_cliente(cuit, nuevo, f"robot (Sistema Registral {r.get('fecha', '')})")
    return hechos


_ULT_COMPLETAR = [0.0]


def completar_todos(cada_seg: int = 1800) -> int:
    """Completa lo vacío de las fichas de TODOS con lo que bajaron los robots (Sistema Registral, Padrón Web,
    constancias, F.1272). Gaby, 25/11/2026. Se hace como mucho cada media hora."""
    import time
    if time.time() - _ULT_COMPLETAR[0] < cada_seg:
        return 0
    _ULT_COMPLETAR[0] = time.time()
    n = 0
    for c in _lista_clientes():
        try:
            if completar_desde_registral(c["cuit"]):
                n += 1
            completar_regimen(c["cuit"])
        except Exception:
            pass
    return n


def completar_regimen(cuit: str) -> bool:
    """Si en Datos del cliente el régimen de IIBB está vacío y se puede deducir, lo registra (no pisa lo cargado)."""
    from . import usuarios as _u
    d = _u.datos_cliente(cuit) or {}
    if (d.get("regimen_iibb") or "").strip():
        return False
    det = regimen_detectado(cuit)
    if not det:
        return False
    nuevo = {k: v for k, v in d.items() if not k.startswith("_")}
    nuevo["regimen_iibb"] = det["regimen_iibb"]
    if not (nuevo.get("jurisdicciones_iibb") or "").strip():
        nuevo["jurisdicciones_iibb"] = det["jurisdicciones_iibb"]
    _u.guardar_datos_cliente(cuit, nuevo, "robot (detectado)")
    return True


def _periodo_corto(p: str) -> str:
    m = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    return f"{m[int(p[5:7]) - 1]}-{p[2:4]}" if p and len(p) >= 7 else p


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
    try:                                    # mail modelo que arma el informe de relación D/C (24/11/2026)
        with open(os.path.join(base, "mail_relacion_dc.txt"), encoding="utf-8") as f_:
            s["mail_cliente"] = f_.read()
    except OSError:
        s["mail_cliente"] = ""
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
                       "crédito a recuperar (F.399): se calcula en la próxima corrida de Deuda histórica" if s.get("scth") else
                       "crédito a recuperar (F.399): falta leer el estado de cumplimiento (pedir 'Deuda histórica')")})
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
    s["apoc_salieron"] = apoc_salieron(cuit)
    s["rectificativas_iva"] = rectificativas_iva(cuit)
    if meses_liva or obs:
        n_obs = len((obs or {}).get("comprobantes") or [])
        _sal = s["apoc_salieron"]["lista"]
        b.append({"id": "compras", "titulo": "Compras y APOC", "valor": n_obs if obs else None,
                  "sub": ("comprobantes observados por ARCA" if obs else "conciliación con el Libro IVA")
                         + (f" · {len(_sal)} dejaron de figurar ({sum(1 for x in _sal if x['rectificado'])} rectificados)" if _sal
                            else " · nunca tuvo observados desde " + _fecha_txt(s["apoc_salieron"]["desde"]) if obs and not n_obs and s["apoc_salieron"]["desde"] else ""),
                  "color": color(False, bool(n_obs), hay=True) if obs else "gris"})
    from . import analisis
    iva = analisis.iva_mensual(cuit)
    s["iva"], s["proyeccion"] = iva, analisis.proyectar_iva(iva)
    s["iva_en_curso"] = analisis.iva_en_curso(cuit)
    _ec = s["iva_en_curso"][-1] if s["iva_en_curso"] else None
    _ec_txt = (f"{_periodo_corto(_ec['periodo'])} al {_fecha_txt(_ec['al'])}: " + (f"a pagar estimado {_pesos_txt(_ec['estimado'])}"
               if _ec["estimado"] > 0 else f"a favor estimado {_pesos_txt(-_ec['estimado'])}") + " (provisorio)") if _ec else ""
    if iva or _ec:
        rt = s["ratio"]
        # 20/11/2026: es débito fiscal ÷ crédito fiscal de IVA, NO la utilidad (la utilidad está en "Relación débito
        # crédito": ventas sin IVA − erogaciones). Mostrarla acá como "utilidad" contradecía a la otra tarjeta.
        b.append({"id": "iva", "titulo": "IVA: débito / crédito fiscal", "valor": f"{rt['ratio']:.2f}".replace(".", ",") if rt and rt["credito"] else None,
                  "sub": (f"débito fiscal ÷ crédito fiscal, {rt['meses']} meses · {rt['nivel']}"
                          + (f" · {rt['parte_sin_iva'] * 100:.0f}% de las ventas sin IVA".replace(".", ",")
                             if rt.get("parte_sin_iva", 0) >= 0.05 else "") + " · proyección") if rt else "",
                  "sub2": _ec_txt,
                  "color": {"Crítico": "rojo", "Advertencia": "amarillo", "No representativo": "gris"}.get((rt or {}).get("nivel"), "verde")})
    res = analisis.resultado_mensual(cuit)
    s["resultado"] = analisis.analizar_resultado(res)
    if res or meses_liva or any(i["tipo"] == "Relación débito/crédito" for i in inf):
        tot = (s["resultado"] or {}).get("total") or {"resultado": None}
        inc = (s["resultado"] or {}).get("incompletos") or []
        fu = _leer(os.path.join(DATOS, cuit, "conciliacion", "fuentes.json")) or {}
        s["fuentes"] = fu
        dif = [f for f in fu.get("meses") or [] if f.get("estado") == "DIFERENCIA"]
        r_pct = lambda x: f"{x * 100:.2f}%".replace(".", ",") if x is not None else "—"
        pc_ = s.get("percepciones") or {}
        sub2_perc = (f"{len(pc_['sin_comprobante'])} percepción(es) sin factura en el Libro IVA: "
                     f"{_pesos_txt(pc_.get('total_sin_comprobante') or 0)}") if pc_.get("sin_comprobante") else ""
        if inc:                                            # 20/11/2026: sin números engañosos si faltan datos
            b.append({"id": "relacion", "titulo": "Relación débito crédito", "valor": "datos incompletos",
                      "sub": f"{len(inc)} de {len(res)} meses sin alguna fuente (" + ", ".join(sorted({x for m in inc for x in m.get('faltantes', [])}))
                             + ") · ver detalle", "color": "amarillo", "sub2": sub2_perc})
        else:
            b.append({"id": "relacion", "titulo": "Relación débito crédito", "valor": tot["resultado"], "pesos": True,
                      "sub": f"{len(res)} meses · índice erogaciones/ventas {r_pct(tot.get('indice'))} · margen {r_pct(tot.get('margen'))}"
                             + (" (presta servicios: pocas compras, margen alto es normal)"
                                if (actividad_principal(cuit).get("tipo") == "Servicios") else "")
                             + (f" · {len(dif)} mes(es) no coinciden con Mis Comprobantes" if dif else ""),
                      "color": "gris" if tot["resultado"] is None else "rojo" if tot["resultado"] < 0 or dif or sub2_perc else "verde",
                      "sub2": "En rojo por: " + "; ".join(x for x in (
                                  "resultado negativo" if tot["resultado"] is not None and tot["resultado"] < 0 else "",
                                  f"{len(dif)} mes(es) en que el Libro IVA no coincide con Mis Comprobantes" if dif else "",
                                  (f"{len(pc_['sin_comprobante'])} percepción(es) sin su factura en el Libro IVA "
                                   f"({_pesos_txt(pc_.get('total_sin_comprobante') or 0)})") if pc_.get("sin_comprobante") else "") if x)
                              if tot["resultado"] is not None and (tot["resultado"] < 0 or dif or sub2_perc) else ""})
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
                  "sub2": (lambda m: (f"Monotributo cat. {m.get('categoria')}: facturado {_pesos_txt(m['facturado'])} · tope "
                                      f"{_pesos_txt(m['tope'])}" + (" — SUPERÓ EL TOPE" if m.get("supero_cartel") or (m.get("proporcion") or 0) > 1
                                                                    else f" ({m['proporcion'] * 100:.0f}%)" if m.get("proporcion") else ""))
                           if m.get("tope") and m.get("facturado") is not None else "")(cm_.get("monotributo") or {}),
                  "color": "rojo" if s["ccma_impagos"] or (cm_.get("monotributo") or {}).get("supero_cartel")
                           else "amarillo" if (cm_.get("totales") or {}).get("deudor_accesorios") else "verde"})
    if s["agip"]:
        b.append({"id": "agip", "titulo": "AGIP (Ciudad)", "valor": s["agip_deuda"] or None, "pesos": True,
                  "sub": f"{(s['agip'] or {}).get('sin_abrir') or 0} comunicaciones sin abrir · deuda",
                  "color": "rojo" if s["agip_altas"] else "amarillo" if s["agip_deuda"] >= analisis.REGLAS["deuda_minima"] else "verde"})
    if meses_liva:
        b.append({"id": "ventas_bancos", "titulo": "Ventas para bancos", "valor": None,
                  "sub": "reporte mensual desde el Portal IVA (Excel / PDF)", "color": "gris"})
    b.append({"id": "informes", "titulo": "Informes Excel", "valor": len(inf), "sub": "para bajar", "color": "gris"})
    # 20/11/2026: todos los clientes muestran las MISMAS tarjetas en el MISMO orden; si todavía no hay datos de algo,
    # la tarjeta aparece en gris diciendo por qué (antes desaparecía y cada ficha se veía distinta).
    falta = {"por_vencer": ("Por vencer", "falta leer Cuentas Tributarias"),
             "iibb": ("Ingresos Brutos", "falta la clave o los datos de Convenio Multilateral / ARBA"),
             "compras": ("Compras y APOC", "se lee en la corrida completa (Libro IVA / Nuestra Parte)"),
             "iva": ("IVA: débito / crédito fiscal", "falta el Libro IVA (monotributo o sin presentar)"),
             "relacion": ("Relación débito crédito", "falta el Libro IVA o el F.931"),
             "fiscalizaciones": ("Fiscalizaciones", "se lee en la corrida completa"),
             "historica": ("Deuda histórica", "se lee en la corrida completa (estado de cumplimiento)"),
             "ccma": ("Autónomos / Monotributo", "se lee en la corrida completa (CCMA)"),
             "agip": ("AGIP (Ciudad)", "falta cargar la Clave Ciudad de AGIP"),
             "ventas_bancos": ("Ventas para bancos", "falta el Libro IVA del Portal IVA")}
    hay = {x["id"] for x in b}
    try:
        from . import usuarios as _u
        if "AGIP" in ((_u.datos_cliente(cuit) or {}).get("no_corresponde") or "").upper():
            falta.pop("agip", None)                    # local de ARBA: no se muestra AGIP "pendiente de configurar"
    except Exception:
        pass
    mono = (s.get("categoria") or "").startswith("sin Portal IVA")
    for id_, (tit, sub) in falta.items():
        if id_ not in hay and mono and id_ in ("iva", "relacion", "ventas_bancos"):
            # 22/11/2026 (Gándara, monotributista): sin Libro IVA no es "pendiente de configurar"
            b.append({"id": id_, "titulo": tit, "valor": "No corresponde", "sub": "monotributo / exento: no tiene Libro IVA",
                      "color": "gris", "vacia": True})
            continue
        if id_ not in hay:
            # pedido 20/11/2026: lo que no está configurado va en ROJO y dice "Pendiente de configurar"
            b.append({"id": id_, "titulo": tit, "valor": "Pendiente de configurar", "sub": sub, "color": "rojo", "vacia": True})
    orden = ["deuda", "por_vencer", "planes", "vencimientos", "ddjj", "notificaciones", "iibb", "compras", "iva", "relacion",
             "fiscalizaciones", "historica", "ccma", "agip", "ventas_bancos", "informes"]
    b.sort(key=lambda x: orden.index(x["id"]) if x["id"] in orden else len(orden))
    fl = fallas(cuit)                                  # lo que falló en la última corrida, en el botón que corresponde
    for x in b:
        x["fallas"] = [f for f in fl if f["boton"] == x["id"]]
    s["fallas_claves"] = [f for f in fl if f["boton"] == "claves"]
    s["fallas"] = fl
    s["botones"] = b
    return s


def _anio(periodo) -> int | None:
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})", str(periodo or ""))
    return int(m[1]) if m else None


def items_alerta(f: dict, tipo: str) -> list[tuple]:
    """Obligaciones (impuesto|concepto|período, año) que forman una alerta de deuda o de falta de presentación."""
    if tipo == "Deuda vencida":
        lista = f.get("deudas_vencidas") or []
    elif tipo == "Falta de presentación":
        lista = (f.get("sct") or {}).get("ddjj_pendientes") or []
    elif tipo.startswith("Deuda en Cuentas Tributarias"):
        lista = (f.get("scth") or {}).get("deudas") or []
    else:
        return []
    return [(f"{d.get('impuesto')}|{d.get('concepto') or ''}|{d.get('periodo')}", d.get("anio") and int(d["anio"]) or _anio(d.get("periodo")))
            for d in lista]


def alertas_del_dia(solo: set | None = None) -> list[dict]:
    """Lo urgente (ALTA) de todos los clientes, para la pantalla 'Alertas del día'."""
    out = []
    for c in lista_clientes(solo):
        f = ficha(c["cuit"])
        al = [a for a in f["alertas"] if a.get("prioridad") in ("URGENTE", "ALTA")]
        al += [a for a in ((f["arba_dfe"] or {}).get("alertas") or []) if a.get("prioridad") in ("URGENTE", "ALTA")]
        # Convenio: ya va como "Deuda histórica para revisar" mientras el encargado no la marque vista
        if f.get("ratio") and f["ratio"]["nivel"] == "Crítico" and f["ratio"]["meses"] >= 6:
            al.append({"prioridad": "ALTA", "tipo": "Relación débito/crédito crítica",
                       "texto": f"D/C {f['ratio']['ratio']:.2f} en {f['ratio']['meses']} meses (menos de 0,8)".replace(".", ",", 1)})
        al = [{**a, "tipo": a.get("tipo") or a.get("Tipo de alerta", ""), "texto": a.get("texto") or a.get("Acción", "")}
              for a in al]
        for a in al:                                   # 20/11/2026: qué períodos forman la alerta (descartes por período)
            it = items_alerta(f, a["tipo"])
            if it:
                a["items"] = it
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


def corrida_en_curso() -> dict | None:
    """Corrida programada de todos los clientes que está corriendo ahora (la publica robots/correr.py). 21/11/2026."""
    d = _leer(os.path.join(PUBLICO, "corrida_en_curso.json"))
    if not isinstance(d, dict):
        return None
    try:
        os.kill(int(d.get("pid") or 0), 0)
    except ProcessLookupError:
        return None                                 # el proceso ya no existe: quedó el archivo de una corrida cortada
    except (PermissionError, ValueError, OSError):
        pass                                        # existe pero es de otro usuario (robot): está corriendo
    if d.get("solo_fallidos"):
        d["nombre"] = "Repechaje (clientes con error en la semana)"
    elif d.get("fin_de_semana") or d.get("modo") == "completo":
        d["nombre"] = "Corrida completa de fin de semana"
    elif d.get("modo") == "diaria":
        d["nombre"] = "Corrida diaria liviana"
    else:
        d["nombre"] = f"Corrida de todos los clientes ({d.get('modo') or d.get('robot')})"
    try:
        ini = datetime.fromisoformat(d["inicio"])
        if d.get("horas"):
            d["termina_a_mas_tardar"] = (ini + timedelta(hours=float(d["horas"]))).isoformat(timespec="minutes")
    except Exception:
        pass
    return d


# ---------------------------------------------------------------- fallas de las corridas, para corregir (22/11/2026)
# Pedido de Gaby: en cada botón de la ficha, en letra chica (como el renglón del F.399), lo que falló en la última
# corrida y qué hay que hacer; y la lista de todos en Más -> Robots.
PARTE_BOTON = {"cuentas_tributarias": "deuda", "sct": "deuda", "mis_facilidades": "planes", "ccma": "ccma",
               "sct_historico": "historica", "ddjj_presentadas": "ddjj", "dfe": "notificaciones", "arba_dfe": "notificaciones",
               "sifere": "iibb", "arba": "iibb", "f931": "relacion", "libro_iva": "iva", "observados": "compras",
               "fiscalizaciones": "fiscalizaciones", "mis_comprobantes": "relacion", "mis_retenciones": "relacion",
               "agip": "agip", "informes": "informes", "clave": "claves", "todo": "claves"}
NOMBRE_PARTE = {"cuentas_tributarias": "Cuentas Tributarias", "mis_facilidades": "Mis Facilidades", "ccma": "CCMA",
                "sct_historico": "Deuda histórica", "ddjj_presentadas": "DDJJ presentadas", "dfe": "Ventanilla ARCA",
                "arba_dfe": "ARBA DFE", "sifere": "SIFERE", "arba": "ARBA", "f931": "F.931", "libro_iva": "Libro IVA",
                "observados": "Compras observadas", "fiscalizaciones": "Fiscalizaciones", "mis_comprobantes": "Mis Comprobantes",
                "mis_retenciones": "Mis Retenciones", "agip": "AGIP", "informes": "Informes", "clave": "Ingreso a ARCA",
                "todo": "Ingreso a ARCA"}


def que_hacer(msg: str) -> str:
    m = msg or ""
    if re.search(r"sin CIT", m, re.I):
        return "cargar la CIT de ARBA en 🔐 Claves"
    if re.search(r"sin Clave Ciudad", m, re.I):
        return "cargar la Clave Ciudad de AGIP en 🔐 Claves"
    if re.search(r"rechaz|clave inv[aá]lida|ClaveInvalida|contrase", m, re.I):
        return "la clave no anda: cargar la nueva en 🔐 Claves"
    if re.search(r"SinRepresentado|no (est[aá]|figura) entre|representad|delegad|apoderad", m, re.I):
        return "revisar en ARCA que el estudio tenga la representación / el servicio delegado de este cliente"
    if re.search(r"RequiereIntervencion|no est[aá] habilitado|habilitar", m, re.I):
        return ("habilitar el servicio en ARCA: con la clave propia del cliente, Administrador de relaciones → "
                "Adherir servicio; si entramos por representación, que el cliente se lo delegue al estudio")
    if re.search(r"captcha", m, re.I):
        return "ARCA pidió captcha: se reintenta solo en la próxima corrida"
    if re.search(r"Timeout|corte|SesionPerdida|net::|ERR_|no respond|Trabada|cargando", m, re.I):
        return "falla de la página del organismo: se reintenta en el repechaje del domingo; si se repite, avisar"
    return "avisar para revisar el robot (copiar este texto)"


def claves_al_dia(cuit: str) -> dict:
    """Por organismo, qué pasa con la clave (sin mostrar valores):
    {"ARCA": {"estado": "cargada"|"pendiente"|"rechazada"|"invalida", "fecha", "texto"}}.
    "pendiente" = cargada en la pantalla, el robot todavía no la tomó de la bandeja."""
    out: dict[str, dict] = {}
    c = next((x for x in _lista_clientes() if x.get("cuit") == cuit), {}) or {}
    for a in c.get("accesos") or []:
        org, est, f = a.get("organismo"), a.get("estado") or "", a.get("actualizado") or ""
        if est == "Clave inválida":
            out[org] = {"estado": "invalida", "fecha": f, "texto": f"la clave de {org} no anda (probada el {f[:10]}): cargar la nueva"}
        else:
            out[org] = {"estado": "cargada", "fecha": f, "texto": f"clave de {org} cargada el {f[:10]} ({est or 'sin verificar'})"}
    try:
        from . import claves as _cl
        for r in _cl.resultados():                    # lo más nuevo primero
            if r.get("cuit") != cuit or r.get("organismo") not in ("ARCA", "ARBA", "AGIP"):
                continue
            org = r["organismo"]
            if r.get("estado") == "rechazado" and (r.get("fecha") or "") >= (out.get(org, {}).get("fecha") or ""):
                out[org] = {"estado": "rechazada", "fecha": r.get("fecha", ""),
                            "texto": f"la clave de {org} cargada el {(r.get('fecha') or '')[:10]} no se pudo guardar "
                                     f"({r.get('motivo') or 'sin detalle'}): volver a cargarla"}
        for p in _cl.pendientes():
            if p.get("cuit") == cuit and p.get("organismo") in ("ARCA", "ARBA", "AGIP"):
                out[p["organismo"]] = {"estado": "pendiente", "fecha": p.get("fecha", ""),
                                       "texto": f"clave de {p['organismo']} cargada el {(p.get('fecha') or '')[:16].replace('T', ' ')}: "
                                                "el robot la toma en unos minutos"}
    except Exception:
        pass
    return out


def fallas(cuit: str) -> list[dict]:
    """Lo que falló o falta en las últimas corridas del cliente: [{parte, nombre, boton, fecha, texto, que_hacer}].
    Se recorren las corridas 'todo' de las últimas semanas: una parte que salió bien después ya no figura."""
    base = os.path.join(DATOS, cuit)
    estado: dict[str, tuple[str, str] | None] = {}
    for ruta in sorted(glob.glob(os.path.join(base, "corrida_todo_*.json")))[-12:]:
        d = _leer(ruta) or {}
        f = d.get("fecha") or ""
        err = d.get("errores") or {}
        corridas = [k for k in ("mis_comprobantes", "f931", "sifere", "libro_iva", "observados", "arba", "arba_dfe", "agip",
                                "fiscalizaciones", "ccma", "sct_historico", "mis_retenciones", "dfe") if d.get(k)]
        corridas += ["cuentas_tributarias"] + (["mis_facilidades"] if d.get("modo") != "diaria" else [])
        for k in corridas:
            if k not in err:
                estado[k] = None
        for k, v in err.items():
            estado[k] = (f, str(v))
        if d.get("arba") == "sin CIT cargada":
            estado["arba"] = (f, "sin CIT cargada")
        if str(d.get("agip", "")).startswith("sin Clave Ciudad"):
            estado["agip"] = (f, "sin Clave Ciudad cargada")
    try:                                               # Convenio Multilateral: las DJ locales de ARBA no corresponden
        from . import usuarios as _u
        if "convenio" in str((_u.datos_cliente(cuit) or {}).get("regimen_iibb") or "").lower():
            estado.pop("arba", None)
    except Exception:
        pass
    try:                                               # ingreso a ARCA rechazado: queda en el registro de ejecuciones
        with open(REGISTRO, encoding="utf-8") as fh:
            ult = None
            for l in fh.readlines()[-3000:]:
                try:
                    e = json.loads(l)
                except ValueError:
                    continue
                if e.get("cuit") == cuit and e.get("robot") not in ("arba", "agip"):
                    ult = e
        if ult and ult.get("estado") in ("Clave inválida", "Requiere intervención"):
            estado["clave"] = ((ult.get("fecha") or "")[:10], f"{ult['estado']}: {ult.get('detalle') or ''}")
    except OSError:
        pass
    # Clave cargada DESPUÉS del aviso (25/11/2026, Gabriel cargó AGIP/ARBA de Nabajuma y seguía diciendo "sin clave"):
    # el aviso viene de la última corrida; si la clave ya está, deja de ser una falla.
    al_dia = claves_al_dia(cuit)
    for k, org in (("arba", "ARBA"), ("arba_dfe", "ARBA"), ("agip", "AGIP"), ("clave", "ARCA")):
        v = estado.get(k)
        a = al_dia.get(org) or {}
        if v and a.get("estado") in ("cargada", "pendiente") and (a.get("fecha") or "")[:10] >= (v[0] or "")[:10] \
                and (k == "clave" or re.search(r"sin CIT|sin Clave Ciudad|clave inv|rechaz", v[1], re.I)):
            estado[k] = None
    try:                                               # organismos que no le corresponden (22/11/2026)
        from . import usuarios as _u
        nc = {x.strip().upper() for x in ((_u.datos_cliente(cuit) or {}).get("no_corresponde") or "").split(",") if x.strip()}
    except Exception:
        nc = set()
    for k in [k for k in estado if (k in ("arba", "arba_dfe") and "ARBA" in nc) or (k == "agip" and "AGIP" in nc)]:
        estado.pop(k)
    out = []
    capt = sorted(glob.glob(os.path.join(base, "capturas", "*.png")), key=os.path.getmtime, reverse=True)
    for k, v in estado.items():
        if not v:
            continue
        boton = "claves" if re.search(r"rechaz|clave inv|sin CIT|sin Clave Ciudad", v[1], re.I) else PARTE_BOTON.get(k, "informes")
        texto = re.sub(r"\s+", " ", v[1])
        # la causa entre paréntesis al final ("no aparecieron los resultados (Debe ingresar...)") va adelante
        m = re.search(r"\(([^()]{8,})\)\s*$", texto)
        corto = (m[1] + " — " + texto[:m.start()]) if m else texto
        pref = {"mis_retenciones": "mis_retenciones", "arba": "error_arba", "arba_dfe": "error_arba_dfe", "agip": "error_agip"}.get(k, f"error_{k}")
        cap = next((os.path.basename(c) for c in capt if os.path.basename(c).startswith(pref)
                    and date.fromtimestamp(os.path.getmtime(c)).isoformat() >= (v[0] or "")[:10]), None)
        out.append({"parte": k, "nombre": NOMBRE_PARTE.get(k, k), "boton": boton, "fecha": v[0],
                    "texto": corto[:300], "que_hacer": que_hacer(v[1]), "captura": cap})
    return sorted(out, key=lambda x: x["nombre"])


def fallas_todos(solo: set | None = None) -> list[dict]:
    out = []
    for c in lista_clientes(solo):
        for f in fallas(c["cuit"]):
            out.append({**f, "cuit": c["cuit"], "razon_social": c.get("razon_social") or ""})
    return out
