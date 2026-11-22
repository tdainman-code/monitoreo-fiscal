"""Robot Portal IVA: descarga el Libro IVA de los períodos YA PRESENTADOS (meses cerrados).

Recorrido (relevado el 16/11/2026 con GONCALVES VICENTE JUAN JOSE, 20-33116278-8):
  Mis servicios -> PORTAL IVA (siapweb.cloud.afip.gob.ar/iva/)  encabezado "NOMBRE [CUIT 20-33116278-8]"
  "Declaraciones juradas presentadas" -> CONSULTAR      (#/anteriores)
  "Libro IVA" -> CONSULTAR                              (#/livas.anteriores)
     lista: Formulario F2083 | Período Fiscal 11/2025 | Secuencia "DJ Original" | Fecha de presentación
     botones por fila:  [acuse de recibo]  [ver (ojo)]  [RECTIFICAR]   <- RECTIFICAR NUNCA SE TOCA
  ojo -> liva.afip.gob.ar/liva/jsp/verVistaPrevia.do   "Vista Previa | 11/2025", encabezado "[20-33116278-8]"
     botón XML (#btnDescargarVistaPrevia, "Exportar el Libro IVA") -> zip con
     comprobantes_compras.csv, comprobantes_ventas.csv, libro_iva.xml
Guarda DATOS/<cuit>/libro_iva/<AAAA-MM>.zip y <AAAA-MM>.json (resumen + control contra la DJ).
Si el contribuyente no tiene Portal IVA (monotributista) queda "sin servicio" y se sigue con Mis Comprobantes.
Solo consulta y descarga: no presenta, no rectifica, no genera VEP.
"""
from __future__ import annotations

import json
import os
import re
import time

from . import arca
from .lector_libro_iva import leer_zip

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")

# Cualquier botón cuyo texto/título coincida con esto NO se toca nunca.
PROHIBIDO = re.compile(r"rectific|present(ar|aci)|nueva|vep|pag(ar|o)|enviar|confirm|generar|eliminar|borrar", re.I)

JS_FILAS = r"""() => {
  const out = [];
  const etiqueta = b => ((b.innerText || '') + ' ' + (b.title || '') + ' ' + (b.getAttribute('aria-label') || '')).trim();
  const recs = [...document.querySelectorAll('button, a')].filter(b => /rectificar/i.test(etiqueta(b)));
  const reP = /(?<![\d\/])(\d{2})\/(\d{4})(?![\d\/])/;
  recs.forEach((b, i) => {
    let e = b.parentElement;
    while (e && !reP.test(e.innerText || '')) e = e.parentElement;
    if (!e) return;
    e.setAttribute('data-robot-fila', String(i));
    const t = (e.innerText || '').replace(/\s+/g, ' ');
    const m = t.match(reP);
    const f = t.match(/(\d{2}\/\d{2}\/\d{4})/);
    const s = t.match(/(DJ\s+Original|Original|Rectificativa\s*(?:N[°ºo.]*\s*)?(\d+))/i);
    const botones = [...e.querySelectorAll('button, a')].map(etiqueta);
    out.push({fila: String(i), periodo: m ? m[2] + '-' + m[1] : null, fecha: f ? f[1] : null,
              secuencia_txt: s ? s[1] : '', secuencia: s && s[2] ? parseInt(s[2]) : 0,
              botones: botones, texto: t.slice(0, 160)});
  });
  return out;
}"""


def _texto(page) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return ""


# Portal IVA: "REPRESENTANDO A: BH ... [CUIT 30-71746863-1]"; Nuestra Parte: "REPRESENTANDO A: BH ... [30-71746863-1]"
_RE_REPRESENTANDO = re.compile(r"REPRESENTANDO A:?\s*[^\[]*\[\s*(?:CUIT\s*)?(\d{2}-\d{8}-\d)\s*\]", re.I)


