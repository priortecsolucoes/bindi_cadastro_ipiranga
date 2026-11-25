"""Passos de automação do Portal de Agendamento Ipiranga (WAAgendamento) via Selenium:
login e alocação de pedidos (agendamento) por veículo/motorista.

Fluxo (ER, tópico 11 "Fluxo Cadastro de Transporte - Distribuidora Ipiranga"):
Login > 1 Tela Principal (ícone de ficha na linha da Base de Betim) > 2 Tela de
pedidos ("Alocar Pedido") > 3 Filtros (FOB, Apenas Liberados, data de carga .. +5) +
Lupa > 4 Marca os pedidos do mesmo motorista/caminhão + "Alocar Pedido" >
5 Data Saída + Placa + lupa da placa > 6 Motorista > 7 Horário > 8 Para cada
pedido, rádio da linha 'Registrado' (se só houver 'Em Análise', usa essa e
registra observação) + produto <-> compartimento; saldo insuficiente registra
observação > 9 Confirmar (popup de compartimento vazio -> "Sim") > salva o ID do
agendamento.

Seletores do login e da tela Alocar Pedido (filtros + grade #grid-pedidos)
confirmados via DOM real no projeto Bind-Rpa (monitoramento Ipiranga). Os
demais (Filiais e telas dos passos 4 em diante) ainda não foram confirmados
via DOM real - estão nas constantes abaixo para ajuste.
"""

import re
import time
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from selenium import webdriver
from selenium.common.exceptions import InvalidElementStateException, NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

BASE_URL = "https://sites2.ipiranga.com.br/WAAgendamento"
LOGIN_URL = f"{BASE_URL}/usuario/login"

DEFAULT_TIMEOUT = 30
# Data Final do filtro = data de carga da programação + FILTER_DAYS_AHEAD.
FILTER_DAYS_AHEAD = 4

# Tela Filiais (colunas: ícone, Nome, Código, Núcleo). Compara só Nome e Código -
# o mesmo nome aparece na coluna Núcleo de outras filiais.
FILIAIS_TITLE_XPATH = "//*[normalize-space(text())='Filiais']"
BASE_ROW_XPATH = "//tr[normalize-space(td[2])='{base}' or normalize-space(td[3])='{base}']"
ROW_ICON_XPATH = "./td[1]//*[self::a or self::button or self::i or self::span or self::img]"
# Menu superior (confirmado via DOM): <div id="apps-menu"> ... <a href="/WAAgendamento/alocacaoPedido/consultar">.
# Sem a classe 'menucolor': ela é adicionada depois por JS do portal e nem sempre está lá.
ALLOCATE_ORDER_MENU_SELECTOR = "#apps-menu a[href*='alocacaoPedido/consultar']"

# Campo "Pesquisar" acima da grade (confirmado via DOM): filtra a grade enquanto se digita
# (ng-change="vm.pesquisar()"). Só existe depois da lupa, quando a pesquisa trouxe pedidos.
GRID_SEARCH_SELECTOR = "input[type='search'][ng-model='vm.busca']"
# Grade #grid-pedidos (confirmada): [checkbox, Filial, Pedido, Item, ...]
ORDER_CHECKBOXES_XPATH = "//table[@id='grid-pedidos']//tbody/tr[normalize-space(td[3])='{number}']//input[@type='checkbox']"
# Botão do formulário, não o link do menu superior com o mesmo texto.
ALLOCATE_ORDER_BUTTON_XPATH = (
    "//*[self::button or self::input or self::a][contains(normalize-space(.), 'Alocar Pedido') or @value='Alocar Pedido']"
    "[not(contains(@href,'alocacaoPedido'))][not(ancestor::*[@id='apps-menu-wrapper' or @id='apps-menu'])]"
)

DEPARTURE_DATE_XPATH = "//label[contains(., 'Data Sa')]/following::input[1]"
PLATE_INPUT_XPATH = "//label[contains(., 'Placa')]/following::input[1]"
PLATE_SEARCH_XPATH = "//label[contains(., 'Placa')]/following::*[contains(@class,'search') or contains(@class,'lupa') or contains(@title,'Pesquisar')][1]"
DRIVER_SELECT_XPATH = "//label[contains(., 'Motorista')]/following::select[1]"
SCHEDULE_TIME_SELECT_XPATH = "//label[contains(., 'Hor')]/following::select[1]"
TIME_PATTERN = re.compile(r"\b([01]\d|2[0-3]):[0-5]\d\b")

