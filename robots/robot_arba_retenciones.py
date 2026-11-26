"""Robot ARBA: retenciones y percepciones de IIBB sufridas (deducciones informadas por los agentes).

Recorrido mostrado por Gabriel el 25/11/2026 con NABAJUMA S.A. (30-71222757-1), agosto 2026:
  Ingreso ARBA (CUIT + CIT) -> Autogestión (app.arba.gov.ar/Gestionar) -> "Mis accesos frecuentes" -> "Ingresos Brutos"
  -> "Deducciones informadas por los Agentes de Recaudación"   (el 21/11 estaba bajo "Agentes de Recaudación": se prueban los dos)
  -> sso.arba.gov.ar "Seleccione un rol": Rol = "Contribuyente de Ingresos Brutos" -> Continuar
  -> dfe.arba.gov.ar/DomicilioElectronico/dfeSetUpInicio.do  "Régimen de Retenciones y Percepciones"
  -> menú Deducciones -> "Descarga para Importar"  (preDescargarRetenciones.do)
     Consulta de deducciones: Cuit | Período: [año] [mes] | Tipo de Contribuyente: [Convenio Multilateral] -> Consultar
  -> descargarRet.do: "Datos Ingresados" + "Total de Deducciones" (PERCEPCION / RETENCIONES BANCARIAS/PSP /
     PERCEPCIONES ADUANERAS con su total) -> botones Volver | Descargar
  -> Descargar: RP-<cuit>-<AAAAMM><C|L>.zip con un TXT por régimen, ancho fijo, listo para importar en SIFERE:
     <cuit>CP<M><AAAA><fecha>.txt  percepciones          codigo(5) cuit agente(13) fecha(10) PV(5) número(20) tipo(1) letra(1) importe(15)
     <cuit>CB<M><AAAA><fecha>.txt  retenciones bancarias codigo(5) cuit agente(13) período AAAA/MM(7) CBU(22) tipo cuenta(2) moneda(1) importe(15)
     <cuit>CA<M><AAAA><fecha>.txt  percepciones aduaneras codigo(5) cuit agente(13) fecha(10) despacho(20) importe(15)
Solo consulta y descarga: no presenta ni modifica nada. Siempre los 2 últimos meses cerrados (biblioteca_archivos).
"""
from __future__ import annotations

import io
import os
import re
import zipfile
from datetime import date

from . import arca, biblioteca_archivos as bib

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
URL_INICIO = "https://dfe.arba.gov.ar/DomicilioElectronico/dfeSetUpInicio.do"
URL_DEDUCCIONES = "https://dfe.arba.gov.ar/DomicilioElectronico/preDescargarRetenciones.do"
FUENTE = "arba"
TIPOS_CP = {"F": "FACTURA", "R": "RECIBO", "C": "NOTA DE CREDITO", "D": "NOTA DE DEBITO", "O": "OTRO COMPROBANTE"}
REGIMEN = {"CP": "PERCEPCION", "CB": "RETENCION BANCARIA/PSP", "CA": "PERCEPCION ADUANERA"}
TIPO_CUENTA = {"CC": "Cuenta corriente", "CA": "Caja de ahorro", "OT": "Otra"}


def _importe(t: str) -> float:
    t = t.strip()
    neg = "-" in t
    v = float(t.replace("-", "").replace(".", "").replace(",", ".") or 0)
    return -v if neg else v


def _cuit(t: str) -> str:
    return re.sub(r"\D", "", t)


