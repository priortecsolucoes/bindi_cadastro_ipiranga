"""
Automação do Portal de Agendamento Ipiranga (WAAgendamento) com Selenium.

Fluxo (conforme fluxograma):
  Login -> 1 Tela Principal (ícone na linha da Base de Retiro) -> 2 Tela de pedidos ("Alocar Pedido")
  -> 3 Filtros (FOB, Apenas liberados, Hoje .. Hoje+2) + Lupa -> 4 Seleciona pedidos do mesmo
  motorista/veículo + "Alocar Pedido" -> 5 Data + Placa + lupa da placa -> 6 Motorista -> 7 Horário
  -> 8 Compartimentos por pedido (Registrado x Em Análise / Saldo insuficiente)
  -> 9 Confirmar (popup de compartimento vazio -> "Sim") -> Salvar ID do agendamento.

Uso:
  pip install selenium python-dotenv
  # .env com IPIRANGA_USUARIO e IPIRANGA_SENHA
  python ipiranga_agendamento.py programacoes.json

Formato de programacoes.json (uma entrada por veículo/motorista):
[
  {
    "base_retiro": "BASE PAULINIA",
    "placa": "ABC1D23",
    "motorista": "JOAO DA SILVA",
    "horario": "08:00",
    "data_carregamento": "03/10/2026",          # opcional (padrão: hoje)
    "pedidos": [
      {"numero": "123456", "compartimentos": {"1": "DIESEL S10", "2": "GASOLINA C"}},
      {"numero": "123457", "compartimentos": {"3": "ETANOL"}}
    ]
  }
]

IMPORTANTE: só a tela de login foi inspecionada (ids codigoUsuario / senha). Os seletores das
telas internas estão centralizados em SEL e usam texto visível; valide-os no DevTools e ajuste.
"""

import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, timedelta

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

URL_LOGIN = "https://sites2.ipiranga.com.br/WAAgendamento/usuario/login"
TIMEOUT = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ipiranga")

# --------------------------------------------------------------------------------------
# Seletores (ajuste aqui). {x} é substituído em tempo de execução.
# --------------------------------------------------------------------------------------
SEL = {
    # Login (confirmados)
    "login_usuario": (By.ID, "codigoUsuario"),
    "login_senha": (By.ID, "senha"),
    "login_entrar": (By.CSS_SELECTOR, "form#usuario input[type='submit']"),

    # 1 - Tela principal: ícone na linha da base de retiro
    "linha_base": (By.XPATH, "//tr[td[contains(normalize-space(.), '{x}')]]"),
    "icone_na_linha": (By.XPATH, ".//a | .//button | .//i[contains(@class,'fa') or contains(@class,'glyph')]"),

    # 2 - Tela de pedidos
    "btn_alocar_pedido": (By.XPATH, "//*[self::button or self::a or self::input][contains(normalize-space(.), 'Alocar Pedido') or @value='Alocar Pedido']"),

    # 3 - Filtros
    "sel_tipo_operacao": (By.XPATH, "//label[contains(., 'Tipo de Opera')]/following::select[1]"),
    "sel_situacao": (By.XPATH, "//label[contains(., 'Situa')]/following::select[1]"),
    "inp_data_inicial": (By.XPATH, "//label[contains(., 'Data Inicial')]/following::input[1]"),
    "inp_data_final": (By.XPATH, "//label[contains(., 'Data Final')]/following::input[1]"),
    "btn_lupa": (By.XPATH, "(//*[contains(@class,'search') or contains(@class,'lupa') or contains(@title,'Pesquisar') or contains(@title,'Buscar')])[1]"),

    # 4 - Seleção de pedidos
    "chk_pedido": (By.XPATH, "//tr[td[normalize-space(.)='{x}']]//input[@type='checkbox']"),

    # 5 - Alocação: data e placa
    "inp_data_aloc": (By.XPATH, "//label[contains(., 'Data')]/following::input[1]"),
    "inp_placa": (By.XPATH, "//label[contains(., 'Placa')]/following::input[1]"),
    "lupa_placa": (By.XPATH, "//label[contains(., 'Placa')]/following::*[contains(@class,'search') or contains(@class,'lupa') or contains(@title,'Pesquisar')][1]"),

    # 6/7 - Motorista e horário
    "sel_motorista": (By.XPATH, "//label[contains(., 'Motorista')]/following::select[1]"),
    "sel_horario": (By.XPATH, "//label[contains(., 'Hor')]/following::select[1]"),

    # 8 - Compartimentos por pedido
    "radio_pedido": (By.XPATH, "//tr[td[contains(normalize-space(.), '{x}')]]//input[@type='radio']"),
    "linha_pedido": (By.XPATH, "//tr[td[contains(normalize-space(.), '{x}')]]"),
    "sel_compartimento_produto": (By.XPATH, "//tr[td[normalize-space(.)='{x}']]//select"),  # x = nº compartimento
    "msg_erro": (By.XPATH, "//*[contains(@class,'alert-danger') or contains(@class,'error') or contains(@class,'toast-error')]"),

    # 9 - Confirmar
    "btn_confirmar": (By.XPATH, "//*[self::button or self::input][contains(normalize-space(.), 'Confirmar') or @value='Confirmar']"),
    "btn_sim": (By.XPATH, "//*[self::button or self::a][normalize-space(.)='Sim']"),
    "id_agendamento": (By.XPATH, "//*[contains(., 'Agendamento') and (contains(., 'nº') or contains(., 'ID') or contains(., 'número'))]"),
}


