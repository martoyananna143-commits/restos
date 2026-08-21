# Dioxus web application - runs dx serve --release

FROM rust:1.93-slim-bookworm

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    pkg-config libssl-dev curl ca-certificates python3 \
    && rm -rf /var/lib/apt/lists/*

# Install wasm target and dioxus-cli
RUN rustup target add wasm32-unknown-unknown \
    && cargo install dioxus-cli --version 0.7.3 --locked

WORKDIR /app

# Copy project files
COPY resty_form_alpha/ .

# Compile and seal the production bundle.  The wrapper derives the immutable
# service-worker release ID from the emitted HTML/JS/WASM/CSS manifest and
# fails if the placeholder was not replaced.
RUN python3 scripts/build_release.py

EXPOSE 8080

# Run dx serve in release mode
CMD ["dx", "serve", "--release", "--addr", "0.0.0.0", "--port", "8080"]
