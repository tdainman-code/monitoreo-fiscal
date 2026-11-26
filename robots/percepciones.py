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


DIAS_MISMO_COMPROBANTE = 45


def _dias(a: str, b: str) -> int | None:
    try:
        return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)
    except (TypeError, ValueError):
        return None


def buscar(p: dict, libros: dict[str, list[dict]]) -> tuple[str, str | None, str]:
    """('en_libro', mes, nota) | ('no_comparable', mes, nota) | ('sin_comprobante', mes, nota).
    22/11/2026 (Gaby): es el MISMO comprobante si coinciden proveedor, número Y fecha (hasta 45 días de diferencia, por
    la fecha de registración). Mismo número con otra fecha es OTRO comprobante: no se da por computado y se avisa para
    revisar (puede ser uno parecido que se omitió, o uno duplicado). Sin número, alcanza proveedor y misma fecha."""
    f = _fecha_iso(p.get("fecha_comprobante") or p.get("fecha"))
    if not f:
        return "no_comparable", None, ""
    mes = f[:7]
    meses = [_mas_meses(mes, k) for k in range(MESES_DESPUES + 1)]
    if mes not in libros:
        return "no_comparable", mes, ""
    num = _numero(p.get("comprobante"))
    txt = re.sub(r"[^\w]", "", str(p.get("comprobante") or "")).upper()
    aduana = bool(p.get("aduana")) or bool(re.fullmatch(r"\d{5}[A-Z]{2}\d{6,8}[A-Z]?", txt))   # n° de despacho
    parecido = ""
    for m in meses:
        for c in libros.get(m, []):
            fc = _fecha_iso(c.get("fecha"))
            d = _dias(fc, f)
            if aduana:                                 # despacho: por su número (el CUIT del libro puede ser el de la Aduana)
                if txt and txt == str(c.get("numero_txt") or "").upper():
                    if d is None or d <= DIAS_MISMO_COMPROBANTE:
                        return "en_libro", m, ""
                    parecido = f"en el Libro IVA de {m[5:]}/{m[:4]} está el despacho {txt} con fecha {fc}: revisar si es el mismo"
                elif not txt and int(c.get("tipo") or 0) == 66 and fc == f:
                    return "en_libro", m, ""
                continue
            if re.sub(r"\D", "", str(c.get("cuit") or "")) != p["agente"]:
                continue
            if num and int(c.get("numero") or 0) == num:
                if d is None or d <= DIAS_MISMO_COMPROBANTE:
                    return "en_libro", m, ""
                parecido = (f"en el Libro IVA de {m[5:]}/{m[:4]} hay un comprobante de este proveedor con el mismo número "
                            f"pero fecha {fc}: es otro comprobante, revisar si este se omitió o está duplicado")
            elif fc == f and (not num or re.search(r"SERV|OTRO", str(p.get("desc_comprobante") or ""), re.I)):
                # sin número, o servicios públicos / "otro comprobante" (su número viene en otro formato en el Libro
                # IVA): mismo proveedor y misma fecha
                return "en_libro", m, ""
    return "sin_comprobante", mes, parecido


