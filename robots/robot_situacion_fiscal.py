"""Robot Situación Fiscal: Sistema de Cuentas Tributarias + Mis Facilidades (un solo login).

Recorrido (relevado en ARCA real el 15/11/2026 con 20331162788):
  SCT  Mis servicios -> cuenta_corriente_contrib -> ctacte.cloud.afip.gob.ar/contribuyente/externo
       El contenido está dentro de un iframe (.../homeContribuyente/index.html) con 3 solapas:
       Vencimientos | Deudas (N) | DDJJ pendientes de presentación (N).
       En cada solapa: "Mostrar" -> Todos, y se lee la tabla.
       ¡OJO! En Deudas las casillas vienen TILDADAS junto a "Pagar seleccionado": el robot no toca
       casillas ni botones de esa solapa; solo lee.
  MF   Mis servicios -> misfacilidades -> seguimiento_presentacion.aspx (lista de presentaciones).
       Por cada plan VIGENTE: botón "Detalle" -> URL .../SeguimientoPlanEnviado/<id>
         .../SeguimientoDetallePlanPago/<id>  cronograma completo (1° y 2° vencimiento)
         .../SeguimientoDetallePagos/<id>     estado de cada cuota y pagos registrados
       En esas pantallas hay botones "Confirmar"/"Aceptar" (liquidación manual, etc.): el robot
       solo hace clic en "Detalle" de la lista; el resto lo abre por dirección.

Controles (si fallan, NO se guarda el dato como bueno):
  - El CUIT que muestra cada servicio tiene que ser el del cliente.
  - Las filas leídas tienen que coincidir con el contador de ARCA (Deudas N, DDJJ N).
  - El capital e intereses sumados tienen que coincidir con el resumen de ARCA.
  - El número de plan de cada pantalla tiene que ser el pedido.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

from playwright.sync_api import Frame, Page, TimeoutError as PWTimeout

from . import arca
from . import lector_situacion as ls

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
BASE_MF = "https://serviciossegsoc.afip.gob.ar/tramites_con_clave_fiscal/MisFacilidadesNet/"
URL_MF_LISTA = BASE_MF + "app/contribuyente/seguimiento_presentacion.aspx"

# Lee una tabla visible: encabezados + filas (texto de cada celda y clase de la fila).
# Usa textContent para incluir filas ocultas por la paginación de la página.
JS_TABLA = """(t) => {
  const limpiar = s => (s || '').replace(/\\(Click to sort.*?\\)/ig, '').replace(/\\s+/g, ' ').trim();
  const head = [...(t.tHead ? t.tHead.rows[t.tHead.rows.length - 1] : t.rows[0]).cells];
  const hr = t.tHead ? t.tHead.rows[t.tHead.rows.length - 1] : t.rows[0];
  const cuerpo = [...t.rows].filter(r => r !== hr && !['THEAD', 'TFOOT'].includes(r.parentElement.tagName));
  return {encabezados: head.map(c => limpiar(c.textContent)),
          filas: cuerpo.map(r => ({clase: r.className || '', celdas: [...r.cells].map(c => limpiar(c.textContent))}))};
}"""


_cuit_fmt = arca.cuit_fmt


USUARIO_ACTUAL = {"cuit": None}   # CUIT con el que se ingresó (distinto del cliente si es representación)


SinRepresentado = arca.SinRepresentado


def _controlar_cuit(texto: str, cuit: str, servicio: str) -> None:
    if _cuit_fmt(cuit) not in texto and cuit not in texto:
        otros = sorted(set(re.findall(r"\d{2}-\d{8}-\d", texto)) - {_cuit_fmt(cuit)})
        usuario = USUARIO_ACTUAL["cuit"]
        if usuario and usuario != cuit and otros == [_cuit_fmt(usuario)]:
            raise SinRepresentado(f"{servicio}: muestra al usuario {_cuit_fmt(usuario)} y no al representado "
                                  f"{_cuit_fmt(cuit)}. Falta elegir el representado (pantalla a relevar).")
        if otros:
            raise arca.CuitEquivocado(f"{servicio}: muestra el CUIT {', '.join(otros)} en lugar de {_cuit_fmt(cuit)}")
        raise arca.ErrorRobot(f"{servicio}: la pantalla no muestra el CUIT {_cuit_fmt(cuit)}; no se leyó nada")


# Consultas internas con las que Cuentas Tributarias trae los datos (vistas el 15/11/2026):
#   .../contribuyente/rest-access/service?request={"serviceName":...,"methodName":"getDeudas","arguments":[CUIT,null]}
METODOS_SCT = ("getVencimientos", "getDeudas", "getFaltasPresentacion")


class EspiaSCT:
    """Anota qué CUIT viaja en cada consulta de datos de Cuentas Tributarias."""

    def __init__(self):
        self.consultas: list[tuple[str, str]] = []   # (método, primer argumento)
        self.marcos: list = []                         # marco (iframe) que hizo cada consulta

    def __call__(self, req) -> None:
        if "rest-access/service" not in req.url:
            return
        from urllib.parse import parse_qs, urlparse
        try:
            pedido = json.loads(parse_qs(urlparse(req.url).query).get("request", ["{}"])[0])
        except ValueError:
            return
        args = pedido.get("arguments") or []
        if pedido.get("methodName") in METODOS_SCT + ("getDeudasSinVencimientos",):
            self.consultas.append((pedido["methodName"], str(args[0]) if args else ""))
            try:
                self.marcos.append(req.frame)
            except Exception:
                self.marcos.append(None)

    def solo_marco(self, marco) -> None:
        """Se queda solo con las consultas del panel que efectivamente se lee (descarta las de un
        panel anterior, p. ej. antes de cambiar el CUIT en el desplegable)."""
        pares = [(c, m) for c, m in zip(self.consultas, self.marcos) if m is marco]
        self.consultas = [c for c, _ in pares]
        self.marcos = [m for _, m in pares]

    def controlar(self, cuit: str) -> None:
        otros = sorted({a for _, a in self.consultas if a != cuit})
        usuario = USUARIO_ACTUAL["cuit"]
        if usuario and usuario != cuit and otros == [usuario]:
            raise SinRepresentado(f"Cuentas Tributarias pidió datos del usuario {usuario} y no del representado "
                                  f"{cuit}. Falta elegir el representado (pantalla a relevar).")
        if otros:
            raise arca.CuitEquivocado(f"Cuentas Tributarias pidió datos del CUIT {', '.join(otros)} en lugar de "
                                      f"{cuit} (falla de ARCA: datos de otra sesión)")
        faltan = [m for m in METODOS_SCT if m not in {x for x, _ in self.consultas}]
        if faltan:
            raise arca.ErrorRobot(f"Cuentas Tributarias: no se vieron las consultas {faltan}; "
                                  "no se puede confirmar de quién son los datos")


# ================================================================ Cuentas Tributarias
def _frame_sct(page: Page, espera_s: int = 60) -> Frame:
    limite = datetime.now().timestamp() + espera_s
    while datetime.now().timestamp() < limite:
        arca.verificar_sesion(page, "cuentas_tributarias")
        for f in page.frames:
            if "homeContribuyente" in f.url:
                try:
                    f.locator("[role=tab]:visible").first.wait_for(state="visible", timeout=5000)
                    return f
                except PWTimeout:
                    pass
        page.wait_for_timeout(1000)
    raise arca.ErrorRobot("Cuentas Tributarias no mostró las solapas (Vencimientos/Deudas/DDJJ)")


def _solapa(fr: Frame, nombre: str):
    """Busca la solapa por su texto visible. No se usa el 'nombre accesible' porque en ARCA
    incluye el ícono (carácter especial de la fuente) delante del texto: ' Vencimientos'."""
    return fr.locator("[role=tab]:visible").filter(has_text=re.compile(nombre, re.I)).first


def _contador(fr: Frame, nombre: str) -> int | None:
    t = _solapa(fr, nombre).text_content() or ""
    m = re.search(r"(\d+)\s*$", t.strip())
    return int(m[1]) if m else None


def _leer_solapa(fr: Frame, nombre: str, columna_clave: str) -> tuple[dict, str]:
    """Abre la solapa, elige 'Mostrar: Todos' y devuelve (tabla, texto de la solapa)."""
    _solapa(fr, nombre).click()
    arca.pausa(1.0, 2.0)
    panel = fr.locator(".tab-pane.active").first
    panel.wait_for(state="visible")
    try:
        panel.get_by_text(re.compile(r"Fecha de consulta", re.I)).first.wait_for(state="visible", timeout=60_000)
    except PWTimeout as e:
        raise arca.ErrorRobot(f"Cuentas Tributarias: la solapa {nombre} no terminó de cargar") from e
    sel = panel.locator("select")
    if sel.count():
        # Con 0 registros (o mientras carga) ARCA deja el selector "Mostrar" deshabilitado.
        for _ in range(10):
            if sel.first.is_enabled():
                break
            fr.page.wait_for_timeout(1000)
        if sel.first.is_enabled():
            try:
                sel.first.select_option("-1", timeout=10_000)          # "Todos"
            except Exception:
                sel.first.select_option(label="Todos", timeout=10_000)
            arca.pausa(1.0, 2.0)
    tablas = panel.locator("table")
    for i in range(tablas.count()):
        t = tablas.nth(i)
        if t.is_visible() and columna_clave.lower() in (t.inner_text() or "").lower():
            tabla, texto = t.evaluate(JS_TABLA), panel.inner_text()
            # Control: las filas leídas tienen que ser las "de N registros" que indica la solapa
            m = re.search(r"de\s+([\d\.]+)\s+registros", texto)
            n_filas = sum(1 for f in tabla["filas"] if len(f["celdas"]) == len(tabla["encabezados"]))
            if m and int(m[1].replace(".", "")) != n_filas:
                raise arca.ErrorRobot(f"Cuentas Tributarias: la solapa {nombre} indica {m[1]} registros y se "
                                      f"leyeron {n_filas} (¿no se pudo mostrar 'Todos'?)")
            return tabla, texto
    raise arca.ErrorRobot(f"Cuentas Tributarias: no se encontró la tabla de {nombre}")


def leer_cuentas_tributarias(ctx, portal: Page, cuit: str, destino: str, hoy: date, delegacion: bool) -> dict:
    espia = EspiaSCT()
    ctx.on("request", espia)
    try:
        return _leer_sct(ctx, portal, cuit, destino, hoy, delegacion, espia)
    finally:
        ctx.remove_listener("request", espia)


def _elegir_cuit_sct(page: Page, cuit: str, espia: "EspiaSCT") -> bool:
    """Desplegable del encabezado de Cuentas Tributarias (select name='$PropertySelection', opciones = CUIT).
    Al cambiarlo la página se recarga. ARCA recuerda la última elección, así que se controla SIEMPRE
    (no solo con representación): si quedó elegido otro CUIT, se cambia al del cliente."""
    sel = page.locator("select[name='$PropertySelection']")
    try:
        sel.first.wait_for(state="attached", timeout=4_000)
    except PWTimeout:
        return False                              # sin desplegable: el usuario tiene un solo CUIT
    opciones = [o.strip() for o in sel.first.locator("option").all_inner_texts()]
    if cuit not in opciones:
        raise SinRepresentado(f"Cuentas Tributarias: {cuit} no está en el desplegable de CUIT ({', '.join(opciones)}). "
                              "Revisar la relación/delegación en ARCA.")
    elegido = sel.first.evaluate("s => s.options[s.selectedIndex] ? s.options[s.selectedIndex].text.trim() : ''")
    if elegido == cuit:
        return False
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
        sel.first.select_option(label=cuit)
    arca.pausa(1.5, 3.0)
    arca.verificar_sesion(page, "cuentas_tributarias")
    elegido = page.locator("select[name='$PropertySelection']").first.evaluate(
        "s => s.options[s.selectedIndex] ? s.options[s.selectedIndex].text.trim() : ''")
    if elegido != cuit:
        raise arca.CuitEquivocado(f"Cuentas Tributarias: se eligió {cuit} y quedó {elegido}")
    return True


def _leer_sct(ctx, portal, cuit, destino, hoy, delegacion, espia) -> dict:
    page = arca.abrir_servicio(ctx, portal, "cuentas_tributarias")
    page.wait_for_load_state("domcontentloaded")
    _elegir_cuit_sct(page, cuit, espia)
    fr = _frame_sct(page)
    _controlar_cuit(page.inner_text("body") + fr.locator("body").inner_text(), cuit, "Cuentas Tributarias")

    try:
        crudo = {"contadores": {"deudas": _contador(fr, r"Deudas"), "ddjj": _contador(fr, r"DDJJ pendientes")}}
        crudo["vencimientos"], _ = _leer_solapa(fr, r"^\W*Vencimientos", "Fecha Vencimiento")
        crudo["deudas"], crudo["resumen_texto"] = _leer_solapa(fr, r"Deudas", "Int. Resarcitorio")
        crudo["ddjj"], _ = _leer_solapa(fr, r"DDJJ pendientes", "Vencimiento")
    except arca.SesionPerdida:
        raise
    except Exception:
        arca.verificar_sesion(page, "cuentas_tributarias")   # si fue la sesión, avisa eso
        raise
    # Control de identidad: TODAS las consultas de datos del panel leído tienen que ser del CUIT del cliente
    espia.solo_marco(fr)
    espia.controlar(cuit)
    crudo["consultas_cuit"] = espia.consultas
    with open(os.path.join(destino, "sct_crudo.json"), "w", encoding="utf-8") as f:
        json.dump(crudo, f, ensure_ascii=False, indent=1)
    page.close()
    return ls.leer_sct(crudo, hoy)


# ================================================================ Mis Facilidades
def _tabla_por_texto(page: Page, texto: str, id_: str | None = None) -> dict:
    if id_:
        loc = page.locator(f"#{id_}")
        if loc.count():
            return loc.first.evaluate(JS_TABLA)
    tablas = page.locator("table")
    for i in range(tablas.count()):
        t = tablas.nth(i)
        if texto.lower() in (t.text_content() or "").lower():
            r = t.evaluate(JS_TABLA)
            if not _con_datos(r):
                r = _tabla_sin_filas(page, texto, r)
            return r
    raise arca.ErrorRobot(f"Mis Facilidades: no se encontró la tabla '{texto}'")


def _con_datos(r: dict) -> bool:
    return any(any(c for c in f.get("celdas") or []) and len(f.get("celdas") or []) > 1 for f in r.get("filas") or [])


JS_TABLAS_TEXTO = """(texto) => {
  const T = [...document.querySelectorAll('table')];
  const i = T.findIndex(t => (t.textContent || '').toLowerCase().includes(texto));
  if (i < 0) return null;
  // la más interna que tiene el texto (la de afuera puede ser de diagramación)
  let j = i;
  for (let k = i + 1; k < T.length; k++) if (T[i].contains(T[k]) && (T[k].textContent || '').toLowerCase().includes(texto)) j = k;
  T.forEach(t => t.removeAttribute('data-robot-t'));
  T[j].setAttribute('data-robot-t', 'cab');
  // la siguiente tabla (no anidada en la del encabezado) con renglones de datos: grilla con encabezado fijo aparte
  for (let k = j + 1; k < T.length; k++) {
    if (T[j].contains(T[k])) continue;
    if ([...T[k].rows].some(r => r.cells.length > 1)) { T[k].setAttribute('data-robot-t', 'cuerpo'); break; }
  }
  return true; }"""


def _tabla_sin_filas(page: Page, texto: str, r: dict) -> dict:
    """26/11/2026 (Nabajuma, "Obligaciones al cierre" vacía): la tabla con el título no trajo renglones. Puede ser que
    la grilla todavía estaba cargando, que la tabla encontrada sea la de diagramación, o que el encabezado esté en una
    tabla y los renglones en la siguiente (encabezado fijo). Se prueba en ese orden."""
    page.wait_for_timeout(3000)
    try:
        if not page.evaluate(JS_TABLAS_TEXTO, texto.lower()):
            return r
        cab = page.locator("[data-robot-t='cab']").first.evaluate(JS_TABLA)
        if _con_datos(cab):
            return cab
        cuerpo = page.locator("[data-robot-t='cuerpo']")
        if cuerpo.count():
            c = cuerpo.first.evaluate(JS_TABLA)
            filas = ([{"clase": "", "celdas": c["encabezados"]}] if c["encabezados"] and len(c["encabezados"]) == len(cab["encabezados"])
                     and not any(texto.lower() in x.lower() for x in c["encabezados"]) else []) + c["filas"]
            filas = [f for f in filas if len(f["celdas"]) == len(cab["encabezados"])] or filas
            if any(len(f["celdas"]) > 1 for f in filas):
                return {"encabezados": cab["encabezados"], "filas": filas}
        return cab if cab.get("encabezados") else r
    except Exception:
        return r


def _ir(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded")
    arca.pausa(1.0, 2.5)
    arca.verificar_sesion(page, "mis_facilidades")
    if arca._hay_texto(page, r"sesi[oó]n (ha )?(expirad|finalizad|caducad)"):
        raise arca.SesionPerdida("Mis Facilidades: la sesión venció")


def _elegir_cuit_mf(page: Page, cuit: str) -> None:
    """Si el usuario tiene CUIT asociados, Mis Facilidades abre primero IndexContribuyente.aspx:
    'Seleccione una de las Cuits asociadas' (select #ContentPlaceHolder1_ddlCUIT) + botón Aceptar."""
    sel = page.locator("#ContentPlaceHolder1_ddlCUIT")
    if not sel.count():
        return
    opciones = [o.strip() for o in sel.first.locator("option").all_inner_texts()]
    if _cuit_fmt(cuit) not in opciones:
        raise SinRepresentado(f"Mis Facilidades: {_cuit_fmt(cuit)} no está entre las CUIT asociadas "
                              f"({', '.join(opciones)}). Revisar la relación/delegación en ARCA.")
    sel.first.select_option(label=_cuit_fmt(cuit))
    arca.pausa(0.5, 1.2)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
        page.locator("#ContentPlaceHolder1_btnAceptar").first.click()   # solo elige el contribuyente
    arca.pausa()
    arca.verificar_sesion(page, "mis_facilidades")


def _abrir_detalle(page: Page, numero: str) -> str:
    """Hace clic en 'Detalle' de la fila del plan y devuelve el id interno de ARCA."""
    _ir(page, URL_MF_LISTA)
    if USUARIO_ACTUAL.get("cliente"):
        _controlar_cuit(page.inner_text("body"), USUARIO_ACTUAL["cliente"], "Mis Facilidades")
    fila = page.locator("table tr", has=page.locator("td", has_text=re.compile(rf"^\s*{re.escape(numero)}\s*$")))
    if not fila.count():
        raise arca.ErrorRobot(f"Mis Facilidades: no se encontró el plan {numero} en la lista")
    boton = fila.first.locator("input[type=submit][value='Detalle'], input[id*='detallePlan']")
    with page.expect_navigation(wait_until="domcontentloaded"):
        boton.first.evaluate("b => b.click()")     # la fila puede estar oculta por la paginación
    arca.verificar_sesion(page, "mis_facilidades")
    m = re.search(r"SeguimientoPlanEnviado/(\d+)", page.url)
    if not m:
        raise arca.ErrorRobot(f"Mis Facilidades: el detalle del plan {numero} no abrió (url inesperada)")
    if numero not in page.inner_text("body"):
        raise arca.ErrorRobot(f"Mis Facilidades: el detalle abierto no es del plan {numero}")
    return m[1]


def leer_mis_facilidades(ctx, portal: Page, cuit: str, destino: str, hoy: date, delegacion: bool,
                         avance: dict | None = None) -> dict:
    """avance: planes ya leídos en un intento anterior (si la sesión venció a mitad de camino,
    al volver a entrar se sigue desde el plan siguiente)."""
    avance = avance if avance is not None else {}
    avance.setdefault("crudo", {})
    avance.setdefault("resumenes", {})
    page = arca.abrir_servicio(ctx, portal, "mis_facilidades")
    page.wait_for_load_state("domcontentloaded")
    _elegir_cuit_mf(page, cuit)
    _controlar_cuit(page.inner_text("body"), cuit, "Mis Facilidades")

    crudo = {"lista": _tabla_por_texto(page, "Consolidado"), "planes": avance["crudo"]}
    planes = ls.leer_lista_planes(crudo["lista"])
    for p in [p for p in planes if ls.es_vigente(p)]:
        if p["numero"] in avance["resumenes"]:
            continue
        id_ = _abrir_detalle(page, p["numero"])
        _ir(page, BASE_MF + f"SeguimientoDetallePlanPago/{id_}")
        _controlar_cuit(page.inner_text("body"), cuit, "Mis Facilidades")
        if p["numero"] not in page.inner_text("body") and "Detalle del Plan de Pago" not in page.inner_text("body"):
            raise arca.ErrorRobot(f"Mis Facilidades: el cronograma no corresponde al plan {p['numero']}")
        cron = _tabla_por_texto(page, "Fecha Vencimiento", "tableDetallePlanPago")
        _ir(page, BASE_MF + f"SeguimientoDetallePagos/{id_}")
        texto = page.inner_text("body")
        _controlar_cuit(texto, cuit, "Mis Facilidades")
        m = re.search(r"Nro de plan:\s*(\S+)", texto)
        if not m or m[1] != p["numero"]:
            raise arca.ErrorRobot(f"Mis Facilidades: 'Ver Pagos' muestra el plan {m[1] if m else '?'} "
                                  f"en lugar de {p['numero']}")
        pagos = _tabla_por_texto(page, "Estado de Cuota", "tableDetallePagos")
        crudo["planes"][p["numero"]] = {"id": id_, "cronograma": cron, "pagos": pagos}
        avance["resumenes"][p["numero"]] = ls.resumir_plan(p, ls.leer_plan_de_pago(cron), ls.leer_pagos(pagos), hoy)
        arca.pausa(1.5, 3.5)

    with open(os.path.join(destino, "mf_crudo.json"), "w", encoding="utf-8") as f:
        json.dump(crudo, f, ensure_ascii=False, indent=1)
    page.close()
    resumenes = [avance["resumenes"][p["numero"]] for p in planes if p["numero"] in avance["resumenes"]]
    return {"planes": planes, "vigentes": resumenes, "alertas": ls.alertas_planes(planes, resumenes, hoy)}


# ================================================================ informe Excel
def guardar_excel(res: dict, ruta: str) -> None:
    import pandas as pd
    filas_res = []
    sct, mf = res.get("sct"), res.get("mis_facilidades")
    if sct:
        t, a = sct["totales_leidos"], sct["resumen_arca"]
        filas_res += [("Deuda total (capital + intereses)", t["total"]), ("Deuda vencida", t["vencido"]),
                      ("Saldo total según ARCA", a.get("saldo_total")),
                      ("DDJJ pendientes de presentación", len(sct["ddjj_pendientes"]))]
    if mf:
        v = mf["vigentes"]
        filas_res += [("Planes vigentes", len(v)),
                      ("Cuotas vencidas impagas", sum(p["vencidas_impagas"] for p in v)),
                      ("Importe cuotas vencidas impagas", sum(p["importe_vencido_impago"] for p in v)),
                      ("Cuotas a vencer en 15 días", sum(p["a_vencer_15_dias"] for p in v)),
                      ("Importe a vencer en 15 días", sum(p["importe_a_vencer_15_dias"] for p in v))]
    hojas = {"Resumen": pd.DataFrame(filas_res, columns=["Concepto", "Valor"]),
             "Alertas": pd.DataFrame(res.get("alertas", []), columns=["prioridad", "tipo", "texto"])}
    if sct:
        hojas["Deudas"] = pd.DataFrame(sct["deudas"])
        hojas["Vencimientos"] = pd.DataFrame(sct["vencimientos"])
        hojas["DDJJ pendientes"] = pd.DataFrame(sct["ddjj_pendientes"],
                                                columns=["impuesto", "concepto", "subconcepto", "periodo", "periodo_txt",
                                                         "establecimiento", "vencimiento"])
    if mf:
        cols = ["numero", "tipo", "presentacion", "con_anticipo", "cuotas_total", "valor_cuota", "cuotas_pagadas",
                "cuotas_pendientes", "vencidas_impagas", "importe_vencido_impago", "a_vencer_15_dias",
                "importe_a_vencer_15_dias", "proximo_vencimiento", "saldo_capital_pendiente"]
        hojas["Planes vigentes"] = pd.DataFrame([{k: p[k] for k in cols} for p in mf["vigentes"]], columns=cols)
        hojas["Cuotas"] = pd.DataFrame([{"plan": p["numero"], **{k: c[k] for k in
                                         ("cuota", "capital", "total_1", "venc_1", "total_2", "venc_2", "estado",
                                          "situacion")}} for p in mf["vigentes"] for c in p["detalle_cuotas"]])
        hojas["Todos los planes"] = pd.DataFrame(mf["planes"])
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        for nombre, df in hojas.items():
            df.to_excel(xw, sheet_name=nombre, index=False)
            ws = xw.sheets[nombre]
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(60, max(10, *(len(str(c.value or "")) for c in col)) + 2)


# ================================================================ entrada
MAX_REINGRESOS = 3   # veces que se vuelve a entrar si la sesión vence en una misma corrida


def correr(cuit: str, periodo: str | None, usuario: str, clave: str, metodo: str = "Directo",
           visible: bool = False, partes=("sct", "mf")) -> dict:
    hoy = date.today()
    destino = os.path.join(DATOS, cuit, "situacion", hoy.isoformat())
    os.makedirs(destino, exist_ok=True)
    res = {"cuit": cuit, "fecha": hoy.isoformat(), "alertas": [], "archivos": {}, "reingresos": 0}
    delegacion = metodo == "Delegación" or usuario != cuit
    USUARIO_ACTUAL["cuit"] = usuario
    USUARIO_ACTUAL["cliente"] = cuit
    pendientes = list(partes)
    avance_mf: dict = {}

    while pendientes:
        with arca.navegador(visible=visible) as ctx:
            try:
                portal = arca.login(ctx, usuario, clave)
            except Exception:
                arca.capturar(ctx, destino, "login")
                raise
            try:
                while pendientes:
                    parte = pendientes[0]
                    try:
                        if parte == "sct":
                            res["sct"] = leer_cuentas_tributarias(ctx, portal, cuit, destino, hoy, delegacion)
                        else:
                            res["mis_facilidades"] = leer_mis_facilidades(ctx, portal, cuit, destino, hoy,
                                                                          delegacion, avance_mf)
                    except arca.SesionPerdida:
                        arca.capturar(ctx, destino, f"sesion_{parte}")
                        res["reingresos"] += 1
                        if res["reingresos"] > MAX_REINGRESOS:
                            raise
                        break                     # salir, abrir navegador nuevo y volver a entrar
                    except arca.ClaveInvalida:
                        raise
                    except Exception as e:
                        # Una parte que falla no impide leer la otra (los planes están en Mis Facilidades,
                        # que es un servicio aparte de Cuentas Tributarias).
                        arca.capturar(ctx, destino, "cuentas_tributarias" if parte == "sct" else "mis_facilidades")
                        res.setdefault("errores", {})[parte] = f"{type(e).__name__}: {str(e).splitlines()[0][:200]}"
                    pendientes.pop(0)
                    if pendientes:
                        arca.pausa(2, 5)
            finally:
                arca.cerrar_sesion(portal)
        if pendientes:
            arca.pausa(10, 20)                    # antes de volver a entrar

    errores = res.get("errores", {})
    if errores and not any(p in res for p in ("sct", "mis_facilidades")):
        raise arca.ErrorRobot("; ".join(f"{k}: {v}" for k, v in errores.items()))
    for parte in ("sct", "mis_facilidades"):
        if parte in res:
            res["alertas"] += res[parte]["alertas"]
    nombres = {"sct": "Cuentas Tributarias", "mf": "Mis Facilidades (planes)", "mis_facilidades": "Mis Facilidades (planes)"}
    for parte, err in errores.items():
        res["alertas"].append({"prioridad": "Media", "tipo": "Robot",
                               "texto": f"No se pudo leer {nombres.get(parte, parte)}: {err}"})
    with open(os.path.join(destino, "resultado.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1, default=str)
    guardar_excel(res, os.path.join(destino, "situacion_fiscal.xlsx"))
    res["archivos"]["situacion"] = {"alertas": res["alertas"]}
    return res
