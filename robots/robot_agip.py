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
    # "deuda" (Estado de Cuenta) ya no existe en el portal (Gaby 26/11/2026): la deuda sale de la Nueva Cuenta
    # Corriente Tributaria ("cct").
    ("fiscalizacion", ["Fiscalización Electrónica AGIP", "Fiscalización Electrónica", "Fiscalizacion Electronica"]),
    # Nueva Cuenta Corriente Tributaria (portal-cct.agip.gob.ar), relevada con Gaby el 18/11/2026 (Dinafer S R L)
    ("cct", ["Nueva Cuenta Corriente Tributaria", "Cuenta Corriente Tributaria"]),
    # Gestión-AR (lb.agip.gob.ar/gestionArciba/?url=cc), relevado con Gaby el 21/11/2026 (Nabajuma): "Consulta de
    # Retenciones / Percepciones" -> CUIT, Mes/Año desde/hasta, Régimen (Todas, Retenciones, Percepciones, Retenciones
    # Bancarias, Retenciones SIRTAC, Percepciones Aduaneras) -> Buscar -> solapas con tabla y "Descargar Excel" (CSV)
    ("percepciones", ["Gestion-AR Agtes. de Recaudacion", "Gestión-AR Agtes. de Recaudación", "Gestion-AR"]),
]
MESES_PERCEPCIONES = 13


def leer_csv_percepciones(texto: str) -> list[dict]:
    """CSV de 'Descargar Excel' de la solapa Percepciones (sep=, ; primera línea 'sep=,'):
    CUIT,N° Ader,Razon Social,N° Certificado,Norma,Fecha Percepcion,Tipo Comprobante,N° Comprobante,Fecha Comprobante,
    Monto Percibido,Base Calculo   (importes 1234.56; comprobante 'A0   1000000053499')."""
    import csv
    import io
    lineas = [l for l in texto.splitlines() if l.strip() and not l.lower().startswith("sep=")]
    out = []
    for f in csv.DictReader(io.StringIO("\n".join(lineas))):
        f = {re.sub(r"[^a-z]", "", k.lower()): (v or "").strip() for k, v in f.items() if k and isinstance(v, str)}
        cuit_ag = re.sub(r"\D", "", f.get("cuit", ""))
        if len(cuit_ag) != 11:
            continue
        try:
            imp = float((f.get("montopercibido") or f.get("importepercibido") or "0").replace(",", ""))
        except ValueError:
            imp = 0.0
        out.append({"agente": cuit_ag, "nombre": f.get("razonsocial", ""), "fecha": f.get("fechapercepcion", ""),
                    "tipo": f.get("tipocomprobante", ""), "comprobante": re.sub(r"\s+", "", f.get("ncomprobante", "")),
                    "fecha_comprobante": f.get("fechacomprobante", ""), "importe": imp, "norma": f.get("norma", ""),
                    "operacion": "PERCEPCION"})
    return out


MESES_CORTOS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def elegir_mes(pag, campo, anio: int, mes: int) -> None:
    """Mes/Año de Gestión-AR (Gaby, 25/11/2026): el campo NO deja escribir, se elige en el calendario de meses
    («  2026  » arriba; Ene..Dic). Se abre el calendario, se va al año y se hace clic en el mes."""
    campo.click()
    pag.wait_for_timeout(500)
    caja = pag.locator(".datepicker-months, .datepicker").filter(visible=True).last
    for _ in range(15):
        try:
            cab = caja.locator(".datepicker-switch, th.switch").filter(visible=True).first.inner_text(timeout=3000)
            actual = int(re.search(r"\d{4}", cab)[0])
        except Exception:
            break
        if actual == anio:
            break
        caja.locator(".prev" if actual > anio else ".next").filter(visible=True).first.click()
        pag.wait_for_timeout(300)
    m = caja.locator("span.month, .month").filter(has_text=re.compile(rf"^\s*{MESES_CORTOS[mes - 1]}\s*$", re.I)).filter(visible=True)
    if m.count():
        m.first.click()
        pag.wait_for_timeout(500)
    valor = f"{mes:02d}/{anio}"
    if campo.input_value().strip() != valor:            # respaldo: el datepicker de jQuery por código
        campo.evaluate("""(e, v) => { try { if (window.jQuery && jQuery(e).datepicker) {
              jQuery(e).datepicker('setDate', new Date(Number(v.slice(3)), Number(v.slice(0, 2)) - 1, 1)); } } catch (x) {}
            if (e.value !== v) { e.value = v; ['input', 'change'].forEach(t => e.dispatchEvent(new Event(t, {bubbles: true}))); } }""", valor)
    pag.keyboard.press("Escape")
    if campo.input_value().strip() != valor:
        raise arca.ErrorRobot(f"AGIP Gestión-AR: no se pudo elegir {valor} en el calendario (quedó '{campo.input_value()}')")


