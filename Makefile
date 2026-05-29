.PHONY: lint-heavy test-full clean

UV ?= uv

# `LINT_HEAVY_CI=1` switches local-autofix targets into check-only mode (for CI:
# `ruff format --check`, `ruff check` without `--fix`). Don't set it locally — the
# default keeps `format` mutating the working tree + safe autofixes.
LINT_HEAVY_CI ?=
ifeq ($(LINT_HEAVY_CI),1)
RUFF_FORMAT_FLAGS := --check
RUFF_CHECK_FLAGS  :=
else
RUFF_FORMAT_FLAGS :=
RUFF_CHECK_FLAGS  := --fix
endif

# `lint-heavy` runs ruff format + ruff check + pyright. Local default applies safe
# autofixes; CI sets `LINT_HEAVY_CI=1` for check-only behavior (same target, same
# semantics, no mutations).
lint-heavy:
	@set -e; \
	echo "=== ruff format ==="; \
	$(UV) run ruff format $(RUFF_FORMAT_FLAGS) src tests; \
	echo ""; \
	echo "=== ruff check ==="; \
	$(UV) run ruff check $(RUFF_CHECK_FLAGS) src tests; \
	echo ""; \
	echo "=== pyright ==="; \
	$(UV) run pyright

# Unit suite — network-free: platform normalization, asset-matching heuristics,
# manifest parsing, engine path helpers. (Live `add`/`run` hit GitHub by design.)
test-full:
	$(UV) run pytest -q

# Remove pyc/__pycache__ and tool caches.
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .ruff_cache .pytest_cache
