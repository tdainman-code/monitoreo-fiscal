"""Robot SIFERE Web Consultas (Convenio Multilateral): impuesto determinado por jurisdicción.

Recorrido (relevado el 15/11/2026, usuario 20-14283675-1 representando a 30-51969833-8):
  Mis servicios -> comarb_sifereweb_consultas -> app1.comarb.gob.ar/siferewebconsultas/mainMenu.do
     encabezado: "CONTRIBUYENTE (20-14283675-1) representando a OFFSET TRAMAR ... (30-51969833-8)"
  Menú SIFERE -> DDJJ -> Mensuales (sfrDdjj.do): selects mesDesdeStr/anioDesdeStr/mesHastaStr/anioHastaStr
     + Buscar -> tabla "Anticipo | Formulario | Monto Total | Forma Pago | Banco / Sucursal | Fecha"
     Anticipo = "09/2026 - 0" (el número final es la rectificativa)
  Enlace de la fila (listPorJuris) -> tabla "Jurisdicción | Imp determinado | Valores que Restan | ..."
Se toma la última rectificativa de cada anticipo. Solo consulta.

DEUDA DE CONVENIO (relevado el 16/11/2026 con GONCALVES VICENTE JUAN JOSE):
  Menú SIFERE -> "Resumen de DDJJs y Pagos" (sfrCtaCte.do?method=ctaCteIn): select juris (901..924),
  mesDesdeStr/anioDesdeStr, mesStr/anioStr (hasta) + Buscar -> tabla #rCtaCte
  "Anticipo (202609) | Saldo Favor Fisco | Saldo Favor Contribuyente | Imp Pagado DDJJ | Imp Pagado Otro".
  Se consultan los últimos 5 años de cada jurisdicción en la que el cliente tiene DDJJ (las mismas de la
  relación débito/crédito). Los VEP pagados desde "Presentación de DDJJ y Pagos" de ARCA figuran acá
  (confirmado por el estudio); el aviso "no incluye Pagos COMARB" no afecta a los clientes del estudio.
  COMARB avisa que la información puede tener hasta 7 días de retraso.
Si el contribuyente no está en Convenio Multilateral (no tiene el servicio) queda "sin servicio".

APODERADOS (relevado con Gaby el 17/11/2026, 20-38893131-1 con varias empresas):
  mainMenu.do muestra "DAINMAN TOMAS (20-38893131-1) representando a DAINMAN TOMAS (20-38893131-1)" y abajo
  "Contribuyentes disponibles": desplegable "BH ... (CUIT 30-71746863-1)" / "CONTRIBUYENTE (CUIT 30-71746863-1)"
  + botón "Seleccionar". Al elegir, el encabezado pasa a "representando a <EMPRESA> (30-...)".
  En cualquier pantalla está el enlace "Cambiar Contribuyente" (vuelve a esa lista).
"""
from __future__ import annotations

import json
import os
import re

from . import arca
from .lector_situacion import importe

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")

JURISDICCIONES = {
    "901": "CABA", "902": "Buenos Aires", "903": "Catamarca", "904": "Córdoba", "905": "Corrientes",
    "906": "Chaco", "907": "Chubut", "908": "Entre Ríos", "909": "Formosa", "910": "Jujuy",
    "911": "La Pampa", "912": "La Rioja", "913": "Mendoza", "914": "Misiones", "915": "Neuquén",
    "916": "Río Negro", "917": "Salta", "918": "San Juan", "919": "San Luis", "920": "Santa Cruz",
    "921": "Santa Fe", "922": "Santiago del Estero", "923": "Tierra del Fuego", "924": "Tucumán",
}

JS_FILAS = """() => [...document.querySelectorAll('table')].filter(t => t.offsetParent).map(t =>
    [...t.rows].map(r => [...r.cells].map(c => c.textContent.replace(/\\s+/g, ' ').trim())))"""