def sel(key, x=None):
    by, value = SEL[key]
    return by, value.format(x=x) if x is not None else value


@dataclass
class Resultado:
    placa: str
    pedidos: list
    id_agendamento: str | None = None
    status: str = "pendente"
    observacoes: list = field(default_factory=list)  # registrar no sistema de pedidos


class PortalIpiranga:
    def __init__(self, headless=False):
        opts = webdriver.ChromeOptions()
        if headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--window-size=1600,1000")
        self.d = webdriver.Chrome(options=opts)
        self.w = WebDriverWait(self.d, TIMEOUT)

    # ---------- helpers ----------
    def find(self, key, x=None, clickable=False):
        cond = EC.element_to_be_clickable if clickable else EC.visibility_of_element_located
        return self.w.until(cond(sel(key, x)))

    def click(self, key, x=None):
        el = self.find(key, x, clickable=True)
        self.d.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        try:
            el.click()
        except Exception:
            self.d.execute_script("arguments[0].click();", el)
        self.aguardar()
        return el

    def digitar(self, key, texto, x=None):
        el = self.find(key, x)
        el.clear()
        el.send_keys(texto)
        return el

    def selecionar(self, key, texto, x=None):
        el = self.find(key, x)
        s = Select(el)
        try:
            s.select_by_visible_text(texto)
        except NoSuchElementException:
            opt = next((o for o in s.options if texto.upper() in o.text.upper()), None)
            if not opt:
                raise ValueError(f"Opção '{texto}' não encontrada em {key}: {[o.text for o in s.options]}")
            opt.click()
        self.aguardar()

    def existe(self, key, x=None, timeout=3):
        try:
            WebDriverWait(self.d, timeout).until(EC.visibility_of_element_located(sel(key, x)))
            return True
        except TimeoutException:
            return False

    def aguardar(self):
        """Espera Angular/loader terminar."""
        time.sleep(0.5)
        try:
            WebDriverWait(self.d, TIMEOUT).until_not(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".loading, .spinner, .blockUI, .modal-backdrop.loading"))
            )
        except TimeoutException:
            pass

    def screenshot(self, nome):
        os.makedirs("prints", exist_ok=True)
        self.d.save_screenshot(f"prints/{nome}_{int(time.time())}.png")

    # ---------- Login ----------
    def login(self, usuario, senha):
        log.info("Login")
        self.d.get(URL_LOGIN)
        self.digitar("login_usuario", usuario)
        self.digitar("login_senha", senha)
        self.click("login_entrar")
        self.w.until(lambda d: "/login" not in d.current_url)

    # ---------- Passos 1–3 ----------
    def abrir_alocacao(self, base_retiro):
        log.info("1. Tela principal -> base %s", base_retiro)
        linha = self.find("linha_base", base_retiro)
        icone = linha.find_element(*SEL["icone_na_linha"])
        self.d.execute_script("arguments[0].click();", icone)
        self.aguardar()

        log.info("2. Tela de pedidos -> Alocar Pedido")
        self.click("btn_alocar_pedido")

    def filtrar(self):
        hoje = date.today()
        log.info("3. Filtros FOB / Apenas liberados / %s..%s", hoje, hoje + timedelta(days=2))
        self.selecionar("sel_tipo_operacao", "FOB")
        self.selecionar("sel_situacao", "Apenas liberados")
        self.digitar("inp_data_inicial", hoje.strftime("%d/%m/%Y"))
        self.digitar("inp_data_final", (hoje + timedelta(days=2)).strftime("%d/%m/%Y"))
        self.click("btn_lupa")

    # ---------- Passos 4–9 ----------
    def programar(self, prog) -> Resultado:
        numeros = [p["numero"] for p in prog["pedidos"]]
        res = Resultado(placa=prog["placa"], pedidos=numeros)

        log.info("4. Selecionando pedidos %s", numeros)
        for n in numeros:
            chk = self.find("chk_pedido", n)
            if not chk.is_selected():
                self.d.execute_script("arguments[0].click();", chk)
        self.click("btn_alocar_pedido")

        log.info("5. Data/placa")
        data_carr = prog.get("data_carregamento") or date.today().strftime("%d/%m/%Y")
        self.digitar("inp_data_aloc", data_carr)
        self.digitar("inp_placa", prog["placa"])
        self.click("lupa_placa")  # preenche campos automaticamente

        log.info("6. Motorista %s", prog["motorista"])
        self.selecionar("sel_motorista", prog["motorista"])

        log.info("7. Horário %s", prog["horario"])
        self.selecionar("sel_horario", prog["horario"])

        log.info("8. Compartimentos por pedido")
        programados = 0
        for ped in prog["pedidos"]:
            n = ped["numero"]
            linha = self.find("linha_pedido", n)
            texto = linha.text.upper()
            if "EM ANÁLISE" in texto or "EM ANALISE" in texto:
                res.observacoes.append(f"Pedido {n}: status 'Em Análise' - não programado")
                log.warning("Pedido %s em análise, pulando", n)
                continue

            self.click("radio_pedido", n)
            for comp, produto in ped["compartimentos"].items():
                self.selecionar("sel_compartimento_produto", produto, x=str(comp))

            if self.existe("msg_erro", timeout=2):
                msg = self.find("msg_erro").text
                if "SALDO" in msg.upper():
                    res.observacoes.append(f"Pedido {n}: saldo insuficiente ({msg})")
                    log.warning("Pedido %s: saldo insuficiente", n)
                    continue
                raise RuntimeError(f"Erro no pedido {n}: {msg}")
            programados += 1

        if programados == 0:
            res.status = "nenhum pedido programado"
            return res

        log.info("9. Confirmar")
        self.click("btn_confirmar")
        if self.existe("btn_sim", timeout=5):  # popup de compartimento vazio
            log.info("Popup compartimento vazio -> Sim")
            self.click("btn_sim")

        res.id_agendamento = self.capturar_id()
        res.status = "agendado" if res.id_agendamento else "confirmado sem ID capturado"
        log.info("ID do agendamento: %s", res.id_agendamento)
        return res

    def capturar_id(self):
        import re
        try:
            txt = self.find("id_agendamento").text
        except TimeoutException:
            txt = self.d.find_element(By.TAG_NAME, "body").text
        m = re.search(r"[Aa]gendamento\D{0,30}(\d{4,})", txt)
        return m.group(1) if m else None

    def fechar(self):
        self.d.quit()


def main():
    arq = sys.argv[1] if len(sys.argv) > 1 else "programacoes.json"
    with open(arq, encoding="utf-8") as f:
        programacoes = json.load(f)

    usuario = os.environ["IPIRANGA_USUARIO"]
    senha = os.environ["IPIRANGA_SENHA"]

    portal = PortalIpiranga(headless=os.getenv("HEADLESS") == "1")
    resultados = []
    try:
        portal.login(usuario, senha)
        for prog in programacoes:
            try:
                portal.abrir_alocacao(prog["base_retiro"])
                portal.filtrar()
                resultados.append(portal.programar(prog))
            except Exception as e:
                log.exception("Falha na programação da placa %s", prog.get("placa"))
                portal.screenshot(f"erro_{prog.get('placa')}")
                resultados.append(Resultado(placa=prog.get("placa"), pedidos=[p["numero"] for p in prog["pedidos"]],
                                            status=f"erro: {e}"))
    finally:
        portal.fechar()

    saida = [r.__dict__ for r in resultados]
    with open("resultado_agendamentos.json", "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, indent=2)
    print(json.dumps(saida, ensure_ascii=False, indent=2))
    return saida


if __name__ == "__main__":
    main()