def leer_percepciones(pag, cuit: str, hoy: date) -> list[dict]:
    """Gestión-AR: Régimen 'Percepciones' de los últimos 13 meses -> Descargar Excel (CSV). Si la descarga falla, lee
    la tabla de la pantalla."""
    a, m = hoy.year, hoy.month - MESES_PERCEPCIONES
    while m <= 0:
        a, m = a - 1, m + 12
    campos = pag.locator("input[type=text], input:not([type])").filter(visible=True)
    vals = {}
    for i in range(campos.count()):
        c = campos.nth(i)
        etiqueta = c.evaluate("e => { const l = e.closest('div, td'); return l ? l.innerText : ''; }") or ""
        if re.search(r"desde", etiqueta, re.I):
            vals["desde"] = c
        elif re.search(r"hasta", etiqueta, re.I):
            vals["hasta"] = c
    if "desde" not in vals or "hasta" not in vals:
        raise arca.ErrorRobot("AGIP Gestión-AR: no se encontraron los campos Mes/Año desde/hasta")
    elegir_mes(pag, vals["desde"], a, m)
    elegir_mes(pag, vals["hasta"], hoy.year, hoy.month)
    sel = pag.locator("select").filter(has=pag.locator("option", has_text=re.compile(r"^\s*Percepciones\s*$", re.I)))
    if sel.count():
        sel.first.select_option(label=next(o for o in sel.first.locator("option").all_inner_texts()
                                           if re.fullmatch(r"\s*Percepciones\s*", o, re.I)).strip())
    pag.locator("button, input[type=submit], a").filter(has_text=re.compile(r"^\s*Buscar\s*$", re.I)).first.click()
    pag.wait_for_load_state("domcontentloaded")
    pag.wait_for_timeout(3000)
    solapa = pag.locator("a, li, button").filter(has_text=re.compile(r"^\s*Percepciones\s*$", re.I)).filter(visible=True)
    if solapa.count():
        solapa.first.click()
        pag.wait_for_timeout(2000)
    boton = pag.locator("a, button").filter(has_text=re.compile(r"Descargar\s+Excel", re.I)).filter(visible=True)
    if boton.count():
        try:
            with pag.expect_download(timeout=60_000) as dl:
                boton.first.click()
            ruta = dl.value.path()
            crudo = open(ruta, "rb").read()
            return leer_csv_percepciones(crudo.decode("latin-1"))
        except Exception:
            pass
    filas = []                                               # respaldo: la tabla de la pantalla
    for t in _tablas(pag):
        enc = [e.lower() for e in t.get("encabezados") or []]
        if not any("percib" in e for e in enc):
            continue
        for f in t["filas"]:
            d = dict(zip(enc, f))
            g = lambda pat: next((v for k, v in d.items() if re.search(pat, k)), "")
            filas.append({"agente": re.sub(r"\D", "", g(r"^cuit")), "nombre": g(r"raz"), "fecha": g(r"fecha perc"),
                          "tipo": g(r"tipo"), "comprobante": re.sub(r"\s+", "", g(r"de cpte|comprob")),
                          "fecha_comprobante": g(r"fecha cpte|fecha comp"), "importe": _num(g(r"percib")) or 0.0,
                          "norma": g(r"norma"), "operacion": "PERCEPCION"})
    return [f for f in filas if len(f["agente"]) == 11]


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
        _esperar_tarjetas(page)
        # 25/11/2026 (Nabajuma): pantalla "Seleccione Representado" con botón Ingresar; sin el clic se queda ahí y
        # ningún servicio aparece ("no encontrado en el portal")
        # solo en la pantalla dedicada "Seleccione Representado" (en el menú principal hay otros "Ingresar" que sacan
        # del menú: 25/11/2026 21:36, ningún servicio aparecía)
        es_pantalla = bool(re.search(r"Seleccione\s+Representado", page.inner_text("body")[:2000], re.I)) \
            and not re.search(r"menu_principal", page.url)
        boton = page.locator("a, button, input[type=submit], input[type=button]").filter(
            has_text=re.compile(r"^\s*Ingresar\s*$", re.I)).filter(visible=True)
        if not boton.count():
            boton = page.locator("input[value='Ingresar' i]").filter(visible=True)
        if es_pantalla and boton.count():
            boton.first.click()
            try:
                page.wait_for_load_state("domcontentloaded", timeout=30_000)
            except Exception:
                pass
            arca.pausa(2.0, 3.0)
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


