FROM python:3.13-slim

USER root

RUN apt-get update && apt-get install -y \
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

RUN useradd -m -u 1000 user
WORKDIR /app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY --chown=user . .

RUN chown -R user:user /app

USER user
ENV PATH="/home/user/.local/bin:$PATH"

CMD ["sh", "-c", "rm -rf /app/prism.db /app/sessions && \
    mkdir -p /data/sessions && \
    touch /data/prism.db && \
    ln -s /data/prism.db /app/prism.db && \
    ln -s /data/sessions /app/sessions && \
    python TgPrism.py"]