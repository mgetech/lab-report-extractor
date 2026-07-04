using Dapper;
using LabReportExtractor.Api.Data;
using Npgsql;

DefaultTypeMap.MatchNamesWithUnderscores = true;

var builder = WebApplication.CreateBuilder(args);

builder.Services.AddNpgsqlDataSource(PostgresConnectionStringBuilder.Build(builder.Configuration));
builder.Services.AddScoped<LabReportRepository>();

var app = builder.Build();

_ = DbInitializer.InitializeAsync(app.Services.GetRequiredService<NpgsqlDataSource>(), app.Logger);

app.MapGet("/health", () => Results.Ok(new { status = "healthy" }))
    .WithName("GetHealth");

app.Run();
