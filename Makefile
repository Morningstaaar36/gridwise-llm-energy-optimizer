# Cross-platform (GNU make on Linux, BSD make on macOS) — plain targets only.
CONDA_ENV ?= gridwise
PORT ?= 8000
IMAGE ?= ghcr.io/CHANGEME/gridwise
TAG ?= dev

setup:
	conda env create -f environment.yml || conda env update -f environment.yml --prune
	@echo "Now run: conda activate $(CONDA_ENV)"

lock:
	pip freeze --exclude-editable > requirements.lock.txt
	@echo "wrote requirements.lock.txt — commit it"

verify-env:
	python -c "import sys,numpy,scipy,fastapi,pydantic,openai;print('python',sys.version.split()[0]);print('numpy',numpy.__version__);print('scipy',scipy.__version__);print('fastapi',fastapi.__version__);print('pydantic',pydantic.__version__)"
	python -c "import json,glob;[json.load(open(f)) for f in glob.glob('schemas/*.json')+glob.glob('fixtures/*.json')];print('schemas+fixtures parse OK')"
	python evals/verify_lp.py

run:
	uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

test:
	pytest -q

health:
	curl -fsS http://localhost:$(PORT)/health

sample:
	python evals/run_public.py --base-url http://localhost:$(PORT)

docker-build:
	docker build -t $(IMAGE):$(TAG) .

docker-run:
	docker run --rm -p $(PORT):8000 --env-file .env $(IMAGE):$(TAG)

docker-push:
	docker push $(IMAGE):$(TAG)

lint:
	ruff check app tests evals
