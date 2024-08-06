# Stage 1: Build stage
FROM python:3.12-alpine as builder

# Define build argument
ARG INSTALL_BUILD_TOOLS=false

# Install build dependencies conditionally
RUN apk update && \
    apk add --no-cache git && \
    if [ "$INSTALL_BUILD_TOOLS" = "true" ]; then \
        apk add --no-cache build-base libffi-dev; \
    fi

WORKDIR /app

COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --user -Ur requirements.txt --no-dependencies

# Stage 2: Runtime stage
FROM python:3.12-alpine

WORKDIR /app

# Copy only the necessary files from the build stage
COPY --from=builder /root/.local /root/.local
COPY . .

# Update PATH to include pip-installed packages
ENV PATH=/root/.local/bin:$PATH

CMD ["python", "bot.py"]
