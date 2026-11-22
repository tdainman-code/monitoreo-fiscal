"""Control de pagos de AUTÓNOMOS y MONOTRIBUTO: CCMA (relevado con Gaby el 17/11/2026).

Recorrido:
  Clave del propio contribuyente: Mis servicios -> "CCMA - CUENTA CORRIENTE DE CONTRIBUYENTES MONOTRIBUTISTAS Y
      AUTONOMOS" (no confundir con "CCMA - ARBA - CUENTA CORRIENTE") -> servicios2.afip.gob.ar/.../ccam/P02_ctacte.asp
  Apoderado (clave del estudio): Mis servicios -> "Monotributo" -> SelecRepresentado.aspx (tarjetas nombre + CUIT)
      -> Inicio.aspx -> "Estado de Cuenta" -> VER SALDO / PAGAR. Si debe, ARCA lo manda a la misma CCMA.
  P02_ctacte.asp  "RECÁLCULO DE DEUDA A FECHA": período desde / hasta (MM/AAAA), fecha de cálculo -> CALCULO DE DEUDA
  P04_ctacte.asp  "ÚLTIMA DEUDA CALCULADA":
      Total Saldo Deudor (Obligación Mensual + Accesorios) | Total Saldo Acreedor (Obligación Mensual + Accesorios)
      Tabla: Detalle | Período | Impuesto | Concepto | Subcpto | Descripción | Fecha Movimiento | Debe | Haber | Saldo
      Cada período cierra con una fila "Saldo" (saldo a la fecha; entre paréntesis y en rojo = DEBE).
      La "Fecha Movimiento" de la fila "Obligacion Mensual ..." es el vencimiento de ese período.
      Importes en formato 159,563.00 (coma de miles, punto decimal).
Criterio (igual que cuotas de planes): impago recién a los 4 días corridos del vencimiento (el pago tarda en verse).
Solo consulta: no toca "VOLANTE DE PAGO" (el VEP de monotributo/autónomos se programa cuando se releve esa pantalla).
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta

from . import arca

DATOS = os.environ.get("ROBOTS_DATOS", "/var/lib/robots/datos")
DIAS_GRACIA = 4
MESES = 36

JS_FILAS = r"""() => {
  const t = [...document.querySelectorAll('table')].filter(x => /Fecha\s*Movimiento/i.test(x.textContent)
              && /Descripci/i.test(x.textContent));
  const tabla = t.length ? t[t.length - 1] : null;      // la más interna que tiene el encabezado
  if (!tabla) return [];
  return [...tabla.querySelectorAll('tr')].map(r => [...r.cells].map(c => c.textContent.replace(/\s+/g, ' ').trim()));
}"""


def _num(t: str) -> float | None:
    t = (t or "").strip()
    if not re.search(r"\d", t):
        return None
    neg = t.startswith("(") or t.startswith("-")
    v = float(re.sub(r"[^\d.]", "", t.replace(",", "")) or 0)
    return -v if neg else v


def _fecha(t: str) -> date | None:
    try:
        return datetime.strptime(t.strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def leer_totales(texto: str) -> dict:
    """Cabecera 'ÚLTIMA DEUDA CALCULADA'. Los dos bloques (deudor / acreedor) tienen 'Obligación Mensual' y 'Accesorios'."""
    t = re.sub(r"\s+", " ", texto)
    out = {}
    m = re.search(r"Total Saldo Deudor:?\s*([\d.,()-]+)", t, re.I)
    out["deudor"] = _num(m[1]) if m else None
    m = re.search(r"Total Saldo Acreedor:?\s*([\d.,()-]+)", t, re.I)
    out["acreedor"] = _num(m[1]) if m else None
    obl = re.findall(r"Obligaci[oó]n Mensual:?\s*([\d.,()-]+)", t, re.I)
    acc = re.findall(r"Accesorios:?\s*([\d.,()-]+)", t, re.I)
    out["deudor_obligacion"] = _num(obl[0]) if obl else None
    out["deudor_accesorios"] = _num(acc[0]) if acc else None
    out["acreedor_obligacion"] = _num(obl[1]) if len(obl) > 1 else None
    out["acreedor_accesorios"] = _num(acc[1]) if len(acc) > 1 else None
    m = re.search(r"Tipo de Contribuyente:?\s*([A-ZÁÉÍÓÚ |]+?)\s+\d{2}/\d{2}/\d{4}", t)
    out["tipo"] = m[1].strip() if m else ""
    return out


def analizar(filas: list[list[str]], hoy: date | None = None) -> dict:
    """Filas crudas de la tabla -> movimientos y estado de cada período."""
    hoy = hoy or date.today()
    movs, periodos = [], {}
    for c in filas:
        c = [x for x in c]
        # la fila trae 11 celdas (+, detalle, período...) o 10 (sin el +): se alinea por la celda del período
        i = next((k for k, x in enumerate(c) if re.fullmatch(r"\d{2}/\d{4}", x)), None)
        if i is None or len(c) < i + 9:
            continue
        per, imp, cpto, sub, desc, fmov, debe, haber, saldo = c[i:i + 9]
        p = periodos.setdefault(per, {"periodo": per, "impuestos": set(), "vencimiento": None, "debe": 0.0,
                                      "haber": 0.0, "saldo": None, "obligacion": 0.0})
        if desc.lower() == "saldo":
            p["saldo"] = _num(saldo)
            continue
        m = {"periodo": per, "impuesto": imp, "concepto": cpto, "subconcepto": sub, "descripcion": desc,
             "fecha": fmov, "debe": _num(debe) or 0.0, "haber": _num(haber) or 0.0}
        movs.append(m)
        p["impuestos"].add(imp)
        p["debe"] += m["debe"]
        p["haber"] += m["haber"]
        if re.match(r"obligaci[oó]n mensual", desc, re.I) and m["debe"]:
            p["obligacion"] += m["debe"]
            f = _fecha(fmov)
            if f and (p["vencimiento"] is None or f < p["vencimiento"]):
                p["vencimiento"] = f
    lista = []
    for per, p in periodos.items():
        saldo = p["saldo"] if p["saldo"] is not None else round(p["haber"] - p["debe"], 2)
        v = p["vencimiento"]
        if saldo >= -0.005:
            estado = "pagado" if saldo < 0.005 else "a favor"
        elif v is None or hoy <= v:
            estado = "a vencer"
        elif hoy <= v + timedelta(days=DIAS_GRACIA):
            estado = "vencido (esperando que se acredite el pago)"
        else:
            estado = "IMPAGO"
        lista.append({"periodo": per, "impuestos": ", ".join(sorted(p["impuestos"])), "vencimiento": v.isoformat() if v else None,
                      "obligacion": round(p["obligacion"], 2), "pagado": round(p["haber"], 2),
                      "saldo": round(saldo, 2), "estado": estado,
                      "dias_vencido": (hoy - v).days if v and hoy > v else 0})
    lista.sort(key=lambda x: (x["periodo"][3:], x["periodo"][:2]), reverse=True)
    impagos = [x for x in lista if x["estado"] == "IMPAGO"]
    return {"periodos": lista, "movimientos": movs, "impagos": impagos,
            "deuda_impaga": round(-sum(x["saldo"] for x in impagos), 2)}


def alertas(r: dict) -> list[dict]:
    out = []
    quien = (r.get("totales") or {}).get("tipo") or "Autónomos / Monotributo"
    if r["impagos"]:
        pers = ", ".join(x["periodo"] for x in r["impagos"][:6]) + ("…" if len(r["impagos"]) > 6 else "")
        out.append({"prioridad": "ALTA", "tipo": "Autónomos / Monotributo impago",
                    "texto": f"{quien.title()}: {len(r['impagos'])} período(s) impago(s) ({pers}) por "
                             f"$ {r['deuda_impaga']:,.2f} (más de {DIAS_GRACIA} días del vencimiento)".replace(",", "X")
                             .replace(".", ",").replace("X", ".")})
    acc = (r.get("totales") or {}).get("deudor_accesorios") or 0
    if acc > 0 and not r["impagos"]:
        out.append({"prioridad": "MEDIA", "tipo": "Autónomos / Monotributo: intereses",
                    "texto": f"Quedan intereses (accesorios) sin pagar por $ {acc:,.2f}".replace(",", "X")
                             .replace(".", ",").replace("X", ".")})
    return out


def _abrir_ccma(ctx, portal, cuit: str, usuario: str):
    """Devuelve la página de la CCMA del cliente, o (None, motivo) si no corresponde."""
    if usuario == cuit:
        try:
            return arca.abrir_servicio(ctx, portal, "ccma"), ""
        except arca.RequiereIntervencion:
            pass                                       # sin el servicio en "Mis servicios": se prueba por Monotributo
    try:
        page = arca.abrir_servicio(ctx, portal, "monotributo")
    except arca.RequiereIntervencion:
        return None, "sin servicio (no es monotributista/autónomo o no está delegado)"
    page.wait_for_load_state("domcontentloaded")
    arca.pausa(1, 2)
    if re.search(r"SelecRepresentado", page.url, re.I):
        tarjeta = page.get_by_text(arca.cuit_fmt(cuit), exact=True)
        if not tarjeta.count():
            page.close()
            return None, "no figura entre los representados de Monotributo"
        tarjeta.first.click()
        page.wait_for_load_state("domcontentloaded")
        arca.pausa(1.5, 3)
    boton = page.get_by_text(re.compile(r"VER SALDO\s*/\s*PAGAR", re.I))
    if not boton.count():
        page.close()
        return None, "Monotributo: no aparece 'VER SALDO / PAGAR'"
    antes = set(ctx.pages)
    boton.first.click()
    page.wait_for_timeout(4000)
    nuevas = [p for p in ctx.pages if p not in antes]
    destino = nuevas[-1] if nuevas else page
    destino.wait_for_load_state("domcontentloaded")
    return destino, ""


def leer(page, cuit: str, hoy: date) -> dict:
    texto = page.inner_text("body")
    if "ccam" not in page.url.lower() and not re.search(r"LCULO DE DEUDA A FECHA|DEUDA CALCULADA", texto, re.I):
        # Monotributo sin deuda: ARCA no redirige a la CCMA. Se guarda lo que muestra para relevarlo.
        return {"sin_ccma": True, "texto": re.sub(r"\s+", " ", texto)[:1500], "periodos": [], "movimientos": [],
                "impagos": [], "deuda_impaga": 0.0, "totales": {}}
    if re.search(r"LCULO DE DEUDA A FECHA", texto, re.I) and not re.search(r"DEUDA CALCULADA", texto, re.I):
        desde = (hoy.replace(day=1) - timedelta(days=MESES * 30.5)).strftime("%m/%Y")
        campos = page.locator("input[type=text]")
        if campos.count() >= 2:
            campos.nth(0).fill(desde)
            campos.nth(1).fill(hoy.strftime("%m/%Y"))
        page.locator("input[value*='CALCULO DE DEUDA' i], button:has-text('CALCULO DE DEUDA')").first.click()
        page.wait_for_load_state("domcontentloaded")
        page.get_by_text(re.compile(r"DEUDA CALCULADA", re.I)).first.wait_for(timeout=60_000)
        arca.pausa(1, 2)
    # "Mostrar N períodos": el mayor que ofrezca, y Consultar
    try:
        sel = page.locator("select").filter(has=page.locator("option", has_text=re.compile(r"^\s*\d+\s*$")))
        if sel.count():
            ops = [o for o in sel.last.locator("option").all_inner_texts() if o.strip().isdigit()]
            if ops:
                sel.last.select_option(label=max(ops, key=lambda x: int(x)).strip())
                page.wait_for_load_state("domcontentloaded")
                page.wait_for_timeout(1500)
                cons = page.locator("input[value='Consultar' i], button:has-text('Consultar')")
                if cons.count():
                    cons.first.click()
                    page.wait_for_load_state("domcontentloaded")
                    page.wait_for_timeout(1500)
    except Exception:
        pass
    texto = page.inner_text("body")
    # 22/11/2026: la CCMA puede mostrar el CUIT sin guiones (20205744283): se acepta en los dos formatos
    if arca.cuit_fmt(cuit) not in texto and cuit not in re.sub(r"[\s-]", "", texto):
        otros = sorted(set(re.findall(r"\d{2}-\d{8}-\d", texto)) - {arca.cuit_fmt(cuit)})
        raise arca.CuitEquivocado(f"CCMA muestra {', '.join(otros) or 'otro CUIT'} en lugar de {arca.cuit_fmt(cuit)}")
    filas, vistos = [], set()
    for _ in range(12):                                   # páginas siguientes (flecha), mientras traigan períodos nuevos
        nuevas = [f for f in page.evaluate(JS_FILAS) if tuple(f) not in vistos]
        if not nuevas:
            break
        vistos.update(tuple(f) for f in nuevas)
        filas += nuevas
        sig = page.locator("a:has(img[src*='flecha' i]), a:has(img[src*='sig' i]), a:has(img[src*='next' i]), "
                           "a[title*='siguiente' i], input[type=image][src*='flecha' i]")
        if not sig.count():
            break
        try:
            sig.last.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1200)
        except Exception:
            break
    r = analizar(filas, hoy)
    r["totales"] = leer_totales(texto)
    return r


def paso(cuit: str, usuario: str, estado: dict):
    def fn(ctx, portal):
        hoy = date.today()
        if cuit.startswith("3"):
            estado.update(resultado="no corresponde (persona jurídica)")
            return "no corresponde"
        page, motivo = _abrir_ccma(ctx, portal, cuit, usuario)
        if page is None:
            estado.update(resultado=motivo)
            return motivo
        try:
            r = leer(page, cuit, hoy)
            carpeta = os.path.join(DATOS, cuit, "capturas")
            os.makedirs(carpeta, exist_ok=True)
            with open(os.path.join(carpeta, f"ccma_{hoy.isoformat()}.html"), "w", encoding="utf-8") as fh:
                fh.write(page.content())
        finally:
            page.close()
        r.update(cuit=cuit, fecha=hoy.isoformat())
        r["alertas"] = alertas(r)
        d = os.path.join(DATOS, cuit, "ccma")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=1, default=str)
        res = ("sin deuda (Monotributo no derivó a la CCMA)" if r.get("sin_ccma")
               else f"OK ({len(r['periodos'])} períodos, {len(r['impagos'])} impagos)")
        estado.update(resultado=res, alertas=r["alertas"])
        return res
    return fn


def correr(cuit, periodo, usuario, clave, metodo="Directo", visible=False, **_):
    estado: dict = {}
    arca.ejecutar(usuario, clave, [("ccma", paso(cuit, usuario, estado))], os.path.join(DATOS, cuit, "capturas"), visible)
    return {"cuit": cuit, "ccma": estado.get("resultado"), "archivos": {"ccma": {"alertas": estado.get("alertas", [])}}}
