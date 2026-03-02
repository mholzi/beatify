# Beatify — Build Makefile
# Minifies JS and CSS assets for local testing.
# In CI, .min files are not tracked — source files are served directly.
#
# Usage:
#   make build    — minify all assets
#   make clean    — remove all .min files

WWW := custom_components/beatify/www
JS_FILES  := admin i18n utils player dashboard
CSS_FILES := styles dashboard

.PHONY: build clean

build: $(JS_FILES:%=$(WWW)/js/%.min.js) $(CSS_FILES:%=$(WWW)/css/%.min.css)
	@echo "✅ Build complete"

$(WWW)/js/%.min.js: $(WWW)/js/%.js
	@echo "  Minifying $<"
	@npx terser $< --compress --mangle --output $@

$(WWW)/css/%.min.css: $(WWW)/css/%.css
	@echo "  Minifying $<"
	@npx --yes clean-css-cli -o $@ $<

clean:
	@rm -f $(WWW)/js/*.min.js $(WWW)/css/*.min.css
	@echo "🧹 Cleaned .min files"