def login_miba(ctx, usuario: str, clave: str):
    """Ingreso con cuenta miBA (22/11/2026, Gaby entra así): claveciudad.agip.gob.ar -> "Iniciar sesión" ->
    login.buenosaires.gob.ar ("Ingresá a tu cuenta de la Ciudad": CUIL o correo + contraseña -> Iniciar sesión) ->
    vuelve a claveciudad.agip.gob.ar/menu_principal.php."""
    page = ctx.new_page()
    page.goto(PORTAL, wait_until="domcontentloaded")
    arca.pausa(1.2, 2.0)
    boton = page.locator("a.btn-miba-login, a[href*='miba'], a:has-text('Iniciar sesión'), button:has-text('Iniciar sesión')")
    if not boton.count():
        raise arca.ErrorRobot("AGIP: no aparece el botón de ingreso con miBA")
    boton.first.click()
    try:
        page.wait_for_url(re.compile(r"login\.buenosaires\.gob\.ar"), timeout=30_000)
    except Exception:
        pass
    page.wait_for_load_state("domcontentloaded")
    arca.pausa(1.0, 1.8)
    usu = page.locator("#username, input[name=username], input[autocomplete=username]").first
    pas = page.locator("#password, input[name=password], input[type=password]").first
    arca._tipear(usu, usuario)
    arca._tipear(pas, clave)
    arca.pausa(0.4, 0.9)
    page.locator("#kc-login, button[type=submit], input[type=submit]").first.click()
    try:
        page.wait_for_url(re.compile(r"claveciudad\.agip\.gob\.ar"), timeout=45_000)
    except Exception:
        err = ""
        try:
            err = page.locator(".alert-error, .kc-feedback-text, #input-error, [class*=error]").first.inner_text(timeout=2000).strip()
        except Exception:
            pass
        if re.search(r"c[oó]digo|verificaci|segundo factor|OTP", page.inner_text("body"), re.I):
            raise arca.RequiereIntervencion("miBA pide un código de verificación: no se puede ingresar automáticamente")
        raise arca.ClaveInvalida(f"miBA no aceptó el usuario o la contraseña{': ' + err if err else ''}")
    page.wait_for_load_state("domcontentloaded")
    arca.pausa(1.5, 2.5)
    return page


def login(ctx, usuario: str, clave: str, miba: tuple | None = None):
    """Clave Ciudad (CUIT del administrador de relaciones + clave); si AGIP la rechaza, la cuenta miBA cargada aparte
    (Gaby 25/11/2026: dos casilleros, usuario CUIL o mail) o, si no hay, la misma clave como cuenta miBA."""
    if not usuario and miba:
        return login_miba(ctx, miba[0], miba[1])
    try:
        return _login_clave_ciudad(ctx, usuario, clave)
    except arca.ClaveInvalida as e:
        if miba:
            for p in list(ctx.pages):
                try:
                    p.close()
                except Exception:
                    pass
            try:
                return login_miba(ctx, miba[0], miba[1])
            except arca.RequiereIntervencion:
                raise
            except Exception as e2:
                raise arca.ClaveInvalida(f"{e} y la cuenta miBA tampoco entró ({e2})")
        for p in list(ctx.pages):
            try:
                p.close()
            except Exception:
                pass
        try:
            return login_miba(ctx, usuario, clave)
        except arca.RequiereIntervencion:
            raise
        except Exception:
            raise arca.ClaveInvalida(f"{e} (tampoco entra como cuenta miBA)")


