.PHONY: install dev run test lint docker-build docker-up

install:
	pip install -r requirements.txt

dev:
	pip install -r requirements.txt
	pip install ruff

run:
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	pytest -q

lint:
	ruff check app tests

docker-build:
	docker build -t osintp:latest .

docker-up:
	docker compose up --build