def _contribuyente(texto: str) -> str | None:
    m = re.search(r"representando a.*?\(?(\d{2}-?\d{8}-?\d)\)?", texto, re.I | re.S) or \
        re.search(r"CONTRIBUYENTE:?\s*\(?(\d{2}-?\d{8}-?\d)\)?", texto, re.I)
    if not m:
        return None
    d = re.sub(r"\D", "", m[1])
    return arca.cuit_fmt(d)


def _controlar_cuit(page, cuit, espera_s: int = 60):
    """COMARB pasa por pantallas intermedias al validar la sesión que viene de ARCA: se espera
    hasta 60 s a que aparezca el encabezado con el contribuyente."""
    import time
    limite = time.time() + espera_s
    texto = ""
    while time.time() < limite:
        try:
            texto = page.inner_text("body")
        except Exception:
            texto = ""
        if _contribuyente(texto):
            break
        page.wait_for_timeout(2000)
    activo = _contribuyente(texto)
    if not activo:
        with open(os.path.join(DATOS, "sifere_sin_encabezado.txt"), "w", encoding="utf-8") as f:
            f.write(page.url.split("?")[0] + "\n\n" + texto[:3000])
        raise arca.ErrorRobot("SIFERE: no se ve el contribuyente en el encabezado (texto guardado en "
                              "sifere_sin_encabezado.txt)")
    m = [None, activo]
    if m[1] != arca.cuit_fmt(cuit):
        raise arca.SinRepresentado(f"SIFERE trabaja con {m[1]} y no con {arca.cuit_fmt(cuit)} (pantalla a relevar)")


def elegir_contribuyente(page, cuit: str, http_comarb: list[str]) -> None:
    """Deja SIFERE Web en el CUIT del cliente: si el encabezado muestra otro, lo elige en
    'Contribuyentes disponibles' (y si esa lista no está en pantalla, entra por 'Cambiar Contribuyente')."""
    fmt = arca.cuit_fmt(cuit)
    try:
        _controlar_cuit(page, cuit)
        return
    except arca.SinRepresentado:
        pass

    def lista():
        return page.locator("select").filter(has=page.locator("option", has_text=re.compile(re.escape(fmt))))

    if not lista().count():
        link = page.locator("a", has_text=re.compile(r"Cambiar Contribuyente", re.I))
        if link.count():
            _navegar(page, lambda: link.first.click(), http_comarb)
        else:
            page.goto(re.sub(r"(siferewebconsultas/).*$", r"\1mainMenu.do", page.url), wait_until="domcontentloaded")
            _pasar_a_https(page, http_comarb)
    if not lista().count():
        opciones = [o.strip() for o in page.locator("select option").all_inner_texts()][:30]
        raise arca.SinRepresentado(f"SIFERE: {fmt} no está entre los contribuyentes disponibles "
                                   f"({'; '.join(opciones) or 'sin lista'})")
    sel = lista().first
    valor = sel.evaluate("(s, c) => [...s.options].find(o => o.text.includes(c)).value", fmt)
    sel.select_option(value=valor)
    arca.pausa(0.5, 1.0)
    boton = page.locator("input[value='Seleccionar'], button:has-text('Seleccionar')")
    _navegar(page, lambda: boton.first.click(), http_comarb)
    _controlar_cuit(page, cuit)


def _pasar_a_https(page, http_comarb: list[str], espera_s: int = 20) -> None:
    """COMARB redirige a "http://app1.comarb.gob.ar/...;jsessionid=..." y desde la red del estudio el
    puerto http no responde (relevado el 15/11/2026). Si la pestaña queda en error o colgada en esa
    dirección, se entra a la misma dirección por https (la sesión viaja en la dirección misma)."""
    import time
    limite = time.time() + espera_s
    while time.time() < limite:
        if _contribuyente(_texto(page)):
            http_comarb.clear()                     # lo anotado ya no sirve para la próxima pantalla
            return
        if page.url.startswith("chrome-error") or page.url.startswith("http://"):
            break
        page.wait_for_timeout(1000)
    destino = next((u for u in reversed(http_comarb) if "comarb" in u), None)
    if page.url.startswith("http://") and "comarb" in page.url:
        destino = page.url
    http_comarb.clear()
    if not destino:
        return
    https = re.sub(r"^http://([^/:]+)(?::80)?", r"https://\1", destino)
    page.goto(https, wait_until="domcontentloaded", timeout=60_000)
    arca.pausa(1.0, 2.0)


