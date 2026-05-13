.PHONY: run test help

# Detect macOS and prepend DYLD_FALLBACK_LIBRARY_PATH so WeasyPrint can
# dlopen libpango/libcairo/libgobject. Prefer Apple Silicon Homebrew prefix;
# fall back to Intel. On Linux this is a no-op (libs live in standard ld paths).
UNAME_S := $(shell uname -s)
ifeq ($(UNAME_S),Darwin)
  ifneq ($(wildcard /opt/homebrew/lib),)
    DYLD_PATH := /opt/homebrew/lib
  else
    DYLD_PATH := /usr/local/lib
  endif
  RUN_ENV := DYLD_FALLBACK_LIBRARY_PATH=$(DYLD_PATH)
endif

help:
	@echo "Available targets:"
	@echo "  make run    Run uvicorn with --reload on :8000 (auto-sets DYLD on macOS)"
	@echo "  make test   Run pytest (requires DATABASE_URL pointing at a migrated test DB)"

run:
	$(RUN_ENV) uv run uvicorn main:app --reload --port 8000

test:
	uv run pytest -q