# Tabela "Pedidos Selecionados": rádio na linha do pedido.
ORDER_RADIO_XPATH = "//tr[td[normalize-space(.)='{number}']]//input[@type='radio']"
# Seção "Compartimentos" (confirmada via DOM): um card por compartimento
# (div[ng-repeat="compartimento in vm.alocacao.compartimentos"]) com rodapé
# "Comp-N: capacidade" e o combo Produto (select[ng-model="compartimento.grupoProduto"]).
# Opções: "ORIGINAL ETANOL - Registrado", value "61975:10000300:Registrado:000000"
# (pedido:código do produto:situação:...) - é aqui que aparece Registrado x Em Análise.
COMPARTMENT_SELECT_XPATH = (
    "//div[@ng-repeat='compartimento in vm.alocacao.compartimentos']"
    "[.//*[contains(normalize-space(text()), 'Comp-{compartment}:')]]"
    "//select[@ng-model='compartimento.grupoProduto']"
)
ERROR_MESSAGE_XPATH = (
    "//*[contains(@class,'alert-danger') or contains(@class,'msg-error') or contains(@class,'toast-error')]"
    "[not(ancestor-or-self::*[@id='msg-erro'])]"
)

# Botão Confirmar da alocação (confirmado via DOM): <a class="btn btn-prime" ng-click="vm.confirmar()">.
CONFIRM_BUTTON_SELECTOR = "a.btn-prime[ng-click='vm.confirmar()']"
YES_BUTTON_XPATH = "//*[self::button or self::a][normalize-space(.)='Sim']"

# Retorno da lupa da Placa (confirmados via DOM):
# - erro na página (ex.: "Veículo não cadastrado..."): <ipp-mensagem id="msg-alocacao-pedido"> > div.msg-error
# - modal "Alerta" (ex.: Cert. de Registro e Lic. vencidos) com botão Confirmar
PAGE_ERROR_SELECTOR = "#msg-alocacao-pedido div.msg-error"
ALERT_MODAL_SELECTOR = "#modal-mensagem .modal-window"
ALERT_MODAL_BODY_SELECTOR = "#modal-mensagem .modal-body-wrapper"
ALERT_MODAL_CONFIRM_SELECTOR = "#modal-mensagem a.btn-prime.ico-ok-option"
PLATE_SEARCH_RESULT_TIMEOUT = 5
SCHEDULING_ID_XPATH = "//*[contains(., 'Agendamento') and (contains(., 'nº') or contains(., 'ID') or contains(., 'número'))]"

LOADING_TEXT_XPATH = "//*[contains(text(),'Aguarde alguns instantes')]"


# --------------------------------------------------------------------------
# Login
# --------------------------------------------------------------------------
class SchedulingError(RuntimeError):
    """Erro de negócio no agendamento (motorista não cadastrado, horário
    indisponível...): user_message vai para o Portal Bindi Log, para o Analista
    tratar; a mensagem completa (str) mantém o detalhe técnico para o log."""

    def __init__(self, user_message: str, technical_detail: str = ""):
        super().__init__(f"{user_message} ({technical_detail})" if technical_detail else user_message)
        self.user_message = user_message


