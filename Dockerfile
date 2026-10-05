# Risk analytics application: docker build -t gs-quant-risk .
# docker run -p 8000:8000 -e RISK_APP_API_TOKEN=<16 or more characters> -v risk-data:/data gs-quant-risk
# Published images: ghcr.io/senanurcetin/gs-quant-risk:<version>
FROM python:3.12-slim

# The version the application reports. A source tree without git history cannot work it out, so a release build passes it
# (docker build --build-arg VERSION=1.2.3 .); without it the image reports 0+unknown.
ARG VERSION=""

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    RISK_APP_HOST=0.0.0.0 \
    RISK_APP_PORT=8000 \
    RISK_APP_DATABASE=/data/runs.db

# Security fixes of the base image's operating system packages that its latest tag has not picked up yet
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . /src
RUN if [ -n "$VERSION" ]; then python deploy/pin_version.py "$VERSION"; fi \
    && pip install ".[app]" && rm -rf /src

RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
USER app
WORKDIR /home/app
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['RISK_APP_PORT'] + '/api/health', timeout=4)"

# Listening on the network needs RISK_APP_API_TOKEN: the container stops with an explanation without it
CMD ["gs-quant-risk", "serve"]
