"""Biblioteca de importables mensuales (especificación de Gaby del 25/11/2026, parte 1) — versión 1.

Por cliente, período y fuente: estado (bajado / sin movimientos / pendiente / error), detalle normalizado (una fila
por comprobante), totales del mes y saldos del mes anterior, con descarga en Excel (o todo el mes en .zip).

Esta versión usa lo que los robots YA bajan (no entra a ningún portal):
  ARCA · Mis Retenciones (impositivas: SICORE 767 y SIRE 216)   DATOS/<cuit>/mis_retenciones/<fecha>.json
  ARCA · Percepciones aduaneras (IVA 767 y Ganancias 217)        idem, agente 33-69345023-9 (ARCA-Aduana)
Saldos del mes anterior: IVA (saldo técnico y libre disponibilidad, Cuentas Tributarias), Convenio Multilateral
(subtotal a favor del contribuyente por jurisdicción, SIFERE CM03) y ARBA local.
Las demás fuentes (impuesto al cheque, Portal IVA precargadas, ARBA, AGIP, COMARB) figuran como "robot pendiente"
hasta relevar sus pantallas con Gaby.
"""
from __future__ import annotations

import glob
import io
import json
import os
import re
from datetime import date, timedelta

from . import datos

ADUANA = "33693450239"
JUR_NOMBRE = {"901": "CABA", "902": "Buenos Aires", "903": "Catamarca", "904": "Córdoba", "905": "Corrientes",
              "906": "Chaco", "907": "Chubut", "908": "Entre Ríos", "909": "Formosa", "910": "Jujuy", "911": "La Pampa",
              "912": "La Rioja", "913": "Mendoza", "914": "Misiones", "915": "Neuquén", "916": "Río Negro", "917": "Salta",
              "918": "San Juan", "919": "San Luis", "920": "Santa Cruz", "921": "Santa Fe", "922": "Santiago del Estero",
              "923": "Tierra del Fuego", "924": "Tucumán"}
# id, organismo, nombre, robot disponible, se usa en
FUENTES = [
    ("constancia", "ARCA", "Constancia de inscripción (se renueva cada mes)", False, "Datos fiscales del cliente"),
    ("arca_mr", "ARCA", "Mis Retenciones (SICORE / SIRE)", True, "IVA"),
    ("arca_aduana", "Aduana", "Percepciones aduaneras (IVA y Ganancias)", True, "IVA y Ganancias"),
    ("arca_piva", "ARCA", "Portal IVA: retenciones y percepciones precargadas", False, "IVA (control cruzado)"),
    ("arba", "ARBA", "Retenciones y percepciones sufridas", False, "IIBB PBA (902)"),
    ("agip", "AGIP", "Retenciones y percepciones sufridas", False, "IIBB CABA (901)"),
    ("sircreb", "COMARB", "SIRCREB (acreditaciones bancarias)", False, "IIBB"),
    ("sirtac", "COMARB", "SIRTAC (tarjetas)", False, "IIBB"),
    ("sircupa", "COMARB", "SIRCUPA (cuentas de pago)", False, "IIBB"),
    ("sircar", "COMARB", "SIRCAR (agentes de jurisdicciones adheridas)", False, "IIBB CM"),
    ("sirpei", "COMARB", "SIRPEI (percepciones en importaciones)", False, "IIBB importadores"),
]
NOMBRE = {f[0]: f"{f[1]} · {f[2]}" for f in FUENTES}
DISPONIBLE = {f[0]: f[3] for f in FUENTES}
ESTADOS = {"bajado": "Bajado", "sin_mov": "Sin movimientos", "pendiente": "Pendiente", "error": "Error",
           "robot": "Robot pendiente", "no": "—"}


MESES_BIBLIOTECA = 2          # Gabriel, 25/11/2026: siempre los 2 últimos meses cerrados, nunca más


def periodos(hoy: date | None = None) -> list[str]:
    hoy = hoy or date.today()
    p1 = hoy.replace(day=1) - timedelta(days=1)
    p2 = p1.replace(day=1) - timedelta(days=1)
    return [p1.strftime("%Y-%m"), p2.strftime("%Y-%m")]


