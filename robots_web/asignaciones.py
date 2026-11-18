"""Planilla de CLIENTES: alta y datos de todos los clientes de una vez (pedidos del 18/11/2026).

Se baja desde la web (Más -> Planilla de clientes) ya completa con todos los clientes, quién los lleva y sus datos;
se completa en Excel y se sube. Sirve para:
  - asignar encargado y equipo (cada colaborador ve solo los clientes que lleva);
  - cargar o corregir los datos del cliente (condición frente al IVA, mails, teléfonos, medios de pago del VEP, etc.);
  - cargar CLAVES (ARCA, CIT de ARBA, AGIP) y dar de alta clientes nuevos (hace falta la clave de ARCA).
Reglas al subirla:
  - Celda VACÍA = no cambia nada. Para borrar un dato, escribir un guion: -
  - Las claves NUNCA se bajan (las columnas de claves vienen vacías) y la web no las guarda: cada una se cifra al
    instante para el robot, igual que en la pantalla de Claves. El archivo subido no se guarda.
"""
from __future__ import annotations

import io
import re

FIJAS = [("cuit", "CUIT"), ("razon_social", "Razón social"), ("encargado", "Encargado (usuario)"),
         ("equipo", "Equipo (usuarios, separados por coma)")]
CLAVES = [("u_ARCA", "Usuario ARCA (solo si entra con OTRA CUIT)"), ("k_ARCA", "Clave fiscal ARCA"),
          ("k_ARBA", "CIT ARBA"), ("k_AGIP", "Clave Ciudad AGIP")]
SALTAR = {"encargado", "equipo"}           # ya están en FIJAS


def _cuit(v) -> str:
    if isinstance(v, float):
        v = int(v)
    return re.sub(r"\D", "", str(v or ""))


def columnas(campos: dict) -> list[tuple[str, str]]:
    return FIJAS + [(k, t) for k, t in campos.items() if k not in SALTAR] + CLAVES


