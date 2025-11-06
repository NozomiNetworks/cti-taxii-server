FROM python:3.13-bookworm

COPY . /opt/taxii
COPY ./docker_utils/*.json /opt/taxii
WORKDIR /opt/taxii
RUN pip install --upgrade pip setuptools \
    && pip install pymongo \
    && pip install .
