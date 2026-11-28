"""Saldos de libre disponibilidad desde Compensaciones (Gaby 28/11/2026). Uso: PYTHONPATH=. python3 robots/pruebas/test_saldos_compensables.py"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from robots import robot_saldos_compensables as s  # noqa: E402

ok = True


def chk(c, m):
    global ok
    ok &= bool(c)
    print(("✔ " if c else "✘ ") + m)


TEXTO = """Seleccioná el origen
GANANCIAS SOCIEDADES\tTotal: $ 97.146.278,00
Saldo a Favor de Libre Disponibilidad del Periodo\tSelección: $ 0,00
Est.\tPeriodo.\tSaldo a favor
0\t20220000\t$ 2.796.577,34
0\t20230000\t$ 9.731.376,02
0\t20240000\t$ 77.064.178,72
0\t20250000\t$ 7.554.145,92
GANANCIA MINIMA PRESUNTA\tTotal: $ 11.050,82
Saldo a Favor de Libre Disponibilidad del Periodo\tSelección: $ 0,00
Est.\tPeriodo.\tSaldo a favor
0\t20130000\t$ 11.050,82
IVA
Total: $ 1.494.330,06
Saldo a Favor de Libre Disponibilidad del Periodo\tSelección: $ 0,00
0\t20221000\t$ 100,00
0\t20241200\t$ 637.014,13
0\t20250100\t$ 857.215,93
No se han localizado deudas, registradas en el sistema, que puedan ser compensadas."""
HOY = date(2026, 11, 28)
r = s.leer_texto(TEXTO, HOY)
nom = [i["impuesto"] for i in r["impuestos"]]
chk(nom == ["GANANCIAS SOCIEDADES", "GANANCIA MINIMA PRESUNTA", "IVA"], f"lee los impuestos ({nom})")
chk(r["impuestos"][0]["vigente"] == 97146278.0 and r["impuestos"][0]["completo"], "Ganancias 2022 todavía no prescribió (vence 31/12/2026)")
chk(r["impuestos"][1]["vigente"] == 0 and r["impuestos"][1]["prescripto"] == 11050.82, "Mínima Presunta 2013: prescripta, no suma")
chk(r["impuestos"][2]["prescripto"] == 100.0 and r["impuestos"][2]["vigente"] == 1494230.06, "IVA 10/2022 prescripto (más de 4 años)")
chk(r["vigente"] == round(97146278.0 + 1494230.06, 2), "total a favor sin lo prescripto")
chk(not s.prescripto("20221200", HOY) and s.prescripto("20221000", HOY), "corte de 4 años contado desde el fin del período")
print("TODO OK" if ok else "FALLAS")
sys.exit(0 if ok else 1)