def login(driver: webdriver.Chrome, username: str, password: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """Abre o portal e, se a sessão do perfil do bot não estiver mais válida,
    autentica. Devolve a URL da tela principal (home), ponto de partida de
    cada programação. Logado = tela Filiais ou menu superior visível (com
    sessão reaproveitada o portal pode abrir /home/index só com o menu)."""
    print("[INFO] Acessando o Portal de Agendamento Ipiranga...")
    driver.get(BASE_URL)

    try:
        WebDriverWait(driver, timeout).until(lambda d: _is_logged_in(d) or d.find_elements(By.ID, "codigoUsuario"))
    except TimeoutException as exc:
        raise RuntimeError(
            f"Nem a tela de login nem a tela principal apareceram a tempo. {_page_diagnosis(driver)}"
        ) from exc

    if _is_logged_in(driver):
        print("[OK] Sessão reaproveitada do perfil do bot - login não foi necessário.")
        return driver.current_url

    username_field = driver.find_element(By.ID, "codigoUsuario")
    username_field.clear()
    username_field.send_keys(username)
    password_field = driver.find_element(By.ID, "senha")
    password_field.clear()
    password_field.send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "input[type='submit'].btn-prime").click()

    try:
        WebDriverWait(driver, timeout).until(_is_logged_in)
    except TimeoutException as exc:
        raise RuntimeError(
            f"Login não confirmado: a tela principal não carregou. Verifique usuário/senha. {_page_diagnosis(driver)}"
        ) from exc

    print("[OK] Login realizado com sucesso.")
    return driver.current_url


def _is_logged_in(driver: webdriver.Chrome) -> bool:
    return bool(
        driver.find_elements(By.XPATH, FILIAIS_TITLE_XPATH)
        or driver.find_elements(By.CSS_SELECTOR, ALLOCATE_ORDER_MENU_SELECTOR)
    )


def _page_diagnosis(driver: webdriver.Chrome) -> str:
    """URL atual + avisos visíveis, para o erro dizer o motivo (credencial
    recusada, bloqueio da Akamai...). Ignora o 'Browser incompatível'
    (#msg-erro), que só some quando o CSS do portal carrega."""
    try:
        if "access denied" in (driver.title or "").lower():
            return f"Bloqueado pela Akamai (Access Denied). URL atual: {driver.current_url}"
        messages = [
            element.text.strip()
            for element in driver.find_elements(By.CSS_SELECTOR, ".msg-error, .js-msg-area, .alert")
            if element.is_displayed() and element.text.strip()
            and not element.find_elements(By.XPATH, "ancestor-or-self::*[@id='msg-erro']")
        ]
        detail = f"Mensagem do portal: {' | '.join(dict.fromkeys(messages))}. " if messages else ""
        return f"{detail}URL atual: {driver.current_url}"
    except Exception as exc:  # noqa: BLE001 - diagnóstico não pode mascarar o erro original
        return f"URL atual: {driver.current_url} (diagnóstico falhou: {exc})"


