# Build the user guide.  `make` for the PDF, `make figures` to regenerate the
# plots from the flight logs first, `make clean` to remove LaTeX droppings.
#
# The pulse logs live outside this repository, under FLIGHT_TESTING_DATA. If
# yours are elsewhere, pass them through:  make figures LOGS="day5.csv day8.csv"

PYTHON ?= ../python/.venv/bin/python
LOGS   ?=

pulseplotter-guide.pdf: pulseplotter-guide.tex $(wildcard figures/*)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $<

.PHONY: figures clean all
all: figures pulseplotter-guide.pdf

figures:
	$(PYTHON) make_figures.py $(LOGS)

clean:
	latexmk -C
