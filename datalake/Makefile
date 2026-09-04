PY ?= python3
export PYTHONPATH := src

.PHONY: help setup init demo run ingest silver gold quality catalog state test clean

help:            ## Mostra esta ajuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	 awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

setup:           ## Instala as dependencias
	$(PY) -m pip install -r requirements.txt

init:            ## Cria diretorios e banco de controle
	$(PY) -m datalake.cli init

demo:            ## Gera a base de demonstracao e roda o pipeline inteiro
	$(PY) scripts/seed_demo.py
	$(PY) -m datalake.cli run -s demo_erp

demo-incremental: ## Simula movimento novo e roda de novo (testa o incremental)
	$(PY) scripts/seed_demo.py --novos 200
	$(PY) -m datalake.cli run -s demo_erp

run:             ## Pipeline completo (todas as fontes)
	$(PY) -m datalake.cli run

ingest:          ## Origem -> bronze
	$(PY) -m datalake.cli ingest

silver:          ## Bronze -> silver
	$(PY) -m datalake.cli silver

gold:            ## Silver -> gold
	$(PY) -m datalake.cli gold

quality:         ## Testes de qualidade
	$(PY) -m datalake.cli quality

catalog:         ## Atualiza data/lake.duckdb
	$(PY) -m datalake.cli catalog

state:           ## Watermarks e ultimas execucoes
	$(PY) -m datalake.cli state

test:            ## Roda os testes
	$(PY) -m pytest

clean:           ## Apaga dados e logs (mantem a configuracao)
	rm -rf data logs
