FROM node:24-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home digitxbd && mkdir /data && chown digitxbd:digitxbd /data
COPY --chown=digitxbd:digitxbd app.py qr_pay.py record_admin.py print_queue.py PRINTING.md seed.json restore_backup.py ./
COPY --chown=digitxbd:digitxbd printer-helper ./printer-helper
COPY --chown=digitxbd:digitxbd templates ./templates
COPY --chown=digitxbd:digitxbd static ./static
COPY --from=frontend --chown=digitxbd:digitxbd /build/static/react ./static/react
USER digitxbd
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1
CMD ["python", "app.py"]
