"""Ingreso a ARCA con clave fiscal y apertura de servicios del portal.

IMPORTANTE – primera prueba real:
  Los selectores de la pantalla de login están marcados con  # VERIFICAR. ARCA cambia el
  diseño cada tanto; en la primera corrida con --ver (navegador visible) se confirman y,
  si hace falta, se ajustan acá en un solo lugar.

Reglas de seguridad del robot:
  - Nunca reintenta un login fallido por clave: ARCA bloquea la clave tras varios intentos.
  - Si aparece captcha, token, cambio de clave obligatorio o aceptación de términos,
    se detiene y marca "Requiere intervención". No resuelve captchas ni acepta nada.
  - No presenta, paga, genera VEP ni abre notificaciones: solo consulta y descarga.
"""
from __future__ import annotations

import random
import re
import time
from contextlib import contextmanager

from playwright.sync_api import Browser, BrowserContext, Page, TimeoutError as PWTimeout, sync_playwright

URL_LOGIN = "https://auth.afip.gob.ar/contribuyente_/login.xhtml"
URL_PORTAL = "https://portalcf.cloud.afip.gob.ar/portal/app/"
URL_MIS_SERVICIOS = "https://portalcf.cloud.afip.gob.ar/portal/app/mis-servicios"

# Identificador del botón de cada servicio en "Mis servicios" (visto el 14/11/2026)
SERVICIOS = {
    "mis_comprobantes": "mcmp",
    "cuentas_tributarias": "cuenta_corriente_contrib",
    "mis_facilidades": "misfacilidades",
    "domicilio_fiscal": "e-ventanilla",
    "declaracion_en_linea": "sudeclaracion",
    "sifere_consultas": "comarb_sifereweb_consultas",
    "mis_retenciones": "mis_retenciones",
    # sin identificador relevado: se busca por el título de la tarjeta en "Mis servicios"
    "ddjj_simplificada": "texto:DECLARACI[OÓ]N JURADA SIMPLIFICADA",
    "portal_iva": "texto:PORTAL\\s+IVA",                # verificado contra ARCA el 16/11/2026
    "nuestra_parte": "texto:NUESTRA\\s+PARTE",          # VERIFICAR en la primera corrida
    # traídos de Radar fiscal (17/11/2026): nombres a VERIFICAR en la primera corrida real
    "fiscalizacion_electronica": "texto:FISCALIZACI[OÓ]N\\s+ELECTR[OÓ]NICA",
    "ordenes_intervencion": "texto:(CONSULTA\\s+DE\\s+)?[OÓ]RDENES\\s+DE\\s+INTERVENCI[OÓ]N",
    "siace": "texto:SIACE|CONTROLES\\s+ELECTR[OÓ]NICOS",
    # relevados con Gaby el 17/11/2026 (control de pagos de autónomos y monotributo)
    "ccma": "texto:CCMA\\s*-\\s*CUENTA\\s+CORRIENTE\\s+DE\\s+CONTRIBUYENTES",   # NO "CCMA - ARBA - ..."
    "monotributo": "texto:^\\s*MONOTRIBUTO\\s*$",
}


class ErrorRobot(Exception):
    """Error genérico del robot (se puede reintentar más tarde)."""


class ClaveInvalida(ErrorRobot):
    """ARCA rechazó CUIT/clave. NO reintentar: avisar al estudio."""


class RequiereIntervencion(ErrorRobot):
    """Captcha, token, cambio de clave, términos, etc. Necesita una persona."""


def pausa(min_s: float = 1.5, max_s: float = 4.0) -> None:
    """Pausa con variación para no golpear los portales."""
    time.sleep(random.uniform(min_s, max_s))


def _comarb_a_https(route):
    url = route.request.url
    nueva = re.sub(r"^http://([^/:]+)(?::80)?", r"https://\1", url)
    route.fulfill(status=307, headers={"Location": nueva})


