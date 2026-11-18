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
from datetime import date

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
ANIOS = 6                                   # año en curso + 5 anteriores
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


def leer_anios(page, cuit: str, anios: int = ANIOS) -> dict:
    try:
        _clic_texto(page, r"^\s*ESTADO DE CUMPLIMIENTO\s*$", espera_s=15)
    except arca.ErrorRobot:                            # menú plegado: se abre "CUENTA CORRIENTE"
        _clic_texto(page, r"^\s*CUENTA CORRIENTE\s*$")
        _clic_texto(page, r"^\s*ESTADO DE CUMPLIMIENTO\s*$")
    fr = _marco_con(page, r"Ingreso de Par[aá]metros")
    fr.get_by_text(re.compile(r"^\s*SIGUIENTE\s*$", re.I)).first.click()
    res = {"anios": []}
    anterior = None
    for _ in range(anios):
        fr = _marco_con(page, r"Per[ií]odo Fiscal consultado")
        _esperar_carga(fr, page)
        texto = fr.locator("body").inner_text()
        tot = leer_totales(texto)
        if tot["desde"] == anterior:                   # el botón no avanzó: se espera un poco más
            page.wait_for_timeout(4000)
            texto = fr.locator("body").inner_text()
            tot = leer_totales(texto)
            if tot["desde"] == anterior:
                break
        if arca.cuit_fmt(cuit) not in texto:
            otros = sorted(set(re.findall(r"\d{2}-\d{8}-\d", texto)) - {arca.cuit_fmt(cuit)})
            raise arca.CuitEquivocado(f"Estado de cumplimiento: muestra {', '.join(otros) or 'otro CUIT'}")
        tablas = fr.evaluate(JS_TABLAS)
        res["anios"].append({"anio": tot["desde"][:4], "totales": tot, "deudas": analizar(tablas),
                             "impuestos": [t["titulo"] for t in tablas]})
        anterior = tot["desde"]
        boton = fr.get_by_text(re.compile(r"A[ÑN]O ANTERIOR", re.I))
        if not boton.count():
            break
        boton.first.click()
        page.wait_for_timeout(2500)
    return res


def resumir(res: dict) -> dict:
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
