using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>A single lab result row, mirroring <c>schema.Result</c> on the Python side.</summary>
public sealed record Result
{
    /// <summary>Analyte name as printed — an open string, never a closed enum (synonyms vary by lab).</summary>
    [JsonPropertyName("analyte")]
    public required string Analyte { get; init; }

    /// <summary>Result value as printed (kept as a string — not every result is numeric).</summary>
    [JsonPropertyName("value")]
    public required string Value { get; init; }

    /// <summary>Unit as printed, if any.</summary>
    [JsonPropertyName("unit")]
    public string? Unit { get; init; }

    /// <summary>Reference range exactly as printed (e.g. "13.5-17.5", "&gt;40", "&lt;200").</summary>
    [JsonPropertyName("ref_range_raw")]
    public string? RefRangeRaw { get; init; }

    /// <summary>Parsed lower bound of the reference range, if resolvable.</summary>
    [JsonPropertyName("ref_low")]
    public double? RefLow { get; init; }

    /// <summary>Parsed upper bound of the reference range, if resolvable.</summary>
    [JsonPropertyName("ref_high")]
    public double? RefHigh { get; init; }

    /// <summary>Flag as printed on the source document.</summary>
    [JsonPropertyName("printed_flag")]
    public Flag? PrintedFlag { get; init; }

    /// <summary>Flag recomputed from value vs. reference range (the plausibility check).</summary>
    [JsonPropertyName("computed_flag")]
    public Flag? ComputedFlag { get; init; }

    /// <summary>Extraction confidence in [0, 1].</summary>
    [JsonPropertyName("confidence")]
    public required double Confidence { get; init; }

    /// <summary>True when confidence routing or the plausibility check flagged this result for human review.</summary>
    [JsonPropertyName("needs_review")]
    public required bool NeedsReview { get; init; }
}