"""Saldos a favor de libre disponibilidad por impuesto y período, desde Compensaciones de Cuentas Tributarias.

Recorrido mostrado por Gaby el 28/11/2026 (Nabajuma 30-71222757-1):
  Sistema de Cuentas Tributarias -> menú TRANSACCIONES -> COMPENSACIÓN -> "Detalle de saldos"
  ("Tu deuda compensable es: $ 0,00 / Tu saldo disponible es: $ 216.101.805,03") -> CONTINUAR
  -> "Selección": "Seleccioná el origen", un bloque por impuesto ("GANANCIAS SOCIEDADES  Total: $ 97.146.278,00 /
     Saldo a Favor de Libre Disponibilidad del Periodo") que se despliega con la tabla Est. | Periodo. | Saldo a favor.
SOLO CONSULTA: nunca tilda casillas ni toca CONFIRMAR / DESTINO MANUAL; al terminar, SALIR.
Gaby: lo de más de 4 años está prescripto, no se puede compensar: se guarda aparte y no suma.
Resultado: DATOS/<cuit>/saldos_compensables/<fecha>.json
"""
from __future__ import annotations

import calendar
import json
import os
import re
from datetime import date

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
ANIOS_PRESCRIPCION = 4
RE_IMPORTE = re.compile(r"-?\$?\s*(-?[\d.]+,\d{2})")


def _num(t: str) -> float:
    m = RE_IMPORTE.search(t or "")
    return float(m[1].replace(".", "").replace(",", ".")) if m else 0.0


def fin_periodo(per: str) -> date | None:
    """AAAAMM00 -> último día del mes; AAAA0000 -> 31/12 del año."""
    if not re.fullmatch(r"\d{8}", per or ""):
        return None
    a, m = int(per[:4]), int(per[4:6])
    if not m:
        return date(a, 12, 31)
    if not 1 <= m <= 12:
        return None
    return date(a, m, calendar.monthrange(a, m)[1])


def prescripto(per: str, hoy: date) -> bool:
    f = fin_periodo(per)
    if not f:
        return False
    try:
        limite = f.replace(year=f.year + ANIOS_PRESCRIPCION)
    except ValueError:                                   # 29/02
        limite = date(f.year + ANIOS_PRESCRIPCION, 2, 28)
    return limite < hoy


def leer_texto(texto: str, hoy: date) -> dict:
    """Texto de la pantalla "Selección" con los bloques desplegados -> saldos por impuesto y período."""
    impuestos, actual, previa = [], None, ""
    for linea in [l.strip() for l in texto.replace("\xa0", " ").splitlines()]:
        if not linea:
            continue
        m = re.match(r"^(.*?)\s*Total:\s*\$\s*([\d.]+,\d{2})", linea, re.I)
        if m:
            nombre = re.sub(r"^[∨˅vV>›\s]+(?=[A-ZÁÉÍÓÚÑ])", "", m[1]).strip() or previa
            actual = {"impuesto": nombre, "total_pantalla": _num(m[2]), "filas": []}
            impuestos.append(actual)
            continue
        f = re.match(r"^(\d{1,3})\s+(\d{8})\s+\$?\s*(-?[\d.]+,\d{2})\s*$", linea)
        if f and actual is not None:
            actual["filas"].append({"establecimiento": f[1], "periodo": f[2], "saldo": _num(f[3]),
                                    "prescripto": prescripto(f[2], hoy)})
            continue
        if not re.search(r"Saldo a Favor|Selecci[oó]n|Est\.|Periodo|Saldo a favor", linea, re.I):
            previa = re.sub(r"^[∨˅>›\s]+", "", linea)
    for i in impuestos:
        i["vigente"] = round(sum(f["saldo"] for f in i["filas"] if not f["prescripto"]), 2)
        i["prescripto"] = round(sum(f["saldo"] for f in i["filas"] if f["prescripto"]), 2)
        i["completo"] = abs(sum(f["saldo"] for f in i["filas"]) - i["total_pantalla"]) < 1
    return {"impuestos": impuestos,
            "vigente": round(sum(i["vigente"] for i in impuestos), 2),
            "prescripto": round(sum(i["prescripto"] for i in impuestos), 2),
            "total_pantalla": round(sum(i["total_pantalla"] for i in impuestos), 2),
            "completo": all(i["completo"] for i in impuestos)}


def leer(ctx, portal, cuit: str, hoy: date) -> dict:
    from . import robot_situacion_fiscal as rsf
    from .robot_sct_historico import _clic_texto, _marco_con
    page = arca.abrir_servicio(ctx, portal, "cuentas_tributarias")
    try:
        page.wait_for_load_state("domcontentloaded")
        rsf._elegir_cuit_sct(page, cuit, None)
        fr = rsf._frame_sct(page)
        rsf._controlar_cuit(page.inner_text("body") + fr.locator("body").inner_text(), cuit, "Cuentas Tributarias")
        try:
            _clic_texto(page, r"^\s*COMPENSACI[OÓ]N\s*$", espera_s=10)
        except arca.ErrorRobot:
            _clic_texto(page, r"^\s*TRANSACCIONES\s*$")
            _clic_texto(page, r"^\s*COMPENSACI[OÓ]N\s*$")
        fr = _marco_con(page, r"Tu saldo disponible es", espera_s=60)
        t0 = fr.locator("body").inner_text()
        m = re.search(r"Tu saldo disponible es:?\s*\$\s*([\d.]+,\d{2})", t0, re.I)
        disponible = _num(m[1]) if m else None
        fr.get_by_text(re.compile(r"^\s*CONTINUAR\s*$", re.I)).locator("visible=true").first.click()
        fr = _marco_con(page, r"Seleccion[aá] el origen|No se han localizado", espera_s=60)
        page.wait_for_timeout(1500)
        cab = fr.get_by_text(re.compile(r"Saldo a Favor de Libre Disponibilidad", re.I)).locator("visible=true")
        for i in range(cab.count()):                   # despliega cada impuesto (solo mirar)
            try:
                cab.nth(i).click()
                page.wait_for_timeout(700)
            except Exception:
                pass
        page.wait_for_timeout(1000)
        texto = fr.locator("body").inner_text()
        if arca.cuit_fmt(cuit) not in texto and cuit not in re.sub(r"\D", "", texto[:4000]):
            raise arca.CuitEquivocado(f"Compensaciones: no muestra el CUIT {arca.cuit_fmt(cuit)}")
        r = leer_texto(texto, hoy)
        r["disponible_pantalla"] = disponible
        try:
            fr.get_by_text(re.compile(r"^\s*SALIR\s*$", re.I)).locator("visible=true").first.click(timeout=5000)
        except Exception:
            pass
        return r
    finally:
        page.close()


def paso(cuit: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        r = leer(ctx, portal, cuit, hoy)
        r.update(cuit=cuit, fecha=hoy.isoformat())
        d = os.path.join(DATOS, cuit, "saldos_compensables")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        txt = lambda v: f"$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        estado.update(resultado=f"OK (a favor no prescripto {txt(r['vigente'])}; prescripto {txt(r['prescripto'])})")
        return "OK"
    return fn
