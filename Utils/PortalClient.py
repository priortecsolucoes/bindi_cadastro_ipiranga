"""Cliente HTTP do Portal Bindi Log (integração RPA Ipiranga - agendamento).
Busca as viagens já planejadas e liberadas pelo Analista (conjunto, motorista,
horário do carregamento IPIRANGA e pedidos alocados), que o agente precisa
agendar no WAAgendamento, e devolve o resultado de cada agendamento. Falha de
conexão/autenticação é pré-requisito faltando - erro controlado."""

from typing import List, Optional

import requests

from Framework.RPAFrameworkException import RPAFrameworkException

REQUEST_TIMEOUT_SECONDS = 30


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def fetch_planned_trips(base_url: str, token: str, days_ahead: int) -> List[dict]:
    """GET /api/rpa/ipiranga/planejados - viagens liberadas com carregamento
    IPIRANGA cujos compartimentos ainda estão 'Programado', com data de carga
    entre hoje e hoje + days_ahead dias. Cada viagem traz tripId, loadDate,
    loadTime, tractorPlate, driverName e orders[] (orderId,
    distributorOrderNumber, items[] com productName e compartments[])."""
    url = f"{base_url.rstrip('/')}/api/rpa/ipiranga/planejados"
    try:
        response = requests.get(
            url, headers=_headers(token), params={"days": days_ahead}, timeout=REQUEST_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise RPAFrameworkException(f"Falha ao conectar no Portal Bindi Log ({url}): {exc}") from exc

    if response.status_code != 200:
        raise RPAFrameworkException(
            f"Portal Bindi Log recusou a busca de viagens planejadas (HTTP {response.status_code}): "
            f"{response.text[:300]}"
        )

    try:
        trips = response.json().get("trips", [])
    except ValueError as exc:
        raise RPAFrameworkException(f"Resposta inválida do Portal Bindi Log ({url}): {response.text[:300]}") from exc

    print(f"[OK] {len(trips)} viagem(ns) planejada(s) recebida(s) do Portal Bindi Log.")
    return trips


def report_scheduling(
    base_url: str,
    token: str,
    trip_id: int,
    scheduling_id: Optional[str],
    order_results: List[dict],
    scheduled_time: Optional[str] = None,
) -> dict:
    """POST /api/rpa/ipiranga/agendamentos - order_results é uma lista de
    {"orderId", "scheduled", "failed"?, "observation"?, "technicalDetail"?}. O
    portal grava o resultado só na viagem (o status do pedido não muda): agendado
    = cadastro da viagem com o ID do agendamento (selo REG); não agendado =
    observação em aberto na viagem; failed = erro em aberto na viagem (selo ERRO).
    scheduled_time ("HH:MM") = horário que a Ipiranga agendou (pode diferir do planejado);
    o portal mostra em "Carregamento na distribuidora".
    Levanta RuntimeError (erro do item, não da execução)."""
    url = f"{base_url.rstrip('/')}/api/rpa/ipiranga/agendamentos"
    payload = {
        "tripId": trip_id,
        "schedulingId": scheduling_id,
        "scheduledTime": scheduled_time or None,
        "orders": order_results,
    }
    try:
        response = requests.post(url, headers=_headers(token), json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise RuntimeError(f"Falha ao conectar no Portal Bindi Log ({url}): {exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"Portal Bindi Log recusou o resultado do agendamento da viagem {trip_id} "
            f"(HTTP {response.status_code}): {response.text[:300]}"
        )
    return response.json()