def leer_linea(regimen: str, l: str) -> dict | None:
    l = l.rstrip("\r\n")
    if len(l) < 40 or not re.match(r"\d{2}-\d{8}-\d", l[5:18]):
        return None
    base = {"codigo": l[:5], "agente": _cuit(l[5:18]), "regimen": REGIMEN[regimen], "jurisdiccion": "902", "linea": l}
    if regimen == "CP":
        tipo, letra = l[53:54], l[54:55].strip()
        imp = _importe(l[55:70])
        if tipo == "C" and imp > 0:                     # nota de crédito: la percepción se devuelve
            imp = -imp
        return {**base, "fecha": l[18:28], "punto_venta": l[28:33], "comprobante": l[33:53].lstrip("0") or "0",
                "tipo": tipo, "letra": letra, "desc_comprobante": TIPOS_CP.get(tipo, tipo) + (f" {letra}" if letra else ""),
                "importe": imp, "operacion": "PERCEPCION"}
    if regimen == "CB":
        per = l[18:25]
        return {**base, "fecha": f"01/{per[5:7]}/{per[:4]}", "periodo": per.replace("/", "-"), "cbu": l[25:47],
                "tipo_cuenta": TIPO_CUENTA.get(l[47:49], l[47:49]), "moneda": "Pesos" if l[49:50] == "P" else l[49:50],
                "comprobante": l[25:47], "desc_comprobante": "Retención bancaria", "importe": _importe(l[50:65]),
                "operacion": "RETENCION"}
    if regimen == "CA":
        return {**base, "fecha": l[18:28], "comprobante": l[28:48].lstrip("0"), "desc_comprobante": "Despacho de importación",
                "importe": _importe(l[48:63]), "operacion": "PERCEPCION"}
    return None


def leer_zip(crudo: bytes) -> dict:
    """{"filas": [...], "archivos": {nombre: bytes}} de la descarga para importar."""
    filas, archivos = [], {}
    with zipfile.ZipFile(io.BytesIO(crudo)) as z:
        for n in z.namelist():
            base = os.path.basename(n)
            m = re.match(r"\d{11}(C[PBA])", base, re.I)
            if not base or not m:
                continue
            datos = z.read(n)
            archivos[base] = datos
            for l in datos.decode("latin-1").splitlines():
                f = leer_linea(m[1].upper(), l)
                if f:
                    filas.append(f)
    return {"filas": filas, "archivos": archivos}


def leer_totales(texto: str) -> dict:
    """Total de Deducciones de descargarRet.do: {"PERCEPCION": 1289423.56, ...} (formato $1,289,423.56)."""
    t = texto[texto.find("Total de Deducciones"):] if "Total de Deducciones" in texto else ""
    out = {}
    for nom, imp in re.findall(r"(PERCEPCI[OÓ]N(?:ES)?(?: ADUANERAS)?|RETENCIONES BANCARIAS/PSP|RETENCI[OÓ]N(?:ES)?[A-Z /]*)\s*\$\s*(-?[\d.,]+\d)", t):
        # 25/11/2026: el total puede venir como $1,289,423.56 o como $ 1.289.423,56
        if re.search(r",\d{2}$", imp):
            v = imp.replace(".", "").replace(",", ".")
        else:
            v = imp.replace(",", "")
        try:
            out[nom.strip()] = float(v)
        except ValueError:
            pass
    return out


# ------------------------------------------------------------------ navegación
def _click_texto(page, patron: str) -> bool:
    x = page.get_by_text(re.compile(patron, re.I)).locator("visible=true")
    if x.count():
        x.last.click()
        page.wait_for_timeout(1000)
        return True
    return False