def _navegar(page, accion, http_comarb: list[str]) -> None:
    """Ejecuta una acción que cambia de pantalla. Si la navegación falla porque COMARB mandó a
    http:// (no responde), se corrige pasando a https."""
    try:
        with page.expect_navigation(wait_until="commit", timeout=60_000):
            accion()
    except Exception:
        if not http_comarb and not page.url.startswith(("chrome-error", "http://")):
            raise
    arca.pausa(1.0, 2.0)
    _pasar_a_https(page, http_comarb)


def _texto(page) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return ""


def _buscar(page, desde: str, hasta: str, http_comarb: list[str]):
    menu = page.locator("a", has_text=re.compile(r"^\s*Mensuales\s*$"))
    _navegar(page, lambda: menu.first.evaluate("a => a.click()"), http_comarb)   # el menú está oculto
    ad, md = desde.split("-")
    ah, mh = hasta.split("-")
    page.select_option("#mesDesdeStr", md)
    page.select_option("#anioDesdeStr", ad)
    page.select_option("#mesHastaStr", mh)
    page.select_option("#anioHastaStr", ah)
    _navegar(page, lambda: page.locator("input[value='Buscar'], button:has-text('Buscar')").first.click(),
             http_comarb)


def _lista(page) -> dict[str, tuple[int, int]]:
    """{'2026-09': (rectificativa, índice de fila en la tabla)}"""
    out = {}
    for tabla in page.evaluate(JS_FILAS):
        if not tabla or not any("Anticipo" in c for c in tabla[0]):
            continue
        for i, c in enumerate(tabla[1:], 1):
            m = next((re.search(r"(\d{2})/(\d{4})\s*-\s*(\d+)", x) for x in c if re.search(r"\d{2}/\d{4}\s*-\s*\d+", x)), None)
            if m:
                per, rect = f"{m[2]}-{m[1]}", int(m[3])
                if per not in out or rect > out[per][0]:
                    out[per] = (rect, i)
    return out


def _detalle(page) -> dict:
    for tabla in page.evaluate(JS_FILAS):
        if tabla and any("Imp determinado" in c for c in tabla[0]):
            enc = tabla[0]
            j_jur = next(i for i, c in enumerate(enc) if "Jurisdic" in c)
            j_det = next(i for i, c in enumerate(enc) if "Imp determinado" in c)
            j_pag = next((i for i, c in enumerate(enc) if "A Pagar" in c), None)
            jur, total = {}, None
            for c in tabla[1:]:
                if len(c) <= j_det:
                    continue
                if re.fullmatch(r"\d{3}", c[j_jur]):
                    jur[c[j_jur]] = {"determinado": importe(c[j_det]) or 0.0,
                                     "a_pagar": importe(c[j_pag]) if j_pag is not None else None}
                elif "Total" in " ".join(c[:2]):
                    vals = [importe(x) for x in c if importe(x) is not None]
                    total = vals[0] if vals else None
            return {"jurisdicciones": jur, "total_determinado": total}
    raise arca.ErrorRobot("SIFERE: no apareció la tabla 'Valores por Jurisdicción'")


