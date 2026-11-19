"""Asientos contables armados con lo que ya bajaron los robots (no entra a ningún organismo).

Pedido de Gaby (18 y 19/11/2026). Especificación completa en el documento "Robot fiscal — Especificación AGIP, ARBA,
SIFERE y asientos contables". Tipos:

  1. Sueldos (F.931, DATOS/<cuit>/f931/AAAA-MM.json):
       Sueldos (pérdida)            D  remuneración
       Cargas sociales (pérdida)    D  contribuciones (S.S. + O.S. + ART + seguro de vida + RENATRE)
       Sueldos a pagar              H  remuneración − aportes S.S. − aportes O.S.
       Cargas sociales a pagar      H  aportes + contribuciones (total del F.931)
     Remuneración: Rem. 1 + conceptos no remunerativos del F.931 (F.931 bajados antes del 19/11/2026: solo Rem. 1).

  2. Devengamiento de IIBB, por DDJJ y por jurisdicción:
       IIBB <jur> (pérdida)         D  impuesto determinado (siempre completo)
       SIRCREB <jur>                H  1° en consumirse
       Percepciones IIBB <jur>      H  2° (incluye aduaneras)
       Retenciones IIBB <jur>       H  3° y el faltante que se cubrió con saldo a favor anterior
       IIBB <jur> a pagar           H  saldo a ingresar de la DDJJ (sin intereses ni otros débitos)
     El Haber nunca supera el determinado: lo que sobra de créditos queda en el activo y lo ajusta el encargado al
     cierre del balance. Convenio: SIFERE (liquidación de cada jurisdicción). Local Buenos Aires: ARBA (por ahora solo
     el determinado: el asiento queda DESBALANCEADO hasta que el robot lea el detalle de créditos de ARBA).

  3. Pagos de impuestos: SIFERE -> Pagos (banco y fecha en el pago). Un asiento por fecha y banco, una línea por
     jurisdicción; intereses aparte (pérdida).

Los asientos que no cierran se muestran DESBALANCEADOS a la espera de revisión del encargado del cliente o del admin.
Las cuentas salen de la tabla de equivalencias de cada cliente (concepto -> cuenta del plan de cuentas de SOS Contador);
sin equivalencia se usa el nombre por defecto y el asiento queda marcado "sin cuenta asignada".
"""
from __future__ import annotations

import calendar
import glob
import json
import os
import re

from . import datos, usuarios

TIPOS = {"sueldos": "Sueldos (F.931)", "iibb": "Devengamiento IIBB", "pagos": "Pagos de impuestos",
         "cuentas": "Equivalencias de cuentas"}
JURISDICCIONES = {
    "901": "CABA", "902": "Buenos Aires", "903": "Catamarca", "904": "Córdoba", "905": "Corrientes",
    "906": "Chaco", "907": "Chubut", "908": "Entre Ríos", "909": "Formosa", "910": "Jujuy",
    "911": "La Pampa", "912": "La Rioja", "913": "Mendoza", "914": "Misiones", "915": "Neuquén",
    "916": "Río Negro", "917": "Salta", "918": "San Juan", "919": "San Luis", "920": "Santa Cruz",
    "921": "Santa Fe", "922": "Santiago del Estero", "923": "Tierra del Fuego", "924": "Tucumán",
}
TOLERANCIA = 0.01
_PER = re.compile(r"^\d{4}-\d{2}$")
_CONCEPTO = re.compile(r"^[a-z_]+(:[0-9]{3})?$|^banco:.{1,80}$")


def _jur(j: str) -> str:
    return JURISDICCIONES.get(j, j)