def _login_clave_ciudad(ctx, usuario: str, clave: str):
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
    eligio = False
    if cuit in texto or fmt in texto:
        sel = page.locator("select").filter(has=page.locator(f"option:has-text('{cuit}'), option:has-text('{fmt}')"))
        if sel.count():
            eligio = True
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
    es_dfe = "/dfe" in page.url

    def _identidad(t: str) -> bool:                   # el renglón "CUIT: …" / "Contribuyente: …" de arriba
        m = re.search(r"(?:CUIT:|Contribuyente:)[^\n]{0,120}", t)
        return bool(m) and cuit in re.sub(r"\D", "", m[0])
    encabezado_ok = (eligio or _identidad(texto)) if es_dfe else (cuit in texto[:1500] or fmt in texto[:1500])
    if not encabezado_ok:
        # DFE (lb.agip.gob.ar/dfe, Gaby 25/11/2026): entra con el usuario del estudio; menú "Representado" -> el cliente
        try:
            rep = page.locator("a, button, li").filter(has_text=re.compile(r"^\s*Representado\s*$", re.I)).filter(visible=True)
            if rep.count():
                rep.first.click()
                page.wait_for_timeout(800)
                item = page.locator("a, li").filter(has_text=cuit).filter(visible=True)
                if item.count():
                    item.last.click()
                    page.wait_for_load_state("domcontentloaded")
                    arca.pausa(2.0, 3.0)
                    texto = page.inner_text("body")
                    return _identidad(texto) if es_dfe else (cuit in texto or fmt in texto)
        except Exception:
            pass
        if es_dfe:                                      # la tabla mezcla a todos los representados: no se lee
            return False
    return cuit in texto or fmt in texto


def _esperar_tarjetas(page) -> None:
    """Al elegir representado el menú recarga las tarjetas (a veces recarga toda la página): se espera."""
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    page.wait_for_timeout(3000)


def _representado_actual(page) -> str:
    try:
        sel = page.locator("select").filter(has=page.locator("option", has_text=re.compile(r"\[\d{2}-\d{8}-\d\]")))
        return sel.first.evaluate("x => (x.options[x.selectedIndex] || {}).text || ''") if sel.count() else ""
    except Exception:
        return ""


def _cambiar_representado(page, cuit: str | None) -> bool:
    """Menú de Clave Ciudad: "Seleccione un representado" (la lista de tarjetas cambia según a quién se representa).
    cuit=None -> la primera opción (el propio usuario). Devuelve True si cambió algo."""
    try:
        sel = page.locator("select").filter(has=page.locator("option", has_text=re.compile(r"\[\d{2}-\d{8}-\d\]")))
        if not sel.count():
            return False
        ops = sel.first.locator("option")
        if cuit:
            fmt = arca.cuit_fmt(cuit)
            op = sel.first.locator(f"option:has-text('{fmt}'), option:has-text('{cuit}')")
            if not op.count():
                return False
            v = op.first.get_attribute("value")
        else:
            v = ops.first.get_attribute("value")
        if sel.first.input_value() == v:
            return False
        sel.first.select_option(value=v)
        _esperar_tarjetas(page)
        return True
    except Exception:
        return False


URL_DIRECTA = {"percepciones": "https://claveciudad.agip.gob.ar/?s=agip_gestion_arciba"}   # Gaby, 25/11/2026