# ---------------------------------------------------------------- asientos contables (pedido de Gaby 18/11/2026)
# Liquidación mensual de cada jurisdicción (columna izquierda del detalle CM03, sfrDdjj.do?method=detalle&jurisdiccion=901):
#   Impuesto determinado 862.479,10 / Saldo a Favor DDJJ anteriores (...) 3.080.479,93 / Total Retenciones soportadas
#   390.195,00 / Total de Recaudaciones Bancarias soportadas 0,00 / Total Percepciones a deducir 699.039,22 /
#   Total Percepciones Aduaneras a deducir 0,00 / Total de deducciones / Subtotal a favor del contribuyente /
#   Subtotal a favor de la D.G.R. / Total Otros Debitos / Intereses / Monto a Ingresar
_LIQ = (("determinado", r"Impuesto determinado"),
        ("saldo_favor_anterior", r"Saldo a Favor DDJJ anteriores[^\n\d]*?(?:\([^)]*\))?"),
        ("retenciones", r"Total Retenciones soportadas"),
        ("recaudaciones_bancarias", r"Total de Recaudaciones Bancarias soportadas"),
        ("percepciones", r"Total Percepciones a deducir"),
        ("percepciones_aduaneras", r"Total Percepciones Aduaneras a deducir"),
        ("total_deducciones", r"Total de deducciones"),
        ("favor_contribuyente", r"Subtotal a favor del contribuyente"),
        ("favor_dgr", r"Subtotal a favor de la D\.G\.R\."),
        ("otros_debitos", r"Total Otros Debitos"),
        ("intereses", r"Intereses"),
        ("monto_a_ingresar", r"Monto a Ingresar"))
_NUM_LIQ = r"[ \t:$]*(-?[\d.]+,\d{2})"


def leer_liquidacion(texto: str) -> dict:
    """Texto de la pantalla de detalle de una jurisdicción -> importes de la liquidación mensual.
    Falta el determinado = no es la pantalla esperada (ErrorRobot)."""
    t = texto.replace("\xa0", " ")
    out = {}
    for clave, et in _LIQ:
        m = re.search(r"(?m)^\s*" + et + _NUM_LIQ, t) or re.search(et + _NUM_LIQ, t)
        out[clave] = importe(m[1]) if m else None
    if out["determinado"] is None:
        raise arca.ErrorRobot("SIFERE: no apareció la Liquidación Mensual de la jurisdicción")
    m = re.search(r"Coef\.?\s*Juris\s*([\d.,]+)", t)
    out["coeficiente"] = importe(m[1]) if m else None
    return {k: v for k, v in out.items()}


def _liquidaciones(page, d: dict, cuit: str, http_comarb: list[str]) -> None:
    """Abre el detalle de cada jurisdicción de la DDJJ (ícono de la fila) y guarda la liquidación en
    d['jurisdicciones'][j]['liquidacion']. Un error en una jurisdicción no frena las demás ni lo ya leído."""
    url_lista = page.url
    for j in list((d.get("jurisdicciones") or {}).keys()):
        try:
            if j != list(d["jurisdicciones"].keys())[0] and page.url != url_lista:
                _navegar(page, lambda: page.goto(url_lista), http_comarb)
            celda = page.locator("td", has_text=re.compile(rf"^\s*{j}\s*$"))
            fila = page.locator("tr").filter(has=celda).filter(has=page.locator("a"))
            if not fila.count():
                raise arca.ErrorRobot(f"no está el enlace de la jurisdicción {j}")
            _navegar(page, lambda: fila.first.locator("a").first.click(), http_comarb)
            _controlar_cuit(page, cuit)
            texto = _texto(page)
            tit = re.search(r"Jurisdicci[oó]n\s+(\d{3})", texto)
            if tit and tit.group(1) != j:
                raise arca.ErrorRobot(f"se pidió la jurisdicción {j} y la pantalla muestra {tit.group(1)}")
            d["jurisdicciones"][j]["liquidacion"] = leer_liquidacion(texto)
        except Exception as e:
            d["jurisdicciones"][j]["liquidacion_error"] = f"{type(e).__name__}: {str(e).splitlines()[0][:150]}"
        arca.pausa(0.8, 1.6)
    if page.url != url_lista:
        try:
            _navegar(page, lambda: page.goto(url_lista), http_comarb)
        except Exception:
            pass


