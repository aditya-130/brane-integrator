FROM python:3.10-slim

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    --allow-change-held-packages --allow-downgrades fuse iptables

ADD branelet /branelet
RUN chmod +x /branelet

RUN mkdir -p /opt/wd
COPY package.py /opt/wd/package.py
COPY run.sh /opt/wd/run.sh
RUN chmod +x /opt/wd/run.sh

COPY container.yml /opt/wd/container.yml

WORKDIR /opt/wd
ENTRYPOINT ["/branelet"]
