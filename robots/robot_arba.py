"""Robot ARBA: impuesto determinado mensual de Ingresos Brutos (contribuyente LOCAL Buenos Aires).

Para los meses en que el cliente tributó como local en ARBA (antes del alta en Convenio Multilateral,
o clientes que siempre son locales). Relevado el 15/11/2026 con 20-33116278-8:
  Ingreso: sso.arba.gov.ar/Login/login  (CUIT + CIT, sin captcha según el estudio)
  Otros trámites -> Ingresos Brutos -> "Presentación de declaración jurada web"
     = app.arba.gov.ar/IBPresentaciones/...
  Consultas -> "Consultas DJ cerradas Anticipo"  (preBuscarDDJJCerradas.do)
     Formulario: estado=C, anioMensualDesde, mesDesde, anioMensualHasta, mesHasta, botón "buscar"
  Resultados (resultadosBusqueda.do), tabla #resultados:
     Nro. comprobante | Estado | Régimen | Año | Periodo | Tipo | Fecha inicio | Fecha cierre | (ícono "Ver detalle")
  Detalle (detalleDJView.do): "CUIT: 20-33116278-8  Año - Período: 2025 - 12 ... Tipo de DJ: Original"
     "Impuesto determinado de período  $ 1.294.963,80"
OJO: en esa aplicación hay formularios para ELIMINAR DJ pendientes y para presentar: el robot solo usa la
búsqueda de DJ CERRADAS y el ícono "Ver detalle". Nunca presenta ni borra nada.
"""
from __future__ import annotations

import json
import os
import re

from . import arca
from .lector_situacion import importe

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
URL_LOGIN = "https://sso.arba.gov.ar/Login/login?service=https%3A%2F%2Fapp.arba.gov.ar%3A443%2FGestionar%2Fdist%2Fgestionar"
URL_GESTIONAR = "https://app.arba.gov.ar/Gestionar/dist/gestionar"
URL_BUSCAR = "https://app.arba.gov.ar/IBPresentaciones/preBuscarDDJJCerradas.do"


def login(ctx, cuit: str, cit: str):
    page = ctx.new_page()
    page.goto(URL_LOGIN, wait_until="domcontentloaded")
    arca.pausa(1.0, 2.0)
    if page.locator("iframe[src*='captcha'], .g-recaptcha, [class*='captcha']").count():
        raise arca.RequiereIntervencion("ARBA pide captcha: no se puede ingresar automáticamente")
    # Formulario relevado el 15/11/2026: select#selectLoguin (CUIT/Host/Dominio), input#CUIT, input#clave_Cuit
    usuario = page.locator("input#CUIT")
    clave = page.locator("input#clave_Cuit")
    try:
        usuario.wait_for(state="attached", timeout=60_000)
    except Exception:
        _guardar_pantalla(page, cuit)
        raise arca.ErrorRobot("ARBA: no apareció el formulario de ingreso (ver arba_login_pantalla.txt)")
    sel = page.locator("select#selectLoguin")
    if sel.count():
        try:
            sel.select_option(index=0)               # opción "C.U.I.T. / C.U.I.L. / C.D.I."
        except Exception:
            pass
    usuario.wait_for(state="visible", timeout=30_000)
    arca._tipear(usuario, cuit)
    arca._tipear(clave, cit)
    arca.pausa(0.5, 1.2)
    boton = page.locator("button[type=submit]:visible, input[type=submit]:visible").filter(
        has_text=re.compile(r"ingres|iniciar|entrar|acceder", re.I))
    (boton.first if boton.count() else page.locator("button[type=submit], input[type=submit]").first).click()
    try:
        page.wait_for_url(re.compile(r"app\.arba\.gov\.ar|Gestionar", re.I), timeout=45_000)
    except Exception:
        texto = page.inner_text("body")
        if re.search(r"(clave|contrase[nñ]a|usuario|CIT).{0,40}(incorrect|inv[aá]lid|err[oó]ne)", texto, re.I):
            raise arca.ClaveInvalida("ARBA rechazó la CIT")
        if re.search(r"bloquead", texto, re.I):
            raise arca.RequiereIntervencion("ARBA informa usuario bloqueado")
        raise arca.ErrorRobot("ARBA: no se pudo confirmar el ingreso (revisar captura)")
    try:
        page.wait_for_load_state("networkidle", timeout=20_000)
    except Exception:
        pass
    solo = ""
    for _ in range(10):
        solo = re.sub(r"\D", "", page.inner_text("body"))
        if cuit in solo:
            break
        arca.pausa(1.0, 1.5)
    if cuit not in solo:
        try:
            _guardar_pantalla(page, cuit)
        except Exception:
            pass
        raise arca.CuitEquivocado("ARBA: la pantalla no muestra el CUIT del cliente")
    return page


