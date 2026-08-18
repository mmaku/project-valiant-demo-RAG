IMAGE ?= valiant-ai-engine
TAG   ?= latest

.PHONY: help build up down logs sh sync run

help:        ## List targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-10s\033[0m %s\n",$$1,$$2}'

build:       ## Build the image (docker compose build)
	docker compose build

up:          ## Start the service in the background
	docker compose up -d

down:        ## Stop the service
	docker compose down

logs:        ## Tail the logs
	docker compose logs -f api

sh:          ## Shell into the running container
	docker compose exec api /bin/bash

sync:        ## Install dependencies locally (uv)
	uv sync

run:         ## Run the API locally with hot-reload
	cd app && uv run uvicorn main:backend_app --host 0.0.0.0 --port 8000 --reload
