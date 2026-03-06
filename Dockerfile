FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN apt-get update

RUN apt-get install -y wget tar gzip sudo iputils-ping

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python3", "main.py"]
