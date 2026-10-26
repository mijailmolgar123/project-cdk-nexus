ENV_NAME ?= dev
PYTHON ?= python3.11
VENV ?= .venv
PIP := $(VENV)/bin/python -m pip
PYTEST := $(VENV)/bin/python -m pytest
CDK := ./node_modules/.bin/cdk

.PHONY: venv install synth diff deploy test

venv:
	$(PYTHON) -m venv $(VENV)

install:
	$(PIP) install "pip @ https://files.pythonhosted.org/packages/3f/06/3e4420302363fbb71be3c7f35ce042f54bfca330e3e66b3a2e3c4cca579f/pip-26.2.2-py3-none-any.whl#sha256=fd7f4dfa8190e014013b9f08f3e973f4e4c26ffd179a204895533a7254813a70"
	$(PIP) install -r requirements-tooling.txt -r requirements.txt -r requirements-dev.txt
	npm ci

synth:
	$(CDK) synth -c env_name=$(ENV_NAME)

diff:
	$(CDK) diff -c env_name=$(ENV_NAME)

deploy:
	$(CDK) deploy --all --require-approval never -c env_name=$(ENV_NAME)

test:
	$(PYTEST)
