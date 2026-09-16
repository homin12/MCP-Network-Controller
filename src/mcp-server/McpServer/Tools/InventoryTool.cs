using System.ComponentModel;
using System.Text.Json;
using System.Text.Json.Serialization;
using McpServer.Services;
using Microsoft.Extensions.Logging;
using ModelContextProtocol;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

[McpServerToolType]
public class InventoryTool
{
    private readonly IGns3Client _gns3Client;
    private readonly ILogger<InventoryTool> _logger;

    public InventoryTool(IGns3Client gns3Client, ILogger<InventoryTool> logger)
    {
        _gns3Client = gns3Client;
        _logger = logger;
    }

    [McpServerTool(Name = "get_inventory")]
    [Description("Возвращает список всех устройств в проекте GNS3 с их статусом и параметрами.")]
    public async Task<CallToolResult> GetInventoryAsync(
        [Description("ID проекта в GNS3 (например, 7d978888-d3c6-4e27-81ff-483304c84bc3)")]
        string projectId)
    {
        _logger.LogInformation("Exec get_inventory for project {ProjectId}", projectId);

        try
        {
            var nodes = await _gns3Client.GetProjectNodesAsync(projectId);

            var inventory = new
            {
                project_id = projectId,
                node_count = nodes.Count,
                nodes = nodes.Select(n => new
                {
                    name = n.Name,
                    type = n.Type,
                    status = n.Status,
                    console = n.Console,
                    node_id = n.NodeId
                })
            };

            var json = JsonSerializer.Serialize(inventory, new JsonSerializerOptions
            {
                WriteIndented = true
            });

            return new CallToolResult
            {
                IsError = false,
                Content = [new TextContentBlock { Text = json }]
            };
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error while executing get_inventory for project {ProjectId}", projectId);

            return new CallToolResult
            {
                IsError = true,
                Content = [new TextContentBlock { Text = $"Error: {ex.Message}" }]
            };
        }
    }
}

/// <summary>
/// Ответ MCP-инструмента.
/// </summary>
public record CallToolResult
{
    [JsonPropertyName("isError")]
    public bool IsError { get; init; }

    [JsonPropertyName("content")]
    public required List<ContentBlock> Content { get; init; }
}
