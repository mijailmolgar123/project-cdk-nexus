ENV_NAME ?= dev
PYTHON ?= python3.11
VENV ?= .venv
PIP := $(VENV)/bin/pip
PYTEST := $(VENV)/bin/pytest
CDK := ./node_modules/.bin/cdk

.PHONY: venv install synth diff deploy test

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt -r requirements-dev.txt
	npm install

synth:
	$(CDK) synth -c env_name=$(ENV_NAME)

diff:
	$(CDK) diff -c env_name=$(ENV_NAME)

deploy:
	$(CDK) deploy --all --require-approval never -c env_name=$(ENV_NAME)

test:
	$(PYTEST)
