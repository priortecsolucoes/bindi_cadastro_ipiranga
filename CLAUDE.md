# Coding Standards — Priortec / Bindi - Cadastro Ipiranga

## Role
You are an assistant for Automation + AI application development at Priortec.
This project is **Bindi - Cadastro Ipiranga**: bot Python (Selenium) que agenda pedidos FOB no
Portal de Agendamento Ipiranga (WAAgendamento) para a BindiLog (detalhes abaixo).

## Language conventions
- **Code identifiers** (variables, methods, properties, interfaces, type literals) must be in **English**.
- **User-facing strings**, log messages, comments, and `print` output must be in **Portuguese**.

## Casing
- Python: `snake_case` for all identifiers.

## Classes and abstraction
- Create classes and abstractions only when genuinely necessary — not speculatively.
- Prefer flat functions and simple modules for single-responsibility logic.

## Error handling
- Always add proper exception handling so that automated processes fail loudly, not silently.
- Surface errors in Portuguese with enough context to diagnose.

## Comments
- Write comments only when the *why* is non-obvious. Never describe what well-named code already says.

---

## This project (Bindi - Cadastro Ipiranga)

### O que é
Bot Python (Selenium) que agenda (aloca) pedidos FOB no **Portal de Agendamento Ipiranga**
(`sites2.ipiranga.com.br/WAAgendamento`) para a operação da BindiLog. Origem: o script
`ipiranga_agendamento.py` (protótipo standalone), reorganizado no padrão FrameworkRE do projeto
`C:\Priortec\Bindi - Cadastro` (Vibra).

Fluxo por programação (`Automation/IpirangaPortal.py`) - **segue o passo a passo da ER**, tópico 11
"Fluxo Cadastro de Transporte - Distribuidora Ipiranga" (`docs contexto/ER Bindi Log - Portal Gestao
de Pedidos V1 1.docx`, imagem `word/media/image5.png`):
Login > 1 Tela Principal/Filiais (ícone de ficha na linha da **Base de Betim**) > 2 "Alocar Pedido" >
3 Filtros (Tipo de Operação = FOB, Situação = Apenas Liberados, Data Inicial = data de carga da
viagem, Data Final = data de carga + 5 - a ER diz hoje .. hoje + 2; alterado a pedido) + Lupa > 4 Marca os pedidos do mesmo motorista/caminhão + "Alocar Pedido" > 5 Data Saída +
Placa + lupa da placa (preenche campos) > 6 Motorista > 7 Horário (combo Horários) > 8 Para cada
pedido: rádio da linha **'Registrado'**; se só houver **'Em Análise'**, usa essa mesmo assim e registra
observação; define produto <-> compartimento; **saldo insuficiente** registra observação (pedido não
programado) > 9 Confirmar (popup de compartimento vazio > "Sim") > salva o ID do agendamento.

Entrada: Portal Bindi Log `GET /api/rpa/ipiranga/planejados?days=N` (Bearer `PORTAL_API_TOKEN` =
`RPA_API_TOKEN` do portal; `PORTAL_PENDING_DAYS`, padrão 3). Mesmo critério de "planejado" do
`vibra/planejados` (`lib/rpaPlannedTrips.ts` no Bindi-PAINEL). **Uma programação por viagem**:
placa = `tractorPlate`, motorista = `driverName`, horário = `loadTime`, data = `loadDate`, pedido =
`distributorOrderNumber`, compartimentos = `items[].compartments[].number` → `productName`.
A Base de Retiro não existe no portal: padrão `Base De Betim` (ER), override em `IPIRANGA_BASE_RETIRO`.
Override para testes: `PROGRAMACOES_PATH` (JSON, formato em `programacoes.example.json`); com ele
o portal não é consultado nem recebe resultado.

Retorno: `POST /api/rpa/ipiranga/agendamentos` com `{ tripId, schedulingId, orders: [{ orderId,
scheduled, observation? }] }`. Agendado → `registered_at_distributor` + nota com o ID (agendado
com ressalva 'Em Análise' → também `distributor_note` em aberto); não agendado (saldo
insuficiente) → `distributor_note` em aberto, status inalterado.
Saída local: `agendamentos_ipiranga.csv` (status `AGENDADO`, `CONFIRMADO_SEM_ID`, `NAO_PROGRAMADO`,
`ERRO_RETORNO_PORTAL` ou `ERRO`) + `erro_agendamento_N.png`. Erro na programação → POST com
`failed: true` e a mensagem tratada (`SchedulingError.user_message`, ou mensagem genérica de falha
técnica): pedidos vão para `scheduling_error` ("Erro no agendamento") + `distributor_note` em aberto;
a viagem só volta no `planejados` depois de alterada no portal (`trip.updated_at` posterior à nota de erro).

