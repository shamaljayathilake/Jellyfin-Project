FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends aria2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["aria2c"]
