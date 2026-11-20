"""Análisis que la web calcula con lo que ya bajaron los robots (no entra a ningún organismo).

Traído de Radar fiscal (17/11/2026), con los mismos criterios por defecto que TributIA:
  - Relación débito/crédito de IVA de los últimos 12 meses: menos de 0,8 = Crítico, menos de 1,2 = Advertencia.
  - Proyección de IVA: tendencia lineal (mínimos cuadrados) del débito y del crédito, extendida un mes.
  - Resultado mensual:  Ventas netas − Compras netas − Sueldos netos − F.931 (aportes + contribuciones).
      Ventas y compras: neto gravado + exento + no gravado del Libro IVA (sin IVA). Ventas: además los comprobantes
      sin desglose (facturas C, alquileres de vivienda): la utilidad es TODO lo vendido sin IVA contra erogaciones. Las compras B/C
      (sin IVA discriminado) se toman por el total, igual que en la relación D/C del estudio.
      Sueldos netos: remuneración (Rem. 1 del F.931) menos aportes retenidos (ESTIMADO: el robot todavía no
      baja el Libro de Sueldos Digital). F.931: aportes + cargas sociales (contribuciones, ART, SCVO, RENATRE).
  - Deuda mínima: por debajo de $15.000 se considera "sin deuda" (redondeos, intereses chicos).

Fuentes (las deja el robot en DATOS/<cuit>/):
  libro_iva/AAAA-MM.json   (robot_libro_iva: ventas y compras de cada DJ presentada)
  f931/AAAA-MM.json        (robot_f931)
"""
from __future__ import annotations

import glob
import json
import os
import re

from . import datos

REGLAS = {
    "deuda_minima": 15_000.0,
    "ratio_critico": 0.8,
    "ratio_advertencia": 1.2,
    "meses": 12,
}
_PER = re.compile(r"^\d{4}-\d{2}$")


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _meses(cuit: str, carpeta: str) -> dict[str, dict]:
    out = {}
    for ruta in glob.glob(os.path.join(datos.DATOS, cuit, carpeta, "*.json")):
        per = os.path.basename(ruta)[:-5]
        if _PER.match(per):
            d = _leer(ruta)
            if isinstance(d, dict):
                out[per] = d
    return out


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def dia_de_corrida(cuit: str, monotributo: bool = False) -> str:
    """Cuándo le toca la corrida completa (lo asigna el robot en publico/grupos.json): inscriptos todas las semanas,
    monotributistas semana por medio (dos veces por mes)."""
    import datetime as _dt
    d = (_leer(os.path.join(datos.PUBLICO, "grupos.json")) or {}).get(cuit)
    if d is None:
        return "a asignar en la próxima corrida"
    if not isinstance(d, dict):
        d = {"dia": int(d), "semana": int(cuit[-1]) % 2}
    dia = DIAS[int(d["dia"])]
    plural = dia + "s" if dia in ("sábado", "domingo") else dia
    if not monotributo:
        return f"todos los {plural}"
    f = _dt.date.today()
    while not (f.weekday() == int(d["dia"]) and f.isocalendar()[1] % 2 == int(d.get("semana", 0))):
        f += _dt.timedelta(days=1)
    return f"{plural} por medio (dos veces por mes; próxima: {f.strftime('%d/%m')})"


def periodo_txt(p: str) -> str:
    meses = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    try:
        a, m = p.split("-")
        return f"{meses[int(m) - 1]}-{a[2:]}"
    except (ValueError, IndexError):
        return p


def _pesos(v: float) -> str:
    t = f"{abs(v):,.0f}".replace(",", ".")
    return f"{'-' if v < 0 else ''}$ {t}"


def pct(v) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f} %".replace(".", ",")


# ---------------------------------------------------------------- IVA
def iva_mensual(cuit: str) -> list[dict]:
    """[{periodo, debito, credito, saldo}] del más viejo al más nuevo (solo DJ presentadas)."""
    out = []
    for per, d in sorted(_meses(cuit, "libro_iva").items()):
        v, c = d.get("ventas") or {}, d.get("compras") or {}
        deb = _num(v.get("Total IVA"))
        cred = _num(c.get("Crédito fiscal computable") or c.get("Total IVA"))
        out.append({"periodo": per, "debito": deb, "credito": cred, "saldo": deb - cred})
    return out


