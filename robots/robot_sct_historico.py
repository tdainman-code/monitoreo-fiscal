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


def _ir_a_parametros(page):
    try:
        _clic_texto(page, r"^\s*ESTADO DE CUMPLIMIENTO\s*$", espera_s=15)
    except arca.ErrorRobot:                            # menú plegado: se abre "CUENTA CORRIENTE"
        _clic_texto(page, r"^\s*CUENTA CORRIENTE\s*$")
        _clic_texto(page, r"^\s*ESTADO DE CUMPLIMIENTO\s*$")
    return _marco_con(page, r"Ingreso de Par[aá]metros")


def _campos_periodo(fr):
    """Campos 'período desde' / 'período hasta' del Ingreso de Parámetros, si se reconocen (por name, id,
    placeholder o el texto de al lado). Devuelve (desde, hasta) o None. Pantalla a confirmar con captura."""
    try:
        info = fr.evaluate("""() => [...document.querySelectorAll('input[type=text], input:not([type]), input[type=number]')]
            .filter(i => i.offsetParent).map((i, n) => {
              const lab = (i.labels && i.labels[0] ? i.labels[0].innerText : '') + ' ' + (i.closest('td,div,label') || {}).innerText;
              i.setAttribute('data-robot-in', String(n));
              return {n, txt: [i.name, i.id, i.placeholder, lab].join(' ').toLowerCase(), max: i.maxLength};
            })""")
    except Exception:
        return None
    desde = next((x for x in info if re.search(r"desde|inicio|inicial", x["txt"]) and re.search(r"per", x["txt"])), None)
    hasta = next((x for x in info if re.search(r"hasta|fin(al)?\b", x["txt"]) and re.search(r"per", x["txt"])), None)
    if not desde or not hasta:
        return None
    return desde, hasta


def _elegir_impuesto(fr, impuesto: str) -> bool:
    sel = fr.locator("select").filter(has=fr.locator("option", has_text=re.compile(rf"^\s*0*{impuesto}\b")))
    if not sel.count():
        return False
    op = next((o for o in sel.first.locator("option").all_inner_texts() if re.match(rf"\s*0*{impuesto}\b", o)), None)
    sel.first.select_option(label=op)
    return True


