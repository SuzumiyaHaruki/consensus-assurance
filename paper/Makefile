LATEXMK ?= latexmk
TECTONIC ?= tectonic

.PHONY: all tectonic clean

all:
	mkdir -p build
	$(LATEXMK) -pdf -interaction=nonstopmode -halt-on-error -outdir=build main.tex

tectonic:
	mkdir -p build
	$(TECTONIC) --untrusted --reruns 2 --keep-logs --keep-intermediates --outdir build main.tex

clean:
	rm -f build/main.aux build/main.bbl build/main.blg build/main.fdb_latexmk build/main.fls build/main.log build/main.out build/main.synctex.gz