def nivel_ratio(ratio: float) -> str:
    if ratio < REGLAS["ratio_critico"]:
        return "Crítico"
    if ratio < REGLAS["ratio_advertencia"]:
        return "Advertencia"
    return "Adecuado"


def ratio_dc(iva: list[dict], meses: int | None = None) -> dict | None:
    r = iva[-(meses or REGLAS["meses"]):]
    if not r:
        return None
    deb = sum(m["debito"] for m in r)
    cred = sum(m["credito"] for m in r)
    ratio = deb / cred if cred else (float("inf") if deb else 0.0)
    return {"debito": deb, "credito": cred, "ratio": ratio, "desde": r[0]["periodo"], "hasta": r[-1]["periodo"],
            "meses": len(r), "nivel": nivel_ratio(ratio)}


def tendencia(vals: list[float]) -> tuple[list[float], float]:
    """Recta de mínimos cuadrados sobre los valores y el valor proyectado del período siguiente."""
    n = len(vals)
    if n < 2:
        return list(vals), (vals[0] if vals else 0.0)
    xm = (n - 1) / 2
    ym = sum(vals) / n
    num = sum((x - xm) * (y - ym) for x, y in enumerate(vals))
    den = sum((x - xm) ** 2 for x in range(n))
    m = num / den if den else 0.0
    b = ym - m * xm
    return [b + m * x for x in range(n)], max(0.0, b + m * n)


def _siguiente(per: str) -> str:
    a, m = map(int, per.split("-"))
    a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return f"{a}-{m:02d}"


def proyectar_iva(iva: list[dict]) -> dict | None:
    r = iva[-REGLAS["meses"]:]
    if len(r) < 3:
        return None
    ld, d = tendencia([m["debito"] for m in r])
    lc, c = tendencia([m["credito"] for m in r])
    d, c = round(d), round(c)
    return {"periodo": _siguiente(r[-1]["periodo"]), "debito": d, "credito": c, "saldo": d - c,
            "ratio": (d / c) if c else None, "linea_debito": ld, "linea_credito": lc, "base": r}


# ---------------------------------------------------------------- resultado mensual
TIPOS_C = {11, 12, 13, 15, 111, 211, 212, 213}      # facturas C de compra (las B no se toman jamás: Gaby 17/11/2026)


def _compras_c(l: dict) -> float | None:
    cc = l.get("comprobantes_compras")
    if cc is None:
        return None
    return sum(_num(c.get("total")) for c in cc if c.get("b_c") and int(_num(c.get("tipo"))) in TIPOS_C)


def ventas_sin_desglose(l: dict) -> float:
    """Ventas sin IVA que no figuran como neto, no gravado ni exento (facturas C, alquileres de vivienda...).
    Libros IVA bajados antes del 20/11/2026 no traen el dato: se calcula con los comprobantes guardados (los que no
    tienen neto ni IVA) menos lo que ya figura como no gravado + exento."""
    v = l.get("ventas") or {}
    if "Otras ventas sin IVA (sin desglose)" in v:
        return _num(v.get("Otras ventas sin IVA (sin desglose)"))
    comps = l.get("comprobantes_ventas")
    if not comps:
        return 0.0
    sin = sum(_num(c.get("total")) for c in comps if not _num(c.get("neto")) and not _num(c.get("iva")))
    return round(max(0.0, sin - _num(v.get("No gravado")) - _num(v.get("Exento"))), 2)


def _neto(res: dict, compras: bool) -> float:
    """Igual que la planilla 'Relación DC': ventas = neto gravado + no gravado + exento;
    compras = lo mismo + comprobantes B/C + impuesto a los combustibles."""
    n = _num(res.get("Neto gravado total")) + _num(res.get("Exento")) + _num(res.get("No gravado"))
    if compras:
        n += _num(res.get("Comprobantes B/C (sin IVA discriminado)")) + _num(res.get("Impuesto a los combustibles"))
    return n


def _iibb(cuit: str) -> dict[str, float]:
    """Impuesto determinado de IIBB por período: SIFERE (todas las jurisdicciones) + ARBA (contribuyente local)."""
    out: dict[str, float] = {}
    for per, d in _meses(cuit, "sifere").items():
        out[per] = out.get(per, 0.0) + sum(_num((v or {}).get("determinado")) for v in (d.get("jurisdicciones") or {}).values())
    for per, d in _meses(cuit, "arba").items():
        if d.get("impuesto_determinado") is not None:
            out[per] = out.get(per, 0.0) + _num(d.get("impuesto_determinado"))
    return out


