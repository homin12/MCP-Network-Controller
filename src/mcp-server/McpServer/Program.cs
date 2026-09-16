using McpServer.Services;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using ModelContextProtocol;
using Serilog;
using ModelContextProtocol.AspNetCore;
using Microsoft.AspNetCore.Server.Kestrel.Core;

class Program
{
    static async Task Main(string[] args)
    {
        try
        {
            Log.Information("Startup MCP server...");

            var builder = WebApplication.CreateBuilder(args);

            builder.WebHost.ConfigureKestrel(options =>
            {
                options.ListenAnyIP(5000, listenOptions =>
                {
                    listenOptions.Protocols = HttpProtocols.Http1AndHttp2;
                });
            });

            Log.Logger = new LoggerConfiguration()
                .WriteTo.Console(outputTemplate: "[{Timestamp:HH:mm:ss} {Level:u3}] {Message:lj}{NewLine}{Exception}")
                .CreateLogger();

            builder.Logging.ClearProviders();
            builder.Logging.AddSerilog();

            builder.Services.AddHttpClient<IGns3Client, Gns3Client>(client =>
            {
                var baseUrl = Environment.GetEnvironmentVariable("Gns3__BaseUrl");

                if (string.IsNullOrEmpty(baseUrl))
                {
                    baseUrl = Environment.GetEnvironmentVariable("GNS3_BASEURL");
                }

                if (string.IsNullOrEmpty(baseUrl))
                {
                    baseUrl = builder.Configuration["Gns3:BaseUrl"];
                }

                // Temporary
                if (string.IsNullOrEmpty(baseUrl))
                {
                    baseUrl = "http://docker.internal";
                }

                client.BaseAddress = new Uri(baseUrl);
                // Temporary
                client.BaseAddress = new Uri("http://host.docker.internal:3080"); 

                client.Timeout = TimeSpan.FromSeconds(60);
            });

            builder.Services
                .AddMcpServer()
                .WithHttpTransport(options =>
                {
                    options.Stateless = false; // Stateful mode for SSE.
                })
                .WithToolsFromAssembly()
                .WithResourcesFromAssembly()
                .WithPromptsFromAssembly();

            builder.Services.AddHealthChecks();

            var app = builder.Build();

            app.MapHealthChecks("/health");
            app.MapMcp("/mcp");

            Log.Information("MCP server is running...");

            await app.RunAsync();
        }
        catch (Exception ex)
        {
            Log.Fatal(ex, "Fatal error while startup");
            throw;
        }
        finally
        {
            Log.CloseAndFlush();
        }
    }
}
