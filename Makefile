# Beatify — Build Makefile
# Minifies JS and CSS assets using esbuild.
#
# Usage:
#   make build    — minify all assets
#   make clean    — remove all .min files

WWW := custom_components/beatify/www

# Non-module JS files (minify individually)
JS_FILES := admin i18n utils dashboard analytics party-lights playlist-requests

# CSS files
CSS_FILES := styles dashboard analytics

.PHONY: build clean bundle

build: $(JS_FILES:%=$(WWW)/js/%.min.js) $(CSS_FILES:%=$(WWW)/css/%.min.css) bundle
	@echo "✅ Build complete"

# Bundle player ES modules into single file
bundle:
	@echo "  Bundling player modules"
	@npx esbuild $(WWW)/js/player-core.js --bundle --minify --format=esm --outfile=$(WWW)/js/player.bundle.min.js

$(WWW)/js/%.min.js: $(WWW)/js/%.js
	@echo "  Minifying $<"
	@npx esbuild $< --minify --outfile=$@

$(WWW)/css/%.min.css: $(WWW)/css/%.css
	@echo "  Minifying $<"
	@npx esbuild $< --minify --outfile=$@

clean:
	@rm -f $(WWW)/js/*.min.js $(WWW)/js/*.bundle.min.js $(WWW)/css/*.min.css
	@echo "🧹 Cleaned .min files"
