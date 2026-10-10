.PHONY: bootstrap format lint unit integration bdd security eval ui ui-install up seed demo down clean verify

bootstrap format lint unit integration bdd security eval ui ui-install up seed demo down clean verify:
	uv run poe $@

# uv must use this repo's .venv, not another project's activated virtualenv.
unexport VIRTUAL_ENV
