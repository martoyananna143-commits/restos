# Dioxus web application - runs dx serve --release

FROM rust:1.93-slim-bookworm

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install wasm target and dioxus-cli
RUN rustup target add wasm32-unknown-unknown \
    && cargo install dioxus-cli --version 0.7.3 --locked

WORKDIR /app

# Copy project files
COPY resty_form_alpha/ .

# Compile the production bundle during image build so deployment fails early on frontend errors.
RUN dx build --release

EXPOSE 8080

# Run dx serve in release mode
CMD ["dx", "serve", "--release", "--addr", "0.0.0.0", "--port", "8080"]
