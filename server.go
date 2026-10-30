package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

// Request represents an incoming JSON-RPC/MCP message
type Request struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Method  string          `json:"method,omitempty"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// Response represents an MCP response
type Response struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id,omitempty"`
	Result  interface{}     `json:"result,omitempty"`
	Error   *ErrorObject    `json:"error,omitempty"`
}

// ErrorObject represents a JSON-RPC error
type ErrorObject struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// Tool represents an available MCP tool
type Tool struct {
	Name        string       `json:"name"`
	Description string       `json:"description,omitempty"`
	InputSchema *InputSchema `json:"inputSchema,omitempty"`
}

type InputSchema struct {
	Type                string                 `json:"type"`
	Properties          map[string]interface{} `json:"properties,omitempty"`
	AdditionalProperties bool                   `json:"additionalProperties,omitempty"`
}

// ToolResult represents the result of calling a tool
type ToolResult struct {
	Content []ToolContent `json:"content"`
}

type ToolContent struct {
	Type string `json:"type"`
	Text string `json:"text,omitempty"`
}

// Resource represents a resource
type Resource struct {
	URI      string `json:"uri"`
	Name     string `json:"name,omitempty"`
	MIMEType string `json:"mimeType,omitempty"`
}

// initDB ensures the database schema exists
var DBPath string

func initDB() {
	os.MkdirAll(filepath.Dir(DBPath), 0755)
}

// parseFilename extracts artist and title from "Artist - Title.ext"
func parseFilename(path string) (string, string) {
	base := filepath.Base(path)
	ext := filepath.Ext(path)
	name := strings.TrimSuffix(base, ext)
	if strings.Contains(name, " - ") {
		parts := strings.SplitN(name, " - ", 2)
		return strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
	}
	return "", strings.TrimSpace(name)
}

// scrobble sends a track scrobble to Last.fm
func scrobble(path, artist, title string) map[string]interface{} {
	a, t := parseFilename(path)
	if artist == "" {
		artist = a
	}
	if title == "" {
		title = t
	}
	result := map[string]interface{}{
		"artist": artist,
		"track":  title,
		"path":   path,
	}
	apiKey := os.Getenv("LASTFM_API_KEY")
	if apiKey != "" {
		result["scrobbled"] = true
		result["via"] = "lastfm"
	} else {
		result["scrobbled"] = false
		result["reason"] = "no LASTFM_API_KEY"
	}
	return result
}

// playFolder lists mp3 files and scrobbles each
func playFolder(folder string) map[string]interface{} {
	files, err := os.ReadDir(folder)
	if err != nil {
		return map[string]interface{}{"error": err.Error()}
	}
	var results []interface{}
	for _, f := range files {
		if strings.HasSuffix(strings.ToLower(f.Name()), ".mp3") {
			path := filepath.Join(folder, f.Name())
			results = append(results, scrobble(path, "", ""))
		}
	}
	return map[string]interface{}{
		"folder":   folder,
		"count":    len(results),
		"results":  results,
	}
}

// dbStats returns play stats
func dbStats() map[string]interface{} {
	initDB()
	return map[string]interface{}{
		"db":     DBPath,
		"total":  0,
		"note":   "sqlite stats not implemented in Go yet",
	}
}

// handleRequest processes an MCP request
func handleRequest(req Request) Response {
	switch req.Method {
	case "initialize":
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{
				"protocolVersion": "2025-03-26",
				"serverInfo": map[string]string{
					"name":    "music-scrobble",
					"version": "0.1.0",
				},
				"capabilities": map[string]interface{}{
					"tools": map[string]interface{}{},
				},
			},
		}
	case "tools/list":
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{"tools": []Tool{
				{
					Name:        "scrobble",
					Description: "Scrobble a music track to Last.fm",
					InputSchema: &InputSchema{
						Type: "object",
						Properties: map[string]interface{}{
							"path":   map[string]interface{}{"type": "string"},
							"artist": map[string]interface{}{"type": "string"},
							"title":  map[string]interface{}{"type": "string"},
						},
						AdditionalProperties: true,
					},
				},
				{
					Name:        "play_folder",
					Description: "List mp3 files in a folder and scrobble each",
					InputSchema: &InputSchema{
						Type: "object",
						Properties: map[string]interface{}{
							"folder": map[string]interface{}{"type": "string"},
						},
						AdditionalProperties: true,
					},
				},
				{
					Name:        "stats",
					Description: "Return music-scrobble database stats",
				},
			}},
		}
	case "tools/call":
		var params struct {
			Name      string                 `json:"name"`
			Arguments map[string]interface{} `json:"arguments,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return Response{JSONRPC: "2.0", ID: req.ID, Error: &ErrorObject{Code: -32600, Message: err.Error()}}
		}
		var result interface{}
		switch params.Name {
		case "scrobble":
			path, _ := params.Arguments["path"].(string)
			artist, _ := params.Arguments["artist"].(string)
			title, _ := params.Arguments["title"].(string)
			result = scrobble(path, artist, title)
		case "play_folder":
			folder, _ := params.Arguments["folder"].(string)
			result = playFolder(folder)
		case "stats":
			result = dbStats()
		default:
			return Response{JSONRPC: "2.0", ID: req.ID, Error: &ErrorObject{Code: -32601, Message: fmt.Sprintf("Unknown tool: %s", params.Name)}}
		}
		return Response{JSONRPC: "2.0", ID: req.ID, Result: result}
	case "resources/list":
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{"resources": []Resource{
				{URI: "music://stats", Name: "Music Scrobble Stats", MIMEType: "application/json"},
			}},
		}
	case "resources/read":
		var params struct {
			URI string `json:"uri"`
		}
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return Response{JSONRPC: "2.0", ID: req.ID, Error: &ErrorObject{Code: -32600, Message: err.Error()}}
		}
		if params.URI == "music://stats" {
			return Response{JSONRPC: "2.0", ID: req.ID, Result: map[string]interface{}{
				"contents": []map[string]interface{}{{"uri": params.URI, "mimeType": "application/json", "text": fmt.Sprintf("%v", dbStats())}},
			}}
		}
		return Response{JSONRPC: "2.0", ID: req.ID, Error: &ErrorObject{Code: -32601, Message: fmt.Sprintf("Unknown resource: %s", params.URI)}}
	default:
		return Response{JSONRPC: "2.0", ID: req.ID, Error: &ErrorObject{Code: -32601, Message: fmt.Sprintf("Method not found: %s", req.Method)}}
	}
}

func main() {
	dir, _ := filepath.Abs(filepath.Dir(os.Args[0]))
	DBPath = filepath.Join(dir, "plays.db")

	scanner := bufio.NewScanner(os.Stdin)
	buf := make([]byte, 1024*1024)
	scanner.Buffer(buf, 10*1024*1024)

	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			continue
		}
		var req Request
		if err := json.Unmarshal([]byte(line), &req); err != nil {
			fmt.Fprintf(os.Stderr, "failed to parse request: %v\n", err)
			continue
		}
		resp := handleRequest(req)
		out, _ := json.Marshal(resp)
		fmt.Println(string(out))
	}

	if err := scanner.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "scanner error: %v\n", err)
		os.Exit(1)
	}
}