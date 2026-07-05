using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>Free-text diagnosis line, mirroring <c>schema.Diagnosis</c> on the Python side.</summary>
public sealed record Diagnosis
{
    /// <summary>Diagnosis text as printed on the source document.</summary>
    [JsonPropertyName("text")]
    public required string Text { get; init; }

    /// <summary>Extraction confidence in [0, 1].</summary>
    [JsonPropertyName("confidence")]
    public required double Confidence { get; init; }
}