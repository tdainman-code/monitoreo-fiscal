"""Robot: VEP de deuda desde Cuentas Tributarias (relevado con Tomás el 20/11/2026, BH Soluciones).

Recorrido (todo dentro del marco de la SCT):
  solapa "Deudas" -> tabla: [casilla] | Establecimiento | (!) | Impuesto | Concepto | Subconcepto | Período | Ant/Cuota |
      Vencimiento | Saldo | Int. Resarcitorio | Int. Punitorio   (filas rojas = vencidas; pie "Subtotal a pagar" / "Total")
  -> tildar los conceptos pedidos -> botón "PAGAR SELECCIONADO" (arriba a la derecha de la tabla)
  -> "Confirmación": Total | Capital vencido | Capital no vencido | Int. Resarcitorios | Int. Punitorios + la tabla de lo
     elegido -> botones VOLVER / "GENERAR VEP"
  -> "Seleccionar medio de pago": lista (CUIT | ARCA - OTROS PAGOS | importe) e "Importe Total a pagar", y los logos
     Pago con QR | pagar (Link) | PagoMisCuentas (Banelco) | interbanking | XN group
  -> cartel "Medio de pago — ¿Querés enviar el VEP a BANELCO?" -> Aceptar
  -> "Enviaste el VEP a la entidad de pago.  N° de VEP: 1710611439 · Descripción: VCON#6 · CUIT · Importe: $ 271.653,02"
Es UN VEP consolidado con todas las obligaciones elegidas (el capital y sus intereses van como renglones separados).
Vence a la medianoche del día en que se genera. No paga nada.
Controles: si falta alguno de los conceptos pedidos, o la confirmación trae otra cantidad, o el cartel nombra otra
entidad, NO se genera el VEP.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
# medio (como en la web) -> (cómo reconocer el logo, posición del logo, cómo lo nombra el cartel de confirmación)
MEDIOS = {
    "Pago con QR": (r"\bqr\b", 0, r"QR"),
    "Pagar (Red Link)": (r"pagar|red\s*link|\blink\b", 1, r"LINK|PAGAR"),
    "Pago Mis Cuentas (Banelco)": (r"pago\s*mis\s*cuentas|pagomiscuentas|banelco", 2, r"BANELCO|MIS\s*CUENTAS"),
    "Interbanking": (r"interbanking|\binter\b", 3, r"INTERBANKING"),
    "XN Group": (r"\bxn\b|xn\s*group", 4, r"\bXN\b"),
}
RE_VEP = re.compile(r"N[°º]?\s*de\s*VEP\s*:?\s*(\d{6,})", re.I)


def _norm(t) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip().upper()


def _importe(t: str) -> float | None:
    m = re.search(r"\$\s*([\d.]+,\d{2})", t or "")
    return float(m[1].replace(".", "").replace(",", ".")) if m else None


JS_FILAS = r"""() => {
  const t = [...document.querySelectorAll('table')].find(x => x.offsetParent !== null && /Subconcepto/i.test(x.innerText)
              && x.querySelector('input[type=checkbox]'));
  if (!t) return null;
  const cab = [...t.querySelectorAll('thead th')].map(h => h.innerText.replace(/\s+/g, ' ').trim());
  document.querySelectorAll('[data-robot-fila]').forEach(r => r.removeAttribute('data-robot-fila'));
  return {cab, filas: [...t.querySelectorAll('tbody tr')].map((r, i) => (r.setAttribute('data-robot-fila', i), {i,
     celdas: [...r.cells].map(c => c.innerText.replace(/\s+/g, ' ').trim()),
     tiene_casilla: !!r.querySelector('input[type=checkbox]'),
     tildada: !!(r.querySelector('input[type=checkbox]') || {}).checked}))};
}"""


def _clave_fila(cab: list[str], celdas: list[str]) -> tuple | None:
    col = lambda nombre: next((i for i, c in enumerate(cab) if re.match(nombre, c, re.I)), None)
    idx = [col(r"Impuesto"), col(r"Concepto"), col(r"Subconcepto"), col(r"Per[ií]odo"), col(r"Ant")]
    if None in idx[:4] or len(celdas) != len(cab):
        return None
    return tuple(_norm(celdas[i]) if i is not None else "" for i in idx)


def _clave_concepto(c: dict) -> tuple:
    return (_norm(c.get("impuesto")), _norm(c.get("concepto")), _norm(c.get("subconcepto") or c.get("concepto")),
            _norm(c.get("periodo")), _norm(c.get("cuota")))


def tildar(fr, conceptos: list[dict]) -> int:
    """Tilda en la solapa Deudas exactamente los conceptos pedidos. Devuelve cuántos tildó (o error si falta alguno)."""
    t = fr.evaluate(JS_FILAS)
    if not t:
        raise arca.ErrorRobot("Cuentas Tributarias: no aparece la tabla de Deudas con casillas")
    buscadas = {_clave_concepto(c) for c in conceptos}
    filas = {}
    for f in t["filas"]:
        k = _clave_fila(t["cab"], f["celdas"])
        if k and f["tiene_casilla"]:
            filas.setdefault(k, f["i"])
    # la cuota puede faltar en lo guardado: se compara sin ella si no hay coincidencia exacta
    elegidas = []
    for b in buscadas:
        i = filas.get(b)
        if i is None:
            cand = [i for k, i in filas.items() if k[:4] == b[:4] and (not b[4] or k[4] == b[4])]
            i = cand[0] if len(cand) == 1 else None
        if i is None:
            raise arca.ErrorRobot(f"VEP: no encontré en Deudas el concepto {' · '.join(x for x in b if x)} "
                                  "(¿ya se pagó o cambió?). No se generó nada.")
        elegidas.append(i)
    # 25/11/2026: cada fila se busca por la marca que le puso JS_FILAS en la tabla de Deudas. Antes se contaba con
    # nth() sobre TODAS las tablas con casillas de la página (había otras ocultas) y la fila 13 no era la de Deudas.
    def casilla(i):
        return fr.locator(f'tr[data-robot-fila="{i}"] input[type=checkbox]').first

    def poner(i, valor):
        c = casilla(i)
        try:
            c.scroll_into_view_if_needed(timeout=10_000)
            c.set_checked(valor, timeout=15_000)
        except Exception:                                 # casilla con estilo propio (input oculto): clic por JS
            if c.evaluate("e => e.checked") != valor:
                c.evaluate("e => e.click()")
    for f in t["filas"]:                                  # primero se destilda todo lo que no corresponde
        if f["tildada"] and f["i"] not in elegidas:
            poner(f["i"], False)
    for i in elegidas:
        poner(i, True)
    arca.pausa(0.5, 1.0)
    marcadas = sum(1 for f in fr.evaluate(JS_FILAS)["filas"] if f["tildada"])
    if marcadas != len(elegidas):
        raise arca.ErrorRobot(f"VEP: quedaron {marcadas} casillas tildadas y se pidieron {len(elegidas)}")
    return len(elegidas)


def _boton(fr, patron: str, espera_ms: int = 60_000):
    b = fr.get_by_role("button", name=re.compile(patron, re.I))
    if not b.count():
        b = fr.locator("button, a, input[type=button], input[type=submit]").filter(has_text=re.compile(patron, re.I))
    b.first.wait_for(state="visible", timeout=espera_ms)
    return b.first


def elegir_medio(fr, medio: str) -> None:
    patron, orden, _ = MEDIOS[medio]
    fr.get_by_text(re.compile(r"Seleccionar medio de pago", re.I)).first.wait_for(state="visible", timeout=60_000)
    ok = fr.evaluate("""([patron, orden]) => {
        const re = new RegExp(patron, 'i');
        const tit = [...document.querySelectorAll('*')].find(e => /^\\s*Medios de pago\\s*$/i.test(e.innerText || ''));
        const raiz = tit ? tit.parentElement : document.body;
        const cands = [...raiz.querySelectorAll('a, button, img, [onclick], [role=button]')].filter(e => e.offsetParent !== null);
        const txt = e => [e.getAttribute('alt'), e.getAttribute('title'), e.getAttribute('src'), e.getAttribute('aria-label'),
                          e.innerText, e.className].join(' ');
        let el = cands.find(e => re.test(txt(e)));
        if (!el) {
          const logos = cands.filter(e => e.tagName === 'IMG' || e.tagName === 'BUTTON');
          if (logos.length >= 5) el = logos[orden];
        }
        if (!el) return 'no encontrado';
        el = el.closest('a, button, [onclick], [role=button]') || el;      // el clic va al botón que contiene el logo
        el.setAttribute('data-robot-medio', '1');
        return 'ok'; }""", [patron, orden])
    if ok != "ok":
        raise arca.ErrorRobot(f"VEP: no se pudo elegir el medio de pago '{medio}' ({ok})")
    fr.locator("[data-robot-medio='1']").first.click()


def generar_en_sct(page, fr, cuit: str, conceptos: list[dict], medio: str) -> dict:
    """Con la SCT abierta en el CUIT del cliente: Deudas -> tildar -> Pagar seleccionado -> Generar VEP -> medio -> VEP."""
    from .robot_situacion_fiscal import _solapa
    _solapa(fr, r"Deudas").click()
    arca.pausa(1.0, 2.0)
    # 21/11/2026: hay varios "Fecha de consulta" (uno por solapa) y el primero está oculto: se espera el visible
    fr.get_by_text(re.compile(r"Fecha de consulta", re.I)).locator("visible=true").first.wait_for(state="visible", timeout=60_000)
    sel = fr.locator(".tab-pane.active select")
    if sel.count() and sel.first.is_enabled():           # "Mostrar: Todos" para ver todas las filas
        try:
            sel.first.select_option("-1", timeout=10_000)
        except Exception:
            pass
        arca.pausa(1.0, 2.0)
    n = tildar(fr, conceptos)
    _boton(fr, r"PAGAR\s+SELECCIONADO").click()
    fr.get_by_text(re.compile(r"^\s*Confirmaci[oó]n\s*$", re.I)).first.wait_for(state="visible", timeout=60_000)
    texto = fr.locator("body").inner_text()
    filas_conf = fr.evaluate("""() => { const t = [...document.querySelectorAll('table')].find(x => x.offsetParent !== null
                                && /Subconcepto/i.test(x.innerText)); if (!t) return -1;
                                return [...t.querySelectorAll('tbody tr')].filter(r => /\\d/.test(r.innerText)
                                        && !/total/i.test(r.innerText)).length; }""")
    if filas_conf not in (-1, n):
        _boton(fr, r"^\s*VOLVER\s*$").click()
        raise arca.ErrorRobot(f"VEP: la confirmación muestra {filas_conf} conceptos y se tildaron {n}. No se generó.")
    m_tot = re.search(r"Total\s*\$\s*[\d.]+,\d{2}", texto, re.I)
    total_conf = _importe(m_tot[0]) if m_tot else None
    _boton(fr, r"GENERAR\s+VEP").click()
    elegir_medio(fr, medio)
    cartel = fr.get_by_text(re.compile(r"Quer[eé]s enviar el VEP a", re.I)).first
    cartel.wait_for(state="visible", timeout=30_000)
    t_cartel = cartel.inner_text()
    if not re.search(MEDIOS[medio][2], t_cartel, re.I):
        _boton(fr, r"^\s*Cancelar\s*$").click()
        raise arca.ErrorRobot(f"VEP: el cartel dice '{t_cartel.strip()[:80]}' y se eligió {medio}. No se generó.")
    _boton(fr, r"^\s*Aceptar\s*$").click()
    fr.get_by_text(RE_VEP).first.wait_for(state="visible", timeout=90_000)
    fin = fr.locator("body").inner_text()
    vep = RE_VEP.search(fin)[1]
    cuit_vep = re.search(r"CUIT\s*:?\s*(\d{2}-?\d{8}-?\d)", fin)
    if cuit_vep and re.sub(r"\D", "", cuit_vep[1]) != cuit:
        raise arca.CuitEquivocado(f"VEP {vep}: figura el CUIT {cuit_vep[1]} y no {arca.cuit_fmt(cuit)}")
    desc = re.search(r"Descripci[oó]n\s*:?\s*([^\n]+)", fin)
    m_imp = re.search(r"Importe\s*:?\s*\$\s*[\d.]+,\d{2}", fin)
    try:                                   # 20/11/2026: captura de la pantalla final, para verla desde la web
        captura = page.screenshot(full_page=True)
    except Exception:
        captura = None
    return {"_captura": captura, "vep": vep, "medio": medio, "importe": _importe(m_imp[0]) if m_imp else None,
            "total_confirmacion": total_conf, "descripcion": desc[1].strip() if desc else "", "conceptos": conceptos,
            "creado": datetime.now().isoformat(timespec="seconds"), "vence": date.today().isoformat()}


def correr(cuit: str, conceptos: list[dict], medio: str, visible: bool = False, por: str = "") -> dict:
    """Entra a ARCA con la clave del cliente y genera el VEP consolidado. Guarda DATOS/<cuit>/vep/<fecha>_deuda_<vep>.json."""
    from . import almacen_claves as alm
    from . import robot_situacion_fiscal as rsf
    if medio not in MEDIOS:
        raise arca.ErrorRobot(f"Medio de pago desconocido: {medio}")
    usuario, clave, metodo = alm.obtener_clave(cuit, "ARCA", motivo=f"VEP de deuda ({len(conceptos)} conceptos)")
    rsf.USUARIO_ACTUAL["cuit"], rsf.USUARIO_ACTUAL["cliente"] = usuario, cuit
    res: dict = {}

    def paso(ctx, portal):
        page = arca.abrir_servicio(ctx, portal, "cuentas_tributarias")
        page.wait_for_load_state("domcontentloaded")
        rsf._elegir_cuit_sct(page, cuit, None)
        fr = rsf._frame_sct(page)
        rsf._controlar_cuit(page.inner_text("body") + fr.locator("body").inner_text(), cuit, "Cuentas Tributarias")
        res["vep"] = generar_en_sct(page, fr, cuit, conceptos, medio)
        page.close()
        return "OK"

    arca.ejecutar(usuario, clave, [("vep_deuda", paso)], os.path.join(DATOS, cuit, "capturas"), visible, max_reingresos=0)
    v = res.get("vep")
    if not v:
        raise arca.ErrorRobot("No se pudo generar el VEP de deuda")
    carpeta = os.path.join(DATOS, cuit, "vep")
    os.makedirs(carpeta, exist_ok=True)
    base = os.path.join(carpeta, f"{date.today().isoformat()}_deuda_{v['vep']}")
    captura = v.pop("_captura", None)
    if captura:
        with open(base + ".png", "wb") as f:
            f.write(captura)
    v.update(cuit=cuit, pedido_por=por, captura=bool(captura))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1)
    return v
