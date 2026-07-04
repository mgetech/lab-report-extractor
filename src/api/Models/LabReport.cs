using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>
/// A fully structured, validated lab report — the record returned by the Python extractor's
/// <c>POST /extract</c> and persisted by this service. Mirrors <c>schema.LabReport</c>.
/// </summary>
public sealed record LabReport
{
    /// <summary>Database identity. Absent on a report fresh from the extractor; set once persisted.</summary>
    [JsonPropertyName("id")]
    public long? Id { get; init; }

    /// <summary>Original source file name/path as ingested.</summary>
    [JsonPropertyName("source_file")]
    public required string SourceFile { get; init; }

    /// <summary>Identifier of the model/deployment that produced this extraction (provenance).</summary>
    [JsonPropertyName("extraction_model")]
    public required string ExtractionModel { get; init; }

    /// <summary>Timestamp the extraction was performed (provenance).</summary>
    [JsonPropertyName("extracted_at")]
    public required DateTimeOffset ExtractedAt { get; init; }

    /// <summary>Report date as printed, if present.</summary>
    [JsonPropertyName("report_date")]
    public DateOnly? ReportDate { get; init; }

    /// <summary>Specimen collection date as printed, if present.</summary>
    [JsonPropertyName("collection_date")]
    public DateOnly? CollectionDate { get; init; }

    /// <summary>Ordering physician, if present.</summary>
    [JsonPropertyName("ordering_physician")]
    public string? OrderingPhysician { get; init; }

    /// <summary>Lab/facility name, if present.</summary>
    [JsonPropertyName("lab_name")]
    public string? LabName { get; init; }

    /// <summary>True when any result or the report itself needs human review.</summary>
    [JsonPropertyName("needs_review")]
    public required bool NeedsReview { get; init; }

    /// <summary>Patient demographics.</summary>
    [JsonPropertyName("patient")]
    public required Patient Patient { get; init; }

    /// <summary>Extracted result rows.</summary>
    [JsonPropertyName("results")]
    public IReadOnlyList<Result> Results { get; init; } = [];

    /// <summary>Extracted free-text diagnoses.</summary>
    [JsonPropertyName("diagnoses")]
    public IReadOnlyList<Diagnosis> Diagnoses { get; init; } = [];
}