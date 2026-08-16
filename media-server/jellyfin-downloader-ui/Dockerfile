FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir flask

COPY app.py .
COPY templates ./templates

EXPOSE 8080

CMD ["python3", "app.py"]
