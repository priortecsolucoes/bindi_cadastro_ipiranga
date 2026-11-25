"""PROCESS — login no Portal de Agendamento Ipiranga e, para cada programação
(viagem planejada no Portal Bindi Log), abre a alocação da Base de Retiro,
aplica os filtros, agenda os pedidos e devolve o resultado ao portal. Erro em
uma programação não interrompe as demais."""

from typing import List

from Automation.IpirangaPortal import SchedulingError, apply_filters, login, open_allocation, schedule_orders
from Framework.InitModule import BotConfig
from Framework.RPAFrameworkException import RPAFrameworkException
from Log.LogModule import (
    STATUS_CONFIRMED_WITHOUT_ID,
    STATUS_ERROR,
    STATUS_NOT_SCHEDULED,
    STATUS_REPORT_FAILED,
    STATUS_SCHEDULED,
    STATUS_SIMULATED,
    LogModule,
)
from Utils.DriverFactory import create_driver, load_cookies, save_cookies
from Utils.PortalClient import report_scheduling

COOKIES_PATH = "ipiranga_cookies.json"
TECHNICAL_ERROR_MESSAGE = (
    "Falha técnica do agente ao agendar no Portal Ipiranga. Agende manualmente se for urgente e acione o "
    "suporte da automação."
)


def process_items(items: List[dict], config: BotConfig, log_module: LogModule) -> None:

    if not items:
        print("[INFO] Nenhuma programação a agendar na Ipiranga - não abrindo o navegador.")
        return

    driver = create_driver(
        headless=config.headless,
        user_data_dir=config.chrome_user_data_dir,
        profile_directory=config.chrome_profile_directory,
        user_agent=config.chrome_user_agent,
        window_size=config.chrome_window_size,
        chrome_binary_path=config.chrome_binary_path,
    )

    logged_in = False
    try:
        load_cookies(driver, COOKIES_PATH)
        try:
            home_url = login(driver, config.username, config.password)
        except Exception as exc:
            screenshot_path = _save_screenshot(driver, "erro_login.png")
            raise RPAFrameworkException(f"Falha no login do WAAgendamento: {exc} (screenshot: {screenshot_path})") from exc
        logged_in = True
        save_cookies(driver, COOKIES_PATH)

        for index, item in enumerate(items, start=1):
            print("=" * 55)
            trip_label = f"viagem {item['trip_id']} | " if item.get("trip_id") else ""
            print(
                f"[INFO] Programação {index}/{len(items)}: {trip_label}base {item['pickup_base']} | "
                f"placa {item['plate']} | motorista {item['driver']} | {item['load_date'] or 'hoje'} "
                f"{item['schedule_time']}"
            )
            for order in item["orders"]:
                compartments = ", ".join(f"{number}: {product}" for number, product in order["compartments"].items())
                print(f"[INFO]   Pedido {order['number']} | {compartments}")
            try:
                open_allocation(driver, home_url, item["pickup_base"])
                apply_filters(driver, item["load_date"])
                result = schedule_orders(driver, item)
            except Exception as exc:  # noqa: BLE001 - erro por programação não pode parar o loop
                screenshot_path = _save_screenshot(driver, f"erro_agendamento_{index}.png")
                user_message = exc.user_message if isinstance(exc, SchedulingError) else TECHNICAL_ERROR_MESSAGE
                print(f"[ERRO] Falha na programação da placa {item['plate']}: {user_message}")
                print(f"[INFO]   Detalhe técnico: {exc} (screenshot: {screenshot_path})")
                technical_detail = f"{exc} (screenshot: {screenshot_path})"
                detail = f"{user_message} | Detalhe técnico: {technical_detail}"
                if item.get("trip_id"):
                    try:
                        _report_error_to_portal(config, item, user_message, technical_detail)
                    except Exception as report_exc:  # noqa: BLE001 - registra no CSV e segue
                        print(f"[ERRO] Falha ao informar o erro da placa {item['plate']} ao Portal Bindi Log: {report_exc}")
                        detail = f"{detail} | Retorno ao portal falhou: {report_exc}"
                log_module.write_result(item, STATUS_ERROR, detail=detail)
                continue

            if item.get("dry_run"):
                status = STATUS_SIMULATED
                print(f"[OK] Simulação da placa {item['plate']} percorreu os passos 1-8 sem erro.")
            elif not result["scheduled_orders"]:
                status = STATUS_NOT_SCHEDULED
                print(f"[AVISO] Nenhum pedido da placa {item['plate']} pôde ser programado.")
            elif result["scheduling_id"]:
                status = STATUS_SCHEDULED
                print(f"[OK] Placa {item['plate']} agendada - ID {result['scheduling_id']}.")
            else:
                status = STATUS_CONFIRMED_WITHOUT_ID
                print(f"[AVISO] Placa {item['plate']} confirmada, mas o ID do agendamento não foi capturado.")

            observations = {**result["order_notes"], **result["skipped_orders"]}
            detail = " | ".join(f"Pedido {number}: {text}" for number, text in observations.items())
            if result.get("scheduled_time") and result["scheduled_time"] != item["schedule_time"]:
                time_note = f"Agendado às {result['scheduled_time']} (planejado {item['schedule_time']})"
                detail = f"{time_note} | {detail}" if detail else time_note
            if item.get("trip_id"):
                try:
                    _report_to_portal(config, item, result)
                except Exception as exc:  # noqa: BLE001 - o agendamento já foi feito; registra e segue
                    # Não reverte o status: na Ipiranga o agendamento existe. Precisa de ajuste manual no portal.
                    print(f"[ERRO] Placa {item['plate']} agendada, mas o retorno ao Portal Bindi Log falhou: {exc}")
                    detail = f"{status} - retorno ao portal falhou: {exc}" + (f" | {detail}" if detail else "")
                    status = STATUS_REPORT_FAILED

            log_module.write_result(
                item,
                status,
                scheduled_orders=result["scheduled_orders"],
                scheduling_id=result["scheduling_id"] or "",
                detail=detail,
            )
    finally:
        # Só com login confirmado: cookies de uma tentativa falha sobrescreveriam uma sessão boa.
        if logged_in:
            save_cookies(driver, COOKIES_PATH)
        try:
            driver.quit()
        except Exception as exc:  # noqa: BLE001 - falha ao encerrar não pode mascarar um erro anterior
            print(f"[AVISO] Falha ao encerrar o Chrome ao final da execução (ignorado): {exc}")


