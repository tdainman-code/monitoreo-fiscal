"""Robot ARBA: Domicilio Fiscal Electrónico (ventanilla de comunicaciones). Lee TODO y resume lo importante.

Recorrido (relevado el 16/11/2026 con GONCALVES VICENTE JUAN JOSE, 20-33116278-8):
  Ingreso ARBA (CUIT + CIT) -> Autogestión (app.arba.gov.ar/Gestionar) -> columna derecha
  "Domicilio Fiscal Electrónico (81)"  (abre PESTAÑA NUEVA: SIIntimaciones/dfe/inicioDomicilioFiscalElectronico.do)
     "Contribuyente: NOMBRE 20-33116278-8"
     Solapas: Intimaciones (3) | Notificaciones (78) | Comunicaciones (1) | Todas (82)   (a[href='#tabs-Todas'])
     Tabla #listaNotificacionesTCTodas, 10 por página (Primero/Anterior/1..N/Siguiente/Último):
       [color] | Fecha puesta a disposición | Fecha notificado | Fecha leído | Impuesto | Operativo (nro - nombre) |
       Destinatario | Razón social | Carácter | Visualizar
       color: rojo = intimación, naranja = notificación, verde = comunicación; negrita = no leída
     Visualizar -> pestaña nueva consultarDetalleNotificacionDFE.do?codTipoComunicacion&nroOperativo&nroNotificacion
       Detalle: Nro. de operativo, Nombre, Nro. de notificación, Destinatario, Disponibilidad, Estado,
       Fecha de leído, Fecha de notificado. Botones: #btnVisualizarNotificacion (PDF con el texto),
       #btnConstanciaMaterialidad, Cerrar.
En ARBA la notificación corre sola (fecha de notificado automática): abrir una ya notificada solo la marca
LEÍDA. Por pedido del estudio (16/11/2026) se abren TODAS: las que estaban SIN NOTIFICAR quedan notificadas
el día que las abre el robot, y eso se avisa con alerta ALTA (corren plazos desde ese día).
Cada comunicación se abre UNA sola vez: queda en DATOS/<cuit>/arba_dfe/registro.json con su texto y resumen.
Resultado: DATOS/<cuit>/arba_dfe/<fecha>/resultado.json (mismo formato que el DFE de ARCA, organismo ARBA).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import date
from urllib.parse import parse_qs, urlparse

from . import arca
from .robot_arba import login

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
TIPOS = {"intimacion": "Intimación", "notificacion": "Notificación", "comunicacion": "Comunicación"}
FECHA = re.compile(r"^\d{2}-\d{2}-\d{4}$")

JS_FILAS = r"""() => {
  const t = document.getElementById('listaNotificacionesTCTodas');
  if (!t) return null;
  return [...t.querySelectorAll('tbody tr')].map(tr => {
    const td = [...tr.children];
    const a = tr.querySelector('a[target=_blank], a[href*="consultarDetalle"]');
    const cls = (td[0] && td[0].className || '').toLowerCase();
    return {celdas: td.map(c => c.innerText.replace(/\s+/g, ' ').trim()), clase: cls,
            negrita: td[1] ? parseInt(getComputedStyle(td[1]).fontWeight) >= 600 : false,
            href: a ? a.href : ''};
  }).filter(f => f.celdas.length >= 8);
}"""


def _texto_pdf(datos: bytes) -> str:
    try:
        import io
        from pypdf import PdfReader
        return "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(datos)).pages)
    except Exception:
        pass
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(datos)
            f.flush()
            return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def analizar(tipo: str, operativo: str, texto: str) -> dict:
    """Importancia, plazo, montos, períodos y un resumen corto del texto de la notificación."""
    t = re.sub(r"[ \t]+", " ", texto or "")
    plano = t.replace("\n", " ")
    plazo = None
    m = re.search(r"plazo(?: improrrogable)? de (\d+|cinco|diez|quince|treinta) \(?\d*\)?\s*d[ií]as( h[aá]biles)?", plano, re.I)
    if m:
        plazo = m.group(0)
    montos = sorted({x for x in re.findall(r"\$\s?\d{1,3}(?:\.\d{3})*(?:,\d{2})?", plano)}, key=len, reverse=True)[:5]
    periodos = sorted(set(re.findall(r"\b(?:20\d{2}[-/]\d{2}|\d{2}[-/]20\d{2})\b", operativo + " " + plano)))[:12]
    from .notificaciones import clasificar
    cl = clasificar(operativo, tipo, plano)
    nivel = cl["importancia"]
    if tipo == "Intimación" and nivel != "Baja":
        nivel = "ALTA"
    # resumen: frases clave del cuerpo (las que piden hacer algo o dicen el motivo)
    frases = [f.strip() for f in re.split(r"(?<=[.:])\s+", plano) if 25 < len(f.strip()) < 400]
    clave = [f for f in frases if re.search(r"intim|plazo|deber[aá]|regulariz|present|descargo|deuda|inconsist|"
                                             r"seg[uú]n nuestros registros|se le comunica|se le notifica", f, re.I)]
    resumen = " ".join((clave or frases)[:3])[:600]
    return {"importancia": nivel, "para": cl["para"], "motivo": cl["motivo"], "plazo": plazo, "montos": montos,
            "periodos": periodos, "resumen": resumen}


def elegir_rol(pag) -> bool:
    """sso.arba.gov.ar "Seleccione un rol" (25/11/2026, Nabajuma: Agente de Recaudación / Contribuyente de Ingresos
    Brutos): se elige el de contribuyente y Continuar. Si no aparece, no hace nada."""
    try:
        pag.wait_for_timeout(1500)
        if not re.search(r"Seleccione un rol", pag.inner_text("body")[:3000], re.I):
            return False
        sel = pag.locator("select").filter(has=pag.locator("option", has_text=re.compile(r"Contribuyente", re.I)))
        if not sel.count():
            return False
        op = next(o for o in sel.first.locator("option").all_inner_texts() if re.search(r"Contribuyente", o, re.I))
        sel.first.select_option(label=op.strip())
        pag.locator("button, input[type=submit], a").filter(has_text=re.compile(r"^\s*Continuar\s*$", re.I)).first.click()
        pag.wait_for_load_state("domcontentloaded")
        pag.wait_for_timeout(2500)
        return True
    except Exception:
        return False


def _abrir_bandeja(ctx, page, cuit):
    link = page.get_by_text(re.compile(r"Domicilio Fiscal Electr[oó]nico", re.I)).locator("visible=true")
    link.first.wait_for(timeout=45_000)
    with ctx.expect_page(timeout=60_000) as nueva:
        link.first.click()
    band = nueva.value
    band.wait_for_load_state("domcontentloaded")
    elegir_rol(band)
    band.locator("#listaNotificacionesTCTodas").wait_for(state="attached", timeout=60_000)
    if arca.cuit_fmt(cuit) not in band.inner_text("body")[:3000]:
        raise arca.CuitEquivocado(f"ARBA DFE: la bandeja no muestra el CUIT {arca.cuit_fmt(cuit)}")
    tab = band.locator("a[href='#tabs-Todas']")
    if tab.count():
        tab.first.click()
        band.wait_for_timeout(1500)
    return band


def _listar(band) -> list[dict]:
    filas, vistos = [], set()
    for _ in range(200):
        lote = band.evaluate(JS_FILAS) or []
        nuevas = 0
        for f in lote:
            q = parse_qs(urlparse(f["href"]).query) if f["href"] else {}
            clave = f"{(q.get('nroOperativo') or [''])[0]}-{(q.get('nroNotificacion') or [''])[0]}"
            if not f["href"] or clave in vistos:
                continue
            vistos.add(clave)
            nuevas += 1
            c = [x for x in f["celdas"]]
            fechas = [x if FECHA.match(x) else "" for x in c[1:4]]
            tipo = next((v for k, v in TIPOS.items() if k in f["clase"]), "")
            filas.append({"clave": clave, "tipo": tipo, "puesta": fechas[0], "notificado": fechas[1] or None,
                          "leido": fechas[2] or None, "impuesto": c[4], "operativo": c[5],
                          "caracter": c[-2] if len(c) >= 9 else "", "no_leida": f["negrita"] or not fechas[2],
                          "href": f["href"]})
        sig = band.locator("#listaNotificacionesTCTodas_paginate a").filter(has_text=re.compile(r"^\s*Siguiente\s*$"))
        if not nuevas or not sig.count() or "disabled" in (sig.first.get_attribute("class") or ""):
            break
        sig.first.click()
        band.wait_for_timeout(1200)
    return filas


def _leer_una(ctx, f: dict, carpeta: str) -> dict:
    """Abre el detalle (la marca leída), baja el PDF de la notificación y lo analiza."""
    capturado = {}

    def al_responder(resp):
        if "visualizarArchivoNotificacion" in resp.url and "pdf" not in capturado:
            try:
                capturado["pdf"] = resp.body()
            except Exception:
                pass

    def al_descargar(dl):
        try:
            capturado.setdefault("pdf", open(dl.path(), "rb").read())
        except Exception:
            pass

    def al_abrir(p):
        p.on("download", al_descargar)
    ctx.on("response", al_responder)
    ctx.on("page", al_abrir)
    det = ctx.new_page()
    try:
        det.goto(f["href"], wait_until="domcontentloaded")
        arca.verificar_sesion(det, "arba_dfe")
        det.get_by_text(re.compile(r"Detalle de la notificaci[oó]n", re.I)).first.wait_for(timeout=45_000)
        detalle = {}
        for fila in det.locator("tr").all():
            celdas = [c.strip() for c in fila.locator("td, th").all_inner_texts()]
            if len(celdas) == 2 and celdas[0]:
                detalle[celdas[0]] = celdas[1]
        boton = det.locator("#btnVisualizarNotificacion")
        if boton.count():
            antes = set(ctx.pages)
            boton.first.click()
            for _ in range(60):
                if "pdf" in capturado:
                    break
                det.wait_for_timeout(500)
            for p in ctx.pages:
                if p not in antes and p is not det:
                    try:
                        p.close()
                    except Exception:
                        pass
    finally:
        ctx.remove_listener("response", al_responder)
        ctx.remove_listener("page", al_abrir)
        try:
            det.close()
        except Exception:
            pass
    texto, pdf = "", None
    datos = capturado.get("pdf") or b""
    if datos[:4] == b"%PDF":
        os.makedirs(carpeta, exist_ok=True)
        pdf = os.path.join(carpeta, f"{f['clave']}.pdf")
        with open(pdf, "wb") as fh:
            fh.write(datos)
        texto = _texto_pdf(datos)
    return {"detalle": detalle, "texto": texto[:20000], "pdf": pdf}


# Autogestión -> "Mi cuenta corriente" (relevado con Gaby el 18/11/2026, GONCALVES 20-33116278-8):
#   1 Ingresos Brutos  $ 10.613.047,90 [Juicios]  $ 0,00 / 4 Sellos $ 0,00 $ 0,00 / TOTALES $ 10.613.047,90 $ 0,00
#   (columnas Deuda y Saldo a favor; la marca "Juicios" aparece solo si hay deuda en juicio).
IMPUESTOS_ARBA = ("Ingresos Brutos", "Sellos", "Inmobiliario", "Automotor", "Embarcaciones", "Planes de pago")
_PESOS = re.compile(r"\$\s*(-?[\d.]+,\d{2})")


def _imp(t: str) -> float:
    return float(t.replace(".", "").replace(",", "."))


def leer_cuenta(texto: str) -> dict:
    t = texto.replace("\xa0", " ")
    a = t.find("Mi cuenta corriente")
    if a < 0:
        return {}
    t = t[a:]
    z = t.find("TOTALES")
    cuerpo = t[:z] if z > 0 else t
    lineas = [l.strip() for l in cuerpo.splitlines() if l.strip()]
    imps = []
    for i, l in enumerate(lineas):
        nombre = next((n for n in IMPUESTOS_ARBA if re.fullmatch(rf"(\d+\s*)?{n}\W*", l, re.I)), None)
        if not nombre or any(x["impuesto"] == nombre for x in imps):
            continue
        sig = []
        for l2 in lineas[i + 1:]:
            if any(re.fullmatch(rf"(\d+\s*)?{n}\W*", l2, re.I) for n in IMPUESTOS_ARBA):
                break
            sig.append(l2)
        montos = [_imp(m) for x in sig[:8] for m in _PESOS.findall(x)]
        imps.append({"impuesto": nombre, "deuda": montos[0] if montos else 0.0,
                     "a_favor": montos[1] if len(montos) > 1 else 0.0,
                     "juicios": any(re.fullmatch(r"\W*Juicios\W*", x, re.I) for x in sig[:3])})
    m = re.search(r"TOTALES\s*\$\s*([\d.]+,\d{2})\s*\$\s*([\d.]+,\d{2})", t)
    tot_d = _imp(m[1]) if m else round(sum(x["deuda"] for x in imps), 2)
    tot_f = _imp(m[2]) if m else round(sum(x["a_favor"] for x in imps), 2)
    return {"impuestos": imps, "deuda_total": tot_d, "saldo_favor_total": tot_f, "juicios": any(x["juicios"] for x in imps)}


def alertas_cuenta(c: dict, minimo: float = 15_000.0) -> list[dict]:
    """Avisos al encargado (pedido de Gaby 20/11/2026): deuda, juicios, compensar con saldo a favor, devolución."""
    if not c:
        return []
    txt = lambda x: f"$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    deuda, favor = c.get("deuda_total") or 0.0, c.get("saldo_favor_total") or 0.0
    deben = ", ".join(x["impuesto"] for x in c["impuestos"] if x["deuda"] >= minimo)
    tienen = ", ".join(x["impuesto"] for x in c["impuestos"] if x["a_favor"] > 0)
    al = []
    if c.get("juicios"):
        al.append({"prioridad": "ALTA", "tipo": "ARBA: deuda en juicio",
                   "texto": "Hay deuda en ejecución fiscal (marca 'Juicios' en " + ", ".join(
                       x["impuesto"] for x in c["impuestos"] if x["juicios"]) + ")"})
    if deuda >= minimo and favor > 0:
        al.append({"prioridad": "ALTA", "tipo": "ARBA: compensar deuda con saldo a favor",
                   "texto": f"Deuda {txt(deuda)} ({deben}) y saldo a favor {txt(favor)} ({tienen})"
                            + (": el saldo a favor la cubre, compensar." if favor >= deuda else ": compensar lo que alcance.")})
    elif deuda >= minimo:
        al.append({"prioridad": "ALTA", "tipo": "ARBA: deuda", "texto": f"Deuda {txt(deuda)} en {deben or 'la cuenta corriente'}"})
    if favor - (deuda if deuda >= minimo else 0) >= 100_000:
        al.append({"prioridad": "ALTA", "tipo": "ARBA: saldo a favor para recuperar",
                   "texto": f"Quedan {txt(favor - (deuda if deuda >= minimo else 0))} a favor ({tienen}): evaluar devolución "
                            "o revisar los regímenes de retención y percepción."})
    return al


# ---------------------------------------------------------------- deducciones (percepciones de IIBB)
# Relevado con Gaby el 21/11/2026 (Nabajuma): Autogestión -> Mis accesos frecuentes -> Agentes de Recaudación ->
# "Deducciones informadas por los Agentes de Recaudación" -> "Seleccione un rol": Contribuyente de Ingresos Brutos ->
# dfe.arba.gov.ar/DomicilioElectronico (Régimen de Retenciones y Percepciones) -> Deducciones -> Descarga para Importar
# (preDescargarRetenciones.do): Período año + mes, Tipo de Contribuyente -> Consultar -> "Total de Deducciones"
# (PERCEPCION, RETENCIONES BANCARIAS/PSP) -> Descargar: zip RP-<cuit>-<AAAAMM>C.zip con <cuit>CP<MMAAAA>....txt
# (percepciones) y <cuit>CB....txt (bancarias). Línea CP (ancho fijo):
#   0290230-70956507-507/11/20250010600000000000011084585FA000000000333,15
#   ... CUIT agente 30-70956507-5 | fecha 07/11/2025 | ... número 11084585 | tipo F | letra A | importe 333,15
URL_DEDUCCIONES = "https://dfe.arba.gov.ar/DomicilioElectronico/preDescargarRetenciones.do"
MESES_DEDUCCIONES = 13
TIPOS_CP = {"F": "FACTURA", "R": "RECIBO", "C": "NOTA DE CREDITO", "D": "NOTA DE DEBITO", "O": "OTRO COMPROBANTE"}
_RE_CP = re.compile(r"(\d{2}-\d{8}-\d)(\d{2}/\d{2}/\d{4})(\d*?)(\d{8})([A-Z])([A-Z ])(-?\d+,\d{2})\s*$")


def leer_cp(texto: str) -> list[dict]:
    """Archivo CP (percepciones) de la descarga para importar de ARBA."""
    out = []
    for l in texto.splitlines():
        m = _RE_CP.search(l.strip())
        if not m:
            continue
        imp = float(m[7].replace(",", "."))
        if m[5] == "C" and imp > 0:                      # nota de crédito: la percepción se devuelve
            imp = -imp
        out.append({"agente": re.sub(r"\D", "", m[1]), "fecha": m[2], "fecha_comprobante": m[2],
                    "comprobante": m[4], "tipo": m[5], "letra": m[6].strip(),
                    "desc_comprobante": (TIPOS_CP.get(m[5], m[5]) + (f" {m[6].strip()}" if m[6].strip() else "")),
                    "importe": imp, "operacion": "PERCEPCION"})
    return out


def leer_zip_deducciones(crudo: bytes) -> list[dict]:
    import io
    import zipfile
    out = []
    with zipfile.ZipFile(io.BytesIO(crudo)) as z:
        for n in z.namelist():
            if re.search(r"\d{11}CP\d", os.path.basename(n), re.I):
                out += leer_cp(z.read(n).decode("latin-1"))
    return out


def leer_deducciones(ctx, page, cuit: str, hoy: date) -> list[dict]:
    """Percepciones de IIBB (Buenos Aires) de los últimos 13 meses, mes por mes."""
    link = page.get_by_text(re.compile(r"Deducciones informadas por los Agentes", re.I)).locator("visible=true")
    if not link.count():
        for t in (r"Mis accesos frecuentes", r"^\s*Agentes de Recaudaci[oó]n\s*$"):
            x = page.get_by_text(re.compile(t, re.I)).locator("visible=true")
            if x.count():
                x.last.click()
                page.wait_for_timeout(1000)
        link = page.get_by_text(re.compile(r"Deducciones informadas por los Agentes", re.I)).locator("visible=true")
    if not link.count():
        raise arca.ErrorRobot("ARBA: no aparece 'Deducciones informadas por los Agentes de Recaudación'")
    antes = set(ctx.pages)
    link.first.click()
    page.wait_for_timeout(3000)
    nuevas = [p for p in ctx.pages if p not in antes]
    ded = nuevas[-1] if nuevas else page
    ded.wait_for_load_state("domcontentloaded")
    rol = ded.locator("select").filter(has=ded.locator("option", has_text=re.compile(r"Contribuyente de Ingresos Brutos", re.I)))
    if rol.count():
        rol.first.select_option(label=next(o for o in rol.first.locator("option").all_inner_texts()
                                           if re.search(r"Contribuyente de Ingresos Brutos", o, re.I)).strip())
        ded.locator("button, input[type=submit], a").filter(has_text=re.compile(r"^\s*Continuar\s*$", re.I)).first.click()
        ded.wait_for_load_state("domcontentloaded")
        ded.wait_for_timeout(2000)
    out = []
    a, m = hoy.year, hoy.month
    for _ in range(MESES_DEDUCCIONES):
        ded.goto(URL_DEDUCCIONES, wait_until="domcontentloaded")
        texto = ded.inner_text("body")
        if arca.cuit_fmt(cuit) not in texto and cuit not in texto:
            raise arca.CuitEquivocado(f"ARBA Deducciones: no muestra el CUIT {arca.cuit_fmt(cuit)}")
        campos = ded.locator("input[type=text], input:not([type])").filter(visible=True)
        if campos.count() < 2:
            raise arca.ErrorRobot("ARBA Deducciones: no aparecen los campos del período (año y mes)")
        campos.nth(0).fill(str(a))
        campos.nth(1).fill(f"{m:02d}")
        ded.locator("button, input[type=submit], input[type=button], a").filter(
            has_text=re.compile(r"^\s*Consultar\s*$", re.I)).first.click()
        ded.wait_for_load_state("domcontentloaded")
        ded.wait_for_timeout(1500)
        t = ded.inner_text("body")
        if re.search(r"PERCEPCI[OÓ]N", t, re.I) and re.search(r"Total de Deducciones", t, re.I):
            boton = ded.locator("button, input[type=submit], input[type=button], a").filter(
                has_text=re.compile(r"^\s*Descargar\s*$", re.I))
            if boton.count():
                with ded.expect_download(timeout=90_000) as dl:
                    boton.first.click()
                with open(dl.value.path(), "rb") as fh:
                    out += leer_zip_deducciones(fh.read())
        a, m = (a, m - 1) if m > 1 else (a - 1, 12)
        arca.pausa(0.8, 1.6)
    if ded is not page:
        ded.close()
    return out


def paso(cuit: str, cit: str, estado: dict, meses: int | None = None):
    carpeta = os.path.join(DATOS, cuit, "arba_dfe")

    def fn():
        os.makedirs(carpeta, exist_ok=True)
        ruta_reg = os.path.join(carpeta, "registro.json")
        reg = json.load(open(ruta_reg, encoding="utf-8")) if os.path.exists(ruta_reg) else {}
        with arca.navegador() as ctx:
            try:
                page = login(ctx, cuit, cit)
                try:                                     # Mi cuenta corriente de Autogestión (20/11/2026)
                    page.wait_for_timeout(3000)
                    t0 = page.inner_text("body")
                    cuenta = leer_cuenta(t0) if (cuit in t0 or arca.cuit_fmt(cuit) in t0) else {}
                except Exception:
                    cuenta = {}
                inicio_autogestion = page.url
                try:
                    band = _abrir_bandeja(ctx, page, cuit)
                    filas = _listar(band)
                except (arca.CuitEquivocado, arca.ClaveInvalida):
                    raise
                except Exception as e:                   # 25/11/2026: si la ventanilla falla, igual se bajan retenciones
                    arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "arba_dfe")
                    estado["error_ventanilla"] = f"{type(e).__name__}: {str(e).splitlines()[0][:160] if str(e) else ''}"
                    filas = []
                for f in filas:
                    previo = reg.get(f["clave"])
                    if previo and previo.get("leida_por_robot"):
                        continue
                    if not f["notificado"]:
                        # pedido del estudio (16/11/2026): se abren TODAS; al abrirla queda notificada hoy
                        f["estado_robot"] = f"SE NOTIFICÓ HOY ({date.today().strftime('%d-%m-%Y')}) al abrirla: corren plazos"
                        f["notificado_por_robot"] = date.today().isoformat()
                    leido = _leer_una(ctx, f, os.path.join(carpeta, "pdf"))
                    reg[f["clave"]] = {**f, **leido, **analizar(f["tipo"], f["operativo"], leido["texto"]),
                                       "leida_por_robot": date.today().isoformat()}
                    with open(ruta_reg, "w", encoding="utf-8") as fh:      # se guarda de a una (cortes de sesión)
                        json.dump(reg, fh, ensure_ascii=False, indent=1)
                    arca.pausa(1.0, 2.0)
                try:                                     # percepciones de IIBB informadas por los agentes (21/11/2026)
                    page.bring_to_front()
                    if page.url != inicio_autogestion:
                        page.goto(inicio_autogestion, wait_until="domcontentloaded")
                    try:                                       # constancia de inscripción de IIBB (25/11/2026)
                        from . import robot_arba_constancia
                        from .robot_agip import _es_convenio
                        if not _es_convenio(cuit):           # en Convenio la constancia está en el Padrón Web
                            robot_arba_constancia.bajar(ctx, page, cuit)
                    except Exception as e:
                        estado["constancia"] = f"error: {str(e).splitlines()[0][:160] if str(e) else type(e).__name__}"
                    if page.url != inicio_autogestion:
                        page.goto(inicio_autogestion, wait_until="domcontentloaded")
                    from . import robot_arba_retenciones      # 25/11/2026: 2 meses, 3 regímenes, archivos y diagnóstico
                    rr = robot_arba_retenciones.bajar(ctx, page, cuit, date.today(), meses=meses)
                    percep = []                                # el cruce las toma de la biblioteca
                    estado["deducciones"] = f"OK ({rr['filas']} comprobantes en {len(rr['meses'])} meses)"
                except arca.CuitEquivocado:
                    raise
                except Exception as e:
                    percep = None
                    estado["deducciones"] = f"error: {str(e).splitlines()[0][:160]}"
                    # la captura y el diagnóstico ya los guardó robot_arba_retenciones
            except Exception:
                arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "arba_dfe")
                with open(ruta_reg, "w", encoding="utf-8") as fh:
                    json.dump(reg, fh, ensure_ascii=False, indent=1)
                raise
        with open(ruta_reg, "w", encoding="utf-8") as fh:
            json.dump(reg, fh, ensure_ascii=False, indent=1)
        from .notificaciones import responsable
        resp = responsable(cuit)
        com, alertas = [], []
        for r in sorted(reg.values(), key=lambda x: (x["puesta"][6:], x["puesta"][3:5], x["puesta"][:2]), reverse=True):
            com.append({"fecha": r["puesta"], "notificado": r["notificado"], "leida": bool(r.get("leido") or r.get("leida_por_robot")),
                        "organismo": "ARBA", "asunto": r["operativo"], "clasificacion": r["tipo"],
                        "importancia": r["importancia"], "plazo": r.get("plazo"), "montos": r.get("montos"),
                        "resumen": r.get("resumen"), "estado_robot": r.get("estado_robot", ""),
                        "para": r.get("para", "estudio"), "motivo": r.get("motivo", ""),
                        "responsable": resp if r.get("motivo") == "falta de presentación" else ""})
            # nueva = estaba SIN LEER y la abrió el robot hoy (las que el estudio ya había leído no se re-avisan)
            nueva = r.get("leida_por_robot") == date.today().isoformat() and not r.get("leido")
            notif_hoy = r.get("notificado_por_robot") == date.today().isoformat()
            if (r["importancia"] == "ALTA" and nueva) or notif_hoy:
                alertas.append({"prioridad": "ALTA", "tipo": "ARBA DFE",
                                "texto": f"{r['puesta']} {r['tipo']}: {r['operativo']} [{r.get('motivo')} -> {r.get('para')}]"
                                         + (f" RESPONSABLE: {resp}" if r.get("motivo") == "falta de presentación" and resp else "")
                                         + (f" — {r['plazo']}" if r.get("plazo") else "")
                                         + (" — SE NOTIFICÓ HOY AL ABRIRLA: corren plazos" if notif_hoy else "")})
        alertas += alertas_cuenta(cuenta)
        res = {"cuit": cuit, "fecha": date.today().isoformat(), "organismo": "ARBA", "comunicaciones": com, "cuenta": cuenta,
               "percepciones": percep,
               "total": len(com), "sin_abrir": sum(1 for c in com if not c["notificado"]),
               "altas_sin_abrir": sum(1 for c in com if not c["notificado"] and c["importancia"] == "ALTA"),
               "nuevas_leidas": sum(1 for r in reg.values() if r.get("leida_por_robot") == date.today().isoformat()),
               "alertas": alertas}
        destino = os.path.join(carpeta, date.today().isoformat())
        os.makedirs(destino, exist_ok=True)
        with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        if percep is not None:
            try:
                from . import percepciones
                percepciones.cruzar(cuit)
            except Exception:
                pass
        estado.update({"total": res["total"], "nuevas_leidas": res["nuevas_leidas"], "alertas": len(alertas),
                       "deducciones": estado.get("deducciones") or (f"OK ({len(percep)} percepciones)" if percep is not None else "")})
        if estado.get("error_ventanilla"):            # la ventanilla falló: se informa, pero lo demás quedó guardado
            raise arca.ErrorRobot(f"ARBA ventanilla DFE: {estado['error_ventanilla']} (retenciones: "
                                  f"{estado.get('deducciones') or 'sin dato'})")
        return res
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    """usuario/clave: los de ARBA (CUIT y CIT)."""
    estado: dict = {}
    paso(usuario, clave, estado)()
    return {"cuit": cuit, "periodos": estado, "archivos": {"arba_dfe": {"alertas": []}}}
