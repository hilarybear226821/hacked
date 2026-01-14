# Makefile for Wireles Security Scanner C Modules
# Builds shared libraries for Python integration

CC = gcc
CFLAGS = -Wall -Wextra -O2 -fPIC -std=c99
LDFLAGS = -shared

# Libraries
TARGET_SUBGHZ = libsubghz_protocols.so
TARGET_MITM = libmitm_packet.so
TARGET_SWEEP = hackrf_sweep

# Sources
SRCS_SUBGHZ = subghz_protocols.c
SRCS_MITM = libmitm_packet.c
SRCS_SWEEP = hackrf_sweep.c

OBJS_SUBGHZ = $(SRCS_SUBGHZ:.c=.o)
OBJS_MITM = $(SRCS_MITM:.c=.o)

# Build all
all: $(TARGET_SUBGHZ) $(TARGET_MITM) $(TARGET_SWEEP)

# SubGHz Protocol Decoder
$(TARGET_SUBGHZ): $(OBJS_SUBGHZ)
	$(CC) $(LDFLAGS) -o $@ $^
	@echo "✓ Built $(TARGET_SUBGHZ)"

# MITM Packet Processor
$(TARGET_MITM): $(OBJS_MITM)
	$(CC) $(LDFLAGS) -o $@ $^
	@echo "✓ Built $(TARGET_MITM)"

# HackRF Sweep
$(TARGET_SWEEP): $(SRCS_SWEEP) $(SRCS_SUBGHZ)
	$(CC) $(CFLAGS) -o $@ $^ -lhackrf -lm
	@echo "✓ Built $(TARGET_SWEEP)"

# Pattern rule for objects
%.o: %.c
	$(CC) $(CFLAGS) -c $< -o $@

# Test programs
test: test_decoder
	./test_decoder

test_decoder: test_decoder.c $(TARGET_SUBGHZ)
	$(CC) $(CFLAGS) -o $@ $< -L. -lsubghz_protocols
	@echo "✓ Built test_decoder"

# Cleanup
clean:
	rm -f *.o *.so test_decoder hackrf_sweep
	@echo "✓ Cleaned build artifacts"

.PHONY: all clean test