def _unir_por_comprobante(filas: list[dict]) -> list[dict]:
    """22/11/2026 (Gaby): la misma factura suele tener percepción de IVA (ARCA) y de IIBB (ARBA / AGIP). Se muestra una
    vez, con los impuestos juntos, el importe de cada uno y el nombre del comprobante más claro (ARBA dice FACTURA o
    RECIBO donde ARCA a veces dice OTRO COMPROBANTE)."""
    out, idx = [], {}
    for x in filas:
        n = _numero(x.get("comprobante"))
        # mismo proveedor, número, signo y MES del comprobante (mismo número en otro mes = otro comprobante)
        k = (x.get("agente"), n, (x.get("importe") or 0) < 0, (_fecha_iso(x.get("fecha_comprobante")) or "")[:7]) if n else None
        if k is None or k not in idx:
            y = dict(x)
            y["por_impuesto"] = {x["impuesto"]: round(x.get("importe") or 0.0, 2)}
            y["fuentes"] = [x.get("fuente")]
            if k is not None:
                idx[k] = len(out)
            out.append(y)
            continue
        y = out[idx[k]]
        y["por_impuesto"][x["impuesto"]] = round(y["por_impuesto"].get(x["impuesto"], 0.0) + (x.get("importe") or 0.0), 2)
        y["impuesto"] = " + ".join(y["por_impuesto"])
        y["importe"] = round(sum(y["por_impuesto"].values()), 2)
        if x.get("fuente") not in y["fuentes"]:
            y["fuentes"].append(x.get("fuente"))
        y["fuente"] = " · ".join(f for f in y["fuentes"] if f)
        if (not y.get("desc_comprobante") or re.search(r"OTRO", y.get("desc_comprobante") or "", re.I)) and x.get("desc_comprobante"):
            y["desc_comprobante"] = x["desc_comprobante"]
    return out


