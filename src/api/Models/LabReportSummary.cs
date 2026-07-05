using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>
/// Lightweight row for <c>GET /documents</c> — the review queue listing. Deliberately omits
/// results/diagnoses; fetch <c>GET /documents/{id}</c> for the full record.
/// </summary>
public sealed record LabReportSummary
{
    [JsonPropertyName("id")]
    public required long Id { get; init; }

    [JsonPropertyName("patient_name")]
    public required string PatientName { get; init; }

    [JsonPropertyName("source_file")]
    public required string SourceFile { get; init; }

    [JsonPropertyName("report_date")]
    public DateOnly? ReportDate { get; init; }

    [JsonPropertyName("extracted_at")]
    public required DateTimeOffset ExtractedAt { get; init; }

    [JsonPropertyName("needs_review")]
    public required bool NeedsReview { get; init; }

    /// <summary>How many of this report's results are individually flagged for review.</summary>
    [JsonPropertyName("results_needing_review_count")]
    public required int ResultsNeedingReviewCount { get; init; }
}