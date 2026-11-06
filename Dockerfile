# Bindi - Cadastro Ipiranga - imagem pra rodar via Cron Schedule no Railway
# (mesmo padrão do Bindi - Vibra). O Selenium Manager baixa o chromedriver da
# versão do Chrome instalado; só o Google Chrome precisa vir na imagem.
FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg ca-certificates fonts-liberation \
    && wget -q -O /tmp/google-chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    # SEM --no-install-recommends aqui: o .deb do Chrome declara bibliotecas de
    # runtime (libgbm, libnss3, libasound2...) como "Recommends" - sem elas o
    # chromedriver/Chrome morre na inicialização (status 127).
    && apt-get install -y /tmp/google-chrome.deb \
    && rm /tmp/google-chrome.deb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sem display no container - headless é obrigatório aqui.
ENV CHROME_HEADLESS=1

CMD ["python", "main.py"]
