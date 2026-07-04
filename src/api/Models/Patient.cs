using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>Patient demographics, mirroring <c>schema.Patient</c> on the Python side.</summary>
public sealed record Patient
{
    /// <summary>Source-document patient identifier (synthetic — not a real MRN).</summary>
    [JsonPropertyName("patient_id")]
    public required string PatientId { get; init; }

    /// <summary>Patient name (synthetic).</summary>
    [JsonPropertyName("name")]
    public required string Name { get; init; }

    /// <summary>Date of birth, if present on the source document.</summary>
    [JsonPropertyName("dob")]
    public DateOnly? Dob { get; init; }

    /// <summary>Sex, if present on the source document.</summary>
    [JsonPropertyName("sex")]
    public Sex? Sex { get; init; }
}