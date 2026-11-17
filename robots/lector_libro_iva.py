"""Lector del Libro IVA exportado desde el Portal IVA (botón "XML" de la vista previa de una DJ presentada).

El zip que baja ARCA (relevado el 16/11/2026, período 11/2025) trae:
  comprobantes_compras.csv   un renglón por comprobante (incluye despachos, servicios públicos, B y C)
  comprobantes_ventas.csv    un renglón por comprobante (incluye tiques de controlador fiscal)
  libro_iva.xml              totales de la DJ (se usan como CONTROL de lo leído en los CSV)
  liva_export.xsd            esquema

Devuelve el resumen con las MISMAS claves que lector_mis_comprobantes.resumir(), para que la relación
débito/crédito pueda usar una u otra fuente sin cambiar nada más.

Uso de prueba:
    python3 -m robots.lector_libro_iva libro_iva_periodo_202511_original_1.zip
"""
from __future__ import annotations

import csv
import io
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

# B y C (sin IVA discriminado). Para el gasto se toma el importe total (pedido del 16/11/2026).
TIPOS_B_C = {6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 82, 111, 113, 114, 206, 207, 208, 211, 212, 213}
NOTAS_CREDITO = {3, 8, 13, 53, 110, 112, 113, 114, 203, 208, 213}
TOL_ABS, TOL_REL = 1.0, 0.0001

ALICUOTAS = ["0%", "2,5%", "5%", "10,5%", "21%", "27%"]
PERCEPCIONES = ["Importe de Per. o Pagos a Cta. de Otros Imp. Nac.", "Importe de Percepciones de Ingresos Brutos",
                "Importe de Impuestos Municipales", "Importe de Percepciones o Pagos a Cuenta de IVA",
                "Percepción a No Categorizados"]
# Combustibles y otros costos que no son percepciones (en el Libro IVA el impuesto a los combustibles
# de las estaciones de servicio viene en "Importe Otros Tributos": caso Estación Fratelli, nov-25).
OTROS_COSTOS = ["Importe Otros Tributos", "Importe de Impuestos Internos"]


def _num(x) -> float:
    x = (x or "").strip()
    if not x:
        return 0.0
    return float(x.replace(".", "").replace(",", ".")) if "," in x else float(x)