def abrir_deducciones(ctx, page, cuit: str, pasos: list):
    """Desde Autogestión hasta 'Régimen de Retenciones y Percepciones' con el rol de contribuyente."""
    patron = r"Deducciones informadas por los Agentes"
    link = page.get_by_text(re.compile(patron, re.I)).locator("visible=true")
    if not link.count():
        _click_texto(page, r"^\s*Mis accesos frecuentes\s*$")
        for menu in (r"^\s*Ingresos Brutos\s*$", r"^\s*Agentes de Recaudaci[oó]n\s*$"):
            link = page.get_by_text(re.compile(patron, re.I)).locator("visible=true")
            if link.count():
                break
            _click_texto(page, menu)
        link = page.get_by_text(re.compile(patron, re.I)).locator("visible=true")
    if not link.count():
        raise arca.ErrorRobot("ARBA: no aparece 'Deducciones informadas por los Agentes de Recaudación' "
                              "(Mis accesos frecuentes -> Ingresos Brutos)")
    pasos.append({"paso": "Autogestión -> Deducciones informadas por los Agentes", "ok": True})
    antes = set(ctx.pages)
    link.first.click()
    page.wait_for_timeout(3000)
    nuevas = [p for p in ctx.pages if p not in antes]
    ded = nuevas[-1] if nuevas else page
    ded.wait_for_load_state("domcontentloaded")
    rol = ded.locator("select").filter(has=ded.locator("option", has_text=re.compile(r"Contribuyente", re.I)))
    if rol.count():
        op = next(o for o in rol.first.locator("option").all_inner_texts() if re.search(r"Contribuyente", o, re.I))
        rol.first.select_option(label=op.strip())
        ded.locator("button, input[type=submit], a").filter(has_text=re.compile(r"^\s*Continuar\s*$", re.I)).first.click()
        ded.wait_for_load_state("domcontentloaded")
        ded.wait_for_timeout(2000)
        pasos.append({"paso": f"Seleccione un rol: {op.strip()}", "ok": True})
    try:
        ded.get_by_text(re.compile(r"R[eé]gimen de Retenciones y Percepciones", re.I)).first.wait_for(timeout=45_000)
    except Exception:
        raise arca.ErrorRobot("ARBA: después del rol no apareció 'Régimen de Retenciones y Percepciones'")
    if arca.cuit_fmt(cuit) not in ded.inner_text("body")[:3000] and cuit not in ded.inner_text("body")[:3000]:
        raise arca.CuitEquivocado(f"ARBA Deducciones: no muestra el CUIT {arca.cuit_fmt(cuit)}")
    pasos.append({"paso": "Régimen de Retenciones y Percepciones (rol contribuyente)", "ok": True})
    return ded


def bajar_mes(ded, cuit: str, anio: int, mes: int) -> dict:
    """Descarga para Importar de un mes: {"totales", "zip", "nombre", "sin_movimientos", "tipo"}."""
    ded.goto(URL_DEDUCCIONES, wait_until="domcontentloaded")
    texto = ded.inner_text("body")
    if arca.cuit_fmt(cuit) not in texto and cuit not in texto:
        raise arca.CuitEquivocado(f"ARBA Deducciones: no muestra el CUIT {arca.cuit_fmt(cuit)}")
    campos = ded.locator("input[type=text], input:not([type])").filter(visible=True)
    if campos.count() < 2:
        raise arca.ErrorRobot("ARBA Descarga para Importar: no aparecen los campos del período (año y mes)")
    campos.nth(0).fill(str(anio))
    campos.nth(1).fill(f"{mes:02d}")
    tipo = ""
    sel = ded.locator("select").filter(visible=True)
    if sel.count():
        ops = [o.strip() for o in sel.first.locator("option").all_inner_texts() if o.strip()]
        if ops:
            tipo = ops[0]                                # Convenio Multilateral o Local: ARBA ofrece el que corresponde
            sel.first.select_option(label=tipo)
    ded.locator("button, input[type=submit], input[type=button], a").filter(
        has_text=re.compile(r"^\s*Consultar\s*$", re.I)).first.click()
    ded.wait_for_load_state("domcontentloaded")
    ded.wait_for_timeout(1500)
    t = ded.inner_text("body")
    if not re.search(r"Total de Deducciones", t, re.I):
        if re.search(r"no (existen|hay|se encontraron|registra)|sin (datos|deducciones|movimientos)", t, re.I):
            return {"totales": {}, "zip": None, "sin_movimientos": True, "tipo": tipo}
        fin = re.sub(r"\s+", " ", t)[-200:]
        raise arca.ErrorRobot(f"ARBA Descarga para Importar {anio}-{mes:02d}: después de Consultar no apareció "
                              f"'Total de Deducciones' ({fin})")
    tot = leer_totales(t)
    boton = ded.locator("button, input[type=submit], input[type=button], a").filter(
        has_text=re.compile(r"^\s*Descargar\s*$", re.I))
    if not boton.count():
        return {"totales": tot, "zip": None, "sin_movimientos": not tot, "tipo": tipo}
    with ded.expect_download(timeout=90_000) as dl:
        boton.first.click()
    with open(dl.value.path(), "rb") as fh:
        crudo = fh.read()
    return {"totales": tot, "zip": crudo, "nombre": dl.value.suggested_filename or f"RP-{cuit}-{anio}{mes:02d}.zip",
            "sin_movimientos": False, "tipo": tipo}


