using LabReportExtractor.Api.Data;
using LabReportExtractor.Api.Models;
using LabReportExtractor.Api.Services;
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddDbContext<LabReportDbContext>(options => options
    .UseNpgsql(PostgresConnectionStringBuilder.Build(builder.Configuration))
    .UseSnakeCaseNamingConvention());
builder.Services.AddScoped<LabReportRepository>();

builder.Services.AddHttpClient<ExtractorClient>(client =>
    client.BaseAddress = new Uri(builder.Configuration["EXTRACTOR_URL"] ?? "http://localhost:8000"));

var app = builder.Build();

_ = InitializeDatabaseAsync(app.Services, app.Logger);

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }))
    .WithName("GetHealth");

app.MapGet("/ready", async (LabReportDbContext db, ExtractorClient extractor, CancellationToken cancellationToken) =>
    {
        var problems = new List<string>();

        try
        {
            if (!await db.Database.CanConnectAsync(cancellationToken))
            {
                problems.Add("Postgres unreachable.");
            }
        }
        catch (Exception ex)
        {
            problems.Add($"Postgres unreachable: {ex.Message}");
        }

        try
        {
            await extractor.PingAsync(cancellationToken);
        }
        catch (Exception ex)
        {
            problems.Add($"Extractor unreachable: {ex.Message}");
        }

        return problems.Count == 0
            ? Results.Ok(new { status = "ready" })
            : Results.Problem(detail: string.Join(" ", problems), statusCode: StatusCodes.Status503ServiceUnavailable);
    })
    .WithName("GetReady");

app.MapPost("/documents", async (
        IFormFile file, ExtractorClient extractor, LabReportRepository repository, CancellationToken cancellationToken) =>
    {
        LabReport extracted;
        try
        {
            extracted = await extractor.ExtractAsync(file, cancellationToken);
        }
        catch (ExtractorRequestException ex)
        {
            return Results.Problem(detail: ex.Message, statusCode: ex.StatusCode);
        }

        var id = await repository.InsertAsync(extracted, cancellationToken);
        return Results.Created($"/documents/{id}", extracted with { Id = id });
    })
    .WithName("PostDocument")
    .DisableAntiforgery();

app.MapGet("/documents/{id:long}", async (long id, LabReportRepository repository, CancellationToken cancellationToken) =>
    {
        var report = await repository.GetByIdAsync(id, cancellationToken);
        return report is null ? Results.NotFound() : Results.Ok(report);
    })
    .WithName("GetDocument");

app.MapGet("/documents", async (bool? needsReview, LabReportRepository repository, CancellationToken cancellationToken) =>
        Results.Ok(await repository.ListAsync(needsReview, cancellationToken)))
    .WithName("ListDocuments");

app.Run();

static async Task InitializeDatabaseAsync(IServiceProvider services, ILogger logger)
{
    await using var scope = services.CreateAsyncScope();
    await DbInitializer.InitializeAsync(scope.ServiceProvider.GetRequiredService<LabReportDbContext>(), logger);
}