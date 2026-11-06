"""GET_DATA — programações a agendar no Portal Ipiranga (WAAgendamento): por
padrão, as viagens planejadas no Portal Bindi Log, uma programação por viagem;
PROGRAMACOES_PATH (JSON local, formato em programacoes.example.json) é um
override manual para testes. Nunca escreve."""

import json
from datetime import date
from typing import List

from Framework.InitModule import BotConfig
from Framework.RPAFrameworkException import RPAFrameworkException
from Utils.PortalClient import fetch_planned_trips

REQUIRED_JSON_FIELDS = ("base_retiro", "placa", "motorista", "horario", "pedidos")


def get_data(config: BotConfig) -> List[dict]:
    """Cada item tem "pickup_base", "plate", "driver", "schedule_time",
    "load_date" (dd/mm/aaaa ou None = hoje) e "orders" (lista de
    {"number", "compartments": {nº compartimento: produto}}). Itens do portal
    também trazem "trip_id" e, em cada pedido, "order_id" - usados para
    devolver o resultado do agendamento."""
    if config.schedules_path:
        return _load_from_json(config.schedules_path)

    trips = fetch_planned_trips(config.portal_api_url, config.portal_api_token, config.portal_pending_days)
    items: List[dict] = []
    for trip in trips:
        trip_id = trip.get("tripId")
        if not trip.get("driverName"):
            print(f"[AVISO] Viagem {trip_id}: portal não informou o motorista da carga - ignorada.")
            continue

        orders = []
        for order in trip.get("orders", []):
            compartments = {
                str(compartment["number"]): item["productName"]
                for item in order.get("items", [])
                for compartment in item.get("compartments", [])
            }
            if not compartments:
                print(f"[AVISO] Viagem {trip_id}, pedido {order.get('orderNumber')}: sem compartimentos - ignorado.")
                continue
            orders.append(
                {
                    "order_id": order["orderId"],
                    "number": str(order["distributorOrderNumber"]).strip(),
                    "compartments": compartments,
                }
            )
        if not orders:
            print(f"[AVISO] Viagem {trip_id}: nenhum pedido com compartimentos - ignorada.")
            continue

        items.append(
            {
                "trip_id": trip_id,
                "pickup_base": config.pickup_base,
                "plate": trip["tractorPlate"].strip().upper().replace("-", ""),
                "driver": trip["driverName"].strip(),
                "schedule_time": trip["loadTime"],
                "load_date": date.fromisoformat(trip["loadDate"]).strftime("%d/%m/%Y"),
                "orders": orders,
            }
        )

    print(f"[OK] {len(items)} programação(ões) a agendar na Ipiranga.")
    return items


def _load_from_json(schedules_path: str) -> List[dict]:
    try:
        with open(schedules_path, encoding="utf-8-sig") as file:
            raw_schedules = json.load(file)
    except (OSError, ValueError) as exc:
        raise RPAFrameworkException(f"Falha ao ler {schedules_path}: {exc}") from exc

    if not isinstance(raw_schedules, list):
        raise RPAFrameworkException(
            f"{schedules_path}: o conteúdo deve ser uma lista de programações (JSON array)."
        )

    items: List[dict] = []
    for index, raw in enumerate(raw_schedules, start=1):
        missing = [name for name in REQUIRED_JSON_FIELDS if not raw.get(name)]
        if missing:
            print(
                f"[AVISO] {schedules_path} programação {index}: campo(s) obrigatório(s) "
                f"ausente(s): {', '.join(missing)} - ignorada."
            )
            continue

        orders = []
        for order in raw["pedidos"]:
            if not order.get("numero") or not order.get("compartimentos"):
                print(
                    f"[AVISO] {schedules_path} programação {index}: pedido sem número ou "
                    f"compartimentos ({order}) - ignorado."
                )
                continue
            orders.append(
                {
                    "number": str(order["numero"]).strip(),
                    "compartments": {str(k).strip(): str(v).strip() for k, v in order["compartimentos"].items()},
                }
            )
        if not orders:
            print(f"[AVISO] {schedules_path} programação {index}: nenhum pedido válido - ignorada.")
            continue

        items.append(
            {
                "pickup_base": raw["base_retiro"].strip(),
                "plate": raw["placa"].strip().upper().replace("-", ""),
                "driver": raw["motorista"].strip(),
                "schedule_time": raw["horario"].strip(),
                "load_date": (raw.get("data_carregamento") or "").strip() or None,
                "orders": orders,
            }
        )

    print(f"[OK] {len(items)} programação(ões) carregada(s) de {schedules_path} (override PROGRAMACOES_PATH).")
    return items