# --------------------------------------------------------------------------
# Passos 1-3: tela principal > Alocar Pedido > filtros
# --------------------------------------------------------------------------
def open_allocation(driver: webdriver.Chrome, home_url: str, pickup_base: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Parte sempre da tela principal: ícone de ficha da Base de Retiro (se a
    tela Filiais estiver aberta) > menu Alocar Pedido."""
    driver.get(home_url)
    try:
        WebDriverWait(driver, timeout).until(_is_logged_in)
    except TimeoutException as exc:
        raise RuntimeError(f"Tela principal do portal não carregou. {_page_diagnosis(driver)}") from exc

    if driver.find_elements(By.XPATH, FILIAIS_TITLE_XPATH):
        print(f"[INFO] 1. Tela principal > ficha da base {pickup_base}")
        try:
            row = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.XPATH, BASE_ROW_XPATH.format(base=pickup_base)))
            )
        except TimeoutException as exc:
            raise SchedulingError(
                f"Base de retiro '{pickup_base}' não encontrada no Portal Ipiranga.", _page_diagnosis(driver)
            ) from exc
        try:
            icon = row.find_element(By.XPATH, ROW_ICON_XPATH)
        except NoSuchElementException as exc:
            raise RuntimeError(f"Ícone de ficha não encontrado na linha da base {pickup_base}.") from exc
        _js_click(driver, icon)
        _wait_loading(driver)
    else:
        print("[AVISO] 1. Tela Filiais não exibida (home só com o menu) - seguindo direto pelo menu Alocar Pedido.")

    print("[INFO] 2. Menu > Alocar Pedido")
    _click(driver, By.CSS_SELECTOR, ALLOCATE_ORDER_MENU_SELECTOR)

    try:
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.ID, "fob")))
    except TimeoutException as exc:
        raise RuntimeError(f"Tela 'Alocar e Agendar Pedido' não carregou. {_page_diagnosis(driver)}") from exc
    _wait_loading(driver)


def apply_filters(driver: webdriver.Chrome, load_date: Optional[str], timeout: int = DEFAULT_TIMEOUT) -> None:
    """Filtra Tipo de Operação = FOB, Situação = Apenas Liberados, Data Inicial
    = data de carga da programação (dd/mm/aaaa; None = hoje), Data Final =
    Data Inicial + FILTER_DAYS_AHEAD, e clica na lupa."""
    start_date = datetime.strptime(load_date, "%d/%m/%Y").date() if load_date else date.today()
    end_date = start_date + timedelta(days=FILTER_DAYS_AHEAD)
    print(f"[INFO] 3. Filtros FOB / Apenas Liberados / {start_date:%d/%m/%Y} .. {end_date:%d/%m/%Y}")

    fob_radio = driver.find_element(By.ID, "fob")
    if not fob_radio.is_selected():
        _js_click(driver, fob_radio)
    released_only = driver.find_element(By.ID, "ehApenasLiberados")
    if not released_only.is_selected():
        _js_click(driver, released_only)
    _fill_date_field(driver, "data-inicial", start_date.strftime("%d/%m/%Y"))
    _fill_date_field(driver, "data-final", end_date.strftime("%d/%m/%Y"))

    search_button = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "a.ico-search")))
    _js_click(driver, search_button)
    _wait_loading(driver)


def _fill_date_field(driver: webdriver.Chrome, element_id: str, value: str) -> None:
    _fill_input(driver, driver.find_element(By.ID, element_id), value)


def _fill_input(driver: webdriver.Chrome, field: WebElement, value: str) -> None:
    """Campos de data do portal são readonly (datepicker) e clear()/send_keys()
    derrubam 'invalid element state'. Nesses casos o valor vai pelo setter
    nativo do <input> + eventos input/change, que é o que o ng-model do
    AngularJS escuta (mesma solução do Bind-Rpa)."""
    if field.is_enabled() and not field.get_attribute("readonly"):
        try:
            field.clear()
            field.send_keys(value)
            return
        except InvalidElementStateException:
            pass
    driver.execute_script(
        """
        const el = arguments[0];
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(el, arguments[1]);
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        """,
        field,
        value,
    )
    if field.get_attribute("value") != value:
        raise RuntimeError(
            f"Campo somente leitura não aceitou o valor {value!r} (ficou {field.get_attribute('value')!r})."
        )


# --------------------------------------------------------------------------
# Passos 4-9: alocação, compartimentos e confirmação
# --------------------------------------------------------------------------
def schedule_orders(driver: webdriver.Chrome, item: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Aloca os pedidos do item no veículo/motorista/horário e confirma.
    Devolve {"scheduled_orders", "skipped_orders" ({nº pedido: observação}),
    "order_notes" ({nº pedido: observação} de pedidos programados com
    ressalva), "scheduling_id"}; se nenhum pedido puder ser programado, não
    confirma e scheduling_id fica None."""
    order_numbers = [order["number"] for order in item["orders"]]
    skipped_orders: Dict[str, str] = {}
    order_notes: Dict[str, str] = {}

    print(f"[INFO] 4. Selecionando pedidos {', '.join(order_numbers)}")
    for number in order_numbers:
        try:
            search_field = WebDriverWait(driver, timeout).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, GRID_SEARCH_SELECTOR))
            )
        except TimeoutException as exc:
            raise SchedulingError(
                f"Nenhum pedido FOB liberado na Ipiranga entre a data de carga {item['load_date'] or 'hoje'} e "
                f"{FILTER_DAYS_AHEAD} dias depois. Confira a liberação dos pedidos na Ipiranga.",
                f"campo 'Pesquisar' da grade não apareceu. {_page_diagnosis(driver)}",
            ) from exc
        _fill_input(driver, search_field, number)
        _wait_loading(driver)
        try:
            # O filtro é por "contém" (61975 também traz 619750): marca só as linhas cujo
            # Pedido é exatamente o número - cada produto do pedido é uma linha.
            checkboxes = WebDriverWait(driver, timeout).until(
                lambda d: d.find_elements(By.XPATH, ORDER_CHECKBOXES_XPATH.format(number=number))
            )
        except TimeoutException as exc:
            raise SchedulingError(
                f"Pedido {number} não está liberado na Ipiranga (FOB, entre a data de carga e {FILTER_DAYS_AHEAD} "
                f"dias depois). Confira o número do pedido e a liberação na Ipiranga."
            ) from exc
        for checkbox in checkboxes:
            if not checkbox.is_selected():
                _js_click(driver, checkbox)
    _click(driver, By.XPATH, ALLOCATE_ORDER_BUTTON_XPATH)

    departure_date = item["load_date"] or date.today().strftime("%d/%m/%Y")
    print(f"[INFO] 5. Data Saída {departure_date} / placa {item['plate']}")
    _type(driver, DEPARTURE_DATE_XPATH, departure_date)
    _type(driver, PLATE_INPUT_XPATH, item["plate"])
    _click(driver, By.XPATH, PLATE_SEARCH_XPATH)  # preenche os campos do veículo automaticamente
    _handle_plate_search_result(driver, item["plate"])

    print(f"[INFO] 6. Motorista {item['driver']}")
    _select(
        driver,
        DRIVER_SELECT_XPATH,
        item["driver"],
        not_found_message=(
            f"Motorista '{item['driver']}' não está cadastrado na Ipiranga para a transportadora. "
            f"Cadastre o motorista no Portal Ipiranga ou troque o motorista da viagem."
        ),
    )

    print(f"[INFO] 7. Horário {item['schedule_time']}")
    scheduled_time = _select_schedule_time(driver, item["schedule_time"], departure_date)

    print("[INFO] 8. Compartimentos por pedido")
    scheduled_orders: List[str] = []
    for order in item["orders"]:
        number = order["number"]
        _click(driver, By.XPATH, ORDER_RADIO_XPATH.format(number=number))
        for compartment, product in order["compartments"].items():
            print(f"[INFO]   Comp-{compartment}: {product}")
            if _select_compartment_product(driver, compartment, product, number, timeout):
                order_notes[number] = "Produto só disponível como 'Em Análise' na Ipiranga - programado mesmo assim."

        error_messages = [e.text.strip() for e in driver.find_elements(By.XPATH, ERROR_MESSAGE_XPATH) if e.is_displayed() and e.text.strip()]
        if error_messages:
            message = " | ".join(error_messages)
            if "SALDO" in message.upper():
                skipped_orders[number] = f"Saldo insuficiente na Ipiranga ({message})."
                order_notes.pop(number, None)
                print(f"[AVISO] Pedido {number}: saldo insuficiente - não programado.")
                continue
            raise SchedulingError(f"A Ipiranga recusou o pedido {number}: {message}")
        scheduled_orders.append(number)

    if not scheduled_orders:
        return {
            "scheduled_orders": [], "skipped_orders": skipped_orders, "order_notes": order_notes,
            "scheduling_id": None, "scheduled_time": scheduled_time,
        }

    if item.get("dry_run"):
        print("[AVISO] Programação simulada (dry_run): parando antes de Confirmar - nada foi agendado na Ipiranga.")
        return {
            "scheduled_orders": scheduled_orders, "skipped_orders": skipped_orders, "order_notes": order_notes,
            "scheduling_id": None, "scheduled_time": scheduled_time,
        }

    print("[INFO] 9. Confirmar")
    _click(driver, By.CSS_SELECTOR, CONFIRM_BUTTON_SELECTOR)
    try:
        yes_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, YES_BUTTON_XPATH)))
        print("[INFO] Popup de compartimento vazio > Sim")
        _js_click(driver, yes_button)
        _wait_loading(driver)
    except TimeoutException:
        pass  # popup só aparece quando sobra compartimento vazio

    scheduling_id = _capture_scheduling_id(driver)
    return {
        "scheduled_orders": scheduled_orders,
        "skipped_orders": skipped_orders,
        "order_notes": order_notes,
        "scheduling_id": scheduling_id,
        "scheduled_time": scheduled_time,
    }


