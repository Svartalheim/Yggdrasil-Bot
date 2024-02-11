FROM python:3.11-slim

# Install git
RUN apt-get update && apt-get install -y git

COPY . /app
WORKDIR /app
RUN pip3 install -Ur requirements.txt

CMD ["python3", "main.py"]