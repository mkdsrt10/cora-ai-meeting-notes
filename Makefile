# Cora developer entry points. Run `make setup` once on a fresh Mac.
SWIFTC ?= swiftc
SWIFT_FLAGS ?= -O
NATIVE := capture/dual-capture capture/mic-watch capture/speaker-watch bin/mac-ocr

.PHONY: setup build-native dev lint test clean install-app app

setup:
	./scripts/bootstrap.sh

build-native: $(NATIVE)

capture/dual-capture: capture/DualCapture.swift
capture/mic-watch: capture/MicWatcher.swift
capture/speaker-watch: capture/SpeakerWatcher.swift
bin/mac-ocr: bin/mac_ocr.swift

$(NATIVE):
	$(SWIFTC) $(SWIFT_FLAGS) -o $@ $<
	codesign --force --sign - $@

dev: build-native
	npm start

app:  ## build a self-contained .app and .dmg in dist/
	./scripts/build-app.sh

install-app:  ## refresh the code inside /Applications/Cora.app (quit it first)
	./scripts/install-app.sh

lint:
	uv run ruff check python plugins tools tests
	npx --no-install eslint src
	node scripts/lint-ui.js

test:
	uv run pytest -m "not mlx"

clean:
	rm -f $(NATIVE)
