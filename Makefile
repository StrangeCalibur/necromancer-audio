.PHONY: build test release plan
PYTHON ?= python3

build:
	$(PYTHON) tools/build.py

test:
	$(PYTHON) tools/test.py

release:
	$(PYTHON) tools/release.py

plan:
	$(PYTHON) tools/install.py plan
