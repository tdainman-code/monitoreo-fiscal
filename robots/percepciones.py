"""Percepciones informadas por los agentes vs. comprobantes del Libro IVA Digital (Portal IVA). Gaby, 21/11/2026.

Las percepciones de IVA entran solas en la DDJJ (importación automática); si la factura de esa compra NO está en el
Libro IVA, ni el gasto ni el crédito fiscal se computaron: hay que buscar el comprobante. Lo mismo vale para las
percepciones de Ingresos Brutos (ARBA, AGIP, SIFERE): se agregan acá cuando se relevan esas pantallas.

Entrada:  DATOS/<cuit>/mis_retenciones/<fecha>.json   (robot_mis_retenciones)
          DATOS/<cuit>/libro_iva/AAAA-MM.json           (robot_libro_iva: comprobantes_compras)
Salida:   DATOS/<cuit>/conciliacion/percepciones.json   (lo muestra la Relación débito crédito)

Búsqueda de cada percepción: en el Libro IVA de compras del mes de la factura y de los dos siguientes (a veces se
registra después), mismo CUIT del agente y mismo número de comprobante (últimos 8 dígitos); si el número no coincide,
mismo CUIT y misma fecha. Si falta el Libro IVA de ese mes: "no comparable" (no se acusa de faltante).
"""
from __future__ import annotations

import glob
import json
import os
import re
from datetime import date

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
MESES_DESPUES = 2


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, TypeError):
        return None


def _ultimo(carpeta: str):
    r = sorted(x for x in glob.glob(os.path.join(carpeta, "*.json")) if not os.path.basename(x).startswith("_"))
    return r[-1] if r else None


def _fecha_iso(t: str) -> str:
    t = (t or "").strip()
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", t)
    if m:
        return f"{m[3]}-{m[2]}-{m[1]}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", t)
    return m[0] if m else ""


def _mas_meses(mes: str, n: int) -> str:
    a, m = int(mes[:4]), int(mes[5:7]) + n
    a += (m - 1) // 12
    return f"{a}-{(m - 1) % 12 + 1:02d}"


