// +build ignore

package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// Request represents an incoming JSON-RPC request
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

type ErrorObject struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

// Tool represents an MCP tool
type Tool struct {
	Name        string      `json:"name"`
	Description string      `json:"description,omitempty"`
	InputSchema *InputSchema `json:"inputSchema,omitempty"`
}

type InputSchema struct {
	Type                 string                 `json:"type"`
	Properties           map[string]interface{} `json:"properties,omitempty"`
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

// Server state
type Server struct {
	Name            string
	Version         string
	HOUDINI_PATH    string
	HOUDINI_VERSION string
}

// getTools returns all available tools
func getTools() []Tool {
	return []Tool{
		{Name: "get_version", Description: "Houdini Engine version"},
		{Name: "check_install", Description: "Check Houdini installation status"},
		{Name: "list_dcc_plugins", Description: "List DCC plugins (Maya, Unity, Unreal, 3ds Max)"},
		{Name: "get_license_status", Description: "Get license status via sesictrl"},
		{Name: "get_install_path", Description: "Get Houdini installation path"},
	}
}

// getResources returns available resources
func getResources() []Resource {
	return []Resource{
		{URI: "houdini://install-info", Name: "Houdini Install Info", MIMEType: "application/json"},
		{URI: "houdini://license", Name: "Houdini License Status", MIMEType: "application/json"},
	}
}

// findHoudiniBinary searches for houdini executable
func findHoudiniBinary() string {
	candidates := []string{
		filepath.Join("C:\\Program Files\\Side Effects Software\\Houdini Engine\\Houdini", "bin", "houdini.exe"),
		filepath.Join("C:\\Program Files\\Side Effects Software\\Houdini Engine\\Houdini", "houdini.exe"),
		filepath.Join("C:\\Program Files\\Side Effects Software\\Houdini Engine\\Houdini", "bin", "houdini-bin.exe"),
	}
	for _, p := range candidates {
		if _, err := os.Stat(p); err == nil {
			return p
		}
	}
	return ""
}

// runCommand executes a shell command
func runCommand(name string, args ...string) (string, error) {
	cmd := exec.Command(name, args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("command failed: %w\n%s", err, string(output))
	}
	return strings.TrimSpace(string(output)), nil
}

// callTool executes a tool call
func callTool(server *Server, name string) (*ToolResult, error) {
	switch name {
	case "get_version":
		return &ToolResult{
			Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("Houdini Engine %s", server.HOUDINI_VERSION)}},
		}, nil
	case "check_install":
		binary := findHoudiniBinary()
		var status string
		if binary != "" {
			status = "✅ Houdini binary found"
		} else {
			status = "❌ Houdini not found"
		}
		return &ToolResult{
			Content: []ToolContent{
				{Type: "text", Text: fmt.Sprintf("%s\nPath: %s\nVersion: %s\nBinary: %s", status, server.HOUDINI_PATH, server.HOUDINI_VERSION, binary)},
			},
		}, nil
	case "list_dcc_plugins":
		dccDir := filepath.Clean(filepath.Join(server.HOUDINI_PATH, ".."))
		plugins := []string{"Maya", "Unity", "Unreal", "3ds Max"}
		var lines []string
		for _, p := range plugins {
			full := filepath.Join(dccDir, p)
			if _, err := os.Stat(full); err == nil {
				lines = append(lines, fmt.Sprintf("✅ %s", p))
			} else {
				lines = append(lines, fmt.Sprintf("❌ %s", p))
			}
		}
		return &ToolResult{
			Content: []ToolContent{{Type: "text", Text: strings.Join(lines, "\n")}},
		}, nil
	case "get_license_status":
		sesictrl := filepath.Join(server.HOUDINI_PATH, "bin", "sesictrl.exe")
		if _, err := os.Stat(sesictrl); err != nil {
			return &ToolResult{Content: []ToolContent{{Type: "text", Text: "❌ sesictrl not found"}}}, nil
		}
		out, err := runCommand(sesictrl, "-p")
		if err != nil {
			return &ToolResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("License check failed: %s", err)}}}, nil
		}
		return &ToolResult{Content: []ToolContent{{Type: "text", Text: out}}}, nil
	case "get_install_path":
		return &ToolResult{Content: []ToolContent{{Type: "text", Text: server.HOUDINI_PATH}}}, nil
	default:
		return &ToolResult{Content: []ToolContent{{Type: "text", Text: fmt.Sprintf("Unknown tool: %s", name)}}}, nil
	}
}

