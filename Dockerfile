FROM python:3.12-slim

WORKDIR /trident
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY trident/ .
COPY .git .git
CMD ["python", "main.py"]