def elegir_representado(page, cuit: str, espera_s: int = 45) -> None:
    """Portal IVA con apoderado (relevado con Gaby el 17/11/2026): el encabezado dice
    'REPRESENTANDO A: DAINMAN TOMAS [CUIT 20-38893131-1]'; el ícono de al lado lleva a #/changeRelation,
    'Elegí una persona para ingresar', con una tarjeta por empresa ('BH SOLUCIONES ... [CUIT 30-71746863-1]').
    Se elige la tarjeta del cliente y se controla que el encabezado pase a ese CUIT."""
    fmt = arca.cuit_fmt(cuit)
    limite = time.time() + espera_s
    while time.time() < limite:
        m = _RE_REPRESENTANDO.search(_texto(page)[:1500])
        if m:
            break
        if fmt in _texto(page)[:600]:                 # sin apoderados: el encabezado ya es del cliente
            return
        page.wait_for_timeout(1000)
    else:
        return                                         # pantalla sin "representando a": lo controla _controlar_cuit
    if m[1] == fmt:
        return
    base = page.url.split("#")[0]
    page.goto(base + "#/changeRelation", wait_until="domcontentloaded")
    arca.pausa(1.0, 2.0)
    tarjeta = page.get_by_text(re.compile(rf"\[\s*CUIT\s*{re.escape(fmt)}\s*\]"))
    try:
        tarjeta.first.wait_for(state="visible", timeout=30_000)
    except Exception:
        raise arca.SinRepresentado(f"Portal IVA: {fmt} no está entre las personas que puede representar el usuario")
    tarjeta.first.click()
    arca.pausa(1.5, 3.0)
    limite = time.time() + 30
    while time.time() < limite:
        m = _RE_REPRESENTANDO.search(_texto(page)[:1500])
        if m and m[1] == fmt:
            if "changeRelation" in page.url:
                page.goto(base + "#/", wait_until="domcontentloaded")
                arca.pausa(1.0, 2.0)
            return
        page.wait_for_timeout(1000)
    raise arca.CuitEquivocado(f"Portal IVA: se eligió {fmt} y el encabezado no cambió")


def _controlar_cuit(page, cuit: str, donde: str, espera_s: int = 45) -> None:
    """El encabezado tiene que mostrar el CUIT del cliente (Portal IVA: '[CUIT 20-33116278-8]';
    Libro IVA: '[20-33116278-8]'). Si hay una pantalla para elegir a quién representar, se elige."""
    fmt = arca.cuit_fmt(cuit)
    limite = time.time() + espera_s
    elegido = False
    while time.time() < limite:
        t = _texto(page)
        m = _RE_REPRESENTANDO.search(t[:1500])
        if m:
            if m[1] == fmt:
                return
            raise arca.SinRepresentado(f"{donde}: representa a {m[1]} y no a {fmt}")
        if fmt in t[:3000]:
            return
        if not elegido and re.search(r"represent|eleg[ií]|seleccion", t, re.I):
            loc = page.get_by_text(fmt, exact=False)
            try:
                if loc.first.is_visible(timeout=1000):
                    loc.first.click()
                    elegido = True
                    arca.pausa()
                    continue
            except Exception:
                pass
        page.wait_for_timeout(1500)
    otros = sorted(set(re.findall(r"\d{2}-\d{8}-\d", _texto(page)[:3000])) - {fmt})
    if otros:
        raise arca.CuitEquivocado(f"{donde}: la pantalla muestra {', '.join(otros)} y no {fmt}")
    raise arca.SinRepresentado(f"{donde}: no aparece el CUIT {fmt} en el encabezado")


def _xp_texto(texto: str) -> str:
    """XPath del elemento MÁS INTERNO cuyo texto es exactamente 'texto' (sin importar mayúsculas ni si es
    button, a, div o span: en el Portal IVA real CONSULTAR no resultó ser un <button>, 16/11/2026)."""
    t = texto.upper()
    norm = f"translate(normalize-space(.),'{texto.lower()}','{t}')='{t}'"
    return f"*[{norm} and not(*[{norm}])]"


def _boton_en_tarjeta(page, titulo: str):
    """CONSULTAR de la tarjeta cuyo título es 'titulo' (pantallas de inicio del Portal IVA)."""
    tit = page.get_by_text(re.compile(rf"^\s*{titulo}\s*$", re.I)).first
    tit.wait_for(state="visible", timeout=60_000)
    tarjeta = tit.locator(f"xpath=ancestor::*[.//{_xp_texto('consultar')}][1]")
    return tarjeta.locator(f"xpath=.//{_xp_texto('consultar')}").first


