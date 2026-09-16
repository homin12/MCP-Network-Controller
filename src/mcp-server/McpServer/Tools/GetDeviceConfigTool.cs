using System.ComponentModel;
using System.Text.Json;
using McpServer.Models;
using McpServer.Services;
using Microsoft.Extensions.Logging;
using ModelContextProtocol;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

/// <summary>
/// Инструмент для получения конфигурации устройства в GNS3.
/// </summary>
[McpServerToolType]
public class GetDeviceConfigTool
{
    private readonly IGns3Client _gns3Client;
    private readonly ILogger<GetDeviceConfigTool> _logger;

    public GetDeviceConfigTool(IGns3Client gns3Client, ILogger<GetDeviceConfigTool> logger)
    {
        _gns3Client = gns3Client;
        _logger = logger;
    }

    [McpServerTool(Name = "get_device_config")]
    [Description("Получает текущий running-config устройства через GNS3 API.")]
    public async Task<IEnumerable<ContentBlock>> GetDeviceConfigAsync(
        [Description("ID проекта в GNS3")] string projectId,
        [Description("ID узла (node_id) в GNS3")] string nodeId)
    {
        _logger.LogInformation("Exec get_device_config for NodeId: {NodeId} in project {ProjectId}", nodeId, projectId);

        try
        {
            var output = await _gns3Client.ExecuteCommandAsync(projectId, nodeId, "show running-config");

            var config = ExtractRunningConfig(output);

            var result = new
            {
                node_id = nodeId,
                config = config,
                raw_output = output,
                success = true
            };

            var json = JsonSerializer.Serialize(result, new JsonSerializerOptions
            {
                WriteIndented = true
            });

            return [
                new TextContentBlock
                {
                    Text = json
                }
            ];
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error while executing get_device_config for {NodeId}", nodeId);

            var errorResult = new
            {
                node_id = nodeId,
                success = false,
                error = ex.Message
            };

            var json = JsonSerializer.Serialize(errorResult, new JsonSerializerOptions
            {
                WriteIndented = true
            });

            return [
                new TextContentBlock
                {
                    Text = json
                }
            ];
        }
    }

    private string ExtractRunningConfig(string output)
    {
        if (string.IsNullOrEmpty(output)) return "!\n";

        var lines = output.Split(new[] { "\r\n", "\r", "\n" }, StringSplitOptions.None);
        var configLines = new List<string>();
        bool inConfig = false;

        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i].Trim();

            if (line.Contains("Current configuration") || line.Contains("Building configuration"))
            {
                inConfig = true;
                continue;
            }

            if (inConfig && (line.Equals("end") || line.Equals("! end")))
            {
                configLines.Add("end");
                break;
            }

            if (inConfig)
            {
                configLines.Add(lines[i]);
            }
        }

        if (configLines.Count == 0)
        {
            return output;
        }

        return string.Join("\n", configLines);
    }
}
