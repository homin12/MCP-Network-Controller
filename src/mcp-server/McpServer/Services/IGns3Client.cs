using McpServer.Models;

namespace McpServer.Services;

public interface IGns3Client
{
    Task<List<Gns3Node>> GetProjectNodesAsync(string projectId);
    Task<string> ExecuteCommandAsync(string projectId, string nodeId, string command);
    Task<string> ExecuteCommandOnDeviceAsync(string projectId, string deviceName, string command);
}