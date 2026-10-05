FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --system --create-home hub && mkdir -p /data && chown -R hub:hub /app /data
USER hub

ENV HUB_DB=/data/hub.db
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import os,urllib.request;r=urllib.request.Request('http://127.0.0.1:8000/v1/health',headers={'Authorization':'Bearer '+os.environ['HUB_TOKEN']});urllib.request.urlopen(r)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
