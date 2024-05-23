FROM python:3.12-alpine

# Install git
RUN apk update && apk add git && rm -rf /var/cache/apk/*

COPY . /app
WORKDIR /app
RUN pip install -U -r requirements.txt --no-dependencies

CMD ["python", "main.py"]