**Pendências:**
- Só a tela de login foi inspecionada (`#codigoUsuario`, `#senha`). Os seletores das telas
  internas estão em `SELECTORS` (`Automation/IpirangaPortal.py`) e usam texto visível -
  validar no DevTools.

### Stack
Python 3.11+, `selenium`, `python-dotenv`, `requests`.

### Estrutura de pastas do projeto
```
├── main.py                          ← orquestrador (INIT → GET_DATA → PROCESS → END)
├── ipiranga_agendamento.py          ← protótipo original (referência)
├── Framework/
│   ├── InitModule.py                ← valida .env, credenciais e pré-requisitos
│   ├── GetDataModule.py             ← viagens planejadas do portal (ou PROGRAMACOES_PATH)
│   ├── ProcessModule.py             ← login → para cada viagem aloca, confirma e reporta ao portal
│   ├── EndModule.py                 ← finalização (fecha o CSV, imprime resumo)
│   └── RPAFrameworkException.py     ← exceção controlada
├── Automation/
│   └── IpirangaPortal.py            ← passos Selenium (login + alocação de pedidos)
├── Utils/
│   ├── DriverFactory.py             ← cria o Chrome WebDriver (perfil persistente + cookies, padrão Bindi - Vibra)
│   └── PortalClient.py              ← cliente HTTP do Portal Bindi Log (planejados + agendamentos)
├── Log/
│   └── LogModule.py                 ← grava o resultado em agendamentos_ipiranga.csv
├── programacoes.example.json
├── requirements.txt
├── .env                              ← não versionar
└── .env.example
```

---

## FrameworkRE — como funciona

Padrão **FrameworkRE** adaptado para Python pela Priortec. Pipeline linear de 4 módulos.
**Reutilize este padrão em todos os projetos de automação Priortec.**

### Pipeline: INIT → GET_DATA → PROCESS → END

```
main.py
  └── InitModule.initialize()        # 1. Valida ambiente (falha total se erro)
  └── GetDataModule.get_data()       # 2. Carrega itens; None = processar tudo
  └── ProcessModule.process_items()  # 3. try/except isolado por item
  └── EndModule.finalize()           # 4. sempre executa (finally)
```

### Módulos e responsabilidades

**InitModule** — valida variáveis de ambiente obrigatórias, existência de paths e pré-requisitos.
Levanta `RPAFrameworkException` para falhas que impedem qualquer execução. Nunca abre browser ou
lê dados de negócio aqui.

**GetDataModule** — única responsabilidade: ler a fonte de dados e devolver `list[dict]` ou `None`.
Filtra itens já processados. Nunca escreve.

**ProcessModule** — itera sobre os itens; cada item tem seu próprio `try/except` (erro em um item
não para o loop). Chama `LogModule` para persistir STATUS e RESULTADO. Instancia scanners/copiers
dentro do loop para evitar estado compartilhado.

**EndModule** — executado no `finally` de `Main.run()`. Fecha recursos, imprime resumo.

**RPAFrameworkException** — para erros controlados (configuração errada, pré-requisito faltando).
Esses erros terminam o processo inteiro. Erros de negócio por item usam `Exception` comum.

**LogModule** — único módulo que escreve na planilha (`openpyxl`). Mantém workbook aberto durante
toda a execução. `write_value(row_index, column_name, value)`. Fecha no `EndModule`.

### Regras do FrameworkRE
1. Um módulo, uma responsabilidade.
2. Falha ruidosa: todo `except` loga com contexto antes de relançar ou registrar.
3. Estado isolado por item: instanciar recursos dentro do loop.
4. LogModule é o único que escreve na planilha.
5. Erros em um item não param o pipeline — registram e continuam.

---

## Estilo CLI
- Separadores `"=" * 55` entre clientes.
- Prefixos: `[OK]`, `[INFO]`, `[AVISO]`, `[ERRO]`, `[ERRO Framework]`.
- Não usar `logging` do Python — `print` direto conforme padrão Priortec.

## Deploy
Railway via `Dockerfile` (python:3.11-slim-bookworm + Google Chrome, `CHROME_HEADLESS=1`) e `railway.json`
(builder DOCKERFILE, cron `*/30 * * * *`, sem restart) - mesmo padrão do Bindi - Vibra. Variáveis do `.env` vão
nas Variables do serviço no Railway (`.env` fica fora da imagem pelo `.dockerignore`).
