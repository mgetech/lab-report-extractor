using System.Text.Json.Serialization;

namespace LabReportExtractor.Api.Models;

/// <summary>Patient sex, mirroring <c>schema.Sex</c> on the Python side.</summary>
[JsonConverter(typeof(JsonStringEnumConverter<Sex>))]
public enum Sex
{
    [JsonStringEnumMemberName("M")]
    Male,

    [JsonStringEnumMemberName("F")]
    Female,

    [JsonStringEnumMemberName("O")]
    Other,

    [JsonStringEnumMemberName("U")]
    Unknown,
}