def _select_schedule_time(driver: webdriver.Chrome, wanted_time: str, departure_date: str) -> str:
    """Combo Horários: prefere a opção que é o horário planejado ou começa nele;
    só usa uma que apenas contém o horário (ex.: faixa "07:30 - 08:00") se não houver
    outra. Devolve o horário "HH:MM" que ficou selecionado (o início da opção) -
    é o que a Ipiranga agendou e vai para o portal (scheduledTime)."""
    try:
        select = Select(
            WebDriverWait(driver, DEFAULT_TIMEOUT).until(
                EC.presence_of_element_located((By.XPATH, SCHEDULE_TIME_SELECT_XPATH))
            )
        )
    except TimeoutException as exc:
        raise RuntimeError(f"Combo Horários não apareceu em {DEFAULT_TIMEOUT}s. URL atual: {driver.current_url}") from exc

    options = [o for o in select.options if TIME_PATTERN.search(o.text)]
    option = (
        next((o for o in options if o.text.strip() == wanted_time), None)
        or next((o for o in options if o.text.strip().startswith(wanted_time)), None)
        or next((o for o in options if wanted_time in o.text), None)
    )
    if option is None:
        raise SchedulingError(
            f"Horário {wanted_time} não está disponível na Ipiranga em {departure_date}. "
            "Escolha outro horário de carregamento para a viagem.",
            f"opções do combo: {[o.text.strip() for o in select.options]}",
        )
    option.click()
    _wait_loading(driver)

    selected_text = Select(driver.find_element(By.XPATH, SCHEDULE_TIME_SELECT_XPATH)).first_selected_option.text.strip()
    match = TIME_PATTERN.search(selected_text)
    if not match:
        raise RuntimeError(f"Combo Horários ficou em '{selected_text}', sem horário reconhecível (esperado {wanted_time}).")
    scheduled_time = match.group(0)
    if scheduled_time != wanted_time:
        print(f"[AVISO] Horário {wanted_time} agendado na Ipiranga como '{selected_text}' (início {scheduled_time}).")
    else:
        print(f"[OK] Horário selecionado: {selected_text}")
    return scheduled_time