def _consultar(page, cuit: str, anio: int, impuesto: str | None = None) -> dict | None:
    """Consulta NUEVA de un año (y opcionalmente un impuesto) eligiendo el período directo. None = la pantalla de
    parámetros no tiene campos de período reconocibles (se usa el recorrido con AÑO ANTERIOR)."""
    fr = _ir_a_parametros(page)
    campos = _campos_periodo(fr)
    if not campos:
        return None
    for x, mes in ((campos[0], "01"), (campos[1], "12")):
        valor = f"{anio}{mes}" if x["max"] in (6, -1, 524288) or x["max"] < 8 else f"{anio}{mes}00"
        fr.locator(f"[data-robot-in='{x['n']}']").fill(valor)
    if impuesto and not _elegir_impuesto(fr, impuesto):
        return {"anio": str(anio), "impuesto": impuesto, "estado": "sin ese impuesto en el selector"}
    fr.get_by_text(re.compile(r"^\s*SIGUIENTE\s*$", re.I)).first.click()
    return _leer_consulta(page, cuit, str(anio))


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
      - cada año es una consulta NUEVA eligiendo el período directo (no el botón AÑO ANTERIOR); si la pantalla de
        parámetros no tiene campos de período reconocibles, se usa el recorrido con AÑO ANTERIOR como antes;
      - si un año se traba se recarga la consulta (sin reloguear) y se reintenta; si se traba con todos los
        impuestos juntos se pide impuesto por impuesto; lo que no sale queda PENDIENTE y se sigue;
      - cada año se guarda al terminarlo (_parcial.json); la próxima corrida retoma solo lo pendiente
        (el año en curso se lee siempre de nuevo).
    Devuelve {"anios": [...], "pendientes": [...], "leidos": [...]}."""
    hoy = hoy or date.today()
    actual = hoy.year
    objetivo = list(range(actual, actual - anios, -1))
    par = _parcial(cuit)
    if par.get("fecha", "")[:7] < (hoy.replace(day=1) - __import__("datetime").timedelta(days=40)).isoformat()[:7]:
        par = {}                                        # lo guardado tiene más de un mes: se lee todo de nuevo
    hechos = {a: v for a, v in (par.get("anios") or {}).items() if v.get("estado") == "OK" and int(a) != actual}
    par = {"fecha": hoy.isoformat(), "anios": dict(hechos), "pendientes": []}
    pendientes = []
    directo = None                                       # None = todavía no se sabe si hay campos de período
    for anio in objetivo:
        if str(anio) in hechos:
            continue
        r = None
        for intento in range(2):
            try:
                if directo is not False:
                    r = _consultar(page, cuit, anio)
                    if r is None:
                        directo = False
                    else:
                        directo = True
                if directo is False:
                    r = _por_anio_anterior(page, cuit, anio)
                break
            except Trabada as e:
                r = {"anio": str(anio), "estado": f"trabada: {e}"}
                try:
                    page.reload(wait_until="domcontentloaded")    # recargar sin reloguear
                    page.wait_for_timeout(3000)
                except Exception:
                    pass
        if r and r.get("estado") != "OK" and directo:          # todos juntos no sale: de a un impuesto
            imps = sorted({re.match(r"(\d+)", t)[1] for v in par["anios"].values() for t in v.get("impuestos") or []
                           if re.match(r"\d+", t)} | set(F931))
            partes, faltan = [], []
            for imp in imps:
                try:
                    x = _consultar(page, cuit, anio, imp)
                    if x and x.get("estado") == "OK":
                        partes.append(x)
                    elif x and "sin ese impuesto" not in x.get("estado", ""):
                        faltan.append(imp)
                except Trabada:
                    faltan.append(imp)
                    try:
                        page.reload(wait_until="domcontentloaded")
                    except Exception:
                        pass
            if partes:
                r = {"anio": str(anio), "totales": partes[0]["totales"], "estado": "OK" if not faltan else "parcial",
                     "deudas": [d for x in partes for d in x["deudas"]], "saldos_sld": [d for x in partes for d in x["saldos_sld"]],
                     "movimientos": [d for x in partes for d in x.get("movimientos", [])],
                     "impuestos": [t for x in partes for t in x["impuestos"]], "impuestos_pendientes": faltan}
        if not r or r.get("estado") != "OK":
            pendientes.append({"anio": str(anio), "motivo": (r or {}).get("estado", "sin datos"),
                               "impuestos": (r or {}).get("impuestos_pendientes", [])})
        if r and r.get("deudas") is not None:
            par["anios"][str(anio)] = r
        par["pendientes"] = pendientes
        _guardar_parcial(cuit, par)                      # se guarda año por año
        arca.pausa(1.0, 2.0)
    anios_ok = [par["anios"][str(a)] for a in objetivo if str(a) in par["anios"]]
    return {"anios": anios_ok, "pendientes": pendientes,
            "leidos": [a["anio"] + ("" if a.get("estado") == "OK" else " (parcial)") for a in anios_ok]}


def _por_anio_anterior(page, cuit: str, anio: int) -> dict:
    """Recorrido viejo (sin campos de período): consulta del año en curso y AÑO ANTERIOR hasta llegar al año."""
    fr = _ir_a_parametros(page)
    fr.get_by_text(re.compile(r"^\s*SIGUIENTE\s*$", re.I)).first.click()
    r = _leer_consulta(page, cuit)
    while int(r["anio"] or 0) > anio:
        fr = _marco_con(page, r"Per[ií]odo Fiscal consultado")
        boton = fr.get_by_text(re.compile(r"A[ÑN]O ANTERIOR", re.I))
        if not boton.count():
            return {"anio": str(anio), "estado": "no hay año anterior"}
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
