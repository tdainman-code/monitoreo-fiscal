"""Planilla para asignar los clientes a cada empleado (encargado + equipo), pedido del 18/11/2026.

Se baja desde la web ya completa con todos los clientes y lo asignado hoy; se completa en Excel y se sube.
Hojas: "Clientes" (CUIT | Razón social | Encargado | Equipo) y "Usuarios" (los usuarios activos, con desplegable).
Al importar: solo cambia encargado y equipo; el resto de los datos del cliente queda como estaba.
Una celda de Encargado VACÍA deja al cliente sin encargado (lo ven solo los administradores y su equipo).
"""
from __future__ import annotations

import io
import re

TITULOS = ["CUIT", "Razón social", "Encargado", "Equipo (también lo llevan)"]


def _cuit(v) -> str:
    return re.sub(r"\D", "", str(v if v is not None else "").split(".")[0] if isinstance(v, float) else str(v or ""))


def generar(clientes: list[dict], asignado: dict, usuarios: list[tuple]) -> bytes:
    """clientes: [{cuit, razon_social}]; asignado: {cuit: {encargado, equipo}}; usuarios: [(usuario, nombre, rol)]."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = "Clientes"
    ws.append(TITULOS)
    for c in sorted(clientes, key=lambda x: (x.get("razon_social") or "~", x["cuit"])):
        a = asignado.get(c["cuit"]) or {}
        ws.append([f"{c['cuit'][:2]}-{c['cuit'][2:10]}-{c['cuit'][10]}", c.get("razon_social") or "",
                   a.get("encargado") or "", a.get("equipo") or ""])
    for j, cel in enumerate(ws[1], 1):
        cel.font = Font(bold=True, color="FFFFFF")
        cel.fill = PatternFill("solid", fgColor="1F4E78")
        cel.alignment = Alignment(horizontal="center", wrap_text=True)
    for col, ancho in zip("ABCD", (16, 46, 18, 34)):
        ws.column_dimensions[col].width = ancho
    ws.freeze_panes = "A2"
    wu = wb.create_sheet("Usuarios")
    wu.append(["Usuario (va en Encargado / Equipo)", "Nombre", "Rol"])
    for u in usuarios:
        wu.append([u[0], u[1] or "", "administrador" if u[2] == "admin" else "empleado"])
    for cel in wu[1]:
        cel.font = Font(bold=True)
    wu.column_dimensions["A"].width = 34
    wu.column_dimensions["B"].width = 30
    if usuarios:
        dv = DataValidation(type="list", formula1=f"=Usuarios!$A$2:$A${len(usuarios) + 1}", allow_blank=True,
                            showErrorMessage=True, errorTitle="Usuario inexistente",
                            error="Elegí un usuario de la lista (hoja Usuarios)")
        ws.add_data_validation(dv)
        dv.add(f"C2:C{max(ws.max_row, 2) + 500}")
    wi = wb.create_sheet("Instrucciones")
    for t in ["Cómo usar esta planilla",
              "1. En 'Encargado' poné el USUARIO (no el nombre) de quien lleva el cliente: hay un desplegable con los usuarios.",
              "2. En 'Equipo' (opcional) los otros usuarios que también lo ven, separados por coma. Ej.: ana, beto",
              "3. Encargado vacío = el cliente queda sin encargado (lo ven solo los administradores y su equipo).",
              "4. Podés borrar filas de clientes que no quieras tocar: solo se cambian los que estén en la planilla.",
              "5. No cambies la columna CUIT. Razón social es solo de referencia.",
              "6. Guardá y subila en la web: Más → Asignar clientes → Subir planilla.",
              "Los administradores ven siempre todos los clientes: no hace falta asignárselos."]:
        wi.append([t])
    wi["A1"].font = Font(bold=True, size=13)
    wi.column_dimensions["A"].width = 110
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def leer(contenido: bytes, validos: set[str]) -> tuple[dict, list[str]]:
    """Devuelve ({cuit: {encargado, equipo}}, errores). Usuarios que no existen se informan y no se asignan."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True)
    except Exception:
        return {}, ["El archivo no es una planilla de Excel (.xlsx) válida"]
    ws = next((w for w in wb.worksheets if w.title.strip().lower() == "clientes"), wb.worksheets[0])
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return {}, ["La planilla está vacía"]
    cab = [str(c or "").strip().lower() for c in filas[0]]
    col = lambda pal, defecto: next((i for i, c in enumerate(cab) if c.startswith(pal)), defecto)
    i_c, i_e, i_q = col("cuit", 0), col("encargado", 2), col("equipo", 3)
    out, err = {}, []
    for n, f in enumerate(filas[1:], 2):
        f = list(f) + [None] * 5
        cuit = _cuit(f[i_c])
        if not cuit:
            continue
        if not re.fullmatch(r"\d{11}", cuit):
            err.append(f"Fila {n}: CUIT inválido ({f[i_c]})")
            continue
        enc = str(f[i_e] or "").strip().lower()
        if enc and enc not in validos:
            err.append(f"Fila {n} ({cuit}): el encargado '{enc}' no es un usuario activo; ese cliente no se cambió")
            continue
        equipo, malos = [], []
        for u in re.split(r"[,;/\s]+", str(f[i_q] or "").strip().lower()):
            if not u or u == enc:
                continue
            (equipo if u in validos else malos).append(u)
        if malos:
            err.append(f"Fila {n} ({cuit}): en el equipo no existen {', '.join(malos)} (se ignoraron)")
        out[cuit] = {"encargado": enc, "equipo": ", ".join(sorted(set(equipo)))}
    return out, err
