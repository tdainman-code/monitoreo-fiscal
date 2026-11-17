"""Lector de CSV de Mis Comprobantes (ARCA) - recibidos o emitidos.

Uso:
    python3 lector_mis_comprobantes.py archivo.csv [salida.xlsx]

- Normaliza importes (coma decimal, moneda extranjera -> pesos, NC en negativo).
- Controla que los conceptos sumen el total de cada comprobante clase A.
- Las diferencias se clasifican:
    * Emisor con actividad de combustibles (según padrón)  -> "Impuesto a los combustibles" CONFIRMADO
    * Sin dato de actividad pero con patrón de combustible -> "Impuesto a los combustibles" ESTIMADO A CONFIRMAR
    * Resto -> "Diferencia sin identificar" (alerta para analizar con la factura)
- Comprobante con todos los conceptos en cero y solo total -> alerta "sin desglose".
- Genera un Excel con el detalle, filas resaltadas por color y una hoja de alertas.

Archivo opcional emisores_actividad.csv (CUIT;codigo_actividad;descripcion): lo va a
completar el robot consultando la constancia de inscripción de cada emisor.
"""
import os
import sys
import pandas as pd

NOTAS_CREDITO = {3, 8, 13, 53, 110, 112, 113, 114, 203, 208, 213}
CLASE_A = {1, 2, 3, 4, 5, 17, 51, 52, 53, 54, 60, 63, 81, 112, 201, 202, 203}

NOMBRES = {
    1: "Factura A", 2: "Nota de Débito A", 3: "Nota de Crédito A",
    6: "Factura B", 7: "Nota de Débito B", 8: "Nota de Crédito B",
    11: "Factura C", 12: "Nota de Débito C", 13: "Nota de Crédito C",
    17: "Liq. Servicios Públicos A", 63: "Liquidación A", 81: "Tique Factura A",
    82: "Tique Factura B", 83: "Tique",
}

# Prefijos de código de actividad (CLAE) de venta de combustibles. A validar.
ACTIVIDAD_COMBUSTIBLES = ("4730", "4661")
# Pista débil por nombre, solo para marcar "estimado a confirmar"
PISTAS_COMBUSTIBLE = ("ESTACION", "ESTACIÓN", "SERVICENTRO", "COMBUSTIBLE", "PETROL", "YPF", "SHELL", "AXION")

COLUMNAS_MONTO = [
    "Imp. Neto Gravado IVA 0%", "IVA 2,5%", "Imp. Neto Gravado IVA 2,5%",
    "IVA 5%", "Imp. Neto Gravado IVA 5%", "IVA 10,5%", "Imp. Neto Gravado IVA 10,5%",
    "IVA 21%", "Imp. Neto Gravado IVA 21%", "IVA 27%", "Imp. Neto Gravado IVA 27%",
    "Imp. Neto Gravado Total", "Imp. Neto No Gravado", "Imp. Op. Exentas",
    "Otros Tributos", "Total IVA", "Imp. Total",
]

TOL = 1.0  # tolerancia de redondeo en pesos

ESTADO_OK = "OK"
ESTADO_COMB_CONF = "Combustibles - confirmado por actividad"
ESTADO_COMB_EST = "Combustibles - ESTIMADO A CONFIRMAR"
ESTADO_SIN_ID = "Diferencia sin identificar"
ESTADO_SIN_DESGLOSE = "Sin desglose (solo total)"


def _num(s: pd.Series) -> pd.Series:
    s = s.fillna("").astype(str).str.strip()
    s = s.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    return pd.to_numeric(s.replace("", "0"), errors="coerce").fillna(0.0)