@contextmanager
def navegador(visible: bool = False, carpeta_descargas: str | None = None):
    with sync_playwright() as pw:
        browser: Browser = pw.chromium.launch(headless=not visible)
        ctx: BrowserContext = browser.new_context(
            accept_downloads=True, locale="es-AR", timezone_id="America/Argentina/Buenos_Aires",
            viewport={"width": 1366, "height": 900})
        ctx.set_default_timeout(45_000)
        # COMARB (SIFERE) redirige a direcciones "http://" que desde la red del estudio no responden
        # (relevado el 15/11/2026: http://app1.comarb.gob.ar se agota; https:// responde). Chrome de
        # escritorio las pasa solo a https; el robot hace lo mismo, únicamente para sitios de COMARB.
        ctx.route(re.compile(r"^http://[^/]*comarb\.gob\.ar(?::80)?/"), _comarb_a_https)
        try:
            yield ctx
        finally:
            ctx.close()
            browser.close()


def _hay_texto(page: Page, patron: str) -> bool:
    try:
        return page.get_by_text(re.compile(patron, re.I)).first.is_visible(timeout=1500)
    except Exception:
        return False


def _hay_visible(page: Page, selector: str) -> bool:
    """True solo si algún elemento que coincide está realmente visible en pantalla
    (la página de ARCA tiene elementos 'captcha' ocultos que no deben frenar al robot)."""
    loc = page.locator(selector)
    for i in range(min(loc.count(), 10)):
        try:
            el = loc.nth(i)
            if el.is_visible():
                caja = el.bounding_box()
                if caja and caja["width"] > 20 and caja["height"] > 20:
                    return True
        except Exception:
            continue
    return False


def _detectar_bloqueos(page: Page) -> None:
    if _hay_visible(page, "img[src*='captcha' i], iframe[src*='recaptcha' i], iframe[src*='hcaptcha' i], "
                          "iframe[title*='captcha' i], [id*='captcha' i], [class*='captcha' i]"):
        raise RequiereIntervencion("El login pide captcha")
    if _hay_texto(page, r"token|segundo factor|c[oó]digo de verificaci[oó]n"):
        raise RequiereIntervencion("El login pide token / segundo factor")
    if _hay_texto(page, r"cambi(o|ar) (de )?(tu |su )?clave|clave (ha )?vencid"):
        raise RequiereIntervencion("ARCA pide cambio de clave")
    if _hay_texto(page, r"t[eé]rminos y condiciones|acepto"):
        raise RequiereIntervencion("ARCA pide aceptar términos")


def _tipear(campo, texto: str) -> None:
    """Escribe tecla por tecla (ARCA no toma los valores pegados de golpe)."""
    campo.click()
    campo.press("Control+a")
    campo.press("Backspace")
    campo.press_sequentially(texto, delay=random.randint(90, 160))


def _largo_campo(campo) -> int:
    """Cantidad de caracteres que tiene el campo (sin leer su contenido)."""
    return campo.evaluate("e => (e.value || '').length")


