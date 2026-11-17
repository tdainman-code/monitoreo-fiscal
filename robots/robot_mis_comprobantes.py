"""Robot Mis Comprobantes: descarga CSV de emitidos y recibidos por período y los procesa.

Recorrido (el mismo que hicimos a mano el 14/11/2026):
  1. Login ARCA con la clave del cliente (o del estudio si el cliente tiene token).
  2. Mis servicios -> Mis Comprobantes (pestaña nueva) -> elegir representado si hace falta.
  3. comprobantesEmitidos.do / comprobantesRecibidos.do -> Fecha "01/MM/AAAA - DD/MM/AAAA" -> Buscar.
  4. "Exportar como CSV" -> guardar en DATOS/<cuit>/<AAAA-MM>/{emitidos,recibidos}.csv
  5. Pasar el CSV por el lector (valida formato, sumas y alertas) y guardar el resumen.
"""
from __future__ import annotations

import calendar
import json
import os
import re
from datetime import date

from playwright.sync_api import Page, TimeoutError as PWTimeout

from . import arca
from .lector_mis_comprobantes import alertas, leer, resumir

BASE_MC = "https://fes.afip.gob.ar/mcmp/jsp/"
DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")


def _rango(periodo: str) -> str:
    a, m = map(int, periodo.split("-"))
    ultimo = calendar.monthrange(a, m)[1]
    return f"01/{m:02d}/{a} - {ultimo:02d}/{m:02d}/{a}"


def _guardar_csv(bajado: str, destino: str) -> None:
    """ARCA a veces entrega el CSV comprimido en un ZIP (empieza con 'PK').
    Si es ZIP, extrae el .csv de adentro; si no, lo deja como está."""
    import shutil
    import zipfile
    with open(bajado, "rb") as f:
        es_zip = f.read(2) == b"PK"
    if es_zip:
        with zipfile.ZipFile(bajado) as z:
            csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not csvs:
                raise arca.ErrorRobot(f"El ZIP de ARCA no trae ningún CSV: {z.namelist()}")
            with z.open(csvs[0]) as origen, open(destino, "wb") as salida:
                shutil.copyfileobj(origen, salida)
        os.remove(bajado)
    else:
        os.replace(bajado, destino)


def _poner_fechas(page: Page, campo, desde: str, hasta: str) -> None:
    """El campo es un calendario (daterangepicker): no toma texto pegado.
    1) Usa la API del calendario de la página (lo más confiable).
    2) Si no está disponible, tipea tecla por tecla y confirma con Enter."""
    modo = campo.evaluate("""(el, f) => {
        const $ = window.jQuery || window.$;
        const dp = $ && $(el).data && $(el).data('daterangepicker');
        if (!dp) return 'sin-api';
        dp.setStartDate(f[0]); dp.setEndDate(f[1]);
        $(el).val(f[0] + ' - ' + f[1]);
        $(el).trigger('apply.daterangepicker', dp); $(el).trigger('change');
        return 'api';
    }""", [desde, hasta])
    if modo != "api":
        campo.click()
        campo.press("Control+a")
        campo.press("Backspace")
        campo.press_sequentially(f"{desde} - {hasta}", delay=80)
        campo.press("Enter")
    # cerrar el calendario si quedó abierto
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass


def _descargar(page: Page, tipo: str, periodo: str, destino: str) -> dict:
    """tipo: 'emitidos' | 'recibidos'. Devuelve info de la descarga."""
    pagina = "comprobantesEmitidos.do" if tipo == "emitidos" else "comprobantesRecibidos.do"
    page.goto(BASE_MC + pagina, wait_until="domcontentloaded")
    arca.pausa()

    desde, hasta = _rango(periodo).split(" - ")
    fecha = page.get_by_label(re.compile(r"Fecha del Comprobante", re.I)).first
    _poner_fechas(page, fecha, desde, hasta)
    arca.pausa(0.8, 1.5)
    page.get_by_role("button", name=re.compile(r"^Buscar$", re.I)).first.click()

    # Esperar resultados (la consulta puede tardar con miles de comprobantes)
    try:
        page.get_by_text(re.compile(r"Mostrando registros|No se encontraron|Ning[uú]n dato", re.I)).first \
            .wait_for(state="visible", timeout=120_000)
    except PWTimeout as e:
        raise arca.ErrorRobot(f"Mis Comprobantes no devolvió resultados ({tipo})") from e

    # CONTROL: el filtro que aplicó ARCA tiene que ser exactamente el período pedido.
    # Si no, NO se descarga (evita guardar datos de otro período como si fueran de este).
    filtro = page.inner_text("body")
    m_f = re.search(r"Fecha del Comprobante:?\s*([\d/]+)(?:\s*a\s*([\d/]+))?", filtro)
    aplicado = (m_f.group(1), m_f.group(2) or m_f.group(1)) if m_f else None
    if aplicado != (desde, hasta):
        raise arca.ErrorRobot(f"ARCA aplicó otro rango de fechas {aplicado} en lugar de {desde} a {hasta} ({tipo}); "
                              "no se descargó nada")

    if arca._hay_texto(page, r"No se encontraron|Ning[uú]n dato"):
        return {"tipo": tipo, "registros": 0, "archivo": None}

    m = re.search(r"total de ([\d\.]+)", page.inner_text("body"))
    total_pantalla = int(m.group(1).replace(".", "")) if m else None

    boton_csv = page.get_by_role("button", name=re.compile(r"Exportar como CSV", re.I))
    if not boton_csv.count():
        boton_csv = page.locator("[title='Exportar como CSV' i], button:has-text('CSV')")
    with page.expect_download(timeout=180_000) as dl:
        boton_csv.first.click()
    archivo = os.path.join(destino, f"{tipo}.csv")
    bajado = os.path.join(destino, f"{tipo}.descarga")
    dl.value.save_as(bajado)
    _guardar_csv(bajado, archivo)
    return {"tipo": tipo, "registros_pantalla": total_pantalla, "archivo": archivo}


