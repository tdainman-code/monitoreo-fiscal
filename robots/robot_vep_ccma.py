"""Robot: VEP de AUTÓNOMOS y MONOTRIBUTO desde la CCMA (relevado con Gaby el 26/11/2026, Piol German 20-30743249-9).

Recorrido:
  CCMA (P02 "Recálculo de deuda a fecha" -> CALCULO DE DEUDA -> P04 "Última deuda calculada") -> botón "VOLANTE DE PAGO"
  -> VolPag_ctacte.asp: solapas AUTONOMOS Y MONOTRIBUTISTAS | MONOTRIB. COMPONENTE SUBNACIONAL | SERVICIO DOMESTICO
     secciones con casillas por renglón (y "Seleccionar todos"):
       AUTONOMO - OBLIGACIONES      Período | Impuesto (AUT) | Concepto | SubConcepto | Categoría | Importe | Selección
       MONOTRIBUTO - OBLIGACIONES   Período | Impuesto (020) | Concepto | SubConcepto | Categoría | Importe | Selección
       MONOTRIBUTO - INTERESES      Período | Impuesto | Concepto | Subcpto (051) | Importe | Selección
  -> "GENERAR VEP O QR" -> seti.afip.gob.ar/setiweb/#/pago/veps-a-enviar "Seleccionar medio de pago" (un renglón por
     concepto: ARCA - OTROS PAGOS / Autonomo - Pago Mensual, e "Importe Total a pagar") -> logo del medio
  -> cartel "¿Querés enviar el VEP a BANELCO?" -> Aceptar -> "Enviaste el VEP a la entidad de pago. N° de VEP ..."
Un VEP consolidado (ej. VCON#3, 3 SubVeps). Vence en ~25 días. No paga nada.
Controles: el total de lo tildado tiene que coincidir con el "Importe Total a pagar"; el cartel tiene que nombrar el
medio elegido; el VEP tiene que ser del CUIT del cliente. Si algo no coincide, NO se genera.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

from . import arca, robot_ccma, robot_vep_deuda as vd

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
SECCIONES = {"autonomo": r"AUTONOMO\s*-\s*OBLIGACIONES", "monotributo": r"MONOTRIBUTO\s*-\s*OBLIGACIONES",
             "intereses": r"MONOTRIBUTO\s*-\s*INTERESES"}

JS_TILDAR = r"""(secciones) => {
  // Cada sección es una tabla cuyo título coincide; se tildan sus casillas y se devuelve lo tildado.
  const out = [];
  const tablas = [...document.querySelectorAll('table')];
  for (const [nombre, patron] of secciones) {
    const re = new RegExp(patron, 'i');
    const t = tablas.filter(x => re.test(x.innerText) && x.querySelector('input[type=checkbox]'))
                    .sort((a, b) => a.innerText.length - b.innerText.length)[0];
    if (!t) continue;
    for (const r of t.querySelectorAll('tr')) {
      const cb = r.querySelector('input[type=checkbox]');
      if (!cb) continue;
      const celdas = [...r.cells].map(c => c.innerText.trim());
      if (!cb.checked) cb.click();
      out.push({seccion: nombre, celdas});
    }
  }
  return out;
}"""


def _importe(t: str) -> float | None:
    """'79,782.20' (CCMA) o '$ 79.782,20' (pantalla de pago)."""
    t = (t or "").replace("$", "").strip()
    if re.fullmatch(r"-?[\d,]+\.\d{2}", t):
        return float(t.replace(",", ""))
    if re.fullmatch(r"-?[\d.]+,\d{2}", t):
        return float(t.replace(".", "").replace(",", "."))
    return None


def leer_tildado(filas: list[dict]) -> list[dict]:
    out = []
    for f in filas:
        c = f["celdas"]
        imps = [_importe(x) for x in c if _importe(x) is not None]
        out.append({"seccion": f["seccion"], "periodo": c[0] if c else "", "impuesto": c[1] if len(c) > 1 else "",
                    "importe": imps[-1] if imps else 0.0})
    return out


def generar(page, cuit: str, medio: str, secciones: list[str]) -> dict:
    """Con la CCMA del cliente en P04: VOLANTE DE PAGO -> tildar -> GENERAR VEP O QR -> medio -> VEP."""
    vd._boton(page, r"VOLANTE\s+DE\s+PAGO").click()
    page.wait_for_load_state("domcontentloaded")
    page.get_by_text(re.compile(r"OBLIGACIONES|INTERESES", re.I)).first.wait_for(timeout=60_000)
    texto = page.inner_text("body")
    if cuit not in re.sub(r"\D", "", texto[:2000]):
        raise arca.CuitEquivocado(f"CCMA (volante de pago): no muestra el CUIT {arca.cuit_fmt(cuit)}")
    tildado = leer_tildado(page.evaluate(JS_TILDAR, [[s, SECCIONES[s]] for s in secciones]))
    if not tildado:
        raise arca.ErrorRobot("CCMA: no hay obligaciones impagas para incluir en el VEP")
    total = round(sum(x["importe"] for x in tildado), 2)
    ctx = page.context
    antes = set(ctx.pages)
    vd._boton(page, r"GENERAR\s+VEP").click()
    page.wait_for_timeout(4000)
    nuevas = [p for p in ctx.pages if p not in antes]
    pago = nuevas[-1] if nuevas else page
    pago.wait_for_load_state("domcontentloaded")
    pago.get_by_text(re.compile(r"Seleccionar medio de pago", re.I)).first.wait_for(timeout=90_000)
    m_tot = re.search(r"Importe Total a pagar\s*:?\s*\$\s*([\d.]+,\d{2})", pago.inner_text("body"), re.I)
    total_pago = _importe(m_tot[1]) if m_tot else None
    if total_pago is not None and abs(total_pago - total) > 0.05:
        raise arca.ErrorRobot(f"VEP: se tildaron $ {total:,.2f} y la pantalla de pago dice $ {total_pago:,.2f}. No se generó.")
    vd.elegir_medio(pago, medio)
    cartel = pago.get_by_text(re.compile(r"Quer[eé]s enviar el VEP a", re.I)).first
    cartel.wait_for(state="visible", timeout=30_000)
    t_cartel = cartel.inner_text()
    if not re.search(vd.MEDIOS[medio][2], t_cartel, re.I):
        vd._boton(pago, r"^\s*Cancelar\s*$").click()
        raise arca.ErrorRobot(f"VEP: el cartel dice '{t_cartel.strip()[:80]}' y se eligió {medio}. No se generó.")
    vd._boton(pago, r"^\s*Aceptar\s*$").click()
    pago.get_by_text(vd.RE_VEP).first.wait_for(state="visible", timeout=90_000)
    fin = pago.inner_text("body")
    vep = vd.RE_VEP.search(fin)[1]
    cuit_vep = re.search(r"CUIT\s*:?\s*(\d{2}-?\d{8}-?\d)", fin)
    if cuit_vep and re.sub(r"\D", "", cuit_vep[1]) != cuit:
        raise arca.CuitEquivocado(f"VEP {vep}: figura el CUIT {cuit_vep[1]} y no {arca.cuit_fmt(cuit)}")
    m_imp = re.search(r"Importe\s*:?\s*\$\s*([\d.]+,\d{2})", fin)
    desc = re.search(r"Descripci[oó]n\s*:?\s*([^\n]+)", fin)
    try:
        captura = pago.screenshot(full_page=True)
    except Exception:
        captura = None
    return {"_captura": captura, "vep": vep, "medio": medio, "importe": _importe(m_imp[1]) if m_imp else total,
            "total_tildado": total, "descripcion": desc[1].strip() if desc else "", "conceptos": tildado,
            "creado": datetime.now().isoformat(timespec="seconds"), "tipo": "autonomos_monotributo"}


def correr(cuit: str, medio: str, secciones: list[str] | None = None, visible: bool = False, por: str = "") -> dict:
    """Entra a ARCA y genera el VEP de autónomos/monotributo. Guarda DATOS/<cuit>/vep/<fecha>_ccma_<vep>.json."""
    from . import almacen_claves as alm
    if medio not in vd.MEDIOS:
        raise arca.ErrorRobot(f"Medio de pago desconocido: {medio}")
    secciones = [s for s in (secciones or list(SECCIONES)) if s in SECCIONES]
    usuario, clave, metodo = alm.obtener_clave(cuit, "ARCA", motivo="VEP autónomos / monotributo")
    res: dict = {}

    def paso(ctx, portal):
        page, motivo = robot_ccma._abrir_ccma(ctx, portal, cuit, usuario)
        if page is None:
            raise arca.ErrorRobot(f"CCMA: {motivo}")
        robot_ccma.leer(page, cuit, date.today())           # recalcula la deuda a hoy y controla el CUIT
        res["vep"] = generar(page, cuit, medio, secciones)
        return "OK"

    arca.ejecutar(usuario, clave, [("vep_ccma", paso)], os.path.join(DATOS, cuit, "capturas"), visible, max_reingresos=0)
    v = res.get("vep")
    if not v:
        raise arca.ErrorRobot("No se pudo generar el VEP de autónomos / monotributo")
    carpeta = os.path.join(DATOS, cuit, "vep")
    os.makedirs(carpeta, exist_ok=True)
    base = os.path.join(carpeta, f"{date.today().isoformat()}_ccma_{v['vep']}")
    captura = v.pop("_captura", None)
    if captura:
        with open(base + ".png", "wb") as f:
            f.write(captura)
    v.update(cuit=cuit, pedido_por=por, captura=bool(captura))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1)
    return v
