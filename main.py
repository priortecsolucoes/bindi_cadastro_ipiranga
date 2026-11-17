"""Orquestrador do bot de agendamento do Portal Ipiranga (WAAgendamento).
Pipeline FrameworkRE: INIT -> GET_DATA -> PROCESS -> END."""

from Framework import EndModule, GetDataModule, InitModule, ProcessModule
from Framework.RPAFrameworkException import RPAFrameworkException
from Log.LogModule import LogModule
from Utils.AgentMonitor import monitored_run

# TESTE: enquanto o portal não tem viagem Ipiranga planejada. Com True, usa
# SIMULATED_ITEMS no lugar do GET_DATA (sem trip_id: o portal não é consultado
# nem recebe resultado) e dry_run para antes de Confirmar no WAAgendamento.
# Troque pelos dados de um pedido real liberado na Ipiranga para percorrer as telas.
USE_SIMULATED_ITEMS = False
SIMULATED_ITEMS = [
    {
        # Pedido 61975 (POSTO ZEPPE GRAND PRIX LTDA, Contagem): itens 3, 4, 5 e 10,
        # ORIGINAL ETANOL, 3.000 L cada (12.000 L), entrega 07/10/2026, Registrado.
        # HGD0J09 tem 3 compartimentos de 5.000 L: só Comp-1 e Comp-2 (10.000 L) -
        # o portal recusa um compartimento maior que o saldo restante (2.000 L).
        # Comp-3 fica vazio (popup "compartimento vazio" > Sim no Confirmar).
        "pickup_base": "Base De Betim",
        "plate": "HGD0J09",
        "driver": "ANDERSON FABIANO LOPES",
        "schedule_time": "16:30",
        "load_date": "07/10/2026",
        "orders": [
            {"number": "61975", "compartments": {"1": "ORIGINAL ETANOL", "2": "ORIGINAL ETANOL"}},
        ],
        "dry_run": True,
    }
]


AGENT_CODE = "ipiranga_cadastro"
AGENT_NAME = "Ipiranga · agendamento"


def run() -> None:
    with monitored_run(AGENT_CODE, AGENT_NAME):
        _run_pipeline()


def _run_pipeline() -> None:
    log_module = None
    try:
        config = InitModule.initialize()
        if USE_SIMULATED_ITEMS:
            print(f"[AVISO] Usando {len(SIMULATED_ITEMS)} programação(ões) simulada(s) de main.py (teste).")
            items = SIMULATED_ITEMS
        else:
            items = GetDataModule.get_data(config)
        log_module = LogModule()
        ProcessModule.process_items(items, config, log_module)
    except RPAFrameworkException as exc:
        print(f"[ERRO Framework] {exc}")
    finally:
        EndModule.finalize(log_module)


if __name__ == "__main__":
    run()
