FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home appuser && mkdir -p data && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000 8501
HEALTHCHECK --interval=30s --timeout=10s CMD python -c "import requests; requests.get('http://localhost:8000/health', timeout=5).raise_for_status()"
CMD ["python", "run_all.py"]
