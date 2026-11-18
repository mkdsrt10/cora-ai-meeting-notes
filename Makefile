# Cora developer entry points. Run `make setup` once on a fresh Mac.
SWIFTC ?= swiftc
# Deployment target must match LSMinimumSystemVersion in package.json: without it swiftc links
# against the build Mac's OS and the helper aborts at load on any older macOS (dyld "Symbol not found").
MACOS_MIN ?= 14.0
SWIFT_FLAGS ?= -O -target arm64-apple-macos$(MACOS_MIN)
NATIVE := capture/dual-capture capture/mic-watch capture/speaker-watch bin/mac-ocr

.PHONY: setup build-native dev lint test clean install-app app

setup:
	./scripts/bootstrap.sh

build-native: $(NATIVE)

capture/dual-capture: capture/DualCapture.swift
capture/mic-watch: capture/MicWatcher.swift
capture/speaker-watch: capture/SpeakerWatcher.swift
# The live-call snippet shared with src/meeting-detector.js is generated into
# SpeakerWatcher.swift (see scripts/gen-live-call-snippet.js); regenerate it first.
capture/SpeakerWatcher.swift: capture/live-call-snippet.js scripts/gen-live-call-snippet.js
	node scripts/gen-live-call-snippet.js
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
	npx --no-install eslint src test/js
	node scripts/lint-ui.js

test:
	uv run pytest -m "not mlx"
	npm run --silent test:js

clean:
	rm -f $(NATIVE)