def resultado_mensual(cuit: str) -> list[dict]:
    """Relación débito/crédito con las MISMAS fórmulas que el Excel del robot (informe_cliente.relacion_dc):
    erogaciones = compras + (remuneraciones + cargas sociales) + IIBB determinado;
    saldo = ventas − erogaciones; índice = erogaciones / ventas; margen = 1 − índice; y sus acumulados.
    Fuentes: Libro IVA (Portal IVA), F.931 y SIFERE/ARBA. No usa Mis Comprobantes."""
    liva = _meses(cuit, "libro_iva")
    from . import asientos                           # F.931 + lo que completó a mano el encargado (19/11/2026)
    f931 = asientos.f931_con_manual(cuit)
    iibb = _iibb(cuit)
    bc_mc = ((_leer(os.path.join(datos.DATOS, cuit, "conciliacion", "compras_bc_fuera_libro.json")) or {})
             .get("por_mes") or {})
    fuentes = {f["periodo"]: f for f in ((_leer(os.path.join(datos.DATOS, cuit, "conciliacion", "fuentes.json")) or {})
                                           .get("meses") or [])}
    ajustes = ((_leer(os.path.join(datos.DATOS, cuit, "conciliacion", "ajustes_conciliacion.json")) or {})
               .get("por_mes") or {})
    hay_iibb = bool(iibb) or os.path.isdir(os.path.join(datos.DATOS, cuit, "sifere"))
    out = []
    acum_v = acum_e = acum_s = 0.0
    for per in sorted(set(liva) | set(f931))[-REGLAS["meses"]:]:
        faltan = []
        l, f = liva.get(per), f931.get(per)
        if l:
            ventas, compras = _neto(l.get("ventas") or {}, False), _neto(l.get("compras") or {}, True)
            ventas += ventas_sin_desglose(l)               # ingresos totales sin IVA (Gaby 20/11/2026)
            solo_c = _compras_c(l)
            if solo_c is not None:                         # saca las facturas B (datos bajados antes del 17/11)
                compras += solo_c - _num((l.get("compras") or {}).get("Comprobantes B/C (sin IVA discriminado)"))
        else:
            ventas = compras = 0.0
            faltan.append("Libro IVA")
        if f or not f931:                                 # sin ningún F.931 bajado = sin empleados (no "falta")
            f = f or {}
            sueldos = _num(f.get("Remuneración total (con no remunerativos)", f.get("Remuneración total (Rem. 1)")))
            cargas = _num(f.get("TOTAL CARGAS SOCIALES"))
        else:
            sueldos = cargas = 0.0
            faltan.append("F.931")
        ib = iibb.get(per)
        if ib is None and hay_iibb and ventas:
            faltan.append("IIBB")
        bc = _num(bc_mc.get(per)) if l else 0.0     # facturas B/C de Mis Comprobantes que no están en el Libro IVA
        erog = compras + bc + sueldos + cargas + (ib or 0.0)
        saldo = ventas - erog
        if ventas:
            acum_v += ventas
            acum_e += erog
            acum_s += saldo
        indice = erog / ventas if ventas else None
        # Ajustes de la conciliación (informativos: el informe principal sale del Portal IVA)
        aj = ajustes.get(per) or {} if l else {}
        aj_dup, aj_nc, aj_nt = (_num(aj.get(f"{k}_neto")) for k in ("duplicados", "nc", "no_tomadas"))
        aj_iva = sum(_num(aj.get(f"{k}_iva")) for k in ("duplicados", "nc", "no_tomadas"))
        erog_aj = erog + aj_dup + aj_nc + aj_nt
        # segunda fuente (Mis Comprobantes, misma fórmula) para la revisión cruzada (20/11/2026)
        fu = fuentes.get(per) or {}
        mc = fu.get("mis_comprobantes")
        out_mc = {"ventas_mc": mc["ventas"] if mc else None, "compras_mc": mc["compras"] if mc else None,
                  "resultado_mc": (mc["ventas"] - mc["compras"] - sueldos - cargas - (ib or 0.0)) if mc else None,
                  "fuentes_estado": fu.get("estado", "sin comparar")}
        out.append({**out_mc, "aj_duplicados": aj_dup, "aj_nc": aj_nc, "aj_no_tomadas": aj_nt, "aj_iva_credito": aj_iva,
                    "erogaciones_ajustadas": erog_aj, "resultado_ajustado": ventas - erog_aj,
                    "indice_ajustado": erog_aj / ventas if ventas else None,
                    "debito": _num((l or {}).get("ventas", {}).get("Total IVA")),
                    "credito": _num((l or {}).get("compras", {}).get("Total IVA")),
                    "saldo_tecnico": _num((l or {}).get("ventas", {}).get("Total IVA"))
                    - _num((l or {}).get("compras", {}).get("Total IVA")),
                    "saldo_tecnico_ajustado": _num((l or {}).get("ventas", {}).get("Total IVA"))
                    - _num((l or {}).get("compras", {}).get("Total IVA")) - aj_iva,"periodo": per, "ventas": ventas, "compras": compras, "compras_bc_mc": bc, "sueldos": sueldos, "cargas": cargas,
                    "f931": cargas, "iibb": ib, "erogaciones": erog, "resultado": saldo, "saldo_acumulado": acum_s,
                    "indice": indice, "indice_acumulado": (acum_e / acum_v) if acum_v else None,
                    "margen": (1 - indice) if indice is not None else None,
                    "faltantes": faltan, "completo": not faltan})
    return out