def _libros(cuit: str) -> dict[str, list[dict]]:
    out = {}
    for ruta in glob.glob(os.path.join(DATOS, cuit, "libro_iva", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        d = _leer(ruta)
        if isinstance(d, dict) and isinstance(d.get("comprobantes_compras"), list):
            out[os.path.basename(ruta)[:7]] = d["comprobantes_compras"]
    return out


def _numero(c: str) -> int:
    d = re.sub(r"\D", "", str(c or ""))
    return int(d[-8:]) if d else 0


def buscar(p: dict, libros: dict[str, list[dict]]) -> tuple[str, str | None]:
    """('en_libro', mes) | ('no_comparable', mes) | ('sin_comprobante', mes)."""
    f = _fecha_iso(p.get("fecha_comprobante") or p.get("fecha"))
    if not f:
        return "no_comparable", None
    mes = f[:7]
    meses = [_mas_meses(mes, k) for k in range(MESES_DESPUES + 1)]
    if mes not in libros:
        return "no_comparable", mes
    num = _numero(p.get("comprobante"))
    txt = re.sub(r"[^\w]", "", str(p.get("comprobante") or "")).upper()
    aduana = bool(p.get("aduana")) or bool(re.fullmatch(r"\d{5}[A-Z]{2}\d{6,8}[A-Z]?", txt))   # n° de despacho
    for m in meses:
        for c in libros.get(m, []):
            if aduana:                                 # despacho: por su número (el CUIT del libro puede ser el de la Aduana)
                if txt and txt == str(c.get("numero_txt") or "").upper():
                    return "en_libro", m
                if int(c.get("tipo") or 0) == 66 and _fecha_iso(c.get("fecha")) == f:
                    return "en_libro", m
                continue
            if re.sub(r"\D", "", str(c.get("cuit") or "")) != p["agente"]:
                continue
            if num and int(c.get("numero") or 0) == num:
                return "en_libro", m
            if _fecha_iso(c.get("fecha")) == f:
                return "en_libro", m
    return "sin_comprobante", mes


def _pesos(x: float) -> str:
    return f"$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def cruzar(cuit: str, hoy: date | None = None) -> dict | None:
    hoy = hoy or date.today()
    mr = _leer(_ultimo(os.path.join(DATOS, cuit, "mis_retenciones")))
    # IIBB CABA: AGIP Gestión-AR (robot_agip, solapa Percepciones), en el resultado de AGIP más nuevo que la traiga
    agip = None
    for ruta in sorted(glob.glob(os.path.join(DATOS, cuit, "agip", "[0-9]*", "resultado.json")), reverse=True):
        d = _leer(ruta)
        if isinstance(d, dict) and d.get("percepciones") is not None:
            agip = d
            break
    # IIBB Buenos Aires: ARBA, Deducciones -> Descarga para Importar (robot_arba_dfe)
    arba = None
    for ruta in sorted(glob.glob(os.path.join(DATOS, cuit, "arba_dfe", "[0-9]*", "resultado.json")), reverse=True):
        d = _leer(ruta)
        if isinstance(d, dict) and d.get("percepciones") is not None:
            arba = d
            break
    if not isinstance(mr, dict) and not agip and not arba:
        return None
    mr = mr if isinstance(mr, dict) else {}
    filas = list(mr.get("filas") or [])
    for x in (agip or {}).get("percepciones") or []:
        filas.append(dict(x, impuesto="IIBB CABA", fuente="AGIP · Gestión-AR"))
    for x in (arba or {}).get("percepciones") or []:
        filas.append(dict(x, impuesto="IIBB Buenos Aires", fuente="ARBA · Deducciones"))
    libros = _libros(cuit)
    sin, nc, ok = [], [], 0
    despachos: dict[str, dict] = {}                   # un despacho trae percepción de IVA y de Ganancias: se cuenta una vez
    for p in filas:
        if not str(p.get("operacion", "")).startswith("PERCEP"):
            continue                                   # las retenciones son sobre cobros: no van contra compras
        imp = {"767": "IVA", "216": "IVA", "217": "Ganancias"}.get(str(p.get("impuesto")), str(p.get("impuesto")))
        if p.get("aduana"):
            k = p.get("comprobante") or f"{p.get('fecha_comprobante')}"
            if k in despachos:
                despachos[k]["impuesto"] = " + ".join(sorted({*despachos[k]["impuesto"].split(" + "), imp}))
                despachos[k]["importe_" + imp.lower()] = round(despachos[k].get("importe_" + imp.lower(), 0) + (p.get("importe") or 0), 2)
                continue
        estado, mes = buscar(p, libros)
        if estado == "en_libro":
            ok += 1
            continue
        fila = {"impuesto": imp, "fuente": p.get("fuente") or ("ARCA · Aduana (despacho de importación)" if p.get("aduana")
                                                              else "ARCA · Mis Retenciones"),
                "agente": p["agente"], "regimen": p.get("regimen"),
                "fecha_comprobante": p.get("fecha_comprobante"), "comprobante": p.get("comprobante"),
                "desc_comprobante": "Despacho" if p.get("aduana") else p.get("desc_comprobante"),
                "importe": p.get("importe") or 0.0, "mes": mes}
        if p.get("aduana"):
            fila["importe_" + imp.lower()] = fila["importe"]
            despachos[p.get("comprobante") or f"{p.get('fecha_comprobante')}"] = fila
        (sin if estado == "sin_comprobante" else nc).append(fila)
    for x in sin + nc:                                # importe del despacho: el de IVA (crédito fiscal) si lo hay
        if "importe_iva" in x or "importe_ganancias" in x:
            x["importe"] = x.get("importe_iva", 0.0) + x.get("importe_ganancias", 0.0)
    sin.sort(key=lambda x: (x["mes"] or "", x["agente"]), reverse=True)
    meses_nc = sorted({x["mes"] for x in nc if x["mes"]})
    r = {"cuit": cuit, "fecha": hoy.isoformat(), "fecha_mis_retenciones": mr.get("fecha"), "desde": mr.get("desde"),
         "hasta": mr.get("hasta"), "fecha_agip": (agip or {}).get("fecha"), "fecha_arba": (arba or {}).get("fecha"), "en_libro": ok, "sin_comprobante": sin,
         "total_sin_comprobante": round(sum(x["importe"] for x in sin), 2),
         "no_comparables": len(nc), "meses_sin_libro": meses_nc}
    al = []
    if sin:
        agentes = len({x["agente"] for x in sin})
        n_desp = sum(1 for x in sin if x["desc_comprobante"] == "Despacho")
        al.append({"prioridad": "ALTA", "tipo": "Percepciones sin factura en el Libro IVA",
                   "texto": f"{len(sin)} percepción(es) por {_pesos(r['total_sin_comprobante'])} de {agentes} agente(s)"
                            + (f" (incluye {n_desp} despacho(s) de importación)" if n_desp else "")
                            + " sin el comprobante en el Libro IVA: ni el gasto ni el crédito fiscal se computaron. "
                              "Buscar los comprobantes."})
    r["alertas"] = al
    d = os.path.join(DATOS, cuit, "conciliacion")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "percepciones.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    return r
