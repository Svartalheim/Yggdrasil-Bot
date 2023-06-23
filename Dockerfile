FROM python:3.10

COPY . /app
WORKDIR /app
RUN pip3 install -Ur requirements.txt

CMD ["python3", "main.py"]