def nombre_defecto(concepto: str) -> str:
    """Nombre de la cuenta cuando el cliente no tiene equivalencia cargada."""
    base, _, j = concepto.partition(":")
    if base == "banco":
        return f"Banco {j}" if j else "Banco (a completar por el encargado)"
    fijos = {"sueldos": "Sueldos (pérdida)", "cargas_perdida": "Cargas sociales (pérdida)",
             "sueldos_a_pagar": "Sueldos a pagar", "cargas_a_pagar": "Cargas sociales a pagar",
             "intereses_iibb": "Intereses IIBB (pérdida)"}
    if base in fijos:
        return fijos[base]
    porjur = {"iibb_perdida": "Ingresos Brutos {} (pérdida)", "iibb_a_pagar": "Ingresos Brutos {} a pagar",
              "sircreb": "SIRCREB {}", "percepciones": "Percepciones IIBB {}", "retenciones": "Retenciones IIBB {}"}
    return porjur.get(base, base).format(_jur(j)) if j else porjur.get(base, base).format("").replace("  ", " ")


# ---------------------------------------------------------------- base de datos (misma web.db de los usuarios)
def _con():
    con = usuarios.conectar()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS cuentas_cliente (cuit TEXT, concepto TEXT, cuenta TEXT, actualizado TEXT, usuario TEXT,
        PRIMARY KEY (cuit, concepto));
    CREATE TABLE IF NOT EXISTS f931_manual (cuit TEXT, periodo TEXT, remuneracion REAL, cargas REAL, aportes REAL,
        nota TEXT, fecha TEXT, usuario TEXT, PRIMARY KEY (cuit, periodo));
    CREATE TABLE IF NOT EXISTS revision_asientos (clave TEXT PRIMARY KEY, cuit TEXT, estado TEXT, nota TEXT, fecha TEXT,
        usuario TEXT, nombre TEXT);
    """)
    return con


def cuentas(cuit: str) -> dict:
    con = _con()
    filas = con.execute("SELECT concepto, cuenta FROM cuentas_cliente WHERE cuit=?", (cuit,)).fetchall()
    con.close()
    return {c: v for c, v in filas if v}


def guardar_cuentas(cuit: str, valores: dict, usuario: str) -> int:
    """valores = {concepto: cuenta}; cuenta vacía = borrar la equivalencia. Devuelve cuántas quedaron guardadas."""
    con = _con()
    n = 0
    with con:
        for concepto, cuenta in valores.items():
            if not _CONCEPTO.match(concepto or ""):
                continue
            cuenta = re.sub(r"[\x00-\x1f<>]", "", (cuenta or "").strip())[:120]
            if cuenta:
                con.execute("INSERT OR REPLACE INTO cuentas_cliente VALUES (?,?,?,?,?)",
                            (cuit, concepto, cuenta, usuarios.ahora(), usuario))
                n += 1
            else:
                con.execute("DELETE FROM cuentas_cliente WHERE cuit=? AND concepto=?", (cuit, concepto))
    con.close()
    return n


def revisiones(cuit: str) -> dict:
    con = _con()
    filas = con.execute("SELECT clave, estado, nota, fecha, nombre FROM revision_asientos WHERE cuit=?", (cuit,)).fetchall()
    con.close()
    return {c: {"estado": e, "nota": n, "fecha": f, "nombre": no} for c, e, n, f, no in filas}


def marcar_revisado(clave: str, cuit: str, revisado: bool, nota: str, usuario: str, nombre: str) -> None:
    con = _con()
    with con:
        if revisado:
            con.execute("INSERT OR REPLACE INTO revision_asientos VALUES (?,?,?,?,?,?,?)",
                        (clave, cuit, "revisado", (nota or "")[:300], usuarios.ahora(), usuario, nombre))
        else:
            con.execute("DELETE FROM revision_asientos WHERE clave=? AND cuit=?", (clave, cuit))
    con.close()


# ---------------------------------------------------------------- F.931 con personal y sin remuneración leída
def f931_manual(cuit: str) -> dict:
    """{periodo: {remuneracion, cargas, aportes, nota, fecha, usuario}} cargado a mano por el encargado."""
    con = _con()
    filas = con.execute("SELECT periodo, remuneracion, cargas, aportes, nota, fecha, usuario FROM f931_manual WHERE cuit=?",
                        (cuit,)).fetchall()
    con.close()
    return {p: {"remuneracion": r or 0.0, "cargas": c or 0.0, "aportes": a or 0.0, "nota": n, "fecha": f, "usuario": u}
            for p, r, c, a, n, f, u in filas}


def guardar_f931_manual(cuit: str, periodo: str, rem, cargas, aportes, nota: str, usuario: str) -> None:
    con = _con()
    with con:
        if rem is None:
            con.execute("DELETE FROM f931_manual WHERE cuit=? AND periodo=?", (cuit, periodo))
        else:
            con.execute("INSERT OR REPLACE INTO f931_manual VALUES (?,?,?,?,?,?,?,?)",
                        (cuit, periodo, rem, cargas or 0.0, aportes or 0.0, (nota or "")[:300], usuarios.ahora(), usuario))
    con.close()


def f931_pendientes(cuit: str) -> list[dict]:
    """Meses con personal según la lista de DJ (Declaración en línea) en los que el robot no pudo tomar la
    remuneración (formulario sin leer, o sin Rem. 1 ni no remunerativo) y que el encargado todavía no completó."""
    lista = _leer(os.path.join(datos.DATOS, cuit, "f931", "_lista.json")) or {}
    man = f931_manual(cuit)
    out = []
    for per, v in sorted(lista.items()):
        n = int((v or {}).get("empleados") or 0)
        if not _PER.match(per) or not n or per in man:
            continue
        d = _leer(os.path.join(datos.DATOS, cuit, "f931", f"{per}.json"))
        rem = _n((d or {}).get("Remuneración total (con no remunerativos)", (d or {}).get("Remuneración total (Rem. 1)")))
        if d and rem:
            continue
        out.append({"periodo": per, "empleados": n,
                    "motivo": "no se pudo leer el formulario" if not d else "el formulario no tiene remuneración que el robot reconozca",
                    "estado": (v or {}).get("estado", "")})
    return out


def f931_con_manual(cuit: str) -> dict:
    """F.931 por mes con lo cargado a mano encima (para la relación D/C y los asientos)."""
    meses = _meses(cuit, "f931")
    for per, m in f931_manual(cuit).items():
        d = dict(meses.get(per) or {"Periodo": per})
        d["Remuneración total (con no remunerativos)"] = m["remuneracion"]
        d["TOTAL CARGAS SOCIALES"] = m["cargas"]
        d["Aportes S.S. (a1)"], d["Aportes O.S. (a1)"] = m["aportes"], 0.0
        d["Total aportes (retenidos al empleado)"] = m["aportes"]
        d["Carga manual"] = f"{m['usuario']} {str(m['fecha'])[:10]}"
        meses[per] = d
    return meses


def puede_revisar(cuit: str, usuario: str, rol: str) -> bool:
    """Revisan (y cargan cuentas) el encargado del cliente o un administrador."""
    return rol == "admin" or (usuarios.datos_cliente(cuit) or {}).get("encargado") == usuario


# ---------------------------------------------------------------- armado
def _leer(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _meses(cuit: str, carpeta: str) -> dict:
    out = {}
    for ruta in glob.glob(os.path.join(datos.DATOS, cuit, carpeta, "*.json")):
        per = os.path.basename(ruta)[:-5]
        d = _leer(ruta) if _PER.match(per) else None
        if isinstance(d, dict):
            out[per] = d
    return out


def _n(v) -> float:
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _fin_de_mes(per: str) -> str:
    a, m = map(int, per.split("-"))
    return f"{per}-{calendar.monthrange(a, m)[1]:02d}"


def _linea(concepto, debe=0.0, haber=0.0, detalle=""):
    return {"concepto": concepto, "debe": round(debe, 2), "haber": round(haber, 2), "detalle": detalle}


def _cerrar(a: dict, eq: dict, rev: dict) -> dict:
    """Completa cuentas, totales, estado de balance y revisión."""
    a["lineas"] = [l for l in a["lineas"] if l["debe"] or l["haber"] or l.get("forzar")]
    for l in a["lineas"]:
        l["cuenta"] = eq.get(l["concepto"]) or nombre_defecto(l["concepto"])
        l["asignada"] = l["concepto"] in eq
    a["debe"] = round(sum(l["debe"] for l in a["lineas"]), 2)
    a["haber"] = round(sum(l["haber"] for l in a["lineas"]), 2)
    a["diferencia"] = round(a["debe"] - a["haber"], 2)
    a["balanceado"] = abs(a["diferencia"]) < TOLERANCIA
    a["sin_cuenta"] = [l["cuenta"] for l in a["lineas"] if not l["asignada"]]
    a["revision"] = rev.get(a["clave"])
    a["estado"] = ("revisado" if a["revision"] else "desbalanceado" if not a["balanceado"]
                   else "sin cuenta asignada" if a["sin_cuenta"] else "listo")
    return a


def asientos_sueldos(cuit: str, eq: dict | None = None, rev: dict | None = None) -> list[dict]:
    eq = cuentas(cuit) if eq is None else eq
    rev = revisiones(cuit) if rev is None else rev
    out = []
    for per, d in sorted(f931_con_manual(cuit).items()):
        rem = _n(d.get("Remuneración total (con no remunerativos)", d.get("Remuneración total (Rem. 1)")))
        aportes = _n(d.get("Aportes S.S. (a1)")) + _n(d.get("Aportes O.S. (a1)"))
        contrib = _n(d.get("TOTAL CARGAS SOCIALES"))
        if not (rem or aportes or contrib):
            continue
        a = {"clave": f"sueldos:{per}", "tipo": "sueldos", "periodo": per, "fecha": _fin_de_mes(per),
             "leyenda": f"Sueldos y cargas sociales {per[5:]}/{per[:4]} (F.931)",
             "notas": [f"Importes cargados a mano por el encargado ({d['Carga manual']})"] if d.get("Carga manual") else [],
             "lineas": [_linea("sueldos", debe=rem, detalle="Remuneración del F.931"),
                        _linea("cargas_perdida", debe=contrib, detalle="Contribuciones, ART, seguro de vida, RENATRE"),
                        _linea("sueldos_a_pagar", haber=rem - aportes, detalle="Remuneración − aportes S.S. y O.S."),
                        _linea("cargas_a_pagar", haber=aportes + contrib, detalle="Total del F.931")]}
        out.append(_cerrar(a, eq, rev))
    return out


def devengamiento(det: float, liq: dict) -> tuple[list[dict], list[str]]:
    """Líneas del devengamiento de una jurisdicción a partir de la liquidación de la DDJJ (ver docstring)."""
    det = _n(det)
    notas = []
    intereses, otros = _n(liq.get("intereses")), _n(liq.get("otros_debitos"))
    a_ingresar = max(0.0, _n(liq.get("monto_a_ingresar")) - intereses - otros)
    a_pagar = min(det, a_ingresar)
    cubrir = round(det - a_pagar, 2)
    lineas, resto = [], cubrir
    for concepto, disp in (("sircreb", _n(liq.get("recaudaciones_bancarias"))),
                           ("percepciones", _n(liq.get("percepciones")) + _n(liq.get("percepciones_aduaneras"))),
                           ("retenciones", _n(liq.get("retenciones")))):
        uso = round(min(disp, resto), 2)
        resto = round(resto - uso, 2)
        lineas.append((concepto, uso))
    if resto > 0:                       # se cubrió con saldo a favor anterior: sale de Retenciones (regla de Gaby)
        lineas = [(c, round(u + resto, 2)) if c == "retenciones" else (c, u) for c, u in lineas]
        notas.append(f"${resto:,.2f} cubiertos con saldo a favor de DDJJ anteriores: se imputan a Retenciones")
    if intereses or otros:
        notas.append("La DDJJ tiene intereses u otros débitos: van en el asiento del pago, no en el devengamiento")
    return [("a_pagar", a_pagar)] + lineas, notas


def asientos_iibb(cuit: str, eq: dict | None = None, rev: dict | None = None) -> list[dict]:
    eq = cuentas(cuit) if eq is None else eq
    rev = revisiones(cuit) if rev is None else rev
    out = []
    for per, d in sorted(_meses(cuit, "sifere").items()):
        for j, v in sorted((d.get("jurisdicciones") or {}).items()):
            v = v or {}
            det = _n(v.get("determinado"))
            if not det:
                continue
            a = {"clave": f"iibb:{per}:{j}", "tipo": "iibb", "periodo": per, "fecha": _fin_de_mes(per),
                 "leyenda": f"Devengamiento IIBB {_jur(j)} {per[5:]}/{per[:4]} (Convenio Multilateral, rect. "
                            f"{d.get('rectificativa', 0)})", "notas": [], "jurisdiccion": j,
                 "lineas": [_linea(f"iibb_perdida:{j}", debe=det, detalle="Impuesto determinado")]}
            liq = v.get("liquidacion")
            if isinstance(liq, dict):
                partes, notas = devengamiento(det, liq)
                a["notas"] += notas
                textos = {"a_pagar": "Saldo a ingresar de la DDJJ", "sircreb": "Recaudaciones bancarias (SIRCREB)",
                          "percepciones": "Percepciones a deducir", "retenciones": "Retenciones soportadas"}
                for c, imp in partes:
                    clave = f"iibb_a_pagar:{j}" if c == "a_pagar" else f"{c}:{j}"
                    a["lineas"].append(_linea(clave, haber=imp, detalle=textos[c]))
            else:
                if v.get("a_pagar") is not None:
                    a["lineas"].append(_linea(f"iibb_a_pagar:{j}", haber=_n(v.get("a_pagar")), detalle="A pagar según la DDJJ"))
                a["notas"].append("Falta el detalle de retenciones, percepciones y SIRCREB de esta jurisdicción "
                                  + (f"({v['liquidacion_error']})" if v.get("liquidacion_error") else
                                     "(el robot lo baja en la próxima corrida de SIFERE)"))
            out.append(_cerrar(a, eq, rev))
    for per, d in sorted(_meses(cuit, "arba").items()):
        det = _n(d.get("impuesto_determinado"))
        if not det:
            continue
        a = {"clave": f"iibb:{per}:arba", "tipo": "iibb", "periodo": per, "fecha": _fin_de_mes(per), "jurisdiccion": "902",
             "leyenda": f"Devengamiento IIBB Buenos Aires {per[5:]}/{per[:4]} (ARBA, contribuyente local)",
             "notas": ["ARBA: el robot todavía no lee las retenciones, percepciones, SIRCREB ni el saldo a pagar "
                       "(detalle del período del Aviso de deuda). Completarlo a mano o esperar la próxima versión."],
             "lineas": [_linea("iibb_perdida:902", debe=det, detalle="Impuesto determinado (ARBA)")]}
        out.append(_cerrar(a, eq, rev))
    return sorted(out, key=lambda a: (a["periodo"], a["clave"]))


def _ultimo_pagos(cuit: str) -> dict:
    r = sorted(glob.glob(os.path.join(datos.DATOS, cuit, "sifere_pagos", "*.json")))
    return (_leer(r[-1]) or {}) if r else {}


def asientos_pagos(cuit: str, eq: dict | None = None, rev: dict | None = None) -> list[dict]:
    eq = cuentas(cuit) if eq is None else eq
    rev = revisiones(cuit) if rev is None else rev
    grupos: dict = {}
    for j, v in (_ultimo_pagos(cuit).get("jurisdicciones") or {}).items():
        for p in (v or {}).get("pagos") or []:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.get("fecha") or ""):
                continue
            grupos.setdefault((p["fecha"], p.get("banco") or ""), []).append((j, p))
    out = []
    for (fecha, banco), pagos in sorted(grupos.items()):
        lineas, total = [], 0.0
        for j, p in sorted(pagos, key=lambda x: (x[0], x[1].get("anticipo", ""))):
            lineas.append(_linea(f"iibb_a_pagar:{j}", debe=_n(p.get("impuesto")),
                                 detalle=f"Anticipo {p.get('anticipo', '')[5:]}/{p.get('anticipo', '')[:4]} {_jur(j)}"))
            if _n(p.get("intereses")):
                lineas.append(_linea("intereses_iibb", debe=_n(p.get("intereses")), detalle=f"Intereses {_jur(j)}"))
            total += _n(p.get("total"))
        lineas.append(_linea(f"banco:{banco}", haber=round(total, 2), detalle=f"{banco or 'Banco'} {pagos[0][1].get('forma_pago', '')}".strip()))
        a = {"clave": f"pagos:{fecha}:{banco}", "tipo": "pagos", "periodo": fecha[:7], "fecha": fecha, "notas": [],
             "leyenda": f"Pago IIBB Convenio Multilateral {fecha[8:]}/{fecha[5:7]}/{fecha[:4]} ({len(pagos)} jurisdicción/es)",
             "lineas": lineas}
        out.append(_cerrar(a, eq, rev))
    return out


ARMADORES = {"sueldos": asientos_sueldos, "iibb": asientos_iibb, "pagos": asientos_pagos}


def armar(cuit: str, tipo: str) -> list[dict]:
    eq, rev = cuentas(cuit), revisiones(cuit)
    return ARMADORES[tipo](cuit, eq, rev)


def conceptos_usados(cuit: str) -> list[dict]:
    """Conceptos que aparecen en los asientos del cliente (para la pantalla de equivalencias)."""
    eq, rev = cuentas(cuit), revisiones(cuit)
    vistos: dict = {}
    for tipo, fn in ARMADORES.items():
        for a in fn(cuit, eq, rev):
            for l in a["lineas"]:
                vistos.setdefault(l["concepto"], set()).add(TIPOS[tipo])
    base = ["sueldos", "cargas_perdida", "sueldos_a_pagar", "cargas_a_pagar"]
    for c in base:
        vistos.setdefault(c, set())
    for c in eq:
        vistos.setdefault(c, set())
    orden = {c: i for i, c in enumerate(base)}
    return [{"concepto": c, "defecto": nombre_defecto(c), "cuenta": eq.get(c, ""), "usado_en": sorted(t)}
            for c, t in sorted(vistos.items(), key=lambda x: (orden.get(x[0], 99), x[0]))]


def excel(cuit: str, razon: str, tipo: str, lista: list[dict]):
    """Planilla con los asientos (formato provisorio hasta tener el modelo de importación de SOS Contador)."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Asientos"
    ws.append([f"{TIPOS[tipo]} — {razon or ''} ({datos.cuit_fmt(cuit)})"])
    ws.append(["Formato provisorio: se adapta a la planilla de importación de SOS Contador cuando esté disponible."])
    ws.append([])
    cab = ["Nº", "Fecha", "Leyenda", "Cuenta", "Concepto", "Debe", "Haber", "Detalle", "Estado"]
    ws.append(cab)
    for c in ws[4]:
        c.font = Font(bold=True)
    rojo = PatternFill("solid", fgColor="FDE2E1")
    for n, a in enumerate(lista, 1):
        for l in a["lineas"]:
            ws.append([n, a["fecha"], a["leyenda"], l["cuenta"], l["concepto"], l["debe"] or None, l["haber"] or None,
                       l["detalle"], a["estado"]])
            if not a["balanceado"]:
                for c in ws[ws.max_row]:
                    c.fill = rojo
        if not a["balanceado"]:
            ws.append([n, a["fecha"], "DESBALANCEADO — diferencia", "", "", None, None, a["diferencia"], a["estado"]])
            for c in ws[ws.max_row]:
                c.fill = rojo
    for col, ancho in zip("ABCDEFGHI", (5, 11, 52, 34, 22, 15, 15, 40, 18)):
        ws.column_dimensions[col].width = ancho
    for fila in ws.iter_rows(min_row=5, min_col=6, max_col=7):
        for c in fila:
            c.number_format = "#,##0.00"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