def cargar_actividades(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    t = pd.read_csv(path, sep=";", dtype=str)
    return dict(zip(t.iloc[:, 0].str.strip(), t.iloc[:, 1].str.strip()))


def _codificacion(path: str) -> str:
    """ARCA entrega el CSV a veces en UTF-8 y a veces en codificación Windows/DOS."""
    crudo = open(path, "rb").read(4000)
    for enc in ("utf-8-sig", "cp1252", "cp850", "latin-1"):
        try:
            txt = crudo.decode(enc)
        except UnicodeDecodeError:
            continue
        if "Emisión" in txt or "Número" in txt:
            return enc
    return "latin-1"


def leer(path: str, actividades: dict | None = None) -> pd.DataFrame:
    actividades = actividades or {}
    df = pd.read_csv(path, sep=";", dtype=str, encoding=_codificacion(path))
    df.columns = [c.strip() for c in df.columns]
    emitidos = "Denominación Receptor" in df.columns and "Denominación Emisor" not in df.columns
    df.attrs["modo"] = "Ventas (emitidos)" if emitidos else "Compras (recibidos)"
    # Columnas genéricas de contraparte
    lado = "Receptor" if emitidos else "Emisor"
    df["CUIT contraparte"] = df[f"Nro. Doc. {lado}"].fillna("")
    df["Contraparte"] = df[f"Denominación {lado}"].fillna("(consumidor final)")
    df.loc[df["CUIT contraparte"].isin(["", "0"]), "Contraparte"] = "(consumidor final)"
    for c in COLUMNAS_MONTO + ["Tipo Cambio"]:
        df[c] = _num(df[c])
    df["Tipo"] = df["Tipo de Comprobante"].astype(int)
    df["Comprobante"] = df["Tipo"].map(lambda t: NOMBRES.get(t, f"Tipo {t}"))
    df["Fecha"] = pd.to_datetime(df["Fecha de Emisión"])
    df["Periodo"] = df["Fecha"].dt.strftime("%Y-%m")
    signo = df["Tipo"].map(lambda t: -1 if t in NOTAS_CREDITO else 1)
    for c in COLUMNAS_MONTO:
        df[c] = df[c] * df["Tipo Cambio"] * signo
    # En ventas el propio contribuyente informa el IVA de todos sus comprobantes (A y B);
    # en compras solo los clase A dan crédito fiscal discriminado.
    df["Clase A"] = True if emitidos else df["Tipo"].isin(CLASE_A)

    # --- Control de sumas y clasificación de diferencias ---
    conceptos = (df["Imp. Neto Gravado Total"] + df["Total IVA"] + df["Imp. Neto No Gravado"]
                 + df["Imp. Op. Exentas"] + df["Otros Tributos"])
    dif = (df["Imp. Total"] - conceptos).round(2)
    df["Impuesto a los combustibles"] = 0.0
    df["Diferencia sin identificar"] = 0.0
    df["Estado"] = ESTADO_OK

    for i in df.index[df["Clase A"] & (dif.abs() > TOL)]:
        cuit = str(df.at[i, "CUIT contraparte"]).strip()
        nombre = str(df.at[i, "Contraparte"]).upper()
        act = actividades.get(cuit, "")
        if conceptos[i] == 0:
            df.at[i, "Diferencia sin identificar"] = dif[i]
            df.at[i, "Estado"] = ESTADO_SIN_DESGLOSE
        elif emitidos:
            df.at[i, "Diferencia sin identificar"] = dif[i]
            df.at[i, "Estado"] = ESTADO_SIN_ID
        elif act.startswith(ACTIVIDAD_COMBUSTIBLES):
            df.at[i, "Impuesto a los combustibles"] = dif[i]
            df.at[i, "Estado"] = ESTADO_COMB_CONF
        elif (not act and (df.at[i, "Tipo"] == 81 or any(p in nombre for p in PISTAS_COMBUSTIBLE))):
            # Tique factura A con diferencia: patrón típico de estación de servicio
            df.at[i, "Impuesto a los combustibles"] = dif[i]
            df.at[i, "Estado"] = ESTADO_COMB_EST
        else:
            df.at[i, "Diferencia sin identificar"] = dif[i]
            df.at[i, "Estado"] = ESTADO_SIN_ID
    return df


def resumir(df: pd.DataFrame) -> pd.Series:
    a = df[df["Clase A"]]
    bc = df[~df["Clase A"]]
    r = pd.Series({
        "Neto gravado 21%": a["Imp. Neto Gravado IVA 21%"].sum(),
        "Neto gravado 10,5%": a["Imp. Neto Gravado IVA 10,5%"].sum(),
        "Neto gravado 27%": a["Imp. Neto Gravado IVA 27%"].sum(),
        "Neto gravado otras alícuotas": a[["Imp. Neto Gravado IVA 0%", "Imp. Neto Gravado IVA 2,5%",
                                            "Imp. Neto Gravado IVA 5%"]].sum().sum(),
        "Neto gravado total": a["Imp. Neto Gravado Total"].sum(),
        "IVA 21%": a["IVA 21%"].sum(),
        "IVA 10,5%": a["IVA 10,5%"].sum(),
        "IVA 27%": a["IVA 27%"].sum(),
        "IVA otras alícuotas": a[["IVA 2,5%", "IVA 5%"]].sum().sum(),
        "Total IVA": a["Total IVA"].sum(),
        "No gravado": a["Imp. Neto No Gravado"].sum(),
        "Exento": a["Imp. Op. Exentas"].sum(),
        "Otros tributos / percepciones": a["Otros Tributos"].sum(),
        "Impuesto a los combustibles": a["Impuesto a los combustibles"].sum(),
        "  de ello estimado a confirmar": a.loc[a["Estado"] == ESTADO_COMB_EST, "Impuesto a los combustibles"].sum(),
        "Diferencia sin identificar": a["Diferencia sin identificar"].sum(),
        "Comprobantes B/C (sin IVA discriminado)": bc["Imp. Total"].sum(),
        "Ventas a consumidor final (sin identificar)": df.loc[df["Contraparte"] == "(consumidor final)", "Imp. Total"].sum(),
        "TOTAL COMPROBANTES": df["Imp. Total"].sum(),
        "Cantidad de comprobantes": len(df),
    }, name=df["Periodo"].iloc[0])
    if df.attrs.get("modo", "").startswith("Compras"):
        r = r.drop("Ventas a consumidor final (sin identificar)")
    else:
        r = r.drop(["Impuesto a los combustibles", "  de ello estimado a confirmar",
                    "Comprobantes B/C (sin IVA discriminado)"])
    return r


def alertas(df: pd.DataFrame) -> pd.DataFrame:
    filas = []
    for estado, msg in [
        (ESTADO_COMB_EST, "Diferencia tratada como impuesto a los combustibles por estimación. "
                          "Confirmar con la actividad del emisor (constancia de CUIT) o con la factura."),
        (ESTADO_SIN_ID, "Los conceptos no suman el total. Subir la factura para analizar su composición."),
        (ESTADO_SIN_DESGLOSE, "El comprobante viene sin desglose (solo total). Revisar si da crédito fiscal."),
    ]:
        sub = df[df["Estado"] == estado]
        for emisor, g in sub.groupby("Contraparte"):
            filas.append({
                "Tipo de alerta": estado, "Contraparte": emisor,
                "CUIT": g["CUIT contraparte"].iloc[0], "Comprobantes": len(g),
                "Importe": (g["Impuesto a los combustibles"] + g["Diferencia sin identificar"]).sum(),
                "Acción": msg,
            })
    return pd.DataFrame(filas)


COLORES = {
    ESTADO_COMB_CONF: "C6EFCE",   # verde
    ESTADO_COMB_EST: "FFEB9C",    # amarillo
    ESTADO_SIN_ID: "FFC7CE",      # rojo
    ESTADO_SIN_DESGLOSE: "F4B084",  # naranja
}


def exportar_excel(df: pd.DataFrame, path: str):
    from openpyxl.styles import PatternFill, Font
    from openpyxl.utils import get_column_letter
    cols = ["Fecha de Emisión", "Comprobante", "Punto de Venta", "Número Desde", "CUIT contraparte",
            "Contraparte", "Imp. Neto Gravado Total", "Total IVA", "Imp. Neto No Gravado",
            "Imp. Op. Exentas", "Otros Tributos", "Impuesto a los combustibles",
            "Diferencia sin identificar", "Imp. Total", "Estado"]
    al = alertas(df)
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        resumir(df).to_frame().to_excel(xw, sheet_name="Resumen")
        df[cols].to_excel(xw, sheet_name="Detalle", index=False)
        al.to_excel(xw, sheet_name="Alertas", index=False)
        pd.DataFrame({"Color": list(COLORES), "Significado": [
            "Impuesto a los combustibles confirmado por actividad del emisor",
            "Impuesto a los combustibles ESTIMADO - a confirmar",
            "Diferencia sin identificar - analizar factura",
            "Comprobante sin desglose"]}).to_excel(xw, sheet_name="Referencias", index=False)

        wb = xw.book
        fmt = '#,##0.00;[Red]-#,##0.00'
        ws = wb["Detalle"]
        idx_estado = cols.index("Estado") + 1
        for row in ws.iter_rows(min_row=2):
            color = COLORES.get(row[idx_estado - 1].value)
            for cell in row:
                if isinstance(cell.value, float):
                    cell.number_format = fmt
                if color:
                    cell.fill = PatternFill("solid", fgColor=color)
        for name in ["Resumen", "Alertas", "Referencias"]:
            for row in wb[name].iter_rows(min_row=2):
                for cell in row:
                    if isinstance(cell.value, float):
                        cell.number_format = fmt
        ref = wb["Referencias"]
        for r, color in enumerate(COLORES.values(), start=2):
            ref.cell(r, 1).fill = PatternFill("solid", fgColor=color)
        for r in range(2, wb["Alertas"].max_row + 1):
            c = COLORES.get(wb["Alertas"].cell(r, 1).value)
            if c:
                for cell in wb["Alertas"][r]:
                    cell.fill = PatternFill("solid", fgColor=c)
        for w in wb.worksheets:
            for c in w[1]:
                c.font = Font(bold=True)
            for i, col in enumerate(w.columns, start=1):
                largo = max(len(str(c.value or "")) for c in col)
                w.column_dimensions[get_column_letter(i)].width = min(max(10, largo + 2), 60)
            w.freeze_panes = "A2"


if __name__ == "__main__":
    base = os.path.dirname(os.path.abspath(__file__))
    acts = cargar_actividades(os.path.join(base, "emisores_actividad.csv"))
    df = leer(sys.argv[1], acts)
    pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
    print(df.attrs["modo"])
    print(resumir(df).to_string())
    print("\nPor tipo:")
    print(df.groupby("Comprobante").agg(cant=("Tipo", "size"), total=("Imp. Total", "sum")).to_string())
    al = alertas(df)
    if len(al):
        print("\nALERTAS:")
        print(al[["Tipo de alerta", "Contraparte", "Comprobantes", "Importe"]].to_string(index=False))
    if len(sys.argv) > 2:
        exportar_excel(df, sys.argv[2])
        print(f"\nExcel generado: {sys.argv[2]}")
