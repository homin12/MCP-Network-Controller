FROM mcr.microsoft.com/dotnet/sdk:9.0 AS build
WORKDIR /src

COPY McpServer.csproj ./
RUN dotnet restore

COPY . ./

RUN rm -rf bin/ obj/

RUN dotnet publish "McpServer.csproj" -c Release -o /app/publish /p:UseAppHost=false

FROM mcr.microsoft.com/dotnet/aspnet:9.0
WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY --from=build /app/publish .

ENV ASPNETCORE_URLS=http://+:5000
ENV ASPNETCORE_ENVIRONMENT=Docker

EXPOSE 5000

ENTRYPOINT ["dotnet", "McpServer.dll"]
