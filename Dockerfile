FROM ubuntu:latest
LABEL authors="Mike"

ENTRYPOINT ["top", "-b"]
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "botv1.py"]