def bajar(ctx, page, cuit: str, hoy: date | None = None) -> dict:
    """Los 2 últimos meses: guarda archivos, versiones y diagnóstico. Devuelve {"meses": {...}, "filas": n}."""
    hoy = hoy or date.today()
    pasos: list = []
    res = {"meses": {}, "filas": 0}
    try:
        ded = abrir_deducciones(ctx, page, cuit, pasos)
        for anio, mes in bib.periodos(hoy):
            per = f"{anio}-{mes:02d}"
            r = bajar_mes(ded, cuit, anio, mes)
            filas = []
            if r.get("zip"):
                bib.guardar_archivo(cuit, per, FUENTE, r["nombre"], r["zip"])
                z = leer_zip(r["zip"])
                for nom, crudo in z["archivos"].items():
                    bib.guardar_archivo(cuit, per, FUENTE, nom, crudo)
                filas = z["filas"]
            bib.guardar_version(cuit, per, FUENTE, filas, hoy, {"totales": r["totales"], "tipo": r.get("tipo", "")})
            suma = round(sum(f["importe"] for f in filas), 2)
            control = round(sum(r["totales"].values()), 2)
            pasos.append({"paso": f"Descarga para Importar {per}", "ok": True,
                          "detalle": f"{len(filas)} comprobantes, $ {suma:,.2f}" + (
                              "" if not r["totales"] or abs(suma - control) < 1 else f" (ARBA informa total $ {control:,.2f})")})
            res["meses"][per] = {"filas": len(filas), "importe": suma, "totales": r["totales"]}
            res["filas"] += len(filas)
            arca.pausa(0.8, 1.6)
        if ded is not page:
            ded.close()
        bib.guardar_diagnostico(cuit, FUENTE, {"estado": "ok" if res["filas"] else "sin_movimientos", "pasos": pasos,
                                               "meses": res["meses"]})
        return res
    except Exception as e:
        caps = arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "arba_retenciones")
        bib.guardar_diagnostico(cuit, FUENTE, {"estado": "error", "pasos": pasos + [{"paso": "siguiente paso", "ok": False}],
                                               "error": f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}",
                                               "captura": os.path.basename(caps[-1]) if caps else ""})
        raise


def paso(cuit: str, cit: str, estado: dict):
    """Entra a ARBA y baja solo las retenciones y percepciones (sin la ventanilla DFE)."""
    def fn():
        from .robot_arba import login
        with arca.navegador() as ctx:
            try:
                page = login(ctx, cuit, cit)
            except Exception as e:
                caps = arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "arba_retenciones")
                bib.guardar_diagnostico(cuit, FUENTE, {"estado": "error", "pasos": [{"paso": "Ingreso a ARBA con la CIT", "ok": False}],
                                                       "error": f"{type(e).__name__}: {e}"[:300],
                                                       "captura": os.path.basename(caps[-1]) if caps else ""})
                raise
            page.wait_for_timeout(2000)
            inicio = page.url
            try:                                         # constancia de inscripción de IIBB (25/11/2026)
                from . import robot_arba_constancia
                cons = robot_arba_constancia.bajar(ctx, page, cuit)
                estado["constancia"] = "OK" + ("" if cons.get("pdf") else " (sin PDF)")
            except Exception as e:
                estado["constancia"] = f"error: {str(e).splitlines()[0][:160] if str(e) else type(e).__name__}"
            if page.url != inicio:
                page.goto(inicio, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
            r = bajar(ctx, page, cuit)
        estado.update({"retenciones": f"OK ({r['filas']} comprobantes en {len(r['meses'])} meses)", **r})
        try:
            from . import percepciones
            percepciones.cruzar(cuit)
        except Exception:
            pass
        return r
    return fn