# Pagos (menú SIFERE -> Pagos, sfrPago.do?method=buscarPagos), relevado con Gaby el 18/11/2026 (RAPTOR.MAX SRL):
#   filtros Período Desde / Hasta y Jurisdicción; tabla "Anticipo | Formulario | Forma Pago | Banco / Sucursal |
#   Fecha Pago | Impuesto | Int/Recargo/Multa | Total". Se consulta de a una jurisdicción.
def leer_tabla_pagos(tabla: list[list[str]]) -> list[dict]:
    if not tabla:
        return []
    enc = [c.lower() for c in tabla[0]]
    col = lambda *ns: next((i for i, c in enumerate(enc) if any(n in c for n in ns)), None)
    i_a, i_f, i_fp, i_b = col("anticipo"), col("formulario"), col("forma"), col("banco")
    i_fe, i_imp, i_int, i_tot = col("fecha"), col("impuesto"), col("int", "recargo"), col("total")
    if None in (i_a, i_b, i_fe, i_tot):
        return []
    out = []
    for c in tabla[1:]:
        if len(c) <= max(i_a, i_b, i_fe, i_tot):
            continue
        m = re.search(r"(\d{2})/(\d{4})\s*-\s*(\d+)", c[i_a])
        f = re.search(r"(\d{2})/(\d{2})/(\d{4})", c[i_fe])
        if not m or not f:
            continue                                          # fila de total u otra
        banco = re.sub(r"^\s*\d+\s*-\s*", "", c[i_b].split("/")[0]).strip()
        out.append({"anticipo": f"{m[2]}-{m[1]}", "rectificativa": int(m[3]),
                    "formulario": c[i_f] if i_f is not None else "", "forma_pago": c[i_fp] if i_fp is not None else "",
                    "banco": banco, "banco_sucursal": c[i_b].strip(), "fecha": f"{f[3]}-{f[2]}-{f[1]}",
                    "impuesto": importe(c[i_imp]) or 0.0 if i_imp is not None else 0.0,
                    "intereses": importe(c[i_int]) or 0.0 if i_int is not None else 0.0,
                    "total": importe(c[i_tot]) or 0.0})
    return out


def leer_pagos(page, cuit: str, jurs: list[str], http_comarb: list[str], meses: int = 13) -> str:
    """Pagos de los últimos `meses` por jurisdicción -> DATOS/<cuit>/sifere_pagos/<fecha>.json (para los asientos)."""
    from datetime import date
    if not jurs:
        return "sin jurisdicciones"
    per = arca.periodos_ultimos(meses)
    desde, hasta = per[0], per[-1]
    menu = page.locator("a", has_text=re.compile(r"^\s*Pagos\s*$"))
    res = {"cuit": cuit, "fecha": date.today().isoformat(), "desde": desde, "hasta": hasta, "jurisdicciones": {}}
    if not menu.count():
        return "sin el menú Pagos"
    for j in jurs:
        _navegar(page, lambda: menu.first.evaluate("a => a.click()"), http_comarb)       # menú oculto
        _controlar_cuit(page, cuit)
        sel_j = page.locator("select").filter(has=page.locator("option", has_text=re.compile(rf"^\s*{j}\s*-")))
        if not sel_j.count():
            raise arca.ErrorRobot("SIFERE pagos: no está el selector de jurisdicción")
        sel_j.first.select_option(value=j) if sel_j.first.locator(f"option[value='{j}']").count() else \
            sel_j.first.select_option(label=next(o for o in sel_j.first.locator("option").all_inner_texts()
                                                 if o.strip().startswith(j)))
        for nombre, valor in (("mesDesdeStr", desde[5:]), ("anioDesdeStr", desde[:4]),
                              ("mesHastaStr", hasta[5:]), ("anioHastaStr", hasta[:4])):
            if page.locator(f"select[name='{nombre}']").count():
                page.select_option(f"select[name='{nombre}']", valor)
        _navegar(page, lambda: page.locator("input[value='Buscar'], button:has-text('Buscar')").first.click(), http_comarb)
        tit = re.search(r"Jurisdicci[oó]n\s+(\d{3})", _texto(page))
        if tit and tit.group(1) != j:
            raise arca.ErrorRobot(f"SIFERE pagos: se pidió la jurisdicción {j} y la pantalla muestra {tit.group(1)}")
        pagos = []
        for tabla in page.evaluate(JS_FILAS):
            if tabla and any("Banco" in c for c in tabla[0]) and any("Fecha" in c for c in tabla[0]):
                pagos = leer_tabla_pagos(tabla)
                break
        res["jurisdicciones"][j] = {"nombre": JURISDICCIONES.get(j, j), "pagos": pagos}
        arca.pausa(1.0, 2.0)
    carpeta = os.path.join(DATOS, cuit, "sifere_pagos")
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, f"{res['fecha']}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return f"{sum(len(v['pagos']) for v in res['jurisdicciones'].values())} pagos en {len(jurs)} jurisdicciones"