def periodo_anterior(hoy: date | None = None) -> str:
    hoy = hoy or date.today()
    return (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")


def _fin(periodo: str) -> date:
    a, m = map(int, periodo.split("-"))
    return date(a + (m == 12), m % 12 + 1, 1) - timedelta(days=1)


def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ qué fuentes van para cada cliente
def por_defecto(cuit: str, dc: dict) -> list[str]:
    """Valores por defecto de la especificación: RI -> fuentes de ARCA; IIBB -> su jurisdicción y SIRCREB / SIRTAC /
    SIRCUPA (CM también SIRCAR); importador -> SIRPEI y aduaneras; monotributo -> nada."""
    cond = (dc.get("condicion_iva") or "").lower()
    es_ri = "inscripto" in cond or (not cond and os.path.isdir(os.path.join(datos.DATOS, cuit, "libro_iva")))
    if "monotrib" in cond:
        return []
    out = []
    if es_ri:
        out += ["arca_mr", "arca_piva"]
    reg = (dc.get("regimen_iibb") or "").lower()
    jur = (dc.get("jurisdicciones_iibb") or "").lower()
    if reg or jur:
        if "convenio" in reg:
            out += ["sircar"]
        if "caba" in jur or "ciudad" in jur:
            out += ["agip"]
        if "buenos aires" in jur or "pba" in jur:
            out += ["arba"]
        out += ["sircreb", "sirtac", "sircupa"]
    if _filas_mr(cuit) and any(f.get("agente") == ADUANA for f in _filas_mr(cuit)):
        out += ["arca_aduana", "sirpei"]
    return list(dict.fromkeys(out))


def elegidas(cuit: str, dc: dict) -> list[str]:
    v = dc.get("importables")
    if isinstance(v, list):
        return [x for x in v if x in NOMBRE]
    return por_defecto(cuit, dc)


# ------------------------------------------------------------------ datos de ARCA · Mis Retenciones
_CACHE: dict = {}


def _ultimo_mr(cuit: str) -> dict | None:
    """Último Mis Retenciones del cliente (en memoria mientras el archivo no cambie: la grilla lo pide muchas veces)."""
    r = sorted(glob.glob(os.path.join(datos.DATOS, cuit, "mis_retenciones", "[0-9]*.json")))
    if not r:
        return None
    clave = (r[-1], os.path.getmtime(r[-1]))
    if _CACHE.get(cuit, (None,))[0] != clave:
        if len(_CACHE) > 2000:
            _CACHE.clear()
        _CACHE[cuit] = (clave, _leer(r[-1]))
    return _CACHE[cuit][1]


def errores_corrida(cuit: str) -> dict:
    r = sorted(glob.glob(os.path.join(datos.DATOS, cuit, "corrida_todo_*.json")))
    return ((_leer(r[-1]) if r else None) or {}).get("errores") or {}


def _filas_mr(cuit: str) -> list[dict]:
    return (_ultimo_mr(cuit) or {}).get("filas") or []


def _en_periodo(fecha: str, periodo: str) -> bool:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", fecha or "")
    return bool(m) and f"{m[3]}-{m[2]}" == periodo


def detalle(cuit: str, periodo: str, fuente: str) -> list[dict]:
    """Una fila por comprobante, con columnas normalizadas."""
    if fuente not in ("arca_mr", "arca_aduana"):
        return []
    out = []
    vs = versiones(cuit, periodo, fuente)
    nuevos = {_clave_fila(f) for f in cambios(cuit, periodo, fuente)["nuevos"]} if len(vs) > 1 else set()
    for f in (vs[-1]["filas"] if vs else _filas_mr(cuit)):
        es_aduana = f.get("agente") == ADUANA
        if (fuente == "arca_aduana") != es_aduana or not _en_periodo(f.get("fecha"), periodo):
            continue
        imp = str(f.get("impuesto") or "")
        out.append({"CUIT agente": f.get("agente", ""), "Fecha": f.get("fecha", ""),
                    "Operación": f.get("operacion", ""), "Régimen": f.get("regimen", ""),
                    "Impuesto": imp, "Jurisdicción": "", "Comprobante": f.get("desc_comprobante", ""),
                    "Número": f.get("comprobante", ""), "Fecha comprobante": f.get("fecha_comprobante", ""),
                    "Certificado": f.get("certificado", ""), "Base imponible": None, "Importe": f.get("importe") or 0.0,
                    "Registrado por el agente": f.get("fecha_dj", ""),
                    "Cambio": "NUEVO" if _clave_fila(f) in nuevos else ""})
    return out


def versiones(cuit: str, periodo: str, fuente: str) -> list[dict]:
    """Versiones guardadas por el robot (la más nueva al final)."""
    out = []
    for r in sorted(glob.glob(os.path.join(datos.DATOS, cuit, "biblioteca", periodo, fuente, "[0-9]*.json"))):
        v = _leer(r)
        if isinstance(v, dict):
            out.append(v)
    return out


def _clave_fila(f: dict) -> tuple:
    return (f.get("agente", ""), f.get("comprobante") or f.get("certificado") or "", f.get("fecha", ""), f.get("operacion", ""))


def cambios(cuit: str, periodo: str, fuente: str) -> dict:
    """Última versión contra la anterior: lo que apareció, desapareció o cambió de importe."""
    vs = versiones(cuit, periodo, fuente)
    if len(vs) < 2:
        return {"hay": False, "nuevos": [], "desaparecidos": [], "cambiados": [], "desde": "", "hasta": vs[-1]["fecha"] if vs else ""}
    a = {_clave_fila(f): f for f in vs[-2].get("filas") or []}
    b = {_clave_fila(f): f for f in vs[-1].get("filas") or []}
    nuevos = [b[k] for k in b if k not in a]
    desap = [a[k] for k in a if k not in b]
    camb = [{**b[k], "importe_anterior": a[k].get("importe")} for k in b if k in a and a[k].get("importe") != b[k].get("importe")]
    return {"hay": bool(nuevos or desap or camb), "nuevos": nuevos, "desaparecidos": desap, "cambiados": camb,
            "desde": vs[-2]["fecha"], "hasta": vs[-1]["fecha"]}


def diagnostico(cuit: str, fuente: str) -> dict:
    """Pedido de Gabriel (25/11/2026): por listado, si bajó o no, en qué paso falló, el error y la captura."""
    if not DISPONIBLE.get(fuente):
        return {"estado": "sin robot", "texto": "Todavía no hay robot para este listado: falta que Gabriel muestre dónde está "
                "en el portal y en qué formato se exporta.", "capturas": [], "fecha": ""}
    r = sorted(glob.glob(os.path.join(datos.DATOS, cuit, "corrida_todo_*.json")))
    ult = (_leer(r[-1]) if r else None) or {}
    err = (ult.get("errores") or {}).get("mis_retenciones")
    mr = _ultimo_mr(cuit)
    caps = sorted((os.path.basename(x) for x in glob.glob(os.path.join(datos.DATOS, cuit, "capturas", "error_mis_retenciones*.png"))),
                  reverse=True)[:3]
    if err:
        return {"estado": "error", "texto": str(err)[:400], "paso": "Mis Retenciones", "capturas": caps, "fecha": ult.get("fecha", "")}
    if mr:
        return {"estado": "ok", "texto": f"Bajó el {mr.get('fecha', '')}: {len(mr.get('filas') or [])} comprobantes en 12 meses "
                f"({ult.get('mis_retenciones') or 'corrida completa'}).", "capturas": [], "fecha": mr.get("fecha", "")}
    return {"estado": "nunca", "texto": "Todavía no se corrió para este cliente (va en la corrida completa del fin de semana "
            "o con «Probar ahora»).", "capturas": caps, "fecha": ""}


def estado(cuit: str, periodo: str, fuente: str, dc: dict | None = None, errores: dict | None = None) -> str:
    dc = dc if dc is not None else {}
    if fuente not in elegidas(cuit, dc):
        return "no"
    if not DISPONIBLE.get(fuente):
        return "robot"
    mr = _ultimo_mr(cuit)
    if not mr:
        return "error" if (errores or {}).get("mis_retenciones") else "pendiente"
    cubre = (mr.get("hasta") or "") >= _fin(periodo).isoformat() and (mr.get("desde") or "9") <= f"{periodo}-01"
    if not cubre:
        return "pendiente"
    return "bajado" if detalle(cuit, periodo, fuente) else "sin_mov"


def totales(filas: list[dict]) -> dict:
    t: dict = {}
    for f in filas:
        k = f"{f['Operación'][:10].strip() or 'Otro'} · impuesto {f['Impuesto'] or '?'}"
        x = t.setdefault(k, {"cantidad": 0, "importe": 0.0})
        x["cantidad"] += 1
        x["importe"] = round(x["importe"] + (f["Importe"] or 0), 2)
    return t


# ------------------------------------------------------------------ saldos del mes anterior
def saldos_anteriores(cuit: str, periodo: str) -> list[dict]:
    """Saldos a favor que quedaron de las DDJJ del período ANTERIOR al de la biblioteca."""
    a, m = map(int, periodo.split("-"))
    ant = f"{a - (m == 1)}-{(m - 2) % 12 + 1:02d}"
    out = []
    from .analisis import _saldos_iva_anteriores
    iva = _saldos_iva_anteriores(cuit, periodo)
    if iva.get("periodo"):
        out.append({"impuesto": "IVA", "detalle": f"saldo técnico a favor ({iva['periodo']})", "importe": iva["saldo_tecnico"],
                    "fuente": f"Cuentas Tributarias al {iva['al']}"})
        out.append({"impuesto": "IVA", "detalle": f"saldo de libre disponibilidad ({iva['periodo']})", "importe": iva["sld"],
                    "fuente": f"Cuentas Tributarias al {iva['al']}"})
    sif = _leer(os.path.join(datos.DATOS, cuit, "sifere", f"{ant}.json")) or {}
    for j, v in sorted((sif.get("jurisdicciones") or {}).items()):
        liq = (v or {}).get("liquidacion") or {}
        if liq.get("favor_contribuyente") is not None:
            out.append({"impuesto": "IIBB CM", "detalle": f"{JUR_NOMBRE.get(j, j)}: a favor del contribuyente ({ant})",
                        "importe": liq["favor_contribuyente"], "fuente": "SIFERE (CM03)"})
    arba = _leer(os.path.join(datos.DATOS, cuit, "arba", f"{ant}.json")) or {}
    if arba.get("saldo_favor") is not None:
        out.append({"impuesto": "IIBB ARBA", "detalle": f"saldo a favor ({ant})", "importe": arba["saldo_favor"],
                    "fuente": "ARBA (DJ local)"})
    return out


# ------------------------------------------------------------------ grilla y descargas
def grilla(clientes: list[dict], periodo: str) -> list[dict]:
    from . import usuarios
    filas = []
    for c in clientes:
        dc = usuarios.datos_cliente(c["cuit"]) or {}
        err = errores_corrida(c["cuit"])
        est = {f[0]: estado(c["cuit"], periodo, f[0], dc, err) for f in FUENTES}
        filas.append({**c, "dc": dc, "estados": est, "elegidas": elegidas(c["cuit"], dc)})
    return filas


def excel(cuit: str, nombre: str, periodo: str, fuentes: list[str]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook()
    wb.remove(wb.active)
    cols = ["CUIT agente", "Fecha", "Operación", "Régimen", "Impuesto", "Jurisdicción", "Comprobante", "Número",
            "Fecha comprobante", "Certificado", "Base imponible", "Importe", "Registrado por el agente", "Cambio"]
    for fu in fuentes:
        ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", "", NOMBRE[fu])[:31])
        ws.append([f"{NOMBRE[fu]} — {nombre} — CUIT {datos.cuit_fmt(cuit)} — {periodo}"])
        ws["A1"].font = Font(bold=True)
        ws.append([])
        ws.append(cols)
        for c in ws[3]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F4E78")
        filas = detalle(cuit, periodo, fu)
        for f in filas:
            ws.append([f[k] for k in cols])
        if filas:
            ws.append([None] * 10 + ["Total", round(sum(f["Importe"] for f in filas), 2)])
        ca = cambios(cuit, periodo, fu)
        for f in ca["desaparecidos"]:
            ws.append([f.get("agente"), f.get("fecha"), f.get("operacion"), f.get("regimen"), f.get("impuesto"), "",
                       f.get("desc_comprobante"), f.get("comprobante"), f.get("fecha_comprobante"), f.get("certificado"), None,
                       f.get("importe"), f.get("fecha_dj"), f"DESAPARECIÓ (estaba el {ca['desde']})"])
        for f in ca["cambiados"]:
            ws.append([f.get("agente"), f.get("fecha"), f.get("operacion"), f.get("regimen"), f.get("impuesto"), "",
                       f.get("desc_comprobante"), f.get("comprobante"), f.get("fecha_comprobante"), f.get("certificado"), None,
                       f.get("importe"), f.get("fecha_dj"), f"CAMBIÓ (antes {f.get('importe_anterior')})"])
        else:
            ws.append(["Sin movimientos" if DISPONIBLE[fu] else "Fuente todavía sin robot"])
        for i, w in enumerate((14, 11, 22, 10, 9, 10, 26, 18, 12, 18, 12, 14, 14, 26), 1):
            ws.column_dimensions[chr(64 + i)].width = w
        for r in ws.iter_rows(min_row=4, min_col=12, max_col=12):
            for c in r:
                c.number_format = "#,##0.00"
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def zip_mes(cuit: str, nombre: str, periodo: str, fuentes: list[str]) -> bytes:
    import zipfile
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", zipfile.ZIP_DEFLATED) as z:
        for fu in fuentes:
            if DISPONIBLE.get(fu):
                z.writestr(f"{periodo}_{fu}_{cuit}.xlsx", excel(cuit, nombre, periodo, [fu]))
        sal = saldos_anteriores(cuit, periodo)
        z.writestr(f"{periodo}_saldos_mes_anterior_{cuit}.txt",
                   "\n".join(f"{s['impuesto']}\t{s['detalle']}\t{s['importe']}\t{s['fuente']}" for s in sal) or "Sin saldos leídos")
    return b.getvalue()
