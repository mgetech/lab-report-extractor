using LabReportExtractor.Api.Data;
using LabReportExtractor.Api.Models;
using Microsoft.EntityFrameworkCore;

namespace LabReportExtractor.Api.Tests.Data;

/// <summary>
/// Round-trips <see cref="LabReport"/> through a real Postgres to prove
/// <c>LabReportDbContext</c>'s owned-entity mapping actually works: <c>Patient</c> flattened via
/// <c>OwnsOne</c>, <c>Results</c> as their own table via <c>OwnsMany</c>, <c>Diagnoses</c> as a
/// JSONB column via <c>OwnsMany().ToJson()</c>.
/// </summary>
[Collection(PostgresCollection.Name)]
public sealed class LabReportRepositoryTests : IAsyncLifetime
{
    private readonly PostgresFixture _postgres;
    private LabReportDbContext _context = null!;

    public LabReportRepositoryTests(PostgresFixture postgres) => _postgres = postgres;

    public async Task InitializeAsync()
    {
        _context = CreateContext(_postgres.ConnectionString);
        await _context.Database.EnsureDeletedAsync();
        await _context.Database.EnsureCreatedAsync();
    }

    public Task DisposeAsync() => _context.DisposeAsync().AsTask();

    private static LabReportDbContext CreateContext(string connectionString) =>
        new(new DbContextOptionsBuilder<LabReportDbContext>()
            .UseNpgsql(connectionString)
            .UseSnakeCaseNamingConvention()
            .Options);

    private LabReportRepository Repository() => new(_context);

    /// <summary>A fresh context/repository proves the round trip came from Postgres, not EF's
    /// in-memory change tracker.</summary>
    private LabReportRepository FreshRepository(out LabReportDbContext context)
    {
        context = CreateContext(_postgres.ConnectionString);
        return new LabReportRepository(context);
    }

    private static LabReport NewReport(Patient patient, List<Result>? results = null, List<Diagnosis>? diagnoses = null) => new()
    {
        SourceFile = "report.pdf",
        ExtractionModel = "gpt-5-mini",
        ExtractedAt = DateTimeOffset.UtcNow,
        NeedsReview = false,
        Patient = patient,
        Results = results ?? [],
        Diagnoses = diagnoses ?? [],
    };

    [Fact]
    public async Task InsertAsync_ThenGetById_RoundTripsFullGraph()
    {
        var report = NewReport(
            patient: new Patient { PatientId = "P-100", Name = "Ada Lovelace", Dob = new DateOnly(1980, 1, 1), Sex = Sex.Female },
            results:
            [
                new Result
                {
                    Analyte = "Hemoglobin", Value = "14.2", Unit = "g/dL", RefRangeRaw = "13.5-17.5",
                    RefLow = 13.5, RefHigh = 17.5, PrintedFlag = Flag.Normal, ComputedFlag = Flag.Normal,
                    Confidence = 0.95, NeedsReview = false,
                },
                new Result
                {
                    Analyte = "Glucose", Value = "145", Unit = "mg/dL", RefRangeRaw = "70-100",
                    RefLow = 70, RefHigh = 100, PrintedFlag = Flag.Normal, ComputedFlag = Flag.High,
                    Confidence = 0.6, NeedsReview = true,
                },
            ],
            diagnoses: [new Diagnosis { Text = "Hyperglycemia, newly noted", Confidence = 0.8 }]);
        report = report with { NeedsReview = true };

        var id = await Repository().InsertAsync(report);

        var fetched = await FreshRepository(out var readContext).GetByIdAsync(id);
        await using var _ = readContext;

        Assert.NotNull(fetched);
        Assert.Equal("Ada Lovelace", fetched.Patient.Name);
        Assert.Equal(new DateOnly(1980, 1, 1), fetched.Patient.Dob);
        Assert.Equal(Sex.Female, fetched.Patient.Sex);
        Assert.Equal(2, fetched.Results.Count);

        var glucose = Assert.Single(fetched.Results, r => r.Analyte == "Glucose");
        Assert.Equal(Flag.Normal, glucose.PrintedFlag);
        Assert.Equal(Flag.High, glucose.ComputedFlag);
        Assert.Equal(70, glucose.RefLow);
        Assert.Equal(100, glucose.RefHigh);
        Assert.True(glucose.NeedsReview);

        var diagnosis = Assert.Single(fetched.Diagnoses);
        Assert.Equal("Hyperglycemia, newly noted", diagnosis.Text);
        Assert.Equal(0.8, diagnosis.Confidence);
    }