def generar(clientes: list[dict], datos_de: dict, usuarios: list[tuple], campos: dict, opciones: dict,
            medios_vep: list[str]) -> bytes:
    """clientes: [{cuit, razon_social}]; datos_de: {cuit: datos del cliente}; usuarios: [(usuario, nombre, rol)]."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.datavalidation import DataValidation
    cols = columnas(campos)
    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append([t for _, t in cols])
    for c in sorted(clientes, key=lambda x: ((x.get("razon_social") or "~").upper(), x["cuit"])):
        d = datos_de.get(c["cuit"]) or {}
        fila = []
        for k, _ in cols:
            if k == "cuit":
                fila.append(f"{c['cuit'][:2]}-{c['cuit'][2:10]}-{c['cuit'][10]}")
            elif k == "razon_social":
                fila.append(c.get("razon_social") or "")
            elif k.startswith(("u_", "k_")):
                fila.append("")                             # las claves nunca se bajan
            else:
                fila.append(d.get(k) or "")
        ws.append(fila)
    azul, ambar = PatternFill("solid", fgColor="1F4E78"), PatternFill("solid", fgColor="9C5700")
    for j, (k, _) in enumerate(cols, 1):
        cel = ws.cell(1, j)
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = ambar if k.startswith(("u_", "k_")) else azul
        cel.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(j)].width = {"cuit": 15, "razon_social": 40, "observaciones": 40,
                                                            "emails": 32, "medios_vep": 32}.get(k, 20)
    ws.row_dimensions[1].height = 45
    ws.freeze_panes = "C2"
    hasta = max(ws.max_row, 2) + 1000
    listas = wb.create_sheet("Listas")
    listas.append(["Usuarios"] + [titulo for k, titulo in cols if k in opciones])
    col_lista = {}
    valores = [[u[0] for u in usuarios]] + [[o for o in opciones[k] if o] for k, _ in cols if k in opciones]
    for j, vals in enumerate(valores, 1):
        for i, v in enumerate(vals, 2):
            listas.cell(i, j, v)
    col_lista["encargado"] = ("A", len(usuarios))
    for j, (k, _) in enumerate([c for c in cols if c[0] in opciones], 2):
        col_lista[k] = (get_column_letter(j), len([o for o in opciones[k] if o]))
    for j, (k, _) in enumerate(cols, 1):
        if k in col_lista and col_lista[k][1]:
            letra, n = col_lista[k]
            dv = DataValidation(type="list", formula1=f"=Listas!${letra}$2:${letra}${n + 1}", allow_blank=True,
                                showErrorMessage=True, errorTitle="Valor no válido", error="Elegí un valor de la lista")
            ws.add_data_validation(dv)
            dv.add(f"{get_column_letter(j)}2:{get_column_letter(j)}{hasta}")
    wu = wb.create_sheet("Usuarios")
    wu.append(["Usuario (va en Encargado / Equipo)", "Nombre", "Rol"])
    for u in usuarios:
        wu.append([u[0], u[1] or "", "administrador (ve todos)" if u[2] == "admin" else "colaborador"])
    wu.column_dimensions["A"].width = 34
    wu.column_dimensions["B"].width = 30
    wi = wb.create_sheet("Instrucciones")
    for t in ["Cómo usar esta planilla",
              "• Una fila por cliente. No cambies la columna CUIT de los clientes que ya están.",
              "• Celda VACÍA = no se cambia nada. Para BORRAR un dato escribí un guion:  -",
              "• Encargado: el USUARIO (no el nombre) de quien lleva el cliente; hay un desplegable. Equipo: otros usuarios que "
              "también lo ven, separados por coma (ej.: ana, beto). Los administradores ven siempre todo.",
              f"• Medios de pago del VEP: uno o varios separados por coma: {', '.join(medios_vep)}.",
              "• Mails: separados por coma. Teléfonos: como quieras (ej.: 11 4444-5555, 11 15 6666-7777).",
              "• CLIENTE NUEVO: agregá una fila con CUIT, Razón social y la Clave fiscal de ARCA (sin la clave de ARCA no se puede dar de alta).",
              "• CLAVES (columnas naranjas): completalas solo para cargar o cambiar una clave. Al bajar la planilla vienen siempre vacías.",
              "  'Usuario ARCA' solo si el cliente entra con la clave de OTRA persona (apoderado): poné esa CUIT.",
              "• SEGURIDAD: si escribiste claves, después de subir la planilla BORRÁ el archivo y no lo mandes por mail ni WhatsApp.",
              "  La web no guarda el archivo ni las claves: cada clave se cifra al instante y solo el robot la puede abrir.",
              "• Subila en la web: Más → Planilla de clientes → Subir planilla. Te muestra qué cambió y qué filas tuvieron problemas."]:
        wi.append([t])
    wi["A1"].font = Font(bold=True, size=13)
    wi.column_dimensions["A"].width = 130
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _medios(txt: str, medios_vep: list[str]) -> tuple[str, list[str]]:
    pistas = [(r"banelco|mis\s*cuentas|pmc", "Banelco"), (r"red\s*link|\blink\b|^pagar", "Link"),
              (r"interbanking", "Interbanking"), (r"\bxn\b|xn\s*group", "XN")]
    elegidos, malos = set(), []
    for parte in [p.strip() for p in re.split(r"[,;]", txt) if p.strip()]:
        m = next((m for m in medios_vep if m.lower() == parte.lower()), None)
        if not m:
            pista = next((clave for pat, clave in pistas if re.search(pat, parte, re.I)), None)
            m = next((m for m in medios_vep if pista and pista.lower() in m.lower()), None)
        if m:
            elegidos.add(m)
        else:
            malos.append(parte)
    return ", ".join(m for m in medios_vep if m in elegidos), malos


def leer(contenido: bytes, validos: set[str], campos: dict, opciones: dict, medios_vep: list[str]) -> tuple[dict, list[str]]:
    """Devuelve ({cuit: {"datos": {campo: valor}, "razon_social": str, "claves": {org: (usuario, clave)}}}, errores).
    En "datos" solo van los campos a cambiar (valor "" = borrar). Los errores nunca muestran claves."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception:
        return {}, ["El archivo no es una planilla de Excel (.xlsx) válida"]
    ws = next((w for w in wb.worksheets if w.title.strip().lower() == "clientes"), wb.worksheets[0])
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return {}, ["La planilla está vacía"]
    titulo_a_clave = {t.strip().lower(): k for k, t in columnas(campos)}
    cab = [titulo_a_clave.get(str(c or "").strip().lower()) for c in filas[0]]
    if "cuit" not in cab:
        return {}, ["No encontré la columna CUIT: usá la planilla que se baja de la web"]
    out, err = {}, []
    for n, f in enumerate(filas[1:], 2):
        v = {k: f[i] for i, k in enumerate(cab) if k and i < len(f)}
        cuit = _cuit(v.get("cuit"))
        if not cuit:
            continue
        if not re.fullmatch(r"\d{11}", cuit):
            err.append(f"Fila {n}: CUIT inválido ({v.get('cuit')})")
            continue
        txt = lambda k: str(v.get(k) if v.get(k) is not None else "").strip()
        d = {}
        enc = txt("encargado").lower()
        if enc == "-":
            d["encargado"] = ""
        elif enc:
            if enc in validos:
                d["encargado"] = enc
            else:
                err.append(f"Fila {n} ({cuit}): el encargado '{enc}' no es un usuario activo (no se cambió el encargado)")
        eq = txt("equipo").lower()
        if eq == "-":
            d["equipo"] = ""
        elif eq:
            us = [u for u in re.split(r"[,;/\s]+", eq) if u]
            malos = [u for u in us if u not in validos]
            if malos:
                err.append(f"Fila {n} ({cuit}): en el equipo no existen {', '.join(malos)} (se ignoraron)")
            d["equipo"] = ", ".join(sorted({u for u in us if u in validos and u != d.get("encargado", enc)}))
        for k in campos:
            if k in SALTAR:
                continue
            t = txt(k)
            if not t:
                continue
            if t == "-":
                d[k] = ""
            elif k in opciones:
                op = next((o for o in opciones[k] if o and o.lower() == t.lower()), None)
                if op:
                    d[k] = op
                else:
                    err.append(f"Fila {n} ({cuit}): '{t}' no es una opción válida para {campos[k]} (no se cambió)")
            elif k == "medios_vep":
                val, malos = _medios(t, medios_vep)
                if malos:
                    err.append(f"Fila {n} ({cuit}): medios de pago no reconocidos: {', '.join(malos)}")
                d[k] = val
            elif k == "emails":
                mails = [m.strip() for m in re.split(r"[,;\s]+", t) if m.strip()]
                malos = [m for m in mails if not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", m)]
                if malos:
                    err.append(f"Fila {n} ({cuit}): mails no válidos: {', '.join(malos)} (se ignoraron)")
                d[k] = ", ".join(m for m in mails if m not in malos)
            else:
                d[k] = t[:500]
        cl = {}
        u_arca = _cuit(v.get("u_ARCA"))
        for org in ("ARCA", "ARBA", "AGIP"):
            k = v.get(f"k_{org}")
            if k is None or str(k).strip() == "":
                continue
            clave = str(int(k)) if isinstance(k, float) and k.is_integer() else str(k).strip()
            cl[org] = (u_arca if org == "ARCA" else "", clave)
        out[cuit] = {"datos": d, "razon_social": txt("razon_social"), "claves": cl, "fila": n}
    return out, err
