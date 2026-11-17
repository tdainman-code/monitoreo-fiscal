"""Motor de recordatorios (reglas definidas por el estudio).

Reglas:
  SECLO / audiencias laborales : aviso al recibir + recordatorio 2 días hábiles antes del plazo.
  Deuda intimada / VEP impago  : recordatorio periódico (1 o 2 por semana) hasta que figure pagado.
  Cuotas de planes             : 1° venc. día 16, 2° venc. día 26 (o hábil siguiente).
                                 Control de pago 4 días corridos después de cada vencimiento
                                 (20 y 30) por la demora del banco en informar al organismo.
                                 - Impaga al control del 1° venc -> recordar al cliente que el
                                   2° débito es el día 26.
                                 - Impaga al control del 2° venc -> ALERTA riesgo de caducidad
                                   (estudio + cliente).
Los feriados se cargan desde feriados.txt (una fecha AAAA-MM-DD por línea).
"""
import os
from dataclasses import dataclass
from datetime import date, timedelta

DEMORA_BANCO_DIAS = 4
RECORDATORIOS_DEUDA_POR_SEMANA = 2   # 1 o 2, configurable
DIAS_HABILES_ANTES_SECLO = 2


def cargar_feriados(path=None) -> set[date]:
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "feriados.txt")
    if not os.path.exists(path):
        return set()
    return {date.fromisoformat(l.strip()) for l in open(path) if l.strip() and not l.startswith("#")}


FERIADOS = cargar_feriados()


def es_habil(d: date) -> bool:
    return d.weekday() < 5 and d not in FERIADOS


def habil_siguiente(d: date) -> date:
    while not es_habil(d):
        d += timedelta(days=1)
    return d


def restar_habiles(d: date, n: int) -> date:
    while n:
        d -= timedelta(days=1)
        if es_habil(d):
            n -= 1
    return d


@dataclass
class Aviso:
    fecha: date
    destino: str        # "estudio", "cliente" o "estudio+cliente"
    prioridad: str      # "ALTA", "Media", "Baja"
    texto: str


def avisos_seclo(recibido: date, plazo: date, asunto: str) -> list[Aviso]:
    return [
        Aviso(recibido, "estudio", "ALTA", f"Nueva notificación SECLO: {asunto}. Plazo {plazo:%d/%m/%Y}."),
        Aviso(restar_habiles(plazo, DIAS_HABILES_ANTES_SECLO), "estudio", "ALTA",
              f"Recordatorio SECLO: {asunto}. Plazo {plazo:%d/%m/%Y} (en {DIAS_HABILES_ANTES_SECLO} días hábiles)."),
    ]


def controles_cuota(plan: str, cuota: int, anio: int, mes: int, importe: float) -> list[dict]:
    """Devuelve los dos controles de pago de una cuota (fecha de control y qué hacer si está impaga)."""
    v1 = habil_siguiente(date(anio, mes, 16))
    v2 = habil_siguiente(date(anio, mes, 26))
    return [
        {"control": v1 + timedelta(days=DEMORA_BANCO_DIAS), "vencimiento": v1,
         "si_impaga": Aviso(v1 + timedelta(days=DEMORA_BANCO_DIAS), "cliente", "Media",
                            f"Plan {plan}: la cuota {cuota} (${importe:,.2f}) no se debitó el {v1:%d/%m}. "
                            f"El segundo intento de débito es el {v2:%d/%m}: verificá fondos en la cuenta.")},
        {"control": v2 + timedelta(days=DEMORA_BANCO_DIAS), "vencimiento": v2,
         "si_impaga": Aviso(v2 + timedelta(days=DEMORA_BANCO_DIAS), "estudio+cliente", "ALTA",
                            f"Plan {plan}: la cuota {cuota} sigue impaga después del 2° vencimiento "
                            f"({v2:%d/%m}). Riesgo de caducidad del plan.")},
    ]


def recordatorios_deuda(desde: date, hasta: date, descripcion: str) -> list[Aviso]:
    """Recordatorios periódicos de deuda intimada o VEP impago (lunes y jueves, o solo lunes)."""
    dias = {0, 3} if RECORDATORIOS_DEUDA_POR_SEMANA == 2 else {0}
    out, d = [], desde
    while d <= hasta:
        if d.weekday() in dias and es_habil(d):
            out.append(Aviso(d, "estudio+cliente", "ALTA", f"Recordatorio: {descripcion} sigue impaga."))
        d += timedelta(days=1)
    return out


if __name__ == "__main__":
    print("Plan W742451, cuota 1 (nov-2026):")
    for c in controles_cuota("W742451", 1, 2026, 11, 1118790.22):
        print(f"  venc {c['vencimiento']:%a %d/%m} -> control {c['control']:%a %d/%m}: {c['si_impaga'].texto}")
    print("\nSECLO con plazo 27/11/2026:")
    for a in avisos_seclo(date(2026, 11, 4), date(2026, 11, 27), "Audiencia de conciliación"):
        print(f"  {a.fecha:%a %d/%m} [{a.prioridad}] {a.texto}")
    print("\nVEP impago desde 16/11 (2 por semana, hasta fin de mes):")
    for a in recordatorios_deuda(date(2026, 11, 16), date(2026, 11, 30), "VEP IVA 09/2026"):
        print(f"  {a.fecha:%a %d/%m}")
