FROM python:3.12-slim

# Without this, Python block-buffers stdout when it isn't a tty (i.e.
# always, inside a container) — `docker logs` on producer/consumer/cleanup
# can sit empty for a long time even though the process is working fine.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .

# timezonefinder has no prebuilt wheel for linux/aarch64 — it compiles a C
# extension at install time, which needs gcc (absent from python:*-slim).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc libc6-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 5001

CMD ["python3", "app.py"]