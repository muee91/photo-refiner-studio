# Photo Refiner Studio

For any Photo Refiner request with at least one source photo available, use the `photoRefinerStudio` MCP server and call `open_photo_refiner_settings` before starting image generation or presenting a text settings menu. Continue only after the user submits the panel and a confirmation path is returned.

If the MCP server or `open_photo_refiner_settings` tool is unavailable, report that the Photo Refiner MCP failed to load instead of silently bypassing the panel.