def _hay_rectificar(page) -> bool:
    return page.locator(f"xpath=//{_xp_texto('rectificar')}").count() > 0


def _ir_a_lista(page) -> None:
    if _hay_rectificar(page):
        return
    if not re.search(r"#/(anteriores|livas)", page.url):
        _boton_en_tarjeta(page, "Declaraciones juradas presentadas").click()
        arca.pausa(1.0, 2.0)
    _boton_en_tarjeta(page, "Libro IVA").click()
    arca.pausa(1.0, 2.0)
    limite = time.time() + 60
    inicio = time.time()
    while time.time() < limite:
        if _hay_rectificar(page):
            return
        if arca._hay_texto(page, r"no (hay|se encontraron|existen|registra)"):
            return
        # 22/11/2026 (Acuña Ana María): sin ningún Libro IVA presentado la pantalla muestra el título "Libro IVA" con
        # la lista VACÍA y sin mensaje. Pasados 20 s con el título y sin filas, es lista vacía (no una falla).
        if time.time() - inicio > 20 and arca._hay_texto(page, r"Declaraciones juradas presentadas") \
                and arca._hay_texto(page, r"Libro IVA") and not page.locator("table tr td, .card .row, li.list-group-item").count():
            return
        page.wait_for_timeout(1000)
    raise arca.ErrorRobot("Portal IVA: no apareció la lista de Libros IVA presentados")


def _lista(page) -> dict[str, dict]:
    """{'2025-11': {fila, fecha, secuencia, secuencia_txt}} con la última presentación de cada período."""
    out: dict = {}
    for f in page.evaluate(JS_FILAS):
        p = f.get("periodo")
        if not p:
            continue
        clave = (f["secuencia"], f.get("fecha") or "")
        if p not in out or clave > (out[p]["secuencia"], out[p].get("fecha") or ""):
            out[p] = f
    return out


def _abrir_vista_previa(ctx, page, fila: str, periodo: str):
    """Hace clic en el 'ojo' de la fila (el botón que NO es acuse ni rectificar). Devuelve la página del Libro IVA."""
    contenedor = page.locator(f"[data-robot-fila='{fila}']")
    botones = contenedor.locator("button, a")
    candidato = None
    for i in range(botones.count()):
        b = botones.nth(i)
        etiqueta = " ".join(filter(None, [b.inner_text().strip(), b.get_attribute("title") or "",
                                          b.get_attribute("aria-label") or ""]))
        if PROHIBIDO.search(etiqueta) or re.search(r"acuse|descargar", etiqueta, re.I):
            continue
        candidato = (b, etiqueta)
        break
    if candidato is None:
        raise arca.ErrorRobot(f"Portal IVA: no se encontró el botón 'ver' del período {periodo}")
    boton, etiqueta = candidato
    if PROHIBIDO.search(etiqueta):                     # doble control: nunca rectificar ni presentar
        raise arca.ErrorRobot(f"Portal IVA: el botón elegido ('{etiqueta}') no es de consulta; no se tocó")
    antes = set(ctx.pages)
    boton.click()
    limite = time.time() + 90
    while time.time() < limite:
        nuevas = [p for p in ctx.pages if p not in antes]
        if nuevas:
            vp = nuevas[-1]
            break
        if "liva.afip.gob.ar" in page.url:
            vp = page
            break
        page.wait_for_timeout(1000)
    else:
        raise arca.ErrorRobot(f"Portal IVA: la vista previa de {periodo} no abrió")
    vp.wait_for_load_state("domcontentloaded")
    arca.verificar_sesion(vp, "libro_iva")
    vp.locator("#btnDescargarVistaPrevia").wait_for(state="visible", timeout=90_000)
    a, m = periodo.split("-")
    t = _texto(vp)
    if not re.search(rf"Vista Previa\s*\|?\s*{m}/{a}", t, re.I) and f"{m}/{a}" not in t[:2000]:
        raise arca.ErrorRobot(f"Libro IVA: la vista previa no es del período {m}/{a}")
    return vp


