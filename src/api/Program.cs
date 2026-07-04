using LabReportExtractor.Api.Data;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddDbContext<LabReportDbContext>(options => options
    .UseNpgsql(PostgresConnectionStringBuilder.Build(builder.Configuration))
    .UseSnakeCaseNamingConvention());
builder.Services.AddScoped<LabReportRepository>();

var app = builder.Build();

_ = InitializeDatabaseAsync(app.Services, app.Logger);

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }))
    .WithName("GetHealth");

app.Run();

static async Task InitializeDatabaseAsync(IServiceProvider services, ILogger logger)
{
    await using var scope = services.CreateAsyncScope();
    await DbInitializer.InitializeAsync(scope.ServiceProvider.GetRequiredService<LabReportDbContext>(), logger);
}