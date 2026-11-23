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


# ---------------------------------------------------------------- monotributo: categoría y tope (22/11/2026)
# Pantalla de Gaby (Gándara): monotributo.afip.gob.ar/app/Inicio.aspx -> "CUIT 20-32956192-6 / Categoría A LOCACIONES
# DE SERVICIOS"; "Facturación electrónica | 01/01/2026 al 21/11/2026"; cartel "Superaste el tope de facturación de tu
# categoria, tenelo en cuenta para la próxima recategorización"; "$12.009.410,45 Tope categoría A";
# "$26.300.000,00 Monto facturado". Aviso al encargado si superó el tope o pasó el 80 %.
CERCA_DEL_TOPE = 0.80


def _pesos_ar(t: str) -> float | None:
    t = (t or "").strip()
    return float(t.replace(".", "").replace(",", ".")) if re.fullmatch(r"-?[\d.]+,\d{2}", t) else None


def leer_monotributo(texto: str) -> dict | None:
    t = re.sub(r"\s+", " ", texto)
    m_cat = re.search(r"Categor[ií]a\s+([A-K])\b\s*([A-ZÁÉÍÓÚÑ ]{3,40}?)(?=\s+(Inicio|Pagos|Facturaci|$)|$)", t)
    m_tope = re.search(r"\$\s*([\d.]+,\d{2})\s*Tope categor[ií]a", t, re.I)
    m_fac = re.search(r"\$\s*([\d.]+,\d{2})\s*Monto facturado", t, re.I)
    if not (m_cat or m_tope or m_fac):
        return None
    m_per = re.search(r"Facturaci[oó]n electr[oó]nica\s*\|?\s*(\d{2}/\d{2}/\d{4})\s*al\s*(\d{2}/\d{2}/\d{4})", t, re.I)
    tope, fac = _pesos_ar(m_tope[1]) if m_tope else None, _pesos_ar(m_fac[1]) if m_fac else None
    return {"categoria": m_cat[1] if m_cat else "", "actividad": (m_cat[2].strip() if m_cat else ""),
            "tope": tope, "facturado": fac, "desde": m_per[1] if m_per else "", "hasta": m_per[2] if m_per else "",
            "supero_cartel": bool(re.search(r"Superaste el tope", t, re.I)),
            "proporcion": round(fac / tope, 4) if tope and fac is not None else None}


def alertas_monotributo(m: dict | None) -> list[dict]:
    if not m or m.get("proporcion") is None and not m.get("supero_cartel"):
        return []
    f = lambda x: f"$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if x is not None else "—"
    per = f" ({m['desde']} al {m['hasta']})" if m.get("desde") else ""
    if m.get("supero_cartel") or (m.get("proporcion") or 0) > 1:
        return [{"prioridad": "ALTA", "tipo": "Monotributo: superó el tope de su categoría",
                 "texto": f"Categoría {m['categoria']}: facturado {f(m['facturado'])} contra un tope de {f(m['tope'])}{per}. "
                          f"Revisar la recategorización (o la exclusión) y avisarle al cliente."}]
    if (m.get("proporcion") or 0) >= CERCA_DEL_TOPE:
        return [{"prioridad": "MEDIA", "tipo": "Monotributo: cerca del tope de su categoría",
                 "texto": f"Categoría {m['categoria']}: facturado {f(m['facturado'])}, el {m['proporcion'] * 100:.0f}% del tope "
                          f"de {f(m['tope'])}{per}."}]
    return []


def _leer_inicio_monotributo(ctx, portal, cuit: str) -> dict | None:
    """Abre Monotributo (eligiendo el representado si hace falta), lee categoría / tope / facturado y cierra."""
    try:
        page = arca.abrir_servicio(ctx, portal, "monotributo")
    except arca.RequiereIntervencion:
        return None
    try:
        page.wait_for_load_state("domcontentloaded")
        arca.pausa(1, 2)
        if re.search(r"SelecRepresentado", page.url, re.I):
            tarjeta = page.get_by_text(arca.cuit_fmt(cuit), exact=True)
            if not tarjeta.count():
                return None
            tarjeta.first.click()
            page.wait_for_load_state("domcontentloaded")
            arca.pausa(1.5, 3)
        page.wait_for_timeout(2500)                       # el tope y lo facturado se cargan con JavaScript
        texto = page.inner_text("body")
        if arca.cuit_fmt(cuit) not in texto and cuit not in re.sub(r"[\s-]", "", texto):
            return None
        return leer_monotributo(texto)
    finally:
        try:
            page.close()
        except Exception:
            pass


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
        try:                                             # categoría y tope de monotributo (22/11/2026)
            mono = _leer_inicio_monotributo(ctx, portal, cuit)
        except Exception:
            mono = None
        page, motivo = _abrir_ccma(ctx, portal, cuit, usuario)
        if page is None:
            if mono:
                d = os.path.join(DATOS, cuit, "ccma")
                os.makedirs(d, exist_ok=True)
                r0 = {"cuit": cuit, "fecha": hoy.isoformat(), "sin_ccma": True, "texto": motivo, "periodos": [],
                      "movimientos": [], "impagos": [], "deuda_impaga": 0.0, "totales": {}, "monotributo": mono,
                      "alertas": alertas_monotributo(mono)}
                with open(os.path.join(d, f"{hoy.isoformat()}.json"), "w", encoding="utf-8") as f:
                    json.dump(r0, f, ensure_ascii=False, indent=1, default=str)
                estado.update(alertas=r0["alertas"])
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
        r.update(cuit=cuit, fecha=hoy.isoformat(), monotributo=mono)
        r["alertas"] = alertas(r) + alertas_monotributo(mono)
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
