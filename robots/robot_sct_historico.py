"""Deuda HISTÓRICA en Cuentas Tributarias: Cuenta corriente -> ESTADO DE CUMPLIMIENTO (relevado con Gaby el 17/11/2026).

Para qué: la solapa "Deudas" del inicio no muestra todo. En el estado de cumplimiento aparece, impuesto por impuesto,
la deuda de cada período y concepto: por ejemplo los conceptos del F.931 que no son 301/351 (28 Seguro de vida,
302 Aportes obras sociales, 312 ART, 352 Contribuciones obra social), intereses resarcitorios, etc.

Recorrido:
  Sistema de Cuentas Tributarias -> menú CUENTA CORRIENTE -> ESTADO DE CUMPLIMIENTO
  -> "Ingreso de Parámetros" (sin períodos = año en curso; columnas DEUDA, S.L.D., SALDO TECNICO, OTROS CREDITOS,
     MULTAS NO FIRMES tildadas) -> SIGUIENTE
  -> "Mostrar Consulta": "Período Fiscal consultado 20260000 a 20261200", botones "|< AÑO ANTERIOR" / "AÑO SIGUIENTE >|",
     totales (Deuda, Saldo Libre Disponibilidad, Saldo técnico, Otros Créditos, Multas no Firmes) y una tabla por
     impuesto ("28 - SEGURO DE VIDA COLECTIVO"): Est. | Período | Concepto | Ant./Cuota | DEUDA | S.L.D. | SALDO TECNICO |
     OTROS CREDITOS | MULTAS NO FIRMES | Temp. DDJJ | Estado DDJJ | Temp. Pago | Estado Pago, con fila Subtotal.
     La DEUDA viene en ROJO si es propia de ARCA (IVA, 301, 351...) y en VERDE si ARCA la recauda para TERCEROS
     (obras sociales 302/352, ART 312, seguro de vida 28) — explicado por Gaby el 17/11/2026. Para el estudio tienen
     la MISMA importancia: el cliente la debe igual y lo pueden embargar o hacerle juicio. Solo se informa el destino.
  -> AÑO ANTERIOR y se repite, año por año.
Solo consulta.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
ANIOS = 6                                   # año en curso + 5 anteriores
ESPERA_CARGA = 90                           # segundos de "CARGANDO" antes de darla por trabada
F931 = {"28", "301", "302", "312", "351", "352", "360"}

JS_TABLAS = r"""() => {
  const out = [];
  const tablas = [...document.querySelectorAll('table')].filter(t => /DEUDA/.test(t.textContent) && /Concepto/i.test(t.textContent));
  for (const t of tablas) {
    // título del impuesto: el texto "NNN - NOMBRE" más cercano antes de la tabla
    let titulo = '', el = t;
    for (let i = 0; i < 12 && el && !titulo; i++) {
      let p = el.previousElementSibling;
      while (p && !titulo) {
        const m = (p.innerText || '').match(/(^|\n)\s*(\d{1,4}\s*-\s*[^\n]+)/);
        if (m) titulo = m[2].trim();
        p = p.previousElementSibling;
      }
      el = el.parentElement;
    }
    const cab = [...t.querySelectorAll('thead th, tr:first-child th')].map(h => h.innerText.replace(/\s+/g, ' ').trim());
    const filas = [];
    for (const r of t.querySelectorAll('tbody tr')) {
      const celdas = [...r.cells].map(c => c.innerText.replace(/\s+/g, ' ').trim());
      const colores = [...r.cells].map(c => { const a = c.querySelector('a, span') || c; return getComputedStyle(a).color; });
      filas.push({celdas, colores});
    }
    out.push({titulo, cab, filas});
  }
  return out;
}"""


def _num(t: str) -> float | None:
    t = (t or "").strip()
    m = re.search(r"-?[\d.,]*\d", t)
    if not m:
        return None
    s = m[0]
    if "," in s and "." in s:                 # 2,918,725.52 (tabla) o 2.918.725,52 (totales)
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(".", "").replace(",", ".") if re.search(r",\d{2}$", s) else s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def _color(css: str) -> str:
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", css or "")
    if not m:
        return ""
    r, g, b = map(int, m.groups())
    if r > 150 and g < 100:
        return "rojo"
    if g > 100 and r < 100:
        return "verde"
    return ""


def leer_totales(texto: str) -> dict:
    t = re.sub(r"\s+", " ", texto)
    out = {}
    for clave, et in (("deuda", r"Deuda"), ("sld", r"Saldo Libre Disponibilidad"), ("saldo_tecnico", r"Saldo t[eé]cnico"),
                      ("otros_creditos", r"Otros Cr[eé]ditos"), ("multas_no_firmes", r"Multas no Firmes")):
        m = re.search(et + r"\s*\$\s*([\d.,]+)", t, re.I)
        out[clave] = _num(m[1]) if m else None
    m = re.search(r"Per[ií]odo Fiscal consultado\s*(\d{8})\s*a\s*(\d{8})", t, re.I)
    out["desde"], out["hasta"] = (m[1], m[2]) if m else ("", "")
    return out


def analizar(tablas: list[dict]) -> list[dict]:
    """Filas con DEUDA > 0 (sin subtotales)."""
    out = []
    for t in tablas:
        cab = [c.upper() for c in t.get("cab") or []]
        i_d = next((i for i, c in enumerate(cab) if c.startswith("DEUDA")), 4)
        col = lambda nombre, defecto: next((i for i, c in enumerate(cab) if c.startswith(nombre)), defecto)
        i_p, i_c, i_ep = col("PER", 1), col("CONCEPTO", 2), col("ESTADO PAGO", 12)
        m = re.match(r"(\d+)\s*-\s*(.+)", t.get("titulo") or "")
        imp, nombre = (m[1], m[2].strip()) if m else ("", t.get("titulo") or "")
        for f in t.get("filas") or []:
            c = f["celdas"]
            if len(c) <= i_d or not re.fullmatch(r"\d{8}", c[i_p] if len(c) > i_p else ""):
                continue
            deuda = _num(c[i_d]) or 0.0
            if deuda <= 0:
                continue
            out.append({"impuesto": imp, "nombre": nombre, "periodo": c[i_p], "concepto": c[i_c] if len(c) > i_c else "",
                        "deuda": round(deuda, 2), "color": _color((f.get("colores") or [""] * 20)[i_d]),
                        "estado_pago": c[i_ep] if len(c) > i_ep else "", "f931": imp in F931})
    return out


IVA = "30"


def analizar_movimientos(tablas: list[dict]) -> list[dict]:
    """Todas las filas con algún importe (deuda, S.L.D., saldo técnico, otros créditos), por impuesto, período y
    concepto: para ver el saldo de cada concepto de cargas sociales y no solo la deuda (Gaby 20/11/2026)."""
    out = []
    for t in tablas:
        cab = [c.upper().replace(" ", "") for c in t.get("cab") or []]
        col = lambda pref, d=None: next((i for i, c in enumerate(cab) if c.startswith(pref)), d)
        i_p, i_c, i_d, i_s, i_t, i_o = col("PER", 1), col("CONCEPTO", 2), col("DEUDA"), col("S.L.D"), col("SALDOTEC"), col("OTROSCRED")
        m = re.match(r"(\d+)\s*-\s*(.+)", t.get("titulo") or "")
        imp, nombre = (m[1], m[2].strip()) if m else ("", t.get("titulo") or "")
        for f in t.get("filas") or []:
            c = f["celdas"]
            if not re.fullmatch(r"\d{8}", c[i_p] if len(c) > i_p else ""):
                continue
            v = lambda i: round(_num(c[i]) or 0.0, 2) if i is not None and i < len(c) else 0.0
            fila = {"impuesto": imp, "nombre": nombre, "periodo": c[i_p], "concepto": c[i_c] if len(c) > i_c else "",
                    "deuda": v(i_d), "sld": v(i_s), "saldo_tecnico": v(i_t), "otros_creditos": v(i_o)}
            if any(fila[k] for k in ("deuda", "sld", "saldo_tecnico", "otros_creditos")):
                out.append(fila)
    return out


def analizar_sld(tablas: list[dict]) -> list[dict]:
    """Filas con S.L.D. > 0 (saldo de libre disponibilidad) de los conceptos que NO son IVA. Pedido de Gaby 19/11/2026:
    cuando el cliente paga mal (dos veces, período equivocado) el saldo queda en la columna S.L.D. del concepto,
    sobre todo en cargas sociales (301, 302, 312, 351, 352, 28...). Se recupera reimputándolo con el F.399 a otros
    períodos que se deban. El IVA queda afuera: se compensa con el procedimiento estándar de la página."""
    out = []
    for t in tablas:
        cab = [c.upper() for c in t.get("cab") or []]
        i_s = next((i for i, c in enumerate(cab) if c.replace(" ", "").startswith("S.L.D")), None)
        if i_s is None:
            continue
        i_p = next((i for i, c in enumerate(cab) if c.startswith("PER")), 1)
        i_c = next((i for i, c in enumerate(cab) if c.startswith("CONCEPTO")), 2)
        m = re.match(r"(\d+)\s*-\s*(.+)", t.get("titulo") or "")
        imp, nombre = (m[1], m[2].strip()) if m else ("", t.get("titulo") or "")
        if imp == IVA:
            continue
        for f in t.get("filas") or []:
            c = f["celdas"]
            if len(c) <= i_s or not re.fullmatch(r"\d{8}", c[i_p] if len(c) > i_p else ""):
                continue
            sld = _num(c[i_s]) or 0.0
            if sld <= 0:
                continue
            out.append({"impuesto": imp, "nombre": nombre, "periodo": c[i_p], "concepto": c[i_c] if len(c) > i_c else "",
                        "sld": round(sld, 2), "f931": imp in F931})
    return out


def _en_frames(page, fn):
    """Primer resultado no vacío de fn(frame) en la página y sus marcos (la SCT usa iframes)."""
    for fr in [page.main_frame] + [f for f in page.frames if f is not page.main_frame]:
        try:
            r = fn(fr)
        except Exception:
            r = None
        if r:
            return r
    return None


def _clic_texto(page, patron: str, espera_s: int = 40) -> None:
    limite = page.evaluate("Date.now()") + espera_s * 1000
    while page.evaluate("Date.now()") < limite:
        loc = _en_frames(page, lambda fr: (lambda l: l if l.count() else None)(
            fr.get_by_text(re.compile(patron, re.I)).locator("visible=true")))
        if loc:
            loc.first.click()
            return
        page.wait_for_timeout(1000)
    raise arca.ErrorRobot(f"Cuentas Tributarias: no aparece '{patron}'")


def _marco_con(page, patron: str, espera_s: int = 60):
    limite = page.evaluate("Date.now()") + espera_s * 1000
    while page.evaluate("Date.now()") < limite:
        fr = _en_frames(page, lambda f: f if re.search(patron, f.locator("body").inner_text(timeout=3000), re.I) else None)
        if fr:
            return fr
        page.wait_for_timeout(1000)
    raise arca.ErrorRobot(f"Cuentas Tributarias: no aparece '{patron}'")


def _esperar_carga(fr, page) -> None:
    for _ in range(90):
        try:
            if not fr.get_by_text(re.compile(r"^\s*CARGANDO", re.I)).locator("visible=true").count():
                return
        except Exception:
            return
        page.wait_for_timeout(1000)


class Trabada(Exception):
    """La consulta no terminó de cargar (la SCT se cuelga, sobre todo al pasar de año)."""


def _hay_marco(page, patron: str):
    return _en_frames(page, lambda f: f if re.search(patron, f.locator("body").inner_text(timeout=3000), re.I) else None)


def _ir_a_parametros(page):
    """Lleva al 'Ingreso de Parámetros' del estado de cumplimiento. Arreglo 20/11/2026 (error "no aparece 'Ingreso de
    Parámetros'" en la 2ª consulta): estando en 'Mostrar Consulta', volver a tocar ESTADO DE CUMPLIMIENTO en el menú no
    hace nada (misma pantalla); hay que tocar VOLVER. Orden: ya está -> VOLVER -> menú -> recargar y menú."""
    fr = _hay_marco(page, r"Ingreso de Par[aá]metros")
    if fr:
        return fr

    def menu():
        try:
            _clic_texto(page, r"^\s*ESTADO DE CUMPLIMIENTO\s*$", espera_s=15)
        except arca.ErrorRobot:                        # menú plegado: se abre "CUENTA CORRIENTE"
            _clic_texto(page, r"^\s*CUENTA CORRIENTE\s*$")
            _clic_texto(page, r"^\s*ESTADO DE CUMPLIMIENTO\s*$")

    def volver():
        fr_c = _hay_marco(page, r"Mostrar Consulta|Per[ií]odo Fiscal consultado")
        if fr_c:
            b = fr_c.get_by_text(re.compile(r"^\s*VOLVER\s*$", re.I)).locator("visible=true")
            if b.count():
                b.first.click()
                return
        raise arca.ErrorRobot("sin botón VOLVER")

    for paso_ in (volver, menu, lambda: (page.reload(wait_until="domcontentloaded"), page.wait_for_timeout(3000), menu())):
        try:
            paso_()
        except Exception:
            continue
        try:
            return _marco_con(page, r"Ingreso de Par[aá]metros", espera_s=25)
        except arca.ErrorRobot:
            continue
    arca.verificar_sesion(page, "cuentas_tributarias")      # si se cortó la sesión, el robot vuelve a entrar
    raise Trabada("no aparece 'Ingreso de Parámetros'")


_JS_CAMPOS = r"""() => {
  // inputs que siguen a los textos 'Período Fiscal Desde' / 'Período Fiscal Hasta' (en ARCA la etiqueta no está
  // ligada al input: se busca el primer input visible que viene DESPUÉS del texto en el documento)
  const vis = e => e.offsetParent !== null;
  const inputs = [...document.querySelectorAll('input')].filter(i => vis(i) && !['checkbox','radio','hidden','button','submit'].includes(i.type));
  inputs.forEach((i, n) => i.setAttribute('data-robot-in', String(n)));
  const etiquetas = [...document.querySelectorAll('label, span, div, td, p, mat-label')].filter(e => vis(e) &&
      e.children.length === 0 && /per[ií]odo\s+fiscal\s+(desde|hasta)/i.test(e.textContent));
  const sig = (et) => inputs.find(i => et.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING);
  const out = {};
  for (const et of etiquetas) {
    const k = /desde/i.test(et.textContent) ? 'desde' : 'hasta';
    const i = sig(et);
    if (i && !out[k]) out[k] = {n: Number(i.getAttribute('data-robot-in')), max: i.maxLength};
  }
  if (!out.desde || !out.hasta) {             // respaldo: por name / id / placeholder
    for (const i of inputs) {
      const t = [i.name, i.id, i.placeholder, i.getAttribute('formcontrolname'), i.getAttribute('aria-label')].join(' ').toLowerCase();
      const n = Number(i.getAttribute('data-robot-in'));
      if (!out.desde && /desde/.test(t)) out.desde = {n, max: i.maxLength};
      if (!out.hasta && /hasta/.test(t)) out.hasta = {n, max: i.maxLength};
    }
  }
  return out;
}"""


def _campos_periodo(fr):
    """Campos 'Período Fiscal Desde' / 'Período Fiscal Hasta' del Ingreso de Parámetros (captura de Gaby 20/11/2026).
    Devuelve (desde, hasta) o None."""
    try:
        out = fr.evaluate(_JS_CAMPOS)
    except Exception:
        return None
    if not out.get("desde") or not out.get("hasta") or out["desde"]["n"] == out["hasta"]["n"]:
        return None
    return out["desde"], out["hasta"]


def _select_impuesto(fr):
    sel = fr.locator("select").filter(has=fr.locator("option", has_text=re.compile(r"^\s*\d+\s*-\s*\S")))
    return sel.first if sel.count() else None


_RE_OPCION = re.compile(r"^\s*(\d+)\s*-\s*\S")


def _combo_impuesto(fr):
    """El combo 'Impuesto' de ARCA es un desplegable con buscador (no un <select> común): el elemento que muestra
    'Todos' o el impuesto elegido, debajo del texto 'Impuesto'."""
    return fr.locator("xpath=//*[normalize-space(text())='Impuesto']/following::*[contains(@class,'select') or "
                      "@role='combobox' or contains(@class,'ng-select') or contains(@class,'mat-select')][1]").first


def _opciones_visibles(fr) -> list:
    return [t.strip() for t in fr.locator("li, [role=option], .ng-option, mat-option").locator("visible=true").all_inner_texts()
            if _RE_OPCION.match(t.strip())]


def impuestos_disponibles(fr) -> list[str]:
    """Opciones del combo Impuesto ('11 - GANANCIAS PERSONAS FISICAS', '28 - SEGURO DE VIDA COLECTIVO', '30 - IVA'...):
    son los impuestos del cliente (sus inscripciones). Devuelve los códigos."""
    sel = _select_impuesto(fr)
    if sel is not None:
        return [m[1] for o in sel.locator("option").all_inner_texts() if (m := _RE_OPCION.match(o))]
    try:                                               # desplegable con buscador: se abre, se leen y se cierra
        combo = _combo_impuesto(fr)
        combo.click(timeout=10_000)
        fr.page.wait_for_timeout(800) if hasattr(fr, "page") else None
        ops = _opciones_visibles(fr)
        fr.locator("body").press("Escape")
        return [m[1] for o in ops if (m := _RE_OPCION.match(o))]
    except Exception:
        return []


def _elegir_impuesto(fr, impuesto: str) -> bool:
    sel = _select_impuesto(fr)
    if sel is not None:
        op = next((o for o in sel.locator("option").all_inner_texts() if re.match(rf"\s*0*{impuesto}\s*-", o)), None)
        if not op:
            return False
        sel.select_option(label=op, force=True)
        sel.evaluate("s => { s.dispatchEvent(new Event('change', {bubbles: true})); if (window.jQuery) jQuery(s).trigger('change'); }")
        return True
    try:                                               # desplegable con buscador
        _combo_impuesto(fr).click(timeout=10_000)
        op = fr.locator("li, [role=option], .ng-option, mat-option").locator("visible=true").filter(
            has_text=re.compile(rf"^\s*0*{impuesto}\s*-"))
        if not op.count():
            fr.locator("body").press("Escape")
            return False
        op.first.click()
        return True
    except Exception:
        return False


_RE_SIN_DATOS = re.compile(r"no (se encontraron|se encontr[oó]|existen|hay|registra)[^.\n]{0,60}"
                           r"(datos|movimientos|informaci[oó]n|resultados|deudas?|registros)", re.I)
_RE_AVISO = re.compile(r"[^\n]{0,60}(inv[aá]lid|incorrect|obligatori|debe ingresar|debe ser|no puede ser|no es v[aá]lid|"
                       r"posterior|anterior al|mayor que|menor que|error)[^\n]{0,120}", re.I)


def _texto_visible(fr) -> str:
    try:
        return fr.locator("body").inner_text(timeout=3000)
    except Exception:
        return ""


ESPERA_SIGUIENTE = 60


def _esperar_resultado(page, fr_par, base: set, espera_s: int | None = None):
    """Después de SIGUIENTE: ('ok', None) si apareció la consulta; ('vacio', texto) si ARCA dice que no hay datos;
    ('aviso', texto) si quedó en Ingreso de Parámetros con un mensaje (formato de período, etc.); ('nada', texto) si
    no pasó nada. Error 21/11/2026 (Goncalves): "no aparece 'Período Fiscal consultado'" -> antes el robot esperaba 90 s
    solo esa pantalla y cortaba toda la corrida."""
    limite = time.time() + (espera_s or ESPERA_SIGUIENTE)
    ultimo = ""
    while time.time() < limite:
        if _hay_marco(page, r"Per[ií]odo Fiscal consultado"):
            return "ok", None
        for f in page.frames:
            m = _RE_SIN_DATOS.search(_texto_visible(f))
            if m:
                return "vacio", m.group(0)
        txt = _texto_visible(fr_par)
        avisos = [m.group(0).strip() for m in _RE_AVISO.finditer(txt) if m.group(0).strip() not in base]
        try:                                            # cartel modal (SweetAlert / bootstrap) en cualquier marco
            for f in page.frames:
                d = f.locator("[role=dialog], [role=alertdialog], .modal.show, .swal2-popup, .alert-danger, .ui-dialog")
                d = d.locator("visible=true")
                if d.count():
                    avisos.append(d.first.inner_text(timeout=2000).strip())
        except Exception:
            pass
        if avisos:
            return "aviso", " / ".join(a for a in avisos if a)[:200]
        ultimo = txt
        page.wait_for_timeout(1000)
    return "nada", ultimo[-200:]


def _cargar_campo(fr, x: dict, valor: str) -> None:
    """El campo de ARCA tiene máscara: se escribe tecla por tecla y se controla que haya quedado el valor."""
    loc = fr.locator(f"[data-robot-in='{x['n']}']")
    loc.click()
    loc.fill("")
    loc.press_sequentially(valor, delay=40)
    try:
        loc.press("Tab")
    except Exception:
        pass
    if re.sub(r"\D", "", loc.input_value()) != valor:
        loc.evaluate("(i, v) => { i.value = v; ['input','change','blur'].forEach(t => i.dispatchEvent(new Event(t, {bubbles: true}))); }",
                     valor)


def _clic_siguiente(fr) -> None:
    for loc in (fr.get_by_role("button", name=re.compile(r"SIGUIENTE", re.I)),
                fr.get_by_text(re.compile(r"^\s*SIGUIENTE\s*$", re.I)),
                fr.locator("input[type=button][value*=SIGUIENTE i], input[type=submit][value*=SIGUIENTE i]")):
        v = loc.locator("visible=true")
        if v.count():
            v.first.click()
            return
    fr.get_by_text(re.compile(r"^\s*SIGUIENTE\s*$", re.I)).first.click()


def _rangos(anio: int, hoy: date) -> list[tuple[str, str]]:
    """Formatos a probar (la pantalla acepta 'AAAAMMDD o AAAAMM00 o AAAA0000'): primero el del año entero que usa ARCA;
    si no lo toma, 01/01 a 31/12; para el año en curso, hasta el mes actual."""
    r = [(f"{anio}0000", f"{anio}1200"), (f"{anio}0101", f"{anio}1231")]
    if anio == hoy.year:
        r.append((f"{anio}0000", f"{anio}{hoy.month:02d}00"))
    return r


def _guardar_pantalla(page, fr, cuit: str, nombre: str) -> None:
    try:
        d = os.path.join(DATOS, cuit, "capturas")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, nombre + ".html"), "w", encoding="utf-8") as f:
            f.write(fr.content())
        page.screenshot(path=os.path.join(d, nombre + ".png"), full_page=True)
    except Exception:
        pass


def _consultar(page, cuit: str, anio: int, impuesto: str | None = None) -> dict | None:
    """Consulta NUEVA de un año y un impuesto: Período Fiscal Desde AAAA0000 / Hasta AAAA1200 (formato AAAAMMDD, el
    mismo rango que usa ARCA para el año: 'Período Fiscal consultado 20260000 a 20261200'). Pedido de Gaby 20/11/2026:
    por año y por impuesto no se cuelga y es más rápido. None = la pantalla no tiene esos campos.
    21/11/2026: si tras SIGUIENTE no aparece la consulta se lee el mensaje de ARCA, se prueban los otros formatos de
    período y, si nada anda, queda PENDIENTE con el motivo (no corta la corrida) y se guarda la pantalla."""
    motivo = ""
    for desde, hasta in _rangos(anio, date.today()):
        arca.verificar_sesion(page, "cuentas_tributarias")    # cada consulta: que la sesión siga abierta (Gaby 20/11)
        fr = _ir_a_parametros(page)
        campos = _campos_periodo(fr)
        if not campos:
            return None
        _cargar_campo(fr, campos[0], desde)
        _cargar_campo(fr, campos[1], hasta)
        if impuesto and not _elegir_impuesto(fr, impuesto):
            return {"anio": str(anio), "impuesto": impuesto, "estado": "sin ese impuesto en el selector"}
        base = {m.group(0).strip() for m in _RE_AVISO.finditer(_texto_visible(fr))}   # textos que ya estaban
        _clic_siguiente(fr)
        estado, texto = _esperar_resultado(page, fr, base)
        arca.verificar_sesion(page, "cuentas_tributarias")
        if estado == "vacio":
            return {"anio": str(anio), "impuesto": impuesto, "estado": "OK", "sin_datos": texto,
                    "fecha_lectura": date.today().isoformat(), "totales": {}, "deudas": [], "saldos_sld": [],
                    "movimientos": [], "impuestos": []}
        if estado == "ok":
            r = _leer_consulta(page, cuit, str(anio))      # controla año y CUIT (mismo contribuyente)
            r["fecha_lectura"] = date.today().isoformat()
            if impuesto:                                     # cada vez: que la consulta sea del impuesto pedido
                otros = [t for t in r["impuestos"] if not re.match(rf"\s*0*{impuesto}\s*-", t)]
                if otros:
                    raise Trabada(f"se pidió el impuesto {impuesto} y la pantalla muestra {', '.join(otros)[:80]}")
            return r
        motivo = f"{desde}-{hasta}: " + (f"ARCA dice «{texto}»" if estado == "aviso" else "no respondió a SIGUIENTE")
        _guardar_pantalla(page, fr, cuit, f"sct_siguiente_{anio}_{impuesto or 'todos'}")
    raise Trabada(f"no apareció la consulta ({motivo})")


def _leer_consulta(page, cuit: str, anio_esperado: str | None = None) -> dict:
    fr = _marco_con(page, r"Per[ií]odo Fiscal consultado", espera_s=90)
    for _ in range(ESPERA_CARGA):                       # CARGANDO: si no termina, está trabada
        try:
            if not fr.get_by_text(re.compile(r"^\s*CARGANDO", re.I)).locator("visible=true").count():
                break
        except Exception:
            break
        page.wait_for_timeout(1000)
    else:
        raise Trabada("la consulta quedó cargando")
    texto = fr.locator("body").inner_text()
    tot = leer_totales(texto)
    if anio_esperado and tot["desde"][:4] != anio_esperado:
        raise Trabada(f"se pidió {anio_esperado} y la pantalla muestra {tot['desde'][:4] or 'otro período'}")
    if arca.cuit_fmt(cuit) not in texto:
        otros = sorted(set(re.findall(r"\d{2}-\d{8}-\d", texto)) - {arca.cuit_fmt(cuit)})
        raise arca.CuitEquivocado(f"Estado de cumplimiento: muestra {', '.join(otros) or 'otro CUIT'}")
    tablas = fr.evaluate(JS_TABLAS)
    return {"anio": tot["desde"][:4], "totales": tot, "deudas": analizar(tablas), "saldos_sld": analizar_sld(tablas),
            "movimientos": analizar_movimientos(tablas), "impuestos": [t["titulo"] for t in tablas], "estado": "OK"}


def _ruta_parcial(cuit: str) -> str:
    return os.path.join(DATOS, cuit, "sct_historico", "_parcial.json")


def _parcial(cuit: str) -> dict:
    try:
        with open(_ruta_parcial(cuit), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _guardar_parcial(cuit: str, p: dict) -> None:
    os.makedirs(os.path.dirname(_ruta_parcial(cuit)), exist_ok=True)
    with open(_ruta_parcial(cuit), "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=1)


def leer_anios(page, cuit: str, anios: int = ANIOS, hoy: date | None = None) -> dict:
    """Pedido de Gaby 20/11/2026 (la SCT se colgaba al pasar de año y el robot terminaba en falla):
      - consulta NUEVA por año (Período Fiscal Desde AAAA0000 / Hasta AAAA1200) y por impuesto (los del combo
        Impuesto, que son las inscripciones del cliente); cada vez se controla año, impuesto y CUIT;
      - si una consulta se traba se recarga (sin reloguear) y se reintenta; si sigue trabada queda PENDIENTE y se
        sigue con la próxima;
      - se guarda cada impuesto y año al terminarlo (_parcial.json); la corrida siguiente retoma solo lo pendiente
        (el año en curso se lee siempre de nuevo);
      - si la pantalla de parámetros no tuviera esos campos, se usa el recorrido viejo con AÑO ANTERIOR.
    Devuelve {"anios": [...], "pendientes": [...], "leidos": [...]}."""
    from datetime import timedelta
    hoy = hoy or date.today()
    actual = hoy.year
    objetivo = list(range(actual, actual - anios, -1))
    par = _parcial(cuit)
    if par.get("fecha", "")[:7] < (hoy.replace(day=1) - timedelta(days=40)).isoformat()[:7]:
        par = {}                                        # lo guardado tiene más de un mes: se lee todo de nuevo
    viejos = par.get("partes") or {}                    # {"2025|312": {...}} consultas que salieron bien
    # se conservan las consultas buenas de años anteriores y las del año en curso hechas HOY (si ARCA corta la sesión
    # y el robot vuelve a entrar, retoma desde donde quedó sin repetir lo ya leído)
    partes = {k: v for k, v in viejos.items() if v.get("estado") == "OK"
              and (not k.startswith(f"{actual}|") or v.get("fecha_lectura") == hoy.isoformat())}
    par = {"fecha": hoy.isoformat(), "partes": dict(partes), "pendientes": []}
    pendientes = []

    def guardar():
        par["pendientes"] = pendientes
        _guardar_parcial(cuit, par)

    def intentar(fn):
        r = None
        for _ in range(2):
            try:
                return fn()
            except (arca.SesionPerdida, arca.ClaveInvalida, arca.RequiereIntervencion):
                raise
            except (Trabada, arca.ErrorRobot) as e:
                r = {"estado": f"trabada: {e}"}
                try:
                    page.reload(wait_until="domcontentloaded")    # recargar sin reloguear
                    page.wait_for_timeout(3000)
                except Exception:
                    pass
        return r

    try:
        fr = _ir_a_parametros(page)
    except Trabada:
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        try:
            fr = _ir_a_parametros(page)
        except Trabada as e:
            raise arca.ErrorRobot(f"Cuentas Tributarias: {e}")
    impuestos = impuestos_disponibles(fr)
    directo = _campos_periodo(fr) is not None
    if not directo or not impuestos:                    # para ajustar el robot: se guarda cómo vino la pantalla
        try:
            os.makedirs(os.path.join(DATOS, cuit, "capturas"), exist_ok=True)
            with open(os.path.join(DATOS, cuit, "capturas", "sct_parametros.html"), "w", encoding="utf-8") as f:
                f.write(fr.content())
        except Exception:
            pass
    for anio in objetivo:
        if not directo:
            # 20/11/2026: sin campos de período reconocibles NO se usa AÑO ANTERIOR (se cuelga): solo el año en curso
            # (lo que ARCA consulta si no se cargan períodos); los demás años quedan pendientes con el motivo.
            k = f"{anio}|todos"
            if k in partes:
                continue
            if anio != actual:
                pendientes.append({"anio": str(anio), "motivo": "no se reconocieron los campos de período en la pantalla",
                                   "impuestos": []})
                guardar()
                continue
            r = intentar(lambda: _por_anio_anterior(page, cuit, anio))
            if r and r.get("estado") == "OK":
                partes[k] = par["partes"][k] = r
            else:
                pendientes.append({"anio": str(anio), "motivo": (r or {}).get("estado", "sin datos"), "impuestos": []})
            guardar()
            continue
        for imp in impuestos or [None]:
            k = f"{anio}|{imp or 'todos'}"
            if k in partes:
                continue
            r = intentar(lambda: _consultar(page, cuit, anio, imp))
            if r and r.get("estado") == "OK":
                partes[k] = par["partes"][k] = r
            elif r and "sin ese impuesto" in r.get("estado", ""):
                pass
            else:
                pendientes.append({"anio": str(anio), "impuesto": imp, "motivo": (r or {}).get("estado", "sin datos")})
            guardar()                                    # se guarda cada impuesto y año al terminarlo
            arca.pausa(0.5, 1.2)
    anios_ok = []
    for anio in objetivo:
        ps = [v for k, v in partes.items() if k.startswith(f"{anio}|")]
        if not ps:
            continue
        pend_anio = [p for p in pendientes if p["anio"] == str(anio)]
        tot = {}
        for clave in ("deuda", "sld", "saldo_tecnico", "otros_creditos", "multas_no_firmes"):
            vals = [(x.get("totales") or {}).get(clave) for x in ps]
            tot[clave] = round(sum(v for v in vals if v is not None), 2) if any(v is not None for v in vals) else None
        tot["desde"], tot["hasta"] = f"{anio}0000", f"{anio}1200"
        anios_ok.append({"anio": str(anio), "totales": tot,
                         "estado": "OK" if not pend_anio else "parcial",
                         "deudas": [d for x in ps for d in x.get("deudas", [])],
                         "saldos_sld": [d for x in ps for d in x.get("saldos_sld", [])],
                         "movimientos": [d for x in ps for d in x.get("movimientos", [])],
                         "impuestos": [t for x in ps for t in x.get("impuestos", [])]})
    # pendientes agrupados por año para la ficha: {"anio", "impuestos": [...]}
    agrup = {}
    for p in pendientes:
        g = agrup.setdefault(p["anio"], {"anio": p["anio"], "motivo": p.get("motivo", ""), "impuestos": []})
        if p.get("impuesto"):
            g["impuestos"].append(p["impuesto"])
    return {"anios": anios_ok, "pendientes": list(agrup.values()),
            "leidos": [a["anio"] + ("" if a["estado"] == "OK" else " (parcial)") for a in anios_ok],
            "impuestos_consultados": impuestos}


def _por_anio_anterior(page, cuit: str, anio: int) -> dict:
    """Recorrido viejo (sin campos de período): consulta del año en curso y AÑO ANTERIOR hasta llegar al año."""
    fr = _ir_a_parametros(page)
    fr.get_by_text(re.compile(r"^\s*SIGUIENTE\s*$", re.I)).first.click()
    r = _leer_consulta(page, cuit)
    while int(r["anio"] or 0) > anio:
        fr = _marco_con(page, r"Per[ií]odo Fiscal consultado")
        boton = fr.get_by_text(re.compile(r"A[ÑN]O ANTERIOR", re.I)).locator("visible=true")
        if not boton.count():
            raise Trabada("no hay botón AÑO ANTERIOR visible")
        antes = r["anio"]
        boton.first.click()
        page.wait_for_timeout(2500)
        r = _leer_consulta(page, cuit)
        if r["anio"] == antes:
            raise Trabada("el botón AÑO ANTERIOR no avanzó")
    if r["anio"] != str(anio):
        return {"anio": str(anio), "estado": "no está ese año"}
    return r


def resumir(res: dict) -> dict:
    res.setdefault("pendientes", [])
    filas = [dict(f, anio=a["anio"]) for a in res["anios"] for f in a["deudas"]]
    por_imp = {}
    for f in filas:
        k = f"{f['impuesto']} - {f['nombre']}"
        por_imp[k] = round(por_imp.get(k, 0.0) + f["deuda"], 2)
    res["deudas"] = filas
    res["por_impuesto"] = por_imp
    res["deuda_total"] = round(sum(f["deuda"] for f in filas), 2)
    res["deuda_terceros"] = round(sum(f["deuda"] for f in filas if f["color"] == "verde"), 2)
    res["deuda_arca"] = round(res["deuda_total"] - res["deuda_terceros"], 2)
    res["deuda_f931_otros"] = round(sum(f["deuda"] for f in filas if f["f931"] and f["impuesto"] not in ("301", "351")), 2)
    al = []
    if filas:
        txt = lambda x: f"$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        anios = sorted({f["anio"] for f in filas})
        al.append({"prioridad": "ALTA", "tipo": "Deuda en Cuentas Tributarias (estado de cumplimiento)",
                   "texto": f"{txt(res['deuda_total'])} en {len(por_imp)} impuesto(s), años {', '.join(anios)}"
                            + f" (propia de ARCA {txt(res['deuda_arca'])}; para terceros —obras sociales, ART, seguro de vida— "
                              f"{txt(res['deuda_terceros'])})"})
    sld = [dict(f, anio=a["anio"]) for a in res["anios"] for f in a.get("saldos_sld") or []]
    res["saldos_recuperar"] = sorted(sld, key=lambda f: (f["impuesto"], f["periodo"]))
    res["saldos_recuperar_total"] = round(sum(f["sld"] for f in sld), 2)
    if sld:
        txt = lambda x: f"$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        det = "; ".join(f"{f['impuesto']} {f['periodo'][4:6]}/{f['periodo'][:4]} {txt(f['sld'])}" for f in res["saldos_recuperar"][:8])
        otros = "; ".join(f"{k} {txt(v)}" for k, v in sorted(por_imp.items(), key=lambda x: -x[1])[:6] if v)
        al.append({"prioridad": "ALTA", "tipo": "Saldos a recuperar (S.L.D.) — F.399",
                   "texto": f"Pago en demasía, reimputable por F.399: {txt(res['saldos_recuperar_total'])} en {len(sld)} "
                            f"período(s) ({det}{'…' if len(sld) > 8 else ''})."
                            + (f" Deuda en otros impuestos para imputarlo: {otros}." if otros else " No hay deuda donde imputarlo hoy.")})
    res["alertas"] = al
    return res


def paso(cuit: str, estado: dict, anios: int = ANIOS):
    def fn(ctx, portal):
        from .robot_situacion_fiscal import _elegir_cuit_sct
        page = arca.abrir_servicio(ctx, portal, "cuentas_tributarias")
        page.wait_for_load_state("domcontentloaded")
        _elegir_cuit_sct(page, cuit, None)
        try:
            res = resumir(leer_anios(page, cuit, anios))
        finally:
            page.close()
        hoy = date.today().isoformat()
        res.update(cuit=cuit, fecha=hoy)
        d = os.path.join(DATOS, cuit, "sct_historico")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy}.json"), "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        r = f"{len(res['anios'])} años, deuda $ {res['deuda_total']:,.2f}"
        if res.get("pendientes"):
            r += " — PENDIENTE: " + ", ".join(p["anio"] + (f" ({', '.join(p['impuestos'])})" if p.get("impuestos") else "")
                                             for p in res["pendientes"]) + " (se retoma en la próxima corrida)"
        estado.update(resultado=r, alertas=res["alertas"])
        return r
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    from . import robot_situacion_fiscal as rsf
    rsf.USUARIO_ACTUAL["cuit"], rsf.USUARIO_ACTUAL["cliente"] = usuario, cuit
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("sct_historico", paso(cuit, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "sct_historico": estado.get("resultado"),
            "archivos": {"sct_historico": {"alertas": estado.get("alertas", [])}}}