def paso(cuit: str, periodos: list[str], estado: dict, forzar: bool = False):
    carpeta = os.path.join(DATOS, cuit, "sifere")

    def fn(ctx, portal):
        http_comarb: list[str] = []
        anotar = lambda req: http_comarb.append(req.url) if re.match(r"^http://[^/]*comarb\.gob\.ar", req.url) else None
        ctx.on("request", anotar)
        try:
            try:
                page = arca.abrir_servicio(ctx, portal, "sifere_consultas")
            except arca.RequiereIntervencion:
                estado["_servicio"] = "sin servicio (no está en Convenio Multilateral)"
                return dict(estado)
            page.wait_for_load_state("domcontentloaded")
            _pasar_a_https(page, http_comarb)
            elegir_contribuyente(page, cuit, http_comarb)
            return _leer_periodos(page, http_comarb)
        finally:
            ctx.remove_listener("request", anotar)

    def _leer_periodos(page, http_comarb):
        os.makedirs(carpeta, exist_ok=True)
        for per in periodos:
            if per in estado:
                continue
            ruta = os.path.join(carpeta, f"{per}.json")
            # 22/11/2026 (Humaitá: meses presentados y pagos figuraban "No presentada"): la búsqueda de los 12 meses
            # juntos trae una lista larga (con rectificativas) que SIFERE pagina, y solo se leía la primera página.
            # Ahora se busca MES POR MES: la lista es corta y la fila queda en la misma pantalla para abrirla.
            _buscar(page, per, per, http_comarb)
            lista = _lista(page)
            if per not in lista:
                txt = _texto(page)
                if not re.search(r"Anticipo", txt, re.I) and not re.search(r"no (se encontraron|existen|hay)|sin resultados", txt, re.I):
                    estado[per] = "sin dato (SIFERE no mostró la lista)"
                else:
                    estado[per] = "no presentada"
                continue
            rect, _ = lista[per]
            previo = {}
            if os.path.exists(ruta) and not forzar:
                with open(ruta, encoding="utf-8") as f:
                    previo = json.load(f)
                # se vuelve a leer una vez si le falta la liquidación por jurisdicción (asientos, 19/11/2026)
                # (hasta 3 intentos si la pantalla de detalle falla, para no repetirlo en cada corrida)
                if previo.get("rectificativa") == rect and (all(
                        "liquidacion" in (v or {}) for v in (previo.get("jurisdicciones") or {}).values())
                        or previo.get("liquidacion_intentos", 0) >= 3):
                    estado[per] = "ya bajado"
                    continue
            # buscar de nuevo la fila (después de volver la tabla se regenera)
            texto_ant = f"{per[5:]}/{per[:4]} - {rect}"
            fila = page.locator("tr", has_text=texto_ant).filter(has=page.locator("a"))
            if not fila.count():
                _buscar(page, per, per, http_comarb)
                fila = page.locator("tr", has_text=texto_ant).filter(has=page.locator("a"))
            _navegar(page, lambda: fila.first.locator("a").first.click(), http_comarb)
            _controlar_cuit(page, cuit)
            d = _detalle(page)
            d.update({"cuit": cuit, "periodo": per, "rectificativa": rect})
            _liquidaciones(page, d, cuit, http_comarb)
            if any("liquidacion_error" in (v or {}) for v in d["jurisdicciones"].values()):
                prev_int = previo.get("liquidacion_intentos", 0) if os.path.exists(ruta) and previo.get("rectificativa") == rect else 0
                d["liquidacion_intentos"] = prev_int + 1
            with open(ruta, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            estado[per] = "OK"
            # no se usa "atrás" (la lista es resultado de un formulario): el próximo período vuelve a buscar
        try:
            estado["_deuda"] = leer_deuda(page, cuit, http_comarb)
        except Exception as e:                     # la deuda no frena lo ya leído
            estado["_deuda"] = f"ERROR {type(e).__name__}: {str(e).splitlines()[0][:150]}"
        try:                                       # pagos con banco y fecha, para los asientos (19/11/2026)
            estado["_pagos"] = leer_pagos(page, cuit, _jurisdicciones_cliente(cuit), http_comarb)
        except Exception as e:
            estado["_pagos"] = f"ERROR {type(e).__name__}: {str(e).splitlines()[0][:150]}"
        page.close()
        return dict(estado)
    return fn


def _jurisdicciones_cliente(cuit: str) -> list[str]:
    import glob
    jur = set()
    for r in glob.glob(os.path.join(DATOS, cuit, "sifere", "[0-9][0-9][0-9][0-9]-[0-9][0-9].json")):
        try:
            with open(r, encoding="utf-8") as f:
                jur |= set((json.load(f).get("jurisdicciones") or {}).keys())
        except Exception:
            continue
    return sorted(j for j in jur if j in JURISDICCIONES)


def _anticipos_tabla(page) -> list[dict]:
    filas = page.evaluate("""() => { const t = document.getElementById('rCtaCte'); if (!t) return null;
        return [...t.rows].map(r => [...r.cells].map(c => c.innerText.trim())); }""")
    if filas is None:
        return []
    out = []
    for c in filas:
        if len(c) >= 5 and re.fullmatch(r"\d{6}", c[0]):
            v = [importe(x) or 0.0 for x in c[1:5]]
            out.append({"anticipo": f"{c[0][:4]}-{c[0][4:]}", "saldo_fisco": v[0], "saldo_contribuyente": v[1],
                        "pagado_ddjj": v[2], "pagado_otro": v[3]})
    return out


def analizar_deuda(anticipos: list[dict], hoy=None) -> dict:
    """Impago = saldo a favor del fisco - lo pagado (DDJJ + otro). Los anticipos que vencieron hace menos de
    10 días se marcan 'reciente': COMARB puede tardar hasta 7 días en mostrar el pago."""
    from datetime import date, timedelta
    hoy = hoy or date.today()
    filas, deuda, impagos = [], 0.0, 0
    for a in sorted(anticipos, key=lambda x: x["anticipo"]):
        imp = round(max(0.0, a["saldo_fisco"] - a["pagado_ddjj"] - a["pagado_otro"]), 2)
        y, m = map(int, a["anticipo"].split("-"))
        venc = date(y + (m == 12), m % 12 + 1, 15)                 # vencimiento aproximado: mediados del mes siguiente
        reciente = imp > 0 and hoy - venc < timedelta(days=10)
        estado = ("pagado" if a["saldo_fisco"] and not imp else "sin saldo" if not a["saldo_fisco"]
                  else "pago parcial" if (a["pagado_ddjj"] + a["pagado_otro"]) else "IMPAGO")
        if reciente:
            estado += " (reciente: el pago puede no figurar aún)"
        filas.append({**a, "impago": imp, "estado": estado})
        if imp and not reciente:
            deuda += imp
            impagos += 1
    return {"anticipos": filas, "deuda": round(deuda, 2), "impagos": impagos}


def leer_deuda(page, cuit: str, http_comarb: list[str], anios: int = 15) -> str:
    """Resumen de DDJJs y Pagos por jurisdicción, HISTÓRICO (pedido de Gaby 17/11/2026: "buscar la deuda de convenio
    histórica para saber si está compensada con algo"). Desde el año más viejo que ofrece COMARB (tope: `anios`).
    Si un anticipo tiene saldo a favor del fisco y no tiene el pago, lo debe. La diferencia es capital SIN actualizar
    (no es la deuda de hoy). Se avisa al encargado, que la marca "vista" en la web."""
    from datetime import date
    jurs = _jurisdicciones_cliente(cuit)
    if not jurs:
        return "sin jurisdicciones (sin DDJJ de Convenio bajadas)"
    hoy = date.today()
    hasta = arca.periodos_ultimos(1)[-1]                           # último mes completo
    y, m = map(int, hasta.split("-"))
    desde = f"{y - anios}-{m + 1:02d}" if m < 12 else f"{y - anios + 1}-01"
    menu = page.locator("a", has_text=re.compile(r"Resumen de DDJJs y Pagos", re.I))
    res = {"cuit": cuit, "fecha": hoy.isoformat(), "desde": desde, "hasta": hasta, "jurisdicciones": {}}
    for j in jurs:
        if not page.locator("select[name='juris']").count():
            _navegar(page, lambda: menu.first.evaluate("a => a.click()"), http_comarb)   # menú oculto
            _controlar_cuit(page, cuit)
        page.select_option("select[name='juris']", j)
        anios_disp = [int(x) for x in page.locator("select[name='anioDesdeStr'] option").all_inner_texts() if x.strip().isdigit()]
        if anios_disp and min(anios_disp) > int(desde[:4]):
            desde = f"{min(anios_disp)}-01"                  # no hay datos más viejos que el primer año que ofrece
        res["desde"] = desde
        page.select_option("select[name='mesDesdeStr']", desde[5:])
        page.select_option("select[name='anioDesdeStr']", desde[:4])
        page.select_option("select[name='mesStr']", hasta[5:])
        page.select_option("select[name='anioStr']", hasta[:4])
        _navegar(page, lambda: page.locator("input[value='Buscar'], button:has-text('Buscar')").first.click(), http_comarb)
        titulo = re.search(r"Jurisdicci[oó]n\s+(\d{3})\s*-\s*Per[ií]odo", _texto(page))
        if not titulo or titulo.group(1) != j:
            raise arca.ErrorRobot(f"SIFERE deuda: se pidió la jurisdicción {j} y la pantalla muestra otra")
        an = analizar_deuda(_anticipos_tabla(page), hoy)
        an["saldo_contribuyente"] = round(sum(a["saldo_contribuyente"] for a in an["anticipos"]), 2)
        res["jurisdicciones"][j] = {"nombre": JURISDICCIONES[j], **an}
        arca.pausa(1.0, 2.0)
    res["deuda_total"] = round(sum(v["deuda"] for v in res["jurisdicciones"].values()), 2)
    res["alertas"] = [{"prioridad": "ALTA", "tipo": "Convenio Multilateral",
                       "texto": f"IIBB Convenio {v['nombre']} ({j}): {v['impagos']} anticipos impagos por "
                                f"${v['deuda']:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                                + f" sin actualizar (último {max(a['anticipo'] for a in v['anticipos'] if a['impago'])})"
                                + " — el encargado tiene que revisarlo y marcarlo visto"}
                      for j, v in res["jurisdicciones"].items() if v["deuda"]]
    carpeta = os.path.join(DATOS, cuit, "sifere_deuda")
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return f"{len(jurs)} jurisdicciones, deuda ${res['deuda_total']:,.2f}"


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, periodos=None, **_):
    periodos = periodos or ([periodo] if periodo else arca.periodos_ultimos(12))
    estado: dict = {}
    r = arca.ejecutar(usuario, clave, [("sifere", paso(cuit, periodos, estado))],
                      os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "periodos": estado, "reingresos": r["_reingresos"], "archivos": {"sifere": {"alertas": []}}}