def login(ctx: BrowserContext, usuario: str, clave: str) -> Page:
    """Ingresa con CUIT/usuario y clave fiscal. Devuelve la página del portal."""
    page = ctx.new_page()
    page.goto(URL_LOGIN, wait_until="domcontentloaded")
    _detectar_bloqueos(page)

    # Paso 1: CUIT
    campo_cuit = page.locator("#F1\\:username, input[name='F1:username']")                # VERIFICAR
    if not campo_cuit.count():
        campo_cuit = page.get_by_label(re.compile(r"CUIT|CUIL|usuario", re.I)).first
    _tipear(campo_cuit, usuario)
    if _largo_campo(campo_cuit) != len(usuario):
        raise ErrorRobot("El campo CUIT no quedó completo; no se avanzó")
    pausa(0.5, 1.2)
    page.locator("#F1\\:btnSiguiente, input[name='F1:btnSiguiente']").first.click()          # VERIFICAR
    page.wait_for_load_state("domcontentloaded")
    _detectar_bloqueos(page)

    # Paso 2: clave
    campo_clave = page.locator("#F1\\:password, input[type='password']").first              # VERIFICAR
    _tipear(campo_clave, clave)
    if _largo_campo(campo_clave) != len(clave):
        # No se envía: evitar un intento fallido que sume para el bloqueo de la clave
        raise ErrorRobot("El campo clave no quedó completo; NO se envió a ARCA")
    pausa(0.5, 1.2)
    page.locator("#F1\\:btnIngresar, input[name='F1:btnIngresar']").first.click()            # VERIFICAR
    # ARCA tarda en pasar del login al portal: esperar hasta 30 s a que la URL salga de auth.afip.gob.ar
    # o a que aparezca un mensaje de error en la misma pantalla.
    import time as _t
    limite = _t.time() + 30
    while _t.time() < limite:
        if "auth.afip.gob.ar" not in page.url:
            break
        if _hay_texto(page, r"clave.*incorrect|usuario incorrect|datos.*incorrect|bloquead"):
            break
        page.wait_for_timeout(1000)
    page.wait_for_load_state("domcontentloaded")
    pausa()

    if "auth.afip.gob.ar" in page.url:
        _detectar_bloqueos(page)
        if _hay_texto(page, r"clave.*incorrect|usuario incorrect|datos.*incorrect|no es v[aá]lid|bloquead"):
            raise ClaveInvalida("ARCA rechazó la clave")
        raise ErrorRobot("No se pudo salir de la pantalla de login (motivo desconocido)")
    # Control: el portal tiene que mostrar el CUIT con el que se ingresó, no otro
    try:
        page.get_by_text(cuit_fmt(usuario)).first.wait_for(state="visible", timeout=15_000)
    except PWTimeout:
        otros = set(re.findall(r"\d{2}-\d{8}-\d", page.inner_text("body"))) - {cuit_fmt(usuario)}
        if otros:
            raise CuitEquivocado(f"El portal muestra otro CUIT ({', '.join(sorted(otros))}) en lugar de "
                                 f"{cuit_fmt(usuario)}")
    return page


def abrir_servicio(ctx: BrowserContext, portal: Page, servicio: str) -> Page:
    """Abre un servicio desde 'Mis servicios'. Los servicios abren pestaña nueva."""
    ident = SERVICIOS[servicio]
    portal.goto(URL_MIS_SERVICIOS, wait_until="domcontentloaded")
    pausa()
    verificar_sesion(portal, "portal")
    if ident.startswith("texto:"):
        portal.locator("a[role=button] h3").first.wait_for(state="attached", timeout=30_000)
        boton = portal.locator("a[role=button]").filter(
            has=portal.locator("h3", has_text=re.compile(ident[6:], re.I)))
    else:
        # Gaby 26/11/2026: con muchos servicios la lista tarda en dibujarse y el botón "no estaba" (Mis Retenciones y
        # Mis Facilidades de su propio CUIT, que sí tiene). Se espera a que aparezca antes de darlo por no habilitado.
        try:
            portal.locator("a[role=button], button").first.wait_for(state="attached", timeout=30_000)
        except Exception:
            pass
        titulo = {"mis_retenciones": r"MIS\s+RETENCIONES", "mis_facilidades": r"MIS\s+FACILIDADES",
                  "mis_comprobantes": r"MIS\s+COMPROBANTES", "cuentas_tributarias": r"CUENTAS?\s+TRIBUTARIA|CUENTA\s+CORRIENTE"}.get(servicio)
        limite = time.time() + 25
        while True:
            boton = portal.get_by_role("button", name=ident, exact=True)
            if not boton.count():
                boton = portal.locator(f"[title='{ident}'], [aria-label='{ident}']")
            if not boton.count() and titulo:
                boton = portal.locator("a[role=button]").filter(
                    has=portal.locator("h3", has_text=re.compile(titulo, re.I)))
            if boton.count() or time.time() > limite:
                break
            portal.wait_for_timeout(1500)
    if not boton.count():
        raise RequiereIntervencion(f"El servicio '{servicio}' no está habilitado para este contribuyente")
    antes = set(ctx.pages)
    pag = None
    for intento in range(2):                     # COMARB a veces tarda o el primer clic no "agarra"
        try:
            with ctx.expect_page(timeout=90_000) as nueva:
                boton.first.scroll_into_view_if_needed()
                boton.first.click()
            pag = nueva.value
            break
        except PWTimeout:
            nuevas = [p for p in ctx.pages if p not in antes]
            if nuevas:                           # se abrió aunque no se detectó el evento
                pag = nuevas[-1]
                break
            pausa(3, 6)
    if pag is None:
        raise ErrorRobot(f"El servicio '{servicio}' no abrió su pestaña (2 intentos de 90 s)")
    pag.wait_for_load_state("domcontentloaded")
    pausa()
    verificar_sesion(pag, servicio)
    return pag