def procesar(archivo: str) -> dict:
    df = leer(archivo)
    r = resumir(df)
    al = alertas(df)
    return {"registros": int(len(df)), "resumen": {k: float(v) for k, v in r.items()},
            "alertas": al.to_dict("records")}


def correr(cuit: str, periodo: str, usuario: str, clave: str, metodo: str = "Directo",
           visible: bool = False) -> dict:
    destino = os.path.join(DATOS, cuit, periodo)
    os.makedirs(destino, exist_ok=True)
    resultado = {"cuit": cuit, "periodo": periodo, "fecha": date.today().isoformat(), "archivos": {}}

    with arca.navegador(visible=visible) as ctx:
        try:
            portal = arca.login(ctx, usuario, clave)
        except Exception:
            arca.capturar(ctx, destino, "login")
            raise
        try:
            mc = arca.abrir_servicio(ctx, portal, "mis_comprobantes")
            if metodo == "Delegación" or usuario != cuit:
                arca.elegir_representado(mc, cuit)
            for tipo in ("emitidos", "recibidos"):
                info = _descargar(mc, tipo, periodo, destino)
                if info.get("archivo"):
                    p = procesar(info["archivo"])
                    if info.get("registros_pantalla") not in (None, p["registros"]):
                        p["alertas"].append({"Tipo de alerta": "Control de descarga",
                                             "Acción": f"Pantalla {info['registros_pantalla']} vs CSV {p['registros']} registros"})
                    info.update(p)
                resultado["archivos"][tipo] = info
                arca.pausa(2, 5)
        except Exception:
            arca.capturar(ctx, destino, "mis_comprobantes")
            raise
        finally:
            arca.cerrar_sesion(portal)

    with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=1, default=str)
    return resultado


# ---------------------------------------------------------------- varios períodos en una sesión
def elegir_contribuyente(page: Page, cuit: str) -> None:
    """Pantalla 'Elegí una persona para ingresar' (usuario con representados): tarjetas a.panel con
    nombre y CUIT. Se hace clic en la del cliente. Luego se controla el encabezado:
    'REPRESENTANDO A: ... [30-51969833-8]' o, si es el propio usuario, '[20-...]'."""
    fmt = arca.cuit_fmt(cuit)
    tarjetas = page.locator("a.panel")
    if tarjetas.count() and arca._hay_texto(page, r"Eleg[ií] una persona|Representar a"):
        t = tarjetas.filter(has_text=fmt)
        if not t.count():
            raise arca.SinRepresentado(f"Mis Comprobantes: {fmt} no figura entre las personas a representar")
        with page.expect_navigation(wait_until="domcontentloaded"):
            t.first.click()
        arca.pausa()
    controlar_contribuyente(page, cuit)


def controlar_contribuyente(page: Page, cuit: str) -> None:
    fmt = arca.cuit_fmt(cuit)
    texto = page.inner_text("body")[:600]
    m = re.search(r"REPRESENTANDO A:?(.*?)\[(\d{2}-\d{8}-\d)\]", texto, re.I | re.S)
    activo = m[2] if m else (re.search(r"\[(\d{2}-\d{8}-\d)\]", texto) or [None, None])[1]
    if activo != fmt:
        raise arca.CuitEquivocado(f"Mis Comprobantes trabaja con {activo} en lugar de {fmt}")


def paso_periodos(cuit: str, periodos: list[str], estado: dict, forzar: bool = False):
    """Paso para arca.ejecutar: baja emitidos y recibidos de cada período. 'estado' guarda lo hecho
    (si la sesión vence, al volver a entrar sigue con el período siguiente)."""
    def fn(ctx, portal):
        mc = arca.abrir_servicio(ctx, portal, "mis_comprobantes")
        elegir_contribuyente(mc, cuit)
        for periodo in periodos:
            if periodo in estado:
                continue
            destino = os.path.join(DATOS, cuit, periodo)
            previo = os.path.join(destino, "resultado.json")
            if os.path.exists(previo) and not forzar:
                estado[periodo] = "ya bajado"
                continue
            os.makedirs(destino, exist_ok=True)
            resultado = {"cuit": cuit, "periodo": periodo, "fecha": date.today().isoformat(), "archivos": {}}
            for tipo in ("emitidos", "recibidos"):
                info = _descargar(mc, tipo, periodo, destino)
                if info.get("archivo"):
                    p = procesar(info["archivo"])
                    if info.get("registros_pantalla") not in (None, p["registros"]):
                        p["alertas"].append({"Tipo de alerta": "Control de descarga",
                                             "Acción": f"Pantalla {info['registros_pantalla']} vs CSV {p['registros']} registros"})
                    info.update(p)
                resultado["archivos"][tipo] = info
                arca.pausa(2, 4)
            with open(previo, "w", encoding="utf-8") as f:
                json.dump(resultado, f, ensure_ascii=False, indent=1, default=str)
            estado[periodo] = "OK"
        mc.close()
        return dict(estado)
    return fn


def correr_periodos(cuit: str, periodos: list[str], usuario: str, clave: str, metodo: str = "Directo",
                    visible: bool = False, forzar: bool = False) -> dict:
    estado: dict = {}
    carpeta = os.path.join(DATOS, cuit, "capturas")
    r = arca.ejecutar(usuario, clave, [("mis_comprobantes", paso_periodos(cuit, periodos, estado, forzar))],
                      carpeta, visible)
    return {"cuit": cuit, "periodos": estado, "reingresos": r["_reingresos"],
            "archivos": {"mis_comprobantes": {"alertas": []}}}