def _handle_plate_search_result(driver: webdriver.Chrome, plate: str) -> None:
    """A lupa da Placa pode devolver erro na página (ex.: veículo não
    cadastrado -> não dá para seguir) ou o modal 'Alerta' (ex.: documentos do
    veículo vencidos -> o portal permite continuar com Confirmar)."""
    def visible_text(selector: str) -> str:
        return " ".join(
            e.text.strip() for e in driver.find_elements(By.CSS_SELECTOR, selector) if e.is_displayed() and e.text.strip()
        )

    try:
        WebDriverWait(driver, PLATE_SEARCH_RESULT_TIMEOUT).until(
            lambda d: visible_text(PAGE_ERROR_SELECTOR) or visible_text(ALERT_MODAL_SELECTOR)
        )
    except TimeoutException:
        return  # placa aceita sem aviso

    page_error = visible_text(PAGE_ERROR_SELECTOR)
    if page_error:
        raise SchedulingError(f"Placa {plate} recusada pela Ipiranga: {page_error}")

    alert_text = visible_text(ALERT_MODAL_BODY_SELECTOR) or visible_text(ALERT_MODAL_SELECTOR)
    print(f"[AVISO] Alerta do portal para a placa {plate}: {alert_text} - clicando em Confirmar.")
    _click(driver, By.CSS_SELECTOR, ALERT_MODAL_CONFIRM_SELECTOR)


def _select_compartment_product(
    driver: webdriver.Chrome, compartment: str, product: str, order_number: str, timeout: int
) -> bool:
    """Escolhe no card do compartimento a opção do produto deste pedido: a
    'Registrado'; se só houver 'Em Análise', usa essa (ER) e devolve True para
    o chamador registrar a observação."""
    xpath = COMPARTMENT_SELECT_XPATH.format(compartment=compartment)
    try:
        select = Select(WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath))))
    except TimeoutException as exc:
        raise SchedulingError(
            f"O veículo não tem o compartimento {compartment} na Ipiranga. Confira os compartimentos da viagem.",
            "card 'Comp-N' não encontrado na seção Compartimentos",
        ) from exc

    candidates = [
        option for option in select.options
        if (option.get_attribute("value") or "").startswith(f"{order_number}:")
        and option.text.strip().upper().startswith(product.strip().upper())
    ]
    registered = [o for o in candidates if "REGISTRADO" in o.text.upper()]
    in_analysis = [o for o in candidates if "ANÁLISE" in o.text.upper() or "ANALISE" in o.text.upper()]
    chosen = (registered or in_analysis or [None])[0]
    if chosen is None:
        raise SchedulingError(
            f"Produto '{product}' do pedido {order_number} não está disponível na Ipiranga para o compartimento "
            f"{compartment}.",
            f"opções do combo: {[o.text.strip() for o in select.options]}",
        )

    select.select_by_value(chosen.get_attribute("value"))
    _wait_loading(driver)
    if not registered:
        print(f"[AVISO] Pedido {order_number}: '{product}' só está como 'Em Análise' - usando essa e registrando observação.")
        return True
    return False


