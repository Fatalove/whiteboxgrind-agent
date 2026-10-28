# Fixed official Ubuntu amd64 image; engine sources are supplied as verified archives.
FROM ubuntu:22.04@sha256:8a2321a92b438238f93b4346fff61bc4259c99fdd4d9b52ee86f153fee0c344f AS dependencies
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
COPY bootstrap-ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY system-packages.lock /tmp/system-packages.lock
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    printf '%s\n' 'deb https://archive.ubuntu.com/ubuntu jammy main universe' \
    'deb https://archive.ubuntu.com/ubuntu jammy-updates main universe' \
    'deb https://security.ubuntu.com/ubuntu jammy-security main universe' > /etc/apt/sources.list && \
    apt-get -o APT::Update::Error-Mode=any -o Acquire::ForceIPv4=true -o Acquire::Retries=1 -o Acquire::https::Timeout=30 -o Acquire::Languages=none update && \
    xargs -a /tmp/system-packages.lock apt-get -o Acquire::ForceIPv4=true -o Acquire::Retries=1 -o Acquire::https::Timeout=30 install -y --no-install-recommends
FROM dependencies AS build
COPY vendor/ /vendor/
COPY patch.patch requirements.lock build_engine.sh /build/
RUN bash /build/build_engine.sh

FROM dependencies AS runtime
LABEL org.opencontainers.image.title="Whiteboxgrind local research runtime" \
      org.opencontainers.image.version="0.3.0-rc.1" \
      io.whiteboxgrind.engine.commit="b4f5b78a415aaf4a864f31b9d85c3305a4970b4f" \
      io.whiteboxgrind.backend="docker"
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 USER=wbg HOME=/home/wbg
RUN dpkg-query -W -f='${Package}\t${Version}\n' > /usr/share/whiteboxgrind-system-packages.tsv && \
    useradd --create-home --uid 1000 wbg && \
    mkdir -p /work/runs /exports && chown -R wbg:wbg /work /exports
COPY --from=build /opt/wbg-engine /opt/wbg-engine
COPY --from=build /vendor /usr/share/whiteboxgrind/sources
COPY --from=build /build /usr/share/whiteboxgrind/build
COPY engine-inputs.json /usr/share/whiteboxgrind/build/engine-inputs.json
COPY app/ /opt/whiteboxgrind/
ENV WBG_RUNTIME_BACKEND=docker WBG_ENGINE_ROOT=/opt/wbg-engine WBG_WORK_ROOT=/work \
    WBG_EXPORT_ROOT=/exports WBG_BASELINE_PATH=/opt/wbg-engine/baseline.json \
    PATH=/opt/wbg-engine/prefix/bin:/opt/wbg-engine/venv/bin:$PATH \
    LD_LIBRARY_PATH=/opt/wbg-engine/prefix/lib PYTHONPATH=/opt/whiteboxgrind/src PYTHONDONTWRITEBYTECODE=1
COPY make_baseline.py /tmp/make_baseline.py
RUN /opt/wbg-engine/venv/bin/python /tmp/make_baseline.py && \
    /opt/wbg-engine/venv/bin/python -c 'import y5, yaml, numpy, Crypto; print("bindings ok")'
USER 1000:1000
WORKDIR /opt/whiteboxgrind
ENTRYPOINT ["/opt/wbg-engine/venv/bin/python", "-m", "wbg.container_entry"]
CMD ["doctor", "--json"]