def _report_to_portal(config: BotConfig, item: dict, result: dict) -> None:
    order_results = []
    for order in item["orders"]:
        if order["number"] in result["scheduled_orders"]:
            order_result = {"orderId": order["order_id"], "scheduled": True}
            if order["number"] in result["order_notes"]:
                order_result["observation"] = result["order_notes"][order["number"]]
            order_results.append(order_result)
        else:
            observation = result["skipped_orders"].get(order["number"], "Não programado pelo agente.")
            order_results.append({"orderId": order["order_id"], "scheduled": False, "observation": observation})

    response = report_scheduling(
        config.portal_api_url, config.portal_api_token, item["trip_id"], result["scheduling_id"], order_results,
        result.get("scheduled_time"),
    )
    print(
        f"[OK] Resultado enviado ao Portal Bindi Log: {response.get('registered', 0)} pedido(s) registrado(s), "
        f"{response.get('alreadyRegistered', 0)} já registrado(s), {response.get('notes', 0)} observação(ões)."
    )


def _report_error_to_portal(config: BotConfig, item: dict, user_message: str, technical_detail: str) -> None:
    """Erro em aberto na viagem (selo ERRO no quadro de viagens, com 'Detalhes
    técnicos'); o status do pedido não muda. A viagem só volta no planejados
    depois que o usuário alterar e liberar de novo ou clicar 'Tentar de novo'."""
    order_results = [
        {
            "orderId": order["order_id"],
            "scheduled": False,
            "failed": True,
            "observation": user_message,
            "technicalDetail": technical_detail[:1000],
        }
        for order in item["orders"]
    ]
    response = report_scheduling(config.portal_api_url, config.portal_api_token, item["trip_id"], None, order_results)
    print(
        f"[OK] Erro informado ao Portal Bindi Log: erro na viagem {item['trip_id']} ({response.get('failed', 0)} pedido(s)), "
        f"{response.get('notes', 0)} observação(ões)."
    )


def _save_screenshot(driver, path: str) -> str:
    try:
        driver.save_screenshot(path)
        return path
    except Exception as exc:  # noqa: BLE001 - screenshot é diagnóstico, não pode mascarar o erro original
        print(f"[AVISO] Falha ao salvar screenshot {path}: {exc}")
        return "-"
