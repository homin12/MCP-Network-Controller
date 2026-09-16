using System.ComponentModel;
using System.Text.Json;
using McpServer.Models;
using McpServer.Services;
using Microsoft.Extensions.Logging;
using ModelContextProtocol;
using ModelContextProtocol.Protocol;
using ModelContextProtocol.Server;

/// <summary>
/// Инструмент для применения конфигурации на устройствах.
/// </summary>
[McpServerToolType]
public class ConfigApplierTool
{
    private readonly IGns3Client _gns3Client;
    private readonly ILogger<ConfigApplierTool> _logger;

    public ConfigApplierTool(IGns3Client gns3Client, ILogger<ConfigApplierTool> logger)
    {
        _gns3Client = gns3Client;
        _logger = logger;
    }

    [McpServerTool(Name = "apply_config")]
    [Description("Применяет набор команд конфигурации к указанным устройствам в проекте GNS3.")]
    public async Task<IEnumerable<ContentBlock>> ApplyConfigAsync(
        [Description("Список команд для выполнения в формате: [{\"device\": \"R1\", \"cli\": \"show running-config\"}]")]
        DeviceCommand[] commands,
        [Description("ID проекта в GNS3")]
        string projectId)
    {
        _logger.LogInformation("Applying {CommandCount} commands to project {ProjectId}", commands.Length, projectId);

        var results = new List<CommandResult>();

        foreach (var cmd in commands)
        {
            _logger.LogInformation("Executing on {Device}: {Command}", cmd.Device, cmd.Cli);

            try
            {
                var output = await _gns3Client.ExecuteCommandOnDeviceAsync(
                    projectId,
                    cmd.Device,
                    cmd.Cli
                );

                results.Add(new CommandResult
                {
                    Device = cmd.Device,
                    Success = true,
                    Output = output,
                    Command = cmd.Cli
                });

                _logger.LogInformation("Successful on {Device}", cmd.Device);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Error on {Device}: {Error}", cmd.Device, ex.Message);

                results.Add(new CommandResult
                {
                    Device = cmd.Device,
                    Success = false,
                    Error = ex.Message,
                    Command = cmd.Cli
                });
            }
        }

        var summary = new
        {
            total = results.Count,
            success = results.Count(r => r.Success),
            failed = results.Count(r => !r.Success),
            results = results
        };

        var json = JsonSerializer.Serialize(summary, new JsonSerializerOptions
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
