FROM python:3.9-slim-buster

# Install ping
RUN apt-get update && apt-get install -y iputils-ping

WORKDIR /app

COPY requirements.txt .
COPY app.py .
COPY .env .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "app.py"]