// readResource reads a resource
func readResource(server *Server, uri string) ([]byte, error) {
	switch uri {
	case "houdini://install-info":
		info := map[string]interface{}{
			"path":         server.HOUDINI_PATH,
			"version":      server.HOUDINI_VERSION,
			"binary":       findHoudiniBinary(),
			"hengine":      filepath.Join(server.HOUDINI_PATH, "bin", "hengine.exe"),
		}
		return json.Marshal(info)
	case "houdini://license":
		sesictrl := filepath.Join(server.HOUDINI_PATH, "bin", "sesictrl.exe")
		if _, err := os.Stat(sesictrl); err != nil {
			return []byte("License check failed: sesictrl not found"), nil
		}
		out, err := runCommand(sesictrl, "-p")
		if err != nil {
			return []byte(fmt.Sprintf("License check failed: %s", err)), nil
		}
		return []byte(out), nil
	default:
		return nil, fmt.Errorf("unknown resource: %s", uri)
	}
}

// Main handles JSON-RPC requests
func main() {
	server := &Server{
		Name:            "houdini-mcp",
		Version:         "0.1.0",
		HOUDINI_PATH:    "C:\\Program Files\\Side Effects Software\\Houdini Engine\\Houdini",
		HOUDINI_VERSION: "19.5.682",
	}

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

		resp := handleRequest(server, req)
		out, _ := json.Marshal(resp)
		fmt.Println(string(out))
	}

	if err := scanner.Err(); err != nil {
		fmt.Fprintf(os.Stderr, "scanner error: %v\n", err)
		os.Exit(1)
	}
}

func handleRequest(server *Server, req Request) Response {
	switch req.Method {
	case "initialize":
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{
				"protocolVersion": "2025-03-26",
				"serverInfo": map[string]string{
					"name":    server.Name,
					"version": server.Version,
				},
				"capabilities": map[string]interface{}{
					"tools":    map[string]interface{}{},
					"resources": map[string]interface{}{},
				},
			},
		}
	case "tools/list":
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result:  map[string]interface{}{"tools": getTools()},
		}
	case "tools/call":
		var params struct {
			Name      string                 `json:"name"`
			Arguments map[string]interface{} `json:"arguments,omitempty"`
		}
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return Response{
				JSONRPC: "2.0",
				ID:      req.ID,
				Error:   &ErrorObject{Code: -32600, Message: err.Error()},
			}
		}
		result, err := callTool(server, params.Name)
		if err != nil {
			return Response{
				JSONRPC: "2.0",
				ID:      req.ID,
				Error:   &ErrorObject{Code: -32600, Message: err.Error()},
			}
		}
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result:  result,
		}
	case "resources/list":
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result:  map[string]interface{}{"resources": getResources()},
		}
	case "resources/read":
		var params struct {
			URI string `json:"uri"`
		}
		if err := json.Unmarshal(req.Params, &params); err != nil {
			return Response{
				JSONRPC: "2.0",
				ID:      req.ID,
				Error:   &ErrorObject{Code: -32600, Message: err.Error()},
			}
		}
		res, err := readResource(server, params.URI)
		if err != nil {
			return Response{
				JSONRPC: "2.0",
				ID:      req.ID,
				Error:   &ErrorObject{Code: -32600, Message: err.Error()},
			}
		}
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Result: map[string]interface{}{
				"contents": []map[string]interface{}{
					{"uri": params.URI, "mimeType": "application/json", "text": string(res)},
				},
			},
		}
	default:
		return Response{
			JSONRPC: "2.0",
			ID:      req.ID,
			Error:   &ErrorObject{Code: -32601, Message: fmt.Sprintf("Method not found: %s", req.Method)},
		}
	}
}