.PHONY: build clean

BIN ?= music-scrobble

build:
	go build -o $(BIN).exe server.go

clean:
	rm -f $(BIN).exe