class SesionPerdida(ErrorRobot):
    """La sesión venció o el servicio mandó de vuelta al login. El robot que la recibe puede
    volver a entrar desde cero (la clave ya fue aceptada en esta corrida), con un tope de
    reingresos. Si ARCA rechaza la clave en el reingreso, eso es ClaveInvalida y se corta."""


class SinRepresentado(ErrorRobot):
    """Se ingresó con la clave de otra persona y no se pudo elegir al cliente como representado.
    No se reintenta: revisar la relación/delegación en ARCA."""


class CuitEquivocado(SesionPerdida):
    """ARCA mostró datos de OTRO contribuyente (falla conocida: Cuentas Tributarias a veces
    muestra el CUIT de una sesión anterior). Se descarta lo leído y se vuelve a entrar."""


def cuit_fmt(cuit: str) -> str:
    return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"


def verificar_sesion(page: Page, servicio: str) -> None:
    if re.search(r"auth\.afip\.gob\.ar|expiredSession|FinSession", page.url, re.I):
        raise SesionPerdida(f"Al abrir '{servicio}' ARCA pidió volver a ingresar (sesión no aceptada). "
                            "(sesión vencida u otra sesión abierta con el mismo CUIT).")


def elegir_representado(page: Page, cuit: str) -> None:
    """Si el servicio muestra una lista de representados (delegación), elige el CUIT pedido."""
    cuit_fmt = f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"
    for texto in (cuit, cuit_fmt):
        loc = page.get_by_text(texto, exact=False)
        try:
            if loc.first.is_visible(timeout=2000):
                # si el CUIT ya figura en el encabezado como "representando a", no hay nada que hacer
                if _hay_texto(page, r"representando a"):
                    return
                loc.first.click()
                page.wait_for_load_state("domcontentloaded")
                pausa()
                return
        except PWTimeout:
            continue


def capturar(ctx: BrowserContext, carpeta: str, etapa: str) -> list[str]:
    """Guarda captura de cada pestaña abierta (para ver qué mostró el portal al fallar).
    Los campos de clave se ven como puntos, así que la captura no expone la clave."""
    import datetime as _dt
    import os as _os
    _os.makedirs(carpeta, exist_ok=True)
    sello = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    rutas = []
    for i, p in enumerate(ctx.pages):
        ruta = _os.path.join(carpeta, f"error_{etapa}_{sello}_{i}.png")
        try:
            p.screenshot(path=ruta, full_page=True)
            rutas.append(ruta)
        except Exception:
            pass
    return rutas


def cerrar_sesion(page: Page) -> None:
    try:
        page.goto(URL_PORTAL, wait_until="domcontentloaded")
        page.get_by_role("link", name=re.compile("salir|cerrar sesi", re.I)).first.click(timeout=5000)
    except Exception:
        pass


# ---------------------------------------------------------------- ejecución con reingreso
ESPERAS_CORTE = [30, 120, 300]        # segundos antes de cada reingreso: 30 s, 2 min, 5 min


def es_corte(e: Exception) -> bool:
    """Cortes de internet o de ARCA (página que no carga, tiempo agotado, navegador caído): se reintentan."""
    if isinstance(e, PWTimeout):
        return True
    t = str(e)
    return any(x in t for x in ("net::ERR_", "Timeout", "timed out", "Target page, context or browser has been closed",
                                 "Navigation failed", "Connection closed", "ECONNRESET", "browser has disconnected"))


