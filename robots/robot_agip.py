"""Robot AGIP (Ciudad de Buenos Aires): Domicilio Fiscal Electrónico, estado de deuda y fiscalización electrónica.

Traído de Radar fiscal (17/11/2026). Lo confirmado allá con la captura del 13/11/2026:
  https://claveciudad.agip.gob.ar/  abre con "Ingresá con cuenta miBA" (a.btn-miba-login) y un enlace
  "Clave Ciudad" que muestra el formulario #loginCC con #cuit, #clave y el botón "Ingresar".
  La clave AGIP del almacén es la Clave Ciudad.  AGIP BLOQUEA NAVEGADORES OCULTOS: este robot abre la ventana
  visible. En el servidor (sin pantalla) se corre dentro de una pantalla virtual:  xvfb-run -a python -m robots.correr ...
Servicios a leer (por el texto del enlace en el portal; los nombres se confirman en la primera corrida real con las
capturas que quedan en DATOS/<cuit>/capturas):
  Domicilio Fiscal Electrónico  -> SOLO el listado. NUNCA se abre una comunicación (no darla por notificada).
  Estado de cuenta / deuda
  Fiscalización Electrónica
Si se ingresa con la clave de un representante, en cada servicio se busca y se elige el CUIT del cliente y se
VERIFICA que la pantalla lo muestre antes de leer (si no, ese servicio se saltea).

Resultado: DATOS/<cuit>/agip/<fecha>/resultado.json
  {"cuit","fecha","comunicaciones":[{fecha, asunto, estado, tipo, impuesto, importancia, leida}],
   "deuda": {"tablas":[...], "total": float|None}, "fiscalizacion": [filas], "servicios": {...}, "alertas": [...]}
(comunicaciones con el mismo formato que el DFE de ARCA y ARBA, organismo "AGIP").

Prueba:  xvfb-run -a ~/venv/bin/python -m robots.correr agip --cuit 30717468631
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca
from .notificaciones import clasificar
from .robot_situacion_fiscal import JS_TABLA

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
PORTAL = "https://claveciudad.agip.gob.ar/"
SEL = {
    "link_clave_ciudad": ".clave-ciudad-info a, a:has-text('Clave Ciudad')",
    "cuit": "#loginCC #cuit, #cuit",
    "clave": "#loginCC #clave, #clave",
    "ingresar": "#loginCC a.btn-primary:has-text('Ingresar'), #loginCC a:has-text('Ingresar'), #loginCC button:has-text('Ingresar')",
    "error": "#loginCC .msgError",
}
SERVICIOS = [
    ("dfe", ["Domicilio Fiscal Electrónico", "Domicilio Fiscal Electronico", "DFE"]),
    ("deuda", ["Estado de Cuenta", "Consulta de Deuda", "Estado de deuda", "Deuda"]),
    ("fiscalizacion", ["Fiscalización Electrónica", "Fiscalizacion Electronica"]),
    # Nueva Cuenta Corriente Tributaria (portal-cct.agip.gob.ar), relevada con Gaby el 18/11/2026 (Dinafer S R L)
    ("cct", ["Nueva Cuenta Corriente Tributaria", "Cuenta Corriente Tributaria"]),
]


def _elegir_representado_portal(page, cuit: str) -> None:
    """Menú principal de Clave Ciudad: 'Seleccione un representado' (opciones 'NOMBRE [30-71103454-0]').
    Se elige el cliente ANTES de abrir los aplicativos. Si no hay selector, no hace nada."""
    fmt = arca.cuit_fmt(cuit)
    try:
        sel = page.locator("select").filter(has=page.locator(f"option:has-text('{fmt}'), option:has-text('{cuit}')"))
        if not sel.count():
            return
        op = sel.first.locator(f"option:has-text('{fmt}'), option:has-text('{cuit}')").first
        sel.first.select_option(value=op.get_attribute("value"))
        arca.pausa(1.5, 2.5)
    except Exception:
        pass


_NUM_CCT = r"\$\s*(-?[\d.]+,\d{2})"


def leer_cct(texto: str) -> dict:
    """Pantalla de inicio de la Nueva Cuenta Corriente Tributaria (texto). Ejemplo Dinafer 18/11/2026:
    Saldo deudor $ 2.133.601,00 / Importe Nominal: $ 2.133.601,00 / Intereses: $ 885.569,26 / Saldo a favor
    $ 26.303.826,11 / 71 Faltas de presentación / Obligaciones al día / 8 Notificaciones no leídas /
    Mis impuestos: 'IIBB - Convenio Multilateral' Total adeudado $ 0,00 Saldo a favor / Disponible $ 26.303.826,11,
    'Automotor' Total adeudado $ 3.019.167,35 Saldo a favor / Disponible $ 0,00."""
    t = texto.replace("\xa0", " ")
    g = lambda pat: (lambda m: _num(m[1]) if m else None)(re.search(pat, t, re.I))
    r = {"saldo_deudor": g(r"Saldo deudor\s*" + _NUM_CCT), "nominal": g(r"Importe Nominal:?\s*" + _NUM_CCT),
         "intereses": g(r"Intereses:?\s*" + _NUM_CCT), "saldo_favor": g(r"Saldo a favor\s*" + _NUM_CCT)}
    m = re.search(r"(\d+)\s*Faltas? de presentaci", t, re.I)
    r["faltas_presentacion"] = int(m[1]) if m else 0
    m = re.search(r"(\d+)\s*Notificaciones? no le[ií]das", t, re.I)
    r["notificaciones_no_leidas"] = int(m[1]) if m else 0
    m = re.search(r"(\d+)\s*Obligaciones? vencidas", t, re.I)
    r["obligaciones_vencidas"] = int(m[1]) if m else 0
    impuestos = []
    lineas = [l.strip() for l in t.splitlines() if l.strip()]
    for i, l in enumerate(lineas):
        if not re.match(r"Total adeudado", l, re.I):
            continue
        nombre = next((x for x in reversed(lineas[max(0, i - 3):i]) if re.search(r"[A-Za-zÁÉÍÓÚáéíóú]{3}", x)
                       and not re.search(r"Mis impuestos|Saldo a favor|Disponible|Ver|Pagar|Detalle", x, re.I)), "")
        bloque = " ".join(lineas[i:i + 4])
        ad = re.search(r"Total adeudado\s*" + _NUM_CCT, bloque, re.I)
        fa = re.search(r"Saldo a favor\s*/?\s*Disponible\s*" + _NUM_CCT, bloque, re.I)
        impuestos.append({"impuesto": nombre, "adeudado": _num(ad[1]) if ad else 0.0, "a_favor": _num(fa[1]) if fa else 0.0})
    r["impuestos"] = impuestos
    if r["saldo_deudor"] is None and not impuestos:
        raise arca.ErrorRobot("AGIP: no apareció el Estado de Cuenta Corriente Tributaria")
    return r


def alertas_cct(c: dict, minimo: float = 15_000.0) -> list[dict]:
    """Avisos al encargado (pedido de Gaby 18/11/2026, caso Dinafer): compensar deuda con saldo a favor,
    evaluar devolución del remanente, faltas de presentación y notificaciones sin leer."""
    txt = lambda x: f"$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    al = []
    deuda = (c.get("saldo_deudor") or 0.0) + (c.get("intereses") or 0.0) if c.get("nominal") is not None else (c.get("saldo_deudor") or 0.0)
    favor = c.get("saldo_favor") or 0.0
    deben = [i for i in c.get("impuestos") or [] if (i.get("adeudado") or 0) >= minimo]
    tienen = [i for i in c.get("impuestos") or [] if (i.get("a_favor") or 0) > 0]
    if deuda >= minimo and favor > 0:
        cubre = favor >= deuda
        al.append({"prioridad": "ALTA", "tipo": "AGIP: compensar deuda con saldo a favor",
                   "texto": f"Deuda {txt(deuda)} (con intereses)" + (" en " + ", ".join(i["impuesto"] for i in deben) if deben else "")
                            + f" y saldo a favor {txt(favor)}" + (" en " + ", ".join(i["impuesto"] for i in tienen) if tienen else "")
                            + (": el saldo a favor la cubre entera, compensar para cancelarla y bajar el riesgo fiscal."
                               if cubre else ": compensar lo que alcance y pagar el resto.")})
    elif deuda >= minimo:
        al.append({"prioridad": "ALTA", "tipo": "AGIP: deuda", "texto": f"Saldo deudor {txt(deuda)} (con intereses)"
                   + (" en " + ", ".join(i["impuesto"] for i in deben) if deben else "")})
    rem = favor - (deuda if deuda >= minimo else 0.0)
    if rem >= 100_000:
        al.append({"prioridad": "ALTA", "tipo": "AGIP: saldo a favor para recuperar",
                   "texto": f"Quedan {txt(rem)} a favor" + (" (" + ", ".join(i["impuesto"] for i in tienen) + ")" if tienen else "")
                            + ": evaluar solicitud de devolución; si crece todos los meses, revisar exclusión o reducción "
                              "de los regímenes de retención y percepción."})
    if c.get("faltas_presentacion"):
        al.append({"prioridad": "ALTA", "tipo": "AGIP: faltas de presentación",
                   "texto": f"{c['faltas_presentacion']} DDJJ con falta de presentación en la Cuenta Corriente Tributaria"})
    if c.get("notificaciones_no_leidas"):
        al.append({"prioridad": "Media", "tipo": "AGIP: notificaciones no leídas",
                   "texto": f"{c['notificaciones_no_leidas']} notificación(es) no leída(s) en la Cuenta Corriente Tributaria"})
    return al


def _visible(page, selector: str, timeout: int = 1500) -> bool:
    try:
        return page.locator(selector).first.is_visible(timeout=timeout)
    except Exception:
        return False


def login(ctx, usuario: str, clave: str):
    page = ctx.new_page()
    page.goto(PORTAL, wait_until="domcontentloaded")
    arca.pausa(1.2, 2.0)
    if "blocked" in (page.title() or "").lower():
        raise arca.RequiereIntervencion("AGIP bloqueó el acceso automático (¿se corrió sin pantalla? usar xvfb-run)")
    if page.locator("iframe[src*='captcha'], .g-recaptcha, [class*='captcha']").count():
        raise arca.RequiereIntervencion("AGIP pide captcha: no se puede ingresar automáticamente")
    if not _visible(page, SEL["cuit"]):
        page.locator(SEL["link_clave_ciudad"]).first.click()
        arca.pausa(0.6, 1.0)
    arca._tipear(page.locator(SEL["cuit"]).first, usuario)
    arca._tipear(page.locator(SEL["clave"]).first, clave)
    arca.pausa(0.4, 0.9)
    page.locator(SEL["ingresar"]).first.click()
    try:
        page.wait_for_load_state("domcontentloaded")
    except Exception:
        pass
    arca.pausa(2.0, 3.0)
    if _visible(page, SEL["clave"], 2500):
        err = ""
        try:
            err = (page.locator(SEL["error"]).first.inner_text(timeout=2000) or "").strip()
        except Exception:
            pass
        if re.search(r"bloquead", err, re.I):
            raise arca.RequiereIntervencion(f"AGIP: {err}")
        raise arca.ClaveInvalida(f"AGIP no aceptó la Clave Ciudad{': ' + err if err else ''}")
    return page


def _elegir_cuit(page, cuit: str) -> bool:
    """Si la pantalla tiene un selector de contribuyente (representación), elige el CUIT del cliente.
    Devuelve True si la pantalla queda mostrando ese CUIT."""
    fmt = arca.cuit_fmt(cuit)
    texto = page.inner_text("body")
    if cuit in texto or fmt in texto:
        sel = page.locator("select").filter(has=page.locator(f"option:has-text('{cuit}'), option:has-text('{fmt}')"))
        if sel.count():
            try:
                opcion = sel.first.locator(f"option:has-text('{cuit}'), option:has-text('{fmt}')").first
                sel.first.select_option(value=opcion.get_attribute("value"))
                arca.pausa(1.5, 2.5)
                boton = page.locator("button, input[type=submit], a").filter(
                    has_text=re.compile(r"^(aceptar|continuar|consultar|ingresar|buscar)$", re.I))
                if boton.count():
                    boton.first.click()
                    page.wait_for_load_state("domcontentloaded")
                    arca.pausa(1.5, 2.5)
            except Exception:
                pass
        texto = page.inner_text("body")
    return cuit in texto or fmt in texto


def _abrir(ctx, page, textos: list[str]):
    """Abre un servicio del portal por el texto del enlace. Devuelve la pestaña (nueva o la misma) o None."""
    for t in textos:
        link = page.locator(f"a:has-text('{t}')").filter(visible=True)
        if not link.count():                             # tarjetas del menú que no son <a> (18/11/2026)
            link = page.get_by_text(t, exact=True).filter(visible=True)
        if not link.count():
            continue
        destino = link.first.get_attribute("target") or ""
        pag = page
        if destino and destino != "_self":               # abre pestaña nueva
            try:
                with ctx.expect_page(timeout=15_000) as nueva:
                    link.first.click()
                pag = nueva.value
                pag.wait_for_url(lambda u: not u.startswith("about:"), timeout=30_000)
            except Exception:
                pag = ctx.pages[-1] if ctx.pages[-1] is not page else page
        else:
            antes = set(ctx.pages)
            link.first.click()
            arca.pausa(2.0, 3.0)
            for _ in range(10):                                  # por si abre ventana con JavaScript
                if [p for p in ctx.pages if p not in antes]:
                    break
                page.wait_for_timeout(500)
            nuevas = [p for p in ctx.pages if p not in antes]
            pag = nuevas[-1] if nuevas else page
        try:
            pag.wait_for_load_state("domcontentloaded")
        except Exception:
            pass
        arca.pausa(1.5, 2.5)
        return pag
    return None


def _tablas(pag) -> list[dict]:
    out = []
    for t in pag.locator("table").all():
        try:
            if not t.is_visible():
                continue
            d = t.evaluate(JS_TABLA)
        except Exception:
            continue
        filas = [f["celdas"] for f in d["filas"] if any(c for c in f["celdas"])]
        if d["encabezados"] and filas:
            out.append({"encabezados": d["encabezados"], "filas": filas})
    return out


def _col(enc: list[str], *patrones) -> int | None:
    for i, e in enumerate(enc):
        if any(re.search(p, e, re.I) for p in patrones):
            return i
    return None


def _num(txt: str) -> float | None:
    t = re.sub(r"[^\d,.\-]", "", txt or "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def comunicaciones_de(tablas: list[dict]) -> list[dict]:
    """Convierte las tablas del DFE de AGIP al formato común de notificaciones."""
    out = []
    for t in tablas:
        enc = t["encabezados"]
        c_fecha = _col(enc, r"fecha")
        c_asunto = _col(enc, r"asunto|descrip|t[ií]tulo|comunicaci")
        if c_fecha is None or c_asunto is None:
            continue
        c_estado = _col(enc, r"estado|notific")
        c_tipo = _col(enc, r"tipo")
        c_imp = _col(enc, r"imp|r[eé]g")
        for f in t["filas"]:
            g = lambda i: f[i] if i is not None and i < len(f) else ""
            estado = g(c_estado)
            asunto = g(c_asunto)
            cl = clasificar(asunto, g(c_tipo))
            out.append({"fecha": g(c_fecha), "organismo": "AGIP", "asunto": asunto, "clasificacion": g(c_tipo),
                        "impuesto": g(c_imp), "estado": estado or "", "importancia": cl.get("importancia", "Media"),
                        "notificado": "" if re.search(r"sin notificar|pendiente", estado, re.I) else estado,
                        "leida": not re.search(r"sin notificar|no le[ií]d|pendiente", estado, re.I)})
    return out


def deuda_de(tablas: list[dict]) -> float | None:
    total = None
    for t in tablas:
        c = _col(t["encabezados"], r"^total|importe|saldo|monto")
        if c is None:
            continue
        s = sum(v for v in (_num(f[c]) for f in t["filas"] if c < len(f)) if v)
        total = (total or 0.0) + s
    return total


def paso(usuario: str, clave: str, cuit: str, estado: dict, visible: bool = True):
    """Ingresa a AGIP con su propia sesión (como ARBA). usuario = CUIT de quien tiene la Clave Ciudad."""
    def fn():
        hoy = date.today().isoformat()
        destino = os.path.join(DATOS, cuit, "agip", hoy)
        os.makedirs(destino, exist_ok=True)
        r = {"cuit": cuit, "fecha": hoy, "usuario": usuario, "comunicaciones": [], "deuda": {"tablas": [], "total": None},
             "fiscalizacion": [], "servicios": {}, "alertas": []}
        with arca.navegador(visible=visible) as ctx:
            try:
                page = login(ctx, usuario, clave)
                _elegir_representado_portal(page, cuit)
                inicio = page.url
                for clave_srv, textos in SERVICIOS:
                    try:
                        pag = _abrir(ctx, page, textos)
                        if pag is None:
                            r["servicios"][clave_srv] = "no encontrado en el portal"
                            continue
                        if not _elegir_cuit(pag, cuit):
                            r["servicios"][clave_srv] = f"no se pudo confirmar que muestre el CUIT {arca.cuit_fmt(cuit)}"
                            arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), f"agip_{clave_srv}_cuit")
                        else:
                            tablas = _tablas(pag)
                            if clave_srv == "dfe":
                                r["comunicaciones"] = comunicaciones_de(tablas)
                                r["dfe_tablas"] = tablas
                            elif clave_srv == "deuda":
                                r["deuda"] = {"tablas": tablas, "total": deuda_de(tablas)}
                            elif clave_srv == "cct":
                                pag.wait_for_timeout(3000)               # la página arma los importes con JavaScript
                                r["cct"] = leer_cct(pag.inner_text("body"))
                            else:
                                r["fiscalizacion"] = [f for t in tablas for f in t["filas"]]
                                r["fiscalizacion_tablas"] = tablas
                            r["servicios"][clave_srv] = ("OK" if clave_srv == "cct"
                                                         else f"OK ({sum(len(t['filas']) for t in tablas)} filas)")
                        if pag is not page:
                            pag.close()
                        else:
                            page.goto(inicio, wait_until="domcontentloaded")
                        arca.pausa()
                    except arca.ErrorRobot:
                        raise
                    except Exception as e:
                        r["servicios"][clave_srv] = f"error: {str(e).splitlines()[0][:160]}"
                        arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), f"agip_{clave_srv}")
            except Exception:
                arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "agip")
                raise
        sin_abrir = [c for c in r["comunicaciones"] if not c["leida"]]
        altas = [c for c in sin_abrir if c["importancia"] == "ALTA"]
        r["sin_abrir"], r["altas_sin_abrir"] = len(sin_abrir), len(altas)
        for c in altas:
            r["alertas"].append({"prioridad": "ALTA", "tipo": "AGIP: comunicación importante sin abrir",
                                 "texto": f"{c['fecha']} · {c['asunto']}"})
        if r["fiscalizacion"]:
            r["alertas"].append({"prioridad": "ALTA", "tipo": "AGIP: fiscalización electrónica",
                                 "texto": f"{len(r['fiscalizacion'])} registro(s) en Fiscalización Electrónica"})
        if r.get("cct"):
            r["alertas"] += alertas_cct(r["cct"])
        elif (r["deuda"]["total"] or 0) >= 15_000:
            r["alertas"].append({"prioridad": "Media", "tipo": "AGIP: deuda",
                                 "texto": f"Estado de cuenta con saldo {r['deuda']['total']:,.2f}"})
        with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        estado.update({k: r[k] for k in ("servicios", "sin_abrir", "altas_sin_abrir", "alertas")})
        if not any(str(v).startswith("OK") for v in r["servicios"].values()):
            raise arca.ErrorRobot(f"AGIP: no se pudo leer ningún servicio {r['servicios']}")
        return "OK"
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=True, **_):
    """Llamado por robots.correr (robot 'agip'): usuario/clave son los de AGIP en el almacén."""
    estado: dict = {}
    paso(usuario, clave, cuit, estado, visible=True)()
    return {"cuit": cuit, "agip": estado, "archivos": {"agip": {"alertas": estado.get("alertas", [])}}}