def _abrir_menu_dj(page):
    """Inicio de ARBA (relevado 16/11/2026): Mis accesos frecuentes > Otros tramites >
    Ingresos Brutos (el que esta DENTRO de Otros tramites) > Presentacion de DJ web."""
    def vis(loc):
        return loc.locator("visible=true")
    rx_dj = re.compile(r"declaraci[oó]n jurada web", re.I)
    rx_ot = re.compile(r"^\s*Otros tr[aá]mites\s*$", re.I)
    rx_ib = re.compile(r"^\s*Ingresos Brutos\s*$", re.I)
    page.get_by_text(re.compile(r"Mis accesos frecuentes", re.I)).first.wait_for(timeout=30_000)
    if vis(page.get_by_text(rx_dj)).count():
        return
    if not vis(page.get_by_text(rx_ot)).count():
        vis(page.get_by_text(re.compile(r"Mis accesos frecuentes", re.I))).first.click()
        arca.pausa(0.8, 1.5)
    ot = vis(page.get_by_text(rx_ot)).first
    ot.wait_for(timeout=15_000)
    li = ot.locator("xpath=ancestor::li[1]")
    if not vis(li.get_by_text(rx_ib)).count():
        ot.click()
        arca.pausa(0.8, 1.5)
    if vis(page.get_by_text(rx_dj)).count():
        return
    vis(li.get_by_text(rx_ib)).first.click()
    arca.pausa(0.8, 1.5)
    vis(page.get_by_text(rx_dj)).first.wait_for(timeout=15_000)


def _guardar_pantalla(page, cuit):
    """Deja el texto y la dirección de la página para diagnosticar (sin claves: el formulario está vacío)."""
    try:
        d = os.path.join(DATOS, cuit, "capturas"); os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "arba_login_pantalla.txt"), "w", encoding="utf-8") as f:
            f.write(page.url + "\n\n" + page.inner_text("body")[:4000])
    except Exception:
        pass


def _ir_busqueda(page):
    page.goto(URL_BUSCAR, wait_until="domcontentloaded")
    arca.pausa(1.0, 2.0)
    if not page.locator("form[action*='performBuscarDDJJ']").count():
        # La aplicación de DJ web se habilita entrando desde el menú (Otros trámites > IIBB > DJ web)
        page.goto(URL_GESTIONAR, wait_until="domcontentloaded")
        arca.pausa(1.5, 3.0)
        try:
            _abrir_menu_dj(page)
        except Exception:
            try:
                _guardar_pantalla(page, locals().get("cuit") or "sin_cuit")
            except Exception:
                pass
            raise
        arca.pausa(0.8, 1.5)
        enlace = page.get_by_text(re.compile(r"declaraci[oó]n jurada web", re.I)).locator("visible=true").first
        try:
            with page.context.expect_page(timeout=30_000) as nueva:
                enlace.click()
            page = nueva.value
        except Exception:
            pass
        page.wait_for_load_state("domcontentloaded")
        page.goto(URL_BUSCAR, wait_until="domcontentloaded")
        arca.pausa(1.0, 2.0)
    if not page.locator("form[action*='performBuscarDDJJ']").count():
        raise arca.ErrorRobot("ARBA: no se pudo abrir la consulta de DJ cerradas")
    # El formulario abre en la solapa "Por comprobante"; Estado y periodos estan en "Por criterios varios"
    estado = page.locator("form[action*='performBuscarDDJJ'] [name=estado]")
    try:
        if not estado.is_visible():
            page.locator("a[href='#tabs-2']").first.click()
            estado.wait_for(state="visible", timeout=15_000)
    except Exception:
        pass
    return page


def _buscar(page, desde: str, hasta: str) -> list[dict]:
    page.evaluate("window.alert = m => (window.__alertas = (window.__alertas||[]).concat([String(m)]));"
                  "window.confirm = () => false;")      # nunca confirmar nada
    f = "form[action*='performBuscarDDJJ']"
    page.select_option(f"{f} [name=estado]", "C")
    page.select_option(f"{f} [name=anioMensualDesde]", desde[:4])
    page.select_option(f"{f} [name=mesDesde]", str(int(desde[5:])))
    page.select_option(f"{f} [name=anioMensualHasta]", hasta[:4])
    page.select_option(f"{f} [name=mesHasta]", str(int(hasta[5:])))
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
        page.locator("[name=buscar]").first.click()
    arca.pausa(1.0, 2.0)
    filas = page.evaluate("""() => { const t = document.getElementById('resultados'); if (!t) return [];
        return [...t.tBodies[0].rows].map(r => [...r.cells].map(c => c.textContent.replace(/\\s+/g,' ').trim())); }""")
    out = []
    for c in filas:
        if len(c) >= 6 and re.fullmatch(r"\d+", c[0]) and re.fullmatch(r"\d{4}", c[3]):
            out.append({"comprobante": c[0], "estado": c[1], "regimen": c[2],
                        "periodo": f"{c[3]}-{int(c[4]):02d}", "tipo": c[5], "cierre": c[7] if len(c) > 7 else ""})
    return out


