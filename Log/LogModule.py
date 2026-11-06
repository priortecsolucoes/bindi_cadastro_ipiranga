"""LogModule — único módulo que persiste o resultado local dos agendamentos.
Mantém o CSV de saída aberto durante toda a execução. Fecha no EndModule."""

import csv
from collections import Counter
from datetime import datetime
from typing import List, Optional

from Framework.RPAFrameworkException import RPAFrameworkException

STATUS_SCHEDULED = "AGENDADO"
STATUS_CONFIRMED_WITHOUT_ID = "CONFIRMADO_SEM_ID"
STATUS_NOT_SCHEDULED = "NAO_PROGRAMADO"
STATUS_ERROR = "ERRO"
STATUS_REPORT_FAILED = "ERRO_RETORNO_PORTAL"
STATUS_SIMULATED = "SIMULADO"

FIELDNAMES = [
    "processed_at", "trip_id", "pickup_base", "plate", "driver", "schedule_time", "load_date", "order_numbers", "scheduled_orders", "scheduling_id", "status", "detail",
]


class LogModule:
    def __init__(self, output_path: str = "agendamentos_ipiranga.csv") -> None:
        self._output_path = output_path
        try:
            self._file = open(output_path, "w", newline="", encoding="utf-8")
        except OSError as exc:
            raise RPAFrameworkException(f"Não foi possível abrir {output_path} para escrita (aberto no Excel?): {exc}") from exc
        self._writer = csv.DictWriter(self._file, fieldnames=FIELDNAMES)
        self._writer.writeheader()
        self._status_count: Counter = Counter()

    def write_result(
        self,
        item: dict,
        status: str,
        scheduled_orders: Optional[List[str]] = None,
        scheduling_id: str = "",
        detail: str = "",
    ) -> None:
        self._writer.writerow(
            {
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "trip_id": item.get("trip_id", ""),
                "pickup_base": item["pickup_base"],
                "plate": item["plate"],
                "driver": item["driver"],
                "schedule_time": item["schedule_time"],
                "load_date": item.get("load_date") or "",
                "order_numbers": " ".join(o["number"] for o in item["orders"]),
                "scheduled_orders": " ".join(scheduled_orders or []),
                "scheduling_id": scheduling_id,
                "status": status,
                "detail": detail,
            }
        )
        self._file.flush()
        self._status_count[status] += 1

    def close(self) -> None:
        self._file.close()
        total = sum(self._status_count.values())
        print(
            f"[OK] {total} programação(ões) gravada(s) em {self._output_path} "
            f"({self._status_count[STATUS_SCHEDULED]} agendada(s), "
            f"{self._status_count[STATUS_CONFIRMED_WITHOUT_ID]} confirmada(s) sem ID, "
            f"{self._status_count[STATUS_NOT_SCHEDULED]} não programada(s), "
            f"{self._status_count[STATUS_REPORT_FAILED]} sem retorno ao portal, "
            f"{self._status_count[STATUS_SIMULATED]} simulada(s), "
            f"{self._status_count[STATUS_ERROR]} com erro)."
        )
