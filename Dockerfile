FROM python:3.9-slim

# Without this, Python block-buffers stdout when it isn't a tty (i.e.
# always, inside a container) — `docker logs` on producer/consumer/cleanup
# can sit empty for a long time even though the process is working fine.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5001

CMD ["python3", "app.py"]