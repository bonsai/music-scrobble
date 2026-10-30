from mcp.server.fastmcp import FastMCP
mcp = FastMCP("music-scrobble")
@mcp.tool()
def scrobble(path, artist, title):
    return "scrobbled"
if __name__ == "__main__": mcp.run()
