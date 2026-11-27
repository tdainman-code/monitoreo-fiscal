"""Robot: VEP del IVA con el beneficio de pago a 90 días (F.1272), relevado con Gaby el 26/11/2026.

Cuándo: el IVA vence normalmente ~15-25 del mes siguiente al período; con el beneficio el vencimiento se corre ~3
meses. En la deuda de Cuentas Tributarias (lectura diaria) se ve una obligación de IVA (DDJJ, 19-19) cuyo
vencimiento cae 3 meses o más después del período: esa es la del beneficio. 10 días antes del vencimiento se
genera el VEP y se le avisa al encargado (al cliente no se le manda nada). Ver avisos.avisar_iva_diferido.

Recorrido (Gonçalves 20-33116278-8, Nabajuma):
  Mis servicios -> "Presentación de DDJJ y Pagos" (seti.afip.gob.ar/setiweb)
  -> Pagos / Gestión de VEP (#/pago/nuevo-vep) -> botón "Generar VEP" (desplegable: Nuevo VEP / Desde deuda /
     Desde archivo / Desde vencimiento) -> "Desde deuda" (#/pago/nuevo-vep?op=2)
  -> combo "Contribuyente" ("30712227571 - NABAJUMA S.A."; si la clave representa a varios) -> "Ver Consulta"
  -> tabla con casillas: Período (AAAAMM) | Impuesto ("30 - IVA") | Concepto y Subconcepto ("19 - 19"; "19 - 51" son
     intereses) | Anticipo/Cuota | Importe | Vencimiento (AAAA-MM-DD); "Mostrando [5..100] filas", paginado "1 de N"
  -> se tilda SOLO el renglón del IVA del período (19 - 19, con ese vencimiento) -> "Generar VEP"
  -> vuelve a Gestión VEP, solapa "VEPs a enviar" (ARCA - OTROS PAGOS, importe), con el VEP nuevo tildado
  -> "Seleccioná medio de pago" -> "Seleccionar medio de pago" (logos QR / pagar / PagoMisCuentas / Interbanking /
     XN group) -> cartel "¿Querés enviar el VEP a ...?" -> Aceptar -> N° de VEP.
Controles: el renglón tiene que coincidir en período, impuesto, concepto y vencimiento, y su importe con el saldo de
Cuentas Tributarias; en "VEPs a enviar" se deja tildado solo el renglón de ese importe; el "Importe Total a pagar"
tiene que dar lo mismo; el cartel tiene que nombrar el medio elegido. Si algo no coincide, NO se genera.
VERIFICAR en la primera corrida real: pantallas posteriores a "Generar VEP" (relevadas con capturas, no corridas).
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime

from . import arca, robot_vep_deuda as vd

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
URL_DESDE_DEUDA = "https://seti.afip.gob.ar/setiweb/#/pago/nuevo-vep?op=2"


def _imp(t) -> float | None:
    m = re.search(r"-?[\d.]+,\d{2}", str(t or ""))
    return float(m[0].replace(".", "").replace(",", ".")) if m else None


def _per(t) -> str:
    return re.sub(r"\D", "", str(t or ""))[:6]


def elegir_renglon(filas: list[list[str]], periodo: str, vencimiento: str) -> int | None:
    """Índice del renglón del IVA (30) DDJJ (19 - 19) del período con ese vencimiento. None si no está o hay más de uno."""
    per, venc = _per(periodo), str(vencimiento)[:10]
    hallados = []
    for i, c in enumerate(filas):
        txt = [x.strip() for x in c]
        if (per in [_per(x) for x in txt if re.fullmatch(r"\d{6}", x.strip())]
                and any(re.match(r"0*30\s*-", x) or re.fullmatch(r"IVA", x, re.I) for x in txt)
                and any(re.fullmatch(r"0*19\s*-\s*0*19", x) for x in txt)
                and venc in txt):
            hallados.append(i)
    return hallados[0] if len(hallados) == 1 else None


JS_FILAS = r"""() => {
  const t = [...document.querySelectorAll('table')].find(x => x.offsetParent !== null && /Vencimiento/i.test(x.innerText)
             && /Importe/i.test(x.innerText));
  if (!t) return null;
  const filas = [...t.querySelectorAll('tbody tr')].filter(r => r.querySelector('input[type=checkbox], mat-checkbox, [role=checkbox]'));
  filas.forEach((r, i) => r.setAttribute('data-robot-fila', String(i)));
  return filas.map(r => [...r.cells].map(c => (c.innerText || '').replace(/\s+/g, ' ').trim()));
}"""


def _boton(fr, patron: str, espera_ms: int = 60_000):
    return vd._boton(fr, patron, espera_ms)


def _ir_a_desde_deuda(page) -> None:
    page.get_by_text(re.compile(r"Gesti[oó]n\s+(de\s+)?VEP", re.I)).first.wait_for(timeout=60_000)
    try:
        page.get_by_text(re.compile(r"^\s*Gesti[oó]n\s+de\s+VEP\s*$", re.I)).first.click(timeout=10_000)
        arca.pausa(1.0, 2.0)
        page.get_by_role("button", name=re.compile(r"Generar\s+VEP", re.I)).first.click(timeout=15_000)
        page.get_by_text(re.compile(r"^\s*Desde\s+deuda\s*$", re.I)).first.click(timeout=15_000)
    except Exception:
        page.goto(URL_DESDE_DEUDA, wait_until="domcontentloaded")
    page.get_by_text(re.compile(r"VEP\s+desde\s+Deuda|Contribuyente", re.I)).first.wait_for(timeout=60_000)
    arca.pausa(1.0, 2.0)


def _elegir_contribuyente(page, cuit: str) -> None:
    """Combo "Contribuyente" (puede venir ya con el único CUIT). Luego "Ver Consulta"."""
    re_c = re.compile(rf"{cuit}|{re.escape(arca.cuit_fmt(cuit))}")
    sel = page.locator("select").filter(has_text=re_c)
    if sel.count():
        op = [o for o in sel.first.locator("option").all_inner_texts() if re_c.search(o)]
        sel.first.select_option(label=op[0])
    else:
        combo = page.get_by_role("combobox").first
        if combo.count():
            actual = (combo.inner_text() or "") + (combo.get_attribute("value") or "")
            if not re_c.search(actual):
                combo.click()
                page.get_by_role("option", name=re_c).first.click(timeout=15_000)
    arca.pausa(0.5, 1.0)
    try:
        _boton(page, r"Ver\s+Consulta", 10_000).click()
    except Exception:
        pass
    page.get_by_text(re.compile(r"Vencimiento", re.I)).first.wait_for(timeout=60_000)
    arca.pausa(1.0, 2.0)
    texto = page.inner_text("body")
    if not re_c.search(texto):
        raise arca.CuitEquivocado(f"Presentación de DDJJ y Pagos: no figura {arca.cuit_fmt(cuit)}")


def _mostrar_100(page) -> None:
    try:
        s = page.locator("select").filter(has_text=re.compile(r"\b100\b")).last
        if s.count():
            s.select_option(label="100")
            arca.pausa(1.0, 2.0)
    except Exception:
        pass


def tildar_iva(page, periodo: str, vencimiento: str, importe: float | None) -> float:
    """Recorre las páginas de la deuda, tilda el renglón del IVA y devuelve su importe."""
    for _ in range(30):
        filas = page.evaluate(JS_FILAS) or []
        i = elegir_renglon(filas, periodo, vencimiento)
        if i is not None:
            imp = next((_imp(x) for x in reversed(filas[i]) if _imp(x) is not None), None)
            if importe and imp is not None and abs(imp - importe) > 1:
                raise arca.ErrorRobot(f"VEP IVA: el renglón {periodo} dice $ {imp:,.2f} y Cuentas Tributarias "
                                      f"$ {importe:,.2f}. No se generó.")
            fila = page.locator(f"[data-robot-fila='{i}']").first
            caja = fila.locator("input[type=checkbox], mat-checkbox, [role=checkbox]").first
            caja.click()
            arca.pausa(0.5, 1.0)
            if not re.search(r"\b1\s+seleccionad", page.inner_text("body"), re.I):
                raise arca.ErrorRobot("VEP IVA: después de tildar no figura '1 seleccionada'. No se generó.")
            return imp or importe or 0.0
        sig = page.locator("button[aria-label*='iguiente' i], button[aria-label*='next' i], .pagination-next, "
                           "button:has(i:text-matches('chevron_right|navigate_next'))")
        if not sig.count() or not sig.last.is_enabled():
            break
        sig.last.click()
        arca.pausa(1.0, 2.0)
    raise arca.ErrorRobot(f"VEP IVA: no está en la deuda el IVA {periodo} (19 - 19) con vencimiento {vencimiento}")


JS_A_ENVIAR = r"""(importe) => {
  const t = [...document.querySelectorAll('table')].find(x => x.offsetParent !== null && /Importe/i.test(x.innerText)
             && /CUIT/i.test(x.innerText));
  if (!t) return 'sin tabla';
  const num = s => { const m = (s || '').match(/-?[\d.]+,\d{2}/); return m ? parseFloat(m[0].replace(/\./g, '').replace(',', '.')) : null; };
  const filas = [...t.querySelectorAll('tbody tr')].filter(r => r.querySelector('input[type=checkbox]') && !/Total/i.test(r.innerText));
  const caja = r => r.querySelector('input[type=checkbox]');
  const nuestras = filas.filter(r => Math.abs((num(r.innerText) ?? -1) - importe) < 0.05);
  if (!nuestras.length) return 'no está el VEP de $ ' + importe;
  const elegida = nuestras[nuestras.length - 1];
  filas.forEach(r => { if ((r === elegida) !== caja(r).checked) caja(r).setAttribute('data-robot-cambiar', '1'); });
  return 'ok';
}"""


def a_medio_de_pago(page, importe: float) -> None:
    """Gestión VEP / VEPs a enviar: deja tildado solo nuestro VEP -> "Seleccioná medio de pago"."""
    page.get_by_text(re.compile(r"VEPs\s+a\s+enviar", re.I)).first.wait_for(timeout=90_000)
    arca.pausa(1.5, 2.5)
    r = page.evaluate(JS_A_ENVIAR, importe)
    if r != "ok":
        raise arca.ErrorRobot(f"VEP IVA (VEPs a enviar): {r}. Revisar en ARCA.")
    cambiar = page.locator("[data-robot-cambiar='1']")
    for k in range(cambiar.count()):
        cambiar.nth(k).click()
    arca.pausa(0.5, 1.0)
    _boton(page, r"Seleccion[aá]\s+medio\s+de\s+pago").click()
    page.get_by_text(re.compile(r"Seleccionar medio de pago", re.I)).first.wait_for(timeout=90_000)
    m = re.search(r"Importe Total a pagar\s*:?\s*\$\s*([\d.]+,\d{2})", page.inner_text("body"), re.I)
    total = _imp(m[1]) if m else None
    if total is not None and abs(total - importe) > 0.05:
        raise arca.ErrorRobot(f"VEP IVA: el total a pagar es $ {total:,.2f} y el IVA $ {importe:,.2f}. No se generó.")


def enviar_al_medio(page, cuit: str, medio: str) -> dict:
    vd.elegir_medio(page, medio)
    cartel = page.get_by_text(re.compile(r"Quer[eé]s enviar el VEP a", re.I)).first
    cartel.wait_for(state="visible", timeout=30_000)
    t_cartel = cartel.inner_text()
    if not re.search(vd.MEDIOS[medio][2], t_cartel, re.I):
        vd._boton(page, r"^\s*Cancelar\s*$").click()
        raise arca.ErrorRobot(f"VEP IVA: el cartel dice '{t_cartel.strip()[:80]}' y se eligió {medio}. No se generó.")
    vd._boton(page, r"^\s*Aceptar\s*$").click()
    page.get_by_text(vd.RE_VEP).first.wait_for(state="visible", timeout=90_000)
    fin = page.inner_text("body")
    vep = vd.RE_VEP.search(fin)[1]
    cuit_vep = re.search(r"CUIT\s*:?\s*(\d{2}-?\d{8}-?\d)", fin)
    if cuit_vep and re.sub(r"\D", "", cuit_vep[1]) != cuit:
        raise arca.CuitEquivocado(f"VEP {vep}: figura el CUIT {cuit_vep[1]} y no {arca.cuit_fmt(cuit)}")
    vence = re.search(r"(?:Fecha\s+de\s+)?[Vv]encimiento(?:\s+del\s+VEP)?\s*:?\s*(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2})", fin)
    try:
        captura = page.screenshot(full_page=True)
    except Exception:
        captura = None
    return {"_captura": captura, "vep": vep, "medio": medio, "vence_vep": vence[1] if vence else ""}


def correr(cuit: str, periodo: str, vencimiento: str, importe: float | None, medios: list[str],
           visible: bool = False, por: str = "") -> list[dict]:
    """Un VEP por cada medio de pago del cliente. Guarda DATOS/<cuit>/vep/<fecha>_deuda_<vep>.json (tipo iva_90),
    así aparece en la ficha junto con los demás VEP generados desde el sistema."""
    from . import almacen_claves as alm
    from . import robot_situacion_fiscal as rsf
    medios = [m for m in medios if m in vd.MEDIOS]
    if not medios:
        raise arca.ErrorRobot("el cliente no tiene cargado el medio de pago del VEP en 'Datos del cliente'")
    usuario, clave, metodo = alm.obtener_clave(cuit, "ARCA", motivo=f"VEP IVA 90 días {periodo}")
    rsf.USUARIO_ACTUAL["cuit"], rsf.USUARIO_ACTUAL["cliente"] = usuario, cuit
    hechos: list[dict] = []

    def paso(ctx, portal):
        page = arca.abrir_servicio(ctx, portal, "presentacion_ddjj_pagos")
        page.wait_for_load_state("domcontentloaded")
        for medio in medios:
            if any(h["medio"] == medio for h in hechos):
                continue
            _ir_a_desde_deuda(page)
            _elegir_contribuyente(page, cuit)
            _mostrar_100(page)
            imp = tildar_iva(page, periodo, vencimiento, importe)
            _boton(page, r"^\s*Generar\s+VEP\s*$").click()
            a_medio_de_pago(page, imp)
            v = enviar_al_medio(page, cuit, medio)
            v["importe"] = imp
            hechos.append(v)
        page.close()
        return "OK"

    arca.ejecutar(usuario, clave, [("vep_iva90", paso)], os.path.join(DATOS, cuit, "capturas"), visible, max_reingresos=2)
    if not hechos:
        raise arca.ErrorRobot("No se pudo generar el VEP del IVA")
    carpeta = os.path.join(DATOS, cuit, "vep")
    os.makedirs(carpeta, exist_ok=True)
    for v in hechos:
        base = os.path.join(carpeta, f"{date.today().isoformat()}_deuda_{v['vep']}")
        captura = v.pop("_captura", None)
        if captura:
            with open(base + ".png", "wb") as f:
                f.write(captura)
        v.update(cuit=cuit, pedido_por=por or "automático (IVA 90 días)", captura=bool(captura), tipo="iva_90",
                 creado=datetime.now().isoformat(timespec="seconds"), vence=str(vencimiento)[:10],
                 conceptos=[{"impuesto": "30 - IVA", "concepto": "19 - 19", "periodo": periodo,
                             "vencimiento": str(vencimiento)[:10], "importe": v.get("importe")}])
        with open(base + ".json", "w", encoding="utf-8") as f:
            json.dump(v, f, ensure_ascii=False, indent=1)
    return hechos
