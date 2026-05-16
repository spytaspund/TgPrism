FROM python:3.13-slim

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    tar \
    && wget https://github.com/SagerNet/sing-box/releases/download/v1.13.11/sing-box-1.13.11-linux-amd64.tar.gz \
    && tar -xvf sing-box-1.13.11-linux-amd64.tar.gz \
    && mv sing-box-1.13.11-linux-amd64/sing-box /usr/local/bin/ \
    && chmod +x /usr/local/bin/sing-box \
    && rm -rf sing-box-1.13.11-linux-amd64* \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY . .

RUN mkdir -p /app/sessions /app/data

EXPOSE 8000

CMD ["sh", "-c", "hypercorn TgPrism:app --bind 0.0.0.0:${SERVER_PORT:-8000} --access-log -"]