def analizar_resultado(meses: list[dict]) -> dict | None:
    if not meses:
        return None
    tot = {k: sum((m.get(k) or 0) for m in meses) for k in ("ventas", "compras", "compras_bc_mc", "sueldos", "cargas", "f931", "iibb",
                                                          "erogaciones", "resultado", "aj_duplicados", "aj_nc",
                                                          "aj_no_tomadas", "aj_iva_credito", "erogaciones_ajustadas",
                                                          "resultado_ajustado", "debito", "credito", "saldo_tecnico",
                                                          "saldo_tecnico_ajustado")}
    tot["indice_ajustado"] = tot["erogaciones_ajustadas"] / tot["ventas"] if tot["ventas"] else None
    tot["hay_ajustes"] = any(tot[k] for k in ("aj_duplicados", "aj_nc", "aj_no_tomadas"))
    tot["indice"] = tot["erogaciones"] / tot["ventas"] if tot["ventas"] else None
    tot["margen"] = (1 - tot["indice"]) if tot["indice"] is not None else None
    negativos = [m for m in meses if m["resultado"] < 0]
    orden = sorted([m for m in meses if m["completo"]] or meses, key=lambda m: m["resultado"], reverse=True)
    mejor, peor = orden[0], orden[-1]
    incompletos = [m for m in meses if not m["completo"]]
    prom = lambda xs: sum(m["resultado"] for m in xs) / len(xs) if xs else 0.0
    ult3, ant3 = meses[-3:], meses[-6:-3]
    var3 = (prom(ult3) - prom(ant3)) / abs(prom(ant3)) if len(ant3) == 3 and prom(ant3) else None
    linea, _ = tendencia([m["resultado"] for m in meses])
    pend = linea[1] - linea[0] if len(linea) > 1 else 0.0

    c = [f"Entre {periodo_txt(meses[0]['periodo'])} y {periodo_txt(meses[-1]['periodo'])} vendió {_pesos(tot['ventas'])} "
         f"y le quedó {_pesos(tot['resultado'])} después de compras, sueldos, cargas sociales e IIBB "
         f"(índice erogaciones/ventas {pct(tot['indice'])}, margen {pct(tot['margen'])})."]
    if tot["ventas"]:
        c.append(f"De cada $100 vendidos: ${round((tot['compras'] + tot['compras_bc_mc']) / tot['ventas'] * 100)} en compras, "
                 f"${round(tot['sueldos'] / tot['ventas'] * 100)} en remuneraciones, ${round(tot['cargas'] / tot['ventas'] * 100)} "
                 f"en cargas sociales y ${round(tot['iibb'] / tot['ventas'] * 100)} en IIBB.")
    if tot["resultado"] < 0:
        c.append("El resultado acumulado es NEGATIVO: los costos superan a las ventas declaradas. Conviene revisar si faltan "
                 "ventas o si hay costos que no corresponden.")
    c.append(f"{len(negativos)} de {len(meses)} meses dieron negativo: {', '.join(periodo_txt(m['periodo']) for m in negativos)}."
             if negativos else "Ningún mes dio negativo.")
    if mejor is not peor:
        c.append(f"Mejor mes: {periodo_txt(mejor['periodo'])} ({_pesos(mejor['resultado'])}). "
                 f"Peor mes: {periodo_txt(peor['periodo'])} ({_pesos(peor['resultado'])}).")
    if var3 is not None:
        c.append("Los últimos 3 meses están en línea con los 3 anteriores." if abs(var3) < 0.05 else
                 f"El promedio de los últimos 3 meses {'mejoró' if var3 > 0 else 'empeoró'} un {pct(abs(var3))} "
                 "respecto de los 3 anteriores.")
    if len(meses) >= 6 and pend:
        c.append(f"Tendencia de los {len(meses)} meses: el resultado {'sube' if pend > 0 else 'baja'} en promedio "
                 f"{_pesos(abs(pend))} por mes.")
    if incompletos:
        c.append(f"Atención: {len(incompletos)} mes(es) con datos incompletos ("
                 + "; ".join(f"{periodo_txt(m['periodo'])}: falta {', '.join(m['faltantes'])}" for m in incompletos)
                 + "). El resultado de esos meses no es confiable.")
    if tot["sueldos"] or tot["cargas"]:
        c.append("Remuneraciones (Rem. 1) y cargas sociales (contribuciones S.S., O.S., ART, seguro de vida y RENATRE) "
                 "tomadas del F.931, igual que en la planilla Relación DC.")
    else:
        c.append("No hay F.931 bajados: se toma como cliente sin empleados.")
    return {"meses": meses, "total": tot, "negativos": negativos, "mejor": mejor, "peor": peor,
            "incompletos": incompletos, "variacion_3m": var3, "tendencia_mensual": pend, "conclusiones": c}


