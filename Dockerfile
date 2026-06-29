FROM python:3.11-slim

WORKDIR /app

COPY simulate.py .

RUN pip install --no-cache-dir numpy scipy boto3

ENTRYPOINT ["python", "simulate.py"]