# Build the user guide.  `make` for the PDF, `make figures` to regenerate the
# plots from the flight logs first, `make clean` to remove LaTeX droppings.
#
# The pulse logs live outside this repository, under FLIGHT_TESTING_DATA. If
# yours are elsewhere, pass them through:  make figures LOGS="day5.csv day8.csv"

PYTHON ?= ../python/.venv/bin/python
LOGS   ?=

pulseplotter-guide.pdf: pulseplotter-guide.tex $(wildcard figures/*)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $<

# The field-review prototype report. Its figures and tables come from the
# validation script, which needs the logs and, for terrain, a network on
# first use (see ../python/dem.py).
fieldreview-prototype.pdf: fieldreview-prototype.tex $(wildcard figures/fieldreview-*)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $<

.PHONY: figures screenshots fieldreview-figures clean all
all: figures screenshots pulseplotter-guide.pdf fieldreview-figures fieldreview-prototype.pdf

figures:
	$(PYTHON) make_figures.py $(LOGS)

fieldreview-figures:
	$(PYTHON) ../python/validate_fieldreview.py

# macOS only, and needs Screen Recording permission. See make_screenshots.py.
screenshots:
	$(PYTHON) make_screenshots.py

clean:
	latexmk -C
