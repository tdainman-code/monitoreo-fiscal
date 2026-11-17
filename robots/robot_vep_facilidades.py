"""Robot: VEP de una cuota de un plan de Mis Facilidades (relevado con Gaby el 17/11/2026, plan V311555 cuota 12).

Recorrido:
  Mis servicios -> Mis Facilidades -> seguimiento_presentacion.aspx (lista de planes) -> "Detalle" del plan
  -> SeguimientoPlanEnviado/<id> -> botón "Rehabilitación Cuotas" -> RehabilitacionCuotas/<id>
  Tabla: Cuota Nro. | Capital | Interés Financiero | Valor Total | Vencimiento del Débito | Opción | Int. Resarcitorio |
         Valor Cuota Rehabilitada | Nuevo Vencimiento. Cada cuota tiene DOS filas de opción:
           [Rehabilitar]  -> pasa la cuota al día 12 del mes siguiente.  NUNCA SE TOCA.
           [Generar Vep]  -> VEP con vencimiento HOY.                  Es el que se usa.
  "Generar Vep" -> cartel ATENCION "¿Está seguro que quiere rehabilitar la cuota N° 12 por un total de 6.854,63 pesos?"
                   (el texto dice "rehabilitar" aunque se eligió Generar Vep) -> Aceptar
  -> "ARCA VEP · Seleccione tipo de pago": pagar (Red Link) | PagoMisCuentas (Banelco) | INTERbanking | XN group
  -> "Nro. VEP: 1708960299 · Organismo recaudador: ARCA · Tipo de pago: MIS FACILIDADES · Nro. de plan: V311555 ·
      Cuota: 12 · Importe: 6854.63 · Fecha de creación: 2026-11-17T19:03:58 · Fecha de expiración: 2026-11-17"
El VEP VENCE A LA MEDIANOCHE del día en que se genera: se genera en el momento de mandar el aviso.
Un VEP por cada medio de pago del cliente (según sus bancos; se eligen en "Datos del cliente" de la web).
No paga nada: el cliente lo paga desde su home banking buscando el número de VEP.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date

from . import arca
from .robot_situacion_fiscal import BASE_MF, _abrir_detalle, _controlar_cuit, _elegir_cuit_mf, _ir

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
# texto de la web -> cómo reconocer el logo en el cartel "Seleccione tipo de pago" (alt / title / src / texto)
MEDIOS = {
    "Pagar (Red Link)": (r"pagar|red\s*link|\blink\b", 0),
    "Pago Mis Cuentas (Banelco)": (r"pago\s*mis\s*cuentas|pagomiscuentas|banelco", 1),
    "Interbanking": (r"interbanking", 2),
    "XN Group": (r"\bxn\b|xn\s*group", 3),
}
RE_VEP = re.compile(r"Nro\.?\s*VEP:?\s*(\d{6,})", re.I)


def _dato(texto: str, etiqueta: str) -> str:
    m = re.search(rf"{etiqueta}:?\s*([^\n]+)", texto, re.I)
    return m[1].strip() if m else ""


def _boton_generar_vep(page, cuota: int):
    """El 'Generar Vep' de la cuota pedida (la fila de 'Rehabilitar' NUNCA)."""
    idx = page.evaluate("""(cuota) => {
        const bs = [...document.querySelectorAll('button, input[type=button], input[type=submit], a')];
        let actual = null, out = -1;
        const filas = [...document.querySelectorAll('table tr')];
        for (const tr of filas) {
          const c0 = tr.cells.length ? tr.cells[0].textContent.trim() : '';
          if (/^\\d+$/.test(c0) && tr.cells.length > 4) actual = parseInt(c0);
          for (const b of tr.querySelectorAll('button, input[type=button], input[type=submit], a')) {
            const t = (b.innerText || b.value || '').trim();
            if (/generar\\s*vep/i.test(t) && actual === cuota) out = bs.indexOf(b);
          }
        }
        return out; }""", cuota)
    if idx < 0:
        raise arca.ErrorRobot(f"Mis Facilidades: no aparece 'Generar Vep' para la cuota {cuota} en Rehabilitación Cuotas")
    b = page.locator("button, input[type=button], input[type=submit], a").nth(idx)
    texto = (b.inner_text() or b.get_attribute("value") or "").strip()
    if not re.search(r"generar\s*vep", texto, re.I) or re.search(r"rehabilitar", texto, re.I):
        raise arca.ErrorRobot(f"Mis Facilidades: el botón elegido dice '{texto}' (se esperaba 'Generar Vep')")
    return b


def _elegir_medio(page, medio: str) -> None:
    """Toca el logo del medio de pago en 'Seleccione tipo de pago' (marca el elemento en la página y lo cliquea)."""
    patron, orden = MEDIOS[medio]
    page.get_by_text(re.compile(r"Seleccione tipo de pago", re.I)).first.wait_for(state="visible", timeout=60_000)
    ok = page.evaluate("""([patron, orden]) => {
        const re = new RegExp(patron, 'i');
        const modal = [...document.querySelectorAll('.modal, [role=dialog]')].find(m => m.offsetParent !== null &&
                       /Seleccione tipo de pago/i.test(m.innerText));
        if (!modal) return 'sin cartel';
        const cands = [...modal.querySelectorAll('a, button, img, [onclick]')].filter(e => e.offsetParent !== null
                       && !/cerrar|close|×/i.test((e.innerText || '') + (e.getAttribute('aria-label') || '')));
        const txt = e => [e.getAttribute('alt'), e.getAttribute('title'), e.getAttribute('src'), e.getAttribute('href'),
                          e.getAttribute('aria-label'), e.getAttribute('onclick'), e.innerText, e.className].join(' ');
        let el = cands.find(e => re.test(txt(e)));
        if (!el) {                                     // sin texto reconocible: los logos vienen siempre en este orden
          const logos = cands.filter(e => e.tagName === 'IMG' && !/arca/i.test(txt(e)));
          if (logos.length >= 4) el = logos[orden];
        }
        if (!el) return 'no encontrado';
        el.setAttribute('data-robot-medio', '1');
        return 'ok'; }""", [patron, orden])
    if ok != "ok":
        raise arca.ErrorRobot(f"VEP: no se pudo elegir el medio de pago '{medio}' ({ok})")
    page.locator("[data-robot-medio='1']").first.click()


def vep_en_pantalla(page, plan: str, cuota: int, medio: str) -> dict:
    """Con 'Rehabilitación Cuotas' en pantalla: Generar Vep de la cuota -> Aceptar -> medio de pago -> lee el VEP."""
    _boton_generar_vep(page, cuota).click()
    arca.pausa(0.8, 1.5)
    aviso = page.get_by_text(re.compile(r"seguro que quiere", re.I)).first
    aviso.wait_for(state="visible", timeout=30_000)
    t = aviso.inner_text()
    if not re.search(rf"cuota\s*N[°º]?\s*{cuota}\b", t, re.I):
        raise arca.ErrorRobot(f"VEP: el cartel de confirmación no es de la cuota {cuota}: '{t[:120]}'")
    page.get_by_role("button", name=re.compile(r"^\s*Aceptar\s*$", re.I)).first.click()
    arca.pausa(1.0, 2.0)
    _elegir_medio(page, medio)
    page.get_by_text(RE_VEP).first.wait_for(state="visible", timeout=90_000)
    texto = page.locator(".modal, [role=dialog]").filter(has_text=RE_VEP).first.inner_text()
    nro = RE_VEP.search(texto)[1]
    d = {"vep": nro, "medio": medio, "plan": _dato(texto, r"Nro\.?\s*de\s*plan"), "cuota": _dato(texto, r"Cuota"),
         "importe": _dato(texto, r"Importe"), "creado": _dato(texto, r"Fecha de creaci[oó]n"),
         "vence": _dato(texto, r"Fecha de expiraci[oó]n"), "tipo": _dato(texto, r"Tipo de pago")}
    if d["plan"] != plan or str(d["cuota"]).strip() != str(cuota):
        raise arca.ErrorRobot(f"VEP {nro}: es del plan {d['plan']} cuota {d['cuota']} y se pidió {plan} cuota {cuota}")
    return d


def generar(page, cuit: str, plan: str, cuota: int, medios: list[str]) -> list[dict]:
    """Con Mis Facilidades abierto en el CUIT del cliente: un VEP por medio de pago. Devuelve los datos de cada VEP."""
    id_ = _abrir_detalle(page, plan)
    veps = []
    for medio in medios:
        if medio not in MEDIOS:
            continue
        _ir(page, BASE_MF + f"RehabilitacionCuotas/{id_}")
        _controlar_cuit(page.inner_text("body"), cuit, "Mis Facilidades")
        if plan not in page.inner_text("body"):
            raise arca.ErrorRobot(f"Rehabilitación Cuotas no muestra el plan {plan}")
        d = vep_en_pantalla(page, plan, cuota, medio)
        veps.append(d)
        cerrar = page.get_by_role("button", name=re.compile(r"^\s*Cerrar\s*$", re.I))
        if cerrar.count():
            cerrar.first.click()
        arca.pausa(1.0, 2.0)
    return veps


def correr(cuit: str, plan: str, cuota: int, medios: list[str], visible: bool = False) -> list[dict]:
    """Entra a ARCA con la clave del cliente y genera los VEP. Guarda DATOS/<cuit>/vep/<fecha>_<plan>_<cuota>.json."""
    from . import almacen_claves as alm
    usuario, clave, metodo = alm.obtener_clave(cuit, "ARCA", motivo=f"VEP plan {plan} cuota {cuota}")
    res: dict = {}

    def paso(ctx, portal):
        page = arca.abrir_servicio(ctx, portal, "mis_facilidades")
        page.wait_for_load_state("domcontentloaded")
        _elegir_cuit_mf(page, cuit)
        _controlar_cuit(page.inner_text("body"), cuit, "Mis Facilidades")
        res["veps"] = generar(page, cuit, plan, int(cuota), medios)
        page.close()
        return "OK"

    arca.ejecutar(usuario, clave, [("vep", paso)], os.path.join(DATOS, cuit, "capturas"), visible, max_reingresos=1)
    veps = res.get("veps") or []
    carpeta = os.path.join(DATOS, cuit, "vep")
    os.makedirs(carpeta, exist_ok=True)
    with open(os.path.join(carpeta, f"{date.today().isoformat()}_{plan}_{cuota}.json"), "w", encoding="utf-8") as f:
        json.dump(veps, f, ensure_ascii=False, indent=1)
    return veps