def _detalle(page, comprobante: str, cuit: str, periodo: str) -> dict:
    icono = page.locator(f"#resultados span.iconoEditar[title*='{comprobante}']")
    if not icono.count():
        raise arca.ErrorRobot(f"ARBA: no se encontró el detalle de la DJ {comprobante}")
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
        icono.first.evaluate("e => e.click()")       # el ícono puede no tener tamaño visible
    arca.pausa(1.0, 2.0)
    txt = page.inner_text("body")
    m_cuit = re.search(r"CUIT:\s*(\d{2}-?\d{8}-?\d)", txt)
    if not m_cuit or re.sub(r"\D", "", m_cuit[1]) != cuit:
        raise arca.CuitEquivocado(f"ARBA: el detalle de la DJ {comprobante} no es del CUIT {cuit}")
    m_per = re.search(r"Per[ií]odo:\s*(\d{4})\s*-\s*(\d{1,2})", txt)
    if not m_per or f"{m_per[1]}-{int(m_per[2]):02d}" != periodo:
        raise arca.ErrorRobot(f"ARBA: el detalle abierto no es del período {periodo}")
    m_imp = re.search(r"Impuesto determinado de per[ií]odo\s*\$?\s*(-?[\d\.]+,\d{2})", txt)
    if not m_imp:
        raise arca.ErrorRobot(f"ARBA: no se encontró 'Impuesto determinado de período' en la DJ {comprobante}")
    grav = re.search(r"Monto imponible declarado total\s*\$?\s*([\d\.]+,\d{2})", txt)
    tipo = re.search(r"Tipo de DJ:\s*(\S+)", txt)
    return {"cuit": cuit, "periodo": periodo, "comprobante": comprobante, "tipo": tipo[1] if tipo else "",
            "impuesto_determinado": importe(m_imp[1]), "base_imponible": importe(grav[1]) if grav else None}


def _ventanas(periodos: list[str], largo: int = 6):
    """Búsquedas de hasta 6 meses (el formulario de ARBA trae ese rango por defecto)."""
    for i in range(0, len(periodos), largo):
        yield periodos[i:i + largo]


def paso(cuit: str, cit: str, periodos: list[str], estado: dict, forzar: bool = False):
    """Paso independiente (ARBA tiene su propio ingreso; no usa la sesión de ARCA)."""
    carpeta = os.path.join(DATOS, cuit, "arba")

    def fn():
        os.makedirs(carpeta, exist_ok=True)
        with arca.navegador() as ctx:
            try:
                page = login(ctx, cuit, cit)
            except Exception:
                arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "login_arba")
                raise
            try:
                page = _ir_busqueda(page)
                for ventana in _ventanas([p for p in periodos if p not in estado]):
                    lista = _buscar(page, ventana[0], ventana[-1])
                    # última presentación de cada período (rectificativas: la de cierre más reciente)
                    ultimas: dict[str, dict] = {}
                    for d in lista:
                        prev = ultimas.get(d["periodo"])
                        if not prev or (d["cierre"][6:] + d["cierre"][3:5] + d["cierre"][:2]) >= \
                                (prev["cierre"][6:] + prev["cierre"][3:5] + prev["cierre"][:2]):
                            ultimas[d["periodo"]] = d
                    for per in ventana:
                        ruta = os.path.join(carpeta, f"{per}.json")
                        if per not in ultimas:
                            estado[per] = "sin DJ local"
                            continue
                        if os.path.exists(ruta) and not forzar:
                            with open(ruta, encoding="utf-8") as fh:
                                if json.load(fh).get("comprobante") == ultimas[per]["comprobante"]:
                                    estado[per] = "ya bajado"
                                    continue
                        if page.locator("#resultados").count() == 0:
                            page = _ir_busqueda(page)
                            _buscar(page, ventana[0], ventana[-1])
                        d = _detalle(page, ultimas[per]["comprobante"], cuit, per)
                        with open(ruta, "w", encoding="utf-8") as fh:
                            json.dump(d, fh, ensure_ascii=False, indent=1)
                        estado[per] = "OK"
                        page = _ir_busqueda(page)
                        _buscar(page, ventana[0], ventana[-1])
            except Exception:
                arca.capturar(ctx, os.path.join(DATOS, cuit, "capturas"), "arba")
                raise
        return dict(estado)
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, periodos=None, **_):
    """usuario/clave: los de ARBA (CUIT y CIT)."""
    periodos = periodos or ([periodo] if periodo else arca.periodos_ultimos(12))
    estado: dict = {}
    paso(usuario, clave, periodos, estado)()
    return {"cuit": cuit, "periodos": estado, "archivos": {"arba": {"alertas": []}}}