def ejecutar(usuario: str, clave: str, pasos: list, carpeta_capturas: str, visible: bool = False,
             max_reingresos: int = 3, seguir_si_falla: bool = False) -> dict:
    """Ingresa una vez y ejecuta los pasos [(nombre, funcion(ctx, portal))] en orden.
    - Si un paso pierde la sesión o se corta internet/ARCA: espera (30 s, 2 min, 5 min), abre navegador
      nuevo, vuelve a entrar y sigue desde ESE paso (cada paso guarda su avance y no repite lo hecho).
    - Si un paso falla por otra causa: con seguir_si_falla=True se anota y se sigue con el siguiente.
    - Login: ClaveInvalida nunca se reintenta. Un corte durante el login se reintenta solo si en esta
      corrida ya hubo un ingreso exitoso (la clave está comprobada)."""
    pendientes = list(pasos)
    intentos: dict = {}
    res: dict = {"_reingresos": 0, "_errores": {}}
    ya_ingreso = False
    espera = 0
    while pendientes:
        if espera:
            time.sleep(espera)
            espera = 0
        with navegador(visible=visible) as ctx:
            try:
                portal = login(ctx, usuario, clave)
                ya_ingreso = True
            except ClaveInvalida:
                capturar(ctx, carpeta_capturas, "login")
                raise
            except Exception as e:
                capturar(ctx, carpeta_capturas, "login")
                intentos["_login"] = intentos.get("_login", 0) + 1
                if ya_ingreso and es_corte(e) and intentos["_login"] <= max_reingresos:
                    res["_reingresos"] += 1
                    espera = ESPERAS_CORTE[min(intentos["_login"], len(ESPERAS_CORTE)) - 1]
                    continue
                raise
            try:
                while pendientes:
                    nombre, fn = pendientes[0]
                    try:
                        res[nombre] = fn(ctx, portal)
                    except Exception as e:
                        reintentable = isinstance(e, SesionPerdida) or es_corte(e)
                        if not reintentable:
                            capturar(ctx, carpeta_capturas, nombre)
                            if not seguir_si_falla or isinstance(e, ClaveInvalida):
                                raise
                            res["_errores"][nombre] = f"{type(e).__name__}: {e}"
                        else:
                            capturar(ctx, carpeta_capturas,
                                     f"sesion_{nombre}" if isinstance(e, SesionPerdida) else f"corte_{nombre}")
                            intentos[nombre] = intentos.get(nombre, 0) + 1
                            agotado = intentos[nombre] > max_reingresos or res["_reingresos"] >= max_reingresos + 5
                            if agotado and not seguir_si_falla:
                                raise
                            if agotado:
                                res["_errores"][nombre] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                                pendientes.pop(0)
                            if pendientes:
                                res["_reingresos"] += 1
                                espera = ESPERAS_CORTE[min(intentos.get(nombre, 1), len(ESPERAS_CORTE)) - 1] \
                                    if not agotado else 10
                            break                         # cerrar y volver a entrar
                    pendientes.pop(0)
                    for p in list(ctx.pages):              # cerrar pestañas de servicios que quedaron abiertas
                        if p is not portal:
                            try:
                                p.close()
                            except Exception:
                                pass
                    if pendientes:
                        pausa(2, 5)
            finally:
                try:
                    cerrar_sesion(portal)
                except Exception:
                    pass
    return res


def periodos_ultimos(n: int, hasta: str | None = None) -> list[str]:
    """Últimos n meses COMPLETOS terminando en 'hasta' (AAAA-MM) o en el mes anterior al actual."""
    import datetime as _dt
    if hasta:
        a, m = map(int, hasta.split("-"))
    else:
        h = _dt.date.today().replace(day=1) - _dt.timedelta(days=1)
        a, m = h.year, h.month
    out = []
    for _ in range(n):
        out.append(f"{a}-{m:02d}")
        m -= 1
        if m == 0:
            a, m = a - 1, 12
    return list(reversed(out))
