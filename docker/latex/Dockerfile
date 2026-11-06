ARG PYTHON_IMAGE=python:3.13-slim-bookworm@sha256:a5a7017efc5969e00ae2b91c8eb0631049a569652aa4ffc4501769049ae45c72
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp/tex
RUN apt-get update \
    && apt-get install -y --no-install-recommends texlive-latex-base texlive-latex-recommended texlive-latex-extra texlive-science texlive-fonts-recommended \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home tex
WORKDIR /worker
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY latex_worker.py ./
COPY scripts/check_release_image.py /usr/local/bin/check-release-image.py
USER tex
EXPOSE 8790
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/health',timeout=3).read()"
CMD ["python","-m","uvicorn","latex_worker:app","--host","0.0.0.0","--port","8790","--workers","1"]
