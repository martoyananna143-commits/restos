# Dioxus web application - runs dx serve --release

FROM rust:1.93-slim-bookworm

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install wasm target and dioxus-cli
RUN rustup target add wasm32-unknown-unknown \
    && cargo install dioxus-cli --locked

WORKDIR /app

# Copy project files
COPY resty_form_alpha/ .

# Build dependencies in release mode (for faster startup)
RUN dx build --release || true

EXPOSE 8080

# Run dx serve in release mode
CMD ["dx", "serve", "--release", "--addr", "0.0.0.0", "--port", "8080"]