def _abrir_servicio(ctx, page, cuit: str, textos: list[str], clave_srv: str = ""):
    """25/11/2026 (Gaby, Nabajuma): las tarjetas dependen del representado elegido arriba. Se busca con el cliente
    elegido; si no está, con el propio usuario (la aplicación pregunta después a quién se representa: _elegir_cuit)."""
    # Gaby (25/11/2026): el robot buscaba las tarjetas con MEYOYAN elegido y no con NABAJUMA: se asegura el cliente
    if arca.cuit_fmt(cuit) not in _representado_actual(page):
        _cambiar_representado(page, cuit)
    pag = None
    for _ in range(3):                                  # las tarjetas pueden tardar en aparecer
        pag = _abrir(ctx, page, textos)
        if pag is not None:
            break
        page.wait_for_timeout(3000)
    if pag is None and _cambiar_representado(page, None):
        pag = _abrir(ctx, page, textos)
        if pag is None or pag is not page:
            _cambiar_representado(page, cuit)            # el menú vuelve a quedar con el cliente
    if pag is None and URL_DIRECTA.get(clave_srv):
        # 25/11/2026: con el usuario del estudio la tarjeta de Gestión-AR no figura en el menú, pero la dirección
        # directa lleva a "Seleccione Representado" (NOMBRE [cuit] -> Ingresar) y de ahí a Gestión-AR
        pag = ctx.new_page()
        pag.goto(URL_DIRECTA[clave_srv], wait_until="domcontentloaded")
        pag.wait_for_timeout(3000)
    return pag


def _abrir(ctx, page, textos: list[str]):
    """Abre un servicio del portal por el texto del enlace. Devuelve la pestaña (nueva o la misma) o None."""
    for t in textos:
        link = page.locator(f"a:has-text('{t}')").filter(visible=True)
        if not link.count():                             # tarjetas del menú que no son <a> (captura 20/11/2026)
            link = page.get_by_text(t, exact=True).filter(visible=True)
        if not link.count():
            link = page.locator("h1, h2, h3, h4, h5, h6, strong, b, .card-title, .titulo").filter(
                has_text=re.compile(rf"^\s*{re.escape(t)}", re.I)).filter(visible=True)
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


def _es_convenio(cuit: str) -> bool:
    """Convenio Multilateral según la ficha, lo deducido de SIFERE o el Padrón Web de COMARB."""
    try:
        from .correr import regimen_iibb
        if "convenio" in (regimen_iibb(cuit).get("regimen") or "").lower():
            return True
    except Exception:
        pass
    try:
        import glob as _g
        r = sorted(_g.glob(os.path.join(DATOS, cuit, "padron_cm", "*.json")))
        return bool(r) and bool(json.load(open(r[-1], encoding="utf-8")).get("en_padron"))
    except Exception:
        return False


