.PHONY: doctor dev stop test test-fast eval clean migrate migration

JWT_SECRET ?= $(shell cat /tmp/lnu_dev_jwt_secret 2>/dev/null)

doctor:
	bash scripts/doctor.sh

migrate:
	cd backend && JWT_SECRET="$(JWT_SECRET)" alembic upgrade head

# 用法：make migration m="add table xxx"
migration:
	cd backend && JWT_SECRET="$(JWT_SECRET)" alembic revision --autogenerate -m "$(m)"

dev:
	bash scripts/dev.sh

stop:
	bash scripts/stop.sh

test:
	cd backend && python3 -m pytest -q

test-fast:
	cd backend && python3 -m pytest tests/test_database.py tests/test_bm25_index.py tests/test_memory_service.py tests/test_prompt_engineering.py -q

eval:
	@echo "[eval] W4 交付：一键评测（60 golden + 6 组消融）"

clean:
	rm -rf .logs
