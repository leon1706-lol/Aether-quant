# Local LEAN engine image for Aether-Quant.
#
# The official QuantConnect image intentionally does not contain this
# project's optional Redis client. Installing it here keeps the dependency
# inside the image instead of making Lean CLI bind-mount a generated
# requirements.txt file from Windows (which fails on some Docker Desktop
# installations with CreateFile: Access denied).
ARG LEAN_BASE_IMAGE=quantconnect/lean:17900
FROM ${LEAN_BASE_IMAGE}

COPY requirements/lean-runtime.txt /tmp/aether-quant-lean-runtime.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
        -r /tmp/aether-quant-lean-runtime.txt \
    && rm -f /tmp/aether-quant-lean-runtime.txt