def _marcar_mis_comprobantes(cuit: str, filas: list[dict]) -> None:
    """¿El comprobante está en Mis Comprobantes (recibidos)? Si está, existe y solo falta cargarlo en el Libro IVA.
    26/11/2026: además se toman sus importes (neto, no gravado, exento, IVA) para saber el gasto y el crédito fiscal
    que se pueden rescatar."""
    meses: dict[str, dict | None] = {}
    for x in filas:
        if not x.get("mes"):
            continue
        for m in (x["mes"], _mas_meses(x["mes"], -1), _mas_meses(x["mes"], 1)):
            if m in meses:
                continue
            ruta = os.path.join(DATOS, cuit, m, "recibidos.csv")
            if not os.path.exists(ruta):
                meses[m] = None
                continue
            meses[m] = {}
            try:                                           # formato viejo del CSV (Nro. Doc. Emisor): sin importes
                import csv
                with open(ruta, encoding="utf-8-sig", errors="replace") as f:
                    for r in csv.DictReader(f, delimiter=";"):
                        r = {k.strip(): (v or "") for k, v in r.items() if k}
                        cu = re.sub(r"\D", "", r.get("Nro. Doc. Emisor", ""))
                        nu = re.sub(r"\D", "", (r.get("Número Desde") or "").split(".")[0])
                        if cu and nu:
                            meses[m][(cu, int(nu[-8:]))] = {}
            except Exception:
                pass
            try:
                from .lector_mis_comprobantes import leer as _leer_mc
                df = _leer_mc(ruta)
                for _, r in df.iterrows():
                    cu = re.sub(r"\D", "", str(r.get("CUIT contraparte", "")))
                    nu = re.sub(r"\D", "", str(r.get("Número Desde", "")).split(".")[0])
                    if cu and nu:
                        g = lambda k: float(r.get(k, 0) or 0)
                        meses[m][(cu, int(nu[-8:]))] = {
                            "fecha": str(r.get("Fecha", ""))[:10], "tipo": str(r.get("Tipo", "")),
                            "punto_venta": str(r.get("Punto de Venta", "")).split(".")[0], "numero": nu,
                            "emisor": str(r.get("Contraparte", "")), "neto": g("Imp. Neto Gravado Total"),
                            "no_gravado": g("Imp. Neto No Gravado"), "exento": g("Imp. Op. Exentas"),
                            "iva": g("Total IVA"), "otros": g("Otros Tributos"), "total": g("Imp. Total")}
            except Exception:
                pass                                       # queda lo del formato viejo (sin importes)
    for x in filas:
        n = _numero(x.get("comprobante"))
        bajados = [meses.get(m) for m in ((x["mes"], _mas_meses(x["mes"], -1), _mas_meses(x["mes"], 1)) if x.get("mes") else ())]
        if not n or not any(b is not None for b in bajados):
            x["en_mis_comprobantes"] = None              # no se puede saber (no está bajado Mis Comprobantes)
            continue
        hallado = next((b[(x["agente"], n)] for b in bajados if b and (x["agente"], n) in b), None)
        x["en_mis_comprobantes"] = hallado is not None
        if hallado:                                        # {} = está, pero el CSV viejo no trae importes
            x["mc"] = hallado


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
    # Biblioteca (robot_arba_retenciones, 25/11/2026): los 2 últimos meses con percepciones y aduaneras; reemplaza esos
    # meses de lo que trajo la ventanilla DFE (que leía solo percepciones de 13 meses)
    bib_arba = {}
    for d in glob.glob(os.path.join(DATOS, cuit, "biblioteca", "[0-9]*", "arba")):
        vs = sorted(glob.glob(os.path.join(d, "[0-9]*.json")))
        v = _leer(vs[-1]) if vs else None
        if isinstance(v, dict):
            bib_arba[v.get("periodo") or os.path.basename(os.path.dirname(d))] = v.get("filas") or []
    if bib_arba:
        viejas = [x for x in (arba or {}).get("percepciones") or []
                  if f"{str(x.get('fecha', ''))[6:10]}-{str(x.get('fecha', ''))[3:5]}" not in bib_arba]
        arba = dict(arba or {}, percepciones=viejas + [x for fs in bib_arba.values() for x in fs])
    # 26/11/2026 (Gaby): histórico acumulado por mes (inicial de 5 años + los 2 meses de cada corrida habitual)
    from . import percepciones_hist as hist
    if isinstance(mr, dict) and mr.get("filas") is not None:     # lo último de Mis Retenciones manda en sus meses
        meses_mr, d0 = [], (mr.get("desde") or "")[:7]
        while d0 and d0 <= (mr.get("hasta") or "")[:7]:
            ant = _leer(os.path.join(hist.carpeta(cuit, "arca"), f"{d0}.json")) or {}
            if (ant.get("fecha") or "") <= (mr.get("fecha") or "9"):
                meses_mr.append(d0)
            d0 = _mas_meses(d0, 1)
        if meses_mr:
            hist.guardar(cuit, "arca", [f for f in mr["filas"] if hist.mes_de(f.get("fecha") or "") in meses_mr], meses_mr,
                         date.fromisoformat(mr["fecha"]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", mr.get("fecha") or "") else hoy)
    h_arca, m_arca = hist.leer(cuit, "arca")
    h_arba, m_arba = hist.leer(cuit, "arba")
    h_agip, m_agip = hist.leer(cuit, "agip")
    if not (h_arca or mr) and not (h_agip or agip) and not (h_arba or arba):
        return None
    mr = mr if isinstance(mr, dict) else {}
    filas = list(h_arca if m_arca else (mr.get("filas") or []))
    for x in (h_agip if m_agip else (agip or {}).get("percepciones") or []):
        filas.append(dict(x, impuesto="IIBB CABA", fuente="AGIP · Gestión-AR"))
    for x in (h_arba if m_arba else (arba or {}).get("percepciones") or []):
        filas.append(dict({"fecha_comprobante": x.get("fecha")}, **x, impuesto="IIBB Buenos Aires", fuente="ARBA · Deducciones"))
    todos_meses = sorted(set(m_arca) | set(m_arba) | set(m_agip))
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
        estado, mes, nota = buscar(p, libros)
        if estado == "en_libro":
            ok += 1
            continue
        fila = {"impuesto": imp, "fuente": p.get("fuente") or ("ARCA · Aduana (despacho de importación)" if p.get("aduana")
                                                              else "ARCA · Mis Retenciones"),
                "agente": p["agente"], "regimen": p.get("regimen"),
                "fecha_comprobante": p.get("fecha_comprobante"), "comprobante": p.get("comprobante"),
                "desc_comprobante": "Despacho" if p.get("aduana") else p.get("desc_comprobante"),
                "importe": p.get("importe") or 0.0, "mes": mes, "nota": nota, "base": p.get("base")}
        if p.get("aduana"):
            fila["importe_" + imp.lower()] = fila["importe"]
            despachos[p.get("comprobante") or f"{p.get('fecha_comprobante')}"] = fila
        (sin if estado == "sin_comprobante" else nc).append(fila)
    sin = _unir_por_comprobante(sin)
    _marcar_mis_comprobantes(cuit, sin)
    for x in sin + nc:                                # importe del despacho: el de IVA (crédito fiscal) si lo hay
        if "importe_iva" in x or "importe_ganancias" in x:
            x["importe"] = x.get("importe_iva", 0.0) + x.get("importe_ganancias", 0.0)
    sin.sort(key=lambda x: (x["mes"] or "", x["agente"]), reverse=True)
    meses_nc = sorted({x["mes"] for x in nc if x["mes"]})
    # 22/11/2026: percepción NEGATIVA = nota de crédito del proveedor; si falta en el Libro IVA el problema es al revés
    # (el crédito fiscal quedó de más). Va aparte y no resta del total de facturas faltantes.
    for x in sin:                                     # lo que se puede rescatar (no la percepción: esa ya entró sola)
        mc = x.get("mc") or {}
        if mc:
            x["gasto_recuperable"] = round(mc.get("neto", 0) + mc.get("no_gravado", 0) + mc.get("exento", 0), 2)
            x["credito_fiscal_recuperable"] = round(mc.get("iva", 0), 2)
            x["recuperable_segun"] = "Mis Comprobantes (factura del proveedor)"
        elif x.get("base") and x.get("impuesto") != "Ganancias":
            x["gasto_recuperable"] = round(x["base"], 2)
            x["credito_fiscal_recuperable"] = round(x["base"] * 0.21, 2)
            x["recuperable_segun"] = "ESTIMADO: base de la percepción × 21 % (confirmar con la factura)"
    nc_sin = [x for x in sin if (x.get("importe") or 0) < 0]
    sin = [x for x in sin if (x.get("importe") or 0) >= 0]
    h = hist.historico_hecho(cuit) or {}
    r = {"cuit": cuit, "fecha": hoy.isoformat(), "fecha_mis_retenciones": mr.get("fecha"),
         "desde": (todos_meses[0] if todos_meses else mr.get("desde")), "rango_inicial": h or None,
         "meses_cruzados": todos_meses,
         "nc_sin_comprobante": nc_sin, "total_nc_sin_comprobante": round(sum(x["importe"] for x in nc_sin), 2),
         "hasta": (todos_meses[-1] if todos_meses else mr.get("hasta")), "fecha_agip": (agip or {}).get("fecha"), "fecha_arba": (arba or {}).get("fecha"), "en_libro": ok, "sin_comprobante": sin,
         "total_sin_comprobante": round(sum(x["importe"] for x in sin), 2),
         "gasto_recuperable": round(sum(x.get("gasto_recuperable") or 0 for x in sin), 2),
         "credito_fiscal_recuperable": round(sum(x.get("credito_fiscal_recuperable") or 0 for x in sin), 2),
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
    if nc_sin:
        al.append({"prioridad": "MEDIA", "tipo": "Notas de crédito con percepción sin registrar en el Libro IVA",
                   "texto": f"{len(nc_sin)} nota(s) de crédito de proveedores (percepción {_pesos(r['total_nc_sin_comprobante'])}) "
                            f"que no están en el Libro IVA: el crédito fiscal y el gasto pueden estar de más. Revisar."})
    r["alertas"] = al
    d = os.path.join(DATOS, cuit, "conciliacion")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "percepciones.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    try:                                              # Excel al repositorio permanente de la Biblioteca (26/11/2026)
        from . import conciliacion_excel
        conciliacion_excel.percepciones(cuit, r, hoy=hoy)
    except Exception:
        pass
    return r