def _decodificar(crudo: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return crudo.decode(enc)
        except UnicodeDecodeError:
            continue
    return crudo.decode("latin-1", errors="replace")


def _filas(texto: str) -> list[dict]:
    lector = csv.DictReader(io.StringIO(texto), delimiter=";")
    lector.fieldnames = [c.strip() for c in (lector.fieldnames or [])]
    return [{k: (v or "").strip() for k, v in f.items() if k} for f in lector]


def _xml_totales(texto: str) -> dict:
    raiz = ET.fromstring(texto)
    sin_ns = lambda t: t.split("}")[-1]
    plano: dict = {}

    def recorrer(nodo, camino):
        hijos = list(nodo)
        if not hijos:
            try:
                plano["/".join(camino)] = float(nodo.text) if nodo.text and re.fullmatch(r"-?[\d.]+", nodo.text.strip()) \
                    else (nodo.text or "").strip()
            except ValueError:
                plano["/".join(camino)] = (nodo.text or "").strip()
        for h in hijos:
            recorrer(h, camino + [sin_ns(h.tag)])
    recorrer(raiz, [])
    return plano


def _x(xml: dict, sufijo: str) -> float:
    """Suma de todos los nodos cuyo camino termina en 'sufijo' (p. ej. 'totales_compras/total_computable')."""
    return sum(v for k, v in xml.items() if k.endswith(sufijo) and isinstance(v, float))


def _comprobante(f: dict, lado: str) -> dict:
    tipo = int(f.get("Tipo de Comprobante") or 0)
    tc = _num(f.get("Tipo de Cambio")) or 1.0
    moneda = f.get("Moneda Original") or "PES"
    c = {
        "fecha": f.get("Fecha de Emisión") or f.get("Fecha de Emision") or "",
        "tipo": tipo, "punto_venta": int(_num(f.get("Punto de Venta"))),
        "numero": int(_num(f.get("Número de Comprobante") or f.get("Numero de Comprobante"))),
        "cuit": re.sub(r"\D", "", f.get(f"Nro. Doc. {lado}", "")),
        "nombre": f.get(f"Denominación {lado}", ""),
        "moneda": moneda, "tipo_cambio": tc,
        "total": _num(f.get("Importe Total")),
        "no_gravado": _num(f.get("Importe No Gravado")), "exento": _num(f.get("Importe Exento")),
        "percepciones": sum(_num(f.get(k)) for k in PERCEPCIONES),
        "otros_costos": sum(_num(f.get(k)) for k in OTROS_COSTOS),
        "credito_computable": _num(f.get("Crédito Fiscal Computable")),
    }
    for a in ALICUOTAS:
        c[f"neto {a}"] = _num(f.get(f"Neto Gravado IVA {a}"))
        c[f"iva {a}"] = _num(f.get(f"Importe IVA {a}"))
    c["neto"] = _num(f.get("Total Neto Gravado"))
    c["iva"] = sum(c[f"iva {a}"] for a in ALICUOTAS) or _num(f.get("Total IVA"))
    # Notas de crédito: en el Libro IVA ya vienen en negativo; si alguna viniera en positivo, se da vuelta.
    if tipo in NOTAS_CREDITO and c["total"] > 0:
        for k, v in list(c.items()):
            if isinstance(v, float) and k != "tipo_cambio":
                c[k] = -v
    c["b_c"] = tipo in TIPOS_B_C or (not c["neto"] and not c["iva"] and not c["no_gravado"] and not c["exento"])
    return c


def _en_pesos(c: dict) -> dict:
    if c["moneda"] in ("PES", "") or c["tipo_cambio"] in (0, 1):
        return c
    d = dict(c)
    for k, v in c.items():
        if isinstance(v, float) and k != "tipo_cambio":
            d[k] = v * c["tipo_cambio"]
    return d


def _resumir(comps: list[dict], periodo: str, compras: bool) -> dict:
    a = [c for c in comps if not c["b_c"]] if compras else comps
    bc = [c for c in comps if c["b_c"]] if compras else []
    s = lambda lista, k: round(sum(c[k] for c in lista), 2)
    r = {
        "Neto gravado 21%": s(a, "neto 21%"),
        "Neto gravado 10,5%": s(a, "neto 10,5%"),
        "Neto gravado 27%": s(a, "neto 27%"),
        "Neto gravado otras alícuotas": round(s(a, "neto 0%") + s(a, "neto 2,5%") + s(a, "neto 5%"), 2),
        "Neto gravado total": s(a, "neto"),
        "IVA 21%": s(a, "iva 21%"), "IVA 10,5%": s(a, "iva 10,5%"), "IVA 27%": s(a, "iva 27%"),
        "IVA otras alícuotas": round(s(a, "iva 2,5%") + s(a, "iva 5%"), 2),
        "Total IVA": s(a, "iva"),
        "No gravado": s(a, "no_gravado"), "Exento": s(a, "exento"),
        "Otros tributos / percepciones": s(a, "percepciones"),
        "TOTAL COMPROBANTES": s(comps, "total"),
        "Cantidad de comprobantes": len(comps),
    }
    if compras:
        r["Impuesto a los combustibles"] = s(a, "otros_costos")       # combustibles / internos / otros tributos
        r["  de ello estimado a confirmar"] = 0.0                     # en el Libro IVA viene informado, no estimado
        r["Comprobantes B/C (sin IVA discriminado)"] = s(bc, "total")
        r["Crédito fiscal computable"] = s(a, "credito_computable")
    else:
        r["Ventas a consumidor final (sin identificar)"] = round(sum(c["total"] for c in comps if not c["cuit"].strip("0")), 2)
    return r


def leer_zip(ruta_o_bytes) -> dict:
    """Devuelve {'periodo','secuencia','codigo','ventas':{resumen},'compras':{resumen},
    'comprobantes_compras':[...], 'control':{...}, 'alertas':[...]}"""
    z = zipfile.ZipFile(io.BytesIO(ruta_o_bytes) if isinstance(ruta_o_bytes, bytes) else ruta_o_bytes)
    nombres = {n.lower().split("/")[-1]: n for n in z.namelist()}
    faltan = [n for n in ("comprobantes_compras.csv", "comprobantes_ventas.csv", "libro_iva.xml") if n not in nombres]
    if faltan:
        raise ValueError(f"El zip del Libro IVA no trae {faltan} (trae {z.namelist()})")
    leer = lambda n: _decodificar(z.read(nombres[n]))
    xml = _xml_totales(leer("libro_iva.xml"))
    per = xml.get("info_presentacion/periodo", "")
    per = str(int(per)) if isinstance(per, float) else str(per)
    periodo = f"{per[:4]}-{per[4:6]}" if re.fullmatch(r"\d{6}", per) else ""
    compras = [_comprobante(f, "Vendedor") for f in _filas(leer("comprobantes_compras.csv"))]
    ventas = [_comprobante(f, "Comprador") for f in _filas(leer("comprobantes_ventas.csv"))]

    # ---- control contra los totales de la DJ (XML)
    cf_xml = (_x(xml, "totales_compras/total_computable") + _x(xml, "totales_bienes_usados/total_computable")
              + _x(xml, "totales_importacion_bienes/total_computable")
              - _x(xml, "totales_compras_mlcf_restituir/total_computable"))
    # Débito neto de la DJ = débitos − restituciones (notas de crédito emitidas, "*_rest_deb_fiscal"): en el CSV
    # las notas de crédito ya vienen en negativo (relevado con Gaby, 17/11/2026: NC 3-13 por 289.800 de IVA).
    deb_xml = sum((-v if "_rest_" in k else v) for k, v in xml.items() if isinstance(v, float)
                  and k.startswith("iva_ventas/") and k.endswith("/total_liquidado"))
    alertas, control = [], {}

    def coincide(a, b):
        return abs(a - b) <= max(TOL_ABS, TOL_REL * abs(b))

    hay_extranjera = any(c["moneda"] not in ("PES", "") for c in compras + ventas)
    variantes = [("tal cual", compras, ventas)]
    if hay_extranjera:
        variantes.append(("convertido a pesos", [_en_pesos(c) for c in compras], [_en_pesos(c) for c in ventas]))
    elegida = None
    for nombre, cc, vv in variantes:
        cf = round(sum(c["credito_computable"] for c in cc if not c["b_c"]), 2)
        deb = round(sum(c["iva"] for c in vv), 2)
        if coincide(cf, cf_xml) and coincide(deb, deb_xml):
            elegida = (nombre, cc, vv, cf, deb)
            break
    if not elegida:
        # El CSV de ARCA trae los importes en PESOS aunque la moneda original sea otra (factura en DOL con
        # tipo de cambio 1506,50 relevada el 17/11/2026): si nada cierra, se toma tal cual y se avisa.
        nombre, cc, vv = variantes[0]
        cf = round(sum(c["credito_computable"] for c in cc if not c["b_c"]), 2)
        deb = round(sum(c["iva"] for c in vv), 2)
        elegida = (nombre, cc, vv, cf, deb)
        alertas.append({"Tipo de alerta": "Control Libro IVA",
                        "Acción": f"Los comprobantes no suman lo declarado: crédito {cf:,.2f} vs DJ {cf_xml:,.2f}; "
                                  f"débito {deb:,.2f} vs DJ {deb_xml:,.2f}. Revisar el período."})
    nombre, compras, ventas, cf, deb = elegida
    control = {"credito_csv": cf, "credito_dj": round(cf_xml, 2), "debito_csv": deb, "debito_dj": round(deb_xml, 2),
               "moneda_extranjera": nombre if hay_extranjera else "no hay", "ok": not alertas}
    return {
        "periodo": periodo, "secuencia": int(_num(str(xml.get("info_presentacion/secuencia", "0")))),
        "codigo": str(xml.get("info_presentacion/codigo", "")),
        "ventas": _resumir(ventas, periodo, compras=False),
        "compras": _resumir(compras, periodo, compras=True),
        "comprobantes_compras": [{k: c[k] for k in ("fecha", "tipo", "punto_venta", "numero", "cuit", "nombre",
                                                    "neto", "iva", "total", "b_c")} for c in compras],
        "comprobantes_ventas": [{k: c[k] for k in ("fecha", "tipo", "punto_venta", "numero", "cuit", "nombre",
                                                   "neto", "iva", "total")} for c in ventas],
        "control": control, "alertas": alertas,
    }


if __name__ == "__main__":
    r = leer_zip(sys.argv[1])
    print(f"Período {r['periodo']}  secuencia {r['secuencia']}  control: {r['control']}")
    for lado in ("ventas", "compras"):
        print(f"\n{lado.upper()}")
        for k, v in r[lado].items():
            print(f"  {k:45s} {v:>18,.2f}" if isinstance(v, float) else f"  {k:45s} {v:>18}")
    for a in r["alertas"]:
        print("ALERTA:", a)
