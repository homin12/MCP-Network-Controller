using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using McpServer.Models;
using System.Net.Sockets;

namespace McpServer.Services;

public class Gns3Client : IGns3Client
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<Gns3Client> _logger;

    public Gns3Client(HttpClient httpClient, ILogger<Gns3Client> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<List<Gns3Node>> GetProjectNodesAsync(string projectId)
    {
        try
        {
            var response = await _httpClient.GetAsync($"/v2/projects/{projectId}/nodes");
            response.EnsureSuccessStatusCode();

            var json = await response.Content.ReadAsStringAsync();
            var nodes = JsonSerializer.Deserialize<List<Gns3Node>>(json, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            _logger.LogInformation("Get {Count} devices from project {ProjectId}", nodes?.Count ?? 0, projectId);
            return nodes ?? new List<Gns3Node>();
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Error while collecting devices from project {ProjectId}", projectId);
            throw;
        }
    }


    public async Task<string> ExecuteCommandAsync(string projectId, string nodeId, string command)
    {
        var response = await _httpClient.GetAsync($"/v2/projects/{projectId}/nodes/{nodeId}");
        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync();
        var node = JsonSerializer.Deserialize<Gns3Node>(json, new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true
        });

        if (node?.Console == null)
        {
            throw new InvalidOperationException($"У узла {nodeId} отсутствует или отключен порт консоли.");
        }

        string gns3Host = _httpClient.BaseAddress?.Host ?? "127.0.0.1";
        int telnetPort = node.Console.Value;

        _logger.LogInformation("Connecting to Telnet console of device {Name} ({Host}:{Port})...", node.Name, gns3Host, telnetPort);

        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(15));

        try
        {
            using var tcpClient = new TcpClient();

            await tcpClient.ConnectAsync(gns3Host, telnetPort, cts.Token);

            using var stream = tcpClient.GetStream();

            stream.ReadTimeout = 2000;
            stream.WriteTimeout = 2000;

            var sb = new StringBuilder();
            byte[] buffer = new byte[4096];

            async Task ReadAvailableDataAsync()
            {
                await Task.Delay(300, cts.Token);

                while (stream.DataAvailable)
                {
                    int read = await stream.ReadAsync(buffer, 0, buffer.Length, cts.Token);
                    if (read == 0) break;

                    var cleanText = Encoding.UTF8.GetString(buffer, 0, read)
                        .Replace("\r", "");

                    sb.Append(cleanText);

                    await Task.Delay(50, cts.Token);
                }
            }

            byte[] enterBytes = Encoding.UTF8.GetBytes("\r\n");
            await stream.WriteAsync(enterBytes, 0, enterBytes.Length, cts.Token);

            // Очищаем стартовый буфер.
            await ReadAvailableDataAsync();
            sb.Clear();

            // Отправляем terminal length 0.
            if (command.Trim().Contains("show", StringComparison.OrdinalIgnoreCase))
            {
                byte[] pageDisableBytes = Encoding.UTF8.GetBytes("terminal length 0\r\n");
                await stream.WriteAsync(pageDisableBytes, 0, pageDisableBytes.Length, cts.Token);

                await ReadAvailableDataAsync();
                sb.Clear();
            }

            // Отправляем основную команду.
            byte[] commandBytes = Encoding.UTF8.GetBytes(command + "\r\n");
            await stream.WriteAsync(commandBytes, 0, commandBytes.Length, cts.Token);

            // Читаем результат выполнения команды.
            await Task.Delay(1500, cts.Token);
            await ReadAvailableDataAsync();

            string output = sb.ToString().Trim();

            if (string.IsNullOrEmpty(output))
            {
                _logger.LogWarning("Device {NodeId} return empty response.", nodeId);
                return "[Пустой ответ консоли]";
            }

            _logger.LogInformation("Command applied succesfully on  {NodeId}", nodeId);
            return output;
        }
        catch (OperationCanceledException)
        {
            _logger.LogError("Console timeout for {NodeId}", nodeId);
            return $"[Ошибка: Превышен таймаут ожидания ответа устройства]";
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "TCP/Telnet error on port {Port}", telnetPort);
            throw;
        }
    }



    public async Task<string> ExecuteCommandOnDeviceAsync(string projectId, string deviceName, string command)
    {
        var nodes = await GetProjectNodesAsync(projectId);
        var node = nodes.FirstOrDefault(n => n.Name.Equals(deviceName, StringComparison.OrdinalIgnoreCase));

        if (node == null)
        {
            throw new ArgumentException($"Устройство '{deviceName}' не найдено в проекте");
        }

        return await ExecuteCommandAsync(projectId, node.NodeId, command);
    }
}