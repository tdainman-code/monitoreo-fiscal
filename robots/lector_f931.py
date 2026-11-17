"""Lector del F931 de Declaración en Línea (texto de ver_formulario.aspx).

El robot obtiene el texto desde:
  https://serviciossegsoc.afip.gob.ar/djproforma/app/consultar/ver_formulario.aspx?Periodo=AAAAMM&SecDJVig=000
(SecDJVig = secuencia: 000 original, 001 rectificativa 1, ...; tomar la vigente/última)

Criterio (indicado por Gabriel): cargas sociales del cuadro del medio (secciones I, II, VI y VII),
importes ANTES de deducciones (retenciones, pago a cuenta Dec. 394 / Ley 25.413, etc.),
no los "montos que se ingresan" de la sección VIII.

Uso: python3 lector_f931.py archivo.txt
"""
import re
import sys

NUM = r"(-?[\d\.]+,\d{2})"


def _n(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _buscar(texto: str, patron: str, grupo: int = 1, ocurrencia: int = 0) -> float:
    m = list(re.finditer(patron, texto))
    if len(m) <= ocurrencia:
        raise ValueError(f"No se encontró: {patron}")
    return _n(m[ocurrencia].group(grupo))


def leer_f931(texto: str) -> dict:
    t = re.sub(r"[ \t]+", " ", texto)
    per = re.search(r"(\d{2})/(\d{4}) Servicios Eventuales", t)
    d = {
        "Periodo": f"{per.group(2)}-{per.group(1)}" if per else "",
        "CUIT": re.search(r"C\.U\.I\.T\. ([\d-]+)", t).group(1),
        "Secuencia": int(re.search(r"Rect\. \(1/9\): (\d)", t).group(1)),
        "Empleados": int(re.search(r"Empleados en nómina: (\d+)", t).group(1)),
        "Remuneración total (Rem. 1)": _buscar(t, r"Suma de Rem\. 1: " + NUM),
        "Aportes S.S. (a1)": _buscar(t, r"a1 - Total de aportes S\.S\. " + NUM),
        "Aportes O.S. (a1)": _buscar(t, r"a1 - Total de aportes O\.S\. " + NUM),
        "Contribuciones S.S. total (b1)": _buscar(t, r"b1 - Total de contribuciones " + NUM, ocurrencia=0),
        "Detracción art. 23 Ley 27.541 (b3)": _buscar(t, r"b3 - Detracción art\. 23 Ley 27\.541 " + NUM),
        "Contribuciones S.S. (subtotal)": _buscar(t, r"Subtotal contribuciones S\.S\. " + NUM),
        "  de ello SIPA": _buscar(t, r"Contribuciones S\.S\. SIPA " + NUM),
        "  de ello No SIPA": _buscar(t, r"Contribuciones S\.S\. No SIPA " + NUM),
        "Contribuciones O.S. (subtotal)": _buscar(t, r"Subtotal contribuciones O\.S\. " + NUM),
        "ART (L.R.T. total)": _buscar(t, r"L\.R\.T\. total a pagar " + NUM),
        "Seguro de vida obligatorio": _buscar(t, r"S\.C\.V\.O\. a Pagar: " + NUM),
        "RENATRE": _buscar(t, r"Total Contribuciones RENATRE " + NUM),
        "Pago a cuenta Dec. 394 (informativo)": _buscar(t, r"Pago a Cuenta Dec\. 394: " + NUM),
        "Retenciones aplicadas (informativo)": _buscar(t, r"Total retenciones " + NUM),
    }
    d["Total aportes (retenidos al empleado)"] = d["Aportes S.S. (a1)"] + d["Aportes O.S. (a1)"]
    d["TOTAL CARGAS SOCIALES"] = (d["Contribuciones S.S. (subtotal)"] + d["Contribuciones O.S. (subtotal)"]
                                  + d["ART (L.R.T. total)"] + d["Seguro de vida obligatorio"]
                                  + d["RENATRE"])
    # Control: SIPA + No SIPA = subtotal S.S.
    dif = d["  de ello SIPA"] + d["  de ello No SIPA"] - d["Contribuciones S.S. (subtotal)"]
    d["Control SIPA+NoSIPA"] = "OK" if abs(dif) < 1 else f"DIFERENCIA {dif:,.2f}"
    return d


if __name__ == "__main__":
    d = leer_f931(open(sys.argv[1], encoding="utf-8").read())
    for k, v in d.items():
        print(f"{k:42s} {v:>18,.2f}" if isinstance(v, float) else f"{k:42s} {v:>18}")