    [Fact]
    public async Task InsertAsync_ThenGetById_RoundTripsNullableFields()
    {
        var report = NewReport(
            patient: new Patient { PatientId = "P-101", Name = "Unknown Patient" },
            results: [new Result { Analyte = "TSH", Value = "2.1", Confidence = 0.9, NeedsReview = false }]);

        var id = await Repository().InsertAsync(report);

        var fetched = await FreshRepository(out var readContext).GetByIdAsync(id);
        await using var _ = readContext;

        Assert.NotNull(fetched);
        Assert.Null(fetched.Patient.Dob);
        Assert.Null(fetched.Patient.Sex);
        Assert.Null(fetched.ReportDate);
        Assert.Null(fetched.OrderingPhysician);

        var result = Assert.Single(fetched.Results);
        Assert.Null(result.Unit);
        Assert.Null(result.RefLow);
        Assert.Null(result.RefHigh);
        Assert.Null(result.PrintedFlag);
        Assert.Null(result.ComputedFlag);
    }

    [Fact]
    public async Task InsertAsync_EmptyResultsAndDiagnoses_RoundTrips()
    {
        var report = NewReport(patient: new Patient { PatientId = "P-102", Name = "No Results" });

        var id = await Repository().InsertAsync(report);

        var fetched = await FreshRepository(out var readContext).GetByIdAsync(id);
        await using var _ = readContext;

        Assert.NotNull(fetched);
        Assert.Empty(fetched.Results);
        Assert.Empty(fetched.Diagnoses);
    }

    [Fact]
    public async Task GetByIdAsync_UnknownId_ReturnsNull()
    {
        var fetched = await Repository().GetByIdAsync(999_999);

        Assert.Null(fetched);
    }

    [Fact]
    public async Task ListAsync_ReturnsNewestExtractedFirst()
    {
        var older = NewReport(new Patient { PatientId = "P-1", Name = "Older" }) with
        {
            ExtractedAt = DateTimeOffset.UtcNow.AddHours(-2),
        };
        var newer = NewReport(new Patient { PatientId = "P-2", Name = "Newer" }) with
        {
            ExtractedAt = DateTimeOffset.UtcNow,
        };
        await Repository().InsertAsync(older);
        await Repository().InsertAsync(newer);

        var summaries = await FreshRepository(out var readContext).ListAsync();
        await using var _ = readContext;

        Assert.Equal(["Newer", "Older"], summaries.Select(s => s.PatientName));
    }

    [Fact]
    public async Task ListAsync_FiltersByNeedsReview()
    {
        var flagged = NewReport(new Patient { PatientId = "P-3", Name = "Flagged" }) with { NeedsReview = true };
        var clean = NewReport(new Patient { PatientId = "P-4", Name = "Clean" }) with { NeedsReview = false };
        await Repository().InsertAsync(flagged);
        await Repository().InsertAsync(clean);

        var summaries = await FreshRepository(out var readContext).ListAsync(needsReview: true);
        await using var _ = readContext;

        var summary = Assert.Single(summaries);
        Assert.Equal("Flagged", summary.PatientName);
    }

    [Fact]
    public async Task ListAsync_ResultsNeedingReviewCount_CountsOnlyFlaggedResults()
    {
        var report = NewReport(
            patient: new Patient { PatientId = "P-5", Name = "Mixed Results" },
            results:
            [
                new Result { Analyte = "A", Value = "1", Confidence = 0.9, NeedsReview = false },
                new Result { Analyte = "B", Value = "2", Confidence = 0.5, NeedsReview = true },
                new Result { Analyte = "C", Value = "3", Confidence = 0.4, NeedsReview = true },
            ]);
        await Repository().InsertAsync(report);

        var summaries = await FreshRepository(out var readContext).ListAsync();
        await using var _ = readContext;

        var summary = Assert.Single(summaries);
        Assert.Equal(2, summary.ResultsNeedingReviewCount);
    }
}