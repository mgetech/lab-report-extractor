using System.Net;
using System.Net.Http.Json;
using LabReportExtractor.Api.Data;
using LabReportExtractor.Api.Models;
using LabReportExtractor.Api.Services;
using LabReportExtractor.Api.Tests.Data;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;

namespace LabReportExtractor.Api.Tests;

/// <summary>
/// End-to-end tests for <c>/documents</c> through the real minimal-API pipeline (routing, model
/// binding, EF Core persistence) — everything <c>ExtractorClientTests</c> and
/// <c>LabReportRepositoryTests</c> exercise in isolation, wired together. The extractor is stubbed
/// (mirrors the Python-mocking convention); Postgres is real (via <see cref="PostgresFixture"/>).
/// </summary>
[Collection(PostgresCollection.Name)]
public sealed class DocumentsEndpointsTests : IAsyncLifetime
{
    private readonly PostgresFixture _postgres;
    private WebApplicationFactory<Program> _factory = null!;
    private HttpClient _client = null!;

    public DocumentsEndpointsTests(PostgresFixture postgres) => _postgres = postgres;

    public async Task InitializeAsync()
    {
        await using (var setupContext = CreateContext())
        {
            await setupContext.Database.EnsureDeletedAsync();
            await setupContext.Database.EnsureCreatedAsync();
        }

        _factory = new WebApplicationFactory<Program>().WithWebHostBuilder(builder =>
            builder.ConfigureServices(services =>
            {
                services.RemoveAll<DbContextOptions<LabReportDbContext>>();
                services.AddDbContext<LabReportDbContext>(options => options
                    .UseNpgsql(_postgres.ConnectionString)
                    .UseSnakeCaseNamingConvention());

                services.RemoveAll<ExtractorClient>();
                services.AddSingleton(new ExtractorClient(new HttpClient(new StubExtractorHandler())
                {
                    BaseAddress = new Uri("http://extractor.test"),
                }));
            }));

        _client = _factory.CreateClient();
    }

    public async Task DisposeAsync()
    {
        _client.Dispose();
        await _factory.DisposeAsync();
    }

    private LabReportDbContext CreateContext() =>
        new(new DbContextOptionsBuilder<LabReportDbContext>()
            .UseNpgsql(_postgres.ConnectionString)
            .UseSnakeCaseNamingConvention()
            .Options);

    private static HttpContent DocumentUpload()
    {
        var content = new MultipartFormDataContent();
        var fileContent = new ByteArrayContent("%PDF-1.4 fake content"u8.ToArray());
        fileContent.Headers.ContentType = new("application/pdf");
        content.Add(fileContent, "file", "report.pdf");
        return content;
    }

    [Fact]
    public async Task PostDocuments_ReturnsCreated_AndPersistsExtractedReport()
    {
        var response = await _client.PostAsync("/documents", DocumentUpload());

        Assert.Equal(HttpStatusCode.Created, response.StatusCode);
        Assert.NotNull(response.Headers.Location);

        var body = await response.Content.ReadFromJsonAsync<LabReport>();
        Assert.NotNull(body);
        Assert.NotNull(body.Id);
        Assert.Equal("Stub Patient", body.Patient.Name);

        var persisted = await CreateContext().LabReports.FindAsync(body.Id);
        Assert.NotNull(persisted);
    }

    [Fact]
    public async Task GetDocumentById_ReturnsNotFound_WhenMissing()
    {
        var response = await _client.GetAsync("/documents/999999");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task GetDocuments_FiltersByNeedsReview()
    {
        await using var context = CreateContext();
        var repository = new LabReportRepository(context);
        await repository.InsertAsync(new LabReport
        {
            SourceFile = "flagged.pdf",
            ExtractionModel = "gpt-5-mini",
            ExtractedAt = DateTimeOffset.UtcNow,
            NeedsReview = true,
            Patient = new Patient { PatientId = "P-1", Name = "Flagged" },
        });
        await repository.InsertAsync(new LabReport
        {
            SourceFile = "clean.pdf",
            ExtractionModel = "gpt-5-mini",
            ExtractedAt = DateTimeOffset.UtcNow,
            NeedsReview = false,
            Patient = new Patient { PatientId = "P-2", Name = "Clean" },
        });

        var response = await _client.GetAsync("/documents?needsReview=true");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        var summaries = await response.Content.ReadFromJsonAsync<List<LabReportSummary>>();
        var summary = Assert.Single(summaries!);
        Assert.Equal("Flagged", summary.PatientName);
    }

    private sealed class StubExtractorHandler : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var report = new LabReport
            {
                SourceFile = "report.pdf",
                ExtractionModel = "stub-model",
                ExtractedAt = DateTimeOffset.UtcNow,
                NeedsReview = true,
                Patient = new Patient { PatientId = "P-1", Name = "Stub Patient" },
                Results = [new Result { Analyte = "Glucose", Value = "145", Confidence = 0.5, NeedsReview = true }],
            };
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = JsonContent.Create(report) });
        }
    }
}