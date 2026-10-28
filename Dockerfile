FROM python:3.12-slim

# kepubify converts EPUB to Kobo's KEPUB format (better rendering and more
# precise reading positions).  Optional; remove these lines to skip it.
ARG KEPUBIFY_VERSION=v4.0.4
ADD https://github.com/pgaskin/kepubify/releases/download/${KEPUBIFY_VERSION}/kepubify-linux-64bit /usr/local/bin/kepubify
RUN chmod +x /usr/local/bin/kepubify

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY kobosync ./kobosync

ENV KOBOSYNC_LIBRARY=/library \
    KOBOSYNC_DATA=/data \
    KOBOSYNC_PORT=8085
VOLUME ["/library", "/data"]
EXPOSE 8085
CMD ["python", "-m", "kobosync", "serve"]