def paso(usuario: str, clave: str, cuit: str, estado: dict, visible: bool = True, miba: tuple | None = None,
         meses: int | None = None):
    """Ingresa a AGIP con su propia sesión (como ARBA). usuario = CUIT de quien tiene la Clave Ciudad."""
    def fn():
        hoy = date.today().isoformat()
        destino = os.path.join(DATOS, cuit, "agip", hoy)
        os.makedirs(destino, exist_ok=True)
        r = {"cuit": cuit, "fecha": hoy, "usuario": usuario, "comunicaciones": [], "deuda": {"tablas": [], "total": None},
             "fiscalizacion": [], "servicios": {}, "alertas": []}
        with arca.navegador(visible=visible) as ctx:
            try:
                page = login(ctx, usuario, clave, miba)
                _elegir_representado_portal(page, cuit)
                inicio = page.url
                try:                                     # constancia de inscripción de IIBB (Gaby, 25/11/2026)
                    from . import robot_agip_constancia
                    if _es_convenio(cuit):
                        # Gaby: la constancia de AGIP existe solo para locales CABA; en Convenio está en el Padrón Web
                        r["servicios"]["constancia"] = "no corresponde (Convenio Multilateral: constancia en el Padrón Web de COMARB)"
                    else:
                        cons = robot_agip_constancia.bajar(ctx, page, cuit)
                        r["servicios"]["constancia"] = f"OK ({cons.get('categoria') or 'sin categoría'})"
                except arca.CuitEquivocado:
                    raise
                except Exception as e:
                    r["servicios"]["constancia"] = f"error: {str(e).splitlines()[0][:160] if str(e) else type(e).__name__}"
                    arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "agip_constancia")
                for p in list(ctx.pages):
                    if p is not page:
                        try:
                            p.close()
                        except Exception:
                            pass
                if page.url != inicio:
                    page.goto(inicio, wait_until="domcontentloaded")
                for clave_srv, textos in SERVICIOS:
                    try:
                        pag = _abrir_servicio(ctx, page, cuit, textos, clave_srv)
                        if pag is None:
                            r["servicios"][clave_srv] = "no encontrado en el portal"
                            caps = arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), f"agip_{clave_srv}_no_encontrado")
                            if clave_srv == "percepciones":          # queda en el diagnóstico de la Biblioteca
                                from . import biblioteca_archivos as _bib
                                _bib.guardar_diagnostico(cuit, "agip", {"estado": "error", "pasos": [
                                    {"paso": "Clave Ciudad -> representado", "ok": True},
                                    {"paso": "Menú de Clave Ciudad: tarjeta 'Gestión-AR Agtes. de Recaudación'", "ok": False}],
                                    "error": "no aparece la tarjeta de Gestión-AR en el menú (ver captura)",
                                    "captura": os.path.basename(caps[0]) if caps else ""})
                            continue
                        if not _elegir_cuit(pag, cuit) and clave_srv == "fiscalizacion":
                            # Gaby (25/11/2026): Fiscalización Electrónica solo muestra algo si hay una abierta; si la hay,
                            # llega aviso al DFE. Sin el CUIT en pantalla = sin fiscalización abierta, no es una falla.
                            r["servicios"][clave_srv] = "OK (sin fiscalización abierta)"
                        elif not _elegir_cuit(pag, cuit):
                            r["servicios"][clave_srv] = f"no se pudo confirmar que muestre el CUIT {arca.cuit_fmt(cuit)}"
                            caps = arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), f"agip_{clave_srv}_cuit")
                            if clave_srv == "percepciones":
                                from . import biblioteca_archivos as _bib
                                _bib.guardar_diagnostico(cuit, "agip", {"estado": "error", "pasos": [
                                    {"paso": "Clave Ciudad -> Gestión-AR", "ok": True},
                                    {"paso": "Seleccione Representado / elegir el CUIT del cliente", "ok": False}],
                                    "error": r["servicios"][clave_srv], "captura": os.path.basename(caps[-1]) if caps else ""})
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
                                if r["deuda"]["total"] is None and r["cct"].get("saldo_deudor") is not None:
                                    # la deuda de AGIP sale de la Nueva Cuenta Corriente Tributaria (26/11/2026)
                                    r["deuda"]["total"] = round((r["cct"].get("saldo_deudor") or 0.0)
                                                                + (r["cct"].get("intereses") or 0.0), 2)
                            elif clave_srv == "percepciones":
                                # 25/11/2026 (Gabriel): todas las solapas, 2 meses, archivos y diagnóstico
                                from . import robot_agip_retenciones
                                try:
                                    rr = robot_agip_retenciones.bajar(ctx, pag, cuit, meses=meses)
                                    r["percepciones"] = rr["percepciones"]
                                    r["retenciones_percepciones"] = rr["meses"]
                                except arca.CuitEquivocado:
                                    raise
                                except Exception as e:           # el diagnóstico y la captura ya quedaron guardados
                                    r["servicios"][clave_srv] = f"error: {str(e).splitlines()[0][:160] if str(e) else type(e).__name__}"
                                    if pag is not page:
                                        pag.close()
                                    else:
                                        page.goto(inicio, wait_until="domcontentloaded")
                                    continue
                            else:
                                r["fiscalizacion"] = [f for t in tablas for f in t["filas"]]
                                r["fiscalizacion_tablas"] = tablas
                            r["servicios"][clave_srv] = ("OK" if clave_srv == "cct"
                                                         else f"OK ({len(r['percepciones'])} percepciones)" if clave_srv == "percepciones"
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
            except Exception as e:
                caps = arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "agip")
                if not r["servicios"]:                        # no llegó a entrar: queda en el diagnóstico de la Biblioteca
                    from . import biblioteca_archivos as _bib
                    _bib.guardar_diagnostico(cuit, "agip", {"estado": "error", "pasos": [
                        {"paso": "Ingreso a AGIP (Clave Ciudad / miBA)", "ok": False}],
                        "error": f"{type(e).__name__}: {e}"[:300], "captura": os.path.basename(caps[-1]) if caps else ""})
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
        if r.get("percepciones") is not None:            # percepciones de IIBB CABA vs Libro IVA (21/11/2026)
            try:
                from . import percepciones
                percepciones.cruzar(cuit)
            except Exception:
                pass
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
