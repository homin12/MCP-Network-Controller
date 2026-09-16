FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

ENV PORT=8000
ENV HOST=0.0.0.0
ENV CONFIG_PATH=/app/config.yaml

EXPOSE 8000

CMD ["python", "main.py"]