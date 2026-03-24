.PHONY: lint test check

lint:
	ruff check src/

test:
	pytest tests/ -v --tb=short

check: lint test
	@echo "All checks passed"
