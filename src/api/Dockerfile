FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY LabReportExtractor.Api.csproj ./
RUN dotnet restore

COPY . .
RUN dotnet publish -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0 AS final
WORKDIR /app
COPY --from=build /app ./

EXPOSE 8080
ENTRYPOINT ["dotnet", "LabReportExtractor.Api.dll"]