def _capture_scheduling_id(driver: webdriver.Chrome) -> Optional[str]:
    try:
        text = WebDriverWait(driver, DEFAULT_TIMEOUT).until(
            EC.visibility_of_element_located((By.XPATH, SCHEDULING_ID_XPATH))
        ).text
    except TimeoutException:
        text = driver.find_element(By.TAG_NAME, "body").text
    match = re.search(r"[Aa]gendamento\D{0,30}(\d{4,})", text)
    return match.group(1) if match else None


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _js_click(driver: webdriver.Chrome, element: WebElement) -> None:
    # Clique via JS: o clique nativo pode ser interceptado por elementos vizinhos (layout responsivo).
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'}); arguments[0].click();", element)


def _click(driver: webdriver.Chrome, by: str, selector: str, timeout: int = DEFAULT_TIMEOUT) -> WebElement:
    try:
        element = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((by, selector)))
    except TimeoutException as exc:
        raise RuntimeError(f"Elemento não ficou clicável em {timeout}s: {selector}. URL atual: {driver.current_url}") from exc
    _js_click(driver, element)
    _wait_loading(driver)
    return element


def _type(driver: webdriver.Chrome, xpath: str, text: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    try:
        field = WebDriverWait(driver, timeout).until(EC.visibility_of_element_located((By.XPATH, xpath)))
    except TimeoutException as exc:
        raise RuntimeError(f"Campo não apareceu em {timeout}s: {xpath}. URL atual: {driver.current_url}") from exc
    _fill_input(driver, field, text)


def _select(
    driver: webdriver.Chrome,
    xpath: str,
    text: str,
    timeout: int = DEFAULT_TIMEOUT,
    not_found_message: Optional[str] = None,
) -> None:
    """Seleciona pelo texto exato; se não houver, pela primeira opção que contém
    o texto. Sem a opção, levanta SchedulingError com not_found_message (quando
    informado) - opção ausente é dado da viagem, não falha técnica."""
    try:
        select = Select(WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.XPATH, xpath))))
    except TimeoutException as exc:
        raise RuntimeError(f"Combo não apareceu em {timeout}s: {xpath}. URL atual: {driver.current_url}") from exc
    try:
        select.select_by_visible_text(text)
    except NoSuchElementException:
        option = next((o for o in select.options if text.upper() in o.text.upper()), None)
        if option is None:
            options = [o.text for o in select.options]
            if not_found_message:
                raise SchedulingError(not_found_message, f"opções do combo: {options}")
            raise RuntimeError(f"Opção '{text}' não encontrada no combo {xpath}: {options}")
        option.click()
    _wait_loading(driver)


def _wait_loading(driver: webdriver.Chrome, timeout: int = DEFAULT_TIMEOUT) -> None:
    """O portal exibe 'Aguarde alguns instantes...' durante chamadas
    assíncronas (Angular $http). Se não sumir a tempo, segue - o próximo
    passo falha com contexto se a tela realmente não carregou."""
    time.sleep(0.5)  # dá tempo do overlay aparecer
    try:
        WebDriverWait(driver, timeout).until_not(
            lambda d: any(e.is_displayed() for e in d.find_elements(By.XPATH, LOADING_TEXT_XPATH))
        )
    except TimeoutException:
        print(f"[AVISO] 'Aguarde alguns instantes' não sumiu em {timeout}s - seguindo.")
