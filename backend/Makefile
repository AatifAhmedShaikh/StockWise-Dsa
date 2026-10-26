# Builds the StockWise DSA engine as a shared library plus the C test program.
#   make        -> shared library (libstockwise.so / .dylib, or stockwise.dll on Windows)
#   make test   -> build and run the C tests
#   make clean

CC = gcc
CFLAGS ?= -std=c11 -O2 -Wall -Wextra -Wpedantic
SRCS = search.c hash_table.c sorting.c max_heap.c inventory_engine.c
HDRS = inventory_types.h

ifeq ($(OS),Windows_NT)
    LIB = stockwise.dll
    TEST_BIN = test_engine.exe
    RUN_TEST = test_engine.exe
    RM = del /Q
    LDLIBS = -static-libgcc
else
    UNAME := $(shell uname -s)
    ifeq ($(UNAME),Darwin)
        LIB = libstockwise.dylib
    else
        LIB = libstockwise.so
    endif
    TEST_BIN = test_engine
    RUN_TEST = ./test_engine
    RM = rm -f
    LDLIBS = -lm
    CFLAGS += -fPIC
endif

all: $(LIB)

$(LIB): $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) -shared -o $@ $(SRCS) $(LDLIBS)

$(TEST_BIN): tests/test_engine.c $(SRCS) $(HDRS)
	$(CC) $(CFLAGS) -I. -o $@ tests/test_engine.c $(SRCS) $(LDLIBS)

test: $(TEST_BIN)
	$(RUN_TEST)

clean:
	$(RM) $(LIB) $(TEST_BIN)

.PHONY: all test clean
