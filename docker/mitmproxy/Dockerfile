FROM python:3.12-slim

RUN pip install --no-cache-dir mitmproxy

COPY scripts/proxy_addon.py /opt/proxy_addon.py

WORKDIR /engagement

EXPOSE 8080

ENTRYPOINT ["mitmdump", "-p", "8080", "-s", "/opt/proxy_addon.py"]
CMD ["--set", "engagement_dir=/engagement"]
