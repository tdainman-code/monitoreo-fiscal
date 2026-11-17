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


def lista_clientes() -> list[dict]:
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
    r["cuotas_impagas"] = sum(p["vencidas_impagas"] for p in vig) if mf else None
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
    r["agip_altas"] = (agip or {}).get("altas_sin_abrir") or 0
    r["agip_deuda"] = ((agip or {}).get("deuda") or {}).get("total") or 0.0
    r["fiscalizaciones"] = (len((fisc or {}).get("en_curso") or []) + len((fisc or {}).get("siace") or [])
                            + len((fisc or {}).get("fiscalizacion_electronica") or []) + len((agip or {}).get("fiscalizacion") or []))
    r["ratio"] = analisis.ratio_dc(analisis.iva_mensual(cuit))
    r["alertas"] += ((agip or {}).get("alertas") or []) + ((fisc or {}).get("alertas") or [])
    ratio_mal = r["ratio"]["nivel"] if r["ratio"] and r["ratio"]["meses"] >= 6 else ""
    minima = analisis.REGLAS["deuda_minima"]
    if not sit and not dfe and not agip and not fisc:
        r["semaforo"], r["motivo"] = "gris", "Sin datos todavía"
    elif (r["cuotas_impagas"] or r["ddjj"] or r["dfe_altas"] or r["caducos"] or r["deuda_cm"] or r["arba_altas"]
          or r["agip_altas"] or r["fiscalizaciones"] or ratio_mal == "Crítico"):
        r["semaforo"] = "rojo"
        r["motivo"] = ", ".join(x for x in [
            f"{r['cuotas_impagas']} cuota(s) impaga(s)" if r["cuotas_impagas"] else "",
            f"{r['ddjj']} DDJJ pendiente(s)" if r["ddjj"] else "",
            f"{r['dfe_altas']} notificación(es) importante(s) sin abrir" if r["dfe_altas"] else "",
            f"{r['caducos']} plan(es) caduco(s)" if r["caducos"] else "",
            "deuda de Convenio" if r["deuda_cm"] else "",
            f"{r['arba_altas']} aviso(s) de ARBA" if r["arba_altas"] else "",
            f"{r['agip_altas']} aviso(s) de AGIP" if r["agip_altas"] else "",
            f"{r['fiscalizaciones']} fiscalización(es)/control(es) abiertos" if r["fiscalizaciones"] else "",
            f"relación D/C crítica ({r['ratio']['ratio']:.2f})".replace(".", ",") if ratio_mal == "Crítico" else ""] if x)
    elif ((r["deuda_vencida"] or 0) >= minima or r["agip_deuda"] >= minima or r["cuotas_15"] or r["errores"]
          or ratio_mal == "Advertencia"):
        r["semaforo"] = "amarillo"
        r["motivo"] = ", ".join(x for x in [
            "deuda vencida" if (r["deuda_vencida"] or 0) >= minima else "",
            "deuda en AGIP" if r["agip_deuda"] >= minima else "",
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


def agenda(dias: int = 15) -> list[dict]:
    hoy = date.today()
    lim = hoy + timedelta(days=dias)
    nombres = {c["cuit"]: c.get("razon_social") or "" for c in lista_clientes()}
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
                if c["situacion"] in ("Vencida impaga", "Vencida sin pago informado"):
                    out.append({"fecha": f, "cuit": cuit, "nombre": nom, "que": f"Plan {p['numero']} cuota {c['cuota']}",
                                "detalle": c["situacion"], "importe": c.get("total_2") or c.get("total_1"), "tipo": "impaga"})
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
                    "responsable": c.get("responsable", ""), "estado": c.get("notificado") or "SIN ABRIR",
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
        return (orden.get(n["importancia"], 1), -f.toordinal())
    import hashlib
    for n in out:
        n["id"] = hashlib.sha1(f"{base}|{n['origen']}|{n['fecha']}|{n['asunto']}".encode()).hexdigest()[:16]
    return sorted(out, key=clave), arba


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
    n_obl = len((sct or {}).get("deudas") or [])
    b.append({"id": "deuda", "titulo": "Deuda ARCA", "valor": s["deuda_vencida"], "pesos": True,
              "sub": f"{n_obl} obligaciones" if sct else "sin datos", "color": color((s["deuda_vencida"] or 0) > 0, hay=bool(sct))})
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
                          if cm else "ARBA"), "color": color(bool((cm or {}).get("deuda_total")), hay=bool(cm))})
    if meses_liva or any(i["tipo"] == "Relación débito/crédito" for i in inf):
        b.append({"id": "relacion", "titulo": "Relación D/C (Excel)", "valor": None,
                  "sub": f"{meses_liva} meses desde Libro IVA" if meses_liva else "desde Mis Comprobantes", "color": "gris"})
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
        b.append({"id": "iva", "titulo": "Débito / crédito y proyección", "valor": f"{rt['ratio']:.2f}".replace(".", ",") if rt and rt["credito"] else None,
                  "sub": f"relación D/C {rt['meses']} meses · {rt['nivel']}" if rt else "",
                  "color": {"Crítico": "rojo", "Advertencia": "amarillo"}.get((rt or {}).get("nivel"), "verde")})
    res = analisis.resultado_mensual(cuit)
    s["resultado"] = analisis.analizar_resultado(res)
    if res:
        tot = s["resultado"]["total"]
        b.append({"id": "resultado", "titulo": "Resultado mensual", "valor": tot["resultado"], "pesos": True,
                  "sub": f"{len(res)} meses · ventas − compras − sueldos − F.931",
                  "color": "rojo" if tot["resultado"] < 0 else "amarillo" if s["resultado"]["incompletos"] else "verde"})
    if s["fisc"] or (s["agip"] or {}).get("fiscalizacion") is not None:
        b.append({"id": "fiscalizaciones", "titulo": "Fiscalizaciones", "valor": s["fiscalizaciones"],
                  "sub": "ARCA (OI, SIACE) y AGIP", "color": "rojo" if s["fiscalizaciones"] else "verde"})
    if s["agip"]:
        b.append({"id": "agip", "titulo": "AGIP (Ciudad)", "valor": s["agip_deuda"] or None, "pesos": True,
                  "sub": f"{(s['agip'] or {}).get('sin_abrir') or 0} comunicaciones sin abrir · deuda",
                  "color": "rojo" if s["agip_altas"] else "amarillo" if s["agip_deuda"] >= analisis.REGLAS["deuda_minima"] else "verde"})
    b.append({"id": "informes", "titulo": "Informes Excel", "valor": len(inf), "sub": "para bajar", "color": "gris"})
    s["botones"] = b
    return s


def alertas_del_dia() -> list[dict]:
    """Lo urgente (ALTA) de todos los clientes, para la pantalla 'Alertas del día'."""
    out = []
    for c in lista_clientes():
        f = ficha(c["cuit"])
        al = [a for a in f["alertas"] if a.get("prioridad") == "ALTA"]
        al += [a for a in ((f["arba_dfe"] or {}).get("alertas") or []) if a.get("prioridad") == "ALTA"]
        al += [a for a in ((f["cm"] or {}).get("alertas") or []) if a.get("prioridad") == "ALTA"]
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
def cartera() -> list[dict]:
    """Ficha completa de cada cliente (para las pantallas que listan a todos)."""
    out = []
    for c in lista_clientes():
        try:
            f = ficha(c["cuit"])
        except Exception:                                    # un cliente con datos rotos no tira abajo la pantalla
            continue
        out.append({"cuit": c["cuit"], "nombre": c.get("razon_social") or cuit_fmt(c["cuit"]), "f": f})
    return out
