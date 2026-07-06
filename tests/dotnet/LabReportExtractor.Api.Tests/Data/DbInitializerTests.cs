using LabReportExtractor.Api.Data;
using LabReportExtractor.Api.Models;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging.Abstractions;

namespace LabReportExtractor.Api.Tests.Data;

[Collection(PostgresCollection.Name)]
public sealed class DbInitializerTests(PostgresFixture postgres)
{
    [Fact]
    public async Task InitializeAsync_CreatesUsableSchema_WhenPostgresReachable()
    {
        await using var context = new LabReportDbContext(new DbContextOptionsBuilder<LabReportDbContext>()
            .UseNpgsql(postgres.ConnectionString)
            .UseSnakeCaseNamingConvention()
            .Options);
        await context.Database.EnsureDeletedAsync();

        await DbInitializer.InitializeAsync(context, NullLogger.Instance);

        var repository = new LabReportRepository(context);
        var id = await repository.InsertAsync(new LabReport
        {
            SourceFile = "report.pdf",
            ExtractionModel = "gpt-5-mini",
            ExtractedAt = DateTimeOffset.UtcNow,
            NeedsReview = false,
            Patient = new Patient { PatientId = "P-1", Name = "Schema Check" },
        });

        Assert.NotEqual(0, id);
    }

    [Fact]
    public async Task InitializeAsync_DoesNotThrow_WhenPostgresUnreachable()
    {
        await using var context = new LabReportDbContext(new DbContextOptionsBuilder<LabReportDbContext>()
            .UseNpgsql("Host=unreachable-host;Port=5432;Database=nope;Username=nope;Password=nope;Timeout=1")
            .UseSnakeCaseNamingConvention()
            .Options);

        await DbInitializer.InitializeAsync(context, NullLogger.Instance);
    }
}