def _volver(page, vp, base: str, cuit: str | None = None) -> None:
    """Vuelve a la lista de Libros IVA. Arreglo 19/11/2026 (caso 30-71103454-0, solo bajaba 11/2025): cuando el
    usuario es apoderado, al volver de la vista previa el Portal IVA puede caer en 'Elegí una persona para
    ingresar' (#/changeRelation) con el representado de vuelta en el propio usuario; hay que elegir otra vez la
    empresa y controlar el CUIT antes de seguir con el próximo mes."""
    if vp is not page:
        try:
            vp.close()
        except Exception:
            pass
    else:
        try:
            page.go_back(wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception:
            pass
        if "siapweb" not in page.url:
            page.goto(base, wait_until="domcontentloaded")
    if cuit:
        if "changeRelation" in page.url:
            page.goto(base + "#/", wait_until="domcontentloaded")
            arca.pausa(1.0, 2.0)
        elegir_representado(page, cuit)
        _controlar_cuit(page, cuit, "Portal IVA")
    _ir_a_lista(page)


def guardar_categoria(cuit: str, categoria: str) -> None:
    """Categoría del cliente para ordenar las corridas por importancia (RI primero)."""
    from datetime import date
    os.makedirs(os.path.join(DATOS, cuit), exist_ok=True)
    with open(os.path.join(DATOS, cuit, "categoria.json"), "w", encoding="utf-8") as fh:
        json.dump({"categoria": categoria, "fecha": date.today().isoformat()}, fh, ensure_ascii=False)


def prioridad(cuit: str) -> int:
    """1 = responsable inscripto, 2 = sin clasificar todavía, 3 = monotributo / sin Portal IVA."""
    ruta = os.path.join(DATOS, cuit, "categoria.json")
    if not os.path.exists(ruta):
        return 1 if os.path.isdir(os.path.join(DATOS, cuit, "libro_iva")) and \
            any(n.endswith(".json") for n in os.listdir(os.path.join(DATOS, cuit, "libro_iva"))) else 2
    with open(ruta, encoding="utf-8") as fh:
        cat = json.load(fh).get("categoria", "")
    return 1 if cat.startswith("Responsable") else 3


def _es_monotributista(cuit: str) -> bool:
    """Según la última lectura de la CCMA: 'MONOTRIBUTISTA' sin 'AUTONOMO' (el autónomo es inscripto en IVA)."""
    import glob as _g
    rutas = sorted(x for x in _g.glob(os.path.join(DATOS, cuit, "ccma", "*.json")) if not os.path.basename(x).startswith("_"))
    if not rutas:
        return False
    try:
        with open(rutas[-1], encoding="utf-8") as f:
            tipo = ((json.load(f).get("totales") or {}).get("tipo") or "").upper()
    except (OSError, ValueError):
        return False
    return "MONOTRIBUT" in tipo and "AUTONOMO" not in tipo


def paso(cuit: str, periodos: list[str], estado: dict, forzar: bool = False):
    carpeta = os.path.join(DATOS, cuit, "libro_iva")

    def fn(ctx, portal):
        try:
            page = arca.abrir_servicio(ctx, portal, "portal_iva")
        except arca.RequiereIntervencion:
            estado["_servicio"] = "sin servicio (sin Portal IVA: monotributo o exento)"
            guardar_categoria(cuit, "sin Portal IVA (monotributo/exento)")
            return dict(estado)
        page.wait_for_load_state("domcontentloaded")
        base = page.url.split("#")[0]
        elegir_representado(page, cuit)
        _controlar_cuit(page, cuit, "Portal IVA")
        try:
            _ir_a_lista(page)
        except arca.ErrorRobot:
            # 22/11/2026 (Gándara): si el cliente no es responsable inscripto el Portal IVA no tiene Libro IVA;
            # no es una falla del robot. Se reconoce por el texto de la pantalla o por la CCMA (monotributista).
            texto = page.inner_text("body")
            if re.search(r"monotribut|no (se encuentra|est[aá]) inscript|no posee (el impuesto|IVA)|exento", texto, re.I) \
                    or _es_monotributista(cuit):
                estado["_servicio"] = "sin Libro IVA (no es responsable inscripto: monotributo o exento)"
                guardar_categoria(cuit, "sin Portal IVA (monotributo/exento)")
                page.close()
                return dict(estado)
            raise
        lista = _lista(page)
        if not lista and _es_monotributista(cuit):
            estado["_servicio"] = "sin Libro IVA (monotributista)"
            guardar_categoria(cuit, "sin Portal IVA (monotributo/exento)")
            page.close()
            return dict(estado)
        if not lista:
            estado["_servicio"] = "Portal IVA sin ningún Libro IVA presentado"
        else:
            guardar_categoria(cuit, "Responsable inscripto")
        os.makedirs(carpeta, exist_ok=True)
        mas_viejo = min(lista) if lista else None
        for per in periodos:
            if per in estado:
                continue
            if per not in lista:
                estado[per] = ("fuera de la lista (revisar a mano)" if mas_viejo and per < mas_viejo and len(lista) >= 10
                               else "no presentado")
                continue
            f = lista[per]
            ruta_json = os.path.join(carpeta, f"{per}.json")
            if os.path.exists(ruta_json) and not forzar:
                with open(ruta_json, encoding="utf-8") as fh:
                    previo = json.load(fh)
                if (previo.get("secuencia_portal"), previo.get("fecha_presentacion")) == (f["secuencia"], f.get("fecha")):
                    estado[per] = "ya bajado"
                    continue
            try:
                estado[per] = _bajar_periodo(ctx, page, base, cuit, per, f, carpeta)
            except (arca.SesionPerdida, arca.SinRepresentado, arca.ClaveInvalida, arca.RequiereIntervencion):
                raise                                  # CUIT equivocado, sesión caída, etc.: como siempre
            except Exception as e:                     # un mes que falla no frena los demás (19/11/2026)
                estado[per] = f"ERROR {type(e).__name__}: {str(e).splitlines()[0][:150]}"
                for extra in [x for x in ctx.pages if x is not page]:
                    try:
                        extra.close()
                    except Exception:
                        pass
                page.goto(base, wait_until="domcontentloaded")
                elegir_representado(page, cuit)
                _controlar_cuit(page, cuit, "Portal IVA")
                _ir_a_lista(page)
        page.close()
        return dict(estado)
    return fn


def _bajar_periodo(ctx, page, base: str, cuit: str, per: str, f: dict, carpeta: str) -> str:
    """Baja el Libro IVA de un mes (vista previa -> XML) y vuelve a la lista. Devuelve el estado del mes."""
    ruta_json = os.path.join(carpeta, f"{per}.json")
    f = _lista(page).get(per) or f            # la lista se regenera al volver: marcar las filas de nuevo
    vp = _abrir_vista_previa(ctx, page, f["fila"], per)
    _controlar_cuit(vp, cuit, "Libro IVA")
    ruta_zip = os.path.join(carpeta, f"{per}.zip")
    with vp.expect_download(timeout=180_000) as dl:
        vp.locator("#btnDescargarVistaPrevia").click()
    tmp = ruta_zip + ".descarga"
    dl.value.save_as(tmp)
    with open(tmp, "rb") as fh:
        if fh.read(2) != b"PK":
            raise arca.ErrorRobot(f"Libro IVA {per}: la descarga no es un zip")
    os.replace(tmp, ruta_zip)
    r = leer_zip(ruta_zip)
    if r["periodo"] and r["periodo"] != per:
        os.remove(ruta_zip)
        raise arca.ErrorRobot(f"Libro IVA: se pidió {per} y el archivo es de {r['periodo']}; se descartó")
    r.update({"cuit": cuit, "secuencia_portal": f["secuencia"], "secuencia_txt": f.get("secuencia_txt"),
              "fecha_presentacion": f.get("fecha")})
    with open(ruta_json, "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False, indent=1)
    res = "OK" if r["control"]["ok"] else "OK con diferencias contra la DJ"
    _volver(page, vp, base, cuit)
    arca.pausa(1.5, 3.0)
    return res


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, periodos=None, forzar=False, **_):
    periodos = periodos or ([periodo] if periodo else arca.periodos_ultimos(12))
    estado: dict = {}
    r = arca.ejecutar(usuario, clave, [("libro_iva", paso(cuit, periodos, estado, forzar))],
                      os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "periodos": estado, "reingresos": r["_reingresos"], "archivos": {"libro_iva": {"alertas": []}}}
