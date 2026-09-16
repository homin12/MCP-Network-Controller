using System.Text.Json.Serialization;

namespace McpServer.Models;

public class DeviceCommand
{
    [JsonPropertyName("device")]
    public string Device { get; set; } = string.Empty;

    [JsonPropertyName("cli")]
    public string Cli { get; set; } = string.Empty;
}