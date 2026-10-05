# Risk analytics application: docker build -t gs-quant-risk .
# docker run -p 8000:8000 -e RISK_APP_API_TOKEN=<16 or more characters> -v risk-data:/data gs-quant-risk
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RISK_APP_HOST=0.0.0.0 \
    RISK_APP_PORT=8000 \
    RISK_APP_DATABASE=/data/runs.db

WORKDIR /src
COPY . /src
RUN pip install ".[app]" && rm -rf /src

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
USER app
WORKDIR /home/app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['RISK_APP_PORT'] + '/api/health', timeout=4)"

# Listening on the network needs RISK_APP_API_TOKEN: the container stops with an explanation without it
CMD ["gs-quant-risk", "serve"]
