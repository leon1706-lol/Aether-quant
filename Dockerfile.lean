# Local LEAN engine image for Aether-Quant.
#
# The official QuantConnect image intentionally does not contain this
# project's optional Redis client. Installing it here keeps the dependency
# inside the image instead of making Lean CLI bind-mount a generated
# requirements.txt file from Windows (which fails on some Docker Desktop
# installations with CreateFile: Access denied).
ARG LEAN_BASE_IMAGE=quantconnect/lean:17900@sha256:917ba212afafc9be9ad401eaed6d55986386855a0a597200a448c34a03f3360b
FROM ${LEAN_BASE_IMAGE}

# V6.6.7 (#361): the same two packages from a hash lock (requirements/lock/lean-runtime.in), installed with --no-deps so
# the image's own packages are never re-resolved
COPY requirements/lock/lean-runtime.txt /tmp/aether-quant-lean-runtime.txt
RUN python -m pip install --no-cache-dir --disable-pip-version-check --require-hashes --no-deps \
        -r /tmp/aether-quant-lean-runtime.txt \
    && rm -f /tmp/aether-quant-lean-runtime.txt
