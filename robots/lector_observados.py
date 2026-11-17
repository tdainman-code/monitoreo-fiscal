"""Lector de "Comprobantes electrónicos observados" (Nuestra Parte -> Mensajes de cumplimiento).

ARCA lista ahí los comprobantes recibidos de proveedores que, según infiere, no tendrían capacidad
técnico-económica (facturas apócrifas / APOC): no se deben computar como crédito fiscal ni deducción.
Exportación XLSX (relevada el 16/11/2026), hoja "Data":
  Tipo de comprobante | Importe Total Comprobante | Cuit del emisor | Denominación del emisor |
  Punto de venta | Nro. de comprobante | Fecha de emisión | Importe IVA
Importes como texto "$   13.942.830,00"; punto de venta y número con espacios y ceros a la izquierda.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

TIPOS = {"factura a": 1, "nota de débito a": 2, "nota de debito a": 2, "nota de crédito a": 3,
         "nota de credito a": 3, "recibo a": 4, "factura b": 6, "nota de débito b": 7, "nota de crédito b": 8,
         "factura c": 11, "nota de débito c": 12, "nota de crédito c": 13, "factura m": 51,
         "nota de débito m": 52, "nota de crédito m": 53, "factura de crédito electrónica mipymes (fce) a": 201,
         "nota de débito electrónica mipymes (fce) a": 202, "nota de crédito electrónica mipymes (fce) a": 203}


def _importe(v) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    if not s:
        return 0.0
    return float(s.replace(".", "").replace(",", "."))


def _entero(v) -> int:
    s = re.sub(r"\D", "", str(v or ""))
    return int(s) if s else 0


def _fecha(v):
    if hasattr(v, "date"):
        return v.date()
    try:
        return datetime.strptime(str(v).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def leer(ruta: str) -> list[dict]:
    from openpyxl import load_workbook
    wb = load_workbook(ruta, read_only=True, data_only=True)
    ws = wb["Data"] if "Data" in wb.sheetnames else wb.worksheets[0]
    filas = list(ws.iter_rows(values_only=True))
    if not filas:
        return []
    cab = [str(c or "").strip().lower() for c in filas[0]]

    def col(*nombres):
        for n in nombres:
            for i, c in enumerate(cab):
                if c.startswith(n):
                    return i
        raise ValueError(f"Comprobantes observados: falta la columna {nombres[0]} (columnas: {cab})")
    i_tipo, i_tot, i_cuit, i_nom = col("tipo de comprobante"), col("importe total"), col("cuit"), col("denominaci")
    i_pv, i_num, i_fecha, i_iva = col("punto de venta"), col("nro. de comprobante", "nro"), col("fecha"), col("importe iva")
    out = []
    for f in filas[1:]:
        if not f or not any(f):
            continue
        tipo_txt = str(f[i_tipo] or "").strip()
        out.append({"tipo_txt": tipo_txt, "tipo": TIPOS.get(tipo_txt.lower(), 0),
                    "nc": "crédito" in tipo_txt.lower() or "credito" in tipo_txt.lower(),
                    "total": _importe(f[i_tot]), "iva": _importe(f[i_iva]),
                    "cuit": re.sub(r"\D", "", str(f[i_cuit] or "")), "nombre": str(f[i_nom] or "").strip(),
                    "punto_venta": _entero(f[i_pv]), "numero": _entero(f[i_num]), "fecha": _fecha(f[i_fecha])})
    # Facturas anuladas con nota de crédito del mismo emisor y mismo importe (caso Shoganai 57/58 con NC 2/3)
    ncs = [c for c in out if c["nc"]]
    for c in out:
        c["anulada_con"] = ""
    for nc in ncs:
        for c in out:
            if (not c["nc"] and not c["anulada_con"] and c["cuit"] == nc["cuit"]
                    and abs(c["total"] - nc["total"]) < 0.01 and (not c["fecha"] or not nc["fecha"] or c["fecha"] <= nc["fecha"])):
                c["anulada_con"] = f"NC {nc['punto_venta']:04d}-{nc['numero']:08d}"
                nc["anulada_con"] = f"anula FC {c['punto_venta']:04d}-{c['numero']:08d}"
                break
    return out


if __name__ == "__main__":
    for c in leer(sys.argv[1]):
        print(c)
