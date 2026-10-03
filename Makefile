.PHONY: help install test lint run docker-up docker-down demo reset

PYTHON ?= python

help:
	@echo "=========================================================="
	@echo "                     OpsPilot Makefile"
	@echo "=========================================================="
	@echo "make install       Install application dependencies"
	@echo "make test          Run automated unit and integration tests"
	@echo "make lint          Run ruff code linter"
	@echo "make run           Run OpsPilot FastAPI backend locally"
	@echo "make docker-up     Start Docker Compose stack in background"
	@echo "make docker-down   Stop and remove Docker Compose stack"
	@echo "make demo          Execute full autonomous demo pipeline"
	@echo "make reset         Reset demo state and target service"
	@echo "=========================================================="

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest tests/ -v

lint:
	$(PYTHON) -m ruff check .

run:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down -v

demo:
	@bash scripts/demo.sh || powershell -File scripts/demo.ps1

reset:
	@bash scripts/reset_demo.sh || powershell -File scripts/reset_demo.ps1
