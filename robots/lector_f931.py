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


# Importes que pueden NO figurar en el F931 (19/11/2026, caso TALLPIR S A: 2 directores con sueldo NO remunerativo,
# "SIN CONTRATO LRT" y "SIN CONTRATO SCVO"): si faltan valen 0 y se anotan en "Campos sin dato", en vez de
# descartar todo el formulario (antes el mes quedaba "no se pudo leer" y la relación D/C no tomaba los sueldos).
_OPCIONALES = {
    "Remuneración total (Rem. 1)": r"Suma de Rem\. 1:? " + NUM,
    "Aportes S.S. (a1)": r"a1 - Total de aportes S\.S\.:? " + NUM,
    "Aportes O.S. (a1)": r"a1 - Total de aportes O\.S\.:? " + NUM,
    "Contribuciones S.S. total (b1)": r"b1 - Total de contribuciones:? " + NUM,
    "Detracción art. 23 Ley 27.541 (b3)": r"b3 - Detracción art\. 23 Ley 27\.541:? " + NUM,
    "Contribuciones S.S. (subtotal)": r"Subtotal contribuciones S\.S\.:? " + NUM,
    "  de ello SIPA": r"Contribuciones S\.S\. SIPA:? " + NUM,
    "  de ello No SIPA": r"Contribuciones S\.S\. No SIPA:? " + NUM,
    "Contribuciones O.S. (subtotal)": r"Subtotal contribuciones O\.S\.:? " + NUM,
    "ART (L.R.T. total)": r"L\.R\.T\. total a pagar:? " + NUM,
    "Seguro de vida obligatorio": r"S\.C\.V\.O\. a Pagar:? " + NUM,
    "RENATRE": r"Total Contribuciones RENATRE:? " + NUM,
    "Pago a cuenta Dec. 394 (informativo)": r"Pago a Cuenta Dec\. 394:? " + NUM,
    "Retenciones aplicadas (informativo)": r"Total retenciones:? " + NUM,
}
# Conceptos no remunerativos (sumas que no integran Rem. 1). Etiqueta a confirmar con el formulario real.
_NO_REM = re.compile(r"(?:Suma de |Total (?:de )?)?(?:conceptos |importes? |montos? )?no remunerativ\w*[^\n\d-]{0,40}?" + NUM, re.I)


def leer_f931(texto: str) -> dict:
    t = re.sub(r"[ \t]+", " ", texto)
    per = re.search(r"(\d{2})/(\d{4}) Servicios Eventuales", t)
    d = {
        "Periodo": f"{per.group(2)}-{per.group(1)}" if per else "",
        "CUIT": re.search(r"C\.U\.I\.T\. ([\d-]+)", t).group(1),
        "Secuencia": int(re.search(r"Rect\. \(1/9\): (\d)", t).group(1)),
    }
    m = re.search(r"Empleados en nómina: (\d+)", t)
    d["Empleados"] = int(m.group(1)) if m else 0
    faltan = []
    for k, patron in _OPCIONALES.items():
        try:
            d[k] = _buscar(t, patron)
        except ValueError:
            d[k] = 0.0
            faltan.append(k.strip())
    nr = [_n(x) for x in _NO_REM.findall(t)]
    d["No remunerativo"] = max(nr) if nr else 0.0
    d["Remuneración total (con no remunerativos)"] = d["Remuneración total (Rem. 1)"] + d["No remunerativo"]
    d["Total aportes (retenidos al empleado)"] = d["Aportes S.S. (a1)"] + d["Aportes O.S. (a1)"]
    d["TOTAL CARGAS SOCIALES"] = (d["Contribuciones S.S. (subtotal)"] + d["Contribuciones O.S. (subtotal)"]
                                  + d["ART (L.R.T. total)"] + d["Seguro de vida obligatorio"]
                                  + d["RENATRE"])
    # Control: SIPA + No SIPA = subtotal S.S.
    dif = d["  de ello SIPA"] + d["  de ello No SIPA"] - d["Contribuciones S.S. (subtotal)"]
    d["Control SIPA+NoSIPA"] = "OK" if abs(dif) < 1 else f"DIFERENCIA {dif:,.2f}"
    if faltan:
        d["Campos sin dato"] = faltan
    if d["Empleados"] and not d["Remuneración total (con no remunerativos)"]:
        d["Aviso"] = ("Hay empleados y no se encontró remuneración (ni Rem. 1 ni no remunerativa): revisar el formulario "
                      "(texto guardado) y avisar para sumar el casillero que corresponda")
    return d


if __name__ == "__main__":
    d = leer_f931(open(sys.argv[1], encoding="utf-8").read())
    for k, v in d.items():
        print(f"{k:42s} {v:>18,.2f}" if isinstance(v, float) else f"{k:42s} {str(v):>18}")