# ---------------------------------------------------------------- gráfico (SVG simple, sin librerías)
def grafico_iva(iva: list[dict], proy: dict | None = None, ancho: int = 720, alto: int = 240) -> str:
    """Barras de débito y crédito por mes (+ el mes proyectado con borde punteado). Devuelve SVG."""
    meses = iva[-REGLAS["meses"]:]
    if not meses:
        return ""
    serie = [(m["periodo"], m["debito"], m["credito"], False) for m in meses]
    if proy:
        serie.append((proy["periodo"], proy["debito"], proy["credito"], True))
    tope = max(max(d, c) for _, d, c, _ in serie) or 1.0
    mi, md, ms, mb = 56, 8, 10, 28
    w, h = ancho - mi - md, alto - ms - mb
    paso = w / len(serie)
    bw = max(4.0, paso * 0.34)
    y = lambda v: ms + h - (v / tope) * h
    partes = [f'<svg viewBox="0 0 {ancho} {alto}" class="grafico" role="img" aria-label="Débito y crédito fiscal por mes">']
    for i in range(5):
        v = tope * i / 4
        yy = y(v)
        partes.append(f'<line x1="{mi}" x2="{ancho - md}" y1="{yy:.1f}" y2="{yy:.1f}" class="g-guia"/>'
                      f'<text x="{mi - 6}" y="{yy + 4:.1f}" class="g-eje" text-anchor="end">{_corto(v)}</text>')
    for i, (per, d, c, es_proy) in enumerate(serie):
        x0 = mi + i * paso + (paso - 2 * bw) / 2
        extra = ' stroke-dasharray="4 3"' if es_proy else ""
        cls = " g-proy" if es_proy else ""
        partes.append(f'<rect x="{x0:.1f}" y="{y(d):.1f}" width="{bw:.1f}" height="{max(0.5, ms + h - y(d)):.1f}" '
                      f'class="g-deb{cls}"{extra}><title>{periodo_txt(per)} débito {_pesos(d)}</title></rect>')
        partes.append(f'<rect x="{x0 + bw:.1f}" y="{y(c):.1f}" width="{bw:.1f}" height="{max(0.5, ms + h - y(c)):.1f}" '
                      f'class="g-cred{cls}"{extra}><title>{periodo_txt(per)} crédito {_pesos(c)}</title></rect>')
        partes.append(f'<text x="{mi + i * paso + paso / 2:.1f}" y="{alto - 8}" class="g-eje" text-anchor="middle">'
                      f'{periodo_txt(per)}{"*" if es_proy else ""}</text>')
    partes.append("</svg>")
    return "".join(partes)


def _corto(v: float) -> str:
    if v >= 1e9:
        return f"{v / 1e9:.1f} mM".replace(".", ",")
    if v >= 1e6:
        return f"{v / 1e6:.1f} M".replace(".", ",")
    if v >= 1e3:
        return f"{v / 1e3:.0f} mil"
    return f"{v:.0f}"
