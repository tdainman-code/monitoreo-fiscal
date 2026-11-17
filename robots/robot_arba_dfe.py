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


def _abrir_bandeja(ctx, page, cuit):
    link = page.get_by_text(re.compile(r"Domicilio Fiscal Electr[oó]nico", re.I)).locator("visible=true")
    link.first.wait_for(timeout=45_000)
    with ctx.expect_page(timeout=60_000) as nueva:
        link.first.click()
    band = nueva.value
    band.wait_for_load_state("domcontentloaded")
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


def paso(cuit: str, cit: str, estado: dict):
    carpeta = os.path.join(DATOS, cuit, "arba_dfe")

    def fn():
        os.makedirs(carpeta, exist_ok=True)
        ruta_reg = os.path.join(carpeta, "registro.json")
        reg = json.load(open(ruta_reg, encoding="utf-8")) if os.path.exists(ruta_reg) else {}
        with arca.navegador() as ctx:
            try:
                page = login(ctx, cuit, cit)
                band = _abrir_bandeja(ctx, page, cuit)
                filas = _listar(band)
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
        res = {"cuit": cuit, "fecha": date.today().isoformat(), "organismo": "ARBA", "comunicaciones": com,
               "total": len(com), "sin_abrir": sum(1 for c in com if not c["notificado"]),
               "altas_sin_abrir": sum(1 for c in com if not c["notificado"] and c["importancia"] == "ALTA"),
               "nuevas_leidas": sum(1 for r in reg.values() if r.get("leida_por_robot") == date.today().isoformat()),
               "alertas": alertas}
        destino = os.path.join(carpeta, date.today().isoformat())
        os.makedirs(destino, exist_ok=True)
        with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as fh:
            json.dump(res, fh, ensure_ascii=False, indent=1)
        estado.update({"total": res["total"], "nuevas_leidas": res["nuevas_leidas"], "alertas": len(alertas)})
        return res
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    """usuario/clave: los de ARBA (CUIT y CIT)."""
    estado: dict = {}
    paso(usuario, clave, estado)()
    return {"cuit": cuit, "periodos": estado, "archivos": {"arba_dfe": {"alertas": []}}}
