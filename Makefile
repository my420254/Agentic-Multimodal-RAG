.PHONY: doctor dev stop test test-fast eval clean

doctor:
	bash scripts/doctor.sh

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
